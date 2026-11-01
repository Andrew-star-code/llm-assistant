"""Зависимости FastAPI: сессия, текущий пользователь, проверка прав, CSRF (§6.4, §15).

Права всегда проверяет сервер по сессии; каждый админ-эндпоинт объявляет своё право через
``require(Perm.…)`` — это проверяют тесты безопасности (§18.2).
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import DbDep
from app.core.errors import ForbiddenError, UnauthenticatedError
from app.modules.auth.sessions import SessionData, SessionStore
from app.modules.rbac import service as rbac
from app.modules.rbac.permissions import Perm
from app.modules.security.ipblocks import Blocklist
from app.modules.users.models import User

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-csrf-token"


@dataclass(frozen=True)
class CurrentUser:
    user: User
    session: SessionData
    roles: list[rbac.AssignedRole]
    permissions: frozenset[str]

    @property
    def id(self) -> UUID:
        return self.user.id

    def has(self, perm: Perm | str) -> bool:
        return str(perm) in self.permissions


def client_ip(request: Request) -> str | None:
    """IP клиента; X-Forwarded-For учитывается только от доверенного прокси (nginx)."""
    settings: Settings = request.app.state.settings
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer in settings.trusted_proxies:
        return forwarded.split(",")[0].strip()[:64] or peer
    return peer


def _store(request: Request) -> SessionStore:
    store: SessionStore = request.app.state.sessions
    return store


async def optional_session(request: Request, db: DbDep) -> SessionData | None:
    if hasattr(request.state, "auth_session"):
        cached: SessionData | None = request.state.auth_session
        return cached
    settings: Settings = request.app.state.settings
    token = request.cookies.get(settings.auth.session.cookie_name)
    session = await _store(request).get(db, token) if token else None
    request.state.auth_session = session
    return session


async def current_user(
    request: Request, db: DbDep, session: Annotated[SessionData | None, Depends(optional_session)]
) -> CurrentUser:
    if session is None:
        raise UnauthenticatedError("Требуется вход")
    blocklist: Blocklist | None = getattr(request.app.state, "blocklist", None)
    if blocklist is not None and await blocklist.blocked(db, client_ip(request)):
        raise ForbiddenError("Доступ с этого адреса заблокирован", code="ip_blocked")
    user = await db.get(User, session.user_id)
    if user is None or user.ad_disabled or user.is_block_active(utcnow()):
        # Блокировку проверяем на каждом запросе: сессия могла пережить её в другом процессе.
        await _store(request).revoke_user(db, session.user_id, by=None, reason="blocked")
        await db.commit()
        raise UnauthenticatedError("Сессия завершена")
    roles = await rbac.user_roles(db, user.id)
    granted = await rbac.permissions_for_roles(db, (r.role.id for r in roles))
    return CurrentUser(user, session, roles, rbac.effective_permissions(roles, granted))


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]


def require(*perms: Perm) -> Callable[..., Awaitable[CurrentUser]]:
    """Зависимость: текущий пользователь с правом admin.access и всеми перечисленными правами."""

    async def dependency(user: CurrentUserDep) -> CurrentUser:
        needed = (Perm.ADMIN_ACCESS, *perms)
        if not all(user.has(p) for p in needed):
            raise ForbiddenError("Недостаточно прав")
        return user

    dependency.required_permissions = frozenset(p.value for p in perms)  # type: ignore[attr-defined]
    return dependency


def require_any(*perms: Perm) -> Callable[..., Awaitable[CurrentUser]]:
    """Как ``require``, но достаточно одного из прав (например, все базы или базы своих ролей)."""

    async def dependency(user: CurrentUserDep) -> CurrentUser:
        if not user.has(Perm.ADMIN_ACCESS) or not any(user.has(p) for p in perms):
            raise ForbiddenError("Недостаточно прав")
        return user

    dependency.required_permissions = frozenset(p.value for p in perms)  # type: ignore[attr-defined]
    return dependency


async def verify_csrf(
    request: Request, session: Annotated[SessionData | None, Depends(optional_session)]
) -> None:
    """Double submit: заголовок X-CSRF-Token равен cookie и токену сессии (если она есть)."""
    if request.method in SAFE_METHODS:
        return
    settings: Settings = request.app.state.settings
    header = request.headers.get(CSRF_HEADER, "")
    cookie = request.cookies.get(settings.auth.session.csrf_cookie_name, "")
    valid = bool(header) and secrets.compare_digest(header, cookie)
    if valid and session is not None:
        valid = secrets.compare_digest(header, session.csrf_token)
    if not valid:
        raise ForbiddenError("Проверка CSRF не пройдена", code="csrf_failed")
