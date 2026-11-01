# modules/memory

> Статус: каркас. Реализация — §11.2, этап 12 ★.

**Назначение:** ★ Память: извлечение фактов из прошлых чатов, инструменты `remember` и `search_past_chats`.

**Публичный интерфейс:** `/api/memory/*`.

**Зависит от:** `llm` (utility, embed); Qdrant.

**Точки расширения:** —

**Данные:** `memories`; коллекция `memories`.

**Тесты:** `backend/tests/unit/memory/`, `backend/tests/integration/memory/`; запуск — `make test`.
