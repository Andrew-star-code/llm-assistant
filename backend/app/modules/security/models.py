"""Журнал входов ``login_events`` (§13.4, §14)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin, utcnow


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
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IpBlock(UUIDPkMixin, CreatedAtMixin, Base):
    """Блокировка IP или подсети (§13.4): автоматически за перебор паролей или вручную."""

    __tablename__ = "ip_blocks"

    cidr: Mapped[str] = mapped_column(String(64), index=True)  # 10.0.0.5/32, 10.1.2.0/24
    reason: Mapped[str] = mapped_column(String(300))
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # пусто — бессрочно
    source: Mapped[str] = mapped_column(String(16))  # auto | manual
    created_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)


class TrustedNetwork(UUIDPkMixin, CreatedAtMixin, Base):
    """Доверенная подсеть: без флага «новый IP» и без автоматической блокировки."""

    __tablename__ = "trusted_networks"

    cidr: Mapped[str] = mapped_column(String(64), unique=True)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
