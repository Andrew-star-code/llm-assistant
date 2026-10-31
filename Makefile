# Команды проекта (§17.2). CI-сервера нет: `make check` обязателен перед каждым пушем (§20).
# Справка: make help

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE_DIR := deploy/compose
ENV_FILE    := $(COMPOSE_DIR)/.env
COMPOSE     := docker compose --env-file $(ENV_FILE) -f $(COMPOSE_DIR)/docker-compose.yml -f $(COMPOSE_DIR)/compose.dev.yml
UV          := uv run --frozen
PNPM        := pnpm --dir frontend
PY_SOURCES  := backend services scripts

.PHONY: help install env dev-up dev-down dev-reset dev-logs dev-ps migrate \
        lint fmt typecheck test test-backend test-frontend e2e gen-api docs-config docs-check \
        images check deploy

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

dev-up: env ## Поднять дев-стенд с нуля одной командой (postgres, redis, qdrant, mock-ad, fake-llm, embed, api, frontend)
	$(COMPOSE) up -d --build --wait --wait-timeout 900
	@echo ""
	@echo "  Фронтенд:  http://localhost:5173"
	@echo "  API:       http://localhost:8000/api/docs   (готовность: /ready)"
	@echo "  fake-llm:  http://localhost:8081/v1         embed: http://localhost:8082"
	@echo "  mock-AD:   ldaps://localhost:636            Qdrant: http://localhost:6333/dashboard"

dev-down: ## Остановить дев-стенд (данные сохраняются)
	$(COMPOSE) down

dev-reset: ## Остановить дев-стенд и удалить его данные (тома)
	$(COMPOSE) down -v

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
	$(UV) mypy backend/app backend/tests services/fake-llm scripts
	$(PNPM) typecheck

test: test-backend test-frontend ## Все unit- и интеграционные тесты

test-backend:
	$(UV) pytest

test-frontend:
	$(PNPM) test

e2e: ## E2E-тесты Playwright
	$(PNPM) e2e

gen-api: ## Перегенерировать OpenAPI, клиентские типы фронтенда и docs/reference/api.md
	APP_ENV=dev $(UV) python -m app.cli openapi -o frontend/src/api/openapi.json
	APP_ENV=dev $(UV) python -m app.cli api-docs -o docs/reference/api.md
	$(PNPM) gen-api

docs-config: ## Перегенерировать docs/reference/config.md
	APP_ENV=dev $(UV) python -m app.cli config docs -o docs/reference/config.md

docs-check: ## Документация не отстаёт от кода (README модулей, сгенерированные справочники, ссылки)
	$(UV) python scripts/docs_check.py

images: env ## Собрать образы приложения
	$(COMPOSE) build
	docker build --target runtime -t ai-assistant/web:$${APP_VERSION:-dev} frontend

check: lint typecheck test docs-check images ## Всё перед пушем: линт → типы → тесты → документация → образы
	@echo "make check: OK"

deploy: ## Выкатка на сервер — этап 10 (§16.2)
	@echo "make deploy появится на этапе 10 (§16.2, §19). Сейчас — только дев-стенд: make dev-up." >&2
	@exit 1
