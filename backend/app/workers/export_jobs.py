"""Выгрузки и плановые задачи админки (§13.3, §14) — работа воркера и ``scheduler``.

* ``export_job`` — собирает выгрузку (JSON, XLSX, DOCX, PDF) и кладёт файл, доступный только
  заказавшему, на ``exports.ttl_days``. Сбой — статус ``error`` с причиной и инцидент.
* ``cleanup_exports_job`` — удаляет файлы истёкших выгрузок.
* ``models_health_job`` — монитор здоровья моделей раз в минуту (``llm.monitor``).
* ``retention_job`` — физически стирает чаты, удалённые пользователями раньше срока хранения
  (настройка админки или ``retention.deleted_days``; 0 — выключено).
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import utcnow
from app.modules.admin import app_settings
from app.modules.audit import service as audit
from app.modules.chats.models import Chat
from app.modules.chats.purge import cleanup, purge_chat
from app.modules.exports import service
from app.modules.exports.models import Export
from app.modules.files.generate import DocumentSpec, create_document
from app.modules.files.models import File
from app.modules.files.sniff import MIME
from app.modules.rag.store import ATTACHMENT_COLLECTION, delete_document, qdrant_client
from app.workers.jobs import report_failure, worker_context

log = structlog.stdlib.get_logger("app.worker.exports")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def export_job(export_id: str, settings: Settings) -> None:
    try:
        await _export(UUID(export_id), settings)
    except Exception as exc:
        log.exception("worker.export_failed", export_id=export_id)
        reason = f"сбой выгрузки ({type(exc).__name__})"
        try:
            await _finish(settings, UUID(export_id), status="error", error=reason)
        except Exception:
            log.exception("worker.export_status_failed", export_id=export_id)
        await report_failure(
            settings, type="worker_failed", title=f"Выгрузка переписки не собрана: {reason}",
            fingerprint=f"worker_failed:exports.build:{type(exc).__name__}",
            payload={"task": "exports.build", "export_id": export_id},
        )  # fmt: skip


async def _finish(settings: Settings, export_id: UUID, *, status: str, error: str) -> None:
    async with worker_context(settings) as ctx, ctx.sessions() as db:
        row = await db.get(Export, export_id)
        if row is not None:
            row.status = status
            row.error = error
            row.finished_at = utcnow()
            await db.commit()


async def _export(export_id: UUID, settings: Settings) -> None:
    tz = settings.chat.timezone
    async with worker_context(settings) as ctx, ctx.sessions() as db:
        row = await db.get(Export, export_id)
        if row is None or row.status not in ("queued", "running"):
            return
        row.status = "running"
        await db.commit()
        fmt, spec, owner = row.format, dict(row.filter), row.requested_by

        ids = await service.chat_ids(db, spec, tz)
        total = await service.count_messages(db, ids)
        if total > settings.exports.max_messages:
            row.status = "error"
            row.error = (
                f"В выборке {total} сообщений — больше предела {settings.exports.max_messages}; "
                "сузьте фильтр"
            )
            row.finished_at = utcnow()
            await db.commit()
            return

        # Время в имени файла — в поясе компании, как и внутри выгрузки (контейнер живёт в UTC).
        stamp = utcnow().astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H-%M")
        title = f"Выгрузка переписки {stamp}"
        if fmt == "json":
            data, ext = await service.build_json(db, ids), "json"
        elif fmt == "xlsx":
            data, ext = await service.build_xlsx(db, ids, tz), "xlsx"
        else:
            markdown = await service.build_markdown(db, ids, tz)
            doc = await asyncio.to_thread(
                create_document,
                DocumentSpec(format=fmt, title=title, markdown=markdown),
                templates=settings.config_dir / "templates",
                timeout=settings.files.convert_timeout_seconds,
            )
            data, ext = doc.data, doc.file_type

        file_id = uuid.uuid4()
        key = f"exports/{file_id}"
        await ctx.storage.put(key, data)
        db.add(
            File(
                id=file_id, owner_id=owner, kind="export", filename=f"{title}.{ext}",
                mime=MIME.get(ext, "application/octet-stream"),
                file_type=ext, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                storage_key=key, parse_status="ready",
            )
        )  # fmt: skip
        await db.flush()
        row = await db.get(Export, export_id)
        if row is None:
            return
        now = utcnow()
        row.status = "ready"
        row.error = None
        row.file_id = file_id
        row.chats = len(ids)
        row.messages = total
        row.finished_at = now
        row.expires_at = now + timedelta(days=settings.exports.ttl_days)
        await db.commit()
    log.info(
        "worker.exported", export_id=str(export_id), format=fmt, chats=len(ids), messages=total
    )


async def cleanup_exports_job(settings: Settings) -> int:
    """Файлы выгрузок после срока хранения удаляются; запись остаётся со статусом ``expired``."""
    removed = 0
    async with worker_context(settings) as ctx, ctx.sessions() as db:
        rows = (
            await db.scalars(
                select(Export).where(Export.status == "ready", Export.expires_at < utcnow())
            )
        ).all()
        for row in rows:
            file = await db.get(File, row.file_id) if row.file_id else None
            row.status = "expired"
            row.file_id = None
            if file is not None:
                await db.flush()
                await db.delete(file)
                await ctx.storage.delete(file.storage_key)
            removed += 1
        await db.commit()
    if removed:
        log.info("worker.exports_expired", exports=removed)
    return removed


async def retention_job(settings: Settings) -> int:
    """Чаты, удалённые пользователями раньше срока хранения, стираются физически."""
    async with worker_context(settings) as ctx:
        async with ctx.sessions() as db:
            days = await app_settings.retention_days(db, settings)
            if days <= 0:
                return 0
            border = utcnow() - timedelta(days=days)
            ids = list(
                (
                    await db.scalars(
                        select(Chat.id).where(
                            Chat.deleted_at.is_not(None), Chat.deleted_at < border
                        )
                    )
                ).all()
            )
        client = qdrant_client(settings)

        async def drop_points(file_id: UUID) -> None:
            await delete_document(client, ATTACHMENT_COLLECTION, file_id)

        try:
            for chat_id in ids:
                async with ctx.sessions() as db:
                    chat = await db.get(Chat, chat_id)
                    if chat is None:
                        continue
                    owner, deleted_at = chat.user_id, chat.deleted_at
                    result = await purge_chat(db, chat_id)
                    # Системное действие над чужими данными — тоже в журнал (§13.6).
                    await audit.record(
                        db, actor_id=None, action="retention.purge", target_type="chat",
                        target_id=chat_id,
                        details={
                            "user_id": str(owner), "messages": result.messages,
                            "files": result.files, "deleted_at": _iso(deleted_at),
                            "days": days,
                        },
                    )  # fmt: skip
                    await db.commit()
                await cleanup(result, ctx.storage, drop_points)
        finally:
            await client.close()
    if ids:
        log.info("worker.retention_purged", chats=len(ids), days=days)
    return len(ids)


async def models_health_job(settings: Settings) -> int:
    """Проверка моделей; возвращает число недоступных."""
    from redis.asyncio import Redis

    from app.modules.llm.monitor import check_models

    redis = Redis.from_url(settings.redis_url.get_secret_value())
    try:
        async with worker_context(settings) as ctx:
            results = await check_models(settings, ctx.sessions, redis)
    finally:
        await redis.aclose()
    return sum(1 for h in results if not h.ok)
