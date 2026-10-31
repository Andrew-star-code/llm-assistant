"""Общий интерфейс провайдеров входа и данные пользователя из каталога."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

FailureReason = Literal[
    "provider_disabled",
    "invalid_login",
    "empty_password",
    "locked_login",
    "locked_ip",
    "bad_credentials",
    "user_not_found",
    "ad_disabled",
    "ad_locked",
    "password_expired",
    "not_in_access_group",
    "ad_unavailable",
    "blocked",
]

# Отказы, которые не считаются попыткой подбора пароля (§6.2 п. 3).
NOT_COUNTED: frozenset[FailureReason] = frozenset({"locked_login", "locked_ip", "ad_unavailable"})


class AuthFailure(Exception):  # noqa: N818 — это результат проверки, а не сбой
    """Отказ во входе. ``reason`` — только для журнала; пользователь видит общий текст (§6.2)."""

    def __init__(self, reason: FailureReason, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class DirectoryUser:
    """Пользователь из каталога (AD или seed-список dev) в нормализованном виде."""

    guid: str
    login: str
    full_name_raw: str | None = None  # displayName
    dn: str | None = None
    upn: str | None = None
    email: str | None = None
    last_name: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    title: str | None = None
    department: str | None = None
    company: str | None = None
    office: str | None = None
    phone: str | None = None
    mobile: str | None = None
    manager_dn: str | None = None
    manager_name: str | None = None
    employee_id: str | None = None
    photo: bytes | None = None
    groups: list[str] = field(default_factory=list)
    disabled: bool = False

    def rule_attributes(self) -> dict[str, str | None]:
        """Значения по ключам маппинга ``ldap.attributes`` — для правил ролей."""
        return {
            "login": self.login,
            "email": self.email,
            "display_name": self.full_name_raw,
            "title": self.title,
            "department": self.department,
            "company": self.company,
            "office": self.office,
            "employee_id": self.employee_id,
        }


class AuthProvider(Protocol):
    name: str

    async def authenticate(self, login: str, password: str) -> DirectoryUser:
        """Проверяет учётные данные и возвращает пользователя или бросает AuthFailure."""
        ...
