# modules/ingestion

> Статус: разбор вложений — этап 3 (§9.3); база знаний и гибридный поиск — этап 4.

**Назначение:** разбор документов в Markdown с маркерами страниц `<!-- page: N -->` и оглавлением,
чанкинг и индекс вложений в Qdrant.

**Парсеры (`parsers.py`, `parse_file`):**

| Формат | Чем |
| --- | --- |
| PDF | PyMuPDF; страница без текстового слоя (< `files.ocr_min_chars_per_page`) — OCR Tesseract `rus+eng` |
| DOCX | python-docx: страницы по разрывам (в т. ч. `lastRenderedPageBreak`), заголовки по стилям, таблицы в Markdown; без разрывов — виртуальные страницы |
| XLSX | openpyxl: лист = страница |
| PPTX | python-pptx: слайд = страница, заметки докладчика |
| DOC, RTF, ODT / XLS, ODS / PPT, ODP | LibreOffice headless → DOCX / XLSX / PPTX (`convert.py`, отдельный профиль, kill группы процессов по тайм-ауту) |
| HTML | MarkItDown; CSV/TSV — таблица; JSON и код — блоком кода; текст — виртуальные страницы по ~3000 символов |

docling подключается флагом `files.docling_enabled` (по умолчанию выключен: модели docling нужно
поставить офлайн, этап 10). Лимиты: `files.max_pages`, `files.max_text_chars` (лишнее обрезается с
предупреждением), `files.parse_timeout_seconds`.

**Индекс (`index.py`):** коллекция `attachment_chunks`, вектор `dense` (роль `embed`), чанки ~1200
символов с перекрытием и префиксом «Документ: … / стр. N». Поиск — только по id вложений текущего
чата (фильтр ставит сервер). Если Qdrant или эмбеддер недоступны, документ всё равно читается
целиком и `read_document`, в оглавлении — предупреждение.

**Зависит от:** `llm` (embed), Qdrant; бинарники LibreOffice и Tesseract — в образе воркера.

**Точки расширения:** новый формат — функция `parse_<формат>` и ветка в `parse_file`;
BM25, гибрид и реранк — этап 4 (`TODO(stage-4)`).

**Данные:** коллекция `attachment_chunks`; дальше `kb_chunks`, `personal_chunks`.

**Тесты:** `backend/tests/unit/test_files.py` (OCR и LibreOffice — при наличии бинарников, полностью —
`make test-worker` в образе воркера), `backend/tests/integration/test_files.py`.
