"""Журнал аудита ``audit_log`` (§13.6). Только вставка: UPDATE и DELETE запрещены триггером."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPkMixin, utcnow


class AuditLog(UUIDPkMixin, Base):
    __tablename__ = "audit_log"

    actor_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    ip: Mapped[str | None] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, index=True
    )
