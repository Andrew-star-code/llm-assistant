# Протокол SSE стриминга ответа

> Версия протокола: **1** (черновик). Реализация — этап 2: `backend/app/modules/completions/streaming.py`
> и `frontend/src/api/sse.ts`. Меняется только вместе с этим документом и тестами обеих сторон (§8.5).

Эндпоинт: `GET /api/messages/{id}/stream`, `Content-Type: text/event-stream`.

- У каждого события есть порядковый `id` — клиент переподключается с заголовком `Last-Event-ID`
  и получает только пропущенное.
- Каждые 15 секунд — heartbeat (комментарий `: ping`).
- Поток хранится в Redis Stream `gen:{message_id}` ещё 10 минут после завершения; позже состояние
  сообщения читается из БД.
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

Для разработки: fake-llm отдаёт размышления полем `reasoning` (как vLLM с `--reasoning-parser`;
в старых версиях vLLM — `reasoning_content`, переключатель `FAKE_LLM_REASONING_FIELD`). Клиент LLM на
этапе 2 должен понимать оба имени.
