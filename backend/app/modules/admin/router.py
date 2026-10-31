"""Админ-API этапа 1: ``/api/admin/*`` (§13).

Каждый эндпоинт объявляет право через ``require(Perm.…)``; всё, что админ делает с чужими
данными, пишется в журнал аудита в той же транзакции (§13.6).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import DbDep, StorageDep
from app.core.errors import AppError, NotFoundError
from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Page,
    decode_cursor,
    decode_datetime_cursor,
    encode_cursor,
)
from app.modules.admin.schemas import (
    AuditOut,
    BlockIn,
    DiagnosticsIn,
    LoginEventOut,
    RevokedOut,
    RoleListItem,
    RolesIn,
    SessionOut,
    UserCard,
    UserListItem,
)
from app.modules.audit import service as audit
from app.modules.audit.models import AuditLog
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.auth.diagnostics import DiagnosticsReport, run_diagnostics
from app.modules.auth.models import UserSession
from app.modules.auth.sessions import SessionStore
from app.modules.rbac import service as rbac
from app.modules.rbac.models import Role, RolePermission, UserRole
from app.modules.rbac.permissions import Perm
from app.modules.security.bruteforce import BruteforceGuard
from app.modules.security.models import LoginEvent
from app.modules.users.models import User
from app.modules.users.profile import photo_media_type, role_out

router = APIRouter(prefix="/admin", tags=["admin"])

Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


def _sessions(request: Request) -> SessionStore:
    store: SessionStore = request.app.state.sessions
    return store


async def _get_user(db: AsyncSession, user_id: UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("Пользователь не найден")
    return user


def _login_out(e: LoginEvent) -> LoginEventOut:
    return LoginEventOut.model_validate(e, from_attributes=True)


# ------------------------------------------------------------------ пользователи


@router.get("/users", response_model=Page[UserListItem], operation_id="adminListUsers")
async def list_users(
    db: DbDep,
    _: Annotated[CurrentUser, Depends(require(Perm.USERS_VIEW))],
    q: str | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[UserListItem]:
    """Поиск по логину, ФИО, отделу и должности; сортировка по ФИО."""
    stmt = select(User)
    if q and (term := q.strip()):
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                User.login.ilike(like),
                User.full_name.ilike(like),
                User.department.ilike(like),
                User.title.ilike(like),
            )
        )
    if cursor:
        name, last_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(User.full_name > name, (User.full_name == name) & (User.id > UUID(last_id)))
        )
    rows = list((await db.scalars(stmt.order_by(User.full_name, User.id).limit(limit + 1))).all())
    items = [UserListItem.model_validate(u, from_attributes=True) for u in rows[:limit]]
    next_cursor = (
        encode_cursor(rows[limit - 1].full_name, rows[limit - 1].id) if len(rows) > limit else None
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get("/users/{user_id}", response_model=UserCard, operation_id="adminGetUser")
async def get_user(
    user_id: UUID,
    request: Request,
    db: DbDep,
    _: Annotated[CurrentUser, Depends(require(Perm.USERS_VIEW))],
) -> UserCard:
    user = await _get_user(db, user_id)
    store = _sessions(request)
    now = utcnow()
    session_rows = (
        await db.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.created_at.desc())
            .limit(50)
        )
    ).all()
    sessions = [
        SessionOut(
            id=s.id,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
            ip=s.ip,
            user_agent=s.user_agent,
            provider=s.provider,
            active=await store.is_active(s.token_hash),
        )
        for s in session_rows
    ]
    logins = (
        await db.scalars(
            select(LoginEvent)
            .where(LoginEvent.user_id == user_id)
            .order_by(LoginEvent.ts.desc())
            .limit(20)
        )
    ).all()
    card = UserCard.model_validate(
        {
            **{k: getattr(user, k) for k in UserCard.model_fields if hasattr(user, k)},
            "has_photo": user.photo_key is not None,
            "roles": role_out(await rbac.user_roles(db, user_id)),
            "sessions": [s for s in sessions if s.active],
            "recent_logins": [_login_out(e) for e in logins],
        }
    )
    return card


@router.get(
    "/users/{user_id}/photo",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}, 404: {"description": "Фото нет"}},
    operation_id="adminGetUserPhoto",
)
async def get_user_photo(
    user_id: UUID,
    db: DbDep,
    storage: StorageDep,
    _: Annotated[CurrentUser, Depends(require(Perm.USERS_VIEW))],
) -> Response:
    user = await _get_user(db, user_id)
    data = await storage.get(user.photo_key) if user.photo_key else None
    if data is None:
        raise NotFoundError("Фото нет")
    return Response(data, media_type=photo_media_type(data), headers={"Cache-Control": "private"})


@router.post("/users/{user_id}/block", response_model=RevokedOut, operation_id="adminBlockUser")
async def block_user(
    user_id: UUID,
    body: BlockIn,
    request: Request,
    db: DbDep,
    actor: Annotated[CurrentUser, Depends(require(Perm.USERS_BLOCK))],
) -> RevokedOut:
    """Блокирует пользователя с причиной и сроком и сразу завершает все его сессии (§6.4)."""
    if user_id == actor.id:
        raise AppError("Нельзя заблокировать самого себя", code="self_block")
    if body.until is not None and body.until <= utcnow():
        raise AppError("Срок блокировки должен быть в будущем", code="bad_until")
    user = await _get_user(db, user_id)
    user.is_blocked = True
    user.blocked_reason = body.reason
    user.blocked_until = body.until
    user.blocked_by = actor.id
    revoked = await _sessions(request).revoke_user(db, user_id, by=actor.id, reason="blocked")
    await audit.record(
        db,
        actor_id=actor.id,
        action="user.block",
        target_type="user",
        target_id=user_id,
        details={
            "reason": body.reason,
            "until": body.until.isoformat() if body.until else None,
            "sessions_revoked": revoked,
        },
        ip=client_ip(request),
    )
    await db.commit()
    return RevokedOut(revoked=revoked)


@router.post("/users/{user_id}/unblock", status_code=204, operation_id="adminUnblockUser")
async def unblock_user(
    user_id: UUID,
    request: Request,
    db: DbDep,
    actor: Annotated[CurrentUser, Depends(require(Perm.USERS_BLOCK))],
) -> None:
    """Снимает блокировку и временную блокировку логина за перебор паролей."""
    user = await _get_user(db, user_id)
    user.is_blocked = False
    user.blocked_reason = user.blocked_until = user.blocked_by = None
    guard: BruteforceGuard = request.app.state.bruteforce
    await guard.unlock_login(user.login)
    await audit.record(
        db,
        actor_id=actor.id,
        action="user.unblock",
        target_type="user",
        target_id=user_id,
        ip=client_ip(request),
    )
    await db.commit()


@router.post("/users/{user_id}/logout", response_model=RevokedOut, operation_id="adminLogoutUser")
async def logout_user(
    user_id: UUID,
    request: Request,
    db: DbDep,
    actor: Annotated[CurrentUser, Depends(require(Perm.USERS_LOGOUT))],
) -> RevokedOut:
    await _get_user(db, user_id)
    revoked = await _sessions(request).revoke_user(db, user_id, by=actor.id, reason="admin_logout")
    await audit.record(
        db,
        actor_id=actor.id,
        action="user.logout",
        target_type="user",
        target_id=user_id,
        details={"sessions_revoked": revoked},
        ip=client_ip(request),
    )
    await db.commit()
    return RevokedOut(revoked=revoked)


@router.delete("/sessions/{session_id}", status_code=204, operation_id="adminRevokeSession")
async def revoke_session(
    session_id: UUID,
    request: Request,
    db: DbDep,
    actor: Annotated[CurrentUser, Depends(require(Perm.USERS_LOGOUT))],
) -> None:
    row = await db.get(UserSession, session_id)
    if row is None:
        raise NotFoundError("Сессия не найдена")
    await _sessions(request).revoke(db, session_id, by=actor.id, reason="admin_revoke")
    await audit.record(
        db,
        actor_id=actor.id,
        action="session.revoke",
        target_type="session",
        target_id=session_id,
        details={"user_id": str(row.user_id)},
        ip=client_ip(request),
    )
    await db.commit()


@router.put("/users/{user_id}/roles", response_model=UserCard, operation_id="adminSetUserRoles")
async def set_user_roles(
    user_id: UUID,
    body: RolesIn,
    request: Request,
    db: DbDep,
    actor: Annotated[CurrentUser, Depends(require(Perm.ROLES_MANAGE))],
) -> UserCard:
    """Задаёт ручные роли. Роли из AD пересчитываются при входе и синхронизации."""
    await _get_user(db, user_id)
    added, removed = await rbac.set_manual_roles(
        db,
        user_id=user_id,
        role_ids=body.role_ids,
        actor_id=actor.id,
        actor_permissions=actor.permissions,
    )
    if added or removed:
        await audit.record(
            db,
            actor_id=actor.id,
            action="user.roles",
            target_type="user",
            target_id=user_id,
            details={"added": added, "removed": removed},
            ip=client_ip(request),
        )
    await db.commit()
    return await get_user(user_id, request, db, actor)


# ------------------------------------------------------------------ роли


@router.get("/roles", response_model=list[RoleListItem], operation_id="adminListRoles")
async def list_roles(
    db: DbDep, _: Annotated[CurrentUser, Depends(require(Perm.USERS_VIEW))]
) -> list[RoleListItem]:
    """Все роли с числом пользователей; роли без пользователей — кандидаты на перенос (§6.3)."""
    counts = dict(
        (
            await db.execute(
                select(UserRole.role_id, func.count(func.distinct(UserRole.user_id))).group_by(
                    UserRole.role_id
                )
            )
        ).all()
    )
    perms: dict[UUID, list[str]] = {}
    for role_id, code in (
        await db.execute(select(RolePermission.role_id, RolePermission.permission_code))
    ).all():
        perms.setdefault(role_id, []).append(code)
    roles = (await db.scalars(select(Role).order_by(Role.kind, Role.name))).all()
    return [
        RoleListItem(
            id=r.id,
            code=r.code,
            name=r.name,
            kind=r.kind,
            description=r.description,
            users=counts.get(r.id, 0),
            permissions=sorted(perms.get(r.id, [])),
        )
        for r in roles
    ]


# ------------------------------------------------------------------ журналы


@router.get("/logins", response_model=Page[LoginEventOut], operation_id="adminListLogins")
async def list_logins(
    db: DbDep,
    _: Annotated[CurrentUser, Depends(require(Perm.LOGINS_VIEW))],
    login: str | None = None,
    user_id: UUID | None = None,
    success: bool | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[LoginEventOut]:
    stmt = select(LoginEvent)
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
    return Page(items=[_login_out(e) for e in rows[:limit]], next_cursor=next_cursor)


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
