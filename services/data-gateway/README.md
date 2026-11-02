# services/data-gateway

Семантический слой над корпоративными SQL-БД (§9.5): модель видит только описанные в каталоге наборы
данных и функции, а не строки подключения и не схему БД. Вызывает шлюз только `api`.

## Каталог

`catalog/` (в контейнере — `/srv/catalog`), перечитывается без перезапуска; ошибка в новой версии не
роняет шлюз — работает последняя корректная, ошибка видна в `/health` и в админке «Источники данных».

* `sources.yaml` — подключения: `name`, `dialect` (`mssql`; `sqlite` и `postgresql` — для тестов),
  `url` (URL SQLAlchemy; `${ИМЯ}` — из `/run/secrets/<имя>` или переменной окружения), `timeout_s`
  (15), `max_rows` (1000). У каждого источника — логин только на чтение с `SELECT` на нужные
  представления.
* `datasets/*.yaml` — наборы поверх представлений: описание, колонки (тип, описание, синонимы,
  примеры, `pii`), связи, метрики, роли с доступом (пусто — всем), RLS (`column`, `equals:
  "{user.department}"` или `"{user.login}"`, `unless_roles`), примеры «вопрос → SQL».
* `functions/*.yaml` — параметризованный T-SQL с типизированными параметрами (`string`, `integer`,
  `number`, `boolean`, `date`; `required`, `default`, `min_length`/`max_length`, `min`/`max`,
  `enum`), роли с доступом. Строки склеивайте `CONCAT(…)`, а не `+`.

Как добавить набор или функцию — [docs/guides/add-dataset.md](../../docs/guides/add-dataset.md).

## API

Каждый запрос — с заголовками `X-DG-Identity` (base64url JSON: `user_id`, `login`, `roles`,
`department`, `admin`, `ts`) и `X-DG-Signature` (HMAC-SHA256 секретом `DG_SECRET`); без верной
подписи или старше 60 секунд — 401.

| Метод | Что делает |
| --- | --- |
| `GET /health` | статус и ошибка каталога |
| `GET /v1/catalog` | наборы и функции, доступные ролям (админу — всё, с источником, ролями, RLS и SQL) |
| `GET /v1/datasets/{name}?question=` | описание набора и до 5 похожих примеров (эмбеддинги `DG_EMBED_URL`) |
| `POST /v1/functions/{name}` `{"params": {…}}` | вызов функции |
| `POST /v1/query` `{"sql": "…"}` | контролируемый text-to-SQL |

Ответ на запрос и функцию: `columns`, `rows` (до `max_rows`), `truncated`, `duration_ms`, `sql` —
итоговый T-SQL после RLS и ограничения строк (его `api` пишет в аудит), `params`, `datasets`, `rls`.
Ошибки: `400 rejected` — запрос не прошёл проверку (текст — модели), `422 query_failed` — ошибка
источника или тайм-аут, `404` — набора или функции нет или они недоступны.

## Проверка SQL (`guard.py`)

Разбор sqlglot в диалекте T-SQL; ровно одно выражение SELECT / WITH … SELECT / UNION. Отказ:
изменения данных и схемы, `EXEC`, `SELECT … INTO`, переменные и параметры, `OPENROWSET`,
`OPENQUERY`, `OPENDATASOURCE`, `OPENXML`, функции `xp_*` и `sp_*`, другие базы, таблицы вне наборов,
доступных ролям, колонки вне каталога, `*` (кроме `COUNT(*)`). Затем RLS — представление заменяется
подзапросом с условием (значения — параметрами), `TOP max_rows` (меньший TOP сохраняется), тайм-аут
источника; транзакция всегда откатывается. Проверенный T-SQL переводится в диалект источника.

## Настройки

`DG_SECRET` (или `DG_SECRET_FILE`, по умолчанию `/run/secrets/data_gateway_secret`), `DG_CATALOG_DIR`,
`DG_SECRETS_DIR`, `DG_EMBED_URL`, `DG_EMBED_MODEL`, `DG_PORT` (8090), `DG_LOG_LEVEL`. В логах — логин,
набор, число строк и время; текст SQL — только на уровне DEBUG.

## Запуск и тесты

* Дев-стенд: `make dev-up` поднимает `mock-mssql` (SQL Server 2022 Developer со справочником
  `dbo.v_phonebook`, `deploy/mock-mssql`) и `data-gateway` на http://localhost:8090.
* `uv run pytest services/data-gateway/tests` — проверка SQL (тесты безопасности §18.2) и API с
  источником SQLite (без Docker).
* `make test-data-gateway` — образ шлюза (pyodbc + ODBC Driver 18) против контейнера MS SQL:
  `python -m data_gateway check`.
