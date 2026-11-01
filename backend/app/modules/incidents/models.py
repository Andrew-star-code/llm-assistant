"""Инциденты (§13.5, §14): запись с группировкой по отпечатку, жизненный цикл
(новый → в работе → решён или ложное срабатывание), ответственный, решение, комментарии.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin


class Incident(UUIDPkMixin, Base):
    __tablename__ = "incidents"

    type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16))  # low | medium | warning | high | critical
    # new | in_progress | resolved | false_positive
    status: Mapped[str] = mapped_column(String(16), index=True)
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


class IncidentComment(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "incident_comments"

    incident_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    # Пусто — системный комментарий (например, «модель снова отвечает»).
    author_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
