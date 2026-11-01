# modules/audit

> Статус: реализовано на этапе 1 (§13.6).

**Назначение:** журнал действий администраторов над чужими данными и настройками.

**Публичный интерфейс:** `service.record(db, actor_id=…, action=…, target_type=…, target_id=…,
details=…, ip=…)` — запись добавляется в ту же транзакцию, что и действие. Просмотр —
`GET /api/admin/audit` (право `admin.audit.view`).

Действия этапа 1: `user.block`, `user.unblock`, `user.logout`, `user.roles`, `session.revoke`,
`ad.diagnostics`. Дальше: просмотр чужого чата, выгрузки, изменение лимитов и сценариев (этапы 6–8).

**Только вставка:** UPDATE и DELETE запрещены триггером `audit_log_append_only` (миграция 0002);
физическая очистка по сроку хранения — отдельной процедурой superadmin (этап 6).

**Зависит от:** —

**Точки расширения:** новое действие — строка `action` + перевод в `frontend/src/i18n/locales/*.json`
(`auditAction.*`).

**Данные:** `audit_log`.

**Тесты:** `backend/tests/integration/test_admin.py`.
