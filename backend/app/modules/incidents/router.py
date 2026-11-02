"""Инциденты в админке (§13.5): список, сводка для меню и дашборда, карточка, жизненный цикл,
ответственный, решение, комментарии. Изменения пишутся в аудит.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from app.core.deps import DbDep
from app.core.errors import AppError, NotFoundError
from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Page,
    decode_datetime_cursor,
    encode_cursor,
)
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.incidents.models import Incident, IncidentComment
from app.modules.incidents.service import HIGH, STATUSES
from app.modules.rbac.models import Role, UserRole
from app.modules.rbac.permissions import ADMIN, SUPERADMIN, Perm
from app.modules.users.models import User

router = APIRouter(prefix="/admin/incidents", tags=["admin"])

Viewer = Annotated[CurrentUser, Depends(require(Perm.INCIDENTS_VIEW))]
Manager = Annotated[CurrentUser, Depends(require(Perm.INCIDENTS_MANAGE))]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Status = Literal["new", "in_progress", "resolved", "false_positive"]


class PersonRef(BaseModel):
    id: UUID
    login: str
    full_name: str


class IncidentOut(BaseModel):
    id: UUID
    type: str
    severity: str
    status: str
    title: str
    occurrences: int
    first_seen: datetime
    last_seen: datetime
    user: PersonRef | None
    assignee: PersonRef | None
    chat_id: UUID | None
    message_id: UUID | None


class CommentOut(BaseModel):
    id: UUID
    author: PersonRef | None
    text: str
    created_at: datetime


class IncidentDetail(IncidentOut):
    resolution: str | None
    payload: dict[str, Any] | None
    comments: list[CommentOut]


class Summary(BaseModel):
    new: int = Field(description="Новые инциденты — счётчик в меню.")
    new_high: int = Field(description="Из них high и critical — подсветка.")
    open: int


class IncidentUpdate(BaseModel):
    status: Status | None = None
    assigned_to: UUID | None = None
    resolution: str | None = Field(None, max_length=5000)


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


def _person(user: User | None) -> PersonRef | None:
    return PersonRef(id=user.id, login=user.login, full_name=user.full_name) if user else None


def _out(row: Incident, user: User | None, assignee: User | None) -> IncidentOut:
    return IncidentOut(
        id=row.id,
        type=row.type,
        severity=row.severity,
        status=row.status,
        title=row.title,
        occurrences=row.occurrences,
        first_seen=row.first_seen,
        last_seen=row.last_seen,
        user=_person(user),
        assignee=_person(assignee),
        chat_id=row.chat_id,
        message_id=row.message_id,
    )


@router.get("", response_model=Page[IncidentOut], operation_id="adminListIncidents")
async def list_incidents(
    db: DbDep,
    _: Viewer,
    status: Annotated[str | None, Query()] = None,
    type: Annotated[str | None, Query()] = None,
    severity: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[IncidentOut]:
    owner, assignee = aliased(User), aliased(User)
    stmt = (
        select(Incident, owner, assignee)
        .outerjoin(owner, owner.id == Incident.user_id)
        .outerjoin(assignee, assignee.id == Incident.assigned_to)
    )
    if status == "open":
        stmt = stmt.where(Incident.status.in_(("new", "in_progress")))
    elif status:
        stmt = stmt.where(Incident.status == status)
    if type:
        stmt = stmt.where(Incident.type == type)
    if severity:
        stmt = stmt.where(Incident.severity == severity)
    if q and q.strip():
        stmt = stmt.where(Incident.title.ilike(f"%{q.strip()}%"))
    if cursor:
        ts, last_id = decode_datetime_cursor(cursor)
        stmt = stmt.where(
            or_(
                Incident.last_seen < ts,
                and_(Incident.last_seen == ts, Incident.id < UUID(last_id)),
            )
        )
    rows = (
        await db.execute(
            stmt.order_by(Incident.last_seen.desc(), Incident.id.desc()).limit(limit + 1)
        )
    ).all()
    items = [_out(r, u, a) for r, u, a in rows[:limit]]
    last = items[-1] if len(rows) > limit else None
    return Page(items=items, next_cursor=encode_cursor(last.last_seen, last.id) if last else None)


@router.get("/summary", response_model=Summary, operation_id="adminIncidentsSummary")
async def summary(db: DbDep, _: Viewer) -> Summary:
    new, new_high, open_ = (
        await db.execute(
            select(
                func.count().filter(Incident.status == "new"),
                func.count().filter(Incident.status == "new", Incident.severity.in_(HIGH)),
                func.count().filter(Incident.status.in_(("new", "in_progress"))),
            )
        )
    ).one()
    return Summary(new=int(new), new_high=int(new_high), open=int(open_))


@router.get("/assignees", response_model=list[PersonRef], operation_id="adminIncidentAssignees")
async def assignees(db: DbDep, _: Viewer) -> list[PersonRef]:
    """Кому можно назначить инцидент: администраторы и суперадминистраторы."""
    rows = (
        await db.scalars(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code.in_((ADMIN, SUPERADMIN)))
            .distinct()
            .order_by(User.full_name)
        )
    ).all()
    return [PersonRef(id=u.id, login=u.login, full_name=u.full_name) for u in rows]


async def _detail(db: DbDep, row: Incident) -> IncidentDetail:
    user = await db.get(User, row.user_id) if row.user_id else None
    assignee = await db.get(User, row.assigned_to) if row.assigned_to else None
    comments = (
        await db.execute(
            select(IncidentComment, User)
            .outerjoin(User, User.id == IncidentComment.author_id)
            .where(IncidentComment.incident_id == row.id)
            .order_by(IncidentComment.created_at)
        )
    ).all()
    return IncidentDetail(
        **_out(row, user, assignee).model_dump(),
        resolution=row.resolution,
        payload=row.payload,
        comments=[
            CommentOut(id=c.id, author=_person(a), text=c.text, created_at=c.created_at)
            for c, a in comments
        ],
    )


async def _get(db: DbDep, incident_id: UUID) -> Incident:
    row = await db.get(Incident, incident_id)
    if row is None:
        raise NotFoundError("Инцидент не найден")
    return row


@router.get("/{incident_id}", response_model=IncidentDetail, operation_id="adminGetIncident")
async def get_incident(incident_id: UUID, db: DbDep, _: Viewer) -> IncidentDetail:
    return await _detail(db, await _get(db, incident_id))


@router.patch("/{incident_id}", response_model=IncidentDetail, operation_id="adminUpdateIncident")
async def update_incident(
    incident_id: UUID, body: IncidentUpdate, request: Request, db: DbDep, actor: Manager
) -> IncidentDetail:
    row = await _get(db, incident_id)
    changes: dict[str, Any] = {}
    if body.status is not None and body.status != row.status:
        if body.status not in STATUSES:  # pragma: no cover — проверено схемой
            raise AppError("Неизвестный статус", code="bad_status")
        changes["status"] = [row.status, body.status]
        row.status = body.status
    if "assigned_to" in body.model_fields_set and body.assigned_to != row.assigned_to:
        if body.assigned_to is not None and await db.get(User, body.assigned_to) is None:
            raise NotFoundError("Пользователь не найден")
        changes["assigned_to"] = str(body.assigned_to) if body.assigned_to else None
        row.assigned_to = body.assigned_to
    if "resolution" in body.model_fields_set and body.resolution != row.resolution:
        changes["resolution"] = "изменено"
        row.resolution = body.resolution
    if changes:
        await audit.record(
            db, actor_id=actor.id, action="incident.update", target_type="incident",
            target_id=row.id, details=changes, ip=client_ip(request),
        )  # fmt: skip
        await db.commit()
    return await _detail(db, row)


@router.post(
    "/{incident_id}/comments",
    response_model=IncidentDetail,
    status_code=201,
    operation_id="adminCommentIncident",
)
async def comment(
    incident_id: UUID, body: CommentIn, request: Request, db: DbDep, actor: Manager
) -> IncidentDetail:
    row = await _get(db, incident_id)
    db.add(IncidentComment(incident_id=row.id, author_id=actor.id, text=body.text.strip()))
    await audit.record(
        db, actor_id=actor.id, action="incident.comment", target_type="incident",
        target_id=row.id, details={}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return await _detail(db, row)
