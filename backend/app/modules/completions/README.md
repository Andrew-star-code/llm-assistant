# modules/completions

> Статус: оркестратор без инструментов — этап 2 (§8); инструменты — этап 3, RAG — этап 4.

**Назначение:** генерация ответа: сборка промпта, бюджет контекста, вызов модели со стримингом,
события в Redis Stream, сохранение ответа и трассировки, «Стоп», перегенерация, автозаголовок.

**Как проходит сообщение (§2.2):**

1. `POST /api/chats/{id}/messages` сохраняет вопрос и пустой ответ `streaming`, ставит ключ живости
   `gen:alive:<id>`, запускает `GenerationManager` фоновой задачей и сразу отвечает `202`.
2. `generation.py`: промпт (`prompt.py`: `config/prompts/system/*` + история активной ветки в бюджете)
   → `AsyncOpenAI` со `stream=True` → дельты в `gen:<id>` пачками раз в 50 мс (`streaming.EventWriter`).
3. Браузер читает `GET /api/messages/{id}/stream` (SSE) с `Last-Event-ID`; протокол —
   [sse-protocol.md](../../../../docs/architecture/sse-protocol.md).
4. В конце — ответ, токены (из `usage` модели или подсчётом), `ttft_ms`, `latency_ms`, трассировка в
   `messages`; заголовок чата служебной моделью; события `usage`, `title`, `message.end`.

**Отмена и сбои:** «Стоп» — флаг `gen:cancel:<id>` (видит любой процесс api), частичный ответ
сохраняется со статусом `stopped`. Остановка процесса — `interrupted`; «осиротевшие» ответы без живого
исполнителя помечаются при старте (`mark_orphaned_interrupted`) и SSE-читателем.

**Публичный интерфейс:** `POST /api/chats/{id}/messages`, `POST /api/messages/{id}/regenerate`,
`POST /api/messages/{id}/stop`, `GET /api/messages/{id}/stream`, `GET /api/models/chat`
(доступен ли «Размышлять»).

**Зависит от:** `chats`, `llm`, `users` (форма обращения); Redis; модели `chat` и `utility`.

**Точки расширения:** формат стрима — `docs/architecture/sse-protocol.md` → `streaming.py` →
`frontend/src/api/sse.ts` (версия протокола, тесты обеих сторон); промпты — `config/prompts/`.
TODO(stage-3): цикл инструментов; TODO(stage-4): RAG; TODO(stage-8): лимиты.

**Данные:** пишет `messages`; Redis `gen:<id>` (живёт `chat.stream_ttl_seconds` после конца),
`gen:alive:<id>`, `gen:cancel:<id>`.

**Тесты:** `backend/tests/unit/test_chat_units.py`, `backend/tests/integration/test_chat.py`
(стрим, переподключение, стоп, перегенерация, ошибки, thinking, interrupted).
