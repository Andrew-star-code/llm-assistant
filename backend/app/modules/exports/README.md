# modules/exports

> Статус: реализовано на этапе 6 (§13.3, §14).

**Назначение:** фоновые выгрузки переписки из админки: JSON (полная, со скрытыми вызовами и
трассировкой), XLSX (строка на сообщение), DOCX и PDF (читаемая стенограмма с пометками об
удалении и версиями ответов). Файл доступен только заказавшему и хранится `exports.ttl_days`.

**Публичный интерфейс** (право `admin.chats.export`):

| Эндпоинт | Назначение |
| --- | --- |
| `POST /api/admin/exports` (`{format, chat_id}` или `{format, filter: ChatFilter}`) | Заказ → 202, задача `exports.build` (аудит `chat.export`) |
| `GET /api/admin/exports`, `GET /api/admin/exports/{id}` | Свои выгрузки и их статус (`queued → running → ready / error → expired`) |
| `GET /api/admin/exports/{id}/download` | Файл (аудит `export.download`); чужая — 404, истёкшая — 410 |

Сборка — `service.py` (чаты пачками по 200; XLSX в режиме write-only), задача —
`app/workers/export_jobs.py::export_job` в очереди `files` (DOCX — pandoc, PDF — LibreOffice в образе
воркера). Предел — `exports.max_messages`: больше — статус «ошибка» с просьбой сузить фильтр. Сбой —
«ошибка» и инцидент `worker_failed`.

**Плановые задачи** (сервис `scheduler`, Celery beat): `exports.cleanup` раз в час удаляет файлы
истёкших выгрузок; `retention.purge` раз в 6 часов физически стирает чаты, удалённые раньше срока
хранения (`retention.deleted_days` или админка «Настройки»; 0 — выключено), с записью
`retention.purge` в аудит.

**Зависит от:** `admin` (фильтр переписки), `chats` (`purge`), `files`, `audit`, воркер.

**Точки расширения:** новый формат — ветка в `export_jobs._export` и функция `build_*` в `service.py`.

**Данные:** `exports`; файлы — `files` с `kind = export` (через `/api/files` не отдаются).

**Тесты:** `backend/tests/integration/test_admin_exports.py` (форматы, доступ только заказавшему,
срок хранения, предел, 1000 сообщений в XLSX быстрее минуты, очистка по сроку).
