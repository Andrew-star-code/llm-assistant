# modules/limits

> Статус: этап 8 (§12) — метрики, политики, атомарные счётчики, учёт, API и админка.

**Назначение:** лимиты пользователей. Политики — глобальные, ролевые, персональные и временные; проверка
до запроса, списание по факту, остаток и время сброса видны пользователю.

**Метрики** (§12.1, `core/config.py::LimitMetric`):

| Метрика | Что считает | Окно | Где проверяется |
| --- | --- | --- | --- |
| `messages` | запросы на генерацию: сообщение, правка, перегенерация | да | `completions/router.py` до запроса |
| `tokens` | вход + выход (включая размышления) ответа | да | до запроса — «не исчерпан ли», списание после ответа |
| `concurrent_generations` | одновременные генерации | — | слот в Redis до запроса, освобождается в конце |
| `uploads` | вложения чата и документы личной базы | да | `files/router.py`, `kb/router.py` |
| `personal_kb_storage` | объём личной базы, МБ | — | `kb.service.quota` (413 `quota_size`) |
| `personal_kb_documents` | документов в личной базе | — | `kb.service.quota` (413 `quota_documents`) |

`messages` и `tokens` можно уточнить ролью модели (`model_role`) и режимом (`thinking: true` —
только генерации с размышлениями). Окна — минута, час, день, неделя (с понедельника), месяц — по
календарю в поясе `chat.timezone`.

**Эффективный лимит** (`policies.py`): по ключу «метрика + окно + роль модели + thinking» —
персональная политика (не истёкшая), иначе максимальная из ролевых, иначе глобальная из админки,
иначе строка `limits.defaults` конфига. Нет ни одной — метрика не ограничена. Срок временной политики
сверяется при каждом расчёте: она перестаёт действовать сама.

**Публичный интерфейс** (`service.py`):

* `Limits.reserve_generation(db, user_id, model_role, thinking, message_id)` — один скрипт Lua
  (`counters.py`) проверяет все применимые лимиты `messages` и `tokens`, резервирует сообщение и
  слот генерации; превышение — `LimitExceeded` (429 `limit_exceeded`, в `details` — `metric`,
  `window`, `limit`, `used`, `reset_at`, `timezone`). `Limits.cancel` возвращает резерв, если
  запрос не дошёл до генерации.
* `Limits.commit_tokens` — фактические токены после ответа любого статуса (перерасход последним
  ответом допускается); `record_usage` — строка `usage_records` (виды `chat`, `title`; служебные
  вызовы лимит пользователя не тратят). Генерация продлевает слот (`refresh_slot`) и освобождает его
  в конце; слот упавшего процесса истекает через `limits.slot_ttl_s`.
* `Limits.upload(db, user_id)` — контекст загрузки: резерв `uploads`, отказ в приёме файла его
  возвращает. `kb_quota` — квота личной базы по политикам.
* `Limits.status` / `status_payload` — остатки по всем метрикам и ближайшая к исчерпанию; то же
  уходит событием SSE `limits` в конце ответа.

| Эндпоинт | Право |
| --- | --- |
| `GET /api/limits` | пользователь |
| `GET/POST /api/admin/limits/policies`, `PATCH/DELETE …/{id}` | `admin.limits.manage` (аудит `limits.policy.*`) |
| `GET /api/admin/users/{id}/limits` — эффективные лимиты и их источник | `admin.limits.manage` |
| `POST /api/admin/users/{id}/limits/reset` — сброс счётчиков | `admin.limits.manage` (аудит `limits.reset`) |

**Зависит от:** `rbac` (роли пользователя), `kb` (занятость личной базы); Redis, Postgres.

**Точки расширения:** новая метрика — [docs/guides/add-limit-metric.md](../../../../docs/guides/add-limit-metric.md).

**Данные:** `limit_policies`; `usage_records` — секционирована по месяцам: разделы на
`limits.partitions_ahead` месяцев вперёд создаёт задача `limits.partitions` (`scheduler`, раз в сутки),
строки без раздела попадают в `usage_records_default` и переносятся при его создании. Redis:
`lim:{user}:{метрика}:{окно}:{роль|*}:{a|t}:{метка окна}` (расход пишется во все окна и варианты
сразу, поэтому новая политика видит расход с начала окна), `lim:{user}:concurrent` — слоты.
Счётчики окон живут только в Redis: после потери Redis расход окна начинается с нуля, история —
в `usage_records`.

**Тесты:** `backend/tests/unit/test_limits_units.py`, `backend/tests/integration/test_limits.py`;
фронтенд — `frontend/tests/unit/limits.test.tsx`, e2e — `frontend/tests/e2e/limits.spec.ts`.
