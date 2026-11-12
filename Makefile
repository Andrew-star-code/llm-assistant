# Команды проекта (§17.2). CI-сервера нет: `make check` обязателен перед каждым пушем (§20).
# Справка: make help

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE_DIR := deploy/compose
ENV_FILE    := $(COMPOSE_DIR)/.env
COMPOSE     := docker compose --env-file $(ENV_FILE) -f $(COMPOSE_DIR)/docker-compose.yml -f $(COMPOSE_DIR)/compose.dev.yml
UV          := uv run --frozen
# Из каталога frontend: corepack берёт версию pnpm из его package.json (packageManager).
PNPM        := cd frontend && pnpm
PY_SOURCES  := backend services scripts eval
# Отчёты eval пишутся в смонтированный eval/ от имени пользователя хоста (в образе — uid 10001).
EVAL_USER   := --user "$$(id -u):$$(id -g)" -e HOME=/tmp

.PHONY: help install env dev-up dev-models-up dev-down dev-reset dev-logs dev-ps migrate \
        lint fmt typecheck test test-unit test-backend test-frontend e2e eval-rag eval-scenarios load-test gen-api docs-config docs-db \
        docs-check \
        images test-worker test-data-gateway test-monitoring check deploy

help: ## Список команд
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости (uv, pnpm) и pre-commit-хуки
	uv sync --frozen
	$(PNPM) install --frozen-lockfile
	$(UV) pre-commit install

env: $(ENV_FILE)
$(ENV_FILE):
	cp $(COMPOSE_DIR)/.env.example $(ENV_FILE)
	@echo "Создан $(ENV_FILE) из .env.example"

# ------------------------------------------------------------------ дев-стенд

dev-up: env ## Поднять дев-стенд с нуля одной командой (postgres, redis, qdrant, mock-ad, mock-mssql, fake-llm, embed, api, generator, worker, scheduler, data-gateway, frontend)
	$(COMPOSE) up -d --build --wait --wait-timeout 2100
	@echo ""
	@echo "  Фронтенд:  http://localhost:5173"
	@echo "  API:       http://localhost:8000/api/docs   (готовность: /ready)"
	@echo "  fake-llm:  http://localhost:8081/v1         embed: http://localhost:8082"
	@echo "  mock-AD:   ldaps://localhost:636            Qdrant: http://localhost:6333/dashboard"

dev-models-up: env ## Настоящий реранкер bge-reranker-v2-m3 (TEI, CPU; ~2,3 ГБ весов) — для eval-rag
	$(COMPOSE) --profile models up -d --wait --wait-timeout 2100 rerank
	@echo "Подключите его к api: deploy/compose/api.local.env по образцу api.local.env.example,"
	@echo "затем: $(COMPOSE) up -d api"

dev-down: ## Остановить дев-стенд (данные сохраняются)
	$(COMPOSE) --profile models down

dev-reset: ## Остановить дев-стенд и удалить его данные (тома)
	$(COMPOSE) --profile models down -v

dev-logs: ## Логи дев-стенда (S=<сервис> — только один)
	$(COMPOSE) logs -f --tail=200 $(S)

dev-ps: ## Состояние сервисов дев-стенда
	$(COMPOSE) ps

migrate: env ## Применить миграции БД (alembic upgrade head)
	$(COMPOSE) run --rm --build migrate

# ------------------------------------------------------------------ качество

lint: ## Линтеры: ruff (+ формат), eslint, prettier
	$(UV) ruff check $(PY_SOURCES)
	$(UV) ruff format --check $(PY_SOURCES)
	$(PNPM) lint

fmt: ## Автоформатирование Python и фронтенда
	$(UV) ruff check --fix $(PY_SOURCES)
	$(UV) ruff format $(PY_SOURCES)
	$(PNPM) format

typecheck: ## Проверка типов: mypy (strict), tsc
	$(UV) mypy backend/app backend/tests services/fake-llm services/data-gateway scripts eval
	$(PNPM) typecheck

test: test-backend test-frontend ## Все unit- и интеграционные тесты (нужен Docker: testcontainers, mock-AD)

