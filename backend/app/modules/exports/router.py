"""Выгрузки переписки (§13.3): заказ, список своих выгрузок, скачивание.

Заказ и скачивание пишутся в аудит. Файл доступен только заказавшему и только до
``expires_at`` (``exports.ttl_days``); список показывает только свои выгрузки.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from app.core.db import utcnow
from app.core.deps import DbDep, StorageDep
from app.core.errors import AppError, NotFoundError
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.chats.models import Chat
from app.modules.exports.models import Export
from app.modules.exports.schemas import ExportIn, ExportOut
from app.modules.files.models import File
from app.modules.files.router import content_response
from app.modules.rbac.permissions import Perm
from app.workers.dispatch import Dispatcher

router = APIRouter(prefix="/admin/exports", tags=["admin"])

Exporter = Annotated[CurrentUser, Depends(require(Perm.CHATS_EXPORT))]
LIST_LIMIT = 50


def _dispatcher(request: Request) -> Dispatcher:
    dispatcher: Dispatcher = request.app.state.dispatcher
    return dispatcher


def export_out(row: Export, file: File | None) -> ExportOut:
    return ExportOut(
        id=row.id,
        format=row.format,
        status=row.status,
        filter=row.filter,
        error=row.error,
        chats=row.chats,
        messages=row.messages,
        filename=file.filename if file else None,
        size=file.size if file else None,
        created_at=row.created_at,
        finished_at=row.finished_at,
        expires_at=row.expires_at,
    )


async def _own(db: DbDep, actor: CurrentUser, export_id: UUID) -> Export:
    row = await db.get(Export, export_id)
    # Чужая выгрузка «не существует» — даже для другого админа (§13.3).
    if row is None or row.requested_by != actor.id:
        raise NotFoundError("Выгрузка не найдена")
    return row


@router.post("", response_model=ExportOut, status_code=202, operation_id="adminCreateExport")
async def create_export(body: ExportIn, request: Request, db: DbDep, actor: Exporter) -> ExportOut:
    """Выгрузка одного чата или выборки по фильтру — фоновой задачей воркера."""
    if body.chat_id is not None:
        if await db.get(Chat, body.chat_id) is None:
            raise NotFoundError("Чат не найден")
        spec = {"chat_id": str(body.chat_id)}
    else:
        assert body.filter is not None  # noqa: S101 — проверено валидатором схемы
        spec = body.filter.model_dump(mode="json", exclude_none=True)
    row = Export(requested_by=actor.id, filter=spec, format=body.format, status="queued")
    db.add(row)
    await db.flush()
    await audit.record(
        db, actor_id=actor.id, action="chat.export", target_type="export", target_id=row.id,
        details={"format": body.format, **spec}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    await _dispatcher(request).export(str(row.id))
    await db.refresh(row)  # в eager-режиме (тесты) выгрузка уже готова
    file = await db.get(File, row.file_id) if row.file_id else None
    return export_out(row, file)


@router.get("", response_model=list[ExportOut], operation_id="adminListExports")
async def list_exports(db: DbDep, actor: Exporter) -> list[ExportOut]:
    """Свои выгрузки, свежие сверху."""
    rows = (
        await db.execute(
            select(Export, File)
            .outerjoin(File, File.id == Export.file_id)
            .where(Export.requested_by == actor.id)
            .order_by(Export.created_at.desc())
            .limit(LIST_LIMIT)
        )
    ).all()
    return [export_out(row, file) for row, file in rows]


@router.get("/{export_id}", response_model=ExportOut, operation_id="adminGetExport")
async def get_export(export_id: UUID, db: DbDep, actor: Exporter) -> ExportOut:
    row = await _own(db, actor, export_id)
    file = await db.get(File, row.file_id) if row.file_id else None
    return export_out(row, file)


@router.get(
    "/{export_id}/download",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="adminDownloadExport",
)
async def download_export(
    export_id: UUID,
    request: Request,
    db: DbDep,
    storage: StorageDep,
    actor: Exporter,
) -> Response:
    row = await _own(db, actor, export_id)
    if row.status == "expired" or (row.expires_at is not None and row.expires_at < utcnow()):
        raise AppError("Срок хранения выгрузки истёк", code="export_expired", status_code=410)
    if row.status != "ready" or row.file_id is None:
        raise AppError("Выгрузка ещё не готова", code="export_not_ready", status_code=409)
    file = await db.get(File, row.file_id)
    if file is None:
        raise NotFoundError("Файл выгрузки не найден")
    await audit.record(
        db, actor_id=actor.id, action="export.download", target_type="export",
        target_id=row.id, details={"format": row.format, "size": file.size},
        ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return await content_response(file, storage, download=True)
