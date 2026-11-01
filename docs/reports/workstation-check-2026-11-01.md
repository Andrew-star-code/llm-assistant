# Проверка проекта с нуля на рабочей станции (Windows + WSL2), 2026-11-01

Ветка `claude/charming-ride-5jb5sd`, коммит `c402015`. Продуктовый код и тесты не менялись.

## Итог

- **`make check` зелёный, образ воркера собран**, три проверки `make test-worker` прошли. Но зелёный
  `make check` не означает рабочий воркер, см. дефект 1.
- **Дефект 1 (блокер):** настоящий Celery не работает. Все задачи `files.parse`, `files.generate`,
  `kb.index`, `kb.import` и CLI `kb import` падают с `NoReferencedTableError`. На чистом продукте:
  e2e 15 из 22, вложения и база знаний не работают, превью XLSX нет.
- **С временно загруженными моделями** (флаг запуска воркера, код не менялся) всё заявленное
  работает: e2e 22 из 22, превью XLSX, импорт, продолжение после перезапуска, поиск с цитатой.
- **Дефект 2:** критерий этапа 4 «гибрид с реранкером не хуже остальных» **не выполнен**
  (hit@5 0,854 против 1,0). Причина — порог `score_threshold: 0.2`, а не сам реранкер: с порогом 0
  получается hit@5 1,0 и MRR 1,0, лучший результат из всех конфигураций.
- **Память:** 12 ГБ для WSL недостаточно. `embed` с реранкером на 15,6 ГБ подвесили VM на 45 минут.

## 1. Окружение

| Что | Значение |
| --- | --- |
| Windows | 11 Home 25H2, сборка 26200.9711 |
| WSL | 2.7.11.0, ядро 6.18.33.2-microsoft-standard-WSL2, WSLg 1.0.73.2 |
| Дистрибутив | Ubuntu 24.04.5 LTS (не было, установлен для проверки) |
| Docker | Docker Desktop, клиент и сервер 29.6.2, Compose v5.3.1, WSL integration включена |
| git / make | 2.43.0 / GNU Make 4.3 |
| uv | 0.13.6 |
| Node / pnpm | v22.23.4 (nvm) / 10.28.0 (corepack) |
| CPU | AMD Ryzen 5 7600X3D, 6 ядер, 12 потоков |
| RAM | 31,1 ГБ; в WSL 15 ГБ по умолчанию, с шага 4 — 22 ГБ |
| Свободно | C: 72 ГБ, E: 227 ГБ (достаточно) |
| Сеть | веса HF ~1,7 МБ/с |

Что пришлось сделать в окружении сверх инструкции:

- Установить Ubuntu 24.04 (`E:\WSL\Ubuntu-24.04`), сделать её дистрибутивом по умолчанию, создать
  пользователя `andre`.
- Включить интеграцию: `IntegratedWslDistros` в `%AppData%\Docker\settings-store.json`.
- `corepack install -g pnpm@10.28.0` (находка 3).
- `playwright install --with-deps chromium` (119 с), в инструкции шага нет.
- Создать `%UserProfile%\.wslconfig` с `memory=22GB` (дефект 5).

## 2. Шаги

Столбец «чистый» — продукт как есть. «С обходом» — воркеры запущены с `-I app.models`, код не менялся
(раздел 3, дефект 1).

