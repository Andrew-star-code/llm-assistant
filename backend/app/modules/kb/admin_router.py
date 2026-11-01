"""Админка «Базы знаний» (§13.2): базы, роли, документы, массовый импорт из папки.

``admin.kb.manage`` — все общие и ролевые базы; ``admin.kb.manage_roles`` (менеджер БЗ) — документы
и импорт ролевых баз тех ролей, что есть у него самого. Каждое действие пишется в аудит.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import DbDep, StorageDep
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.modules.admin import app_settings
from app.modules.admin.models import AppSetting
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require, require_any
from app.modules.files.sniff import UploadRejected
from app.modules.kb import service
from app.modules.kb.models import (
    LEVEL_PERSONAL,
    LEVEL_ROLE,
    KbDocument,
    KbImport,
    KbRole,
    KnowledgeBase,
)
from app.modules.kb.schemas import (
    DocumentOut,
    ImportFolder,
    ImportIn,
    ImportOut,
    KbIn,
    KbOut,
    KbUpdate,
    RoleRef,
    SearchSettingsIn,
    SearchSettingsOut,
    StatusCounts,
)
from app.modules.rag.store import delete_document, qdrant_client
from app.modules.rbac.models import Role
from app.modules.rbac.permissions import Perm
from app.workers.dispatch import Dispatcher
from app.workers.kb_jobs import scan_folder

router = APIRouter(prefix="/admin/kb", tags=["admin"])

Manager = Annotated[CurrentUser, Depends(require_any(Perm.KB_MANAGE, Perm.KB_MANAGE_ROLES))]
Owner = Annotated[CurrentUser, Depends(require(Perm.KB_MANAGE))]


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _dispatcher(request: Request) -> Dispatcher:
    dispatcher: Dispatcher = request.app.state.dispatcher
    return dispatcher


async def _base(db: AsyncSession, actor: CurrentUser, kb_id: UUID) -> KnowledgeBase:
    """База, которой актор может управлять; чужая для менеджера — 403, нет такой — 404."""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or kb.deleted_at is not None or kb.level == LEVEL_PERSONAL:
        raise NotFoundError("База знаний не найдена")
    roles = (await service.kb_roles(db, [kb.id])).get(kb.id, [])
    if not service.manageable(
        kb,
        manage_all=actor.has(Perm.KB_MANAGE),
        own_role_ids={r.role.id for r in actor.roles},
        kb_role_ids=roles,
    ):
        raise ForbiddenError("Эта база знаний вам недоступна")
    return kb


async def _roles(db: AsyncSession, role_ids: list[UUID]) -> list[Role]:
    if not role_ids:
        return []
    rows = (await db.scalars(select(Role).where(Role.id.in_(role_ids)))).all()
    if len(rows) != len(set(role_ids)):
        raise AppError("Роль не найдена", code="role_not_found", status_code=422)
    return list(rows)


async def _kb_out(db: AsyncSession, actor: CurrentUser, bases: list[KnowledgeBase]) -> list[KbOut]:
    ids = [kb.id for kb in bases]
    role_map = await service.kb_roles(db, ids)
    all_role_ids = {r for roles in role_map.values() for r in roles}
    roles = {
        r.id: r for r in (await db.scalars(select(Role).where(Role.id.in_(all_role_ids)))).all()
    }
    counts = await service.status_counts(db, kb_ids=ids)
    own = {r.role.id for r in actor.roles}
    result = []
    for kb in bases:
        kb_roles = role_map.get(kb.id, [])
        if not service.manageable(
            kb, manage_all=actor.has(Perm.KB_MANAGE), own_role_ids=own, kb_role_ids=kb_roles
        ):
            continue
        result.append(
            KbOut(
                id=kb.id,
                code=kb.code,
                name=kb.name,
                description=kb.description,
                level=kb.level,
                roles=[
                    RoleRef(id=roles[r].id, code=roles[r].code, name=roles[r].name)
                    for r in kb_roles
                    if r in roles
                ],
                documents=counts.get(kb.id, StatusCounts()),
                created_at=kb.created_at,
                can_edit=actor.has(Perm.KB_MANAGE),
            )
        )
    return result


# ------------------------------------------------------------------ базы


async def _search_settings_out(db: AsyncSession, settings: Settings) -> SearchSettingsOut:
    row = await db.get(AppSetting, app_settings.RERANK_THRESHOLD)
    effective = await app_settings.search_settings(db, settings)
    return SearchSettingsOut(
        score_threshold=effective.rerank.score_threshold,
        default_threshold=settings.rag.search.rerank.score_threshold,
        overridden=row is not None,
        updated_at=row.updated_at if row is not None else None,
    )


@router.get(
    "/search-settings", response_model=SearchSettingsOut, operation_id="adminKbSearchSettings"
)
async def get_search_settings(request: Request, db: DbDep, _: Owner) -> SearchSettingsOut:
    """Параметры поиска, которые подбирают на реальных документах (порог реранкера)."""
    return await _search_settings_out(db, _settings(request))


@router.put(
    "/search-settings", response_model=SearchSettingsOut, operation_id="adminUpdateKbSearchSettings"
)
async def update_search_settings(
    body: SearchSettingsIn, request: Request, db: DbDep, actor: Owner
) -> SearchSettingsOut:
    """Новый порог действует со следующего поиска, без перезапуска; null — значение из конфига."""
    settings = _settings(request)
    before = (await app_settings.search_settings(db, settings)).rerank.score_threshold
    await app_settings.set_value(
        db, app_settings.RERANK_THRESHOLD, body.score_threshold, updated_by=actor.id
    )
    await audit.record(
        db, actor_id=actor.id, action="kb.search_settings", target_type="app_setting",
        target_id=app_settings.RERANK_THRESHOLD,
        details={"before": before, "after": body.score_threshold}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return await _search_settings_out(db, settings)


@router.get("", response_model=list[KbOut], operation_id="adminListKb")
async def list_bases(db: DbDep, actor: Manager) -> list[KbOut]:
    bases = (
        await db.scalars(
            select(KnowledgeBase)
            .where(KnowledgeBase.deleted_at.is_(None), KnowledgeBase.level != LEVEL_PERSONAL)
            .order_by(KnowledgeBase.name)
        )
    ).all()
    return await _kb_out(db, actor, list(bases))


@router.post("", response_model=KbOut, status_code=201, operation_id="adminCreateKb")
async def create_base(body: KbIn, request: Request, db: DbDep, actor: Owner) -> KbOut:
    if await db.scalar(select(KnowledgeBase.id).where(KnowledgeBase.code == body.code)):
        raise AppError("База с таким кодом уже есть", code="kb_exists", status_code=409)
    if body.level == LEVEL_ROLE and not body.role_ids:
        raise AppError("Для ролевой базы нужна хотя бы одна роль", code="roles_required")
    roles = await _roles(db, body.role_ids if body.level == LEVEL_ROLE else [])
    settings = _settings(request)
    embed = settings.models.get("embed")
    kb = KnowledgeBase(
        code=body.code, name=body.name, description=body.description, level=body.level,
        embed_model=embed.model if embed else "", chunking=settings.rag.chunking.model_dump(),
        created_by=actor.id,
    )  # fmt: skip
    db.add(kb)
    await db.flush()
    for role in roles:
        db.add(KbRole(kb_id=kb.id, role_id=role.id))
    await audit.record(
        db, actor_id=actor.id, action="kb.create", target_type="knowledge_base", target_id=kb.id,
        details={"code": kb.code, "level": kb.level, "roles": [r.code for r in roles]},
        ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    [out] = await _kb_out(db, actor, [kb])
    return out


@router.patch("/{kb_id}", response_model=KbOut, operation_id="adminUpdateKb")
async def update_base(
    kb_id: UUID, body: KbUpdate, request: Request, db: DbDep, actor: Owner
) -> KbOut:
    kb = await _base(db, actor, kb_id)
    changes = body.model_dump(exclude_unset=True)
    if body.name is not None:
        kb.name = body.name
    if "description" in changes:
        kb.description = body.description
    if body.role_ids is not None:
        if kb.level != LEVEL_ROLE:
            raise AppError("Роли задаются только у ролевой базы", code="not_role_kb")
        if not body.role_ids:
            raise AppError("Для ролевой базы нужна хотя бы одна роль", code="roles_required")
        roles = await _roles(db, body.role_ids)
        await db.execute(delete(KbRole).where(KbRole.kb_id == kb.id))
        for role in roles:
            db.add(KbRole(kb_id=kb.id, role_id=role.id))
        changes["role_ids"] = [r.code for r in roles]
    await audit.record(
        db, actor_id=actor.id, action="kb.update", target_type="knowledge_base", target_id=kb.id,
        details={k: str(v) for k, v in changes.items()}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    [out] = await _kb_out(db, actor, [kb])
    return out


@router.delete("/{kb_id}", status_code=204, operation_id="adminDeleteKb")
async def delete_base(kb_id: UUID, request: Request, db: DbDep, actor: Owner) -> None:
    """База и все её документы пропадают из поиска сразу (точки удаляются из Qdrant)."""
    kb = await _base(db, actor, kb_id)
    now = utcnow()
    kb.deleted_at = now
    docs = (
        await db.scalars(
            select(KbDocument).where(KbDocument.kb_id == kb.id, KbDocument.deleted_at.is_(None))
        )
    ).all()
    for doc in docs:
        doc.deleted_at = now
    await audit.record(
        db, actor_id=actor.id, action="kb.delete", target_type="knowledge_base", target_id=kb.id,
        details={"code": kb.code, "documents": len(docs)}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    client = qdrant_client(_settings(request))
    try:
        for doc in docs:
            await delete_document(client, service.collection_of(kb), doc.id)
    finally:
        await client.close()


# ------------------------------------------------------------------ документы


@router.get("/{kb_id}/documents", response_model=list[DocumentOut], operation_id="adminKbDocuments")
async def list_documents(
    kb_id: UUID,
    db: DbDep,
    actor: Manager,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
) -> list[DocumentOut]:
    kb = await _base(db, actor, kb_id)
    rows = await service.documents(db, kb.id, status=status, limit=limit)
    return [service.document_out(d, f) for d, f in rows]


@router.post(
    "/{kb_id}/documents",
    response_model=DocumentOut,
    status_code=201,
    operation_id="adminUploadKbDocument",
)
async def upload_document(
    kb_id: UUID,
    file: UploadFile,
    request: Request,
    db: DbDep,
    storage: StorageDep,
    actor: Manager,
) -> DocumentOut:
    kb = await _base(db, actor, kb_id)
    try:
        doc, row = await service.add_document(
            db, storage, _settings(request), kb=kb, uploader_id=actor.id, upload=file
        )
    except UploadRejected as exc:
        raise AppError(exc.message, code=exc.code, status_code=exc.status_code) from exc
    await audit.record(
        db, actor_id=actor.id, action="kb.document.upload", target_type="kb_document",
        target_id=doc.id, details={"kb": kb.code, "filename": row.filename},
        ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    await _dispatcher(request).index_document(str(doc.id))
    await db.refresh(doc)
    await db.refresh(row)
    return service.document_out(doc, row)


@router.delete(
    "/{kb_id}/documents/{document_id}", status_code=204, operation_id="adminDeleteKbDocument"
)
async def delete_kb_document(
    kb_id: UUID, document_id: UUID, request: Request, db: DbDep, actor: Manager
) -> None:
    kb = await _base(db, actor, kb_id)
    doc = await service.get_document(db, kb.id, document_id)
    await audit.record(
        db, actor_id=actor.id, action="kb.document.delete", target_type="kb_document",
        target_id=doc.id, details={"kb": kb.code, "title": doc.title}, ip=client_ip(request),
    )  # fmt: skip
    await service.remove_document(db, _settings(request), kb, doc)


@router.post(
    "/{kb_id}/documents/{document_id}/reindex",
    response_model=DocumentOut,
    operation_id="adminReindexKbDocument",
)
async def reindex_document(
    kb_id: UUID, document_id: UUID, request: Request, db: DbDep, actor: Manager
) -> DocumentOut:
    kb = await _base(db, actor, kb_id)
    doc = await service.get_document(db, kb.id, document_id)
    service.mark_reindex(doc)
    await audit.record(
        db, actor_id=actor.id, action="kb.document.reindex", target_type="kb_document",
        target_id=doc.id, details={"kb": kb.code}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    await _dispatcher(request).index_document(str(doc.id))
    await db.refresh(doc)
    return service.document_out(doc, await service.file_of(db, doc))


# ------------------------------------------------------------------ импорт из папки


@router.get("/import-folders", response_model=list[ImportFolder], operation_id="adminImportFolders")
async def import_folders(request: Request, actor: Manager) -> list[ImportFolder]:
    """Папки верхнего уровня в ``kb.import_root`` — что можно импортировать."""
    root = _settings(request).kb.import_root

    def scan() -> list[ImportFolder]:
        if not root.is_dir():
            return []
        result = []
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                files = scan_folder(child, root) or []
                result.append(ImportFolder(path=child.name, files=len(files)))
        return result

    return await asyncio.to_thread(scan)


@router.get("/{kb_id}/imports", response_model=list[ImportOut], operation_id="adminKbImports")
async def list_imports(kb_id: UUID, db: DbDep, actor: Manager) -> list[ImportOut]:
    kb = await _base(db, actor, kb_id)
    rows = (
        await db.scalars(
            select(KbImport).where(KbImport.kb_id == kb.id).order_by(KbImport.created_at.desc())
        )
    ).all()
    return [await service.import_out(db, imp) for imp in rows]


@router.post(
    "/{kb_id}/imports", response_model=ImportOut, status_code=202, operation_id="adminStartImport"
)
async def start_import(
    kb_id: UUID, body: ImportIn, request: Request, db: DbDep, actor: Manager
) -> ImportOut:
    """Массовый импорт идёт фоном (§10.3); прогресс — ``GET …/imports``."""
    kb = await _base(db, actor, kb_id)
    root = _settings(request).kb.import_root
    folder = root / body.path.strip().lstrip("/")
    files = await asyncio.to_thread(scan_folder, folder, root)
    if files is None:
        raise AppError(
            "Папка не найдена внутри каталога импорта", code="import_path", status_code=422
        )
    imp = KbImport(
        kb_id=kb.id, path=str(Path(folder)), status="scanning", total=len(files), skipped=0,
        created_by=actor.id,
    )  # fmt: skip
    db.add(imp)
    await db.flush()
    await audit.record(
        db, actor_id=actor.id, action="kb.import", target_type="knowledge_base", target_id=kb.id,
        details={"path": body.path, "files": len(files)}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    await _dispatcher(request).import_folder(str(imp.id))
    await db.refresh(imp)
    return await service.import_out(db, imp)
