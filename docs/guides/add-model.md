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