| Шаг | Чистый | С обходом | Время | Примечание |
| --- | --- | --- | --- | --- |
| 0. Окружение | ⚠️ | — | инструменты 23 с, клон 1 с | не было дистрибутива WSL; установка не замерена |
| 1. `make install` | ⚠️ | — | 40 с (сбой), 13 с | падает при `corepack enable`, находка 3 |
| 1. `make check` | ✅ | — | 10:10 с нуля, 1:40 повторно | `make check: OK` на втором прогоне |
| 1. Образ `ai-assistant/worker` | ✅ | — | все образы 5:37 | `apt-get install` прошёл, образ 1,95 ГБ |
| 1. `make test-worker` | ✅ | — | 8 с | pandoc ✓, libreoffice ✓, tesseract ✓ |
| 1. pytest | ✅ | — | 3:57, повторно 1:08 | 223 passed, 5 skipped (всего 228) |
| 1. Vitest | ✅ | — | 4 с | 56 passed |
| 2. `make dev-up` | ⚠️ | — | 11:21 (сбой), 1:00 | `embed` unhealthy при закачке, находка 4; готов за 23:45 |
| 2. `/ready` | ✅ | — | — | postgres, redis, qdrant — `ok` |
| 2. e2e | ❌ | ✅ | 4:17 / 1:38 | 15 из 22 / 22 из 22 |
| 2. `files.parse`, `files.generate` | ❌ | ✅ | — | все падают / parse 4 и generate 6 успешно |
| 2. Превью XLSX, «Просмотр» | ❌ | ✅ | — | проверено в браузере, PDF с таблицей открылся |
| 3. CLI `kb import` | ❌ | не проверено | — | падает сам CLI; в обходе импорт шёл через админ-API |
| 3. `kb.import`, `kb.index`, «готово 2» | ❌ | ✅ | 10 с | импорт зависает в `scanning` / `готово 2` |
| 3. Продолжение после перезапуска | нельзя проверить | ✅ | 3:15 | 25 файлов, перезапуск после 6 готовых, итог 27 без дублей |
| 3. Поиск `ORION-2026-KB` в UI | нельзя проверить | ✅ | — | цитата 1, «regulation · Регламенты · стр. 2», PDF на 2-й странице |
| 4. `make dev-models-up` | ❌ | — | зависание 45 мин | дефект 5; после перезапуска с 22 ГБ работает |
| 4. `make eval-rag` | ❌ | — | 5:17 | инструмент отработал, критерий не выполнен, дефект 2 |
| 4. `--json` по инструкции | ⚠️ | — | 5:27 (сбой), 5:21 | нет прав на запись, находка 6 |

«Нельзя проверить»: на чистом продукте импорт не стартует, и проверять нечего. «Продолжение» с обходом шло
через `docker restart` диагностического контейнера, а не `compose restart worker-kb`. `make check` с нуля
занял 10:10 без фронтенд-частей: они упали из-за находки 3 и были быстро повторены вторым прогоном.

## 3. Разбор ❌ и ⚠️

### Дефект 1 ❌. Воркеры и CLI не регистрируют все модели

Команды: `make dev-up`, затем e2e или импорт из инструкции.

```text
File "/srv/backend/app/workers/celery_app.py", line 60, in parse_file_task
  asyncio.run(jobs.parse_job(file_id, get_settings()))
File "/srv/backend/app/workers/jobs.py", line 117, in parse_job
  await db.commit()
[error] Task files.parse[…] raised unexpected: NoReferencedTableError("Foreign key associated with
  column 'files.chat_id' could not find table 'chats' …")
[error] Task files.generate[…] raised unexpected: NoReferencedTableError("… 'files.chat_id' … 'chats' …")
[error] Task kb.index[…] raised unexpected: NoReferencedTableError("… 'kb_documents.uploaded_by' … 'users' …")
[error] Task kb.import[…] raised unexpected: NoReferencedTableError("… 'kb_imports.created_by' … 'users' …")
```

`… exec api python -m app.cli kb import --kb regs regs`, код выхода 1:

```text
sqlalchemy.exc.NoReferencedTableError: Foreign key associated with column 'kb_imports.created_by'
could not find table 'users' with which to generate a foreign key to target column 'id'
```

**Причина подтверждена.** `workers/jobs.py` импортирует только `app.modules.files.models`, а таблицы
`chats` и `users` в `Base.metadata` не попадают. `import app.models` есть в `migrations/env.py` и
`cli/db_docs.py`, но не в воркере и не в `cli/kb.py`. `make check` этого не видит: в тестах
`worker.eager=true` и задача идёт в процессе api, где все модели уже загружены, а `worker check`
не обращается к БД.

Проверка в чистом интерпретаторе контейнера api:

```text
import app.workers.celery_app; Base.metadata.sorted_tables   → NoReferencedTableError
то же + import app.models                                    → OK, 22 таблицы
import app.models, app.workers.jobs, app.cli.kb              → OK, циклов импорта нет
```

Предлагаемый diff, одна строка: `celery_app` и `cli/kb.py` (через `dispatch`) импортируют `jobs`.

```diff
--- a/backend/app/workers/jobs.py
+++ b/backend/app/workers/jobs.py
@@
 from sqlalchemy.pool import NullPool

+import app.models  # noqa: F401 — регистрирует все таблицы: воркер и CLI не поднимают api
 from app.core.config import Settings
```

