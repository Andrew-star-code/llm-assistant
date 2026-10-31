# modules/chats

> Статус: каркас. Реализация — §7.2, §8.6, этап 2.

**Назначение:** Чаты, папки, сообщения деревом (`parent_id`, `active_leaf_id`), закрепление, мягкое удаление, поиск.

**Публичный интерфейс:** `/api/chats/*`, `/api/folders/*`, `/api/search`.

**Зависит от:** `users`.

**Точки расширения:** —

**Данные:** `chats`, `folders`, `messages`, `message_sources`, `tool_calls`.

**Тесты:** `backend/tests/unit/chats/`, `backend/tests/integration/chats/`; запуск — `make test`.
