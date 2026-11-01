"""Провайдер ldap: вход по логину и паролю домена через LDAPS или LDAP + StartTLS (§6.2).

Порядок (§6.2): bind пользователем по UPN на первый доступный контроллер → поиск записи
сервисной учёткой (значения в фильтрах экранируются) → проверка ``userAccountControl`` и
``access_group`` (с учётом вложенных групп, правило 1.2.840.113556.1.4.1941) → атрибуты по маппингу.

ldap3 — синхронная библиотека, поэтому сетевые вызовы уходят в поток (``asyncio.to_thread``).
"""

from __future__ import annotations

import asyncio
import math
import re
import ssl
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import structlog
from ldap3 import BASE, NONE, SIMPLE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from app.core.config import LdapSettings
from app.modules.auth.providers.base import AuthFailure, DirectoryUser, FailureReason

log = structlog.stdlib.get_logger("app.auth.ldap")

ACCOUNTDISABLE = 0x0002
NESTED_MEMBER_RULE = "1.2.840.113556.1.4.1941"

# Коды AD в тексте ошибки bind (AcceptSecurityContext error, data XXX).
_AD_BIND_CODES: dict[str, FailureReason] = {
    "52e": "bad_credentials",
    "525": "bad_credentials",  # пользователь не найден — наружу то же, что неверный пароль
    "533": "ad_disabled",
    "775": "ad_locked",
    "532": "password_expired",
    "773": "password_expired",
    "701": "ad_disabled",  # учётка просрочена
}
_DATA_CODE = re.compile(r"data ([0-9a-f]{3})", re.IGNORECASE)


class DirectoryUnavailable(Exception):  # noqa: N818
    """Ни один контроллер домена не ответил."""


@dataclass
class ControllerCheck:
    url: str
    ok: bool
    duration_ms: float
    error: str | None = None


def _decode(values: list[bytes] | None) -> str | None:
    if not values:
        return None
    text = values[0].decode("utf-8", errors="replace").strip()
    return text or None


def classify_bind_error(message: str) -> FailureReason:
    match = _DATA_CODE.search(message or "")
    return (
        _AD_BIND_CODES.get(match.group(1).lower(), "bad_credentials")
        if match
        else "bad_credentials"
    )


