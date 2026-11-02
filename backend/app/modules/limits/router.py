"""Лимиты пользователя (§12.4): остатки по всем метрикам и ближайшая к исчерпанию."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.deps import DbDep
from app.modules.auth.deps import CurrentUserDep
from app.modules.limits.service import Limits, status_payload

router = APIRouter(tags=["limits"])


class LimitItem(BaseModel):
    metric: str
    window: str | None
    model_role: str | None
    thinking: bool
    limit: int
    used: int
    remaining: int
    reset_at: datetime | None


class NearestLimit(BaseModel):
    metric: str
    window: str | None
    limit: int
    used: int
    remaining: int
    reset_at: datetime | None


class LimitsOut(BaseModel):
    items: list[LimitItem]
    nearest: NearestLimit | None
    blocked: bool  # исчерпан лимит, действующий на все сообщения: поле ввода блокируется


@router.get("/limits", response_model=LimitsOut, operation_id="getMyLimits")
async def my_limits(request: Request, db: DbDep, current: CurrentUserDep) -> LimitsOut:
    """То же, что событие SSE ``limits`` в конце ответа (§8.5)."""
    limits: Limits = request.app.state.limits
    return LimitsOut.model_validate(status_payload(await limits.status(db, current.id)))
