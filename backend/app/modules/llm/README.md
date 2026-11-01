# modules/llm

> Статус: реализовано на этапе 2 (§8.2, §8.3).

**Назначение:** доступ к моделям по ролям (`chat`, `coder`, `utility`, `guard`, `embed`, `rerank`)
из `config/models.yaml` — код не знает имён моделей.

**Публичный интерфейс:**

* `registry.ModelRegistry` — `get(role)`, `client(role)` (кэшируемый `AsyncOpenAI`),
  `thinking_available(role)`, `plan(role, thinking=…)` → параметры запроса с учётом режима thinking
  и сэмплинга: `chat_template_kwarg` → `extra_body.chat_template_kwargs`, `reasoning_effort`,
  `separate_model` → другая роль, `none`. Расширения vLLM (`top_k`, `min_p`, …) — в `extra_body`.
* `tokens.TokenCounter` — токенизатор модели (`models.<роль>.tokenizer`, локальный tokenizer.json);
  без него — оценка по длине текста.
* `stream.parse_stream` — дельты размышлений (`reasoning` и `reasoning_content`), ответа, `usage`,
  `finish_reason`.

**Зависит от:** OpenAI-совместимые эндпоинты (vLLM в проде, fake-llm в разработке).

**Точки расширения:** новая модель или роль — [add-model.md](../../../../docs/guides/add-model.md).

**Данные:** нет.

**Тесты:** `backend/tests/unit/test_chat_units.py` (режимы thinking, разбор стрима, бюджет).
