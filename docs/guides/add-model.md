# Как сменить или добавить модель

Код обращается к моделям по **ролям** (§3.1, §8.2): `chat`, `coder`, `utility`, `guard`, `embed`,
`rerank`. Смена модели — правка конфигурации, а не кода.

## Сменить модель роли

1. Поднимите модель в vLLM (`deploy/models/…`, этап 10) с парсерами `--reasoning-parser` и
   `--tool-call-parser` под её семейство.
2. Поправьте роль в `config/models.yaml` (прод) или `config/models.dev.yaml` (дев-стенд):

   ```yaml
   models:
     chat:
       base_url: http://llm-chat:8000/v1
       model: Qwen/Qwen3.8-27B
       context_length: 131072        # сколько реально отдаём, а не максимум модели
       max_output_tokens: 16384      # резерв на ответ в бюджете контекста
       tokenizer: /models/chat/tokenizer.json   # для точного подсчёта токенов
       thinking: {mode: chat_template_kwarg, kwarg: enable_thinking, default: false}
       sampling:                     # из карточки модели
         thinking: {temperature: 1.0, top_p: 0.95, top_k: 20}
         default: {temperature: 0.7, top_p: 0.8, top_k: 20}
   ```

3. Проверьте конфиг и модель:

   ```bash
   docker compose exec api python -m app.cli config check
   ```

4. Прогоните `eval/scenarios` (с этапа 5) и сравните с прошлым прогоном; запишите решение в
   `docs/runbooks/models.md` (этап 10).

## Режим thinking

| `thinking.mode` | Что уходит в запрос |
| --- | --- |
| `chat_template_kwarg` | `chat_template_kwargs: {<kwarg>: true\|false}` (Qwen3.x) |
| `reasoning_effort` | `reasoning_effort: <effort>` при включённом thinking |
| `separate_model` | запросы с thinking — на роль `thinking.model_role` |
| `none` | переключатель «Размышлять» скрыт |

Размышления приходят отдельным полем дельты (`reasoning` или `reasoning_content` — оба понимаются).

## Локально без GPU

Любой OpenAI-совместимый сервер (Ollama, llama.cpp) — через `deploy/compose/api.local.env`
(см. README). Для детерминированных тестов — fake-llm (`services/fake-llm`).

## Реранкер: vLLM или text-embeddings-inference

Клиент реранкера понимает два формата — поле `api` у роли `rerank`:

| `api` | Сервер | Запрос |
| --- | --- | --- |
| `openai` (по умолчанию) | vLLM, Jina-совместимые | `POST {base_url}/rerank` (`base_url` с `/v1`): `documents` → `results[].relevance_score` |
| `tei` | text-embeddings-inference | `POST /rerank` (`/v1` в `base_url` отбрасывается): `texts` → `[{index, score}]`, пакетами по 32 |

Оба дают балл 0..1, порог `rag.search.rerank.score_threshold` к ним одинаково применим. На дев-стенде
настоящий реранкер поднимает `make dev-models-up` (TEI на CPU, профиль `models`), подключение — через
`deploy/compose/api.local.env` (образец — `api.local.env.example`):

```dotenv
APP_MODELS__RERANK__BASE_URL=http://rerank:80
APP_MODELS__RERANK__MODEL=BAAI/bge-reranker-v2-m3
APP_MODELS__RERANK__API=tei
```

На GPU (в том числе в WSL2): образ TEI нужен под архитектуру видеокарты — тег по таблице «Docker
Images» в README text-embeddings-inference (RTX 50xx — сборка для compute capability 12.0), в сервис
добавить `gpus: all`, digest закрепить по правилам репозитория. Модели те же — меняется только
скорость.

