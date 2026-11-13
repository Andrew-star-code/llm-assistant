"""Подготовка ответа (§8.1): всё, что читается из БД до обращения к модели.

Одна короткая сессия БД: сообщение и активная ветка, сценарий (из БД на каждое сообщение — правка
админа действует сразу), модель и режим thinking, системный промпт, вложения, область поиска,
инструменты, история с прошлыми вызовами инструментов. Результат — ``Prepared``; дальше генерация
к БД до сохранения ответа не обращается.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.modules.admin import app_settings
from app.modules.chats.models import Chat, Message
from app.modules.chats.service import branch
from app.modules.completions.attachments import AttachmentsBlock, build_attachments, fit_attachments
from app.modules.completions.context import schemas_tokens
from app.modules.completions.prompt import (
    DEFAULT_CONTEXT,
    DEFAULT_RESERVE,
    PromptUser,
    ToolStep,
    Turn,
    system_prompt,
)
from app.modules.completions.state import (
    CHAT_ROLE,
    RESULT_PREVIEW_CHARS,
    Deps,
    GenerationResult,
)
from app.modules.files.service import chat_files
from app.modules.kb.models import KnowledgeBase
from app.modules.llm.registry import RequestPlan
from app.modules.llm.tokens import TokenCounter
from app.modules.moderation.policy import Policy, load_policy
from app.modules.rag.search import Scope
from app.modules.rag.service import (
    SourceBook,
    build_scope,
)
from app.modules.rbac import service as rbac
from app.modules.scenarios.models import Scenario
from app.modules.scenarios.service import now_text
from app.modules.scenarios.service import render_prompt as render_scenario
from app.modules.tools.base import Tool, ToolContext
from app.modules.tools.models import ToolCall
from app.modules.tools.registry import available_tools
from app.modules.users.models import User
from app.modules.users.service import address_of

# Обвязка блока знаний в промпте (вводный текст, заголовки фрагментов) — сверх самих фрагментов.
KNOWLEDGE_MARGIN = 300

HISTORY_CUT_NOTE = "\n[…результат сокращён в истории диалога]"


@dataclass(frozen=True)
class Prepared:
    """Снимок всего, что нужно шагам генерации после закрытия сессии БД."""

    question: str
    history: list[Turn]
    plan: RequestPlan
    counter: TokenCounter
    policy: Policy
    base_system: str  # базовые правила + пользователь + модерация + сценарий
    attachments: AttachmentsBlock
    scenario_code: str | None
    rag_mode: str
    scope: Scope
    tools: list[Tool]
    context: ToolContext
    chat_id: UUID
    parent_id: UUID | None
    user_id: UUID
    guard_block: list[str]
    overhead: int = 0  # токены описаний инструментов
    rag_budget: int = 0  # сколько токенов фрагментов авто-поиска поместится после вложений


def history_steps(calls: list[ToolCall], limit: int) -> tuple[ToolStep, ...]:
    """Вызовы инструментов прошлого ответа для истории (§8.1): что спрашивали и что получили.

    Только видимые вызовы цикла: скрытый репорт (§9.6) и шаг авто-поиска (итерация 0, не вызов
    модели) в историю не идут. Результат — сохранённое начало, не длиннее ``limit``.
    """
    steps = []
    for call in sorted(calls, key=lambda c: (c.iteration, c.created_at, c.call_id)):
        if call.visibility != "visible" or call.iteration < 1:
            continue
        result = call.result_preview or ""
        # Сохраняется только начало результата (4000 символов) — полный текст мог быть длиннее.
        cut = len(result) > limit or len(result) >= RESULT_PREVIEW_CHARS
        steps.append(
            ToolStep(
                iteration=call.iteration,
                call_id=call.call_id,
                name=call.tool,
                arguments=json.dumps(call.arguments or {}, ensure_ascii=False),
                result=result[:limit] + (HISTORY_CUT_NOTE if cut else ""),
            )
        )
    return tuple(steps)


async def load(db: AsyncSession, message_id: UUID) -> tuple[Message, Chat, User, list[Message]]:
    message = await db.get(Message, message_id)
    if message is None:
        raise LookupError(message_id)
    chat = await db.get(Chat, message.chat_id)
    user = await db.get(User, chat.user_id) if chat else None
    if chat is None or user is None:
        raise LookupError(message_id)
    all_messages = (
        await db.scalars(
            select(Message).where(Message.chat_id == chat.id, Message.deleted_at.is_(None))
        )
    ).all()
    return message, chat, user, branch(all_messages, message.parent_id)


async def load_history_steps(
    db: AsyncSession, message_ids: list[UUID], limit: int
) -> dict[UUID, tuple[ToolStep, ...]]:
    if not message_ids:
        return {}
    calls: dict[UUID, list[ToolCall]] = {}
    rows = await db.scalars(select(ToolCall).where(ToolCall.message_id.in_(message_ids)))
    for call in rows:
        calls.setdefault(call.message_id, []).append(call)
    return {
        message_id: steps
        for message_id, items in calls.items()
        if (steps := history_steps(items, limit))
    }


async def prepare(
    deps: Deps, db: AsyncSession, message_id: UUID, result: GenerationResult
) -> Prepared:
    """Читает всё нужное для ответа и фиксирует модель и режим в сообщении."""
    message, chat, user, chain = await load(db, message_id)
    result.user_id, result.chat_id = user.id, chat.id
    question = result.question = chain[-1].content if chain else ""
    past = [m for m in chain[:-1] if m.status in ("completed", "stopped") and m.content]
    history = [Turn(m.role, m.content) for m in past]  # type: ignore[arg-type]
    result.is_first_answer = chat.title is None
    # Сценарий — из БД на каждое сообщение: правка в админке действует сразу (§8.7).
    scenario = await db.get(Scenario, chat.scenario_id) if chat.scenario_id else None
    plan = deps.registry.plan(
        scenario.model_role if scenario else CHAT_ROLE, thinking=message.thinking
    )
    counter = TokenCounter(plan.endpoint.tokenizer)
    # Правки из админки «Настройки» (компания, обращение, промпт) — без перезапуска.
    effective = await app_settings.effective(db, deps.settings)
    base_override = await app_settings.system_prompt_override(db)
    prompt_user = PromptUser(
        full_name=user.full_name,
        title=user.title,
        department=user.department,
        address=address_of(user, effective),
    )
    # Вложения только сообщений текущей ветки: у отредактированного вопроса — свои.
    branch_ids = {m.id for m in chain}
    uploads = [
        f for f in await chat_files(db, chat.id, kind="upload") if f.message_id in branch_ids
    ]
    attachments = await build_attachments(
        uploads,
        storage=deps.storage,
        renderer=deps.renderer,
        settings=deps.settings,
        endpoint=plan.endpoint,
        counter=counter,
    )
    now = utcnow()
    enabled = await app_settings.enabled_tools(db, deps.settings)
    policy = load_policy(deps.settings.config_dir)
    base_system = system_prompt(
        deps.renderer, effective, prompt_user, now, base_template=base_override,
        moderation={
            "categories": [c.model_dump() for c in policy.categories],
            "refusal": policy.refusal,
            "self_harm_help": policy.self_harm_help,
            "report_tool": plan.endpoint.supports_tools
            and (enabled is None or "report_incident" in enabled),
        },
    )  # fmt: skip
    if scenario is not None:
        scenario_text = render_scenario(
            scenario,
            {
                "user": asdict(prompt_user),
                "company": effective.chat.company_name,
                "now": now_text(now, deps.settings.chat.timezone),
            },
        )
        base_system = "\n\n".join(x for x in (base_system, scenario_text) if x)
    roles = await rbac.user_roles(db, user.id)
    permissions = rbac.effective_permissions(
        roles, await rbac.permissions_for_roles(db, (r.role.id for r in roles))
    )
    rag_mode = scenario.rag_mode if scenario else deps.settings.rag.mode
    # Базы сценария сужают область поиска; пусто — все доступные пользователю.
    only_kb_ids = None
    if scenario is not None and scenario.knowledge_bases:
        only_kb_ids = list(
            (
                await db.scalars(
                    select(KnowledgeBase.id).where(KnowledgeBase.code.in_(scenario.knowledge_bases))
                )
            ).all()
        )
    scope = await build_scope(db, user.id, (r.role.id for r in roles), only_kb_ids=only_kb_ids)
    has_kb = bool(scope.kb_ids or scope.personal_kb_ids)
    # Инструменты: включены ∩ разрешены сценарием ∩ доступны ролям (§9.1).
    tools = (
        available_tools(
            enabled=enabled,
            scenario=scenario.tools if scenario else None,
            permissions=permissions,
            has_attachments=bool(attachments.files),
            has_knowledge=has_kb and rag_mode != "off",
            has_data=bool(deps.settings.data_gateway.url),
        )
        if plan.endpoint.supports_tools
        else []
    )
    # Бюджет системной части (§8.3): инструкции, инструменты и вопрос — как есть; вложения
    # ужимаются под остаток, авто-поиск получает то, что осталось после них. Иначе модель с
    # малым контекстом отказывала бы на любом сообщении с большим документом.
    budget = (plan.endpoint.context_length or DEFAULT_CONTEXT) - (
        plan.endpoint.max_output_tokens or DEFAULT_RESERVE
    )
    overhead = schemas_tokens(counter, [t.schema() for t in tools])
    room = (
        budget
        - overhead
        - counter.count_messages(
            [{"role": "system", "content": base_system}, {"role": "user", "content": question}]
        )
    )
    attachments = fit_attachments(
        attachments, limit=max(room, 0), renderer=deps.renderer, counter=counter
    )
    rag_budget = min(
        int((plan.endpoint.context_length or DEFAULT_CONTEXT) * deps.settings.rag.context_share),
        max(room - attachments.tokens - KNOWLEDGE_MARGIN, 0),
    )
    # Вложения ищутся вместе с базами, когда в промпте только их оглавление (§10.4).
    if attachments.mode == "outline":
        scope = replace(scope, attachment_ids=tuple(f.id for f in attachments.files))
    step_chars = deps.settings.tools.history_result_max_chars
    if tools and step_chars:
        # Прошлые вызовы инструментов — в историю: на уточняющий вопрос модель
        # отвечает по уже полученным данным, а не запрашивает их заново.
        steps = await load_history_steps(db, [m.id for m in past], step_chars)
        history = [
            Turn(t.role, t.content, steps.get(m.id, ())) for t, m in zip(history, past, strict=True)
        ]
    book = SourceBook()
    result.book = book
    context = ToolContext(
        user_id=user.id,
        permissions=permissions,
        chat_id=chat.id,
        message_id=message_id,
        attachments=attachments.files,
        services=deps.services,
        kb_scope=scope,
        sources=book,
    )
    chat_id, parent_id = chat.id, message.parent_id
    user_id = user.id
    guard_block = await app_settings.guard_block_categories(db)
    message.model = plan.endpoint.model
    message.thinking = plan.thinking
    # Роль, которую запросил пользователь (как при резервировании), а не модель
    # размышлений, на которую её может перенаправить реестр (§8.2).
    result.model_role = scenario.model_role if scenario else CHAT_ROLE
    result.thinking = plan.thinking
    await db.commit()
    return Prepared(
        question=question,
        history=history,
        plan=plan,
        counter=counter,
        policy=policy,
        base_system=base_system,
        attachments=attachments,
        scenario_code=scenario.code if scenario else None,
        rag_mode=rag_mode,
        scope=scope,
        tools=tools,
        context=context,
        chat_id=chat_id,
        parent_id=parent_id,
        user_id=user_id,
        guard_block=guard_block,
        overhead=overhead,
        rag_budget=rag_budget,
    )
