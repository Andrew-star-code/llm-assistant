"""Инциденты (§12.5, §14). Этап 4 — минимум: запись с дедупликацией по отпечатку и список в
админке; карточка, назначение, комментарии и захват логов — этап 7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPkMixin


class Incident(UUIDPkMixin, Base):
    __tablename__ = "incidents"

    type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16))  # low | warning | high | critical
    status: Mapped[str] = mapped_column(String(16), index=True)  # new | in_progress | resolved
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(300))
    user_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    chat_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("chats.id"), index=True)
    message_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("messages.id"), index=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    assigned_to: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    resolution: Mapped[str | None] = mapped_column(Text)
