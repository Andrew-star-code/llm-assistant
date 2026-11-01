# modules/incidents

> Статус: реализовано на этапах 4 и 7 (§13.5).

**Назначение:** инциденты с группировкой по отпечатку, жизненным циклом и комментариями.

**Типы:** `system_error` — необработанная ошибка API или генерации (стек, request_id, эндпоинт,
пользователь, лог запроса до 200 строк, последние строки лога процесса — `incidents/errors.py`,
`core/log_capture.py`); `model_report` — скрытый репорт модели (§9.6); `guard` — вердикт
guard-модели; `security` — правила входов и всплеск запросов (§13.4); `model_health` — модель не
отвечает (`llm/monitor.py`, логи контейнера); `rag_degraded`, `kb_index`, `worker_failed`.

**Публичный интерфейс:** `service.report(sessions, type=…, severity=…, title=…, fingerprint=…,
throttle_s=…)` и `service.upsert(db, …)` в чужой транзакции — открытый инцидент с тем же отпечатком
получает +1 к счётчику, решённый открывается снова, «ложное срабатывание» только считает повторы;
`errors.report_exception(...)` — `system_error` из исключения (отпечаток без чисел, id и адресов).

| Эндпоинт | Право |
| --- | --- |
| `GET /api/admin/incidents?status=open|new|…&type=&severity=&q=&cursor=` | `admin.incidents.view` |
| `GET /api/admin/incidents/summary` — новые (и high/critical) для счётчика в меню | `admin.incidents.view` |
| `GET /api/admin/incidents/{id}`, `GET …/assignees` | `admin.incidents.view` |
| `PATCH /api/admin/incidents/{id}` (статус, ответственный, решение), `POST …/{id}/comments` | `admin.incidents.manage` (аудит) |

Уведомления — только в админке: счётчик новых в меню (high и critical подсвечены) и блок на
дашборде. Почта и мессенджеры — FUTURE.

**Зависит от:** Redis (ограничение частоты), `users`, `audit`.

**Точки расширения:** новый тип — строка `type`, подпись в i18n `admin.incidents.types.*` и вид
полезной нагрузки в `frontend/src/admin/pages/IncidentPage.tsx`.

**Данные:** `incidents`, `incident_comments`.

**Тесты:** `backend/tests/integration/test_incidents.py`, `test_security.py`, `test_moderation.py`,
`test_model_health.py`, `backend/tests/unit/test_incident_errors.py`,
`frontend/tests/unit/incidents.test.tsx`, `frontend/tests/e2e/admin-incidents.spec.ts`.
