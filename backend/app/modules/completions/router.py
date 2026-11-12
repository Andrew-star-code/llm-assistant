"""API генерации: отправка сообщения, перегенерация, «Стоп», SSE-поток (§2.2, §8.5, §8.6)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import exists, select

from app.core import metrics
from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import DbDep
from app.core.errors import AppError, NotFoundError
from app.modules.admin import app_settings
from app.modules.auth.deps import CurrentUser, CurrentUserDep
from app.modules.chats import service as chats
from app.modules.chats.models import Chat, Message
from app.modules.chats.schemas import (
    ChatModelInfo,
    MessageOut,
    RegenerateIn,
    SendMessageIn,
    SendMessageOut,
)
from app.modules.completions.generation import CHAT_ROLE, GenerationManager
from app.modules.completions.streaming import sse_events
from app.modules.files import service as files_service
from app.modules.files.models import File
from app.modules.limits.service import Limits, Reservation
from app.modules.llm.registry import ModelRegistry
from app.modules.rbac.permissions import Perm
from app.modules.scenarios import service as scenarios
from app.modules.scenarios.models import Scenario
from app.modules.scenarios.router import role_codes
from app.modules.security import rules

router = APIRouter(tags=["completions"])


def _manager(request: Request) -> GenerationManager:
    manager: GenerationManager = request.app.state.generations
    return manager


def _limits(request: Request) -> Limits:
    limits: Limits = request.app.state.limits
    return limits


async def _reserve(
    request: Request,
    db: DbDep,
    current: CurrentUser,
    *,
    scenario: Scenario | None,
    thinking: bool,
    message_id: UUID,
) -> Reservation:
    """Лимиты до запроса (§12.3): сообщения, токены, слот генерации; превышение — 429."""
    return await _limits(request).reserve_generation(
        db,
        user_id=current.id,
        model_role=scenario.model_role if scenario else CHAT_ROLE,
        thinking=thinking,
        message_id=message_id,
    )


async def _ensure_idle(db: DbDep, chat: Chat) -> None:
    busy = await db.scalar(
        select(exists().where(Message.chat_id == chat.id, Message.status == "streaming"))
    )
    if busy:
        raise AppError(
            "Дождитесь окончания ответа или остановите его", code="chat_busy", status_code=409
        )


def _thinking(
    request: Request, requested: bool | None, chat: Chat, scenario: Scenario | None = None
) -> bool:
    """Запрошенное → сохранённое в чате → по умолчанию сценария → по умолчанию модели (§7.3)."""
    registry: ModelRegistry = request.app.state.models
    role = scenario.model_role if scenario else CHAT_ROLE
    if not registry.thinking_available(role):
        return False
    if requested is not None:
        return requested
    if chat.thinking_enabled is not None:
        return chat.thinking_enabled
    if scenario is not None and scenario.thinking_default is not None:
        return scenario.thinking_default
    return registry.get(role).thinking.default


async def chat_scenario(db: DbDep, chat: Chat, current: CurrentUser) -> Scenario | None:
    """Сценарий чата, если он ещё доступен пользователю (роли могли смениться).

    Тестовый чат из редактора доступен тому, кто управляет сценариями, — даже без роли сценария
    и для выключенного сценария.
    """
    if chat.scenario_id is None:
        return None
    scenario = await db.get(Scenario, chat.scenario_id)
    if scenario is not None and (
        await scenarios.visible_for(db, scenario, role_codes(current))
        or (chat.is_test and current.has(Perm.SCENARIOS_MANAGE))
    ):
        return scenario
    raise AppError(
        "Сценарий этого чата вам больше недоступен — сбросьте его, чтобы продолжить",
        code="scenario_unavailable",
        status_code=403,
    )


@router.get("/models/chat", response_model=ChatModelInfo, operation_id="getChatModel")
async def chat_model(request: Request, _: CurrentUserDep) -> ChatModelInfo:
    """Доступен ли переключатель «Размышлять» (§7.3) и его значение по умолчанию."""
    registry: ModelRegistry = request.app.state.models
    available = registry.thinking_available(CHAT_ROLE)
    default = available and registry.get(CHAT_ROLE).thinking.default
    return ChatModelInfo(thinking_available=available, thinking_default=default)


@router.post(
    "/chats/{chat_id}/messages",
    response_model=SendMessageOut,
    status_code=202,
    operation_id="sendMessage",
)
async def send_message(
    chat_id: UUID, body: SendMessageIn, request: Request, db: DbDep, current: CurrentUserDep
) -> SendMessageOut:
    """Сохраняет сообщение и пустой ответ ``streaming``, запускает генерацию, сразу отвечает."""
    settings: Settings = request.app.state.settings
    content = body.content.strip()
    if not content:
        raise AppError("Пустое сообщение", code="empty_message", status_code=422)
    if len(content) > settings.chat.max_message_chars:
        raise AppError("Сообщение слишком длинное", code="message_too_long", status_code=413)
    chat = await chats.get_chat(db, current.id, chat_id)
    await _ensure_idle(db, chat)
    # Аномальный объём (§13.4): инцидент для разбора, независимо от лимитов (§12).
    await rules.track_message(
        request.app.state.redis, request.app.state.db_sessions,
        user_id=current.id, login=current.user.login, settings=settings,
    )  # fmt: skip

    parent_id = body.parent_id if "parent_id" in body.model_fields_set else chat.active_leaf_id
    if parent_id is not None:
        parent = await db.get(Message, parent_id)
        if parent is None or parent.chat_id != chat.id or parent.role != "assistant":
            raise AppError("Продолжать можно только от ответа этого чата", code="bad_parent")

    scenario = await chat_scenario(db, chat, current)
    if scenario is not None and scenario.requires_attachment and not body.attachment_ids:
        has_files = await db.scalar(
            select(exists().where(File.chat_id == chat.id, File.kind == "upload"))
        )
        if not has_files:
            raise AppError(
                scenario.attachment_hint or "Для этого сценария приложите файл",
                code="attachment_required",
                status_code=422,
            )
    thinking = _thinking(request, body.thinking, chat, scenario)
    assistant_id = uuid4()
    reservation = await _reserve(
        request, db, current, scenario=scenario, thinking=thinking, message_id=assistant_id
    )
    try:
        return await _create_and_start(
            request, db, current, chat, body, content, parent_id, thinking, assistant_id
        )
    except BaseException:
        # Запрос не дошёл до генерации — сообщение и слот возвращаются в лимит.
        await _limits(request).cancel(reservation)
        raise


async def _create_and_start(
    request: Request,
    db: DbDep,
    current: CurrentUser,
    chat: Chat,
    body: SendMessageIn,
    content: str,
    parent_id: UUID | None,
    thinking: bool,
    assistant_id: UUID,
) -> SendMessageOut:
    settings: Settings = request.app.state.settings
    now = utcnow()
    user_message = Message(
        chat_id=chat.id,
        parent_id=parent_id,
        role="user",
        content=content,
        status="completed",
        created_at=now,
    )
    db.add(user_message)
    await db.flush()
    attached = await files_service.attach(
        db,
        owner_id=current.id,
        file_ids=body.attachment_ids,
        chat_id=chat.id,
        message_id=user_message.id,
        max_files=(await app_settings.effective(db, settings)).files.max_files_per_message,
    )
    assistant = Message(
        id=assistant_id,
        chat_id=chat.id,
        parent_id=user_message.id,
        role="assistant",
        content="",
        status="streaming",
        thinking=thinking,
        # Ответ строго позже вопроса — стабильный порядок в ленте.
        created_at=now + timedelta(milliseconds=1),
    )
    db.add(assistant)
    await db.flush()
    chat.active_leaf_id = assistant.id
    chat.last_message_at = now
    if body.thinking is not None:
        chat.thinking_enabled = body.thinking
    await db.commit()
    await _manager(request).start(assistant.id)
    return SendMessageOut(
        user_message=chats.message_out(
            user_message, files=[files_service.file_out(f) for f in attached]
        ),
        assistant_message=chats.message_out(assistant),
    )


@router.post(
    "/messages/{message_id}/regenerate",
    response_model=MessageOut,
    status_code=202,
    operation_id="regenerateMessage",
)
async def regenerate(
    message_id: UUID, body: RegenerateIn, request: Request, db: DbDep, current: CurrentUserDep
) -> MessageOut:
    """Новая версия ответа — сестринское сообщение к тому же вопросу (§8.6). «Повторить» — то же."""
    message, chat = await chats.get_message(db, current.id, message_id)
    if message.role != "assistant" or message.parent_id is None:
        raise AppError("Перегенерировать можно только ответ ассистента", code="bad_message")
    await _ensure_idle(db, chat)
    scenario = await chat_scenario(db, chat, current)
    thinking = _thinking(request, body.thinking, chat, scenario)
    assistant_id = uuid4()
    reservation = await _reserve(
        request, db, current, scenario=scenario, thinking=thinking, message_id=assistant_id
    )
    try:
        assistant = Message(
            id=assistant_id,
            chat_id=chat.id,
            parent_id=message.parent_id,
            role="assistant",
            content="",
            status="streaming",
            thinking=thinking,
            created_at=utcnow(),
        )
        db.add(assistant)
        await db.flush()
        chat.active_leaf_id = assistant.id
        chat.last_message_at = utcnow()
        await db.commit()
        await _manager(request).start(assistant.id)
    except BaseException:
        await _limits(request).cancel(reservation)
        raise
    return chats.message_out(assistant)


@router.post("/messages/{message_id}/stop", status_code=202, operation_id="stopMessage")
async def stop(message_id: UUID, request: Request, db: DbDep, current: CurrentUserDep) -> None:
    """Ставит флаг отмены в Redis — его увидит процесс, который генерирует ответ (§8.6)."""
    message, _ = await chats.get_message(db, current.id, message_id)
    if message.status == "streaming":
        await _manager(request).request_stop(message.id)


@router.get(
    "/messages/{message_id}/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE, §8.5"}},
    operation_id="streamMessage",
)
async def stream(
    message_id: UUID,
    request: Request,
    db: DbDep,
    current: CurrentUserDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    after: Annotated[int | None, Query(ge=0, description="То же, что Last-Event-ID")] = None,
) -> StreamingResponse:
    """События ответа (docs/architecture/sse-protocol.md); переподключение — с Last-Event-ID."""
    settings: Settings = request.app.state.settings
    message, _ = await chats.get_message(db, current.id, message_id)
    if message.role != "assistant":
        raise NotFoundError("Сообщение не найдено")
    start = after if after is not None else 0
    if after is None and last_event_id and last_event_id.isdigit():
        start = int(last_event_id)
    factory = request.app.state.db_sessions

    async def status() -> str | None:
        async with factory() as session:
            row = await session.get(Message, message_id)
            return row.status if row else None

    async def mark_interrupted() -> None:
        async with factory() as session:
            row = await session.get(Message, message_id)
            if row is not None and row.status == "streaming":
                row.status = "interrupted"
                row.error = {"code": "interrupted", "message": "Генерация прервана"}
                await session.commit()

    events = sse_events(
        request.app.state.redis,
        message_id,
        last_event_id=start,
        heartbeat_seconds=settings.chat.heartbeat_seconds,
        message_status=status,
        mark_interrupted=mark_interrupted,
    )

    async def counted() -> AsyncIterator[str]:
        metrics.SSE_CONNECTIONS.inc()
        try:
            async for line in events:
                yield line
        finally:
            metrics.SSE_CONNECTIONS.dec()

    return StreamingResponse(
        counted(),
        media_type="text/event-stream",
        # Без буферизации на прокси — иначе стрим придёт одним куском (AGENTS.md, §16.2).
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