test-unit: ## Быстрые тесты без Docker: unit бэкенда и фронтенда
	$(UV) pytest backend/tests/unit services/fake-llm/tests services/data-gateway/tests
	$(PNPM) test

test-backend:
	$(UV) pytest

test-frontend:
	$(PNPM) test

e2e: ## E2E-тесты Playwright
	$(PNPM) e2e

# Настоящие базы знаний: make eval-rag KB=<коды через запятую> QUESTIONS=eval/rag/local/<файл>.yaml
eval-rag: env ## Оценка поиска (§10.6): hit@5 и MRR по 4 конфигурациям и подбор порога реранкера
	$(COMPOSE) run --rm --no-deps $(EVAL_USER) -v $(CURDIR)/eval:/srv/eval api python /srv/eval/rag/run.py \
		--check --json /srv/eval/rag/report.json $(if $(KB),--kb $(KB)) \
		$(if $(QUESTIONS),--questions /srv/$(QUESTIONS))

eval-scenarios: env ## Эталонные запросы сценариев (§18): ответы + LLM-судья, сравнение с прошлым прогоном
	$(COMPOSE) run --rm --no-deps $(EVAL_USER) -v $(CURDIR)/eval:/srv/eval api python /srv/eval/scenarios/run.py \
		--report /srv/eval/scenarios/report.json --baseline /srv/eval/scenarios/baseline.json

# Против настоящего сервера: make load-test LOAD_ARGS="--base-url https://assistant.corp.local --provider ldap --logins u1,u2 --password … --prompt 'Расскажи о компании'"
load-test: ## Нагрузочный тест чата (§18.4): 10 одновременных диалогов против стенда (сначала make dev-up)
	$(UV) python eval/load/run.py --check --json eval/load/report.json $(LOAD_ARGS)

gen-api: ## Перегенерировать OpenAPI, клиентские типы фронтенда и docs/reference/api.md
	APP_ENV=dev $(UV) python -m app.cli openapi -o frontend/src/api/openapi.json
	APP_ENV=dev $(UV) python -m app.cli api-docs -o docs/reference/api.md
	$(PNPM) gen-api

docs-config: ## Перегенерировать docs/reference/config.md
	APP_ENV=dev $(UV) python -m app.cli config docs -o docs/reference/config.md

docs-db: ## Перегенерировать docs/reference/db-schema.md из моделей SQLAlchemy
	$(UV) python -m app.cli db-docs -o docs/reference/db-schema.md

docs-check: ## Документация не отстаёт от кода (README модулей, сгенерированные справочники, ссылки)
	$(UV) python scripts/docs_check.py

images: env ## Собрать образы приложения
	$(COMPOSE) build
	docker build --target runtime -t ai-assistant/web:$${APP_VERSION:-dev} frontend

test-worker: env ## Самопроверка образа воркера: pandoc, LibreOffice, Tesseract (worker check)
	$(COMPOSE) run --rm --build --no-deps worker python -m app.cli worker check

test-data-gateway: env ## Самопроверка образа шлюза: ODBC Driver 18, подключение к MS SQL, search_employees
	$(COMPOSE) up -d --build --wait mock-mssql
	$(COMPOSE) run --rm --build --no-deps data-gateway python -m data_gateway check

# promtool — из образа Prometheus (по digest, v3.5.0): отдельно его ставить не нужно.
PROMTOOL = docker run --rm -v $(CURDIR)/deploy/monitoring:/m:ro --entrypoint promtool \
	prom/prometheus@sha256:63805ebb8d2b3920190daf1cb14a60871b16fd38bed42b857a3182bc621f4996

test-monitoring: ## Проверка конфигурации Prometheus и тесты правил алертов (promtool)
	$(PROMTOOL) check config /m/prometheus.yml
	$(PROMTOOL) test rules /m/alerts.test.yml

check: lint typecheck test docs-check test-monitoring images test-worker test-data-gateway ## Всё перед пушем: линт → типы → тесты → документация → образы
	@echo "make check: OK"

deploy: ## Выкатка на сервер — этап 10 (§16.2)
	@echo "make deploy появится на этапе 10 (§16.2, §19). Сейчас — только дев-стенд: make dev-up." >&2
	@exit 1
