# modules/llm

> Статус: каркас. Реализация — §8.2, этап 2.

**Назначение:** Реестр моделей по ролям (`config/models.yaml`), клиент AsyncOpenAI, режимы thinking, токенизация для бюджета контекста.

**Публичный интерфейс:** `ModelRegistry.get(role)`, `LLMClient.stream(...)`, `count_tokens(...)`.

**Зависит от:** vLLM / fake-llm (OpenAI-совместимый API).

**Точки расширения:** Новая модель — `config/models.yaml` + `docs/runbooks/models.md`.

**Данные:** —

**Тесты:** `backend/tests/unit/llm/`, `backend/tests/integration/llm/`; запуск — `make test`.
