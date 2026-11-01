"""Чаты, папки и сообщения (§7.2, §8.6, §14).

Сообщения образуют дерево через ``parent_id``: перегенерация создаёт сестринский ответ к тому же
сообщению пользователя. ``chats.active_leaf_id`` — лист активной ветки; ветка восстанавливается
проходом по родителям. Удаление — мягкое (``deleted_at``): у пользователя пропадает, админ видит.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin


class Folder(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "folders"

    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Chat(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "chats"
    __table_args__ = (
        Index(
            "ix_chats_user_last_message",
            "user_id",
            text("last_message_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    folder_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(300))
    # Сценарий чата (§8.7); сам сценарий читается из БД на каждое сообщение.
    scenario_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("scenarios.id", ondelete="SET NULL"), index=True
    )
    # Тестовый чат из редактора сценария: не показывается в истории пользователя.
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    active_leaf_id: Mapped[UUID | None] = mapped_column(Uuid)
    thinking_enabled: Mapped[bool | None] = mapped_column(Boolean)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)


class Message(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_search", "search_vector", postgresql_using="gin"),
        Index(
            "ix_messages_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
    )

    chat_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("chats.id"), index=True)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("messages.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    reasoning: Mapped[str | None] = mapped_column(Text)
    # completed | streaming | stopped | error | interrupted
    status: Mapped[str] = mapped_column(String(16))
    thinking: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    model: Mapped[str | None] = mapped_column(String(256))
    finish_reason: Mapped[str | None] = mapped_column(String(32))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trace: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('russian', coalesce(content, ''))", persisted=True)
    )
