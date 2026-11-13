# modules/completions

> Статус: оркестратор — этап 2 (§8); вложения и цикл инструментов — этап 3; RAG — этап 4.

**Назначение:** генерация ответа: сборка промпта, бюджет контекста, вызов модели со стримингом,
события в Redis Stream, сохранение ответа и трассировки, «Стоп», перегенерация, автозаголовок.

**Как проходит сообщение (§2.2):**

1. `POST /api/chats/{id}/messages` сохраняет вопрос и пустой ответ `streaming`, ставит ключ живости
   `gen:alive:<id>`, передаёт ответ `GenerationManager.start` и сразу отвечает `202`.
   `generation.mode: queue` (прод и дев-стенд, [ADR-0013](../../../../docs/adr/0013-generation-executor.md)):
   `start` кладёт задание в список Redis `gen:queue`, его забирает сервис `generator`
   (`executor.py`, `python -m app.cli generator run`) и запускает задачу у себя. `inline`
   (тесты): задача в процессе api.
2. Задача `GenerationManager._run` (`generation.py`) проходит шаги: промпт (`prompt.py`: `config/prompts/system/*` + история активной ветки в бюджете)
   + вложения ветки (`attachments.py`: целиком, если влезают в `files.full_text_budget_share` бюджета,
   иначе оглавление и начало) → `AsyncOpenAI` со `stream=True` и инструментами → дельты в `gen:<id>`
   пачками раз в 50 мс (`streaming.EventWriter`).
   Цикл инструментов (§8.4): вызовы одной итерации — параллельно (`tools.executor`), события
   `tool.start`/`tool.end`/`file`, результаты — сообщениями `tool`, снова запрос; не больше
   `tools.max_iterations`, иначе честная пометка в ответе и `finish_reason: max_iterations`.
   Бюджет контекста в цикле держит `context.LoopContext`: перед каждым повторным запросом —
   старая история → результаты прошлых итераций → обрезка свежих результатов; в трассировке —
   `context` (`budget`, `peak_tokens`, сколько убрано и обрезано). История содержит и прошлые
   вызовы инструментов (`prompt.Turn.steps` из `tool_calls`, кроме скрытых и авто-поиска).
3. Браузер читает `GET /api/messages/{id}/stream` (SSE) с `Last-Event-ID`; протокол —
   [sse-protocol.md](../../../../docs/architecture/sse-protocol.md).
4. В конце — ответ, токены (из `usage` модели или подсчётом), `ttft_ms`, `latency_ms`, трассировка в
   `messages`; заголовок чата служебной моделью; события `usage`, `title`, `message.end`.

**Модули:**

| Файл | Что в нём |
| --- | --- |
| `generation.py` | `GenerationManager`: запуск и остановка задач, осиротевшие ответы, `_run` — порядок шагов и обработка исходов |
| `state.py` | `Deps` (зависимости шагов), `GenerationResult`, коды ошибок |
| `preparation.py` | `prepare` → `Prepared`: одна сессия БД — ветка, сценарий, модель, системный промпт, вложения, область поиска, инструменты, история с прошлыми вызовами |
| `retrieval.py` | авто-поиск по базам знаний (`auto_rag`), карточки источников |
| `prompt.py`, `context.py`, `attachments.py` | сборка промпта, бюджет контекста в цикле, вложения в промпте |
| `toolloop.py` | запрос к модели со стримингом, автоповтор, цикл инструментов |
| `finish.py` | сохранение ответа, учёт токенов и лимиты, заголовок, метрики, `message.end` |
| `streaming.py`, `executor.py`, `health.py` | протокол событий; исполнитель очереди; проверка исполнителя |
| `router.py` | HTTP: отправка, перегенерация, «Стоп», SSE |