Регрессионный тест (набросок, логика проверена командой выше): в отдельном процессе
`python -c "import app.workers.celery_app; from app.core.db import Base; Base.metadata.sorted_tables"`
и то же для `app.cli.kb`, код выхода 0.

**Обход для проверки.** Чтобы убедиться в гипотезе и пройти шаги 2–3, воркеры на время запускались
`docker compose run` с готовым флагом Celery `-I app.models`. Файлы репозитория не менялись, по
окончании контейнеры удалены, стенд возвращён к исходным сервисам. Сам diff на воркерах не запускался:
проверен эквивалентный импорт.

Первый прогон e2e с обходом дал 20 из 22 по моей ошибке: `compose start worker-kb` поднял и исходный
`worker` как зависимость, он забирал часть задач `files` и падал на них. После его остановки — 22 из 22.

### Дефект 2 ❌. Порог реранкера 0,2 отсекает верные ответы

`make eval-rag`, код выхода 2 (`--check`). Полная таблица в разделе 4. Стадия rerank не пропускалась.

**Причина подтверждена.** Реранкер не ошибается: верный документ первым в 48 из 48 вопросов. Но у коротких
запросов и перефразов балл ниже 0,2, порог убирает все фрагменты, и у всех 7 промахов список пуст.
`score_threshold: 0.2` — значение из SPEC §10.4 и `core/config.py`.

Предлагаемый diff, **после решения человека**: порог из SPEC, значение подобрано на маленьком корпусе.

```diff
--- a/config/app.yaml
+++ b/config/app.yaml
@@ rag.search
     rerank:
+      score_threshold: 0.01
```

Ограничение: в `questions.yaml` нет вопросов без ответа, поэтому не проверено, как порог работает
фильтром «ничего не найдено». Шум доходит до 0,0288, а минимальный верный балл 0,0114, так что порог не
разделяет их полностью. Перед сменой порога стоит добавить такие вопросы в `eval/rag`.

### Дефект 5 ❌. Памяти 12–15 ГБ не хватает для `embed` и реранкера

Команда: `make dev-models-up` при работающем стенде, память WSL по умолчанию (15,6 ГБ).

Что наблюдалось: через 13 минут, в 13:10, VM перестала отвечать на 45 минут. Загружено 10–11 ядер из 12,
память на лимите, диски ~280 МБ/с, `docker ps` → 500, сервисы молчат, `wsl.exe` →
`Wsl/Service 0x8007274c`. Записей OOM в журнале ядра нет, изнутри само зависание никто не видел. Вернуть
VM удалось через `wsl --shutdown`.

**Причина — нехватка памяти.** Прямого лога зависания нет, но та же пара исчерпала память и при 22 ГБ,
журнал `free` и `docker stats` каждые 10 с:

```text
14:00:39  Mem: 21223/22016 MB  available 793   Swap: 6110/6144   memory pressure some=43%
          ai-assistant-embed-1   11 GiB
          ai-assistant-rerank-1  7.4 GiB (прогрев)
14:01:05  Mem: 21953/22016 MB  available 62    Swap: 6144/6144   memory pressure some=72%
```

Здесь `embed` пришлось остановить вручную, чтобы не получить второе зависание. После этого реранкер
закончил прогрев, упал до 2,2 ГиБ, и `embed` запустился за 57 с. Устойчивое потребление: `embed` 12,3 ГиБ
+ `rerank` 2,2 ГиБ, стенд ~17 ГБ. При eval реранкер занимал около 2,5 ГиБ.

Из-за `restart: unless-stopped` оба сервиса после перезапуска Docker прогреваются одновременно. Именно это
привело к пределу на 22 ГБ. Дойдёт ли такой старт до конца сам, не проверялось: он был прерван вручную.

Предлагаемое: в `eval/README.md` и `docs/guides/add-model.md` указать `memory=22GB` вместо «не меньше
8 ГБ» и предупредить, что `embed` и `rerank` надо прогревать по очереди. Снижение памяти через параметры
TEI (`--max-batch-tokens` и др.) не проверялось.

### Находка 3 ⚠️. `make install` падает при `corepack enable`

```text
pnpm --dir frontend install --frozen-lockfile
Error: ERR_PNPM_BAD_PM_VERSION
  × This project is configured to use 10.28.0 of pnpm. Your current pnpm is v12.16.1
make: *** [Makefile:24: install] Error 1
```

