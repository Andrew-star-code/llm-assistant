"""Проверка загружаемых файлов (§7.3, §9.3, §15): тип — по сигнатуре содержимого, а не по
расширению; для zip-форматов (DOCX, XLSX, PPTX, ODF) — лимиты распакованного объёма, коэффициента
сжатия и числа записей (защита от zip-бомб). Макросы не исполняются никогда: файлы только читаются.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

TEXT_EXTENSIONS = frozenset(
    {
        "txt",
        "md",
        "markdown",
        "csv",
        "tsv",
        "json",
        "xml",
        "yaml",
        "yml",
        "html",
        "htm",
        "log",
        "ini",
        "cfg",
        "conf",
        "toml",
        "sql",
        # исходный код
        "py",
        "js",
        "mjs",
        "ts",
        "tsx",
        "jsx",
        "java",
        "kt",
        "cs",
        "go",
        "rs",
        "c",
        "h",
        "cpp",
        "hpp",
        "cc",
        "php",
        "rb",
        "sh",
        "bash",
        "ps1",
        "bat",
        "css",
        "scss",
        "swift",
        "r",
        "bsl",
        "vue",
        "dockerfile",
        "gradle",
        "properties",
        "tex",
    }
)
OOXML = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
}
ODF = {
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
}
OLE2 = frozenset({"doc", "xls", "ppt"})
MIME = {
    "pdf": "application/pdf",
    "rtf": "application/rtf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    "ppt": "application/vnd.ms-powerpoint",
    "csv": "text/csv",
    "md": "text/markdown",
    "html": "text/html",
    "htm": "text/html",
    "json": "application/json",
    "xml": "application/xml",
    **ODF,
}

OLE2_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
SUPPORTED_HINT = (
    "txt, md, csv, json, xml, yaml, html, исходный код, DOC(X), XLS(X), PPT(X), RTF, "
    "ODT/ODS/ODP, PDF"
)


class UploadRejected(Exception):  # noqa: N818 — это результат проверки, а не сбой
    """Файл не принят; ``message`` показывается пользователю в чипе файла (§7.3)."""

    def __init__(self, code: str, message: str, status_code: int = 415) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Limits:
    max_unpacked_bytes: int
    max_ratio: int
    max_entries: int


@dataclass(frozen=True)
class Detected:
    file_type: str
    mime: str


def extension_of(filename: str) -> str:
    name = Path(filename).name.lower()
    if name == "dockerfile":
        return "dockerfile"
    return name.rsplit(".", 1)[-1] if "." in name else ""


def _looks_like_text(head: bytes) -> bool:
    if head.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        return True
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        # Обрезанный посередине многобайтный символ в конце буфера — не повод отказывать.
        if exc.start >= len(head) - 4:
            return True
    try:
        head.decode("cp1251")
        return True
    except UnicodeDecodeError:
        return False


def check_zip(stream: BinaryIO, limits: Limits) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(stream)
    except (zipfile.BadZipFile, OSError) as exc:
        raise UploadRejected("broken_archive", "Файл повреждён: архив не читается") from exc
    entries = archive.infolist()
    if len(entries) > limits.max_entries:
        raise UploadRejected("zip_bomb", "Файл отклонён: слишком много вложенных файлов", 422)
    total = 0
    for info in entries:
        if info.flag_bits & 0x1:
            raise UploadRejected("encrypted", "Зашифрованные документы не поддерживаются", 422)
        total += info.file_size
        if total > limits.max_unpacked_bytes:
            raise UploadRejected(
                "zip_bomb", "Файл отклонён: распакованный объём превышает допустимый", 422
            )
        if (
            info.compress_size
            and info.file_size > 1_000_000
            and info.file_size / info.compress_size > limits.max_ratio
        ):
            raise UploadRejected(
                "zip_bomb", "Файл отклонён: подозрительно высокая степень сжатия", 422
            )
    return archive


def detect(filename: str, stream: BinaryIO, limits: Limits) -> Detected:
    """Определяет тип файла по содержимому и сверяет с расширением; бросает UploadRejected."""
    ext = extension_of(filename)
    stream.seek(0)
    head = stream.read(65536)
    stream.seek(0)
    if not head:
        raise UploadRejected("empty", "Файл пустой", 422)

    def mismatch() -> UploadRejected:
        return UploadRejected("type_mismatch", "Содержимое файла не соответствует его расширению")

    if head.startswith(b"%PDF-"):
        if ext != "pdf":
            raise mismatch()
        return Detected("pdf", MIME["pdf"])
    if head.startswith(b"{\\rtf"):
        if ext != "rtf":
            raise mismatch()
        return Detected("rtf", MIME["rtf"])
    if head.startswith(OLE2_MAGIC):
        if ext not in OLE2:
            raise mismatch()
        return Detected(ext, MIME[ext])
    if head.startswith(b"PK\x03\x04"):
        if ext not in OOXML and ext not in ODF:
            raise UploadRejected(
                "unsupported", f"Архивы не поддерживаются. Поддерживаются: {SUPPORTED_HINT}"
            )
        archive = check_zip(stream, limits)
        names = set(archive.namelist())
        stream.seek(0)
        if ext in OOXML:
            if "[Content_Types].xml" not in names or OOXML[ext] not in names:
                raise mismatch()
            return Detected(ext, MIME[ext])
        if "mimetype" not in names or archive.read("mimetype").decode(errors="ignore") != ODF[ext]:
            raise mismatch()
        return Detected(ext, MIME[ext])
    if ext in TEXT_EXTENSIONS and _looks_like_text(head):
        return Detected(ext if ext != "markdown" else "md", MIME.get(ext, "text/plain"))
    if ext in TEXT_EXTENSIONS or ext in OOXML or ext in ODF or ext in OLE2 or ext in {"pdf", "rtf"}:
        raise mismatch()
    raise UploadRejected(
        "unsupported", f"Формат файла не поддерживается. Поддерживаются: {SUPPORTED_HINT}"
    )
