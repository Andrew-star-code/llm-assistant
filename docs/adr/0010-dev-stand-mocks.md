# 0010. Дев-стенд без GPU и AD: fake-llm, Samba AD DC, bge-m3 на CPU, uv workspace

- Статус: принято
- Дата: 2026-10-31

## Контекст

До приезда сервера нет GPU и доступа к AD (§1, §16.1). Нужен стенд, который поднимается одной
командой, и детерминированные тесты.

## Решение

- **fake-llm** (`services/fake-llm`) — свой OpenAI-совместимый mock в формате vLLM: сценарии выбираются
  маркером `[[scenario:…]]`. Обслуживает роли `chat`, `coder`, `utility`, `guard`, `rerank` в
  `config/models.dev.yaml`. Совместимость проверяется тестами на официальном SDK `openai`.
- **mock-AD** (`deploy/mock-ad`) — Samba AD DC на Ubuntu 24.04 с тестовыми пользователями и своим CA для
  LDAPS. Контейнеру нужен `cap_add: SYS_ADMIN`: Samba записывает NT ACL в xattr `security.*`.
  Только для дев-стенда.
- **embed** — bge-m3 на CPU через
  [text-embeddings-inference](https://github.com/huggingface/text-embeddings-inference) (CPU-образ):
  OpenAI-совместимый `/v1/embeddings`, та же модель, что в проде. vLLM на CPU тяжелее в сборке и
  медленнее на эмбеддингах.
- **Python — uv workspace** в корне: один `uv.lock` на `backend` и `services/*`, общие dev-инструменты.
  Docker-образы ставят только свой пакет (`uv sync --package …`).
- Конфиг — слоями `app.yaml` + `app.<env>.yaml`, `models.yaml` + `models.<env>.yaml`: дев-оверлей меняет
  только адреса, остальное наследуется из прод-конфига.

## Альтернативы

- Ollama/llama.cpp с маленькой моделью вместо fake-llm: недетерминированно для тестов; остаётся для
  ручной проверки (достаточно поменять `base_url`).
- OpenLDAP вместо Samba: нет `objectGUID`, `userAccountControl`, правила вложенных групп
  `1.2.840.113556.1.4.1941` — проверка была бы нечестной.
- Отдельные lock-файлы на каждый Python-сервис: дублирование dev-зависимостей и версий.

## Последствия

Первый `make dev-up` скачивает веса bge-m3 (~2,3 ГБ) в том `embed-cache`. Когда появится сервер,
прод-оверлей указывает на vLLM; код не меняется.
