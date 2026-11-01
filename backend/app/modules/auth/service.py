"""Поток входа (§6.2): нормализация логина → пустой пароль → счётчики перебора → провайдер →
пользователь и роли → блокировка → сессия → журнал входов.

Пользователь при любой ошибке видит одно сообщение «Неверный логин или пароль»;
точная причина — только в журнале входов.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.storage import Storage
from app.modules.auth.providers.base import NOT_COUNTED, AuthFailure, AuthProvider
from app.modules.auth.sessions import SessionData, SessionStore
from app.modules.rbac import service as rbac
from app.modules.rbac.compute import compute_directory_roles
from app.modules.rbac.permissions import SUPERADMIN
from app.modules.security import rules
from app.modules.security.bruteforce import BruteforceGuard
from app.modules.security.ipblocks import Blocklist
from app.modules.security.service import record_login_event
from app.modules.users.models import User
from app.modules.users.service import upsert_from_directory

# Буквы и цифры любого алфавита (бывают кириллические sAMAccountName), точка, дефис, подчёркивание.
LOGIN_RE = re.compile(r"^\w[\w.-]{0,63}$")


def normalize_login(raw: str, *, netbios_domain: str, upn_suffix: str) -> str:
    """``ivanov``, ``ivanov@corp.local`` и ``CORP\\ivanov`` → ``ivanov`` (sAMAccountName).

    Чужой домен или недопустимые символы → AuthFailure("invalid_login"): в фильтр LDAP такой
    логин не попадёт (экранирование — вторая линия защиты).
    """
    value = raw.strip()
    if "\\" in value:
        domain, _, value = value.partition("\\")
        if netbios_domain and domain.casefold() != netbios_domain.casefold():
            raise AuthFailure("invalid_login")
    elif "@" in value:
        value, _, suffix = value.partition("@")
        if upn_suffix and suffix.casefold() != upn_suffix.casefold():
            raise AuthFailure("invalid_login")
    value = value.lower()
    if not LOGIN_RE.match(value):
        raise AuthFailure("invalid_login")
    return value


@dataclass(frozen=True)
class Attempt:
    login: str
    method: str
    ip: str | None
    user_agent: str | None


@dataclass(frozen=True)
class LoginResult:
    user: User
    token: str
    session: SessionData


class LoginService:
    def __init__(
        self,
        *,
        settings: Settings,
        providers: dict[str, AuthProvider],
        sessions: SessionStore,
        bruteforce: BruteforceGuard,
        storage: Storage,
        blocklist: Blocklist | None = None,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.sessions = sessions
        self.bruteforce = bruteforce
        self.storage = storage
        self.blocklist = blocklist or Blocklist(ttl_s=0)

    async def _fail(
        self,
        db: AsyncSession,
        failure: AuthFailure,
        attempt: Attempt,
        *,
        user_id: UUID | None = None,
        count: bool = True,
    ) -> AuthFailure:
        """Пишет отказ в журнал (и в счётчики перебора) и возвращает исключение для raise."""
        details: dict[str, object] = {}
        ip_locked = False
        if count and failure.reason not in NOT_COUNTED:
            result = await self.bruteforce.register_failure(attempt.login, attempt.ip)
            if result.login_locked:
                details["locked"] = "login"
            if result.ip_locked and attempt.ip:
                details["locked_ip"] = True
                ip_locked = True
        if failure.detail:
            details["detail"] = failure.detail[:500]
        await record_login_event(
            db,
            login=attempt.login,
            method=attempt.method,
            success=False,
            ip=attempt.ip,
            user_agent=attempt.user_agent,
            user_id=user_id,
            failure_reason=failure.reason,
            risk_flags=rules.failure_flags(failure.reason),
            details=details,
        )
        if ip_locked and attempt.ip:
            # Доверенную подсеть (например, NAT офиса) не блокируем — только инцидент.
            trusted = await self.blocklist.trusted(db, attempt.ip)
            if trusted:
                await self.bruteforce.unlock_ip(attempt.ip)
            await rules.block_bruteforce_ip(
                db, ip=attempt.ip, settings=self.settings, now=utcnow(), trusted=trusted
            )
        await db.commit()
        if ip_locked:
            await self.blocklist.changed()
        return failure

    async def login(
        self,
        db: AsyncSession,
        *,
        provider: str,
        login: str,
        password: str,
        ip: str | None,
        user_agent: str | None,
    ) -> LoginResult:
        """Выполняет вход или бросает AuthFailure (событие в журнале уже записано)."""
        raw = Attempt(login.strip()[:256], provider, ip, user_agent)
        auth = self.providers.get(provider)
        if auth is None:
            raise await self._fail(db, AuthFailure("provider_disabled"), raw, count=False)
        try:
            normalized = normalize_login(
                raw.login,
                netbios_domain=self.settings.ldap.netbios_domain,
                upn_suffix=self.settings.ldap.upn_suffix,
            )
        except AuthFailure as failure:
            raise await self._fail(db, failure, raw, count=False) from None

        attempt = Attempt(normalized, provider, ip, user_agent)
        if provider == "ldap" and not password:
            raise await self._fail(db, AuthFailure("empty_password"), attempt)
        if locked := await self.bruteforce.locked(normalized, ip):
            raise await self._fail(db, AuthFailure(locked), attempt, count=False)
        if await self.blocklist.blocked(db, ip):  # IP или подсеть заблокированы в админке
            raise await self._fail(db, AuthFailure("locked_ip"), attempt, count=False)

        try:
            directory_user = await auth.authenticate(normalized, password)
        except AuthFailure as failure:
            raise await self._fail(db, failure, attempt) from None

        user = await upsert_from_directory(
            db, directory_user, settings=self.settings, storage=self.storage
        )
        specs = compute_directory_roles(
            directory_user.rule_attributes(), directory_user.groups, self.settings.ldap
        )
        await rbac.sync_directory_roles(db, user.id, specs)
        if normalized in {a.lower() for a in self.settings.auth.bootstrap_admins}:
            await rbac.grant_role(db, user.id, SUPERADMIN)

        now = utcnow()
        if user.is_block_active(now):
            await db.commit()  # данные из AD сохраняем даже для заблокированного
            raise await self._fail(
                db, AuthFailure("blocked"), attempt, user_id=user.id, count=False
            )

        flags = await rules.success_flags(
            db,
            user_id=user.id,
            ip=ip,
            now=now,
            settings=self.settings,
            failures_before=await self.bruteforce.failures(normalized),
            trusted=await self.blocklist.trusted(db, ip),
        )
        user.last_login_at = now
        token, session = await self.sessions.create(
            db, user_id=user.id, provider=provider, ip=ip, user_agent=user_agent
        )
        await record_login_event(
            db,
            login=normalized,
            method=provider,
            success=True,
            ip=ip,
            user_agent=user_agent,
            user_id=user.id,
            risk_flags=flags,
        )
        await db.commit()
        await self.bruteforce.reset_login(normalized)
        return LoginResult(user=user, token=token, session=session)
