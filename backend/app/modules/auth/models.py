"""Таблица ``sessions`` (§6.4, §14): история сессий. Активные сессии живут в Redis."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin


class UserSession(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    # SHA-256 от токена из cookie: сам токен нигде не хранится.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    provider: Mapped[str] = mapped_column(String(16))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(64))
