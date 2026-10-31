# modules/scenarios

> Статус: каркас. Реализация — §8.7, этап 5.

**Назначение:** Корпоративные сценарии: промпт, модель, инструменты, базы знаний, режим RAG, роли; seed из `config/scenarios/`.

**Публичный интерфейс:** `GET /api/scenarios`; админ-CRUD.

**Зависит от:** `rbac`, `tools`, `rag`.

**Точки расширения:** Новый сценарий — `docs/guides/add-scenario.md`.

**Данные:** `scenarios`.

**Тесты:** `backend/tests/unit/scenarios/`, `backend/tests/integration/scenarios/`; запуск — `make test`.
