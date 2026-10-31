"""API генерации: отправка сообщения, перегенерация, «Стоп», SSE-поток (§2.2, §8.5, §8.6)."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import exists, select

from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import DbDep
from app.core.errors import AppError, NotFoundError
from app.modules.auth.deps import CurrentUserDep
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
from app.modules.llm.registry import ModelRegistry

router = APIRouter(tags=["completions"])


def _manager(request: Request) -> GenerationManager:
    manager: GenerationManager = request.app.state.generations
    return manager


async def _ensure_idle(db: DbDep, chat: Chat) -> None:
    busy = await db.scalar(
        select(exists().where(Message.chat_id == chat.id, Message.status == "streaming"))
    )
    if busy:
        raise AppError(
            "Дождитесь окончания ответа или остановите его", code="chat_busy", status_code=409
        )


def _thinking(request: Request, requested: bool | None, chat: Chat) -> bool:
    registry: ModelRegistry = request.app.state.models
    if not registry.thinking_available(CHAT_ROLE):
        return False
    if requested is not None:
        return requested
    if chat.thinking_enabled is not None:
        return chat.thinking_enabled
    return registry.get(CHAT_ROLE).thinking.default


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
    # TODO(stage-8): проверка и резервирование лимитов до запроса (§12.3).

    parent_id = body.parent_id if "parent_id" in body.model_fields_set else chat.active_leaf_id
    if parent_id is not None:
        parent = await db.get(Message, parent_id)
        if parent is None or parent.chat_id != chat.id or parent.role != "assistant":
            raise AppError("Продолжать можно только от ответа этого чата", code="bad_parent")

    thinking = _thinking(request, body.thinking, chat)
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
    assistant = Message(
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
        user_message=chats.message_out(user_message), assistant_message=chats.message_out(assistant)
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
    assistant = Message(
        chat_id=chat.id,
        parent_id=message.parent_id,
        role="assistant",
        content="",
        status="streaming",
        thinking=_thinking(request, body.thinking, chat),
        created_at=utcnow(),
    )
    db.add(assistant)
    await db.flush()
    chat.active_leaf_id = assistant.id
    chat.last_message_at = utcnow()
    await db.commit()
    await _manager(request).start(assistant.id)
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
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        # Без буферизации на прокси — иначе стрим придёт одним куском (AGENTS.md, §16.2).
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
