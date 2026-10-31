"""Чаты, папки и сообщения: доступ только владельцу (защита от IDOR, §15, §18.2).

Чужой или удалённый чат для пользователя «не существует» — 404, а не 403, чтобы не раскрывать
наличие объекта.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.core.errors import NotFoundError
from app.modules.chats.models import Chat, Folder, Message
from app.modules.chats.schemas import (
    FeedbackOut,
    MessageError,
    MessageOut,
    SearchFragment,
    SearchHit,
    ToolStep,
)
from app.modules.feedback.models import Feedback
from app.modules.files.models import File
from app.modules.files.schemas import FileOut
from app.modules.files.service import file_out
from app.modules.tools.models import ToolCall

# Маркеры подсветки в ts_headline: управляющие символы не встречаются в тексте пользователя.
_START, _STOP = "\x02", "\x03"
SEARCH_LIMIT = 30


async def get_chat(db: AsyncSession, user_id: UUID, chat_id: UUID) -> Chat:
    chat = await db.get(Chat, chat_id)
    if chat is None or chat.user_id != user_id or chat.deleted_at is not None:
        raise NotFoundError("Чат не найден")
    return chat


async def get_message(db: AsyncSession, user_id: UUID, message_id: UUID) -> tuple[Message, Chat]:
    message = await db.get(Message, message_id)
    if message is None or message.deleted_at is not None:
        raise NotFoundError("Сообщение не найдено")
    chat = await get_chat(db, user_id, message.chat_id)
    return message, chat


async def get_folder(db: AsyncSession, user_id: UUID, folder_id: UUID) -> Folder:
    folder = await db.get(Folder, folder_id)
    if folder is None or folder.user_id != user_id:
        raise NotFoundError("Папка не найдена")
    return folder


def message_out(
    message: Message,
    feedback: Feedback | None = None,
    *,
    files: Sequence[FileOut] = (),
    tools: Sequence[ToolStep] = (),
) -> MessageOut:
    error = None
    if message.error:
        error = MessageError(
            code=str(message.error.get("code", "error")),
            message=str(message.error.get("message", "Ошибка")),
        )
    return MessageOut(
        id=message.id,
        chat_id=message.chat_id,
        parent_id=message.parent_id,
        role=message.role,
        content=message.content,
        reasoning=message.reasoning,
        status=message.status,
        thinking=message.thinking,
        model=message.model,
        finish_reason=message.finish_reason,
        prompt_tokens=message.prompt_tokens,
        completion_tokens=message.completion_tokens,
        reasoning_tokens=message.reasoning_tokens,
        ttft_ms=message.ttft_ms,
        reasoning_ms=(message.trace or {}).get("reasoning_ms"),
        latency_ms=message.latency_ms,
        error=error,
        created_at=message.created_at,
        feedback=(FeedbackOut.model_validate(feedback, from_attributes=True) if feedback else None),
        files=list(files),
        tools=list(tools),
    )


def tool_step(call: ToolCall) -> ToolStep:
    return ToolStep(
        call_id=call.call_id,
        tool=call.tool,
        status=call.status,
        label=call.label,
        params=call.label_params or {},
        duration_ms=call.duration_ms,
    )


async def chat_messages(db: AsyncSession, chat_id: UUID, user_id: UUID) -> list[MessageOut]:
    rows = await db.execute(
        select(Message, Feedback)
        .outerjoin(Feedback, and_(Feedback.message_id == Message.id, Feedback.user_id == user_id))
        .where(Message.chat_id == chat_id, Message.deleted_at.is_(None))
        .order_by(Message.created_at, Message.id)
    )
    files: dict[UUID, list[FileOut]] = {}
    for row in await db.scalars(
        select(File)
        .where(File.chat_id == chat_id, File.deleted_at.is_(None), File.message_id.is_not(None))
        .order_by(File.created_at)
    ):
        files.setdefault(row.message_id, []).append(file_out(row))  # type: ignore[arg-type]
    tools: dict[UUID, list[ToolStep]] = {}
    # Скрытые инструменты не уходят в пользовательский API (§9.6).
    for call in await db.scalars(
        select(ToolCall)
        .join(Message, Message.id == ToolCall.message_id)
        .where(Message.chat_id == chat_id, ToolCall.visibility == "visible")
        .order_by(ToolCall.iteration, ToolCall.created_at)
    ):
        tools.setdefault(call.message_id, []).append(tool_step(call))
    return [
        message_out(m, f, files=files.get(m.id, ()), tools=tools.get(m.id, ()))
        for m, f in rows.all()
    ]


def branch(messages: Sequence[Message], leaf_id: UUID | None) -> list[Message]:
    """Активная ветка: от листа вверх по ``parent_id``, в хронологическом порядке."""
    by_id = {m.id: m for m in messages}
    chain: list[Message] = []
    current = by_id.get(leaf_id) if leaf_id else None
    while current is not None:
        chain.append(current)
        current = by_id.get(current.parent_id) if current.parent_id else None
    chain.reverse()
    return chain


async def list_chats(
    db: AsyncSession,
    user_id: UUID,
    *,
    pinned: bool | None,
    folder_id: UUID | None,
    cursor: tuple[datetime, UUID] | None,
    limit: int,
) -> list[Chat]:
    """Чаты с хотя бы одним сообщением, свежие сверху (§7.2: в списке — после первого сообщения)."""
    stmt = select(Chat).where(
        Chat.user_id == user_id, Chat.deleted_at.is_(None), Chat.last_message_at.is_not(None)
    )
    if pinned is not None:
        stmt = stmt.where(Chat.pinned.is_(pinned))
    if folder_id is not None:
        stmt = stmt.where(Chat.folder_id == folder_id)
    if cursor:
        ts, last_id = cursor
        stmt = stmt.where(
            or_(
                Chat.last_message_at < ts,
                and_(Chat.last_message_at == ts, Chat.id < last_id),
            )
        )
    stmt = stmt.order_by(Chat.last_message_at.desc(), Chat.id.desc()).limit(limit)
    return list((await db.scalars(stmt)).all())


def _fragments(headline: str) -> list[SearchFragment]:
    parts: list[SearchFragment] = []
    rest = headline
    while rest:
        start = rest.find(_START)
        if start < 0:
            parts.append(SearchFragment(text=rest, match=False))
            break
        if start:
            parts.append(SearchFragment(text=rest[:start], match=False))
        stop = rest.find(_STOP, start)
        stop = len(rest) if stop < 0 else stop
        parts.append(SearchFragment(text=rest[start + 1 : stop], match=True))
        rest = rest[stop + 1 :]
    return [p for p in parts if p.text]


def _title_fragments(title: str, query: str) -> list[SearchFragment]:
    index = title.casefold().find(query.casefold())
    if index < 0:
        return [SearchFragment(text=title, match=False)]
    end = index + len(query)
    raw = [(title[:index], False), (title[index:end], True), (title[end:], False)]
    return [SearchFragment(text=t, match=m) for t, m in raw if t]


async def search(db: AsyncSession, user_id: UUID, query: str) -> list[SearchHit]:
    """Поиск по названиям чатов и тексту сообщений пользователя (§7.2, Ctrl+K).

    Полнотекстовый поиск с русской морфологией плюс подстрока (индекс pg_trgm) — так находятся
    и словоформы, и номера/коды.
    """
    q = query.strip()
    if not q:
        return []
    tsquery = func.websearch_to_tsquery("russian", q)
    like = f"%{q.replace('%', r'\%').replace('_', r'\_')}%"
    own_chats = and_(Chat.user_id == user_id, Chat.deleted_at.is_(None))

    headline = func.ts_headline(
        "russian",
        Message.content,
        tsquery,
        f"StartSel={_START}, StopSel={_STOP}, MaxWords=18, MinWords=6, MaxFragments=1",
    )
    rank = func.ts_rank(Message.search_vector, tsquery)
    message_rows = (
        await db.execute(
            select(
                Message.id,
                Message.chat_id,
                Chat.title,
                Chat.last_message_at,
                headline,
                Message.content,
            )
            .join(Chat, Chat.id == Message.chat_id)
            .where(
                own_chats,
                Message.deleted_at.is_(None),
                or_(Message.search_vector.op("@@")(tsquery), Message.content.ilike(like)),
            )
            .order_by(rank.desc(), Message.created_at.desc())
            .limit(SEARCH_LIMIT * 3)
        )
    ).all()

    hits: dict[UUID, SearchHit] = {}
    title_rows = (
        await db.execute(
            select(Chat.id, Chat.title, Chat.last_message_at)
            .where(own_chats, Chat.last_message_at.is_not(None), Chat.title.ilike(like))
            .order_by(Chat.last_message_at.desc())
            .limit(SEARCH_LIMIT)
        )
    ).all()
    for chat_id, title, last_at in title_rows:
        hits[chat_id] = SearchHit(
            chat_id=chat_id,
            chat_title=title,
            message_id=None,
            fragments=_title_fragments(title or "", q),
            last_message_at=last_at,
        )
    for message_id, chat_id, title, last_at, head, content in message_rows:
        if chat_id in hits and hits[chat_id].message_id is not None:
            continue  # одно совпадение на чат
        fragments = _fragments(head)
        if not any(f.match for f in fragments):
            # Совпадение по подстроке, которое FTS не подсветил (например, часть кода).
            index = content.casefold().find(q.casefold())
            start = max(0, index - 60)
            fragments = _title_fragments(content[start : index + len(q) + 60], q)
        hits[chat_id] = SearchHit(
            chat_id=chat_id,
            chat_title=title,
            message_id=message_id,
            fragments=fragments,
            last_message_at=last_at,
        )
        if len(hits) >= SEARCH_LIMIT:
            break
    return sorted(
        hits.values(),
        key=lambda h: h.last_message_at or datetime.min.replace(tzinfo=utcnow().tzinfo),
        reverse=True,
    )
