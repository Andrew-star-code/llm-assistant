"""API чатов и папок: ``/api/chats``, ``/api/folders`` (§7.2). Доступ — только владельцу."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select, update

from app.core.db import utcnow
from app.core.deps import DbDep
from app.core.errors import AppError
from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Page,
    decode_datetime_cursor,
    encode_cursor,
)
from app.modules.auth.deps import CurrentUserDep
from app.modules.chats import service
from app.modules.chats.models import Chat, Folder, Message
from app.modules.chats.schemas import (
    ChatCreate,
    ChatDetail,
    ChatListItem,
    ChatUpdate,
    FolderIn,
    FolderOut,
    FolderUpdate,
    SearchHit,
)

router = APIRouter(tags=["chats"])

Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


def _item(chat: Chat) -> ChatListItem:
    return ChatListItem.model_validate(chat, from_attributes=True)


@router.get("/chats", response_model=Page[ChatListItem], operation_id="listChats")
async def list_chats(
    db: DbDep,
    current: CurrentUserDep,
    pinned: bool | None = None,
    folder_id: UUID | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[ChatListItem]:
    """Чаты с сообщениями, свежие сверху. Закреплённые — отдельно (``pinned=true``)."""
    parsed = None
    if cursor:
        ts, last_id = decode_datetime_cursor(cursor)
        parsed = (ts, UUID(last_id))
    rows = await service.list_chats(
        db, current.id, pinned=pinned, folder_id=folder_id, cursor=parsed, limit=limit + 1
    )
    items = [_item(c) for c in rows[:limit]]
    last = rows[limit - 1] if len(rows) > limit else None
    next_cursor = (
        encode_cursor(last.last_message_at, last.id) if last and last.last_message_at else None
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get("/chats/search", response_model=list[SearchHit], operation_id="searchChats")
async def search_chats(
    db: DbDep, current: CurrentUserDep, q: Annotated[str, Query(min_length=1, max_length=200)]
) -> list[SearchHit]:
    """Поиск по названиям и тексту сообщений (Ctrl+K, §7.2)."""
    return await service.search(db, current.id, q)


@router.post("/chats", response_model=ChatDetail, status_code=201, operation_id="createChat")
async def create_chat(body: ChatCreate, db: DbDep, current: CurrentUserDep) -> ChatDetail:
    """Пустой чат; в списке появится после первого сообщения."""
    if body.folder_id:
        await service.get_folder(db, current.id, body.folder_id)
    chat = Chat(
        user_id=current.id, folder_id=body.folder_id, thinking_enabled=body.thinking_enabled
    )
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return ChatDetail(
        **_item(chat).model_dump(),
        active_leaf_id=None,
        thinking_enabled=chat.thinking_enabled,
        messages=[],
    )


@router.get("/chats/{chat_id}", response_model=ChatDetail, operation_id="getChat")
async def get_chat(chat_id: UUID, db: DbDep, current: CurrentUserDep) -> ChatDetail:
    chat = await service.get_chat(db, current.id, chat_id)
    return ChatDetail.model_validate(
        {
            **_item(chat).model_dump(),
            "active_leaf_id": chat.active_leaf_id,
            "thinking_enabled": chat.thinking_enabled,
            "messages": await service.chat_messages(db, chat.id, current.id),
        }
    )


@router.patch("/chats/{chat_id}", response_model=ChatListItem, operation_id="updateChat")
async def update_chat(
    chat_id: UUID, body: ChatUpdate, db: DbDep, current: CurrentUserDep
) -> ChatListItem:
    """Переименование, закрепление, перенос в папку, активная ветка, режим thinking."""
    chat = await service.get_chat(db, current.id, chat_id)
    fields = body.model_fields_set
    if "title" in fields and body.title:
        chat.title = body.title.strip()
    if "pinned" in fields and body.pinned is not None:
        chat.pinned = body.pinned
    if "folder_id" in fields:
        if body.folder_id:
            await service.get_folder(db, current.id, body.folder_id)
        chat.folder_id = body.folder_id
    if "active_leaf_id" in fields and body.active_leaf_id:
        leaf = await db.get(Message, body.active_leaf_id)
        if leaf is None or leaf.chat_id != chat.id or leaf.deleted_at is not None:
            raise AppError("Сообщение не из этого чата", code="bad_leaf")
        chat.active_leaf_id = leaf.id
    if "thinking_enabled" in fields:
        chat.thinking_enabled = body.thinking_enabled
    await db.commit()
    return _item(chat)


@router.delete("/chats/{chat_id}", status_code=204, operation_id="deleteChat")
async def delete_chat(chat_id: UUID, db: DbDep, current: CurrentUserDep) -> None:
    """Мягкое удаление: чат исчезает у пользователя, но остаётся для админа (§7.2, §13)."""
    chat = await service.get_chat(db, current.id, chat_id)
    chat.deleted_at = utcnow()
    chat.deleted_by = current.id
    await db.commit()


# ------------------------------------------------------------------ папки


@router.get("/folders", response_model=list[FolderOut], operation_id="listFolders")
async def list_folders(db: DbDep, current: CurrentUserDep) -> list[FolderOut]:
    rows = await db.scalars(
        select(Folder).where(Folder.user_id == current.id).order_by(Folder.sort_order, Folder.name)
    )
    return [FolderOut.model_validate(f, from_attributes=True) for f in rows.all()]


@router.post("/folders", response_model=FolderOut, status_code=201, operation_id="createFolder")
async def create_folder(body: FolderIn, db: DbDep, current: CurrentUserDep) -> FolderOut:
    folder = Folder(user_id=current.id, name=body.name.strip(), sort_order=0)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return FolderOut.model_validate(folder, from_attributes=True)


@router.patch("/folders/{folder_id}", response_model=FolderOut, operation_id="updateFolder")
async def update_folder(
    folder_id: UUID, body: FolderUpdate, db: DbDep, current: CurrentUserDep
) -> FolderOut:
    folder = await service.get_folder(db, current.id, folder_id)
    if body.name is not None:
        folder.name = body.name.strip()
    if body.sort_order is not None:
        folder.sort_order = body.sort_order
    await db.commit()
    return FolderOut.model_validate(folder, from_attributes=True)


@router.delete("/folders/{folder_id}", status_code=204, operation_id="deleteFolder")
async def delete_folder(
    folder_id: UUID,
    db: DbDep,
    current: CurrentUserDep,
    chats: Literal["move", "delete"] = "move",
) -> None:
    """Удаление папки: чаты переносятся в корень (``move``) или удаляются мягко (``delete``)."""
    folder = await service.get_folder(db, current.id, folder_id)
    in_folder = (Chat.folder_id == folder.id) & (Chat.user_id == current.id)
    if chats == "delete":
        await db.execute(
            update(Chat)
            .where(in_folder, Chat.deleted_at.is_(None))
            .values(deleted_at=utcnow(), deleted_by=current.id, folder_id=None)
        )
    else:
        await db.execute(update(Chat).where(in_folder).values(folder_id=None))
    await db.delete(folder)
    await db.commit()
