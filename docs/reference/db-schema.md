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

## `chats`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `user_id` | UUID | not null | → users.id, index |
| `folder_id` | UUID | null | → folders.id, index |
| `title` | VARCHAR(300) | null |  |
| `scenario_id` | UUID | null |  |
| `pinned` | BOOLEAN | not null |  |
| `active_leaf_id` | UUID | null |  |
| `thinking_enabled` | BOOLEAN | null |  |
| `last_message_at` | TIMESTAMP WITH TIME ZONE | null |  |
| `deleted_at` | TIMESTAMP WITH TIME ZONE | null |  |
| `deleted_by` | UUID | null | → users.id, index |
| `id` | UUID | not null | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | not null |  |

## `feedback`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `message_id` | UUID | not null | → messages.id, index |
| `user_id` | UUID | not null | → users.id, index |
| `rating` | SMALLINT | not null |  |
| `reasons` | JSONB | not null |  |
| `comment` | TEXT | null |  |
| `id` | UUID | not null | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | not null |  |

## `folders`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `user_id` | UUID | not null | → users.id, index |
| `name` | VARCHAR(200) | not null |  |
| `sort_order` | INTEGER | not null |  |
| `id` | UUID | not null | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | not null |  |

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

## `messages`

| Колонка | Тип | NULL | Ключи и индексы |
| --- | --- | --- | --- |
| `chat_id` | UUID | not null | → chats.id, index |
| `parent_id` | UUID | null | → messages.id, index |
| `role` | VARCHAR(16) | not null |  |
| `content` | TEXT | not null |  |
| `reasoning` | TEXT | null |  |
| `status` | VARCHAR(16) | not null |  |
| `thinking` | BOOLEAN | not null |  |
| `model` | VARCHAR(256) | null |  |
| `finish_reason` | VARCHAR(32) | null |  |
| `prompt_tokens` | INTEGER | null |  |
| `completion_tokens` | INTEGER | null |  |
| `reasoning_tokens` | INTEGER | null |  |
| `ttft_ms` | INTEGER | null |  |
| `latency_ms` | INTEGER | null |  |
| `error` | JSONB | null |  |
| `trace` | JSONB | null |  |
| `deleted_at` | TIMESTAMP WITH TIME ZONE | null |  |
| `search_vector` | TSVECTOR | null |  |
| `id` | UUID | not null | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | not null |  |

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
