"""Админка «Переписка» (§13.3): поиск, список, просмотр, восстановление, физическое удаление.

Просмотр чата целиком пишется в аудит при каждом открытии (§13.6, §15); поиск и список показывают
только фрагменты и метаданные. Физическое удаление — только ``admin.chats.purge`` (superadmin).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.core.deps import DbDep, SettingsDep, StorageDep
from app.core.errors import AppError, NotFoundError
from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Page,
    decode_datetime_cursor,
    encode_cursor,
)
from app.modules.admin import chats as service
from app.modules.admin.chat_schemas import (
    AdminChatDetail,
    AdminChatItem,
    AdminMessageHit,
    ChatFilter,
    FilterOptions,
    PurgeIn,
    PurgeOut,
)
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.chats.models import Chat
from app.modules.chats.purge import cleanup, purge_chat
from app.modules.rag.store import ATTACHMENT_COLLECTION, delete_document, qdrant_client
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/admin", tags=["admin"])

Viewer = Annotated[CurrentUser, Depends(require(Perm.CHATS_VIEW))]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Filter = Annotated[ChatFilter, Query()]


def _cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    ts, last_id = decode_datetime_cursor(cursor)
    return ts, UUID(last_id)


@router.get("/chats/filters", response_model=FilterOptions, operation_id="adminChatFilterOptions")
async def filter_options(db: DbDep, _: Viewer) -> FilterOptions:
    """Значения для фильтров: отделы, сценарии, модели."""
    return await service.filter_options(db)


@router.get("/messages", response_model=Page[AdminMessageHit], operation_id="adminSearchMessages")
async def search_messages(
    db: DbDep,
    settings: SettingsDep,
    _: Viewer,
    f: Filter,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[AdminMessageHit]:
    """Поиск по всем сообщениям: русская морфология + подстрока, фрагмент с подсветкой."""
    items = await service.search_messages(
        db, f, settings.chat.timezone, cursor=_cursor(cursor), limit=limit + 1
    )
    last = items[limit - 1] if len(items) > limit else None
    return Page(
        items=items[:limit],
        next_cursor=encode_cursor(last.created_at, last.message_id) if last else None,
    )


@router.get("/chats", response_model=Page[AdminChatItem], operation_id="adminListChats")
async def list_chats(
    db: DbDep,
    settings: SettingsDep,
    _: Viewer,
    f: Filter,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[AdminChatItem]:
    items = await service.list_chats(
        db, f, settings.chat.timezone, cursor=_cursor(cursor), limit=limit + 1
    )
    last = items[limit - 1] if len(items) > limit else None
    return Page(
        items=items[:limit],
        next_cursor=encode_cursor(service.chat_activity(last), last.id) if last else None,
    )


@router.get("/chats/{chat_id}", response_model=AdminChatDetail, operation_id="adminGetChat")
async def get_chat(chat_id: UUID, request: Request, db: DbDep, actor: Viewer) -> AdminChatDetail:
    """Чат целиком — все ветки, удалённое, скрытые вызовы; просмотр записывается в аудит."""
    detail = await service.chat_detail(db, chat_id)
    await audit.record(
        db, actor_id=actor.id, action="chat.view", target_type="chat", target_id=chat_id,
        details={"user_id": str(detail.user.id), "login": detail.user.login},
        ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return detail


@router.post(
    "/chats/{chat_id}/restore", response_model=AdminChatItem, operation_id="adminRestoreChat"
)
async def restore_chat(
    chat_id: UUID,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    actor: Annotated[CurrentUser, Depends(require(Perm.CHATS_RESTORE))],
) -> AdminChatItem:
    """Вернуть пользователю удалённый чат: он снова появится в его истории."""
    chat = await db.get(Chat, chat_id)
    if chat is None:
        raise NotFoundError("Чат не найден")
    if chat.deleted_at is None:
        raise AppError("Чат не удалён", code="not_deleted", status_code=409)
    deleted_at = chat.deleted_at
    chat.deleted_at = None
    chat.deleted_by = None
    await audit.record(
        db, actor_id=actor.id, action="chat.restore", target_type="chat", target_id=chat_id,
        details={"user_id": str(chat.user_id), "deleted_at": deleted_at.isoformat()},
        ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return await service.chat_item(db, chat_id)


@router.post("/chats/{chat_id}/purge", response_model=PurgeOut, operation_id="adminPurgeChat")
async def purge(
    chat_id: UUID,
    body: PurgeIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    actor: Annotated[CurrentUser, Depends(require(Perm.CHATS_PURGE))],
) -> PurgeOut:
    """Удалить чат безвозвратно; в аудите — кто, чей чат и сколько удалено, без содержимого."""
    if body.confirm.strip() != str(chat_id):
        raise AppError(
            "Для подтверждения введите id чата", code="confirm_mismatch", status_code=422
        )
    chat = await db.get(Chat, chat_id)
    if chat is None:
        raise NotFoundError("Чат не найден")
    owner_id = chat.user_id
    result = await purge_chat(db, chat_id)
    await audit.record(
        db, actor_id=actor.id, action="chat.purge", target_type="chat", target_id=chat_id,
        details={"user_id": str(owner_id), "messages": result.messages, "files": result.files},
        ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    client = qdrant_client(settings)

    async def drop_points(file_id: UUID) -> None:
        await delete_document(client, ATTACHMENT_COLLECTION, file_id)

    try:
        await cleanup(result, storage, drop_points)
    finally:
        await client.close()
    return PurgeOut(messages=result.messages, files=result.files)
