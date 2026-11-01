"""Генерация файлов по запросу модели (§9.4). Выполняется в воркере.

* Документы: Markdown → pandoc → DOCX по шаблону ``config/templates/reference.docx``; формулы LaTeX
  (``$…$``, ``\\(…\\)``) становятся нативными формулами Word. PDF — тот же DOCX через LibreOffice.
  ODT — pandoc; MD, HTML и TXT — напрямую.
* Таблицы: openpyxl — типы ячеек, жирная шапка, автофильтр, закреплённая первая строка, ширина
  колонок; формулы — строки, начинающиеся с ``=``. CSV — UTF-8 с BOM (открывается в Excel).
* Презентации: python-pptx по шаблону ``config/templates/presentation.pptx``.

Корпоративных шаблонов пока нет — поставляются нейтральные; замена файлов не требует правок кода.
"""

from __future__ import annotations

import csv
import io
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.ingestion.convert import ConversionError, libreoffice_convert, soffice_binary

DocumentFormat = Literal["docx", "pdf", "md", "html", "txt", "odt"]
PANDOC_FROM = "markdown+tex_math_dollars+tex_math_single_backslash+pipe_tables+task_lists"


class GenerationError(Exception):
    """Файл не создан; текст возвращается модели как результат инструмента."""


@dataclass(frozen=True)
class GeneratedFile:
    filename: str
    file_type: str
    mime: str
    data: bytes


MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "odt": "application/vnd.oasis.opendocument.text",
    "md": "text/markdown",
    "html": "text/html",
    "txt": "text/plain",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def safe_filename(title: str, ext: str) -> str:
    """Имя файла для пользователя: без путей и служебных символов (на диске — случайный ключ)."""
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", title)
    name = re.sub(r"\s+", " ", name).strip(" .") or "Документ"
    return f"{name[:120]}.{ext}"


# ------------------------------------------------------------------ документы


class DocumentSpec(BaseModel):
    format: DocumentFormat
    title: str = Field(min_length=1, max_length=200)
    markdown: str = Field(min_length=1)


def _pandoc(
    markdown: str, to: str, *, reference: Path | None, standalone: bool, title: str
) -> bytes:
    import pypandoc

    with tempfile.TemporaryDirectory(prefix="pandoc-") as tmp:
        target = Path(tmp) / f"out.{to}"
        args = ["--standalone"] if standalone else []
        args += ["--metadata", f"title={title}"] if standalone else []
        if reference is not None and reference.exists():
            args.append(f"--reference-doc={reference}")
        try:
            pypandoc.convert_text(
                markdown,
                to,
                format=PANDOC_FROM,
                outputfile=str(target),
                extra_args=args,
                sandbox=True,
            )
        except (RuntimeError, OSError) as exc:
            raise GenerationError(f"pandoc: {str(exc)[:300]}") from exc
        return target.read_bytes()


def create_document(spec: DocumentSpec, *, templates: Path, timeout: int) -> GeneratedFile:
    fmt = spec.format
    text = spec.markdown
    if fmt in {"md", "txt"}:
        return GeneratedFile(safe_filename(spec.title, fmt), fmt, MIME[fmt], text.encode("utf-8"))
    if fmt == "html":
        data = _pandoc(text, "html", reference=None, standalone=True, title=spec.title)
        return GeneratedFile(safe_filename(spec.title, "html"), "html", MIME["html"], data)
    if fmt == "odt":
        data = _pandoc(text, "odt", reference=None, standalone=False, title=spec.title)
        return GeneratedFile(safe_filename(spec.title, "odt"), "odt", MIME["odt"], data)
    docx = _pandoc(
        text, "docx", reference=templates / "reference.docx", standalone=False, title=spec.title
    )
    if fmt == "docx":
        return GeneratedFile(safe_filename(spec.title, "docx"), "docx", MIME["docx"], docx)
    pdf = convert_bytes(docx, "docx", "pdf", timeout=timeout)
    return GeneratedFile(safe_filename(spec.title, "pdf"), "pdf", MIME["pdf"], pdf)


# ------------------------------------------------------------------ таблицы


class ColumnSpec(BaseModel):
    header: str = Field(min_length=1, max_length=200)
    type: Literal["text", "number", "integer", "date", "percent", "currency"] = "text"
    format: str | None = Field(None, description="Числовой формат Excel, например «# ##0,00».")


class SheetSpec(BaseModel):
    name: str = Field(min_length=1, max_length=31)
    columns: list[ColumnSpec] = Field(min_length=1, max_length=200)
    rows: list[list[Any]] = Field(default_factory=list, max_length=100_000)


class SpreadsheetSpec(BaseModel):
    format: Literal["xlsx", "csv"] = "xlsx"
    title: str = Field(min_length=1, max_length=200)
    sheets: list[SheetSpec] = Field(min_length=1, max_length=50)


NUMBER_FORMATS = {
    "number": "#,##0.00",
    "integer": "0",
    "date": "DD.MM.YYYY",
    "percent": "0.00%",
    "currency": "#,##0.00 [$₽-419]",
}


