# modules/auth

> Статус: каркас. Реализация — §6, этап 1.

**Назначение:** Вход пользователей: провайдеры `ldap` и `dev` (kerberos — FUTURE), серверные сессии в Redis, CSRF (double submit), выход.

**Публичный интерфейс:** `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`; зависимость FastAPI `current_user`.

**Зависит от:** `users`, `rbac`, `security` (журнал входов, блокировки); AD по LDAPS; Redis.

**Точки расширения:** Новый провайдер — класс в `modules/auth/providers/` (§6.6).

**Данные:** Таблица `sessions`; ключи сессий в Redis.

**Тесты:** `backend/tests/unit/auth/`, `backend/tests/integration/auth/`; запуск — `make test`.
