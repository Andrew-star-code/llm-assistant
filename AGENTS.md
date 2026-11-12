# AGENTS.md — правила и карта проекта для людей и ИИ-агентов

## 1. Что за проект

Корпоративный ИИ-ассистент в закрытом контуре: веб-чат для 200+ сотрудников с входом через AD,
RAG по базам знаний трёх уровней, инструментами (документы, файлы, SQL через семантический слой)
и админ-панелью, плюс OpenAI-совместимый API моделей для агентного кодинга разработчиков.
Всё работает на одном сервере с 4× A100 без внешних сетевых обращений.
Требования — [docs/SPEC.md](docs/SPEC.md) (единственный источник), прогресс — [docs/status.md](docs/status.md).

## 2. Команды

| Команда | Что делает |
| --- | --- |
| `make install` | Зависимости (uv, pnpm) и pre-commit-хуки |
| `make dev-up` | Поднять дев-стенд с нуля: postgres, redis, qdrant, mock-ad, mock-mssql, fake-llm, embed, api, generator, worker, worker-kb, scheduler, data-gateway, frontend |
| `make dev-down` / `make dev-reset` | Остановить стенд / остановить и удалить данные |
| `make check` | **Всё перед пушем:** линт → типы → тесты → docs-check → правила алертов → сборка образов |
| `make test` | Unit- и интеграционные тесты (pytest, Vitest; нужен Docker: testcontainers и mock-AD) |
| `make test-unit` | Быстрые тесты без Docker |
| `make lint` / `make fmt` | Линтеры (ruff, eslint, prettier) / автоформат |
| `make typecheck` | mypy strict, tsc |
| `make e2e` | Playwright против работающего api (сначала `make dev-up`) |
| `make eval-rag` | hit@5 и MRR поиска по 4 конфигурациям (`eval/rag`, `--check`) на моделях стенда |
| `make eval-scenarios` | Эталонные запросы сценариев + LLM-судья, сравнение с `baseline.json` |
| `make load-test` | Нагрузочный тест чата: 10 одновременных диалогов, цели §18.4 (`eval/load`; сначала `make dev-up`; параметры — `LOAD_ARGS`) |
| `make test-worker` | Самопроверка образа воркера: pandoc, LibreOffice, Tesseract (`worker check`) |
| `make test-data-gateway` | Самопроверка образа шлюза данных: ODBC Driver 18, подключение к mock-mssql, `search_employees` |
| `make test-monitoring` | Конфигурация Prometheus и тесты правил алертов (`deploy/monitoring`, promtool) |
| `make gen-api` | OpenAPI → `frontend/src/api/` + `docs/reference/api.md` (после любого изменения API) |
| `make migrate` | Миграции Alembic |
| `make docs-config` | `docs/reference/config.md` из Pydantic-настроек (после изменения конфига) |
| `make docs-db` | `docs/reference/db-schema.md` из моделей SQLAlchemy (после изменения схемы) |
| `make docs-check` | README модулей, актуальность справочников, битые ссылки |
| `make deploy` | Выкатка на сервер — этап 10 |

CLI бэкенда: `uv run python -m app.cli --help` — `config check|docs`, `openapi`, `api-docs`, `db-docs`,
`ad check --user L [--password-prompt]`, `ad sync`, `create-admin --login L`, `worker check`, `kb list`, `kb import --kb <код> <папка>`,
`ip list`, `ip unblock <IP или подсеть>`, `generator run|check`.
В дев-стенде: `docker compose … exec api python -m app.cli …`.

Вход на дев-стенде: провайдер dev — кнопки на странице входа (seed из `config/app.dev.yaml`);
через mock-AD — любой пользователь из `deploy/mock-ad/README.md`, пароль `Passw0rd!`;
суперадмин — `ivanov`.

## 3. Карта репозитория

