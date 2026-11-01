# modules/files

> Статус: реализовано на этапе 3 (§7.3, §7.7, §9.3–9.4, §15).

**Назначение:** загрузки вложений с проверками, сгенерированные файлы, скачивание и превью.

**Проверки загрузки (`sniff.py`, до записи на диск разбора):** размер (`files.max_file_mb`, потоком —
413 `too_large`), пустой файл, тип **по сигнатуре** и сверка с расширением (`type_mismatch`),
неподдерживаемые форматы и архивы (`unsupported`), OOXML/ODF — наличие обязательных частей,
zip-бомбы (`zip_bomb`: распакованный объём, число записей, степень сжатия), шифрование. Ответ —
понятный текст ошибки, его показывает чип файла.

**Публичный интерфейс:**

| Эндпоинт | Назначение |
| --- | --- |
| `GET /api/files/limits` | Лимиты и допустимые расширения для поля ввода |
| `POST /api/files` (multipart `file`) | Загрузка → `parse_status: pending` и задача разбора в воркере |
| `GET /api/files/{id}` | Статус разбора (`pending/processing/ready/error` + причина), страницы |
| `GET /api/files/{id}/content?download=` | Оригинал; `download=false` — inline только PDF, остальное `text/plain` |
| `GET /api/files/{id}/preview` | PDF-превью (оригинал PDF или превью Office-файла из воркера) |
| `DELETE /api/files/{id}` | Удалить ещё не приложенный файл (крестик на чипе) |

К сообщению файлы прикладываются полем `attachment_ids` в `POST /api/chats/{id}/messages`
(`service.attach`: только свои, только `ready`, не больше `files.max_files_per_message`).
Сбой задачи разбора вне известных ошибок формата тоже даёт `error` с причиной (и инцидент
`worker_failed`), а не вечное «читаю…»; вложения `pending` / `processing` воркер `files` при
старте ставит в очередь заново (`files.requeue`).
Сгенерированные файлы создаёт воркер (`generate.py`): DOCX — pandoc по `config/templates/reference.docx`
(формулы `$…$` → нативные формулы Word), PDF — DOCX через LibreOffice, XLSX — openpyxl (типы, формат
чисел, шапка, автофильтр, формулы), CSV с BOM, PPTX — python-pptx по `presentation.pptx`.

**Безопасность:** доступ только владельцу (`service.get_file` → 404 на чужое), имя файла — только
для показа, на диске — случайный ключ; `X-Content-Type-Options: nosniff`, `CSP: sandbox` (только
для показа в браузере — на скачивании Chromium из-за неё теряет имя файла),
`Content-Disposition` с RFC 5987.

**Зависит от:** `core.storage` (локальный диск), `workers` (разбор и генерация), `ingestion`.

**Точки расширения:** S3 — новая реализация `Storage` (FUTURE); новый формат генерации —
`generate.py` + аргументы инструмента в `tools/builtin/generation.py`.

**Данные:** `files` (`kind`: `upload`, `generated`; дальше `kb_document`, `export`); в хранилище —
`uploads/`, `generated/`, `texts/` (Markdown с маркерами страниц), `previews/`.

**Тесты:** `backend/tests/unit/test_files.py`, `backend/tests/integration/test_files.py`.