**Малый контекст.** `preparation.prepare` считает остаток бюджета после инструкций, описаний
инструментов и вопроса и ужимает под него блок вложений (`attachments.fit_attachments`: ступени
от «короче начало документа» до «только имена файлов»); авто-поиск получает остаток после
вложений (`Prepared.rag_budget`) или пропускается (`rag.skipped: no_room` в трассировке, у модели
остаётся инструмент поиска). В трассировке — `attachments.shrunk`. Ответ с `finish_reason: length`
получает пометку `generation.LENGTH_NOTE`.

**Автоповтор:** краткий сбой модели (соединение, 429, 5xx, обрыв стрима) до первой дельты запроса
повторяется `chat.model_retries` раз с паузой `chat.model_retry_backoff_seconds` × 2ⁿ — в любой
итерации цикла инструментов, так что работа прошлых шагов не пропадает; в трассировке —
`model_retries`. Тайм-аут и ошибки 4xx не повторяются.

**Отмена и сбои:** «Стоп» — флаг `gen:cancel:<id>` (видит любой процесс), частичный ответ
сохраняется со статусом `stopped`. «Осиротевшие» ответы без живого исполнителя помечает api при
старте и раз в 30 с (`mark_orphaned_interrupted`) и SSE-читатель.

**Исполнитель (`executor.py`):** задание берётся из очереди один раз и только пока жив его ключ
живости (api ставит его на `generation.queue_ttl_seconds`; просроченное уже прервано). Не больше
`generation.max_concurrent` ответов сразу — остальные ждут в очереди. По SIGTERM исполнитель не
берёт новые задания и дорабатывает идущие до `generation.shutdown_grace_seconds`, остальные
сохраняет как `interrupted`. Перезапуск api ответы не трогает. Отметка `gen:executor:<имя>` —
для healthcheck (`generator check`). Слот лимита одновременных генераций без продления живёт
`limits.slot_ttl_s`: задание, ждущее в очереди дольше, слот уже не держит.

**Публичный интерфейс:** `POST /api/chats/{id}/messages`, `POST /api/messages/{id}/regenerate`,
`POST /api/messages/{id}/stop`, `GET /api/messages/{id}/stream`, `GET /api/models/chat`
(доступен ли «Размышлять»).

**Зависит от:** `chats`, `llm`, `users` (форма обращения), `files`, `tools`, `rbac` (права для
набора инструментов); Redis; модели `chat` и `utility`.

**Точки расширения:** формат стрима — `docs/architecture/sse-protocol.md` → `streaming.py` →
`frontend/src/api/sse.ts` (версия протокола, тесты обеих сторон); промпты — `config/prompts/`.
Лимиты (этап 8): резерв до запроса в `router.py` (`limits.reserve_generation`, отказ — 429), слот генерации продлевается и освобождается в `generation.py`, фактические токены — `usage_records` и счётчики после ответа, событие `limits` в конце.

**Метрики и здоровье:** `core/metrics.py` — ответы, TTFT, токены, инструменты, ожидание в очереди
(пишет процесс, который ведёт ответ: `generator`, порт `generation.metrics_port`); api отдаёт длину
очереди, число исполнителей и открытые SSE. `health.py` — проверка «есть ли исполнитель» раз в
минуту из `scheduler`: инцидент `generator_health` и комментарий о восстановлении. Перечень метрик
и алерты — [deploy/monitoring](../../../../deploy/monitoring/README.md).

**Данные:** пишет `messages`; Redis `gen:queue` (задания), `gen:executor:<имя>`, `gen:<id>` (живёт `chat.stream_ttl_seconds` после конца),
`gen:alive:<id>`, `gen:cancel:<id>`.

**Тесты:** `backend/tests/unit/test_chat_units.py` (в том числе бюджет цикла инструментов),
`backend/tests/integration/test_chat.py` (стрим, переподключение, стоп, перегенерация, ошибки,
thinking, interrupted), `backend/tests/integration/test_files.py` (история инструментов, обрезка
результатов под контекст), `backend/tests/integration/test_generator.py` (очередь, просроченное
задание, «Стоп» в очереди, остановка с доработкой, предел параллельности, настоящий процесс).