```text
├── AGENTS.md · CLAUDE.md · README.md · CHANGELOG.md · Makefile
├── pyproject.toml · uv.lock        # uv workspace: backend + services/*
├── docs/                           # SPEC, status, architecture, adr, guides, reference, runbooks
├── backend/app/
│   ├── main.py                     # сборка FastAPI-приложения
│   ├── core/                       # config, logging, db, redis, qdrant, errors, health, request_context
│   ├── modules/<модуль>/           # бизнес-модули, у каждого README.md
│   ├── workers/                    # Celery: разбор вложений и генерация файлов (jobs.py — сама работа)
│   └── cli/                        # python -m app.cli …
├── backend/migrations/             # Alembic
├── backend/tests/                  # unit, integration, security
├── frontend/src/                   # app, api (генерируется), features, admin, components/ui, lib, i18n
├── services/fake-llm/              # OpenAI-совместимый mock для разработки и тестов
├── services/data-gateway/          # семантический слой SQL: catalog/*.yaml, проверка SQL, RLS (§9.5)
├── config/                         # app.yaml, models.yaml (+ оверлеи <env>), prompts/, templates/, scenarios/
├── deploy/compose/                 # docker-compose.yml, compose.dev.yml, .env.example
├── deploy/mock-ad/                 # Samba AD DC с тестовыми пользователями
├── deploy/mock-mssql/              # SQL Server 2022 Developer с тестовым телефонным справочником
├── deploy/monitoring/              # prometheus.yml, alerts.yml (+ тесты правил); compose и Grafana — этап 10
├── eval/                           # rag/ (hit@5, MRR), scenarios/ (эталоны, LLM-судья), load/ (нагрузка)
└── scripts/docs_check.py
```

Появятся по этапам: `services/sandbox-runner/` ★,
`deploy/nginx/`, `deploy/models/`, `deploy/offline/` и др. (§5).

### Карта изменений

| Хочу… | Где править | Что обновить вместе с этим |
| --- | --- | --- |
| Изменить вид сообщения или кнопки под ним | `frontend/src/features/message/` | e2e-тест сообщения |
| Добавить кнопку в поле ввода | `frontend/src/features/composer/` | строки в `i18n/` |
| Поменять рендер Markdown, формул, кода | `frontend/src/features/markdown/` | тесты рендера |
| Добавить инструмент для модели | `backend/app/modules/tools/builtin/` + регистрация в `tools/registry.py` | `docs/guides/add-tool.md`, тест на fake-LLM |
| Добавить корпоративный сценарий | админка «Сценарии» или `config/scenarios/*.yaml` | промпт в `config/prompts/scenarios/`, эталоны в `eval/scenarios/`, `docs/guides/add-scenario.md` |
| Сменить или добавить модель | `config/models.yaml` + `deploy/models/` | `docs/runbooks/models.md` |
| Изменить системный промпт | `config/prompts/system/` | прогон `eval/scenarios` |
| Добавить поле профиля из AD | маппинг атрибутов в конфиге + `modules/users/` + миграция + `features/profile/` | `docs/guides/ad-setup.md` |
| Добавить страницу админки | `frontend/src/admin/pages/` + `backend/app/modules/admin/` | новое право в `docs/reference/permissions.md` |
| Добавить метрику лимитов | `core/config.py::LimitMetric` + `modules/limits/` + место проверки | `docs/guides/add-limit-metric.md`, админка «Лимиты», i18n, `make docs-config` |
| Добавить метрику Prometheus | `backend/app/core/metrics.py` + место записи | таблица в `deploy/monitoring/README.md`; правило в `alerts.yml` — с тестом в `alerts.test.yml` (`make test-monitoring`) |
| Добавить тип инцидента | `backend/app/modules/incidents/` | фильтры в админке |
| Добавить набор данных или функцию SQL | `services/data-gateway/catalog/` | описания полей и примеры запросов, `docs/guides/add-dataset.md`, проверка в админке «Источники данных» |
| Изменить формат стрима | `docs/architecture/sse-protocol.md` → `modules/completions/streaming.py` → `frontend/src/api/sse.ts` | версия протокола, тесты обеих сторон |
| Изменить схему БД | модель SQLAlchemy + `app/models.py` + миграция Alembic | `make docs-db` |
| Добавить право | `modules/rbac/permissions.py` | `docs/reference/permissions.md` |
| Добавить провайдер входа | `modules/auth/providers/` + `main.py::init_services` | README `modules/auth` |
| Добавить параметр конфигурации | `backend/app/core/config.py` (+ `config/*.yaml`) | `make docs-config` |
| Добавить или изменить эндпоинт | роутер модуля | `make gen-api`, тесты |
| Добавить сценарий fake-llm | `services/fake-llm/src/fake_llm/scenarios.py` | README сервиса, тест |
| Поддержать новый формат вложений | `modules/files/sniff.py` + `modules/ingestion/parsers.py` | README `ingestion`, тест в `tests/unit/test_files.py` |
| Сменить шаблон DOCX/PPTX | `config/templates/` | `config/templates/README.md` |
| Поменять параметры поиска или чанкинга | `rag.search`, `rag.chunking` в `config/app.yaml`; порог реранкера — и в админке «Базы знаний» (перекрывает конфиг) | прогон `make eval-rag` (по реальным базам — `KB=… QUESTIONS=…`); после смены BM25 — переиндексация |
| Добавить уровень или поле базы знаний | `modules/kb/` + `modules/rag/service.build_scope` | тесты изоляции в `test_rag.py` |