Corepack выбирает версию по текущей папке. В корне нет `package.json`, и `--dir frontend` ему не
указ, поэтому берётся последний pnpm. Из-за этого в `make check` упали `lint`, `typecheck` и Vitest.

Проверенное решение для инструкции и README:

```bash
corepack install -g pnpm@10.28.0
```

### Находка 4 ⚠️. Первый `make dev-up` падает на медленной сети

```text
12:17:02 container ai-assistant-embed-1 is unhealthy
make: *** [Makefile:35: dev-up] Error 1
```

Healthcheck сдаётся через `30 с + 60 × 10 с`, а закачка шла 21:38, сервис готов за 23:45. Контейнер жив,
закачка продолжается, повторный `make dev-up` проходит за минуту. `--wait-timeout 900` тоже меньше.
Предлагаемый diff (не проверялся):

```diff
--- a/deploy/compose/compose.dev.yml
+++ b/deploy/compose/compose.dev.yml
@@ embed: healthcheck
-      retries: 60
+      retries: 180
@@ rerank: healthcheck
-      retries: 90
+      retries: 180
--- a/Makefile
+++ b/Makefile
-	$(COMPOSE) up -d --build --wait --wait-timeout 900
+	$(COMPOSE) up -d --build --wait --wait-timeout 2100
-	$(COMPOSE) --profile models up -d --wait --wait-timeout 1800 rerank
+	$(COMPOSE) --profile models up -d --wait --wait-timeout 2100 rerank
```

### Находка 6 ⚠️. `--json` из инструкции не может записать файл

```text
PermissionError: [Errno 13] Permission denied: '/srv/eval/rag/report.json'
```

Контейнер работает под uid 10001, папка принадлежит пользователю 1000. Вероятно, то же у
`make eval-scenarios`: он пишет в смонтированный `eval/scenarios/` (не запускался). `report.json` сохранён
через отдельную папку с правом записи. Проверено: `docker compose run --user "$(id -u):$(id -g)"` пишет
в смонтированную `eval/`, это и есть предлагаемое исправление. Кроме того, `eval/rag/report.json` в
`.gitignore`, поэтому в этот коммит он добавлен через `git add -f`.

### Находка 7 ⚠️. Плавающий `admin.spec` на Vite dev-сервере

На `E2E_BASE_URL=http://localhost:5173` упал 4 раза из 6, на собранной SPA прошёл 3 из 3. Продукт исправен:
`/api/admin/ad/diagnostics` отвечает 200, запроса в трассе нет, поле «Логин» пустое. Метку «Логин» имеет и
фильтр страницы «Входы», `fill("kim")` попадает в него до загрузки lazy-страницы, а дальше пустое `required`
блокирует отправку. Предлагаемый diff только для теста (не проверялся):

```diff
--- a/frontend/tests/e2e/admin.spec.ts
+++ b/frontend/tests/e2e/admin.spec.ts
@@
   await page.getByRole("link", { name: "Диагностика AD" }).click();
+  await expect(page.getByRole("heading", { name: "Диагностика AD" })).toBeVisible();
   await page.getByLabel("Логин").fill("kim");
```

### Находка 8 ⚠️. e2e не проверяет превью XLSX

В `files.spec.ts` «Просмотр» проверяется под `if ((await preview.count()) > 0)`, поэтому без превью тест
зелёный. Превью проверено отдельно: по `files.preview_key` и вручную в браузере. Для прогонов с настоящим
воркером стоит сделать проверку обязательной, например по переменной окружения.

## 4. `make eval-rag`

Первая строка: `Модели: BAAI/bge-m3, реранкер BAAI/bge-reranker-v2-m3 (tei)`. `degraded` пуст. Сохранён
в [`eval/rag/report.json`](../../eval/rag/report.json).

| Конфигурация | hit@5 | MRR | hit@5 english | hit@5 exact_id | hit@5 paraphrase | hit@5 word_form |
| --- | --- | --- | --- | --- | --- | --- |
| dense | 1.0 | 0.99 | 1.0 | 1.0 | 1.0 | 1.0 |
| bm25 | 0.917 | 0.91 | 1.0 | 1.0 | 0.667 | 1.0 |
| hybrid | 1.0 | 0.986 | 1.0 | 1.0 | 1.0 | 1.0 |
| hybrid+rerank | 0.854 | 0.854 | 0.917 | 1.0 | 0.583 | 0.917 |

