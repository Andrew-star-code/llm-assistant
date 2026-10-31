"""``python -m app.cli worker check`` — самопроверка образа воркера (§9.3, §9.4).

Проверяет то, чего нет в образе api: pandoc (DOCX с формулами Word), LibreOffice (PDF и превью),
Tesseract с нужными языками (OCR скана). Запуск: ``make test-worker`` или в контейнере воркера.
"""

from __future__ import annotations

import io
import shutil
import subprocess  # фиксированная программа без shell
import tempfile
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import Settings


def _pandoc_docx(settings: Settings) -> str:
    from app.modules.files.generate import DocumentSpec, create_document

    spec = DocumentSpec(format="docx", title="Проверка", markdown="# Проверка\n\n$E = mc^2$")
    data = create_document(spec, templates=settings.config_dir / "templates", timeout=60).data
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if "<m:oMath" not in zf.read("word/document.xml").decode():
            raise RuntimeError("в DOCX нет формулы Word")
    return f"DOCX {len(data) // 1024} КБ, формула Word есть"


def _libreoffice_pdf(settings: Settings) -> str:
    from app.modules.files.generate import (
        SpreadsheetSpec,
        create_spreadsheet,
        preview_pdf,
    )

    spec = SpreadsheetSpec.model_validate(
        {"title": "t", "sheets": [{"name": "s", "columns": [{"header": "A"}], "rows": [[1]]}]}
    )
    pdf = preview_pdf(
        create_spreadsheet(spec).data, "xlsx", timeout=settings.files.convert_timeout_seconds
    )
    if pdf is None or not pdf.startswith(b"%PDF-"):
        raise RuntimeError("LibreOffice не найден или не сделал PDF")
    return f"превью XLSX → PDF {len(pdf) // 1024} КБ"


def _tesseract(settings: Settings) -> str:
    import pymupdf

    from app.modules.ingestion.convert import ocr_image

    binary = shutil.which("tesseract")
    if binary is None:
        raise RuntimeError("tesseract не найден")
    languages = subprocess.run(  # noqa: S603 — путь из shutil.which, аргументы фиксированы
        [binary, "--list-langs"], capture_output=True, text=True, check=True, timeout=30
    ).stdout.split()
    missing = [lang for lang in settings.files.ocr_languages.split("+") if lang not in languages]
    if missing:
        raise RuntimeError(f"нет языков OCR: {', '.join(missing)}")
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page: Any = document.new_page(width=400, height=120)
    page.insert_text((20, 70), "OCR 2026", fontsize=40, fontname="helv")
    with tempfile.TemporaryDirectory(prefix="ocr-check-") as tmp:
        image = Path(tmp) / "page.png"
        page.get_pixmap(dpi=200).save(image)
        text = ocr_image(image, languages=settings.files.ocr_languages, timeout=60)
    if "2026" not in text:
        raise RuntimeError(f"распознано не то: {text.strip()[:50]!r}")
    return f"языки {settings.files.ocr_languages}, распознано «{text.strip()}»"


CHECKS: dict[str, Callable[[Settings], str]] = {
    "pandoc": _pandoc_docx,
    "libreoffice": _libreoffice_pdf,
    "tesseract": _tesseract,
}


def cmd_worker_check(settings: Settings) -> int:
    failed = 0
    for name, check in CHECKS.items():
        started = time.monotonic()
        try:
            detail = check(settings)
        except Exception as exc:
            failed += 1
            print(f"✗ {name}: {exc}")
            continue
        print(f"✓ {name}: {detail} ({time.monotonic() - started:.1f} с)")
    print("Воркер готов" if not failed else f"Проверок не пройдено: {failed}")
    return 1 if failed else 0
