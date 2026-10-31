"""API файлов: ``/api/files`` (§7.3, §7.7). Доступ — только владельцу."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, UploadFile

from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import DbDep, StorageDep
from app.core.errors import AppError, NotFoundError
from app.modules.auth.deps import CurrentUserDep
from app.modules.files import service
from app.modules.files.schemas import FileLimits, FileOut
from app.modules.files.sniff import ODF, OLE2, OOXML, TEXT_EXTENSIONS, UploadRejected
from app.workers.dispatch import Dispatcher

router = APIRouter(prefix="/files", tags=["files"])

# Отдаём пользовательские файлы так, чтобы браузер их не исполнял: HTML — текстом, без sniffing.
SAFE_INLINE = {"pdf": "application/pdf"}
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}


def _disposition(kind: str, filename: str) -> str:
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/limits", response_model=FileLimits, operation_id="getFileLimits")
async def limits(request: Request, _: CurrentUserDep) -> FileLimits:
    settings: Settings = request.app.state.settings
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
    settings: Settings = request.app.state.settings
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
    data = await storage.get(row.storage_key)
    if data is None:
        raise NotFoundError("Файл не найден")
    if download:
        media = row.mime
        disposition = _disposition("attachment", row.filename)
    else:
        media = SAFE_INLINE.get(row.file_type, "text/plain; charset=utf-8")
        disposition = _disposition("inline", row.filename)
    return Response(
        data, media_type=media, headers={"Content-Disposition": disposition, **SECURITY_HEADERS}
    )


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
    key = row.storage_key if row.file_type == "pdf" else row.preview_key
    data = await storage.get(key) if key else None
    if data is None:
        raise NotFoundError("Превью нет")
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": _disposition("inline", f"{row.filename}.pdf"),
            **SECURITY_HEADERS,
        },
    )


@router.delete("/{file_id}", status_code=204, operation_id="deleteFile")
async def delete(file_id: UUID, db: DbDep, current: CurrentUserDep) -> None:
    """Удалить загрузку, ещё не отправленную в сообщении (крестик на чипе файла)."""
    row = await service.get_file(db, current.id, file_id)
    if row.message_id is not None:
        raise AppError("Файл уже отправлен в сообщении", code="file_attached")
    row.deleted_at = utcnow()
    await db.commit()