def _cell_value(value: Any, column: ColumnSpec) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.startswith("="):
        return value  # формула
    try:
        if column.type in {"number", "percent", "currency"}:
            return float(str(value).replace(" ", "").replace(",", "."))
        if column.type == "integer":
            return int(float(str(value).replace(" ", "").replace(",", ".")))
        if column.type == "date" and isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
    except ValueError:
        return value
    return value


def create_spreadsheet(spec: SpreadsheetSpec) -> GeneratedFile:
    if spec.format == "csv":
        sheet = spec.sheets[0]
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow([c.header for c in sheet.columns])
        writer.writerows(sheet.rows)
        data = ("﻿" + buffer.getvalue()).encode("utf-8")
        return GeneratedFile(safe_filename(spec.title, "csv"), "csv", MIME["csv"], data)

    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for sheet_spec in spec.sheets:
        sheet = workbook.create_sheet(re.sub(r"[\[\]:*?/\\]", " ", sheet_spec.name)[:31])
        sheet.append([c.header for c in sheet_spec.columns])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in sheet_spec.rows:
            sheet.append([_cell_value(v, c) for v, c in zip(row, sheet_spec.columns, strict=False)])
        for index, column in enumerate(sheet_spec.columns, start=1):
            letter = get_column_letter(index)
            number_format = column.format or NUMBER_FORMATS.get(column.type)
            if number_format:
                for (cell,) in sheet.iter_rows(min_row=2, min_col=index, max_col=index):
                    cell.number_format = number_format
            values = [
                column.header,
                *(str(r[index - 1]) for r in sheet_spec.rows if len(r) >= index),
            ]
            sheet.column_dimensions[letter].width = min(
                60, max(10, max(len(v) for v in values) + 2)
            )
        sheet.freeze_panes = "A2"
        last = get_column_letter(len(sheet_spec.columns))
        sheet.auto_filter.ref = f"A1:{last}{max(1, len(sheet_spec.rows) + 1)}"
    buffer_bytes = io.BytesIO()
    workbook.save(buffer_bytes)
    return GeneratedFile(
        safe_filename(spec.title, "xlsx"), "xlsx", MIME["xlsx"], buffer_bytes.getvalue()
    )


# ------------------------------------------------------------------ презентации


class SlideSpec(BaseModel):
    layout: Literal["title", "content", "section"] = "content"
    title: str = Field(max_length=300)
    bullets: list[str] = Field(default_factory=list, max_length=30)
    notes: str | None = None


class PresentationSpec(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slides: list[SlideSpec] = Field(min_length=1, max_length=100)


LAYOUTS = {"title": 0, "content": 1, "section": 2}


def create_presentation(spec: PresentationSpec, *, templates: Path) -> GeneratedFile:
    from pptx import Presentation

    template = templates / "presentation.pptx"
    presentation = Presentation(str(template)) if template.exists() else Presentation()
    for slide_spec in spec.slides:
        layouts = presentation.slide_layouts
        layout = layouts[min(LAYOUTS[slide_spec.layout], len(layouts) - 1)]
        slide = presentation.slides.add_slide(layout)
        if slide.shapes.title is not None:
            slide.shapes.title.text = slide_spec.title
        body = next(
            (p for p in slide.placeholders if p.placeholder_format.idx != 0 and p.has_text_frame),
            None,
        )
        if body is not None and slide_spec.bullets:
            frame = body.text_frame
            frame.text = slide_spec.bullets[0]
            for bullet in slide_spec.bullets[1:]:
                frame.add_paragraph().text = bullet
        if slide_spec.notes:
            slide.notes_slide.notes_text_frame.text = slide_spec.notes
    buffer = io.BytesIO()
    presentation.save(buffer)
    return GeneratedFile(safe_filename(spec.title, "pptx"), "pptx", MIME["pptx"], buffer.getvalue())


# ------------------------------------------------------------------ конвертация и превью


def convert_bytes(data: bytes, source_ext: str, target_ext: str, *, timeout: int) -> bytes:
    with tempfile.TemporaryDirectory(prefix="gen-") as tmp:
        source = Path(tmp) / f"document.{source_ext}"
        source.write_bytes(data)
        try:
            return libreoffice_convert(source, target_ext, timeout=timeout).read_bytes()
        except ConversionError as exc:
            raise GenerationError(str(exc)) from exc


PREVIEWABLE = frozenset({"docx", "xlsx", "pptx", "odt", "ods", "odp", "doc", "xls", "ppt", "rtf"})


def preview_pdf(data: bytes, file_type: str, *, timeout: int) -> bytes | None:
    """PDF-превью Office-файла (§7.7); None — LibreOffice недоступен или файл не конвертируется."""
    if file_type not in PREVIEWABLE or soffice_binary() is None:
        return None
    try:
        return convert_bytes(data, file_type, "pdf", timeout=timeout)
    except GenerationError:
        return None
