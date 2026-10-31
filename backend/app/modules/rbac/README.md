# modules/rbac

> Статус: реализовано на этапе 1 (§6.3, §13.1).

**Назначение:** роли и гранулярные права. Права живут в коде (`permissions.py::Perm`), роли — их
наборы в БД, поэтому состав ролей меняется без правок кода. Полный список —
[docs/reference/permissions.md](../../../../docs/reference/permissions.md).

**Откуда берутся роли пользователя:**

| Источник | `user_roles.source` | Когда пересчитывается |
| --- | --- | --- |
| Роль отдела «Отдел: <department>» (`ldap.department_roles.auto`) | `ad` | при входе и синхронизации |
| Правила по атрибутам (`ldap.department_roles.rules`) | `ad` | при входе и синхронизации |
| Группы AD (`ldap.group_roles`) | `ad` | при входе и синхронизации |
| `auth.bootstrap_admins` → `superadmin` | `manual` | выдаётся при входе, сам не снимается |
| Админка / `create-admin` | `manual` | вручную |

Системные роли создаются при старте приложения (`ensure_system_rbac`), если их нет:
`superadmin` (все права всегда), `admin` (всё, кроме назначения админов), `kb_manager`
(вход в админку; права на базы знаний — этап 4). Существующие наборы прав не перезаписываются.

**Публичный интерфейс:** `compute.compute_directory_roles` (чистая функция), `service.sync_directory_roles`,
`service.grant_role`, `service.set_manual_roles` (админские роли — только с правом
`admin.admins.manage`; роли отделов вручную не выдаются), `service.user_roles`,
`service.effective_permissions`. Проверка в эндпоинтах — `modules/auth/deps.py::require`.

**Зависит от:** —

**Точки расширения:** новое право — значение в `Perm` + описание в `PERMISSION_DESCRIPTIONS` +
строка в `docs/reference/permissions.md`; при необходимости — в наборе системной роли.

**Данные:** `roles`, `permissions`, `role_permissions`, `user_roles`.
TODO(stage-6): таблица `role_mappings` для правки маппинга AD → роли в админке поверх конфига.

**Тесты:** `backend/tests/unit/test_auth_units.py::test_compute_directory_roles`,
`backend/tests/integration/test_admin.py`.
