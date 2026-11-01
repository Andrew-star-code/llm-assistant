"""Инциденты в админке — минимум этапа 4: список с фильтрами (§13.5; полностью — этап 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import DbDep
from app.modules.auth.deps import CurrentUser, require
from app.modules.incidents.models import Incident
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/admin/incidents", tags=["admin"])


class IncidentOut(BaseModel):
    id: UUID
    type: str
    severity: str
    status: str
    title: str
    occurrences: int
    first_seen: datetime
    last_seen: datetime
    user_id: UUID | None
    chat_id: UUID | None
    message_id: UUID | None
    payload: dict[str, Any] | None


@router.get("", response_model=list[IncidentOut], operation_id="adminListIncidents")
async def list_incidents(
    db: DbDep,
    _: Annotated[CurrentUser, Depends(require(Perm.INCIDENTS_VIEW))],
    status: Annotated[str | None, Query()] = None,
    type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[IncidentOut]:
    stmt = select(Incident)
    if status:
        stmt = stmt.where(Incident.status == status)
    if type:
        stmt = stmt.where(Incident.type == type)
    rows = (await db.scalars(stmt.order_by(Incident.last_seen.desc()).limit(limit))).all()
    return [IncidentOut.model_validate(r, from_attributes=True) for r in rows]
