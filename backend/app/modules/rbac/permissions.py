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
    INCIDENTS_MANAGE = "admin.incidents.manage"
    SECURITY_MANAGE = "admin.security.manage"
    SCENARIOS_MANAGE = "admin.scenarios.manage"
    DASHBOARD_VIEW = "admin.dashboard.view"
    CHATS_VIEW = "admin.chats.view"
    CHATS_EXPORT = "admin.chats.export"
    CHATS_RESTORE = "admin.chats.restore"
    CHATS_PURGE = "admin.chats.purge"
    FEEDBACK_VIEW = "admin.feedback.view"
    MODELS_MANAGE = "admin.models.manage"
    TOOLS_MANAGE = "admin.tools.manage"
    SETTINGS_MANAGE = "admin.settings.manage"
    LIMITS_MANAGE = "admin.limits.manage"
    DATASOURCES_VIEW = "admin.datasources.view"


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
    Perm.INCIDENTS_MANAGE: "Работа с инцидентами: статус, ответственный, решение, комментарии",
    Perm.SECURITY_MANAGE: "Блокировки IP и подсетей, доверенные подсети, проверка событий входа",
    Perm.SCENARIOS_MANAGE: "Сценарии: создание, редактирование, тестовый чат",
    Perm.DASHBOARD_VIEW: "Дашборд: активность, токены, качество, состояние моделей и очередей",
    Perm.CHATS_VIEW: "Поиск и просмотр переписки всех пользователей (каждый просмотр — в аудит)",
    Perm.CHATS_EXPORT: "Выгрузки переписки: JSON, XLSX, DOCX, PDF",
    Perm.CHATS_RESTORE: "Вернуть пользователю удалённый чат",
    Perm.CHATS_PURGE: "Физическое удаление переписки",
    Perm.FEEDBACK_VIEW: "Обратная связь: лайки, дизлайки, причины, выгрузка",
    Perm.MODELS_MANAGE: "Модели: реестр, состояние, видимость по ролям",
    Perm.TOOLS_MANAGE: "Инструменты: включение и выключение, статистика",
    Perm.SETTINGS_MANAGE: (
        "Настройки: название, логотип, уведомление, сроки хранения, лимиты файлов, обращение, "
        "системный промпт"
    ),
    Perm.DATASOURCES_VIEW: (
        "Источники данных: каталог шлюза, тестовый вызов функции, журнал SQL-запросов"
    ),
    Perm.LIMITS_MANAGE: (
        "Лимиты: политики, эффективные лимиты пользователя, сброс счётчиков, временное повышение"
    ),
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
        # Назначение админов, физическое удаление и настройки — только superadmin (§13.1).
        frozenset(Perm)
        - {Perm.ADMINS_MANAGE, Perm.KB_MANAGE_ROLES, Perm.CHATS_PURGE, Perm.SETTINGS_MANAGE},
    ),
    SystemRole(
        KB_MANAGER,
        "Менеджер баз знаний",
        "Только базы знаний назначенных ролей",
        frozenset({Perm.ADMIN_ACCESS, Perm.KB_MANAGE_ROLES}),
    ),
)
