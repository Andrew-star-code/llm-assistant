# modules/completions

> Статус: каркас. Реализация — §8, этап 2.

**Назначение:** Оркестратор: сборка промпта, RAG по режиму, вызов LLM со стримингом, цикл инструментов, публикация событий SSE через Redis Streams, отмена.

**Публичный интерфейс:** `POST /api/chats/{id}/messages`, `GET /api/messages/{id}/stream` (SSE), `POST /api/messages/{id}/stop`.

**Зависит от:** `llm`, `tools`, `rag`, `chats`, `limits`, `scenarios`; Redis.

**Точки расширения:** Формат стрима — `docs/architecture/sse-protocol.md` → `streaming.py` → `frontend/src/api/sse.ts`.

**Данные:** Пишет `messages`, `tool_calls`, `message_sources`; Redis Stream `gen:{message_id}`.

**Тесты:** `backend/tests/unit/completions/`, `backend/tests/integration/completions/`; запуск — `make test`.