@dataclass
class LdapDirectory:
    """Низкоуровневый доступ к AD. Все методы синхронные — вызывайте через ``asyncio.to_thread``."""

    settings: LdapSettings
    read_password: Callable[[], str] = field(default=lambda: "")

    # ------------------------------------------------------------------ подключение

    @property
    def _timeout(self) -> int:
        # ldap3 упаковывает тайм-аут сокета через struct.pack — нужно целое число секунд.
        return max(1, math.ceil(self.settings.timeout_s))

    def _server(self, url: str) -> Server:
        parsed = urlparse(url)
        use_ssl = parsed.scheme == "ldaps"
        tls = Tls(
            validate=ssl.CERT_REQUIRED,
            version=ssl.PROTOCOL_TLS_CLIENT,
            ca_certs_file=str(self.settings.ca_cert_file) if self.settings.ca_cert_file else None,
        )
        return Server(
            parsed.hostname or "",
            port=parsed.port or (636 if use_ssl else 389),
            use_ssl=use_ssl,
            tls=tls,
            get_info=NONE,
            connect_timeout=self._timeout,
        )

    def _open(self, url: str, user: str | None, password: str | None) -> Connection:
        """Открывает соединение (с StartTLS при необходимости) и делает simple bind.

        Сетевые ошибки и ошибки TLS — LDAPException; неверные учётные данные — AuthFailure.
        """
        conn = Connection(
            self._server(url),
            user=user,
            password=password,
            authentication=SIMPLE,
            receive_timeout=self._timeout,
            raise_exceptions=False,
            read_only=True,
        )
        conn.open()
        if self.settings.start_tls and not url.startswith("ldaps://") and not conn.start_tls():
            conn.unbind()
            raise LDAPException(f"StartTLS не удался: {conn.result.get('description')}")
        if not conn.bind():
            message = str(conn.result.get("message") or conn.result.get("description") or "")
            conn.unbind()
            if conn.result.get("result") == 49:  # invalidCredentials
                raise AuthFailure(classify_bind_error(message), message)
            raise LDAPException(f"bind: {conn.result.get('description')} {message}".strip())
        return conn

    def _connect(self, user: str | None, password: str | None) -> Connection:
        """Пробует контроллеры по порядку. Неверный пароль на других не повторяется:
        иначе каждая попытка увеличит счётчик блокировки AD несколько раз."""
        errors: list[str] = []
        for url in self.settings.urls:
            try:
                return self._open(url, user, password)
            except (LDAPException, OSError) as exc:
                log.warning("ldap.controller_unavailable", url=url, error=str(exc))
                errors.append(f"{url}: {exc}")
        raise DirectoryUnavailable("; ".join(errors) or "не задан ни один контроллер")

    def service_connection(self) -> Connection:
        return self._connect(self.settings.bind_dn, self.read_password())

    # ------------------------------------------------------------------ чтение

    def _attribute_names(self) -> list[str]:
        a = self.settings.attributes
        return [
            a.guid,
            a.login,
            a.email,
            a.display_name,
            a.last_name,
            a.first_name,
            a.middle_name,
            a.title,
            a.department,
            a.company,
            a.office,
            a.phone,
            a.mobile,
            a.manager,
            a.employee_id,
            a.photo,
            "userAccountControl",
            "userPrincipalName",
            "memberOf",
        ]

    def _find_entry(self, conn: Connection, login: str) -> dict[str, Any] | None:
        query = self.settings.user_filter.format(username=escape_filter_chars(login))
        conn.search(self.settings.base_dn, query, SUBTREE, attributes=self._attribute_names())
        entries = [r for r in conn.response or [] if r.get("type") == "searchResEntry"]
        return entries[0] if entries else None

    def _groups(self, conn: Connection, dn: str, member_of: list[str]) -> list[str]:
        if not self.settings.nested_groups:
            return member_of
        query = f"(&(objectClass=group)(member:{NESTED_MEMBER_RULE}:={escape_filter_chars(dn)}))"
        conn.search(self.settings.base_dn, query, SUBTREE, attributes=["cn"])
        return [r["dn"] for r in conn.response or [] if r.get("type") == "searchResEntry"]

    def _display_name_of(self, conn: Connection, dn: str) -> str | None:
        conn.search(dn, "(objectClass=*)", BASE, attributes=[self.settings.attributes.display_name])
        for r in conn.response or []:
            if r.get("type") == "searchResEntry":
                return _decode(r["raw_attributes"].get(self.settings.attributes.display_name))
        return None

    def _to_user(self, conn: Connection, entry: dict[str, Any]) -> DirectoryUser:
        raw: dict[str, list[bytes]] = entry["raw_attributes"]
        a = self.settings.attributes
        guid_raw = raw.get(a.guid) or []
        guid = str(uuid.UUID(bytes_le=guid_raw[0])) if guid_raw else entry["dn"]
        member_of = [v.decode("utf-8", errors="replace") for v in raw.get("memberOf", [])]
        uac = int(_decode(raw.get("userAccountControl")) or "0")
        manager_dn = _decode(raw.get(a.manager))
        photos = raw.get(a.photo) or []
        return DirectoryUser(
            guid=guid,
            login=(_decode(raw.get(a.login)) or "").lower(),
            full_name_raw=_decode(raw.get(a.display_name)),
            dn=entry["dn"],
            upn=_decode(raw.get("userPrincipalName")),
            email=_decode(raw.get(a.email)),
            last_name=_decode(raw.get(a.last_name)),
            first_name=_decode(raw.get(a.first_name)),
            middle_name=_decode(raw.get(a.middle_name)),
            title=_decode(raw.get(a.title)),
            department=_decode(raw.get(a.department)),
            company=_decode(raw.get(a.company)),
            office=_decode(raw.get(a.office)),
            phone=_decode(raw.get(a.phone)),
            mobile=_decode(raw.get(a.mobile)),
            manager_dn=manager_dn,
            manager_name=self._display_name_of(conn, manager_dn) if manager_dn else None,
            employee_id=_decode(raw.get(a.employee_id)),
            photo=bytes(photos[0]) if photos else None,
            groups=self._groups(conn, entry["dn"], member_of),
            disabled=bool(uac & ACCOUNTDISABLE),
        )

    def lookup(self, login: str) -> DirectoryUser | None:
        """Ищет пользователя сервисной учёткой; None — записи нет."""
        conn = self.service_connection()
        try:
            entry = self._find_entry(conn, login)
            return self._to_user(conn, entry) if entry else None
        finally:
            conn.unbind()

    def in_access_group(self, user: DirectoryUser) -> bool:
        group = self.settings.access_group
        return not group or group.casefold() in {g.casefold() for g in user.groups}

    def verify_password(self, login: str, password: str) -> None:
        """Bind пользователем по UPN; бросает AuthFailure или DirectoryUnavailable."""
        upn = f"{login}@{self.settings.upn_suffix}" if self.settings.upn_suffix else login
        self._connect(upn, password).unbind()

    def check_controllers(self) -> list[ControllerCheck]:
        """Доступность и TLS каждого контроллера (анонимное подключение без bind)."""
        result = []
        for url in self.settings.urls:
            started = time.perf_counter()
            try:
                conn = Connection(self._server(url), receive_timeout=self._timeout)
                conn.open()
                if self.settings.start_tls and not url.startswith("ldaps://"):
                    conn.start_tls()
                conn.unbind()
                result.append(ControllerCheck(url, True, _ms(started)))
            except LDAPException as exc:
                result.append(ControllerCheck(url, False, _ms(started), str(exc)))
        return result


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


class LdapProvider:
    name = "ldap"

    def __init__(self, directory: LdapDirectory) -> None:
        self.directory = directory

    def _authenticate_sync(self, login: str, password: str) -> DirectoryUser:
        if not password:
            # Bind с пустым паролем AD считает анонимным и «успешным» (§6.2 п. 2).
            raise AuthFailure("empty_password")
        try:
            self.directory.verify_password(login, password)
            user = self.directory.lookup(login)
        except DirectoryUnavailable as exc:
            raise AuthFailure("ad_unavailable", str(exc)) from exc
        if user is None:
            raise AuthFailure("user_not_found")
        if user.disabled:
            raise AuthFailure("ad_disabled")
        if not self.directory.in_access_group(user):
            raise AuthFailure("not_in_access_group")
        return user

    async def authenticate(self, login: str, password: str) -> DirectoryUser:
        return await asyncio.to_thread(self._authenticate_sync, login, password)
