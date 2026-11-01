# modules/admin

> Статус: разделы этапов 1 и 6 (§13): пользователи, входы, аудит, AD; переписка, выгрузки,
> обратная связь, дашборд, модели, инструменты, настройки.

**Назначение:** админ-роутеры поверх модулей и настройки из админки (`app_settings`).

**Публичный интерфейс:**

| Эндпоинт | Право |
| --- | --- |
| `GET /api/admin/users`, `GET /api/admin/users/{id}`, `GET …/{id}/photo`, `GET /api/admin/roles` | `admin.users.view` |
| `POST /api/admin/users/{id}/block`, `POST …/{id}/unblock` | `admin.users.block` |
| `POST /api/admin/users/{id}/logout`, `DELETE /api/admin/sessions/{id}` | `admin.users.logout` |
| `PUT /api/admin/users/{id}/roles` | `admin.roles.manage` (+ `admin.admins.manage` для админских ролей) |
| `GET /api/admin/logins` | `admin.logins.view` |
| `GET /api/admin/audit` | `admin.audit.view` |
| `POST /api/admin/ad/diagnostics` | `admin.ad.diagnostics` |
| `GET /api/admin/dashboard?days=` — активность, токены, TTFT, качество, модели, очереди, GPU | `admin.dashboard.view` |
| `GET /api/admin/messages` (поиск), `GET /api/admin/chats`, `GET /api/admin/chats/filters`, `GET /api/admin/chats/{id}` (просмотр → аудит `chat.view`) | `admin.chats.view` |
| `POST /api/admin/chats/{id}/restore` | `admin.chats.restore` |
| `POST /api/admin/chats/{id}/purge` (`{confirm: id}`) | `admin.chats.purge` |
| `GET /api/admin/feedback`, `…/stats`, `…/export` (XLSX → аудит) | `admin.feedback.view` |
| `GET /api/admin/models`, `…/models/health`, `PUT …/models/{role}/visibility` | `admin.models.manage` |
| `GET /api/admin/tools`, `PUT /api/admin/tools/{name}` | `admin.tools.manage` |
| `GET/PUT /api/admin/settings`, `POST/DELETE /api/admin/settings/logo` | `admin.settings.manage` |
| `GET /api/admin/roles/{id}`, `GET …/{id}/members` | `admin.users.view` |
| `POST /api/admin/roles`, `PATCH/DELETE …/{id}`, `POST …/{id}/members` (массово: логины или e-mail; кого нет — из AD), `POST …/{id}/members/remove` | `admin.roles.manage` (+ `admin.admins.manage` для админских ролей) |
| `GET /api/branding`, `GET /api/branding/logo` — название и логотип, без входа | — |

Выгрузки — модуль `exports` (`/api/admin/exports`, `admin.chats.export`).

Каждый эндпоинт требует `admin.access` и своё право через `require(Perm.…)`; это проверяет тест
`test_every_admin_endpoint_requires_permission`. Все действия над чужими данными — в аудит.

**Переписка** (`chats.py`): фильтр `ChatFilter` — общий для поиска, списка и выгрузки по выборке;
поиск — FTS `russian` + подстрока (`pg_trgm`), курсор по времени сообщения. Просмотр отдаёт всё, что
пользователю не показывается: удалённое, все ветки, размышления, скрытые вызовы, все источники,
трассировку. Физическое удаление — `chats.purge` (записи → commit → файлы и точки Qdrant).

**Роли** (`roles_router.py`, решение 57): отдел из AD не используется — свои роли (`kind = custom`)
создаются в админке и назначаются вручную. Массовое добавление принимает список логинов или e-mail
(`login`, `login@домен`, `ДОМЕН\login`); кого ещё нет в системе, ищет в AD сервисной учёткой и
заводит (с ролями из AD), не найденных возвращает списком. Назначения `source = manual`
синхронизация с AD не трогает. Роль, которая открывает базы знаний, сценарии или модели, не
удаляется.

**Настройки поверх конфига** (`app_settings.py`): `effective(db, settings)` — конфиг с правками из
админки одной выборкой, на каждый запрос, без кэша (название, компания, лимиты файлов, обращение по
умолчанию, срок хранения); `system_prompt_override` — шаблон базового промпта (песочница Jinja2,
при ошибке — файл); `notice_required` — уведомление и повторное подтверждение после обновления
текста; `hidden_model_roles` — видимость моделей (сценарий на скрытой модели не виден);
`enabled_tools` — конфиг минус выключенные в админке; `search_settings` — параметры
поиска с поправкой порога реранкера из админки «Базы знаний» (`rag.search.rerank.score_threshold`);
читается на каждый поиск, без кэша.

**Зависит от:** `users`, `rbac`, `auth`, `audit`, `chats`, `feedback`, `files`, `kb`, `incidents`,
`scenarios`, `tools`, `llm` (проверка эндпоинтов — `llm/health.py`).

**Точки расширения:** новая страница — `docs/guides/add-admin-page.md`.

**Данные:** `app_settings`.

**Тесты:** `backend/tests/integration/test_admin.py`, `test_admin_chats.py`, `test_admin_sections.py`,
`backend/tests/unit/test_dashboard_gpu.py`, `frontend/tests/unit/admin.test.tsx`,
`adminCorrespondence.test.tsx`, `frontend/tests/e2e/admin.spec.ts`, `admin-correspondence.spec.ts`.
