# modules/admin

> Статус: каркас и разделы этапа 1; переписка, дашборд, настройки — этап 6 (§13).

**Назначение:** админ-роутеры поверх модулей и настройки из админки (`app_settings`).

**Публичный интерфейс (этап 1):**

| Эндпоинт | Право |
| --- | --- |
| `GET /api/admin/users`, `GET /api/admin/users/{id}`, `GET …/{id}/photo`, `GET /api/admin/roles` | `admin.users.view` |
| `POST /api/admin/users/{id}/block`, `POST …/{id}/unblock` | `admin.users.block` |
| `POST /api/admin/users/{id}/logout`, `DELETE /api/admin/sessions/{id}` | `admin.users.logout` |
| `PUT /api/admin/users/{id}/roles` | `admin.roles.manage` (+ `admin.admins.manage` для админских ролей) |
| `GET /api/admin/logins` | `admin.logins.view` |
| `GET /api/admin/audit` | `admin.audit.view` |
| `POST /api/admin/ad/diagnostics` | `admin.ad.diagnostics` |

Каждый эндпоинт требует `admin.access` и своё право через `require(Perm.…)`; это проверяет тест
`test_every_admin_endpoint_requires_permission`. Все действия над чужими данными — в аудит.

`app_settings.first_login_notice` — текст уведомления при первом входе (по умолчанию —
`auth.first_login_notice` из конфига; редактор — этап 6). `app_settings.search_settings` — параметры
поиска с поправкой порога реранкера из админки «Базы знаний» (`rag.search.rerank.score_threshold`);
читается на каждый поиск, без кэша.

**Зависит от:** все модули этапа 1.

**Точки расширения:** новая страница — `docs/guides/add-admin-page.md`.

**Данные:** `app_settings`.

**Тесты:** `backend/tests/integration/test_admin.py`, `frontend/tests/unit/admin.test.tsx`,
`frontend/tests/e2e/admin.spec.ts`.
