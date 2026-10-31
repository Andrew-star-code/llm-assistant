"""Каталог прав и системных ролей (§13.1). Полный список — docs/reference/permissions.md.

Права гранулярные и живут в коде; роли — их наборы в БД, поэтому состав ролей меняется без правок
кода. ``superadmin`` имеет все права всегда, независимо от ``role_permissions``.
При старте приложения недостающие права и системные роли создаются, существующие наборы прав
ролей не перезаписываются (их меняют в админке).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Perm(StrEnum):
    ADMIN_ACCESS = "admin.access"
    USERS_VIEW = "admin.users.view"
    USERS_BLOCK = "admin.users.block"
    USERS_LOGOUT = "admin.users.logout"
    ROLES_MANAGE = "admin.roles.manage"
    ADMINS_MANAGE = "admin.admins.manage"
    LOGINS_VIEW = "admin.logins.view"
    AUDIT_VIEW = "admin.audit.view"
    AD_DIAGNOSTICS = "admin.ad.diagnostics"
    KB_MANAGE = "admin.kb.manage"
    KB_MANAGE_ROLES = "admin.kb.manage_roles"
    INCIDENTS_VIEW = "admin.incidents.view"
    SCENARIOS_MANAGE = "admin.scenarios.manage"


PERMISSION_DESCRIPTIONS: dict[Perm, str] = {
    Perm.ADMIN_ACCESS: "Вход в админку",
    Perm.USERS_VIEW: "Просмотр пользователей и их карточек",
    Perm.USERS_BLOCK: "Блокировка и разблокировка пользователей",
    Perm.USERS_LOGOUT: "Завершение сессий пользователей",
    Perm.ROLES_MANAGE: "Выдача и отзыв пользовательских ролей (кроме админских)",
    Perm.ADMINS_MANAGE: "Назначение админских ролей (superadmin, admin, kb_manager)",
    Perm.LOGINS_VIEW: "Просмотр журнала входов",
    Perm.AUDIT_VIEW: "Просмотр журнала аудита",
    Perm.AD_DIAGNOSTICS: "Диагностика подключения к AD",
    Perm.KB_MANAGE: "Все базы знаний: создание, роли, документы, импорт, удаление",
    Perm.KB_MANAGE_ROLES: "Ролевые базы знаний тех ролей, что есть у самого менеджера",
    Perm.INCIDENTS_VIEW: "Просмотр инцидентов",
    Perm.SCENARIOS_MANAGE: "Сценарии: создание, редактирование, тестовый чат",
}

SUPERADMIN = "superadmin"
ADMIN = "admin"
KB_MANAGER = "kb_manager"
ADMIN_ROLE_CODES = frozenset({SUPERADMIN, ADMIN, KB_MANAGER})


@dataclass(frozen=True)
class SystemRole:
    code: str
    name: str
    description: str
    permissions: frozenset[Perm]


SYSTEM_ROLES: tuple[SystemRole, ...] = (
    SystemRole(
        SUPERADMIN,
        "Суперадминистратор",
        "Всё, включая назначение админов, настройки и физическое удаление данных",
        frozenset(Perm),
    ),
    SystemRole(
        ADMIN,
        "Администратор",
        "Пользователи, переписка, входы, инциденты, лимиты, базы знаний, сценарии, модели",
        frozenset(Perm) - {Perm.ADMINS_MANAGE, Perm.KB_MANAGE_ROLES},
    ),
    SystemRole(
        KB_MANAGER,
        "Менеджер баз знаний",
        "Только базы знаний назначенных ролей",
        frozenset({Perm.ADMIN_ACCESS, Perm.KB_MANAGE_ROLES}),
    ),
)
