"""Базы знаний (§10.1, §14): базы трёх уровней, роли ролевых баз, документы, массовый импорт."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin

LEVEL_GLOBAL = "global"
LEVEL_ROLE = "role"
LEVEL_PERSONAL = "personal"


class KnowledgeBase(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "knowledge_bases"

    # Код для ссылок из сценариев и CLI (`legal-templates`); у личных баз — `personal:<user_id>`.
    code: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(16), index=True)  # global | role | personal
    owner_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    embed_model: Mapped[str] = mapped_column(String(200))
    chunking: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KbRole(Base):
    """Кто видит ролевую базу (и чьи менеджеры БЗ ею управляют)."""

    __tablename__ = "kb_roles"

    kb_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class KbImport(UUIDPkMixin, CreatedAtMixin, Base):
    """Массовый импорт из папки на сервере (§10.3): прогресс — по статусам его документов."""

    __tablename__ = "kb_imports"

    kb_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("knowledge_bases.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # scanning | running | done | error
    total: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)  # дубли по SHA-256 и неподходящие
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KbDocument(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "kb_documents"

    kb_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("knowledge_bases.id"), index=True)
    file_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("files.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    # queued | processing | ready | error
    status: Mapped[str] = mapped_column(String(16), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    import_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("kb_imports.id"), index=True)
    # Путь файла внутри папки импорта: по нему импорт продолжается после перезапуска.
    source_path: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
