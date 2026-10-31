# modules/exports

> Статус: каркас. Реализация — §13.3, этап 6.

**Назначение:** Фоновые выгрузки чатов: JSON, XLSX, DOCX, PDF; файл хранится 7 дней и доступен только заказавшему.

**Публичный интерфейс:** `POST /api/admin/exports`, `GET /api/admin/exports/{id}`.

**Зависит от:** `chats`, `files`, `audit`.

**Точки расширения:** Новый формат — экспортер в `exports/formats/`.

**Данные:** `exports`.

**Тесты:** `backend/tests/unit/exports/`, `backend/tests/integration/exports/`; запуск — `make test`.
