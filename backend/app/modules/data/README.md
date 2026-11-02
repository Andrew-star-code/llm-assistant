# modules/data

> Статус: этап 9 (§9.5) — клиент шлюза данных.

**Назначение:** доступ `api` к семантическому слою `services/data-gateway`. Модель вызывает
инструменты данных (`tools/builtin/data.py`), а клиент передаёт шлюзу идентичность пользователя —
логин, роли и отдел из БД, подписанные HMAC (`X-DG-Identity`, `X-DG-Signature`). Модель её не
видит и подменить не может.

**Публичный интерфейс:** `client.identity_of(db, user_id)`, `client.DataGateway(settings)` —
`catalog`, `describe`, `call`, `query`; ошибки шлюза — `GatewayError(code, message)` (`rejected`,
`query_failed`, `not_found`, `unavailable`).

**Инструменты** (`tools/builtin/data.py`, только при `data_gateway.url`): `list_datasets`,
`describe_dataset`, `call_data_function`, `run_sql_query`, `search_employees`. Каждый запрос и вызов
функции — запись в аудит `data.query` / `data.function` (итоговый SQL после RLS, параметры, число
строк, время, результат; отклонённые тоже). Модель видит до `data_gateway.preview_rows` строк,
больший результат — CSV-карточка; неудачных SQL на ответ — не больше
`data_gateway.max_failed_attempts` (счётчик в Redis резервируется атомарно).

**Зависит от:** `rbac`, `users`, `audit`; сервис `data-gateway`.

**Точки расширения:** новый набор или функция — каталог шлюза
([docs/guides/add-dataset.md](../../../../docs/guides/add-dataset.md)); новый инструмент данных —
`tools/builtin/data.py`.

**Данные:** своих таблиц нет; Redis `data:sqlfail:{message_id}`.

**Тесты:** `backend/tests/integration/test_data.py` (шлюз в процессе, источник SQLite),
`services/data-gateway/tests/`.
