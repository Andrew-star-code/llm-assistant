# modules/tools

> Статус: каркас. Реализация — §9, этап 3.

**Назначение:** Фреймворк инструментов (`Tool`, `ToolContext`, `ToolResult`), реестр `@register_tool`, встроенные инструменты в `builtin/`.

**Публичный интерфейс:** `ToolRegistry`, `run_tool(...)`.

**Зависит от:** `files`, `rag`, `incidents`, data-gateway, ★ sandbox-runner.

**Точки расширения:** Новый инструмент — `docs/guides/add-tool.md` (§9.8).

**Данные:** `tool_calls` (через completions).

**Тесты:** `backend/tests/unit/tools/`, `backend/tests/integration/tools/`; запуск — `make test`.
