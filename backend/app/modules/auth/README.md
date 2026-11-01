# modules/auth

> Статус: реализовано на этапе 1 (§6, §19).

**Назначение:** вход пользователей и серверные сессии. Провайдеры `ldap` (MUST) и `dev`
(только разработка); `kerberos` — FUTURE, добавляется новым классом в `providers/` (§6.6).

**Поток входа (§6.2)** — `service.py::LoginService.login`:

1. Нормализация логина: `ivanov`, `CORP\ivanov`, `ivanov@corp.local` → `ivanov`; чужой домен и
   спецсимволы фильтров LDAP отклоняются (`invalid_login`).
2. Пустой пароль отклоняется до обращения к AD (`empty_password`).
3. Счётчики перебора по логину и IP (`modules/security/bruteforce.py`).
4. Провайдер: `providers/ldap.py` — bind по UPN на первый доступный контроллер, поиск сервисной
   учёткой с экранированием, `userAccountControl`, `access_group` с вложенностью (1.2.840.113556.1.4.1941).
5. Пользователь и роли из каталога (`modules/users`, `modules/rbac`), `bootstrap_admins`.
6. Блокировка администратором → отказ `blocked`.
7. Сессия + запись в журнал входов. Пользователь при любой ошибке видит «Неверный логин или пароль».

**Сессии (ADR-0004)** — `sessions.py`: токен в cookie `sid` (HttpOnly, SameSite=Lax, Secure), в Redis
и в таблице `sessions` — только SHA-256 токена. Простой — 8 ч, абсолютный срок — 7 дней.
Блокировка и отключение в AD завершают все сессии пользователя.

**CSRF** — `deps.py::verify_csrf`: double submit, заголовок `X-CSRF-Token` = cookie `csrftoken`
и = токен сессии. Подключён ко всем роутерам `/api` в `main.py`.

**Публичный интерфейс:**

| Эндпоинт | Назначение |
| --- | --- |
| `GET /api/auth/providers` | Включённые провайдеры и seed-пользователи dev |
| `GET /api/auth/csrf` | Выдать CSRF-cookie до входа |
| `POST /api/auth/login` | Вход: `{login, password, provider}` → `Me` |
| `POST /api/auth/logout` | Выход |
| `GET /api/auth/me` | Текущий пользователь, его права, уведомление при первом входе |
| `POST /api/auth/notice/accept` | Подтвердить уведомление |

Зависимости FastAPI: `CurrentUserDep`, `require(Perm.…)` (админ-права), `optional_session`, `client_ip`.
Диагностика AD — `diagnostics.py` (CLI `ad check` и страница «Диагностика AD»).

**Зависит от:** `users`, `rbac`, `security`, `admin` (текст уведомления); AD по LDAPS; Redis.

**Точки расширения:** новый провайдер — класс с методом `authenticate(login, password) -> DirectoryUser`
в `providers/` и регистрация в `main.py::init_services`. Настройка AD — `docs/guides/ad-setup.md`.

**Данные:** таблица `sessions`; Redis `sess:<hash>`, `user_sessions:<user_id>`.

**Тесты:** `backend/tests/unit/test_auth_units.py`, `backend/tests/integration/test_auth_dev.py`,
`test_auth_ldap.py` (mock-AD); запуск — `make test`.
