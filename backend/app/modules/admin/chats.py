"""Переписка всех пользователей для админки (§13.3): поиск, список, просмотр чата целиком.

Админ видит всё, что пользователю не показывается: удалённые чаты и сообщения, все ветки,
размышления, скрытые вызовы инструментов, все выданные модели источники и трассировку. Аудит
просмотра пишет роутер.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import NotFoundError
from app.modules.admin.chat_schemas import (
    AdminChatDetail,
    AdminChatItem,
    AdminFeedback,
    AdminFile,
    AdminMessage,
    AdminMessageHit,
    AdminSource,
    AdminToolCall,
    ChatFilter,
    FilterOptions,
    NamedRef,
    ScenarioRef,
    UserRef,
)
from app.modules.chats.models import Chat, Message
from app.modules.chats.service import _fragments, _title_fragments
from app.modules.feedback.models import Feedback
from app.modules.files.models import File
from app.modules.incidents.models import Incident
from app.modules.rag.models import MessageSource
from app.modules.scenarios.models import Scenario
from app.modules.tools.models import ToolCall
from app.modules.users.models import User

type AnySelect = Select[*tuple[Any, ...]]

# Маркеры подсветки — те же, что в пользовательском поиске (``chats.service``).
_START, _STOP = "\x02", "\x03"


def like_pattern(q: str) -> str:
    return f"%{q.replace('%', r'\%').replace('_', r'\_')}%"


def _bounds(f: ChatFilter, tz: str) -> tuple[datetime | None, datetime | None]:
    zone = ZoneInfo(tz)

    def start(d: date) -> datetime:
        return datetime.combine(d, time.min, zone)

    return (
        start(f.date_from) if f.date_from else None,
        start(f.date_to + timedelta(days=1)) if f.date_to else None,
    )


def _text_match(q: str) -> Any:
    tsquery = func.websearch_to_tsquery("russian", q)
    return or_(Message.search_vector.op("@@")(tsquery), Message.content.ilike(like_pattern(q)))


def _user_filters(stmt: AnySelect, f: ChatFilter) -> AnySelect:
    if f.user_id:
        stmt = stmt.where(Chat.user_id == f.user_id)
    if f.department:
        stmt = stmt.where(User.department == f.department)
    if f.scenario_id:
        stmt = stmt.where(Chat.scenario_id == f.scenario_id)
    return stmt


def message_conditions(f: ChatFilter, tz: str) -> list[Any]:
    """Условия на уровне сообщения (поиск): сообщение подходит само."""
    conds: list[Any] = []
    if f.q and f.q.strip():
        conds.append(_text_match(f.q.strip()))
    start, end = _bounds(f, tz)
    if start:
        conds.append(Message.created_at >= start)
    if end:
        conds.append(Message.created_at < end)
    if f.model:
        conds.append(Message.model == f.model)
    deleted = or_(Message.deleted_at.is_not(None), Chat.deleted_at.is_not(None))
    if f.deleted is True:
        conds.append(deleted)
    elif f.deleted is False:
        conds.append(~deleted)
    for flag, cond in (
        (f.disliked, exists().where(Feedback.message_id == Message.id, Feedback.rating < 0)),
        (f.incident, exists().where(Incident.message_id == Message.id)),
        (
            f.attachments,
            exists().where(File.message_id == Message.id, File.kind == "upload"),
        ),
    ):
        if flag is True:
            conds.append(cond)
        elif flag is False:
            conds.append(~cond)
    return conds


def chat_conditions(f: ChatFilter, tz: str) -> list[Any]:
    """Условия на уровне чата (список, выгрузка по выборке): в чате есть подходящее."""
    conds: list[Any] = []
    inner = aliased(Message)
    msg_conds: list[Any] = []
    if f.q and f.q.strip():
        q = f.q.strip()
        tsquery = func.websearch_to_tsquery("russian", q)
        msg_conds.append(
            or_(inner.search_vector.op("@@")(tsquery), inner.content.ilike(like_pattern(q)))
        )
    if f.model:
        msg_conds.append(inner.model == f.model)
    start, end = _bounds(f, tz)
    if start:
        msg_conds.append(inner.created_at >= start)
    if end:
        msg_conds.append(inner.created_at < end)
    if msg_conds:
        conds.append(exists().where(inner.chat_id == Chat.id, *msg_conds))
    if f.deleted is True:
        conds.append(Chat.deleted_at.is_not(None))
    elif f.deleted is False:
        conds.append(Chat.deleted_at.is_(None))
    for flag, cond in (
        (
            f.disliked,
            exists()
            .where(Feedback.message_id == Message.id, Feedback.rating < 0)
            .where(Message.chat_id == Chat.id),
        ),
        (f.incident, exists().where(Incident.chat_id == Chat.id)),
        (f.attachments, exists().where(File.chat_id == Chat.id, File.kind == "upload")),
    ):
        if flag is True:
            conds.append(cond)
        elif flag is False:
            conds.append(~cond)
    return conds


def matching_chats(f: ChatFilter, tz: str) -> AnySelect:
    """id чатов выборки — общий запрос для списка и выгрузки."""
    stmt = select(Chat.id).join(User, User.id == Chat.user_id).where(*chat_conditions(f, tz))
    return _user_filters(stmt, f)


def _user_ref(user: User) -> UserRef:
    return UserRef(
        id=user.id, login=user.login, full_name=user.full_name, department=user.department
    )


async def search_messages(
    db: AsyncSession,
    f: ChatFilter,
    tz: str,
    *,
    cursor: tuple[datetime, UUID] | None,
    limit: int,
) -> list[AdminMessageHit]:
    """Сообщения всех пользователей, свежие сверху; с ``q`` — с подсвеченным фрагментом."""
    q = (f.q or "").strip()
    if q:
        snippet = func.ts_headline(
            "russian",
            Message.content,
            func.websearch_to_tsquery("russian", q),
            f"StartSel={_START}, StopSel={_STOP}, MaxWords=24, MinWords=8, MaxFragments=1",
        )
    else:
        snippet = func.left(Message.content, 240)
    disliked = exists().where(Feedback.message_id == Message.id, Feedback.rating < 0)
    incident = exists().where(Incident.message_id == Message.id)
    attachments = exists().where(File.message_id == Message.id, File.kind == "upload")
    stmt: AnySelect = (
        select(
            Message,
            Chat,
            User,
            Scenario.name,
            snippet,
            disliked,
            incident,
            attachments,
        )
        .join(Chat, Chat.id == Message.chat_id)
        .join(User, User.id == Chat.user_id)
        .outerjoin(Scenario, Scenario.id == Chat.scenario_id)
        .where(*message_conditions(f, tz))
    )
    stmt = _user_filters(stmt, f)
    if cursor:
        ts, last_id = cursor
        stmt = stmt.where(
            or_(
                Message.created_at < ts,
                and_(Message.created_at == ts, Message.id < last_id),
            )
        )
    rows = (
        await db.execute(stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit))
    ).all()
    hits = []
    for message, chat, user, scenario, head, is_disliked, has_incident, has_files in rows:
        if q:
            fragments = _fragments(head)
            if not any(x.match for x in fragments):
                index = message.content.casefold().find(q.casefold())
                begin = max(0, index - 80)
                fragments = _title_fragments(message.content[begin : index + len(q) + 80], q)
        else:
            fragments = _fragments(head)
        hits.append(
            AdminMessageHit(
                message_id=message.id,
                chat_id=chat.id,
                chat_title=chat.title,
                user=_user_ref(user),
                role=message.role,
                created_at=message.created_at,
                fragments=fragments,
                model=message.model,
                scenario=scenario,
                deleted=message.deleted_at is not None or chat.deleted_at is not None,
                is_test=chat.is_test,
                disliked=bool(is_disliked),
                has_incident=bool(has_incident),
                has_attachments=bool(has_files),
            )
        )
    return hits


async def list_chats(
    db: AsyncSession,
    f: ChatFilter,
    tz: str,
    *,
    cursor: tuple[datetime, UUID] | None,
    limit: int,
    only_id: UUID | None = None,
) -> list[AdminChatItem]:
    """Чаты всех пользователей по последней активности (пустые — по времени создания)."""
    activity = func.coalesce(Chat.last_message_at, Chat.created_at)
    counts = (
        select(
            Message.chat_id.label("chat_id"),
            func.count().label("messages"),
        )
        .group_by(Message.chat_id)
        .subquery()
    )
    dislikes = (
        select(Message.chat_id.label("chat_id"), func.count().label("disliked"))
        .join(Feedback, Feedback.message_id == Message.id)
        .where(Feedback.rating < 0)
        .group_by(Message.chat_id)
        .subquery()
    )
    incidents = (
        select(Incident.chat_id.label("chat_id"), func.count().label("incidents"))
        .where(Incident.chat_id.is_not(None))
        .group_by(Incident.chat_id)
        .subquery()
    )
    stmt: AnySelect = (
        select(
            Chat,
            User,
            Scenario.name,
            func.coalesce(counts.c.messages, 0),
            func.coalesce(dislikes.c.disliked, 0),
            func.coalesce(incidents.c.incidents, 0),
        )
        .join(User, User.id == Chat.user_id)
        .outerjoin(Scenario, Scenario.id == Chat.scenario_id)
        .outerjoin(counts, counts.c.chat_id == Chat.id)
        .outerjoin(dislikes, dislikes.c.chat_id == Chat.id)
        .outerjoin(incidents, incidents.c.chat_id == Chat.id)
        .where(*chat_conditions(f, tz))
    )
    stmt = _user_filters(stmt, f)
    if only_id is not None:
        stmt = stmt.where(Chat.id == only_id)
    if cursor:
        ts, last_id = cursor
        stmt = stmt.where(or_(activity < ts, and_(activity == ts, Chat.id < last_id)))
    rows = (await db.execute(stmt.order_by(activity.desc(), Chat.id.desc()).limit(limit))).all()
    return [
        AdminChatItem(
            id=chat.id,
            title=chat.title,
            user=_user_ref(user),
            scenario=scenario,
            is_test=chat.is_test,
            created_at=chat.created_at,
            last_message_at=chat.last_message_at,
            deleted_at=chat.deleted_at,
            messages=n_messages,
            disliked=n_disliked,
            incidents=n_incidents,
        )
        for chat, user, scenario, n_messages, n_disliked, n_incidents in rows
    ]


async def chat_item(db: AsyncSession, chat_id: UUID) -> AdminChatItem:
    """Строка списка для одного чата (после восстановления)."""
    stmt_items = await list_chats(db, ChatFilter(), "UTC", cursor=None, limit=1, only_id=chat_id)
    if not stmt_items:
        raise NotFoundError("Чат не найден")
    return stmt_items[0]


def chat_activity(item: AdminChatItem) -> datetime:
    return item.last_message_at or item.created_at


async def chat_detail(db: AsyncSession, chat_id: UUID) -> AdminChatDetail:
    chat = await db.get(Chat, chat_id)
    if chat is None:
        raise NotFoundError("Чат не найден")
    owner = await db.get(User, chat.user_id)
    if owner is None:
        raise NotFoundError("Владелец чата не найден")
    deleted_by = await db.get(User, chat.deleted_by) if chat.deleted_by else None
    scenario = await db.get(Scenario, chat.scenario_id) if chat.scenario_id else None
    messages = list(
        (
            await db.scalars(
                select(Message)
                .where(Message.chat_id == chat_id)
                .order_by(Message.created_at, Message.id)
            )
        ).all()
    )
    ids = [m.id for m in messages]
    calls: dict[UUID, list[AdminToolCall]] = {}
    sources: dict[UUID, list[AdminSource]] = {}
    files: dict[UUID, list[AdminFile]] = {}
    feedback: dict[UUID, AdminFeedback] = {}
    if ids:
        for call in await db.scalars(
            select(ToolCall)
            .where(ToolCall.message_id.in_(ids))
            .order_by(ToolCall.iteration, ToolCall.created_at)
        ):
            calls.setdefault(call.message_id, []).append(
                AdminToolCall.model_validate(call, from_attributes=True)
            )
        for src in await db.scalars(
            select(MessageSource)
            .where(MessageSource.message_id.in_(ids))
            .order_by(MessageSource.index)
        ):
            sources.setdefault(src.message_id, []).append(
                AdminSource.model_validate(src, from_attributes=True)
            )
        for fb in await db.scalars(select(Feedback).where(Feedback.message_id.in_(ids))):
            feedback[fb.message_id] = AdminFeedback.model_validate(fb, from_attributes=True)
    for file in await db.scalars(
        select(File).where(File.chat_id == chat_id).order_by(File.created_at)
    ):
        if file.message_id is not None:
            files.setdefault(file.message_id, []).append(
                AdminFile.model_validate(file, from_attributes=True)
            )
    return AdminChatDetail(
        id=chat.id,
        title=chat.title,
        user=_user_ref(owner),
        scenario=(
            ScenarioRef(id=scenario.id, code=scenario.code, name=scenario.name)
            if scenario
            else None
        ),
        is_test=chat.is_test,
        created_at=chat.created_at,
        last_message_at=chat.last_message_at,
        deleted_at=chat.deleted_at,
        deleted_by=_user_ref(deleted_by) if deleted_by else None,
        active_leaf_id=chat.active_leaf_id,
        messages=[
            AdminMessage(
                id=m.id,
                parent_id=m.parent_id,
                role=m.role,
                content=m.content,
                reasoning=m.reasoning,
                status=m.status,
                thinking=m.thinking,
                model=m.model,
                finish_reason=m.finish_reason,
                prompt_tokens=m.prompt_tokens,
                completion_tokens=m.completion_tokens,
                reasoning_tokens=m.reasoning_tokens,
                ttft_ms=m.ttft_ms,
                latency_ms=m.latency_ms,
                reasoning_ms=(m.trace or {}).get("reasoning_ms"),
                error=m.error,
                trace=m.trace,
                created_at=m.created_at,
                deleted_at=m.deleted_at,
                tool_calls=calls.get(m.id, []),
                sources=sources.get(m.id, []),
                files=files.get(m.id, []),
                feedback=feedback.get(m.id),
            )
            for m in messages
        ],
    )


async def filter_options(db: AsyncSession) -> FilterOptions:
    departments = (
        await db.scalars(
            select(User.department)
            .where(User.department.is_not(None))
            .distinct()
            .order_by(User.department)
        )
    ).all()
    scenarios = (await db.execute(select(Scenario.id, Scenario.name).order_by(Scenario.name))).all()
    models = (
        await db.scalars(
            select(Message.model)
            .where(Message.model.is_not(None))
            .distinct()
            .order_by(Message.model)
        )
    ).all()
    return FilterOptions(
        departments=[d for d in departments if d],
        scenarios=[NamedRef(id=i, name=n) for i, n in scenarios],
        models=[m for m in models if m],
    )
