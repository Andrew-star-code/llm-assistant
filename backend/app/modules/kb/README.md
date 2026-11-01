# modules/kb

> Статус: реализовано на этапе 4 (§7.8, §10.1, §10.3, §13.2).

**Назначение:** базы знаний трёх уровней — общие (`global`), ролевые (`role`, кто видит — `kb_roles`)
и личные (`personal`, одна на пользователя, создаётся при первом обращении), их документы и массовый
импорт из папки на сервере.

**Публичный интерфейс:**

| Эндпоинт | Назначение |
| --- | --- |
| `GET /api/kb/personal` | «Моя база знаний»: документы со статусами и квота (100 документов, 500 МБ) |
| `POST /api/kb/personal/documents` | Загрузка (проверки §9.3, дедупликация по SHA-256, квота) → индексация |
| `DELETE /api/kb/personal/documents/{id}`, `POST …/{id}/reindex` | Удаление (сразу пропадает из поиска), переиндексация |
| `GET /api/kb/documents/{id}`, `…/content`, `…/preview` | Документ-источник цитаты: права на базу проверяются заново (§10.5) |
| `GET/POST /api/admin/kb`, `PATCH/DELETE /api/admin/kb/{id}` | Базы: создать, название, роли, удалить (`admin.kb.manage`) |
| `GET/POST /api/admin/kb/{id}/documents`, `DELETE …/{doc}`, `POST …/{doc}/reindex` | Документы базы |
| `GET /api/admin/kb/import-folders`, `GET/POST /api/admin/kb/{id}/imports` | Массовый импорт из папки внутри `kb.import_root` и его прогресс |

Менеджер БЗ (`admin.kb.manage_roles`) видит и наполняет только ролевые базы тех ролей, что есть у него
самого; создавать базы и менять роли может только `admin.kb.manage`. Все действия админов — в аудит.

CLI: `python -m app.cli kb list`, `python -m app.cli kb import --kb <код> <папка>`.

**Индексация** — воркер очереди `kb` (`app/workers/kb_jobs.py`): разбор (модуль `ingestion`) →
чанкинг по структуре → dense + BM25 в Qdrant (модуль `rag`) → `ready` с числом чанков; ошибка →
`error` с причиной и инцидент `kb_index`; непредвиденный сбой импорта — `error` и инцидент
`worker_failed`. Office-документы получают PDF-превью — по нему источник
открывается на нужной странице. Импорт: каждый файл сразу фиксируется в БД (`source_path`), поэтому
после перезапуска воркер (`kb.requeue` при старте) продолжает с того же места без дублей.

**Зависит от:** `files` (проверки и хранение), `ingestion`, `rag`, `rbac`, `audit`, `incidents`.

**Точки расширения:** квоты по ролям (§7.8) — `TODO(stage-8)` вместе с лимитами; базы сценария — этап 5.

**Данные:** `knowledge_bases`, `kb_roles`, `kb_documents`, `kb_imports`; файлы — `files.kind = kb_document`.

**Тесты:** `backend/tests/integration/test_rag.py`, `backend/tests/unit/test_rag_units.py`.
