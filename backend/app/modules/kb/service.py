"""Сервис баз знаний: личная база с квотой, документы, права менеджеров, просмотр источников.

Удаление документа сразу удаляет его точки из Qdrant (из api, без очереди) — документ пропадает
из поиска до ответа на запрос удаления (§10.3: не позже чем через минуту).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.errors import AppError, NotFoundError
from app.core.storage import Storage
from app.modules.files.models import File
from app.modules.files.service import accept_upload
from app.modules.kb.models import (
    LEVEL_PERSONAL,
    LEVEL_ROLE,
    KbDocument,
    KbImport,
    KbRole,
    KnowledgeBase,
)
from app.modules.kb.schemas import DocumentOut, ImportOut, QuotaOut, StatusCounts
from app.modules.rag.service import accessible_bases
from app.modules.rag.store import KB_COLLECTION, PERSONAL_COLLECTION, delete_document, qdrant_client

PERSONAL_NAME = "Моя база знаний"


def collection_of(kb: KnowledgeBase) -> str:
    return PERSONAL_COLLECTION if kb.level == LEVEL_PERSONAL else KB_COLLECTION


def document_out(doc: KbDocument, file: File) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        kb_id=doc.kb_id,
        title=doc.title,
        filename=file.filename,
        file_type=file.file_type,
        size=file.size,
        status=doc.status,
        error=doc.error,
        chunks=doc.chunks,
        pages=file.pages,
        version=doc.version,
        has_preview=file.file_type == "pdf" or file.preview_key is not None,
        created_at=doc.created_at,
        indexed_at=doc.indexed_at,
    )


async def personal_base(db: AsyncSession, user_id: UUID, settings: Settings) -> KnowledgeBase:
    """Личная база пользователя; создаётся при первом обращении."""
    code = f"personal:{user_id}"
    kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.code == code))
    if kb is None:
        embed = settings.models.get("embed")
        kb = KnowledgeBase(
            code=code,
            name=PERSONAL_NAME,
            level=LEVEL_PERSONAL,
            owner_id=user_id,
            embed_model=embed.model if embed else "",
            chunking=settings.rag.chunking.model_dump(),
            created_by=user_id,
        )
        db.add(kb)
        await db.commit()
    return kb


async def documents(
    db: AsyncSession, kb_id: UUID, *, status: str | None = None, limit: int = 1000
) -> list[tuple[KbDocument, File]]:
    stmt = (
        select(KbDocument, File)
        .join(File, File.id == KbDocument.file_id)
        .where(KbDocument.kb_id == kb_id, KbDocument.deleted_at.is_(None))
    )
    if status:
        stmt = stmt.where(KbDocument.status == status)
    rows = await db.execute(stmt.order_by(KbDocument.created_at.desc()).limit(limit))
    return [(d, f) for d, f in rows.all()]


async def quota(db: AsyncSession, kb_id: UUID, settings: Settings) -> QuotaOut:
    count, size = (
        await db.execute(
            select(func.count(KbDocument.id), func.coalesce(func.sum(File.size), 0))
            .join(File, File.id == KbDocument.file_id)
            .where(KbDocument.kb_id == kb_id, KbDocument.deleted_at.is_(None))
        )
    ).one()
    q = settings.kb.personal_quota
    return QuotaOut(
        max_documents=q.max_documents,
        max_bytes=q.max_mb * 1024 * 1024,
        used_documents=int(count),
        used_bytes=int(size),
    )


async def add_document(
    db: AsyncSession,
    storage: Storage,
    settings: Settings,
    *,
    kb: KnowledgeBase,
    uploader_id: UUID,
    upload: UploadFile,
) -> tuple[KbDocument, File]:
    """Проверки §9.3, дедупликация по SHA-256 внутри базы, квота личной базы; статус «в очереди»."""
    used = await quota(db, kb.id, settings) if kb.level == LEVEL_PERSONAL else None
    if used is not None and used.used_documents >= used.max_documents:
        raise AppError(
            f"В личной базе уже {used.max_documents} документов — удалите ненужные",
            code="quota_documents",
            status_code=413,
        )
    file = await accept_upload(
        db, storage, settings.files, owner_id=uploader_id, upload=upload, kind="kb_document",
        commit=False,
    )  # fmt: skip
    if used is not None and used.used_bytes + file.size > used.max_bytes:
        await db.rollback()
        await storage.delete(file.storage_key)
        raise AppError(
            f"Не хватает места в личной базе (доступно {used.max_bytes // 1024 // 1024} МБ)",
            code="quota_size",
            status_code=413,
        )
    duplicate = await db.scalar(
        select(KbDocument).where(
            KbDocument.kb_id == kb.id,
            KbDocument.sha256 == file.sha256,
            KbDocument.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        title = duplicate.title  # до rollback: потом объект истечёт
        await db.rollback()
        await storage.delete(file.storage_key)
        raise AppError(f"Этот файл уже есть в базе: «{title}»", code="duplicate", status_code=409)
    title = file.filename.rsplit(".", 1)[0] if "." in file.filename else file.filename
    doc = KbDocument(
        kb_id=kb.id, file_id=file.id, title=title[:255], status="queued", sha256=file.sha256,
        uploaded_by=uploader_id,
    )  # fmt: skip
    db.add(doc)
    await db.commit()
    return doc, file


async def remove_document(
    db: AsyncSession, settings: Settings, kb: KnowledgeBase, doc: KbDocument
) -> None:
    now = utcnow()
    doc.deleted_at = now
    file = await db.get(File, doc.file_id)
    if file is not None:
        file.deleted_at = now
    await db.commit()
    client = qdrant_client(settings)
    try:
        await delete_document(client, collection_of(kb), doc.id)
    finally:
        await client.close()


def mark_reindex(doc: KbDocument) -> None:
    doc.version += 1
    doc.status = "queued"
    doc.error = None


async def file_of(db: AsyncSession, doc: KbDocument) -> File:
    file = await db.get(File, doc.file_id)
    if file is None:
        raise NotFoundError("Документ не найден")
    return file


async def get_document(db: AsyncSession, kb_id: UUID, doc_id: UUID) -> KbDocument:
    doc = await db.get(KbDocument, doc_id)
    if doc is None or doc.kb_id != kb_id or doc.deleted_at is not None:
        raise NotFoundError("Документ не найден")
    return doc


async def viewable_document(
    db: AsyncSession, user_id: UUID, role_ids: Iterable[UUID], doc_id: UUID
) -> tuple[KbDocument, File]:
    """Документ для просмотра источника: права проверяются заново (§10.5); нет прав — 404."""
    doc = await db.get(KbDocument, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise NotFoundError("Документ не найден")
    allowed = {kb.id for kb in await accessible_bases(db, user_id, role_ids)}
    file = await db.get(File, doc.file_id)
    if doc.kb_id not in allowed or file is None:
        raise NotFoundError("Документ не найден")
    return doc, file


async def status_counts(
    db: AsyncSession, *, kb_ids: Sequence[UUID] = (), import_id: UUID | None = None
) -> dict[UUID, StatusCounts]:
    key = KbDocument.import_id if import_id is not None else KbDocument.kb_id
    stmt = select(key, KbDocument.status, func.count()).where(KbDocument.deleted_at.is_(None))
    stmt = (
        stmt.where(KbDocument.import_id == import_id)
        if import_id is not None
        else stmt.where(KbDocument.kb_id.in_(list(kb_ids)))
    )
    result: dict[UUID, StatusCounts] = {}
    for owner, status, count in (await db.execute(stmt.group_by(key, KbDocument.status))).all():
        if owner is None:
            continue
        counts = result.setdefault(owner, StatusCounts())
        if hasattr(counts, status):
            setattr(counts, status, int(count))
    return result


async def import_out(db: AsyncSession, imp: KbImport) -> ImportOut:
    counts = (await status_counts(db, import_id=imp.id)).get(imp.id, StatusCounts())
    if imp.status == "running" and counts.queued == 0 and counts.processing == 0:
        # Сканирование закончено и очередь пуста — импорт завершён.
        imp.status = "done"
        imp.finished_at = utcnow()
        await db.commit()
    return ImportOut(
        id=imp.id,
        kb_id=imp.kb_id,
        path=imp.path,
        status=imp.status,
        total=imp.total,
        skipped=imp.skipped,
        documents=counts,
        error=imp.error,
        created_at=imp.created_at,
        finished_at=imp.finished_at,
    )


async def kb_roles(db: AsyncSession, kb_ids: Sequence[UUID]) -> dict[UUID, list[UUID]]:
    rows = await db.execute(select(KbRole.kb_id, KbRole.role_id).where(KbRole.kb_id.in_(kb_ids)))
    result: dict[UUID, list[UUID]] = {}
    for kb_id, role_id in rows.all():
        result.setdefault(kb_id, []).append(role_id)
    return result


def manageable(
    kb: KnowledgeBase, *, manage_all: bool, own_role_ids: set[UUID], kb_role_ids: Sequence[UUID]
) -> bool:
    """Менеджер БЗ (`admin.kb.manage_roles`) управляет ролевыми базами своих ролей (§13.1)."""
    if kb.level == LEVEL_PERSONAL:
        return False  # личные базы — только их владельцы
    if manage_all:
        return True
    return kb.level == LEVEL_ROLE and bool(own_role_ids & set(kb_role_ids))
