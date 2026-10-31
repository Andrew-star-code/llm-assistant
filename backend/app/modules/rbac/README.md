# modules/rbac

> Статус: каркас. Реализация — §6.2, §13.1, этап 1.

**Назначение:** Роли и гранулярные права: роли отделов из атрибута department, правила, группы AD, ручные роли; админские роли superadmin, admin, kb_manager.

**Публичный интерфейс:** Зависимость `require(permission)`; сервис вычисления ролей пользователя.

**Зависит от:** `users`.

**Точки расширения:** Новое право — константа + `docs/reference/permissions.md`.

**Данные:** `roles`, `permissions`, `role_permissions`, `user_roles`, `role_mappings`.

**Тесты:** `backend/tests/unit/rbac/`, `backend/tests/integration/rbac/`; запуск — `make test`.
