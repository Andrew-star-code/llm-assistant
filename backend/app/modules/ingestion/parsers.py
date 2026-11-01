"""Разбор документов в Markdown с маркерами страниц и оглавлением (§9.3, §10.3).

Результат одинаков для всех форматов: текст ``<!-- page: N -->`` + содержимое страницы, а также
оглавление (заголовки, таблицы, листы). У DOCX настоящие страницы известны только после вёрстки:
берём разрывы, которые сохранил Word (``lastRenderedPageBreak``), и явные разрывы; если их нет —
режем на «условные» страницы по ~3000 символов (``outline.virtual_pages = true``).

Порядок выбора парсера: docling (если включён и установлен, этап 10) → собственные парсеры на
PyMuPDF / python-docx / openpyxl / python-pptx → MarkItDown (HTML). DOC, XLS, PPT, RTF и ODF сначала
конвертируются LibreOffice в OOXML. Страницы PDF без текстового слоя распознаются Tesseract.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from app.core.config import FilesSettings
from app.modules.ingestion.convert import ConversionError, libreoffice_convert, ocr_image

log = structlog.stdlib.get_logger("app.ingestion")

PAGE_MARKER = "<!-- page: {n} -->"
PAGE_SPLIT = re.compile(r"^<!-- page: (\d+) -->$", re.MULTILINE)
VIRTUAL_PAGE_CHARS = 3000
MAX_TABLE_ROWS_IN_TEXT = 500

LEGACY_TARGET = {
    "doc": "docx",
    "rtf": "docx",
    "odt": "docx",
    "xls": "xlsx",
    "ods": "xlsx",
    "ppt": "pptx",
    "odp": "pptx",
}
CODE_LANG = {
    "py": "python",
    "js": "javascript",
    "mjs": "javascript",
    "ts": "typescript",
    "tsx": "tsx",
    "jsx": "jsx",
    "java": "java",
    "kt": "kotlin",
    "cs": "csharp",
    "go": "go",
    "rs": "rust",
    "c": "c",
    "h": "c",
    "cpp": "cpp",
    "hpp": "cpp",
    "cc": "cpp",
    "php": "php",
    "rb": "ruby",
    "sh": "bash",
    "bash": "bash",
    "ps1": "powershell",
    "bat": "bat",
    "css": "css",
    "scss": "scss",
    "swift": "swift",
    "r": "r",
    "bsl": "1c",
    "vue": "vue",
    "sql": "sql",
    "json": "json",
    "xml": "xml",
    "yaml": "yaml",
    "yml": "yaml",
    "toml": "toml",
    "ini": "ini",
    "tex": "latex",
    "dockerfile": "dockerfile",
}


class ParseError(Exception):
    """Документ не разобран; текст — причина для пользователя."""


@dataclass
class ParsedDocument:
    pages: list[str]
    headings: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    sheets: list[dict[str, Any]] = field(default_factory=list)
    virtual_pages: bool = False
    ocr_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parser: str = ""

    def markdown(self) -> str:
        parts = []
        for number, text in enumerate(self.pages, start=1):
            parts.append(f"{PAGE_MARKER.format(n=number)}\n\n{text.strip()}\n")
        return "\n".join(parts)

    def outline(self) -> dict[str, Any]:
        return {
            "headings": self.headings,
            "tables": self.tables,
            "sheets": self.sheets,
            "virtual_pages": self.virtual_pages,
            "ocr_pages": self.ocr_pages,
            "warnings": self.warnings,
            "parser": self.parser,
        }


def split_pages(markdown: str) -> list[str]:
    """Обратная операция к ``ParsedDocument.markdown``: тексты страниц по порядку."""
    parts = PAGE_SPLIT.split(markdown)
    # [до первого маркера, n1, текст1, n2, текст2, …]
    return [parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)]


def _units(text: str, size: int) -> Iterator[tuple[str, str]]:
    """Куски текста с разделителем после них: абзацы, а слишком длинные — строки или отрезки."""
    for paragraph in text.split("\n\n"):
        if len(paragraph) <= size:
            yield paragraph, "\n\n"
            continue
        for line in paragraph.split("\n"):
            for start in range(0, max(len(line), 1), size):
                yield line[start : start + size], "\n"


def virtual_pages(text: str, size: int = VIRTUAL_PAGE_CHARS) -> list[str]:
    """Режет текст на «страницы» по абзацам (длинные — по строкам), не длиннее ~size символов."""
    pages: list[str] = []
    current = ""
    for unit, separator in _units(text, size):
        if current and len(current) + len(unit) > size:
            pages.append(current.rstrip("\n"))
            current = ""
        current += unit + separator
    if current.strip("\n"):
        pages.append(current.rstrip("\n"))
    return pages or [""]


def markdown_table(rows: list[list[str]], *, max_rows: int = MAX_TABLE_ROWS_IN_TEXT) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)

    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ").strip()

    header = [cell(c) for c in rows[0]] + [""] * (width - len(rows[0]))
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for row in rows[1 : max_rows + 1]:
        cells = [cell(c) for c in row] + [""] * (width - len(row))
        lines.append("| " + " | ".join(cells) + " |")
    if len(rows) - 1 > max_rows:
        lines.append(f"\n_…ещё {len(rows) - 1 - max_rows} строк — читайте таблицу по диапазонам_")
    return "\n".join(lines)


# ------------------------------------------------------------------ PDF


def parse_pdf(path: Path, settings: FilesSettings) -> ParsedDocument:
    import pymupdf

    try:
        document: Any = pymupdf.open(path)  # type: ignore[no-untyped-call]
    except Exception as exc:
        raise ParseError("PDF повреждён или защищён") from exc
    if document.needs_pass:
        raise ParseError("PDF защищён паролем")
    if document.page_count > settings.max_pages:
        raise ParseError(
            f"Слишком много страниц: {document.page_count} (максимум {settings.max_pages})"
        )
    parsed = ParsedDocument(pages=[], parser="pymupdf")
    for level, title, page in document.get_toc(simple=True):
        parsed.headings.append({"level": level, "text": title, "page": page})
    with tempfile.TemporaryDirectory(prefix="ocr-") as tmp:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if len(text) < settings.ocr_min_chars_per_page:
                try:
                    image = Path(tmp) / f"page-{index}.png"
                    page.get_pixmap(dpi=300).save(image)
                    recognized = ocr_image(
                        image,
                        languages=settings.ocr_languages,
                        timeout=settings.parse_timeout_seconds,
                    ).strip()
                    if recognized:
                        text = recognized
                        parsed.ocr_pages.append(index)
                except ConversionError as exc:
                    if "OCR недоступен" not in parsed.warnings:
                        parsed.warnings.append(str(exc))
            parsed.pages.append(text)
    document.close()
    return parsed


# ------------------------------------------------------------------ DOCX


def _iter_docx_blocks(document: Any) -> Iterator[Any]:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, document)
        elif tag == "tbl":
            yield Table(child, document)


def _paragraph_breaks(paragraph: Any) -> int:
    xml = paragraph._p.xml  # python-docx не даёт API для разрывов страниц
    rendered = xml.count("w:lastRenderedPageBreak")
    explicit = len(re.findall(r'<w:br [^>]*w:type="page"', xml))
    return int(rendered) + explicit


def parse_docx(path: Path, settings: FilesSettings) -> ParsedDocument:
    import docx
    from docx.table import Table

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ParseError("DOCX повреждён или не читается") from exc
    parsed = ParsedDocument(pages=[], parser="python-docx")
    current: list[str] = []
    page = 1
    has_breaks = False
    for block in _iter_docx_blocks(document):
        if isinstance(block, Table):
            rows = [[c.text for c in row.cells] for row in block.rows]
            parsed.tables.append(
                {
                    "index": len(parsed.tables) + 1,
                    "page": page,
                    "rows": len(rows),
                    "cols": max((len(r) for r in rows), default=0),
                }
            )
            current.append(markdown_table(rows))
            continue
        breaks = _paragraph_breaks(block)
        if breaks:
            has_breaks = True
            parsed.pages.append("\n\n".join(current))
            current = []
            page += breaks
            # Пустые страницы между множественными разрывами не храним.
        text = block.text.strip()
        if not text:
            continue
        style = (block.style.name or "").lower() if block.style is not None else ""
        level = 0
        if style.startswith(("heading", "заголовок")):
            digits = re.findall(r"\d+", style)
            level = int(digits[0]) if digits else 1
        elif style == "title":
            level = 1
        if level:
            parsed.headings.append({"level": level, "text": text, "page": page})
            current.append(f"{'#' * min(level, 6)} {text}")
        elif style.startswith("list"):
            current.append(f"- {text}")
        else:
            current.append(text)
    parsed.pages.append("\n\n".join(current))
    if not has_breaks:
        parsed.pages = virtual_pages(parsed.pages[0])
        parsed.virtual_pages = True
        # Номера страниц заголовков и таблиц при условных страницах — по положению в тексте.
        _assign_virtual_pages(parsed)
    return parsed


def _assign_virtual_pages(parsed: ParsedDocument) -> None:
    for heading in parsed.headings:
        marker = f"{'#' * min(heading['level'], 6)} {heading['text']}"
        heading["page"] = next(
            (i for i, text in enumerate(parsed.pages, start=1) if marker in text), 1
        )


# ------------------------------------------------------------------ XLSX


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def parse_xlsx(path: Path, settings: FilesSettings) -> ParsedDocument:
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ParseError("XLSX повреждён или не читается") from exc
    parsed = ParsedDocument(pages=[], parser="openpyxl")
    for index, sheet in enumerate(workbook.worksheets, start=1):
        rows: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            if len(rows) > MAX_TABLE_ROWS_IN_TEXT:
                break
            values = [_cell_text(v) for v in row]
            while values and not values[-1]:
                values.pop()
            if any(values):
                rows.append(values)
        parsed.sheets.append(
            {
                "index": index,
                "name": sheet.title,
                "page": index,
                "rows": sheet.max_row,
                "cols": sheet.max_column,
                "dimensions": sheet.calculate_dimension(),
            }
        )
        parsed.headings.append({"level": 1, "text": f"Лист «{sheet.title}»", "page": index})
        table = markdown_table(rows) if rows else "_Лист пуст_"
        parsed.pages.append(f"# Лист «{sheet.title}»\n\n{table}")
    workbook.close()
    return parsed


# ------------------------------------------------------------------ PPTX


def parse_pptx(path: Path, settings: FilesSettings) -> ParsedDocument:
    from pptx import Presentation

    try:
        presentation = Presentation(str(path))
    except Exception as exc:
        raise ParseError("PPTX повреждён или не читается") from exc
    parsed = ParsedDocument(pages=[], parser="python-pptx")
    for index, slide in enumerate(presentation.slides, start=1):
        title = slide.shapes.title.text.strip() if slide.shapes.title is not None else ""
        lines = [f"# Слайд {index}" + (f". {title}" if title else "")]
        parsed.headings.append({"level": 1, "text": title or f"Слайд {index}", "page": index})
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[c.text for c in row.cells] for row in shape.table.rows]
                parsed.tables.append(
                    {
                        "index": len(parsed.tables) + 1,
                        "page": index,
                        "rows": len(rows),
                        "cols": len(rows[0]) if rows else 0,
                    }
                )
                lines.append(markdown_table(rows))
            elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs).strip()
                    if text:
                        lines.append(f"{'  ' * paragraph.level}- {text}")
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                lines.append(f"> Заметки: {notes}")
        parsed.pages.append("\n\n".join(lines))
    return parsed


# ------------------------------------------------------------------ текст


def decode_text(data: bytes) -> str:
    for bom, encoding in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ):
        if data.startswith(bom):
            return data.decode(encoding, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def parse_text(path: Path, file_type: str, settings: FilesSettings) -> ParsedDocument:
    text = decode_text(path.read_bytes()[: settings.max_text_chars * 4])
    parsed = ParsedDocument(pages=[], parser="text")
    if file_type in {"csv", "tsv"}:
        delimiter = (
            "\t"
            if file_type == "tsv"
            else (csv.Sniffer().sniff(text[:4096]).delimiter if text.strip() else ",")
        )
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        parsed.tables.append(
            {
                "index": 1,
                "page": 1,
                "rows": len(rows),
                "cols": max((len(r) for r in rows), default=0),
            }
        )
        parsed.pages = [markdown_table(rows)]
        return parsed
    if file_type in {"html", "htm"}:
        try:
            from markitdown import MarkItDown

            text = MarkItDown().convert(str(path)).text_content
            parsed.parser = "markitdown"
        except Exception as exc:
            log.warning("ingestion.markitdown_failed", error=str(exc)[:200])
    elif file_type == "json":
        try:
            text = (
                "```json\n" + json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n```"
            )
        except json.JSONDecodeError:
            text = f"```json\n{text}\n```"
    elif file_type in CODE_LANG:
        text = f"```{CODE_LANG[file_type]}\n{text}\n```"
    parsed.pages = virtual_pages(text)
    parsed.virtual_pages = len(parsed.pages) > 1
    for match in re.finditer(r"^(#{1,6}) (.+)$", text, re.MULTILINE):
        parsed.headings.append({"level": len(match.group(1)), "text": match.group(2).strip()})
    _assign_virtual_pages(parsed)
    return parsed


# ------------------------------------------------------------------ docling (опционально)


def parse_with_docling(path: Path) -> ParsedDocument:  # pragma: no cover — нужен docling и модели
    """docling: разметка страниц и таблиц (§4). Модели — локально, без сети (этап 10)."""
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(str(path))
    document = result.document
    pages: list[str] = []
    for page_no in sorted(document.pages):
        pages.append(document.export_to_markdown(page_no=page_no))
    parsed = ParsedDocument(pages=pages or [document.export_to_markdown()], parser="docling")
    for item, level in document.iterate_items():
        label = str(getattr(item, "label", ""))
        if label in {"section_header", "title"}:
            prov = getattr(item, "prov", None) or []
            page = prov[0].page_no if prov else 1
            parsed.headings.append({"level": max(level, 1), "text": item.text, "page": page})
    return parsed


# ------------------------------------------------------------------ точка входа

PARSERS = {"pdf": parse_pdf, "docx": parse_docx, "xlsx": parse_xlsx, "pptx": parse_pptx}
DOCLING_TYPES = frozenset({"pdf", "docx", "pptx", "xlsx", "html"})


def parse_file(path: Path, file_type: str, settings: FilesSettings) -> ParsedDocument:
    """Разбирает файл любого поддерживаемого типа. Бросает ParseError с понятной причиной."""
    source = path
    if file_type in LEGACY_TARGET:
        try:
            source = libreoffice_convert(
                path, LEGACY_TARGET[file_type], timeout=settings.convert_timeout_seconds
            )
        except ConversionError as exc:
            raise ParseError(str(exc)) from exc
        file_type = LEGACY_TARGET[file_type]

    if settings.docling_enabled and file_type in DOCLING_TYPES:
        try:
            return _limit(parse_with_docling(source), settings)
        except ImportError:
            log.warning("ingestion.docling_not_installed")
        except Exception as exc:
            log.warning("ingestion.docling_failed", error=str(exc)[:300])

    parser = PARSERS.get(file_type)
    parsed = parser(source, settings) if parser else parse_text(source, file_type, settings)
    return _limit(parsed, settings)


def _limit(parsed: ParsedDocument, settings: FilesSettings) -> ParsedDocument:
    total = 0
    for index, page in enumerate(parsed.pages):
        if total + len(page) > settings.max_text_chars:
            keep = settings.max_text_chars - total
            parsed.pages = [*parsed.pages[:index], *([page[:keep]] if keep > 0 else [])]
            parsed.warnings.append(
                f"Документ обрезан: обработаны первые {settings.max_text_chars} символов"
            )
            break
        total += len(page)
    return parsed
