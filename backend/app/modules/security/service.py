"""Запись событий входа в журнал ``login_events``."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.security.models import LoginEvent

log = structlog.stdlib.get_logger("app.security")


async def record_login_event(
    db: AsyncSession,
    *,
    login: str,
    method: str,
    success: bool,
    ip: str | None,
    user_agent: str | None,
    user_id: UUID | None = None,
    failure_reason: str | None = None,
    risk_flags: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> LoginEvent:
    event = LoginEvent(
        user_id=user_id,
        login_attempted=login[:256],
        method=method,
        success=success,
        ip=ip,
        user_agent=(user_agent or "")[:1000] or None,
        failure_reason=failure_reason,
        risk_flags=risk_flags or [],
        details=details or {},
    )
    db.add(event)
    await db.flush()
    log.info(
        "auth.login",
        login=event.login_attempted,
        method=method,
        success=success,
        reason=failure_reason,
        ip=ip,
    )
    return event
