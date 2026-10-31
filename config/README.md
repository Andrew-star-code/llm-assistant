# config/

Поведение системы в YAML. Секретов здесь нет — они в `.env` и `/run/secrets` (§15).

| Файл / каталог | Что задаёт | Этап |
| --- | --- | --- |
| `app.yaml` | Вход, AD, сессии, логи | 0–1 |
| `app.<env>.yaml` | Оверлей окружения (`dev`, `test`, `prod`), сливается поверх `app.yaml` | 0 |
| `models.yaml` | Реестр моделей по ролям (§8.2) | 0 |
| `models.<env>.yaml` | Оверлей реестра; в `dev` — fake-llm и bge-m3 на CPU | 0 |
| `prompts/` | Jinja2-шаблоны промптов: `system/`, `scenarios/`, `utility/` | 2 |
| `scenarios/` | Встроенные сценарии (seed) | 5 |
| `moderation/policy.yaml` | Категории скрытого репорта | 7 |
| `templates/` | `reference.docx`, `presentation.pptx` | 3 |

Порядок слияния: `app.yaml` → `app.<env>.yaml` → `models.yaml` → `models.<env>.yaml` →
файлы секретов → переменные окружения `APP_*` (вложенность через `__`, например
`APP_LOGGING__LEVEL=DEBUG`). Конфиг проверяется при старте и командой
`uv run python -m app.cli config check`. Полный справочник — `docs/reference/config.md`.
