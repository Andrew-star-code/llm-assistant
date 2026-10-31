# services/fake-llm

Назначение: OpenAI-совместимый mock LLM для разработки без GPU и для детерминированных тестов (§16.1).
Повторяет формат vLLM: размышления отдельным полем дельты, `tool_calls` по кускам, usage последним чанком.

Публичный интерфейс:

| Эндпоинт | Что делает |
| --- | --- |
| `POST /v1/chat/completions` | Ответ по сценарию; `stream: true` — SSE-чанки как у vLLM |
| `POST /v1/embeddings` | Детерминированные нормированные векторы («мешок слов»: общие слова → близкие векторы) |
| `POST /v1/rerank`, `POST /rerank` | Реранк в формате vLLM/Jina: балл — доля слов запроса в документе |
| `GET /v1/models`, `GET /health` | Список моделей, проверка живости |

Сценарий выбирается маркером в последнем сообщении пользователя, например
`[[scenario:tool_call_search]] найди регламент отпуска`. Без маркера — `default`,
а при `chat_template_kwargs.enable_thinking: true` — `thinking`.

| Сценарий | Поведение |
| --- | --- |
| `default` | Обычный стрим: «Это ответ fake-llm на запрос: «…»» |
| `thinking` | Сначала размышления (`reasoning`), затем ответ |
| `markdown` | Формулы во всех делимитерах, таблица, блок кода — для тестов рендера |
| `tool_call_search` | Вызов `search_knowledge_base(query)`; после сообщения `tool` — финальный ответ со ссылкой `[1]` |
| `error_500` | HTTP 500 |
| `disconnect` | Часть ответа, затем обрыв соединения без `[DONE]` |
| `slow` | 40 слов с паузой `FAKE_LLM_SLOW_DELAY_S` перед каждым — для «Стоп» и перезагрузки посреди стрима |
| `title` | Короткий ответ — для автозаголовков |

Настройки (переменные окружения): `FAKE_LLM_PORT` (8080), `FAKE_LLM_SLOW_DELAY_S` (0.3),
`FAKE_LLM_REASONING_FIELD` (`reasoning` | `reasoning_content` | `both` — имя поля в разных версиях vLLM),
`FAKE_LLM_EMBED_DIM` (1024), `FAKE_LLM_MODELS` (список через запятую).

Зависит от: ничего.

Точки расширения: новый сценарий — ветка в `src/fake_llm/scenarios.py::resolve` + имя в `SCENARIO_NAMES` + тест.

Данные: нет.

Тесты: `services/fake-llm/tests/` — через официальный SDK `openai` против настоящего uvicorn;
запуск — `make test` или `uv run pytest services/fake-llm/tests`.
