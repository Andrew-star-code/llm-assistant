"""API баз знаний для пользователя: «Моя база знаний» (§7.8) и просмотр источников (§10.5)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, UploadFile

from app.core.config import Settings
from app.core.deps import DbDep, StorageDep
from app.core.errors import AppError
from app.modules.auth.deps import CurrentUser, CurrentUserDep
from app.modules.files.router import content_response, preview_response
from app.modules.files.sniff import UploadRejected
from app.modules.kb import service
from app.modules.kb.schemas import DocumentOut, PersonalKbOut
from app.workers.dispatch import Dispatcher

router = APIRouter(prefix="/kb", tags=["kb"])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _dispatcher(request: Request) -> Dispatcher:
    dispatcher: Dispatcher = request.app.state.dispatcher
    return dispatcher


def _role_ids(current: CurrentUser) -> list[UUID]:
    return [r.role.id for r in current.roles]


@router.get("/personal", response_model=PersonalKbOut, operation_id="getPersonalKb")
async def personal(request: Request, db: DbDep, current: CurrentUserDep) -> PersonalKbOut:
    settings = _settings(request)
    kb = await service.personal_base(db, current.id, settings)
    rows = await service.documents(db, kb.id)
    return PersonalKbOut(
        id=kb.id,
        name=kb.name,
        quota=await service.quota(db, kb, settings),
        documents=[service.document_out(d, f) for d, f in rows],
    )


@router.post(
    "/personal/documents",
    response_model=DocumentOut,
    status_code=201,
    operation_id="uploadPersonalDocument",
)
async def upload_personal(
    file: UploadFile, request: Request, db: DbDep, storage: StorageDep, current: CurrentUserDep
) -> DocumentOut:
    """Документ в личную базу: проверки, квота, дедупликация; индексация — в воркере."""
    settings = _settings(request)
    kb = await service.personal_base(db, current.id, settings)
    try:
        doc, row = await service.add_document(
            db, storage, settings, kb=kb, uploader_id=current.id, upload=file
        )
    except UploadRejected as exc:
        raise AppError(exc.message, code=exc.code, status_code=exc.status_code) from exc
    await _dispatcher(request).index_document(str(doc.id))
    await db.refresh(doc)
    await db.refresh(row)
    return service.document_out(doc, row)


@router.delete(
    "/personal/documents/{document_id}", status_code=204, operation_id="deletePersonalDocument"
)
async def delete_personal(
    document_id: UUID, request: Request, db: DbDep, current: CurrentUserDep
) -> None:
    settings = _settings(request)
    kb = await service.personal_base(db, current.id, settings)
    doc = await service.get_document(db, kb.id, document_id)
    await service.remove_document(db, settings, kb, doc)


@router.post(
    "/personal/documents/{document_id}/reindex",
    response_model=DocumentOut,
    operation_id="reindexPersonalDocument",
)
async def reindex_personal(
    document_id: UUID, request: Request, db: DbDep, current: CurrentUserDep
) -> DocumentOut:
    settings = _settings(request)
    kb = await service.personal_base(db, current.id, settings)
    doc = await service.get_document(db, kb.id, document_id)
    service.mark_reindex(doc)
    await db.commit()
    await _dispatcher(request).index_document(str(doc.id))
    await db.refresh(doc)
    return service.document_out(doc, await service.file_of(db, doc))


@router.get("/documents/{document_id}", response_model=DocumentOut, operation_id="getKbDocument")
async def document(document_id: UUID, db: DbDep, current: CurrentUserDep) -> DocumentOut:
    doc, row = await service.viewable_document(db, current.id, _role_ids(current), document_id)
    return service.document_out(doc, row)


@router.get(
    "/documents/{document_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadKbDocument",
)
async def document_content(
    document_id: UUID,
    db: DbDep,
    storage: StorageDep,
    current: CurrentUserDep,
    download: Annotated[bool, Query()] = True,
) -> Response:
    """Оригинал документа-источника; права на базу проверяются при каждом запросе."""
    _, row = await service.viewable_document(db, current.id, _role_ids(current), document_id)
    return await content_response(row, storage, download=download)


@router.get(
    "/documents/{document_id}/preview",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}, 404: {"description": "Превью нет"}},
    operation_id="previewKbDocument",
)
async def document_preview(
    document_id: UUID, db: DbDep, storage: StorageDep, current: CurrentUserDep
) -> Response:
    _, row = await service.viewable_document(db, current.id, _role_ids(current), document_id)
    return await preview_response(row, storage)
