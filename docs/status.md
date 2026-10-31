# Статус проекта

Обновляется после каждой задачи (§17.1, §20). Этапы и критерии приёмки — [SPEC §19](SPEC.md#19-план-этапов-с-критериями-приёмки).

## Этапы

| Этап | Статус |
| --- | --- |
| 0. Каркас и инструменты | ✅ код готов, ждёт проверки человеком (см. ниже) |
| 1. Вход, пользователи, роли, каркас админки | ⏳ следующий |
| 2. Ядро чата | — |
| 3. Файлы и инструменты | — |
| 4. RAG | — |
| 5. Сценарии | — |
| 6. Админка: переписка, аналитика, настройки | — |
| 7. Безопасность входов и инциденты | — |
| 8. Лимиты | — |
| 9. Семантический слой и SQL | — |
| 10. Прод на GPU-сервере | — |
| 11 ★. Песочница кода | после запуска |
| 12 ★. Память | после запуска |

## Кто чем занят

| Задача | Кто | Ветка |
| --- | --- | --- |
| Этап 0: каркас репозитория | агент | `claude/charming-ride-5jb5sd` |

## Этап 0. Каркас и инструменты

### План

1. Монорепозиторий по §5: uv workspace (`backend`, `services/fake-llm`), pnpm для `frontend`, Makefile,
   pre-commit.
2. Бэкенд: конфиг с валидацией (Pydantic Settings + YAML слоями), structlog с `request_id`,
   `/health` и `/ready`, единый формат ошибок, Alembic, CLI, каркас модулей с README.
3. fake-llm в формате vLLM со сценариями §16.1.
4. mock-AD: Samba AD DC с тестовыми данными §6.7.
5. Compose для разработки: postgres, redis, qdrant, mock-ad, fake-llm, embed на CPU, api, frontend.
6. Каркас SPA: роутинг, layout, тема, i18n, генерация API-клиента.
7. Документация: AGENTS.md, CLAUDE.md, структура `docs/`, ADR по §2.3, этот файл; `make docs-check`.

### Критерии приёмки

- [x] `make dev-up` поднимает стек с нуля одной командой — проверено в песочнице агента для всех
  сервисов, кроме `embed`: образ text-embeddings-inference лежит на ghcr.io, а сеть песочницы не
  пускает к его хранилищу. **Нужно повторить на машине разработчика** (первый запуск качает ~2,3 ГБ весов).
- [x] `make check` (линт, типы, тесты, сборка образов) зелёный; pre-commit-хуки установлены и запускают
  быстрые проверки. Линт, типы, тесты (backend + fake-llm 38, frontend 15) и docs-check — зелёные.
  Образы `api`, `fake-llm`, `mock-ad`, `frontend` собраны; в песочнице агента для этого понадобился
  CA её прокси. **Нужно повторить `make check` целиком на машине разработчика.**
- [x] SPA открывается, тема переключается и сохраняется — e2e `frontend/tests/e2e/theme.spec.ts`
  и ручная проверка против живого стека (индикатор «API готов»).
- [x] fake-llm отдаёт стрим с размышлениями и вызовом инструмента — `services/fake-llm/tests`.
- [x] В `docs/` есть индекс, ADR и `status.md`.

### Демо-сценарий

```bash
make install
```

```bash
make dev-up
```

1. <http://localhost:5173> — каркас приложения, в шапке «API готов»; переключите тему на «Тёмная»
   и обновите страницу — тема сохранилась, вспышки светлой темы нет.
2. <http://localhost:8000/ready> — `{"status":"ready", …}` по postgres, redis, qdrant;
   остановите redis (`docker compose … stop redis`) — `/ready` отвечает 503 с причиной, индикатор
   в SPA жёлтый.
3. fake-llm — стрим с размышлениями и вызов инструмента:

   ```bash
   curl -N localhost:8081/v1/chat/completions -H 'Content-Type: application/json' \
     -d '{"model":"fake-chat","stream":true,"messages":[{"role":"user","content":"[[scenario:thinking]] привет"}]}'
   ```

   ```bash
   curl -N localhost:8081/v1/chat/completions -H 'Content-Type: application/json' \
     -d '{"model":"fake-chat","stream":true,"messages":[{"role":"user","content":"[[scenario:tool_call_search]] отпуск"}]}'
   ```

4. Конфиг: `APP_ENV=prod APP_AUTH__PROVIDERS='["dev"]' uv run python -m app.cli config check` —
   понятные ошибки, код 1.
5. `make check` — зелёный.

## Открытые вопросы

Из §21 «уточнить при деплое» (разработку не блокируют, в конфиге помечены `TODO(question)`):

1. Логины первых админов (`auth.bootstrap_admins`).
2. Адреса контроллеров домена и сервисная учётка (`ldap.urls`, `ldap.bind_dn`).
3. Имя и колонки представления телефонного справочника в MS SQL (этап 9).
4. Названия отделов для правил ролей (`ldap.department_roles.rules`).

Решения агента на этапе 0 — подтвердить при ревью:

5. Дев-эмбеддинги — text-embeddings-inference (CPU) с bge-m3, а не vLLM на CPU ([ADR-0010](adr/0010-dev-stand-mocks.md)).
6. Версии: PostgreSQL 17.11 (SPEC: 16+), Qdrant v1.19.2 (SPEC: ≥ 1.15.3; переход на 1.20 — после eval),
   Redis 7.4, TypeScript 6.0 (7.0 пока не поддерживают typescript-eslint и openapi-typescript).
7. Имя поля размышлений в стриме vLLM (`reasoning` или `reasoning_content`) зависит от версии vLLM —
   клиент LLM на этапе 2 должен понимать оба; fake-llm переключается `FAKE_LLM_REASONING_FIELD`.
8. Celery (`worker`, `scheduler`) добавляется на этапе 3 вместе с первыми фоновыми задачами, а не
   пустым сервисом на этапе 0.
