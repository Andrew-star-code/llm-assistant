"""Физическое удаление чата со всем содержимым (§13.3, §14).

Вызывают: админ с правом ``admin.chats.purge`` и очистка удалённого по сроку хранения
(``scheduler``). Удаляются сообщения, вызовы инструментов, источники, оценки, вложения и
сгенерированные файлы (в хранилище и их точки в Qdrant); инциденты остаются, но теряют ссылку на
чат. Файл, который стал документом личной базы знаний, принадлежит базе — у него снимается только
привязка к чату.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import Storage
from app.modules.chats.models import Chat, Message
from app.modules.feedback.models import Feedback
from app.modules.files.models import File
from app.modules.incidents.models import Incident
from app.modules.kb.models import KbDocument
from app.modules.rag.models import MessageSource
from app.modules.tools.models import ToolCall

log = structlog.stdlib.get_logger("app.chats.purge")

# Удаление точек файла из Qdrant (``rag.store.delete_document`` по коллекции вложений).
DropPoints = Callable[[UUID], Awaitable[None]]


@dataclass(frozen=True)
class PurgeResult:
    messages: int
    files: int
    # Что убрать из хранилища и Qdrant после commit (``cleanup``): иначе откат оставил бы
    # записи о файлах, которых уже нет.
    storage_keys: tuple[str, ...]
    file_ids: tuple[UUID, ...]


async def purge_chat(db: AsyncSession, chat_id: UUID) -> PurgeResult:
    """Удаляет записи чата безвозвратно; commit и затем ``cleanup`` — на вызывающем."""
    message_ids = list(
        (await db.scalars(select(Message.id).where(Message.chat_id == chat_id))).all()
    )
    files = list((await db.scalars(select(File).where(File.chat_id == chat_id))).all())
    kept = set(
        (
            await db.scalars(
                select(KbDocument.file_id).where(KbDocument.file_id.in_([f.id for f in files]))
            )
        ).all()
    )
    doomed = [f for f in files if f.id not in kept]
    if message_ids:
        await db.execute(delete(ToolCall).where(ToolCall.message_id.in_(message_ids)))
        await db.execute(delete(MessageSource).where(MessageSource.message_id.in_(message_ids)))
        await db.execute(delete(Feedback).where(Feedback.message_id.in_(message_ids)))
    if doomed:
        # Источники других сообщений, ссылающиеся на эти вложения (на всякий случай).
        await db.execute(
            delete(MessageSource).where(MessageSource.file_id.in_([f.id for f in doomed]))
        )
    if kept:
        await db.execute(
            update(File).where(File.id.in_(kept)).values(chat_id=None, message_id=None)
        )
    await db.execute(
        update(Incident).where(Incident.chat_id == chat_id).values(chat_id=None, message_id=None)
    )
    if message_ids:
        await db.execute(
            update(Incident).where(Incident.message_id.in_(message_ids)).values(message_id=None)
        )
    if doomed:
        await db.execute(delete(File).where(File.id.in_([f.id for f in doomed])))
    # Дерево сообщений удаляется одним запросом: ссылки parent_id проверяются в конце запроса.
    await db.execute(delete(Message).where(Message.chat_id == chat_id))
    await db.execute(delete(Chat).where(Chat.id == chat_id))
    await db.flush()
    keys = tuple(k for f in doomed for k in (f.storage_key, f.text_key, f.preview_key) if k)
    return PurgeResult(
        messages=len(message_ids),
        files=len(doomed),
        storage_keys=keys,
        file_ids=tuple(f.id for f in doomed),
    )


async def cleanup(result: PurgeResult, storage: Storage, drop_points: DropPoints) -> None:
    """Файлы удалённого чата — из хранилища и Qdrant (после commit; сбой только логируется)."""
    for key in result.storage_keys:
        try:
            await storage.delete(key)
        except Exception as exc:
            log.warning("chats.purge_storage_failed", key=key, error=str(exc)[:200])
    for file_id in result.file_ids:
        try:
            await drop_points(file_id)
        except Exception as exc:  # поиск по вложениям всё равно ограничен файлами чата
            log.warning("chats.purge_points_failed", file_id=str(file_id), error=str(exc)[:200])
