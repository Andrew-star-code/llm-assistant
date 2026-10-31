# Схема БД

> Файл сгенерирован командой `make docs-db` из моделей SQLAlchemy. Не правьте вручную.
> Ключевые таблицы и их назначение — [SPEC §14](../SPEC.md#14-модель-данных-postgresql).

## `app_settings`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `key` | VARCHAR(128) | not null | PK |
| `value` | JSONB | not null |  |
| `updated_by` | UUID | null | → users.id, index |
| `updated_at` | TIMESTAMP WITH TIME ZONE | not null |  |

## `audit_log`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `actor_id` | UUID | null | → users.id, index |
| `action` | VARCHAR(64) | not null | index |
| `target_type` | VARCHAR(64) | null |  |
| `target_id` | VARCHAR(128) | null | index |
| `details` | JSONB | not null |  |
| `ip` | VARCHAR(64) | null |  |
| `ts` | TIMESTAMP WITH TIME ZONE | not null | index |
| `id` | UUID | not null | PK |

## `login_events`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `user_id` | UUID | null | → users.id, index |
| `login_attempted` | VARCHAR(256) | not null | index |
| `ts` | TIMESTAMP WITH TIME ZONE | not null | index |
| `ip` | VARCHAR(64) | null |  |
| `user_agent` | TEXT | null |  |
| `method` | VARCHAR(16) | not null |  |
| `success` | BOOLEAN | not null |  |
| `failure_reason` | VARCHAR(64) | null |  |
| `risk_flags` | JSONB | not null |  |
| `details` | JSONB | not null |  |
| `reviewed_by` | UUID | null | → users.id, index |
| `id` | UUID | not null | PK |

## `permissions`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `code` | VARCHAR(128) | not null | PK |
| `description` | TEXT | not null |  |

## `role_permissions`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `role_id` | UUID | not null | PK, → roles.id |
| `permission_code` | VARCHAR(128) | not null | PK, → permissions.code, index |

## `roles`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `code` | VARCHAR(256) | not null | unique |
| `name` | VARCHAR(256) | not null |  |
| `kind` | VARCHAR(32) | not null |  |
| `description` | TEXT | null |  |
| `id` | UUID | not null | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | not null |  |

## `sessions`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `user_id` | UUID | not null | → users.id, index |
| `token_hash` | VARCHAR(64) | not null | unique |
| `provider` | VARCHAR(16) | not null |  |
| `last_seen_at` | TIMESTAMP WITH TIME ZONE | not null |  |
| `expires_at` | TIMESTAMP WITH TIME ZONE | not null |  |
| `ip` | VARCHAR(64) | null |  |
| `user_agent` | TEXT | null |  |
| `revoked_at` | TIMESTAMP WITH TIME ZONE | null |  |
| `revoked_by` | UUID | null | → users.id, index |
| `revoke_reason` | VARCHAR(64) | null |  |
| `id` | UUID | not null | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | not null |  |

## `user_roles`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `user_id` | UUID | not null | PK, → users.id |
| `role_id` | UUID | not null | PK, → roles.id, index |
| `source` | VARCHAR(16) | not null | PK |
| `granted_by` | UUID | null | → users.id, index |
| `created_at` | TIMESTAMP WITH TIME ZONE | not null |  |

## `users`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `ad_guid` | VARCHAR(64) | not null | unique |
| `login` | VARCHAR(128) | not null | unique |
| `upn` | VARCHAR(256) | null |  |
| `email` | VARCHAR(256) | null |  |
| `full_name` | VARCHAR(512) | not null |  |
| `last_name` | VARCHAR(128) | null |  |
| `first_name` | VARCHAR(128) | null |  |
| `middle_name` | VARCHAR(128) | null |  |
| `title` | VARCHAR(256) | null |  |
| `department` | VARCHAR(256) | null |  |
| `company` | VARCHAR(256) | null |  |
| `office` | VARCHAR(256) | null |  |
| `phone` | VARCHAR(64) | null |  |
| `mobile` | VARCHAR(64) | null |  |
| `manager_dn` | TEXT | null |  |
| `manager_name` | VARCHAR(512) | null |  |
| `employee_id` | VARCHAR(64) | null |  |
| `photo_key` | VARCHAR(256) | null |  |
| `photo_sha256` | VARCHAR(64) | null |  |
| `ad_groups` | JSONB | not null |  |
| `address_form` | VARCHAR(32) | null |  |
| `settings` | JSONB | not null |  |
| `is_blocked` | BOOLEAN | not null |  |
| `blocked_reason` | TEXT | null |  |
| `blocked_until` | TIMESTAMP WITH TIME ZONE | null |  |
| `blocked_by` | UUID | null | → users.id, index |
| `ad_disabled` | BOOLEAN | not null |  |
| `notice_accepted_at` | TIMESTAMP WITH TIME ZONE | null |  |
| `last_login_at` | TIMESTAMP WITH TIME ZONE | null |  |
| `synced_at` | TIMESTAMP WITH TIME ZONE | null |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | not null |  |
| `id` | UUID | not null | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | not null |  |
