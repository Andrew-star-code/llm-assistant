"""API файлов: ``/api/files`` (§7.3, §7.7). Доступ — только владельцу."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, UploadFile

from app.core.db import utcnow
from app.core.deps import DbDep, StorageDep
from app.core.errors import AppError, NotFoundError
from app.core.storage import Storage
from app.modules.admin import app_settings
from app.modules.auth.deps import CurrentUserDep
from app.modules.files import service
from app.modules.files.models import File
from app.modules.files.schemas import FileLimits, FileOut
from app.modules.files.sniff import ODF, OLE2, OOXML, TEXT_EXTENSIONS, UploadRejected
from app.workers.dispatch import Dispatcher

router = APIRouter(prefix="/files", tags=["files"])

# Отдаём пользовательские файлы так, чтобы браузер их не исполнял: HTML — текстом, без sniffing.
# CSP sandbox — только для показа в браузере: на ответе-вложении Chromium из-за него теряет имя
# файла при скачивании, а исполнять вложение браузер и так не станет.
SAFE_INLINE = {"pdf": "application/pdf"}
NOSNIFF = {"X-Content-Type-Options": "nosniff"}
INLINE_HEADERS = {**NOSNIFF, "Content-Security-Policy": "sandbox"}


def _disposition(kind: str, filename: str) -> str:
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


async def content_response(row: File, storage: Storage, *, download: bool) -> Response:
    """Отдача оригинала; права проверяет вызывающий код (файлы чата, документы БЗ)."""
    data = await storage.get(row.storage_key)
    if data is None:
        raise NotFoundError("Файл не найден")
    if download:
        headers = {"Content-Disposition": _disposition("attachment", row.filename), **NOSNIFF}
        return Response(data, media_type=row.mime, headers=headers)
    media = SAFE_INLINE.get(row.file_type, "text/plain; charset=utf-8")
    headers = {"Content-Disposition": _disposition("inline", row.filename), **INLINE_HEADERS}
    return Response(data, media_type=media, headers=headers)


async def preview_response(row: File, storage: Storage) -> Response:
    key = row.storage_key if row.file_type == "pdf" else row.preview_key
    data = await storage.get(key) if key else None
    if data is None:
        raise NotFoundError("Превью нет")
    headers = {
        "Content-Disposition": _disposition("inline", f"{row.filename}.pdf"),
        **INLINE_HEADERS,
    }
    return Response(data, media_type="application/pdf", headers=headers)


@router.get("/limits", response_model=FileLimits, operation_id="getFileLimits")
async def limits(request: Request, db: DbDep, _: CurrentUserDep) -> FileLimits:
    settings = await app_settings.effective(db, request.app.state.settings)
    accept = sorted(TEXT_EXTENSIONS | set(OOXML) | set(ODF) | OLE2 | {"pdf", "rtf"})
    return FileLimits(
        max_file_mb=settings.files.max_file_mb,
        max_files_per_message=settings.files.max_files_per_message,
        accept=accept,
    )


@router.post("", response_model=FileOut, status_code=201, operation_id="uploadFile")
async def upload(
    file: UploadFile, request: Request, db: DbDep, storage: StorageDep, current: CurrentUserDep
) -> FileOut:
    """Загрузка вложения: проверки (§9.3) и разбор в воркере; статус — ``GET /api/files/{id}``."""
    settings = await app_settings.effective(db, request.app.state.settings)
    # TODO(stage-8): лимит uploads в день (§12.1).
    try:
        row = await service.accept_upload(
            db, storage, settings.files, owner_id=current.id, upload=file
        )
    except UploadRejected as exc:
        raise AppError(exc.message, code=exc.code, status_code=exc.status_code) from exc
    dispatcher: Dispatcher = request.app.state.dispatcher
    await dispatcher.parse(str(row.id))
    await db.refresh(row)
    return service.file_out(row)


@router.get("/{file_id}", response_model=FileOut, operation_id="getFile")
async def get_file(file_id: UUID, db: DbDep, current: CurrentUserDep) -> FileOut:
    return service.file_out(await service.get_file(db, current.id, file_id))


@router.get(
    "/{file_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadFile",
)
async def content(
    file_id: UUID,
    db: DbDep,
    storage: StorageDep,
    current: CurrentUserDep,
    download: Annotated[bool, Query()] = True,
) -> Response:
    """Оригинал. ``download=false`` — показать в браузере (только PDF и текст как text/plain)."""
    row = await service.get_file(db, current.id, file_id)
    return await content_response(row, storage, download=download)


@router.get(
    "/{file_id}/preview",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}, 404: {"description": "Превью нет"}},
    operation_id="previewFile",
)
async def preview(
    file_id: UUID, db: DbDep, storage: StorageDep, current: CurrentUserDep
) -> Response:
    """PDF-превью (§7.7): PDF — сам файл, Office — PDF, подготовленный воркером в LibreOffice."""
    row = await service.get_file(db, current.id, file_id)
    return await preview_response(row, storage)


@router.delete("/{file_id}", status_code=204, operation_id="deleteFile")
async def delete(file_id: UUID, db: DbDep, current: CurrentUserDep) -> None:
    """Удалить загрузку, ещё не отправленную в сообщении (крестик на чипе файла)."""
    row = await service.get_file(db, current.id, file_id)
    if row.message_id is not None:
        raise AppError("Файл уже отправлен в сообщении", code="file_attached")
    row.deleted_at = utcnow()
    await db.commit()
