"""Журнал входов ``login_events`` (§13.4, §14)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPkMixin, utcnow


class LoginEvent(UUIDPkMixin, Base):
    __tablename__ = "login_events"

    user_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    login_attempted: Mapped[str] = mapped_column(String(256), index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, index=True
    )
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(16))
    success: Mapped[bool] = mapped_column(Boolean)
    # Точная причина отказа — только здесь; пользователь видит «Неверный логин или пароль».
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    risk_flags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
