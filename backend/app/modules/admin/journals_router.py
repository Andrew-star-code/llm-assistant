"""Админ-API: журнал входов, журнал аудита, диагностика AD (§13.4, §13.6, §6.7).

Каждый эндпоинт объявляет право через ``require(Perm.…)``; диагностика AD пишется в аудит.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select

from app.core.config import Settings
from app.core.deps import DbDep
from app.core.errors import AppError
from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Page,
    decode_datetime_cursor,
    encode_cursor,
)
from app.modules.admin.schemas import (
    AuditOut,
    DiagnosticsIn,
    LoginEventOut,
)
from app.modules.audit import service as audit
from app.modules.audit.models import AuditLog
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.auth.diagnostics import DiagnosticsReport, run_diagnostics
from app.modules.rbac.permissions import Perm
from app.modules.security.models import LoginEvent
from app.modules.users.models import User

router = APIRouter(prefix="/admin", tags=["admin"])

Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


def login_out(e: LoginEvent) -> LoginEventOut:
    return LoginEventOut.model_validate(e, from_attributes=True)


# ------------------------------------------------------------------ журналы


@router.get("/logins", response_model=Page[LoginEventOut], operation_id="adminListLogins")
async def list_logins(
    db: DbDep,
    _: Annotated[CurrentUser, Depends(require(Perm.LOGINS_VIEW))],
    login: str | None = None,
    user_id: UUID | None = None,
    success: bool | None = None,
    flagged: bool | None = None,
    unreviewed: bool | None = None,
    ip: str | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[LoginEventOut]:
    stmt = select(LoginEvent)
    if flagged is True:
        stmt = stmt.where(func.jsonb_array_length(LoginEvent.risk_flags) > 0)
    elif flagged is False:
        stmt = stmt.where(func.jsonb_array_length(LoginEvent.risk_flags) == 0)
    if unreviewed:
        stmt = stmt.where(LoginEvent.reviewed_at.is_(None))
    if ip:
        stmt = stmt.where(LoginEvent.ip == ip.strip())
    if login:
        stmt = stmt.where(LoginEvent.login_attempted.ilike(f"%{login.strip()}%"))
    if user_id:
        stmt = stmt.where(LoginEvent.user_id == user_id)
    if success is not None:
        stmt = stmt.where(LoginEvent.success.is_(success))
    if cursor:
        ts, last_id = decode_datetime_cursor(cursor)
        stmt = stmt.where(
            or_(LoginEvent.ts < ts, (LoginEvent.ts == ts) & (LoginEvent.id < UUID(last_id)))
        )
    rows = list(
        (
            await db.scalars(
                stmt.order_by(LoginEvent.ts.desc(), LoginEvent.id.desc()).limit(limit + 1)
            )
        ).all()
    )
    next_cursor = (
        encode_cursor(rows[limit - 1].ts, rows[limit - 1].id) if len(rows) > limit else None
    )
    return Page(items=[login_out(e) for e in rows[:limit]], next_cursor=next_cursor)


@router.get("/audit", response_model=Page[AuditOut], operation_id="adminListAudit")
async def list_audit(
    db: DbDep,
    _: Annotated[CurrentUser, Depends(require(Perm.AUDIT_VIEW))],
    action: str | None = None,
    actor_id: UUID | None = None,
    target_id: str | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[AuditOut]:
    stmt = select(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
    if cursor:
        ts, last_id = decode_datetime_cursor(cursor)
        stmt = stmt.where(
            or_(AuditLog.ts < ts, (AuditLog.ts == ts) & (AuditLog.id < UUID(last_id)))
        )
    rows = (
        await db.execute(stmt.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(limit + 1))
    ).all()
    items = [
        AuditOut(
            id=e.id,
            ts=e.ts,
            actor_id=e.actor_id,
            actor_name=name,
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
            details=e.details,
            ip=e.ip,
        )
        for e, name in rows[:limit]
    ]
    last = rows[limit - 1][0] if len(rows) > limit else None
    return Page(items=items, next_cursor=encode_cursor(last.ts, last.id) if last else None)


# ------------------------------------------------------------------ диагностика AD


@router.post("/ad/diagnostics", response_model=DiagnosticsReport, operation_id="adminAdDiagnostics")
async def ad_diagnostics(
    body: DiagnosticsIn,
    request: Request,
    db: DbDep,
    actor: Annotated[CurrentUser, Depends(require(Perm.AD_DIAGNOSTICS))],
) -> DiagnosticsReport:
    """Проверка подключения к AD и данных пользователя без проверки пароля (§6.7)."""
    settings: Settings = request.app.state.settings
    directory = request.app.state.ldap_directory
    if directory is None:
        raise AppError("Провайдер ldap выключен в конфигурации", code="ldap_disabled")
    report = await run_diagnostics(directory, settings, body.login)
    await audit.record(
        db,
        actor_id=actor.id,
        action="ad.diagnostics",
        target_type="login",
        target_id=report.login,
        details={"ok": report.ok, "user_found": report.user_found},
        ip=client_ip(request),
    )
    await db.commit()
    return report
