# mypy: disallow-untyped-calls=False
"""Образцы файлов для тестов этапа 3: создаются в коде, бинарные фикстуры в репозитории не нужны."""

from __future__ import annotations

import io
import zipfile

NEEDLE = "Кодовое слово проекта: ЛАЗУРЬ-7"


def docx_pages(pages: int = 30, *, needle_page: int = 25) -> bytes:
    """DOCX с явными разрывами страниц, заголовками и таблицей; ``NEEDLE`` — на ``needle_page``."""
    from docx import Document
    from docx.enum.text import WD_BREAK

    document = Document()
    for page in range(1, pages + 1):
        document.add_heading(f"Раздел {page}", level=1)
        document.add_paragraph(f"Текст страницы {page}. " + "Обычный абзац документа. " * 20)
        if page == needle_page:
            document.add_paragraph(NEEDLE)
        if page == 2:
            table = document.add_table(rows=2, cols=2)
            table.cell(0, 0).text, table.cell(0, 1).text = "Показатель", "Значение"
            table.cell(1, 0).text, table.cell(1, 1).text = "Выручка", "1000"
        if page < pages:
            document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def text_pdf(lines: list[str]) -> bytes:
    import pymupdf

    document = pymupdf.open()
    for line in lines:
        page = document.new_page()
        page.insert_text((72, 72), line, fontname="helv")
    data: bytes = document.tobytes()
    document.close()
    return data


def scanned_pdf(text: str = "SCAN TEST 2026 OCR") -> bytes:
    """PDF из одной картинки без текстового слоя — как скан."""
    import pymupdf

    source = pymupdf.open()
    page = source.new_page(width=595, height=200)
    page.insert_text((40, 110), text, fontsize=36, fontname="helv")
    pixmap = page.get_pixmap(dpi=200)
    source.close()
    scan = pymupdf.open()
    target = scan.new_page(width=595, height=200)
    target.insert_image(target.rect, stream=pixmap.tobytes("png"))
    data: bytes = scan.tobytes()
    scan.close()
    return data


def xlsx_sample() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Продажи"
    sheet.append(["Месяц", "Сумма"])
    sheet.append(["Январь", 100])
    sheet.append(["Февраль", 200])
    workbook.create_sheet("Пусто")
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def pptx_sample() -> bytes:
    from pptx import Presentation

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    assert slide.shapes.title is not None
    slide.shapes.title.text = "Итоги года"
    slide.placeholders[1].text_frame.text = "Рост выручки"
    slide.notes_slide.notes_text_frame.text = "Заметка докладчика"
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def zip_bomb_docx(unpacked_mb: int = 400) -> bytes:
    """Похож на DOCX (нужные части есть), но внутри — сотни мегабайт нулей."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
        chunk = b"\0" * (1024 * 1024)
        with zf.open("word/media/zeros.bin", "w", force_zip64=True) as entry:
            for _ in range(unpacked_mb):
                entry.write(chunk)
    return buffer.getvalue()


def high_ratio_docx(unpacked_mb: int = 20) -> bytes:
    """Объём в пределах лимита, но степень сжатия подозрительная."""
    return zip_bomb_docx(unpacked_mb)
