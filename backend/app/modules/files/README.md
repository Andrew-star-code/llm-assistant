# modules/files

> Статус: каркас. Реализация — §7.3, §7.7, §9.3–9.4, этап 3.

**Назначение:** Загрузки (проверки сигнатуры, размера, распаковки), сгенерированные файлы, превью; интерфейс `Storage`.

**Публичный интерфейс:** `POST /api/files`, `GET /api/files/{id}`, `/download`, `/preview`.

**Зависит от:** `ingestion`; storage.

**Точки расширения:** S3 — новая реализация `Storage` (FUTURE).

**Данные:** `files`.

**Тесты:** `backend/tests/unit/files/`, `backend/tests/integration/files/`; запуск — `make test`.
