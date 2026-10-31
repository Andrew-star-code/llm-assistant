# modules/feedback

> Статус: каркас. Реализация — §7.4, этап 2.

**Назначение:** Лайки и дизлайки ответов с причинами и комментарием.

**Публичный интерфейс:** `PUT /api/messages/{id}/feedback`.

**Зависит от:** `chats`.

**Точки расширения:** —

**Данные:** `feedback`.

**Тесты:** `backend/tests/unit/feedback/`, `backend/tests/integration/feedback/`; запуск — `make test`.
