"""Источники ответа (§10.5, §14): какие фрагменты получила модель и на какие сослалась."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPkMixin


class MessageSource(UUIDPkMixin, Base):
    __tablename__ = "message_sources"

    message_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("messages.id"), index=True)
    index: Mapped[int] = mapped_column(Integer)  # номер для цитаты [n]
    kind: Mapped[str] = mapped_column(String(16))  # kb | attachment
    kb_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("knowledge_bases.id"), index=True)
    document_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("kb_documents.id"), index=True
    )
    file_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("files.id"), index=True)
    chunk_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    kb_name: Mapped[str | None] = mapped_column(String(200))
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    cited: Mapped[bool] = mapped_column(Boolean, default=False)