## 4. Соглашения

- **Язык.** Идентификаторы, имена файлов и сообщения коммитов — на английском; документация,
  комментарии и строки интерфейса — на русском (строки — только через i18n).
- **Коммиты** — [Conventional Commits](https://www.conventionalcommits.org/): `feat(chats): …`,
  `fix(auth): …`, `docs: …`, `chore: …`, `test: …`. Маленькие коммиты; каждый собирается и проходит тесты.
- **Python** 3.12: ruff (линт + формат, длина строки 100), mypy strict, Pydantic v2, async везде,
  где есть I/O. Модули общаются через сервисы, а не через чужие таблицы.
- **TypeScript** strict, ESLint (typescript-eslint strictTypeChecked) + Prettier; импорт через `@/`.
- **Зависимости** — только с обоснованием (ADR или описание задачи), версии закреплены lock-файлами
  (`uv.lock`, `pnpm-lock.yaml`), образы — по digest.
- **Конфиг** — поведение в `config/*.yaml`, секреты — только в `.env` / `/run/secrets`.

## 5. Порядок работы

1. Перед этапом: прочитать SPEC §20, сам этап в §19 и разделы, на которые он ссылается; записать план
   в `docs/status.md`.
2. Задачу берёт человек или агент — отметка в `docs/status.md` («Кто чем занят»), чтобы не править
   одни файлы одновременно.
3. Каждая задача — в своей ветке: `agent/<задача>` или `<имя>/<задача>`.
4. `make check` обязателен перед каждым пушем — и для людей, и для агента (CI-сервера нет).
   pre-commit-хуки запускают быстрые проверки при каждом коммите.
5. В `main` вливает человек после просмотра диффа и зелёного `make check`.
6. Неясное не додумывать: вопрос — в `docs/status.md`, вариант по умолчанию — из SPEC,
   в коде — `TODO(question)`. Задел на будущий этап — `TODO(stage-N)`.
7. Не переходить к следующему этапу, пока не отмечены все критерии приёмки текущего.
8. Этап завершается демо-сценарием в `docs/status.md`: какие команды выполнить и что должно получиться.

## 6. Definition of Done

Код; тесты (unit, а для пользовательского потока — интеграционный или e2e); миграции;
перегенерированный API-клиент (`make gen-api`); обновлённые README модуля, SPEC и guides, если
поменялось поведение; запись в `docs/status.md` и `CHANGELOG.md`; зелёный `make check`.

## 7. Подводные камни

- **SSE за nginx** — только с `proxy_buffering off` и увеличенным `proxy_read_timeout`, иначе стрим
  приходит одним куском в конце.
- **Делимитеры формул** `\(…\)` и `\[…\]` нормализуются в `$…$` / `$$…$$` перед рендером.
- **Права RAG** — только через серверный фильтр в каждом prefetch Qdrant; модель может сузить поиск,
  но не расширить.
- **Скрытые инструменты** (`report_incident`) не уходят ни в пользовательский API, ни в SSE,
  ни в выгрузки пользователя — это обеспечивает сервер, а не модель.
- **Провайдер `dev`** запрещён в prod: приложение с ним не стартует (проверка в `core/config.py`).
- **Секреты не логируются**: пароли, токены, cookie, тексты сообщений — не на уровне INFO;
  `core/logging.redact_secrets` — страховка, а не разрешение.
- **Пустой пароль** отклоняется до обращения к AD — bind с пустым паролем AD считает анонимным
  и «успешным».
- **Никаких внешних обращений и CDN** в рантайме: модели, шрифты, KaTeX, pdf.js — только локально.
  Без inline-скриптов (CSP) — поэтому тема применяется внешним `frontend/public/theme-init.js`.
- **mock-AD** требует `cap_add: SYS_ADMIN` (Samba пишет NT ACL в xattr) — только дев-стенд.
- **Права — в каждом админ-эндпоинте** через `Depends(require(Perm.…))`; тест
  `test_every_admin_endpoint_requires_permission` упадёт, если забыть. Действие над чужими
  данными без `audit.record` — ошибка ревью.
- **CSRF**: все изменяющие запросы под `/api` требуют `X-CSRF-Token`; фронтенд ставит его сам
  (`frontend/src/api/client.ts`), в тестах — `ApiClient` из `backend/tests/integration/conftest.py`.
- **Ответ может завершиться раньше `message.end`**: если чат перечитали по REST, статус уже не
  `streaming` и подписка на SSE закрывается — побочные действия «по окончании» (обновить историю)
  делаются по переходу статуса, а не только по событию (`frontend/src/features/chat/live.ts`).
- **fake-llm опирается на строки промптов** `Обращение к пользователю: …`, `Придумай короткий
  заголовок` и `=== Файл «…»` (`config/prompts/README.md`) — меняете шаблон, обновите и fake-llm.
- **Все объекты пользователя — через `chats.service.get_*`**: они проверяют владельца и отдают 404
  на чужое; прямой `db.get(Chat, id)` в роутере — дыра IDOR.
- **Виртуальный список истории**: строки с `transform` — отдельные контексты наложения; всплывающее
  меню строки поднимается `has-[[role=menu]]:z-20`.
- **ldap3 синхронный** — вызовы AD только через `asyncio.to_thread`; тайм-ауты сокета — целые секунды.
- **Конфиг слоями**: init-аргументы `Settings(...)` сливаются с YAML, а не заменяют его — в тестах
  конфигурацию подменяйте через `APP_CONFIG_DIR` на временный каталог.
- **Воркер в тестах — eager**: `worker.eager=true` выполняет задачу в потоке api без Celery и
  брокера; в проде api только ставит задачу. Бинарники (LibreOffice, Tesseract) есть только в образе
  воркера — код api не должен вызывать их напрямую (`preview_pdf` и OCR — в задачах воркера).
  Eager скрывает то, чего нет в процессе воркера: модели SQLAlchemy регистрирует `import app.models`
  в `workers/jobs.py` — новая модель без него ломает задачи только на настоящем Celery
  (ловят `test_worker_imports.py` и `worker check`). Новые задачи оборачивайте страховкой, как
  `parse_job`: сбой → статус «ошибка» и инцидент `worker_failed`, а не вечное «в обработке».
- **Файлы инструментов — только из вложений чата**: `ToolContext.attachments` строит сервер; аргумент
  модели `file` лишь выбирает из этого списка. Права на поиск в Qdrant — фильтр по id этих файлов.
- **`.mjs` в nginx**: воркер pdf.js — ES-модуль; без `application/javascript` для `.mjs`
  (`frontend/nginx.conf`, прод-gateway этапа 10) просмотр PDF не работает.
- **CSP `sandbox` на скачивании** ломает имя файла в Chromium — только на inline-ответах.
- **Колбэки `mutate(…, {onSuccess})`** не вызываются, если компонент размонтирован раньше (типично
  для пунктов списка, который перечитывается в общем `onSuccess`) — для навигации после мутации
  используйте `mutateAsync().then(…)`.
- **Playwright и кириллица**: без UTF-8-локали Chromium называет скачанный файл «download» —
  локаль задана в `playwright.config.ts`.
- **Права поиска строит сервер** (`rag.service.build_scope`) при каждом запросе; инструменты и
  авто-поиск получают готовый `Scope` и могут его только сузить. Тест изоляции — отдельно для
  dense и BM25 (`test_rag.py`), меняете фильтры — гоняйте оба.
- **Удаление документа базы** удаляет его точки из Qdrant сразу в api (`kb.service.remove_document`),
  не через очередь: «пропадает из поиска за минуту» — это гарантирует api.
- **Новая версия документа** пишется с новым `version` в id точек и вытесняет старые
  (`rag.store.write_document`); переиндексация = `mark_reindex` (version + 1) и задача `kb.index`.
- **Генерация живёт в `generator`, а не в `api`** (ADR-0013): `GenerationManager.start` в api
  только ставит задание в `gen:queue`. Код генерации и инструментов не должен опираться на
  `app.state` и объекты запроса — их в исполнителе нет; новая модель SQLAlchemy регистрируется
  через `import app.models` (ловит `test_worker_imports.py`). В тестах — `generation.mode: inline`
  (задача в api, как `worker.eager`); очередь, остановку и сам процесс проверяет
  `test_generator.py`. `stop_grace_period` сервиса — больше `generation.shutdown_grace_seconds`.
- **SSE-поток не держит соединение с БД**: эндпоинт стрима закрывает сессию запроса
  (`await db.close()`) до начала потока и дальше открывает короткие сессии. Долгий ответ
  (стрим, long-poll) с `DbDep` до конца держит соединение и транзакцию — пул (20 соединений)
  кончается на паре десятков одновременных ответов, и встаёт весь api.
- **Блокирующие вызовы Redis короче тайм-аута чтения**: клиент (`core/redis.py`) рвёт чтение
  через `chat.heartbeat_seconds` + 5 с; `XREAD BLOCK` и `BLPOP` должны ждать меньше. Каждый
  открытый SSE держит соединение Redis — размер пула `redis_max_connections`. В тестах
  heartbeat — 1 с, поэтому такие ошибки видны только под нагрузкой (`make load-test`).
- **Метки метрик — только из закрытых наборов** (`core/metrics.py`): роль модели, статус, имя
  зарегистрированного инструмента. Логин, id чата или имя инструмента, придуманное моделью, в
  метке — неограниченное число рядов в Prometheus. Метрики генерации пишет `generator`, не `api`.
- **Сообщения цикла инструментов — только через `LoopContext`** (`completions/context.py`):
  `add_calls`/`add_result` считают токены, `fit()` перед запросом возвращает промпт в бюджет.
  Прямой `messages.append` в цикле обходит бюджет — модель ответит ошибкой на длинном чате.
  Всё, что попадает в промпт помимо сообщений (описания инструментов), учитывайте в `overhead`.
- **`EventWriter`** вызывают параллельные инструменты: запись в Redis Stream — под замком, новые
  события пишите только через `emit`/`delta`.
- **Порог реранкера из админки** (`app_settings`) применяет `rag.service.run_search`; прямой вызов
  `rag.search.search` с `settings.rag.search` (тесты, eval по корпусу) поправку не видит — новый
  поиск в продукте делайте через `run_search`.
- **Настройки из админки перекрывают конфиг** (`app_settings`): название, компания, лимиты файлов,
  обращение, срок хранения — читайте через `app_settings.effective(db, settings)` в момент
  применения; прямой `settings.files.max_file_mb` правку админа не видит. Базовый промпт из
  админки — только песочница Jinja2 (`scenarios.service.render_admin_template`).
- **Переписка в админке**: просмотр чата целиком — запись `chat.view` в аудит при каждом открытии;
  новый эндпоинт, отдающий переписку целиком, тоже пишет аудит. Списки и поиск показывают только
  фрагменты. Физическое удаление — `chats.purge.purge_chat`, файлы и точки Qdrant — после commit.
- **Ошибки — уже инциденты**: необработанное исключение в API становится `system_error` со стеком
  и логом запроса (`core/log_capture`), поэтому всё, что логируется, может оказаться в карточке
  инцидента — тем строже правило «без секретов и текстов сообщений на INFO».
- **Блокировки IP проверяются на каждом запросе** (`security.ipblocks.Blocklist` в `current_user` и
  при входе); после изменения блокировок вызывайте `await blocklist.changed()` — иначе другие
  процессы увидят их только через `security.blocklist_cache_s`.
- **IP клиента на дев-стенде** приходит через прокси Vite (`xfwd`) в `X-Forwarded-For`, которому
  api верит из частных сетей Docker (`trusted_proxies` в `config/app.dev.yaml`); в проде доверять
  только адресу nginx. Заблокировали свой адрес — `python -m app.cli ip unblock <IP>`.
- **Лимиты — до запроса и по факту**: любой новый путь к генерации для пользователя резервирует
  `limits.reserve_generation` до создания ответа и возвращает резерв `limits.cancel`, если запрос
  сорвался; слот и списание токенов делает `GenerationManager`. Счётчики пишите только через
  `counters.spread` (все окна сразу), а не прямым INCR. Нет политики — метрика без ограничения;
  список `limits.defaults` в оверлее заменяет базовый целиком.
- **`usage_records` секционирована по месяцам**: ключ — `(id, ts)`; разделы вперёд создаёт задача
  `limits.partitions`, без раздела строки идут в `usage_records_default`.
- **Данные — только через `data-gateway`**: модель не видит строк подключения; `api` подписывает
  идентичность пользователя (`modules/data/client.py`), шлюз проверяет SQL и подставляет RLS.
  Каждый запрос к данным и вызов функции пишется в аудит (`data.query`, `data.function`), включая
  отклонённые — новый инструмент данных обязан делать так же. В SQL функций строки склеивайте
  `CONCAT(…)`, а не `+`: в тестах шлюз переводит T-SQL в SQLite (`data_gateway.testing`).
- **`.gitignore`**: `/data/` и `/storage/` — только в корне; модуль `backend/app/modules/data` — код.
- **Скрытый `report_incident`** всегда в наборе инструментов (сценарий его не убирает), а его
  инструкция — отдельный шаблон `system/moderation.md.j2`, не заменяемый промптом из админки.
- **Номера цитат** выдаёт `SourceBook` (общая на ответ); не нумеруйте фрагменты в инструментах
  сами — `render_fragments` в `tools/builtin/knowledge.py`.
- **Сценарий читается из БД на каждое сообщение** (`completions/generation.py`) — не кэшируйте
  его: «правка действует без перезапуска» — критерий приёмки. Seed из `config/scenarios` только
  добавляет новые коды и не трогает правки админа.
- **Промпт сценария — шаблон админа**: рендер только через `scenarios.service.render_prompt`
  (песочница Jinja2), никогда через `PromptRenderer` файловых шаблонов.
- **Тестовые чаты** (`chats.is_test`) не попадают в историю и поиск — новые выборки чатов
  пользователя фильтруйте по `is_test` так же. e2e создают сценарии выключенными, чтобы не засорять
  стартовый экран дев-стенда.
