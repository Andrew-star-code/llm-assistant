# Корпоративный ИИ-ассистент

Чат-ассистент в закрытом контуре для 200+ сотрудников (вход через AD, RAG по базам знаний,
инструменты, админ-панель) и OpenAI-совместимый API моделей для разработчиков — на одном сервере
с 4× A100 без внешних сетевых обращений.

- Требования и план — [docs/SPEC.md](docs/SPEC.md)
- Прогресс этапов и открытые вопросы — [docs/status.md](docs/status.md)
- Правила работы и карта «где править» — [AGENTS.md](AGENTS.md)
- Вся документация — [docs/README.md](docs/README.md)

## Быстрый старт (≈10 минут)

Нужны: Docker с Compose v2.23+, [uv](https://docs.astral.sh/uv/) ≥ 0.11, Node.js 22 и pnpm 10
(`corepack enable`), GNU make.

```bash
make install
```

```bash
make dev-up
```

Первый `make dev-up` собирает образы (воркер с LibreOffice и Tesseract — ~1 ГБ) и скачивает веса
bge-m3 (~2,3 ГБ), поэтому дольше обычного. Разбор вложений и создание файлов идут в сервисе `worker`
(логи — `make dev-logs S=worker`, самопроверка — `make test-worker`), индексация баз знаний и
импорт — в `worker-kb`; папка для массового импорта — `deploy/compose/import/` (`KB_IMPORT_DIR`).
Файл `deploy/compose/.env` создаётся из `.env.example` автоматически.

| Что | Адрес |
| --- | --- |
| Фронтенд (Vite, hot reload) | <http://localhost:5173> — вход кнопками dev или `ivanov` / `Passw0rd!` через mock-AD |
| API: Swagger / готовность | <http://localhost:8000/api/docs> · <http://localhost:8000/ready> |
| fake-llm (OpenAI-совместимый mock) | <http://localhost:8081/v1> |
| embed (bge-m3 на CPU) | <http://localhost:8082> |
| mock-AD (Samba AD DC) | `ldaps://localhost:636` — пользователи в [deploy/mock-ad/README.md](deploy/mock-ad/README.md) |
| Qdrant | <http://localhost:6333/dashboard> (ключ — `QDRANT_API_KEY` из `.env`) |

Перед пушем — всегда:

```bash
make check
```

Остальные команды — `make help` и [AGENTS.md](AGENTS.md#2-команды).

## Состав

| Каталог | Что внутри |
| --- | --- |
| `backend/` | API на FastAPI: `core/` (конфиг, логи, БД, health), `modules/` (бизнес-модули), `cli/`, миграции Alembic |
| `frontend/` | SPA пользователя и админки: React 19 + TypeScript + Vite |
| `services/fake-llm/` | OpenAI-совместимый mock LLM со сценариями для разработки и тестов |
| `config/` | Поведение в YAML: вход и AD, реестр моделей; дальше — промпты, сценарии, политики |
| `deploy/` | Docker Compose, mock-AD; дальше — nginx, модели vLLM, мониторинг, офлайн-бандл |
| `docs/` | SPEC, статус, архитектура, ADR, руководства, справочники, runbooks |

## Ручная проверка на живой модели

Без GPU можно подключить маленькую модель через Ollama или llama.cpp: достаточно OpenAI-совместимого
адреса (§16.1 SPEC). Создайте `deploy/compose/api.local.env` (в git не попадает) и перезапустите api:

```dotenv
APP_MODELS__CHAT__BASE_URL=http://host.docker.internal:11434/v1
APP_MODELS__CHAT__MODEL=qwen3.5:4b
```

```bash
make dev-up
```
