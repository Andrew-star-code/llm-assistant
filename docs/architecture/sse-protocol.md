# Протокол SSE стриминга ответа

> Версия протокола: **1**. Реализация: `backend/app/modules/completions/streaming.py` и
> `frontend/src/api/sse.ts`. Меняется только вместе с этим документом и тестами обеих сторон (§8.5):
> `backend/tests/integration/test_chat.py`, `frontend/tests/unit/chat.test.tsx`.

Эндпоинт: `GET /api/messages/{id}/stream`, `Content-Type: text/event-stream`.

- У каждого события есть порядковый `id` (1, 2, 3, …; в Redis — `0-<id>`) — клиент
  переподключается с заголовком `Last-Event-ID` (или `?after=<id>`) и получает только пропущенное.
- Дельты `reasoning.delta` и `content.delta` склеиваются пачками не реже раза в 50 мс.
- Каждые 15 секунд — heartbeat (комментарий `: ping`).
- Поток хранится в Redis Stream `gen:{message_id}` ещё 10 минут после завершения
  (`chat.stream_ttl_seconds`). Если потока уже нет, сервер сразу отдаёт `message.end` с финальным
  статусом, а клиент перечитывает сообщение по REST — после `message.end` он делает это всегда.
- Если ответ всё ещё `streaming`, а исполнитель не продлевает `gen:alive:{message_id}`, сервер отдаёт
  `error` с кодом `interrupted` и `message.end` со статусом `interrupted`.
- Скрытые инструменты (например, `report_incident`) событий не порождают.
- Шаги инструментов, файлы и источники ответа после завершения доступны и по REST: поля `tools`,
  `files` и `sources` (с признаком `cited` — модель сослалась на номер)
  сообщения в `GET /api/chats/{id}` — интерфейс строит из них ту же ленту после перезагрузки.
- Авто-поиск по базам знаний (режим `auto`) показывается как шаг `search_knowledge_base` с
  `call_id: rag-auto` (`tool.start` / `tool.end`, `params.query` — переформулированный запрос).

| Событие | Данные | Когда |
| --- | --- | --- |
| `message.start` | `message_id`, `chat_id`, `parent_id`, `model`, `thinking`, `protocol_version` | начало генерации |
| `reasoning.delta` | `text` | очередной кусок размышлений |
| `content.delta` | `text` | очередной кусок ответа |
| `tool.start` | `call_id`, `tool`, `label` (i18n-ключ строки статуса, например `tools.read_document`), `params` (параметры строки, например `{"name": "Отчёт.docx"}`) | начат видимый инструмент |
| `tool.end` | `call_id`, `tool`, `status` (`ok`, `error`, `timeout`), `label`, `params` | закончен видимый инструмент |
| `sources` | `items`: **полный** текущий список карточек — `index` (номер для `[n]`), `kind` (`kb` / `attachment`), `title`, `kb_name`, `document_id`, `file_id`, `page`, `section`, `snippet`, `score`; клиент заменяет список, а не дописывает | после авто-поиска RAG и после каждого инструмента, нашедшего фрагменты |
| `file` | `file_id`, `name`, `mime`, `size`, `preview` (есть PDF-превью) | создан файл (после `tool.end` его инструмента) |
| `usage` | `prompt_tokens`, `completion_tokens`, `reasoning_tokens` | в конце |
| `limits` | `timezone`, `items` (метрика, окно, роль модели, thinking, `limit`, `used`, `remaining`, `reset_at`), `nearest` — ближайшая к исчерпанию, `blocked` — исчерпан лимит на все сообщения; то же, что `GET /api/limits` | в конце, после `usage` |
| `title` | `chat_id`, `title` | сгенерирован заголовок |
| `error` | `code`, `message`, `retryable` | ошибка |
| `message.end` | `status` (`completed`, `stopped`, `error`, `interrupted`), `finish_reason` (`stop`, `length`, `max_iterations` — модель не уложилась в `tools.max_iterations`, …) | конец |

Пример:

```text
id: 1
event: message.start
data: {"message_id":"…","chat_id":"…","parent_id":"…","model":"chat","thinking":false,"protocol_version":1}

id: 2
event: content.delta
data: {"text":"Добрый день, Иван Петрович!"}

id: 3
event: message.end
data: {"status":"completed","finish_reason":"stop"}
```

Коды ошибок (`error.code`): `model_http_<status>`, `model_timeout`, `model_unavailable`,
`internal_error`, `interrupted`. `retryable: true` — интерфейс показывает «Повторить» (перегенерация).

Модель отдаёт размышления полем `reasoning` (vLLM с `--reasoning-parser`) или `reasoning_content`
(старые версии vLLM) — `modules/llm/stream.py` понимает оба; fake-llm переключается
`FAKE_LLM_REASONING_FIELD`.
