"""Лайки и дизлайки ответов (§7.4, §14)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, SmallInteger, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin


class Feedback(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("message_id", "user_id"),)

    message_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("messages.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    rating: Mapped[int] = mapped_column(SmallInteger)  # +1 | -1
    reasons: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    comment: Mapped[str | None] = mapped_column(Text)
