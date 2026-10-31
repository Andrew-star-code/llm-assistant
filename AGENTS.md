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
| `make dev-up` | Поднять дев-стенд с нуля: postgres, redis, qdrant, mock-ad, fake-llm, embed, api, worker, worker-kb, frontend |
| `make dev-down` / `make dev-reset` | Остановить стенд / остановить и удалить данные |
| `make check` | **Всё перед пушем:** линт → типы → тесты → docs-check → сборка образов |
| `make test` | Unit- и интеграционные тесты (pytest, Vitest; нужен Docker: testcontainers и mock-AD) |
| `make test-unit` | Быстрые тесты без Docker |
| `make lint` / `make fmt` | Линтеры (ruff, eslint, prettier) / автоформат |
| `make typecheck` | mypy strict, tsc |
| `make e2e` | Playwright против работающего api (сначала `make dev-up`) |
| `make eval-rag` | hit@5 и MRR поиска по 4 конфигурациям (`eval/rag`, `--check`) на моделях стенда |
| `make test-worker` | Самопроверка образа воркера: pandoc, LibreOffice, Tesseract (`worker check`) |
| `make gen-api` | OpenAPI → `frontend/src/api/` + `docs/reference/api.md` (после любого изменения API) |
| `make migrate` | Миграции Alembic |
| `make docs-config` | `docs/reference/config.md` из Pydantic-настроек (после изменения конфига) |
| `make docs-db` | `docs/reference/db-schema.md` из моделей SQLAlchemy (после изменения схемы) |
| `make docs-check` | README модулей, актуальность справочников, битые ссылки |
| `make deploy` | Выкатка на сервер — этап 10 |

CLI бэкенда: `uv run python -m app.cli --help` — `config check|docs`, `openapi`, `api-docs`, `db-docs`,
`ad check --user L [--password-prompt]`, `ad sync`, `create-admin --login L`, `worker check`, `kb list`, `kb import --kb <код> <папка>`.
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
├── config/                         # app.yaml, models.yaml (+ оверлеи <env>), prompts/, templates/; дальше scenarios…
├── deploy/compose/                 # docker-compose.yml, compose.dev.yml, .env.example
├── deploy/mock-ad/                 # Samba AD DC с тестовыми пользователями
├── eval/rag/                       # оценка поиска: корпус, questions.yaml, run.py
└── scripts/docs_check.py
```

Появятся по этапам: `services/data-gateway/`, `services/sandbox-runner/` ★,
`deploy/nginx/`, `deploy/models/`, `deploy/monitoring/`, `deploy/offline/`, `eval/scenarios/`, `config/scenarios/` и др. (§5).

### Карта изменений

| Хочу… | Где править | Что обновить вместе с этим |
| --- | --- | --- |
| Изменить вид сообщения или кнопки под ним | `frontend/src/features/message/` | e2e-тест сообщения |
| Добавить кнопку в поле ввода | `frontend/src/features/composer/` | строки в `i18n/` |
| Поменять рендер Markdown, формул, кода | `frontend/src/features/markdown/` | тесты рендера |
| Добавить инструмент для модели | `backend/app/modules/tools/builtin/` + регистрация в `tools/registry.py` | `docs/guides/add-tool.md`, тест на fake-LLM |
| Добавить корпоративный сценарий | админка «Сценарии» или `config/scenarios/*.yaml` | промпт в `config/prompts/scenarios/` |
| Сменить или добавить модель | `config/models.yaml` + `deploy/models/` | `docs/runbooks/models.md` |
| Изменить системный промпт | `config/prompts/system/` | прогон `eval/scenarios` |
| Добавить поле профиля из AD | маппинг атрибутов в конфиге + `modules/users/` + миграция + `features/profile/` | `docs/guides/ad-setup.md` |
| Добавить страницу админки | `frontend/src/admin/pages/` + `backend/app/modules/admin/` | новое право в `docs/reference/permissions.md` |
| Добавить метрику лимитов | `backend/app/modules/limits/` | админка «Лимиты», `docs/reference/config.md` |
| Добавить тип инцидента | `backend/app/modules/incidents/` | фильтры в админке |
| Добавить набор данных или функцию SQL | `services/data-gateway/catalog/` | описания полей и примеры запросов |
| Изменить формат стрима | `docs/architecture/sse-protocol.md` → `modules/completions/streaming.py` → `frontend/src/api/sse.ts` | версия протокола, тесты обеих сторон |
| Изменить схему БД | модель SQLAlchemy + `app/models.py` + миграция Alembic | `make docs-db` |
| Добавить право | `modules/rbac/permissions.py` | `docs/reference/permissions.md` |
| Добавить провайдер входа | `modules/auth/providers/` + `main.py::init_services` | README `modules/auth` |
| Добавить параметр конфигурации | `backend/app/core/config.py` (+ `config/*.yaml`) | `make docs-config` |
| Добавить или изменить эндпоинт | роутер модуля | `make gen-api`, тесты |
| Добавить сценарий fake-llm | `services/fake-llm/src/fake_llm/scenarios.py` | README сервиса, тест |
| Поддержать новый формат вложений | `modules/files/sniff.py` + `modules/ingestion/parsers.py` | README `ingestion`, тест в `tests/unit/test_files.py` |
| Сменить шаблон DOCX/PPTX | `config/templates/` | `config/templates/README.md` |
| Поменять параметры поиска или чанкинга | `rag.search`, `rag.chunking` в `config/app.yaml` | прогон `make eval-rag`; после смены BM25 — переиндексация |
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
- **`EventWriter`** вызывают параллельные инструменты: запись в Redis Stream — под замком, новые
  события пишите только через `emit`/`delta`.
- **Номера цитат** выдаёт `SourceBook` (общая на ответ); не нумеруйте фрагменты в инструментах
  сами — `render_fragments` в `tools/builtin/knowledge.py`.
