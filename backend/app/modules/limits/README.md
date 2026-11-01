# modules/limits

> Статус: каркас. Реализация — §12, этап 8.

**Назначение:** Лимиты: метрики, политики (глобальные, ролевые, персональные), атомарные счётчики в Redis (Lua), учёт в `usage_records`.

**Публичный интерфейс:** `check_and_reserve(...)`, `commit_usage(...)`; `GET /api/limits`.

**Зависит от:** `rbac`; Redis.

**Точки расширения:** Новая метрика — `docs/guides/add-limit-metric.md`.

**Данные:** `limit_policies`, `usage_records`.

**Тесты:** `backend/tests/unit/limits/`, `backend/tests/integration/limits/`; запуск — `make test`.
