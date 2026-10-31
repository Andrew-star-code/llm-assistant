"""Файлы (этап 3): определение типа, zip-бомбы, разбор форматов, генерация DOCX/XLSX/PPTX/CSV."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.core.config import FilesSettings
from app.modules.files.generate import (
    DocumentSpec,
    GenerationError,
    PresentationSpec,
    SpreadsheetSpec,
    create_document,
    create_presentation,
    create_spreadsheet,
    preview_pdf,
    safe_filename,
)
from app.modules.files.sniff import Limits, UploadRejected, detect
from app.modules.ingestion.convert import soffice_binary, tesseract_available
from app.modules.ingestion.parsers import ParsedDocument, ParseError, parse_file, split_pages
from tests import samples

LIMITS = Limits(max_unpacked_bytes=300 * 1024 * 1024, max_ratio=100, max_entries=5000)
TEMPLATES = Path(__file__).resolve().parents[3] / "config" / "templates"

requires_soffice = pytest.mark.skipif(soffice_binary() is None, reason="нужен LibreOffice")
requires_tesseract = pytest.mark.skipif(not tesseract_available(), reason="нужен Tesseract")


def _detect(name: str, data: bytes) -> str:
    return detect(name, io.BytesIO(data), LIMITS).file_type


# ------------------------------------------------------------------ определение типа


def test_detect_by_signature() -> None:
    assert _detect("отчёт.docx", samples.docx_pages(2)) == "docx"
    assert _detect("a.xlsx", samples.xlsx_sample()) == "xlsx"
    assert _detect("a.pptx", samples.pptx_sample()) == "pptx"
    assert _detect("a.PDF", samples.text_pdf(["x"])) == "pdf"
    assert _detect("notes.md", "# Заголовок".encode()) == "md"
    assert _detect("data.csv", "а;б\n1;2".encode("cp1251")) == "csv"
    assert _detect("Dockerfile", b"FROM python:3.12") == "dockerfile"


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("empty.txt", b"", "empty"),
        ("virus.pdf", b"MZ\x90\x00binary", "type_mismatch"),
        ("fake.docx", b"%PDF-1.7 ...", "type_mismatch"),
        ("photo.png", b"\x89PNG\r\n\x1a\n", "unsupported"),
        ("program.exe", b"MZ\x90\x00", "unsupported"),
        ("archive.zip", b"PK\x03\x04rest", "unsupported"),
        ("broken.docx", b"PK\x03\x04not a zip", "broken_archive"),
        ("binary.txt", b"\x00\x01\x02\x03", "type_mismatch"),
    ],
)
def test_detect_rejects(name: str, data: bytes, code: str) -> None:
    with pytest.raises(UploadRejected) as exc:
        _detect(name, data)
    assert exc.value.code == code
    assert exc.value.message  # понятный текст для пользователя


def test_docx_with_wrong_parts_is_mismatch() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(UploadRejected) as exc:
        _detect("table.docx", buffer.getvalue())
    assert exc.value.code == "type_mismatch"


def test_zip_bomb_by_unpacked_size() -> None:
    with pytest.raises(UploadRejected) as exc:
        _detect("bomb.docx", samples.zip_bomb_docx(400))
    assert exc.value.code == "zip_bomb" and exc.value.status_code == 422


def test_zip_bomb_by_ratio() -> None:
    with pytest.raises(UploadRejected) as exc:
        _detect("bomb.docx", samples.high_ratio_docx(20))
    assert exc.value.code == "zip_bomb"
    assert "сжатия" in exc.value.message


def test_too_many_entries() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
        for i in range(20):
            zf.writestr(f"word/x{i}.xml", "x")
    limits = Limits(max_unpacked_bytes=10**9, max_ratio=100, max_entries=10)
    with pytest.raises(UploadRejected) as exc:
        detect("many.docx", io.BytesIO(buffer.getvalue()), limits)
    assert exc.value.code == "zip_bomb"


# ------------------------------------------------------------------ разбор


def _parse(tmp_path: Path, name: str, data: bytes, **settings: object) -> ParsedDocument:
    path = tmp_path / name
    path.write_bytes(data)
    return parse_file(path, name.rsplit(".", 1)[-1], FilesSettings.model_validate(settings))


def test_parse_docx_pages_headings_tables(tmp_path: Path) -> None:
    parsed = _parse(tmp_path, "a.docx", samples.docx_pages(30, needle_page=25))
    assert len(parsed.pages) == 30
    assert samples.NEEDLE in parsed.pages[24]
    outline = parsed.outline()
    assert outline["headings"][0] == {"level": 1, "text": "Раздел 1", "page": 1}
    assert outline["tables"][0]["page"] == 2
    markdown = parsed.markdown()
    assert split_pages(markdown)[24].count(samples.NEEDLE) == 1
    assert "| Показатель | Значение |" in markdown


def test_parse_xlsx_sheet_per_page(tmp_path: Path) -> None:
    parsed = _parse(tmp_path, "a.xlsx", samples.xlsx_sample())
    assert len(parsed.pages) == 2
    assert "| Январь | 100 |" in parsed.pages[0]
    assert parsed.outline()["sheets"][0]["name"] == "Продажи"


def test_parse_pptx_slides_and_notes(tmp_path: Path) -> None:
    parsed = _parse(tmp_path, "a.pptx", samples.pptx_sample())
    [slide] = parsed.pages
    assert "Итоги года" in slide and "Рост выручки" in slide and "Заметка докладчика" in slide


def test_parse_pdf_text_layer(tmp_path: Path) -> None:
    parsed = _parse(tmp_path, "a.pdf", samples.text_pdf(["First page text", "Second page"]))
    assert [p.strip() for p in parsed.pages] == ["First page text", "Second page"]
    assert parsed.parser == "pymupdf"


def test_parse_csv_and_cp1251_text(tmp_path: Path) -> None:
    parsed = _parse(tmp_path, "a.csv", "Имя;Сумма\nИванов;10\n".encode("cp1251"))
    assert "| Иванов | 10 |" in parsed.pages[0]
    long = _parse(tmp_path, "b.txt", ("строка текста\n" * 1000).encode())
    assert len(long.pages) > 1


def test_parse_limits(tmp_path: Path) -> None:
    with pytest.raises(ParseError, match="страниц"):
        _parse(tmp_path, "a.pdf", samples.text_pdf(["1", "2", "3"]), max_pages=2)
    parsed = _parse(tmp_path, "c.txt", ("x" * 5000).encode(), max_text_chars=1000)
    assert sum(len(p) for p in parsed.pages) <= 1000
    assert parsed.warnings


def test_broken_pdf_is_parse_error(tmp_path: Path) -> None:
    with pytest.raises(ParseError):
        _parse(tmp_path, "a.pdf", b"%PDF-1.7\nnot really a pdf")


@requires_tesseract
def test_scanned_pdf_ocr(tmp_path: Path) -> None:
    parsed = _parse(tmp_path, "scan.pdf", samples.scanned_pdf("SCAN TEST 2026 OCR"))
    assert parsed.ocr_pages == [1]
    assert "SCAN TEST 2026" in parsed.pages[0]


@requires_soffice
def test_legacy_doc_via_libreoffice(tmp_path: Path) -> None:
    from app.modules.ingestion.convert import libreoffice_convert

    source = tmp_path / "src.docx"
    source.write_bytes(samples.docx_pages(2, needle_page=2))
    legacy = libreoffice_convert(source, "doc", timeout=120)
    parsed = _parse(tmp_path, "old.doc", legacy.read_bytes())
    assert samples.NEEDLE in "\n".join(parsed.pages)


def test_chunks_have_document_and_page_prefix(tmp_path: Path) -> None:
    from app.core.config import ChunkingSettings
    from app.modules.ingestion.chunking import chunk_pages
    from app.modules.llm.tokens import TokenCounter

    count = TokenCounter(None).count
    parsed = _parse(tmp_path, "a.docx", samples.docx_pages(30, needle_page=25))
    chunks = chunk_pages(parsed.pages, title="Отчёт", settings=ChunkingSettings(), count=count)
    assert chunks[0].text.startswith("Документ: Отчёт\nРаздел: Раздел 1\n")
    assert all(count(c.text) <= ChunkingSettings().max_tokens for c in chunks)
    with_needle = [c for c in chunks if samples.NEEDLE in c.body]
    assert with_needle and with_needle[0].page_from <= 25 <= with_needle[0].page_to
    assert [c.index for c in chunks] == list(range(len(chunks)))


# ------------------------------------------------------------------ генерация


def test_spreadsheet_types_formulas_and_style() -> None:
    from openpyxl import load_workbook

    spec = SpreadsheetSpec.model_validate(
        {
            "title": "Продажи: Q1/Q2",
            "sheets": [
                {
                    "name": "Лист",
                    "columns": [
                        {"header": "Месяц"},
                        {"header": "Сумма", "type": "currency"},
                        {"header": "Дата", "type": "date"},
                    ],
                    "rows": [["Январь", "1 200,50", "2026-01-31"], ["Итого", "=SUM(B2:B2)", ""]],
                }
            ],
        }
    )
    generated = create_spreadsheet(spec)
    assert generated.filename == "Продажи Q1 Q2.xlsx"
    sheet = load_workbook(io.BytesIO(generated.data)).active
    assert sheet is not None
    assert sheet["A1"].font.bold and sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:C3"
    assert sheet["B2"].value == 1200.5 and "₽" in sheet["B2"].number_format
    assert sheet["B3"].value == "=SUM(B2:B2)"
    assert sheet["C2"].number_format == "DD.MM.YYYY"


def test_csv_has_bom_and_semicolons() -> None:
    spec = SpreadsheetSpec.model_validate(
        {
            "format": "csv",
            "title": "t",
            "sheets": [{"name": "s", "columns": [{"header": "А"}], "rows": [["б"]]}],
        }
    )
    data = create_spreadsheet(spec).data
    assert data.startswith("﻿".encode()) and data.decode("utf-8-sig") == "А\r\nб\r\n"


def test_docx_has_native_word_formulas() -> None:
    spec = DocumentSpec(
        format="docx",
        title="Формулы",
        markdown="# Заголовок\n\nСтрочная $E = mc^2$ и блочная:\n\n$$\\frac{a}{b}$$\n",
    )
    generated = create_document(spec, templates=TEMPLATES, timeout=60)
    with zipfile.ZipFile(io.BytesIO(generated.data)) as zf:
        xml = zf.read("word/document.xml").decode()
    assert "<m:oMath" in xml  # OMML — нативные формулы Word
    assert "Заголовок" in xml and generated.file_type == "docx"


def test_markdown_and_txt_documents() -> None:
    spec = DocumentSpec(format="md", title="../../etc/passwd", markdown="# x")
    generated = create_document(spec, templates=TEMPLATES, timeout=60)
    assert generated.filename == "etc passwd.md" and generated.data == b"# x"


def test_presentation_from_template() -> None:
    from pptx import Presentation

    spec = PresentationSpec.model_validate(
        {
            "title": "План",
            "slides": [
                {"layout": "title", "title": "План", "bullets": ["Отдел"]},
                {"title": "Этапы", "bullets": ["Анализ", "Запуск"], "notes": "Говорить кратко"},
            ],
        }
    )
    generated = create_presentation(spec, templates=TEMPLATES)
    slides = list(Presentation(io.BytesIO(generated.data)).slides)
    assert len(slides) == 2
    assert slides[1].notes_slide.notes_text_frame.text == "Говорить кратко"


def test_safe_filename() -> None:
    assert safe_filename('a/b\\c:*?"<>|', "docx") == "a b c.docx"
    assert safe_filename("   ", "pdf") == "Документ.pdf"


@requires_soffice
def test_pdf_document_and_preview() -> None:
    spec = DocumentSpec(format="pdf", title="Отчёт", markdown="# Отчёт\n\nТекст.")
    generated = create_document(spec, templates=TEMPLATES, timeout=120)
    assert generated.data.startswith(b"%PDF-")
    xlsx = create_spreadsheet(
        SpreadsheetSpec.model_validate(
            {"title": "t", "sheets": [{"name": "s", "columns": [{"header": "A"}], "rows": [[1]]}]}
        )
    )
    preview = preview_pdf(xlsx.data, "xlsx", timeout=120)
    assert preview is not None and preview.startswith(b"%PDF-")


def test_preview_skipped_for_text_formats() -> None:
    assert preview_pdf(b"text", "md", timeout=1) is None


def test_generation_error_is_raised_for_bad_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.files import generate

    monkeypatch.setattr(generate, "libreoffice_convert", _raise_conversion)
    with pytest.raises(GenerationError):
        generate.convert_bytes(b"x", "docx", "pdf", timeout=1)


def _raise_conversion(*_: object, **__: object) -> Path:
    from app.modules.ingestion.convert import ConversionError

    raise ConversionError("LibreOffice недоступен")
