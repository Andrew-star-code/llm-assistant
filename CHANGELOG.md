# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Added

- Этап 1 «Вход, пользователи, роли, каркас админки» (§19 SPEC):
  - вход через AD (LDAPS / StartTLS): bind по UPN с обходом контроллеров, поиск сервисной учёткой
    с экранированием, проверка `userAccountControl` и `access_group` с вложенными группами;
    провайдер `dev` с seed-пользователями; нормализация логина (`CORP\ivanov`, UPN);
  - серверные сессии (cookie HttpOnly + Redis + таблица `sessions`), CSRF double submit, выход;
  - журнал входов с точной причиной отказа, защита от перебора по логину и IP;
  - пользователи из AD (ключ `objectGUID`), фото, отчество из `displayName`, формы обращения,
    периодическая синхронизация (отключённых в AD — блокировать и разлогинивать);
  - роли отделов из `department`, правила по атрибутам, `group_roles`, `bootstrap_admins`,
    гранулярные права, системные роли `superadmin`, `admin`, `kb_manager`;
  - админка: «Пользователи» (поиск, карточка, блокировка, разлогин, ручные роли), «Входы»,
    «Журнал аудита» (только вставка), «Диагностика AD»;
  - CLI `ad check [--password-prompt]`, `ad sync`, `create-admin`, `db-docs`;
  - фронтенд: страница входа, проверка сессии, уведомление при первом входе, меню пользователя,
    профиль, тема в настройках пользователя, каркас админки с проверкой прав;
  - миграция 0002; интеграционные тесты на testcontainers и mock-AD, e2e входа и админки;
  - документация: `guides/ad-setup.md`, `guides/add-admin-page.md`, `reference/permissions.md`,
    `reference/db-schema.md` (генерируется), `architecture/security.md`.

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
