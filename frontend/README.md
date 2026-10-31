# frontend

SPA пользователя и админки: React 19 + TypeScript (strict) + Vite, Tailwind CSS + shadcn/ui,
TanStack Query, Zustand, React Router, i18next (§4 SPEC).

| Каталог              | Что внутри                                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------------ |
| `src/app/`           | Роутер, провайдеры, layout                                                                                   |
| `src/api/`           | `openapi.json` и `schema.d.ts` (генерируются `make gen-api`), клиент `client.ts`; SSE-клиент — этап 2        |
| `src/features/`      | Фичи пользовательской части: `home`, `theme`, `system`; дальше — chat, sidebar, composer, message, markdown… |
| `src/admin/`         | Админка: layout и `pages/`                                                                                   |
| `src/components/ui/` | Компоненты shadcn/ui                                                                                         |
| `src/i18n/`          | `locales/ru.json` (по умолчанию) и `en.json` — все строки интерфейса только здесь                            |
| `tests/unit/`        | Vitest + Testing Library                                                                                     |
| `tests/e2e/`         | Playwright                                                                                                   |

Команды (из корня репозитория): `make lint`, `make test`, `make e2e`, `make gen-api`.
Напрямую: `pnpm dev` (прокси на api — `VITE_API_PROXY_TARGET`, по умолчанию `http://127.0.0.1:8000`),
`pnpm test`, `pnpm e2e`, `pnpm build`.

Правила: без CDN и внешних шрифтов (§4); без inline-скриптов (CSP, §15) — поэтому тема
до загрузки React применяется внешним `public/theme-init.js`; клиентские типы API не править
руками — только `make gen-api`.
