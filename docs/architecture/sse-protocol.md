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

| Событие | Данные | Когда |
| --- | --- | --- |
| `message.start` | `message_id`, `chat_id`, `parent_id`, `model`, `thinking`, `protocol_version` | начало генерации |
| `reasoning.delta` | `text` | очередной кусок размышлений |
| `content.delta` | `text` | очередной кусок ответа |
| `tool.start` | `call_id`, `tool`, `label` | начат видимый инструмент |
| `tool.end` | `call_id`, `status`, `label` | закончен видимый инструмент |
| `sources` | карточки источников | после шагов RAG |
| `file` | `file_id`, `name`, `mime`, `size`, `preview` | создан файл |
| `usage` | `prompt_tokens`, `completion_tokens`, `reasoning_tokens` | в конце |
| `limits` | остатки по метрикам пользователя | в конце |
| `title` | `chat_id`, `title` | сгенерирован заголовок |
| `error` | `code`, `message`, `retryable` | ошибка |
| `message.end` | `status` (`completed`, `stopped`, `error`, `interrupted`), `finish_reason` | конец |

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
