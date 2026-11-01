"""Файлы пользователя: приём загрузки, доступ только владельцу, привязка к сообщению (§7.3, §15)."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from collections.abc import Sequence
from typing import BinaryIO
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import FilesSettings
from app.core.errors import AppError, NotFoundError
from app.core.storage import Storage
from app.modules.files.models import File
from app.modules.files.schemas import FileOut
from app.modules.files.sniff import Limits, UploadRejected, detect

READ_CHUNK = 1024 * 1024


def file_out(row: File) -> FileOut:
    return FileOut(
        id=row.id,
        kind=row.kind,
        filename=row.filename,
        mime=row.mime,
        file_type=row.file_type,
        size=row.size,
        parse_status=row.parse_status,
        parse_error=row.parse_error,
        pages=row.pages,
        has_preview=row.preview_key is not None or row.file_type == "pdf",
        chat_id=row.chat_id,
        message_id=row.message_id,
        created_at=row.created_at,
    )


async def get_file(db: AsyncSession, user_id: UUID, file_id: UUID) -> File:
    """Файл пользователя; чужой или удалённый — 404 (IDOR, §18.2).

    Файлы выгрузок (``export``) отдаёт только раздел выгрузок — со сроком хранения и аудитом.
    """
    row = await db.get(File, file_id)
    if row is None or row.owner_id != user_id or row.deleted_at is not None or row.kind == "export":
        raise NotFoundError("Файл не найден")
    return row


def _limits(settings: FilesSettings) -> Limits:
    return Limits(
        max_unpacked_bytes=settings.max_unpacked_mb * 1024 * 1024,
        max_ratio=settings.max_compression_ratio,
        max_entries=settings.max_archive_entries,
    )


async def _spool(upload: UploadFile, max_bytes: int) -> tuple[BinaryIO, int, str]:
    """Копирует загрузку во временный файл, считая размер и SHA-256; сверх лимита — отказ."""
    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # noqa: SIM115 — закрывает вызывающий
    digest = hashlib.sha256()
    size = 0
    while chunk := await upload.read(READ_CHUNK):
        size += len(chunk)
        if size > max_bytes:
            spool.close()
            raise UploadRejected(
                "too_large", f"Файл больше {max_bytes // (1024 * 1024)} МБ", status_code=413
            )
        digest.update(chunk)
        spool.write(chunk)
    spool.seek(0)
    return spool, size, digest.hexdigest()  # type: ignore[return-value]


async def accept_upload(
    db: AsyncSession,
    storage: Storage,
    settings: FilesSettings,
    *,
    owner_id: UUID,
    upload: UploadFile,
    kind: str = "upload",
    commit: bool = True,
) -> File:
    """Проверки §9.3 и запись оригинала; ``kind=kb_document`` — документ базы знаний."""
    filename = (upload.filename or "файл").replace("\x00", "")[-255:]
    spool, size, sha256 = await _spool(upload, settings.max_file_mb * 1024 * 1024)
    try:
        detected = detect(filename, spool, _limits(settings))
        spool.seek(0)
        data = spool.read()
    finally:
        spool.close()
    file_id = uuid.uuid4()
    # Ключ — случайный: имя файла пользователя никогда не используется как путь (§15).
    storage_key = f"{'kb' if kind == 'kb_document' else 'uploads'}/{file_id}"
    await storage.put(storage_key, data)
    row = File(
        id=file_id,
        owner_id=owner_id,
        kind=kind,
        filename=filename,
        mime=detected.mime,
        file_type=detected.file_type,
        size=size,
        sha256=sha256,
        storage_key=storage_key,
        parse_status="pending",
    )
    db.add(row)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return row


async def attach(
    db: AsyncSession,
    *,
    owner_id: UUID,
    file_ids: Sequence[UUID],
    chat_id: UUID,
    message_id: UUID,
    max_files: int,
) -> list[File]:
    """Привязывает загруженные файлы к сообщению. Отправка ждёт окончания разбора (§7.3)."""
    if len(set(file_ids)) > max_files:
        raise AppError(f"Можно приложить не больше {max_files} файлов", code="too_many_files")
    rows = []
    for file_id in dict.fromkeys(file_ids):
        row = await get_file(db, owner_id, file_id)
        if row.kind != "upload" or row.message_id is not None:
            raise AppError("Файл уже приложен к другому сообщению", code="file_attached")
        if row.parse_status != "ready":
            raise AppError(
                f"Файл «{row.filename}» ещё обрабатывается или не прочитан", code="file_not_ready"
            )
        row.chat_id = chat_id
        row.message_id = message_id
        rows.append(row)
    return rows


async def chat_files(db: AsyncSession, chat_id: UUID, *, kind: str | None = None) -> list[File]:
    stmt = select(File).where(File.chat_id == chat_id, File.deleted_at.is_(None))
    if kind:
        stmt = stmt.where(File.kind == kind)
    return list((await db.scalars(stmt.order_by(File.created_at))).all())
