"""Внешние программы разбора: LibreOffice (конвертация) и Tesseract (OCR), §9.3.

Запускаются только в воркере — в контейнере без доступа наружу. Каждый вызов — отдельный
процесс с тайм-аутом и временным профилем; по тайм-ауту процесс убивается целиком (группа).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess  # вызываем только фиксированные программы без shell
import tempfile
from pathlib import Path


class ConversionError(Exception):
    """Конвертация не удалась; текст — для пользователя (статус «ошибка: …»)."""


def _run(cmd: list[str], *, timeout: int, cwd: Path, env: dict[str, str] | None = None) -> str:
    process = subprocess.Popen(  # noqa: S603 — аргументы формирует код, не пользователь
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise ConversionError("превышено время обработки документа") from None
    if process.returncode != 0:
        raise ConversionError(stderr.decode(errors="replace").strip()[:300] or "ошибка конвертации")
    return stdout.decode(errors="replace")


def soffice_binary() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def libreoffice_convert(source: Path, target_ext: str, *, timeout: int) -> Path:
    """Конвертирует файл LibreOffice headless; результат — во временном каталоге."""
    binary = soffice_binary()
    if binary is None:
        raise ConversionError("LibreOffice недоступен — конвертация выполняется в воркере")
    workdir = Path(tempfile.mkdtemp(prefix="lo-"))
    profile = workdir / "profile"
    env = {
        "HOME": str(workdir),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
    }
    _run(
        [
            binary,
            f"-env:UserInstallation=file://{profile}",
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--convert-to",
            target_ext,
            "--outdir",
            str(workdir),
            str(source),
        ],
        timeout=timeout,
        cwd=workdir,
        env=env,
    )
    result = workdir / f"{source.stem}.{target_ext.split(':')[0]}"
    if not result.exists():
        raise ConversionError("LibreOffice не смог прочитать документ")
    return result


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_image(image: Path, *, languages: str, timeout: int) -> str:
    if not tesseract_available():
        raise ConversionError("OCR недоступен — распознавание выполняется в воркере")
    return _run(
        ["tesseract", str(image), "stdout", "-l", languages, "--psm", "3"],
        timeout=timeout,
        cwd=image.parent,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "OMP_THREAD_LIMIT": "1"},
    )
