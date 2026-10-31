# Как добавить страницу админки

1. **Право.** Добавьте значение в `Perm` и описание в `PERMISSION_DESCRIPTIONS`
   (`backend/app/modules/rbac/permissions.py`), строку — в [reference/permissions.md](../reference/permissions.md).
   Решите, входит ли право в системную роль `admin` (у существующих установок набор прав роли
   меняется в админке или миграцией данных — при старте он не перезаписывается).
2. **API.** Эндпоинт в `backend/app/modules/admin/router.py` (или роутер модуля с префиксом
   `/admin`) с зависимостью `Depends(require(Perm.…))`. Любое действие над чужими данными или
   настройками — `audit.record(...)` в той же транзакции. Списки — с курсорной пагинацией
   (`core/pagination.py`).
3. **Тесты.** Интеграционный тест в `backend/tests/integration/`; тест
   `test_every_admin_endpoint_requires_permission` автоматически проверит, что без права — 403.
4. **Клиент.** `make gen-api` — обновятся `frontend/src/api/schema.d.ts` и `docs/reference/api.md`.
5. **Страница.** Компонент в `frontend/src/admin/pages/`, маршрут в `frontend/src/app/router.tsx`
   (внутри `/admin`), пункт меню с правом в `frontend/src/admin/sections.ts`. Строки — в
   `frontend/src/i18n/locales/ru.json` и `en.json`.
6. **Документация.** README модуля, CHANGELOG, `docs/status.md`.
