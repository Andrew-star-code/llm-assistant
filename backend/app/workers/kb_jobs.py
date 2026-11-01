"""Индексация баз знаний (§10.3) — работа воркера очереди ``kb``.

* ``index_document_job`` — разбор → чанкинг → dense + BM25 в ``kb_chunks`` / ``personal_chunks`` →
  ``ready`` с числом чанков. Ошибка → ``error`` с причиной и инцидент для админа. Если документ
  удалили, пока он индексировался, его точки удаляются.
* ``import_job`` — массовый импорт из папки: дедупликация по SHA-256 внутри базы, каждый файл
  сразу фиксируется в БД (документ «в очереди»), поэтому после перезапуска сканирование
  продолжается с того же места, а уже поставленные документы не дублируются.
* ``requeue_job`` — при старте воркера: незавершённые импорты и документы «в очереди» и
  «в обработке» (их воркер умер) возвращаются в очередь. Повтор безопасен: запись в Qdrant
  идемпотентна, а готовый документ задача пропускает.

Непредвиденная ошибка задачи (БД, хранилище, код) не оставляет документ «в обработке», а импорт —
«сканирование»: статус ``error`` с причиной и инцидент.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import utcnow
from app.modules.files.generate import PREVIEWABLE, preview_pdf
from app.modules.files.models import File
from app.modules.files.sniff import Limits, UploadRejected, detect
from app.modules.incidents import service as incidents
from app.modules.ingestion.parsers import ParseError
from app.modules.kb.models import LEVEL_PERSONAL, KbDocument, KbImport, KnowledgeBase
from app.modules.rag.store import KB_COLLECTION, PERSONAL_COLLECTION, DocumentRef
from app.workers.jobs import (
    index_chunks,
    make_chunks,
    parse_bytes,
    report_failure,
    worker_context,
)

log = structlog.stdlib.get_logger("app.worker.kb")

Enqueue = Callable[[str], Awaitable[None]]


def document_ref(kb: KnowledgeBase, doc: KbDocument) -> DocumentRef:
    personal = kb.level == LEVEL_PERSONAL
    return DocumentRef(
        collection=PERSONAL_COLLECTION if personal else KB_COLLECTION,
        document_id=doc.id,
        version=doc.version,
        title=doc.title,
        level=kb.level,
        kb_id=kb.id,
        owner_id=kb.owner_id if personal else None,
        file_id=doc.file_id,
    )


async def _fail(settings: Settings, document_id: uuid.UUID, reason: str) -> None:
    async with worker_context(settings) as ctx:
        async with ctx.sessions() as db:
            doc = await db.get(KbDocument, document_id)
            if doc is None:
                return
            doc.status = "error"
            doc.error = reason
            title, kb_id = doc.title, doc.kb_id
            await db.commit()
        await incidents.report(
            ctx.sessions, type="kb_index", severity="warning",
            title=f"Документ «{title}» не проиндексирован: {reason}"[:300],
            fingerprint=f"kb_index:{document_id}",
            payload={"document_id": str(document_id), "kb_id": str(kb_id), "reason": reason},
        )  # fmt: skip


async def index_document_job(document_id: str, settings: Settings) -> None:
    try:
        await _index_document(document_id, settings)
    except Exception as exc:
        log.exception("worker.kb_index_crashed", document_id=document_id)
        try:
            await _fail(settings, uuid.UUID(document_id), f"сбой индексации ({type(exc).__name__})")
        except Exception:
            log.exception("worker.kb_status_failed", document_id=document_id)
            await report_failure(
                settings, type="worker_failed", title="Сбой индексации документа базы знаний",
                fingerprint=f"worker_failed:kb.index:{type(exc).__name__}",
                payload={"task": "kb.index", "document_id": document_id},
            )  # fmt: skip


async def _index_document(document_id: str, settings: Settings) -> None:
    doc_id = uuid.UUID(document_id)
    async with worker_context(settings) as ctx:
        async with ctx.sessions() as db:
            doc = await db.get(KbDocument, doc_id)
            if doc is None or doc.deleted_at is not None or doc.status == "ready":
                return  # удалён или уже готов (повторная доставка задачи)
            kb = await db.get(KnowledgeBase, doc.kb_id)
            file = await db.get(File, doc.file_id)
            if kb is None or file is None:
                return
            doc.status = "processing"
            doc.error = None
            await db.commit()
            ref = document_ref(kb, doc)
            storage_key, file_type = file.storage_key, file.file_type
        data = await ctx.storage.get(storage_key)

    if data is None:
        await _fail(settings, doc_id, "файл не найден в хранилище")
        return
    try:
        parsed = await parse_bytes(data, file_type, settings)
        chunks = make_chunks(parsed, ref.title, settings)
        count = await index_chunks(ref, chunks, settings)
    except ParseError as exc:
        await _fail(settings, doc_id, str(exc))
        return
    except TimeoutError:
        await _fail(settings, doc_id, "превышено время обработки документа")
        return
    except Exception as exc:
        log.exception("worker.kb_index_failed", document_id=document_id)
        await _fail(settings, doc_id, f"ошибка индексации ({type(exc).__name__})")
        return

    async with worker_context(settings) as ctx, ctx.sessions() as db:
        doc = await db.get(KbDocument, doc_id)
        if doc is None:
            return
        if doc.deleted_at is not None or doc.version != ref.version:
            # Удалён или переиндексирован, пока шла работа: эта версия не нужна.
            from app.modules.rag.store import delete_document, qdrant_client

            client = qdrant_client(settings)
            try:
                if doc.deleted_at is not None:
                    await delete_document(client, ref.collection, doc_id)
            finally:
                await client.close()
            return
        text_key = f"texts/{doc.file_id}"
        await ctx.storage.put(text_key, parsed.markdown().encode("utf-8"))
        file = await db.get(File, doc.file_id)
        if file is not None:
            if file.preview_key is None and file_type in PREVIEWABLE:
                # PDF-превью Office-файла: по нему источник открывается на нужной странице.
                preview = await asyncio.to_thread(
                    preview_pdf, data, file_type, timeout=settings.files.convert_timeout_seconds
                )
                if preview is not None:
                    file.preview_key = f"previews/{file.id}"
                    await ctx.storage.put(file.preview_key, preview)
            file.text_key = text_key
            file.pages = len(parsed.pages)
            file.parse_status = "ready"
        doc.status = "ready"
        doc.chunks = count
        doc.indexed_at = utcnow()
        await db.commit()
    log.info("worker.kb_indexed", document_id=document_id, chunks=count)


def _supported(path: Path, data: bytes, settings: Settings) -> str:
    limits = Limits(
        max_unpacked_bytes=settings.files.max_unpacked_mb * 1024 * 1024,
        max_ratio=settings.files.max_compression_ratio,
        max_entries=settings.files.max_archive_entries,
    )
    return detect(path.name, io.BytesIO(data), limits).file_type


async def import_job(import_id: str, settings: Settings, enqueue: Enqueue) -> None:
    try:
        await _import(import_id, settings, enqueue)
    except Exception as exc:
        log.exception("worker.kb_import_crashed", import_id=import_id)
        reason = f"сбой импорта ({type(exc).__name__})"
        try:
            async with worker_context(settings) as ctx, ctx.sessions() as db:
                imp = await db.get(KbImport, uuid.UUID(import_id))
                if imp is not None:
                    imp.status = "error"
                    imp.error = reason
                    imp.finished_at = utcnow()
                    await db.commit()
        except Exception:
            log.exception("worker.kb_import_status_failed", import_id=import_id)
        await report_failure(
            settings, type="worker_failed", title=f"Импорт в базу знаний прерван: {reason}",
            fingerprint=f"worker_failed:kb.import:{import_id}",
            payload={"task": "kb.import", "import_id": import_id, "error": type(exc).__name__},
        )  # fmt: skip


async def _import(import_id: str, settings: Settings, enqueue: Enqueue) -> None:
    imp_id = uuid.UUID(import_id)
    async with worker_context(settings) as ctx:
        async with ctx.sessions() as db:
            imp = await db.get(KbImport, imp_id)
            if imp is None or imp.status not in ("scanning", "running"):
                return
            kb = await db.get(KnowledgeBase, imp.kb_id)
            # Файлы импорта принадлежат тому, кто его запустил (CLI — создателю базы).
            owner_id = imp.created_by or (kb.created_by if kb else None)
            kb_id, folder = imp.kb_id, Path(imp.path)
            if kb is None or kb.deleted_at is not None or owner_id is None:
                imp.status = "error"
                imp.error = "база удалена или не задан владелец файлов импорта"
                await db.commit()
                return
            imp.status = "scanning"
            rows = (
                await db.scalars(
                    select(KbDocument).where(
                        KbDocument.kb_id == kb_id, KbDocument.deleted_at.is_(None)
                    )
                )
            ).all()
            known = {row.sha256 for row in rows}
            done = {row.source_path for row in rows if row.import_id == imp_id}
            await db.commit()

        paths = await asyncio.to_thread(scan_folder, folder, settings.kb.import_root)
        base = await asyncio.to_thread(folder.resolve)
        if paths is None:
            async with ctx.sessions() as db:
                imp = await db.get(KbImport, imp_id)
                if imp is not None:
                    imp.status = "error"
                    imp.error = f"папка недоступна: {folder}"
                    await db.commit()
            return

        max_bytes = settings.files.max_file_mb * 1024 * 1024
        skipped = 0
        async with ctx.sessions() as db:
            imp = await db.get(KbImport, imp_id)
            if imp is not None:
                imp.total = len(paths)
                await db.commit()

        for path in paths:
            relative = str(path.relative_to(base))
            if relative in done:
                continue  # этот импорт уже поставил файл до перезапуска
            data = await asyncio.to_thread(_read_limited, path, max_bytes)
            if data is None:
                skipped += 1
                continue
            sha = hashlib.sha256(data).hexdigest()
            if sha in known:
                skipped += 1  # дубль: уже есть в базе (в том числе из этого же импорта)
                continue
            try:
                file_type = _supported(path, data, settings)
            except UploadRejected as exc:
                log.info("worker.kb_import_skip", file=path.name, reason=exc.code)
                skipped += 1
                continue
            file_id = uuid.uuid4()
            storage_key = f"kb/{file_id}"
            await ctx.storage.put(storage_key, data)
            async with ctx.sessions() as db:
                db.add(
                    File(
                        id=file_id, owner_id=owner_id, kind="kb_document", filename=path.name[:255],
                        mime=_mime(file_type), file_type=file_type, size=len(data), sha256=sha,
                        storage_key=storage_key, parse_status="pending",
                    )
                )  # fmt: skip
                await db.flush()
                doc = KbDocument(
                    kb_id=kb_id, file_id=file_id, title=path.stem[:255], status="queued",
                    sha256=sha, import_id=imp_id, uploaded_by=owner_id, source_path=relative,
                )  # fmt: skip
                db.add(doc)
                imp = await db.get(KbImport, imp_id)
                if imp is not None:
                    imp.skipped = skipped
                await db.commit()
                doc_id = doc.id
            known.add(sha)
            await enqueue(str(doc_id))

        async with ctx.sessions() as db:
            imp = await db.get(KbImport, imp_id)
            if imp is not None:
                imp.skipped = skipped
                imp.status = "running"
                await db.commit()
    log.info("worker.kb_import_scanned", import_id=import_id, files=len(paths), skipped=skipped)


def scan_folder(folder: Path, root: Path) -> list[Path] | None:
    """Файлы папки импорта по порядку; None — папка вне ``kb.import_root`` или её нет."""
    target = folder.resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_dir():
        return None
    return sorted(
        p
        for p in target.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(target).parts)
    )


def _read_limited(path: Path, max_bytes: int) -> bytes | None:
    return None if path.stat().st_size > max_bytes else path.read_bytes()


def _mime(file_type: str) -> str:
    from app.modules.files.sniff import MIME

    return MIME.get(file_type, "application/octet-stream")


async def requeue_job(
    settings: Settings, enqueue_index: Enqueue, enqueue_import: Enqueue
) -> dict[str, int]:
    async with worker_context(settings) as ctx, ctx.sessions() as db:
        imports = (await db.scalars(select(KbImport.id).where(KbImport.status == "scanning"))).all()
        docs = (
            await db.scalars(
                select(KbDocument).where(
                    KbDocument.deleted_at.is_(None),
                    KbDocument.status.in_(("queued", "processing")),
                )
            )
        ).all()
        for doc in docs:
            doc.status = "queued"
        doc_ids = [d.id for d in docs]
        await db.commit()
    for import_id in imports:
        await enqueue_import(str(import_id))
    for doc_id in doc_ids:
        await enqueue_index(str(doc_id))
    if imports or doc_ids:
        log.info("worker.kb_requeued", imports=len(imports), documents=len(doc_ids))
    return {"imports": len(imports), "documents": len(doc_ids)}
