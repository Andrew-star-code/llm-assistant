"""Файлы (§14): загрузки, сгенерированные файлы; документы БЗ и выгрузки — этапы 4 и 6."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin


class File(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "files"

    owner_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    chat_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("chats.id"), index=True)
    message_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("messages.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # upload | generated | kb_document | export
    # Имя файла пользователя — только для показа и Content-Disposition, никогда не путь (§15).
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(128))
    file_type: Mapped[str] = mapped_column(String(16))  # docx, pdf, xlsx, … — по сигнатуре
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(256))
    text_key: Mapped[str | None] = mapped_column(String(256))
    preview_key: Mapped[str | None] = mapped_column(String(256))
    # pending | processing | ready | error
    parse_status: Mapped[str] = mapped_column(String(16))
    parse_error: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[int | None] = mapped_column(Integer)
    chars: Mapped[int | None] = mapped_column(Integer)
    # Оглавление: заголовки, страницы, таблицы (§9.2 get_document_outline).
    outline: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
