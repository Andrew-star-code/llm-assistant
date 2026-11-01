"""Админка «Обратная связь» (§13.2): лайки и дизлайки с причинами, переход в чат, выгрузка.

Список показывает отрывки вопроса и ответа, как поиск по переписке; чат целиком открывается в
«Переписке» (там просмотр пишется в аудит). Выгрузка XLSX — тоже в аудит.
"""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import aliased

from app.core.deps import DbDep, SettingsDep
from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Page,
    decode_datetime_cursor,
    encode_cursor,
)
from app.modules.admin.chat_schemas import UserRef
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.chats.models import Chat, Message
from app.modules.feedback.models import Feedback
from app.modules.rbac.permissions import Perm
from app.modules.scenarios.models import Scenario
from app.modules.users.models import User

router = APIRouter(prefix="/admin/feedback", tags=["admin"])

Viewer = Annotated[CurrentUser, Depends(require(Perm.FEEDBACK_VIEW))]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
EXCERPT = 400
EXPORT_LIMIT = 50_000


class FeedbackFilter(BaseModel):
    rating: int | None = None  # 1 | -1
    reason: str | None = None
    user_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


class FeedbackItem(BaseModel):
    id: UUID
    rating: int
    reasons: list[str]
    comment: str | None
    created_at: datetime
    user: UserRef
    chat_id: UUID
    chat_title: str | None
    message_id: UUID
    question: str
    answer: str
    model: str | None
    scenario: str | None


class FeedbackStats(BaseModel):
    likes: int
    dislikes: int
    reasons: dict[str, int]


Filter = Annotated[FeedbackFilter, Query()]


def _conditions(f: FeedbackFilter, tz: str) -> list[Any]:
    zone = ZoneInfo(tz)
    conds: list[Any] = []
    if f.rating in (1, -1):
        conds.append(Feedback.rating == f.rating)
    if f.reason:
        conds.append(Feedback.reasons.contains([f.reason]))
    if f.user_id:
        conds.append(Feedback.user_id == f.user_id)
    if f.date_from:
        conds.append(Feedback.created_at >= datetime.combine(f.date_from, time.min, zone))
    if f.date_to:
        end = datetime.combine(f.date_to + timedelta(days=1), time.min, zone)
        conds.append(Feedback.created_at < end)
    return conds


def _query(f: FeedbackFilter, tz: str) -> Any:
    question = aliased(Message)
    return (
        select(Feedback, Message, question.content, Chat, User, Scenario.name)
        .join(Message, Message.id == Feedback.message_id)
        .outerjoin(question, question.id == Message.parent_id)
        .join(Chat, Chat.id == Message.chat_id)
        .join(User, User.id == Feedback.user_id)
        .outerjoin(Scenario, Scenario.id == Chat.scenario_id)
        .where(*_conditions(f, tz))
    )


def _excerpt(text: str | None) -> str:
    text = (text or "").strip()
    return text if len(text) <= EXCERPT else text[: EXCERPT - 1] + "…"


def _item(row: Any) -> FeedbackItem:
    fb, answer, question, chat, user, scenario = row
    return FeedbackItem(
        id=fb.id,
        rating=fb.rating,
        reasons=fb.reasons,
        comment=fb.comment,
        created_at=fb.created_at,
        user=UserRef(
            id=user.id, login=user.login, full_name=user.full_name, department=user.department
        ),
        chat_id=chat.id,
        chat_title=chat.title,
        message_id=answer.id,
        question=_excerpt(question),
        answer=_excerpt(answer.content),
        model=answer.model,
        scenario=scenario,
    )


@router.get("", response_model=Page[FeedbackItem], operation_id="adminListFeedback")
async def list_feedback(
    db: DbDep,
    settings: SettingsDep,
    _: Viewer,
    f: Filter,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[FeedbackItem]:
    stmt = _query(f, settings.chat.timezone)
    if cursor:
        ts, last_id = decode_datetime_cursor(cursor)
        stmt = stmt.where(
            or_(
                Feedback.created_at < ts,
                and_(Feedback.created_at == ts, Feedback.id < UUID(last_id)),
            )
        )
    rows = (
        await db.execute(
            stmt.order_by(Feedback.created_at.desc(), Feedback.id.desc()).limit(limit + 1)
        )
    ).all()
    items = [_item(r) for r in rows[:limit]]
    last = items[-1] if len(rows) > limit else None
    return Page(items=items, next_cursor=encode_cursor(last.created_at, last.id) if last else None)


@router.get("/stats", response_model=FeedbackStats, operation_id="adminFeedbackStats")
async def stats(db: DbDep, settings: SettingsDep, _: Viewer, f: Filter) -> FeedbackStats:
    conds = _conditions(f, settings.chat.timezone)
    totals = dict(
        (
            await db.execute(
                select(Feedback.rating, func.count()).where(*conds).group_by(Feedback.rating)
            )
        ).all()
    )
    reason = func.jsonb_array_elements_text(Feedback.reasons).table_valued("value")
    by_reason = (
        await db.execute(
            select(reason.c.value, func.count())
            .select_from(Feedback)
            .join(reason, true())
            .where(*conds)
            .group_by(reason.c.value)
        )
    ).all()
    return FeedbackStats(
        likes=int(totals.get(1, 0)),
        dislikes=int(totals.get(-1, 0)),
        reasons={str(r): int(n) for r, n in by_reason},
    )


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="adminExportFeedback",
)
async def export_feedback(
    request: Request, db: DbDep, settings: SettingsDep, actor: Viewer, f: Filter
) -> Response:
    """XLSX: строка на оценку — пользователь, вопрос, ответ, причины, комментарий."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from app.modules.exports.service import xlsx_cell

    zone = ZoneInfo(settings.chat.timezone)
    rows = (
        await db.execute(
            _query(f, settings.chat.timezone)
            .order_by(Feedback.created_at.desc())
            .limit(EXPORT_LIMIT)
        )
    ).all()
    book = Workbook()
    sheet = book.active
    assert sheet is not None  # noqa: S101 — у новой книги лист есть всегда
    sheet.title = "Обратная связь"
    sheet.append(
        ["Время", "Оценка", "Причины", "Комментарий", "Логин", "ФИО", "Отдел", "Сценарий",
         "Модель", "Вопрос", "Ответ", "Чат", "Сообщение"]
    )  # fmt: skip
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        item = _item(row)
        sheet.append(
            [
                item.created_at.astimezone(zone).replace(tzinfo=None),
                item.rating,
                ", ".join(item.reasons) or None,
                xlsx_cell(item.comment),
                item.user.login,
                item.user.full_name,
                item.user.department,
                item.scenario,
                item.model,
                xlsx_cell(row[2]),
                xlsx_cell(row[1].content),
                str(item.chat_id),
                str(item.message_id),
            ]
        )
    buffer = io.BytesIO()
    book.save(buffer)
    details = {"rows": len(rows), **f.model_dump(mode="json", exclude_none=True)}
    await audit.record(
        db, actor_id=actor.id, action="feedback.export", target_type="feedback",
        target_id="export", details=details, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="feedback.xlsx"; '
            f"filename*=UTF-8''{quote('Обратная связь.xlsx')}",
            "X-Content-Type-Options": "nosniff",
        },
    )
