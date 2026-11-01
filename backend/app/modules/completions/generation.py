"""Генерация ответа (§2.2, §8): фоновая asyncio-задача на каждый ответ ассистента.

Шаги: сборка промпта (с вложениями, §9.3) → запрос к модели со стримингом → цикл инструментов
(§8.4) → дельты и события в Redis Stream → сохранение ответа, токенов, вызовов инструментов и
трассировки в Postgres → автозаголовок → ``message.end``.

* «Стоп» может попасть в любой процесс api: отмена — флаг ``gen:cancel:<id>`` в Redis; исполнитель
  проверяет его между чанками, закрывает запрос к модели и сохраняет частичный ответ (``stopped``).
* Остановка процесса: задачи отменяются и сохраняют ответ со статусом ``interrupted``; ответы,
  чьи исполнители умерли, помечает ``mark_orphaned_interrupted`` при старте.
"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

import openai
import structlog
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import log_capture
from app.core.config import Settings
from app.core.db import utcnow
from app.core.storage import Storage
from app.modules.admin import app_settings
from app.modules.chats.models import Chat, Message
from app.modules.chats.service import branch
from app.modules.completions.attachments import build_attachments
from app.modules.completions.prompt import (
    DEFAULT_CONTEXT,
    PromptRenderer,
    PromptUser,
    Turn,
    build_messages,
    system_prompt,
)
from app.modules.completions.streaming import (
    ALIVE_TTL_SECONDS,
    PROTOCOL_VERSION,
    EventWriter,
    alive_key,
    cancel_key,
)
from app.modules.files.service import chat_files
from app.modules.incidents.errors import report_exception
from app.modules.kb.models import KnowledgeBase
from app.modules.llm.registry import ModelRegistry
from app.modules.llm.stream import Delta, Finish, ToolCallDelta, Usage, parse_stream
from app.modules.llm.tokens import TokenCounter
from app.modules.rag.models import MessageSource
from app.modules.rag.search import Fragment
from app.modules.rag.service import (
    SourceBook,
    build_scope,
    cited_indexes,
    fragments_context,
    rewrite_query,
    run_search,
    source_card,
)
from app.modules.rag.service import Turn as RagTurn
from app.modules.rbac import service as rbac
from app.modules.scenarios.models import Scenario
from app.modules.scenarios.service import now_text
from app.modules.scenarios.service import render_prompt as render_scenario
from app.modules.tools.base import Services, ToolContext
from app.modules.tools.executor import ToolOutcome, execute, preview_label_params
from app.modules.tools.models import ToolCall
from app.modules.tools.registry import available_tools
from app.modules.users.models import User
from app.modules.users.service import address_of
from app.workers.dispatch import Dispatcher

log = structlog.stdlib.get_logger("app.completions")

CHAT_ROLE = "chat"
UTILITY_ROLE = "utility"
CANCEL_CHECK_INTERVAL = 0.2
TITLE_MAX_WORDS = 6
TITLE_MAX_CHARS = 80


@dataclass
class GenerationResult:
    content: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    status: str = "completed"
    finish_reason: str | None = None
    usage: Usage | None = None
    ttft_ms: int | None = None
    reasoning_started: float | None = None
    reasoning_ms: int | None = None
    error: dict[str, Any] | None = None
    tools: list[ToolOutcome] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    book: SourceBook | None = None

    def add_usage(self, usage: Usage) -> None:
        if self.usage is None:
            self.usage = usage
            return
        self.usage = Usage(
            prompt_tokens=self.usage.prompt_tokens + usage.prompt_tokens,
            completion_tokens=self.usage.completion_tokens + usage.completion_tokens,
            reasoning_tokens=(self.usage.reasoning_tokens or 0) + (usage.reasoning_tokens or 0),
        )


@dataclass
class PendingCall:
    id: str = ""
    name: str = ""
    arguments: str = ""


MAX_ITERATIONS_NOTE = (
    "\n\nНе удалось завершить ответ: превышено число шагов с инструментами. "
    "Попробуйте уточнить или разбить запрос."
)


def clean_title(raw: str) -> str | None:
    """Первые слова ответа служебной модели без кавычек, разметки и точки в конце."""
    line = next((ln for ln in raw.strip().splitlines() if ln.strip()), "")
    line = re.sub(r"^(заголовок|title)\s*:\s*", "", line.strip(), flags=re.IGNORECASE)
    line = line.strip(" \t\"'«»`*#.").strip()
    words = line.split()
    if not words:
        return None
    return " ".join(words[:TITLE_MAX_WORDS])[:TITLE_MAX_CHARS]


def fallback_title(message: str) -> str:
    words = message.split()
    title = " ".join(words[:TITLE_MAX_WORDS])[:TITLE_MAX_CHARS]
    return title + ("…" if len(words) > TITLE_MAX_WORDS else "")


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, openai.APIStatusError):
        retryable = exc.status_code >= 500 or exc.status_code == 429
        return {
            "code": f"model_http_{exc.status_code}",
            "message": "Модель вернула ошибку",
            "retryable": retryable,
        }
    if isinstance(exc, openai.APITimeoutError):
        return {"code": "model_timeout", "message": "Модель не ответила вовремя", "retryable": True}
    if isinstance(exc, openai.APIConnectionError):
        return {"code": "model_unavailable", "message": "Модель недоступна", "retryable": True}
    return {"code": "internal_error", "message": "Не удалось получить ответ", "retryable": True}


class GenerationManager:
    def __init__(
        self,
        *,
        settings: Settings,
        redis: Redis,
        sessions: async_sessionmaker[AsyncSession],
        registry: ModelRegistry,
        renderer: PromptRenderer,
        storage: Storage,
        dispatcher: Dispatcher,
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.sessions = sessions
        self.registry = registry
        self.renderer = renderer
        self.storage = storage
        self.services = Services(
            settings=settings,
            sessions=sessions,
            storage=storage,
            models=registry,
            dispatcher=dispatcher,
            redis=redis,
        )
        self.tasks: dict[UUID, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------ управление

    async def start(self, message_id: UUID) -> None:
        # Ключ живости ставится до запуска задачи: SSE-читатель, пришедший раньше первого
        # события, будет ждать, а не решит, что генерация умерла.
        await self.redis.set(alive_key(message_id), "1", ex=ALIVE_TTL_SECONDS)
        task = asyncio.create_task(self._run(message_id), name=f"generation:{message_id}")
        self.tasks[message_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(message_id, None))

    async def request_stop(self, message_id: UUID) -> None:
        await self.redis.set(cancel_key(message_id), "1", ex=ALIVE_TTL_SECONDS * 10)

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def mark_orphaned_interrupted(self) -> int:
        """При старте: ответы в статусе streaming без живого исполнителя → interrupted."""
        async with self.sessions() as db:
            rows = (await db.scalars(select(Message).where(Message.status == "streaming"))).all()
            count = 0
            for message in rows:
                if message.id in self.tasks or await self.redis.exists(alive_key(message.id)):
                    continue
                message.status = "interrupted"
                message.error = {"code": "interrupted", "message": "Генерация прервана"}
                count += 1
            await db.commit()
        if count:
            log.warning("completions.orphans_interrupted", count=count)
        return count

    # ------------------------------------------------------------------ генерация

    async def _keep_alive(self, message_id: UUID) -> None:
        while True:
            await self.redis.set(alive_key(message_id), "1", ex=ALIVE_TTL_SECONDS)
            await asyncio.sleep(ALIVE_TTL_SECONDS / 3)

    async def _load(
        self, db: AsyncSession, message_id: UUID
    ) -> tuple[Message, Chat, User, list[Message]]:
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

    async def _run(self, message_id: UUID) -> None:
        started = time.monotonic()
        writer = EventWriter(self.redis, message_id, self.settings.chat.stream_ttl_seconds)
        keepalive = asyncio.create_task(self._keep_alive(message_id))
        result = GenerationResult()
        trace: dict[str, Any] = {}
        is_first_answer = False
        question = ""
        try:
            async with self.sessions() as db:
                message, chat, user, chain = await self._load(db, message_id)
                question = chain[-1].content if chain else ""
                history = [
                    Turn(m.role, m.content)  # type: ignore[arg-type]
                    for m in chain[:-1]
                    if m.status in ("completed", "stopped") and m.content
                ]
                is_first_answer = chat.title is None
                # Сценарий — из БД на каждое сообщение: правка в админке действует сразу (§8.7).
                scenario = await db.get(Scenario, chat.scenario_id) if chat.scenario_id else None
                plan = self.registry.plan(
                    scenario.model_role if scenario else CHAT_ROLE, thinking=message.thinking
                )
                counter = TokenCounter(plan.endpoint.tokenizer)
                # Правки из админки «Настройки» (компания, обращение, промпт) — без перезапуска.
                effective = await app_settings.effective(db, self.settings)
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
                    f
                    for f in await chat_files(db, chat.id, kind="upload")
                    if f.message_id in branch_ids
                ]
                attachments = await build_attachments(
                    uploads,
                    storage=self.storage,
                    renderer=self.renderer,
                    settings=self.settings,
                    endpoint=plan.endpoint,
                    counter=counter,
                )
                now = utcnow()
                base_system = system_prompt(
                    self.renderer, effective, prompt_user, now, base_template=base_override
                )
                if scenario is not None:
                    scenario_text = render_scenario(
                        scenario,
                        {
                            "user": asdict(prompt_user),
                            "company": effective.chat.company_name,
                            "now": now_text(now, self.settings.chat.timezone),
                        },
                    )
                    base_system = "\n\n".join(x for x in (base_system, scenario_text) if x)
                roles = await rbac.user_roles(db, user.id)
                permissions = rbac.effective_permissions(
                    roles, await rbac.permissions_for_roles(db, (r.role.id for r in roles))
                )
                rag_mode = scenario.rag_mode if scenario else self.settings.rag.mode
                # Базы сценария сужают область поиска; пусто — все доступные пользователю.
                only_kb_ids = None
                if scenario is not None and scenario.knowledge_bases:
                    only_kb_ids = list(
                        (
                            await db.scalars(
                                select(KnowledgeBase.id).where(
                                    KnowledgeBase.code.in_(scenario.knowledge_bases)
                                )
                            )
                        ).all()
                    )
                # Вложения ищутся вместе с базами, когда в промпте только их оглавление (§10.4).
                scope = await build_scope(
                    db, user.id, (r.role.id for r in roles),
                    attachment_ids=[f.id for f in attachments.files]
                    if attachments.mode == "outline" else (),
                    only_kb_ids=only_kb_ids,
                )  # fmt: skip
                has_kb = bool(scope.kb_ids or scope.personal_kb_ids)
                # Инструменты: включены ∩ разрешены сценарием ∩ доступны ролям (§9.1).
                tools = (
                    available_tools(
                        enabled=await app_settings.enabled_tools(db, self.settings),
                        scenario=scenario.tools if scenario else None,
                        permissions=permissions,
                        has_attachments=bool(attachments.files),
                        has_knowledge=has_kb and rag_mode != "off",
                    )
                    if plan.endpoint.supports_tools
                    else []
                )
                book = SourceBook()
                result.book = book
                context = ToolContext(
                    user_id=user.id,
                    permissions=permissions,
                    chat_id=chat.id,
                    message_id=message_id,
                    attachments=attachments.files,
                    services=self.services,
                    kb_scope=scope,
                    sources=book,
                )
                chat_id, parent_id = chat.id, message.parent_id
                message.model = plan.endpoint.model
                message.thinking = plan.thinking
                await db.commit()

            await writer.emit(
                "message.start",
                {
                    "message_id": str(message_id),
                    "chat_id": str(chat_id),
                    "parent_id": str(parent_id) if parent_id else None,
                    "model": plan.endpoint.model,
                    "thinking": plan.thinking,
                    "protocol_version": PROTOCOL_VERSION,
                },
            )
            knowledge: str | None = None
            rag_trace: dict[str, Any] | None = None
            if rag_mode == "auto" and not scope.empty:
                knowledge, rag_trace = await self._auto_rag(
                    context, writer, result, question=question, history=history,
                    budget=int(
                        (plan.endpoint.context_length or DEFAULT_CONTEXT)
                        * self.settings.rag.context_share
                    ),
                    counter=counter,
                )  # fmt: skip
            system = "\n\n".join(x for x in (base_system, knowledge, attachments.text) if x)
            prompt = build_messages(
                system=system,
                history=history,
                message=question,
                endpoint=plan.endpoint,
                counter=counter,
            )
            trace = {
                "model_role": plan.role,
                "model": plan.endpoint.model,
                "thinking": plan.thinking,
                **prompt.trace(),
                "rag_mode": rag_mode,
                "scenario": scenario.code if scenario else None,
                **({"rag": rag_trace} if rag_trace else {}),
                "attachments": {
                    "mode": attachments.mode,
                    "files": len(attachments.files),
                    "tokens": attachments.tokens,
                },
                "tools_offered": [t.name for t in tools],
            }
            await self._loop(
                message_id,
                plan.role,
                prompt.messages,
                plan.params,
                writer,
                result,
                started,
                tools=tools,
                context=context,
            )
            if result.usage is None:
                result.usage = Usage(
                    prompt_tokens=prompt.prompt_tokens,
                    completion_tokens=counter.count(
                        "".join(result.content) + "".join(result.reasoning)
                    ),
                    reasoning_tokens=counter.count("".join(result.reasoning)) or None,
                )
                trace["usage_estimated"] = True
        except asyncio.CancelledError:
            result.status = "interrupted"
            result.error = {"code": "interrupted", "message": "Генерация прервана"}
            await self._finish(message_id, result, trace, started, writer, title_for=None)
            raise
        except Exception as exc:
            log.exception("completions.failed", message_id=str(message_id))
            result.status = "error"
            result.error = _error_payload(exc)
            if result.error["code"] == "internal_error":
                # Ошибка нашего кода (не модели): инцидент со стеком и логами генерации.
                await report_exception(
                    self.sessions, exc,
                    context={"stage": "generation", "message_id": str(message_id)},
                    request_lines=log_capture.request_lines(),
                    message_id=message_id,
                )  # fmt: skip
            trace["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            await writer.emit("error", result.error)
        finally:
            keepalive.cancel()
        # Заголовок — служебной моделью по первому успешному ответу; если ответ остановлен или
        # упал — сразу из первых слов вопроса, чтобы чат не висел в истории безымянным.
        title_for = question if is_first_answer and result.status == "completed" else None
        fallback = (
            fallback_title(question) if is_first_answer and not title_for and question else None
        )
        await self._finish(
            message_id, result, trace, started, writer, title_for=title_for, title_now=fallback
        )

    async def _loop(
        self,
        message_id: UUID,
        role: str,
        messages: list[dict[str, Any]],
        params: dict[str, Any],
        writer: EventWriter,
        result: GenerationResult,
        started: float,
        *,
        tools: list[Any],
        context: ToolContext,
    ) -> None:
        """Цикл инструментов (§8.4): запрос → вызовы инструментов → их результаты → снова запрос."""
        schemas = [t.schema() for t in tools]
        allowed = {t.name for t in tools}
        max_iterations = self.settings.tools.max_iterations
        for iteration in range(1, max_iterations + 1):
            text, calls = await self._stream(
                message_id, role, messages, params, writer, result, started, schemas=schemas
            )
            if result.status == "stopped" or not calls:
                return
            messages.append(
                {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": c.arguments},
                        }
                        for c in calls
                    ],
                }
            )
            outcomes = await asyncio.gather(
                *(self._run_tool(context, call, writer, allowed) for call in calls)
            )
            for outcome in outcomes:
                outcome.iteration = iteration
                result.tools.append(outcome)
                result.files.extend(outcome.files)
                messages.append(
                    {"role": "tool", "tool_call_id": outcome.call_id, "content": outcome.content}
                )
            if await self.redis.exists(cancel_key(message_id)):
                result.status = "stopped"
                return
        # Модель всё ещё вызывает инструменты — честно сообщаем, что не уложились.
        # TODO(stage-7): инцидент уровня warning (§8.4).
        result.content.append(MAX_ITERATIONS_NOTE)
        await writer.delta("content", MAX_ITERATIONS_NOTE)
        result.finish_reason = "max_iterations"

    async def _auto_rag(
        self,
        context: ToolContext,
        writer: EventWriter,
        result: GenerationResult,
        *,
        question: str,
        history: list[Turn],
        budget: int,
        counter: TokenCounter,
    ) -> tuple[str | None, dict[str, Any]]:
        """Режим ``auto`` (§8.3): переформулировка → гибридный поиск → фрагменты в промпт.

        Для пользователя это шаг «Ищу в базах знаний…» — как вызов инструмента, и в истории тоже.
        """
        started = time.monotonic()
        call_id, tool, label = "rag-auto", "search_knowledge_base", "tools.search_knowledge_base"
        rewritten = await rewrite_query(
            self.registry, self.renderer, self.settings, question,
            [RagTurn(t.role, t.content) for t in history],
        )  # fmt: skip
        params = {"query": rewritten}
        await writer.emit(
            "tool.start", {"call_id": call_id, "tool": tool, "label": label, "params": params}
        )
        status = "ok"
        trace: dict[str, Any] = {"rewritten": rewritten}
        fragments: list[Fragment] = []
        try:
            # BM25 получает и исходный текст: точные коды не потеряются при переформулировке.
            bm25_query = rewritten if rewritten == question else f"{rewritten}\n{question}"
            found = await run_search(
                self.services.search(), context.kb_scope, query=rewritten, bm25_query=bm25_query,
                user_id=context.user_id, chat_id=context.chat_id, message_id=context.message_id,
            )  # fmt: skip
            fragments = found.fragments
            trace.update(found.trace)
        except Exception as exc:
            log.exception("completions.rag_failed", message_id=str(context.message_id))
            status = "error"
            trace["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        # Бюджет фрагментов (§8.3): лишние — с конца списка, они наименее релевантны.
        kept: list[Fragment] = []
        used = 0
        for fragment in fragments:
            cost = counter.count(fragment.text)
            if kept and used + cost > budget:
                break
            kept.append(fragment)
            used += cost
        numbered = context.sources.add(kept)
        trace["fragments"] = len(numbered)
        trace["tokens"] = used
        knowledge = (
            self.renderer.render("system/knowledge.md.j2", fragments=fragments_context(numbered))
            if status == "ok"
            else None
        )
        await writer.emit(
            "tool.end",
            {"call_id": call_id, "tool": tool, "label": label, "status": status, "params": params},
        )
        if numbered:
            await self._emit_sources(writer, context.sources)
        result.tools.append(
            ToolOutcome(
                call_id=call_id, tool=tool, arguments={"query": rewritten, "mode": "auto"},
                content=f"фрагментов: {len(numbered)}", status=status,
                duration_ms=int((time.monotonic() - started) * 1000), visibility="visible",
                label=label, label_params=params, iteration=0,
            )
        )  # fmt: skip
        return knowledge, trace

    async def _emit_sources(self, writer: EventWriter, book: SourceBook) -> None:
        # Каждый раз — полный список: клиент заменяет карточки, а не дописывает.
        await writer.emit("sources", {"items": [source_card(f) for f in book.fragments]})

    async def _run_tool(
        self, context: ToolContext, call: PendingCall, writer: EventWriter, allowed: set[str]
    ) -> ToolOutcome:
        from app.modules.tools.registry import get_tool

        tool = get_tool(call.name) if call.name in allowed else None
        visible = tool is None or tool.visibility == "visible"
        # Скрытые инструменты не порождают событий SSE (§9.6).
        if visible:
            await writer.emit(
                "tool.start",
                {
                    "call_id": call.id,
                    "tool": call.name,
                    "label": tool.status_label if tool else "tools.unknown",
                    "params": preview_label_params(tool, call.arguments),
                },
            )
        outcome = await execute(
            context,
            call_id=call.id,
            name=call.name,
            raw_arguments=call.arguments,
            allowed=allowed,
            limit=self.settings.tools.result_max_chars,
        )
        if visible:
            await writer.emit(
                "tool.end",
                {
                    "call_id": call.id,
                    "tool": call.name,
                    "status": outcome.status,
                    "label": outcome.label,
                    "params": outcome.label_params,
                },
            )
            if outcome.sources:
                await self._emit_sources(writer, context.sources)
            for file in outcome.files:
                await writer.emit(
                    "file",
                    {
                        "file_id": file["file_id"],
                        "name": file["filename"],
                        "mime": file["mime"],
                        "size": file["size"],
                        "preview": file["has_preview"],
                    },
                )
        return outcome

    async def _stream(
        self,
        message_id: UUID,
        role: str,
        messages: list[dict[str, Any]],
        params: dict[str, Any],
        writer: EventWriter,
        result: GenerationResult,
        started: float,
        *,
        schemas: list[dict[str, Any]],
    ) -> tuple[str, list[PendingCall]]:
        """Один запрос к модели со стримингом: текст этой итерации и вызовы инструментов."""
        client = self.registry.client(role)
        extra: dict[str, Any] = {"tools": schemas, "tool_choice": "auto"} if schemas else {}
        stream: AsyncStream[ChatCompletionChunk] = await client.chat.completions.create(  # type: ignore[call-overload]
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            **params,
            **extra,
        )
        last_check = time.monotonic()
        text: list[str] = []
        calls: dict[int, PendingCall] = {}
        try:
            async for item in parse_stream(stream):
                if isinstance(item, Delta):
                    now = time.monotonic()
                    if result.ttft_ms is None:
                        result.ttft_ms = int((now - started) * 1000)
                    if item.kind == "reasoning" and result.reasoning_started is None:
                        result.reasoning_started = now
                    if (
                        item.kind == "content"
                        and result.reasoning_started is not None
                        and result.reasoning_ms is None
                    ):
                        # Время размышления — от первой дельты размышлений до первой дельты ответа.
                        result.reasoning_ms = int((now - result.reasoning_started) * 1000)
                    if item.kind == "content":
                        result.content.append(item.text)
                        text.append(item.text)
                    else:
                        result.reasoning.append(item.text)
                    await writer.delta(item.kind, item.text)
                elif isinstance(item, ToolCallDelta):
                    call = calls.setdefault(item.index, PendingCall())
                    call.id = call.id or (item.id or "")
                    call.name = call.name or (item.name or "")
                    call.arguments += item.arguments
                elif isinstance(item, Usage):
                    result.add_usage(item)
                elif isinstance(item, Finish):
                    result.finish_reason = item.reason
                if time.monotonic() - last_check >= CANCEL_CHECK_INTERVAL:
                    last_check = time.monotonic()
                    if await self.redis.exists(cancel_key(message_id)):
                        result.status = "stopped"
                        result.finish_reason = "stop_requested"
                        break
        finally:
            await stream.close()
        if result.status != "stopped" and await self.redis.exists(cancel_key(message_id)):
            result.status = "stopped"
        pending = [c for _, c in sorted(calls.items()) if c.name]
        for index, call in enumerate(pending):
            call.id = call.id or f"call_{index}"
        return "".join(text), pending

    async def _generate_title(self, question: str) -> str:
        try:
            plan = self.registry.plan(UTILITY_ROLE, thinking=False)
            params = {**plan.params, "max_tokens": 32}
            prompt = self.renderer.render("utility/title.md.j2", message=question[:2000])
            response = await asyncio.wait_for(
                self.registry.client(UTILITY_ROLE).chat.completions.create(
                    messages=[{"role": "user", "content": prompt}], **params
                ),
                timeout=self.settings.chat.title_timeout_seconds,
            )
            title = clean_title(response.choices[0].message.content or "")
            if title:
                return title
        except Exception as exc:
            log.warning("completions.title_failed", error=f"{type(exc).__name__}: {exc}"[:300])
        return fallback_title(question)

    async def _finish(
        self,
        message_id: UUID,
        result: GenerationResult,
        trace: dict[str, Any],
        started: float,
        writer: EventWriter,
        *,
        title_for: str | None,
        title_now: str | None = None,
    ) -> None:
        """Сохраняет ответ в БД и закрывает поток событий. Вызывается ровно один раз."""
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = result.usage
        title = await self._generate_title(title_for) if title_for else title_now
        chat_id: UUID | None = None
        try:
            async with self.sessions() as db:
                message = await db.get(Message, message_id)
                if message is not None:
                    message.content = "".join(result.content)
                    message.reasoning = "".join(result.reasoning) or None
                    message.status = result.status
                    message.finish_reason = result.finish_reason
                    message.ttft_ms = result.ttft_ms
                    message.latency_ms = latency_ms
                    message.error = (
                        {k: v for k, v in result.error.items() if k != "retryable"}
                        if result.error
                        else None
                    )
                    if result.reasoning_started is not None and result.reasoning_ms is None:
                        result.reasoning_ms = int(
                            (time.monotonic() - result.reasoning_started) * 1000
                        )
                    if result.reasoning_ms is not None:
                        trace["reasoning_ms"] = result.reasoning_ms
                    if result.tools:
                        trace["tools"] = [
                            {
                                "call_id": o.call_id,
                                "tool": o.tool,
                                "status": o.status,
                                "duration_ms": o.duration_ms,
                                "visibility": o.visibility,
                                "arguments": o.arguments,
                                "result_preview": o.content[:2000],
                            }
                            for o in result.tools
                        ]
                        for outcome in result.tools:
                            db.add(
                                ToolCall(
                                    message_id=message_id,
                                    call_id=outcome.call_id,
                                    tool=outcome.tool,
                                    arguments=outcome.arguments,
                                    result_preview=outcome.content[:4000],
                                    status=outcome.status,
                                    duration_ms=outcome.duration_ms,
                                    visibility=outcome.visibility,
                                    iteration=outcome.iteration,
                                    label=outcome.label,
                                    label_params=outcome.label_params or None,
                                )
                            )
                    if result.book and result.book.fragments:
                        cited = cited_indexes(message.content)
                        trace["sources"] = {
                            "offered": len(result.book.fragments),
                            "cited": sorted(cited),
                        }
                        for f in result.book.fragments:
                            db.add(
                                MessageSource(
                                    message_id=message_id, index=f.index, kind=f.kind,
                                    kb_id=UUID(f.kb_id) if f.kb_id else None,
                                    document_id=UUID(f.document_id) if f.kind == "kb" else None,
                                    file_id=UUID(f.file_id) if f.file_id else None,
                                    chunk_id=f.chunk_id, title=f.title[:255], kb_name=f.kb_name,
                                    page=f.page, section=f.section, snippet=f.snippet,
                                    score=f.score, cited=f.index in cited,
                                )
                            )  # fmt: skip
                    message.trace = {**(message.trace or {}), **trace}
                    if usage:
                        message.prompt_tokens = usage.prompt_tokens
                        message.completion_tokens = usage.completion_tokens
                        message.reasoning_tokens = usage.reasoning_tokens
                    values: dict[str, Any] = {"last_message_at": utcnow()}
                    if title:
                        values["title"] = title
                    await db.execute(
                        update(Chat).where(Chat.id == message.chat_id).values(**values)
                    )
                    chat_id = message.chat_id
                    await db.commit()
                    # TODO(stage-8): списание токенов в лимиты и usage_records (§12.3).
                    # TODO(stage-7): проверка guard-моделью (§9.6).
            with suppress(asyncio.CancelledError):
                if usage:
                    await writer.emit(
                        "usage",
                        {
                            "prompt_tokens": usage.prompt_tokens,
                            "completion_tokens": usage.completion_tokens,
                            "reasoning_tokens": usage.reasoning_tokens,
                        },
                    )
                if title and chat_id:
                    await writer.emit("title", {"chat_id": str(chat_id), "title": title})
                await writer.emit(
                    "message.end", {"status": result.status, "finish_reason": result.finish_reason}
                )
                await writer.close()
        finally:
            await self.redis.delete(alive_key(message_id), cancel_key(message_id))
            log.info(
                "completions.done",
                message_id=str(message_id),
                status=result.status,
                latency_ms=latency_ms,
                ttft_ms=result.ttft_ms,
            )
