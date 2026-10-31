# modules/ingestion

> Статус: каркас. Реализация — §9.3, §10.3, этапы 3–4.

**Назначение:** Парсинг документов (docling, MarkItDown, LibreOffice, OCR), чанкинг, пайплайн индексации в Qdrant.

**Публичный интерфейс:** Задачи Celery `parse_file`, `index_document`; CLI `kb import`.

**Зависит от:** `files`, `rag`, `llm` (embed); Qdrant.

**Точки расширения:** Новый формат — парсер в `ingestion/parsers/`.

**Данные:** Коллекции `kb_chunks`, `personal_chunks`, `attachment_chunks`.

**Тесты:** `backend/tests/unit/ingestion/`, `backend/tests/integration/ingestion/`; запуск — `make test`.
