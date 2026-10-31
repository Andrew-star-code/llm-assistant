# modules/rag

> Статус: каркас. Реализация — §10, этап 4.

**Назначение:** Базы знаний трёх уровней, гибридный поиск BM25 + dense с RRF и реранкером, цитаты, проверка прав серверным фильтром.

**Публичный интерфейс:** `/api/kb/*`, `search(...)` для оркестратора и инструмента `search_knowledge_base`.

**Зависит от:** `rbac`, `llm` (embed, rerank, utility); Qdrant.

**Точки расширения:** Параметры поиска — `rag.search` в конфиге; менять по `eval/rag`.

**Данные:** `knowledge_bases`, `kb_roles`, `kb_documents`.

**Тесты:** `backend/tests/unit/rag/`, `backend/tests/integration/rag/`; запуск — `make test`.
