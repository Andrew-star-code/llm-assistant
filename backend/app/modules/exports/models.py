"""Выгрузки переписки ``exports`` (§13.3, §14): заказ, статус, файл и срок хранения."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin


class Export(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "exports"

    requested_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    # Один чат ({"chat_id": …}) или фильтр раздела «Переписка» (ChatFilter).
    filter: Mapped[dict[str, Any]] = mapped_column(JSONB)
    format: Mapped[str] = mapped_column(String(8))  # json | xlsx | docx | pdf
    status: Mapped[str] = mapped_column(String(16))  # queued | running | ready | error | expired
    error: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("files.id"), index=True)
    chats: Mapped[int | None] = mapped_column(Integer)
    messages: Mapped[int | None] = mapped_column(Integer)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
