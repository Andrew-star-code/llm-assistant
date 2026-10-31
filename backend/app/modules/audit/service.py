"""Журнал аудита (§13.6): всё, что админ делает с чужими данными и настройками."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog


async def record(
    db: AsyncSession,
    *,
    actor_id: UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: str | UUID | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Добавляет запись в ту же транзакцию, что и само действие: нет действия — нет записи."""
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details or {},
        ip=ip,
    )
    db.add(entry)
    await db.flush()
    return entry
