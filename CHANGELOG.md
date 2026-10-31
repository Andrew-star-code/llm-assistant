# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Added

- Этап 0 «Каркас и инструменты» (§19 SPEC):
  - монорепозиторий по §5, uv workspace (`backend`, `services/fake-llm`) и pnpm для фронтенда;
  - бэкенд: конфиг слоями (`config/app.yaml`, `config/models.yaml` + оверлеи окружения, `APP_*`,
    `/run/secrets`) с валидацией при старте; structlog (JSON) с `request_id` и маскированием секретов;
    `/health`, `/ready` (PostgreSQL, Redis, Qdrant), `/metrics`; единый формат ошибок; Alembic;
    CLI `python -m app.cli` (`config check|docs`, `openapi`, `api-docs`); каркас модулей с README;
  - fake-llm: OpenAI-совместимый mock в формате vLLM — стрим, размышления, вызов инструмента,
    ошибка 500, обрыв, медленный стрим, эмбеддинги, реранк;
  - mock-AD: Samba AD DC с русскими тестовыми пользователями, группами и LDAPS;
  - дев-стенд Docker Compose: postgres, redis, qdrant, mock-ad, fake-llm, embed (bge-m3 на CPU),
    api с hot reload, frontend (Vite);
  - каркас SPA: роутинг, layout, тема «Светлая / Тёмная / Как в системе» без мигания, i18n (ru, en),
    клиент API из OpenAPI;
  - `make check` (линт, типы, тесты, docs-check, сборка образов), pre-commit-хуки;
  - документация: AGENTS.md, ADR 0001–0010, обзор архитектуры, SSE-протокол (черновик),
    генерируемые справочники конфигурации и API, `docs/status.md`.
