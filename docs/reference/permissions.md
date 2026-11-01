# Права и роли

Права гранулярные и объявлены в коде — `backend/app/modules/rbac/permissions.py::Perm`; роли — их
наборы в таблице `role_permissions`, поэтому состав ролей меняется без правок кода (§13.1).
Каждый админ-эндпоинт объявляет своё право через `require(Perm.…)`; `admin.access` нужен всегда.

## Права

| Право | Что разрешает | Этап |
| --- | --- | --- |
| `admin.access` | Вход в админку | 1 |
| `admin.users.view` | Список пользователей, карточка, фото, список ролей | 1 |
| `admin.users.block` | Блокировка и разблокировка пользователей | 1 |
| `admin.users.logout` | Завершение сессий пользователя | 1 |
| `admin.roles.manage` | Выдача и отзыв ручных ролей (кроме админских) | 1 |
| `admin.admins.manage` | Назначение `superadmin`, `admin`, `kb_manager` | 1 |
| `admin.logins.view` | Журнал входов | 1 |
| `admin.audit.view` | Журнал аудита | 1 |
| `admin.ad.diagnostics` | Диагностика AD | 1 |
| `admin.kb.manage` | Все базы знаний: создание, уровень и роли, документы, импорт из папки, удаление; параметры поиска (порог реранкера) | 4 |
| `admin.kb.manage_roles` | Ролевые базы тех ролей, что есть у самого пользователя (документы, импорт); создавать базы и менять роли нельзя | 4 |
| `admin.incidents.view` | Список инцидентов (минимум; полностью — этап 7) | 4 |
| `admin.scenarios.manage` | Сценарии: создание, редактирование, удаление, тестовый чат в редакторе | 5 |

Запланированы по §13.1: `admin.chats.view`, `admin.chats.export`, `admin.chats.purge` (этап 6),
`admin.limits.manage` (этап 8), остальные `admin.incidents.*` (этап 7),
`admin.settings.manage` (этап 6).

## Системные роли

| Роль | Права по умолчанию |
| --- | --- |
| `superadmin` | Все права всегда, независимо от `role_permissions` |
| `admin` | Все, кроме `admin.admins.manage` и `admin.kb.manage_roles` (у админа и так все базы) |
| `kb_manager` | `admin.access`, `admin.kb.manage_roles` |

Новое право, появившееся в коде после установки, при старте один раз выдаётся системным ролям,
в набор которых оно входит по умолчанию; дальше состав ролей меняется только в админке.

Первые суперадминистраторы — `auth.bootstrap_admins` в конфиге или
`python -m app.cli create-admin --login <логин>`.

## Пользовательские роли

* «Отдел: <department>» (`dept:<department>`) — автоматически из атрибута `department`.
* Роли из правил `ldap.department_roles.rules` и `ldap.group_roles` (например, `legal`, `it`).
* Пересчитываются при каждом входе и синхронизации с AD (`source = ad`); ручные роли
  (`source = manual`) при этом не трогаются.
