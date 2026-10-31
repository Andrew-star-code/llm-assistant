"""Таблица ``users`` (§14). Источник правды — AD; обновляется при входе и синхронизации."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin, utcnow


class User(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    # objectGUID из AD (строка UUID); у пользователей провайдера dev — «dev:<логин>».
    ad_guid: Mapped[str] = mapped_column(String(64), unique=True)
    login: Mapped[str] = mapped_column(String(128), unique=True)
    upn: Mapped[str | None] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256))
    full_name: Mapped[str] = mapped_column(String(512))
    last_name: Mapped[str | None] = mapped_column(String(128))
    first_name: Mapped[str | None] = mapped_column(String(128))
    middle_name: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(256))
    department: Mapped[str | None] = mapped_column(String(256))
    company: Mapped[str | None] = mapped_column(String(256))
    office: Mapped[str | None] = mapped_column(String(256))
    phone: Mapped[str | None] = mapped_column(String(64))
    mobile: Mapped[str | None] = mapped_column(String(64))
    manager_dn: Mapped[str | None] = mapped_column(Text)
    manager_name: Mapped[str | None] = mapped_column(String(512))
    employee_id: Mapped[str | None] = mapped_column(String(64))
    photo_key: Mapped[str | None] = mapped_column(String(256))
    photo_sha256: Mapped[str | None] = mapped_column(String(64))
    ad_groups: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    address_form: Mapped[str | None] = mapped_column(String(32))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    # Учётка отключена в AD (бит ACCOUNTDISABLE) — отдельно от блокировки администратором.
    ad_disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    notice_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow
    )

    def is_block_active(self, now: datetime) -> bool:
        if not self.is_blocked:
            return False
        return self.blocked_until is None or self.blocked_until > now
