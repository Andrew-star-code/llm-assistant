# modules/tools

> Статус: фреймворк и инструменты файлов — этап 3 (§9.1–9.2, §9.4, §8.4).

**Назначение:** фреймворк инструментов: `Tool` (имя, описание для модели, Pydantic-схема аргументов,
`visibility`, `status_label`, `timeout_s`, `required_permissions`, `needs_attachments`, `run`),
`ToolContext` (пользователь и права из сессии, чат, вложения, сервисы), `ToolResult`, реестр
`@register_tool`, исполнитель `executor.execute` (валидация, тайм-аут, обрезка до
`tools.result_max_chars`, ошибки — текстом модели).

**Встроенные инструменты (`builtin/`):**

| Инструмент | Что делает | Строка статуса |
| --- | --- | --- |
| `list_attachments` | Список вложений чата | `tools.list_attachments` |
| `read_document` | Страницы вложения (≤ 30 за вызов) | `tools.read_document` |
| `get_document_outline` | Оглавление, таблицы, листы | `tools.get_document_outline` |
| `read_spreadsheet` | Лист и диапазон XLSX/CSV | `tools.read_spreadsheet` |
| `search_in_documents` | Поиск по вложениям чата в Qdrant | `tools.search_in_documents` |
| `create_document` | DOCX/PDF/ODT/MD/HTML/TXT из Markdown | `tools.create_document` |
| `create_spreadsheet` | XLSX/CSV | `tools.create_spreadsheet` |
| `create_presentation` | PPTX | `tools.create_presentation` |

**Какие инструменты видит модель:** `registry.available_tools` — пересечение `tools.enabled`
(дальше — админка), списка сценария (этап 5), прав пользователя; инструменты вложений — только если в
чате есть прочитанные файлы. Файл модель указывает именем или id, но выбирает только из вложений
текущего чата (`ToolContext.attachments` строит сервер).

**Цикл (§8.4)** — в `completions/generation.py`: вызовы одной итерации выполняются параллельно,
не больше `tools.max_iterations` итераций; события `tool.start` / `tool.end` / `file` — только для
`visibility = visible`.

**Зависит от:** `files`, `ingestion` (поиск), `workers` (генерация); дальше `rag`, `incidents`,
data-gateway.

**Точки расширения:** новый инструмент — [docs/guides/add-tool.md](../../../../docs/guides/add-tool.md).

**Данные:** `tool_calls` (аргументы, превью результата, статус, длительность, шаг, строка статуса).

**Тесты:** `backend/tests/unit/test_tools.py`, `backend/tests/integration/test_files.py`.