Промахи рабочей конфигурации (у всех пустой список):

```text
промах hybrid+rerank: наставниками новичков → []
промах hybrid+rerank: что делать если заболел → []
промах hybrid+rerank: сколько компенсируют на обед → []
промах hybrid+rerank: кто помогает новому человеку в первые месяцы → []
промах hybrid+rerank: сколько можно потратить на ужин с партнёрами → []
промах hybrid+rerank: нужно ли подписывать соглашение о конфиденциальности с поставщиком → []
промах hybrid+rerank: ransomware → []
ОШИБКА: hybrid+rerank хуже dense по hit@5: 0.854 < 1.0
ОШИБКА: hybrid+rerank хуже dense по mrr: 0.854 < 0.99
ОШИБКА: hybrid+rerank хуже bm25 по hit@5: 0.854 < 0.917
ОШИБКА: hybrid+rerank хуже bm25 по mrr: 0.854 < 0.91
ОШИБКА: hybrid+rerank хуже hybrid по hit@5: 0.854 < 1.0
ОШИБКА: hybrid+rerank хуже hybrid по mrr: 0.854 < 0.986
```

**Вывод: критерий этапа 4 «гибрид с реранкером не хуже остальных» не выполнен** при пороге 0,2 из SPEC.

Диагностика, продукт не менялся. Прогон с `APP_RAG__SEARCH__RERANK__SCORE_THRESHOLD=0`: `hybrid+rerank`
hit@5 1.0, MRR 1.0, ни одной строки «ОШИБКА», это лучший результат среди конфигураций, `--check` проходит.
Влияние порога посчитано по баллам одного прогона с порогом 0 (при 0,2 расчёт совпал с настоящим
прогоном):

| Порог | hit@5 | MRR | Пустых ответов из 48 |
| --- | --- | --- | --- |
| 0 – 0,01 | 1.000 | 1.000 | 0 |
| 0,02 – 0,05 | 0.958 | 0.958 | 2 |
| 0,1 | 0.917 | 0.917 | 4 |
| 0,15 | 0.875 | 0.875 | 6 |
| 0,2 | 0.854 | 0.854 | 7 |

Самые низкие баллы верного документа: 0,0114 («ужин с партнёрами»), 0,0192 («заболел»), 0,0594, 0,0714,
0,1133 («ransomware»), 0,1468, 0,1963.

## 5. Замечания сверх списка

- **Сбой воркера не виден пользователю.** Вложение навсегда остаётся «читаю…» (`parse_status=pending`),
  документ «в очереди», импорт `scanning`, ни статуса `error`, ни инцидента. У очереди `files` нет возврата
  при старте, как `kb.requeue` у `kb`: после устранения сбоя зависшие файлы остаются (`report.docx`,
  `memo.pdf` из прогона без обхода так и остались `pending`), а документы базы подхватились сами.
- **`worker check` стоит дополнить** проверкой `Base.metadata.sorted_tables`: она поймала бы дефект 1.
- **У `worker` и `worker-kb` нет healthcheck**, `make dev-ps` и `--wait` не показывают их состояние.
- **Таймаут реранкера:** `rerank.timeout_s: 3` по SPEC, а запрос на CPU занимает ~5,4 с. Вероятно, в чате
  с настоящим реранкером на CPU поиск будет деградировать до RRF (не проверялось). В eval таймаут 120 с.
- **Eval быстрее обещанного:** 5:17 против «10–20 минут» в инструкции.
- **Расхождение документов:** `eval/README.md` говорит о 8 ГБ, инструкция о 12 ГБ, нужно ~22 ГБ.
- **Интеграция Docker Desktop** не включилась для дистрибутива по умолчанию сама, понадобилась настройка.
- **`compose start <сервис>` запускает и зависимости:** остановленный вручную `worker` может вернуться.
- **В `origin` нет `main`:** единственная ветка `claude/charming-ride-5jb5sd`, она же `HEAD`.
- **Предупреждения:** `Api key is used with an insecure connection` от клиента Qdrant,
  `Failed to persist telemetry device ID` от onnxruntime в `worker check`. На результат не влияют.
- **5 пропусков pytest** ожидаемы: тесты требуют LibreOffice или Tesseract на хосте, их нет вне образа
  воркера. Внутри образа эти тесты не запускались, проверен только `worker check`.
- **Демо этапов 3–5** целиком не проходилось, проверены только пункты этой инструкции.
