"""Сценарии (§8.7, §14): промпт, модель, инструменты, базы знаний, режим RAG, роли."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin


class Scenario(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "scenarios"

    code: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(64))
    # Коды ролей, которым виден сценарий; пусто — всем. Коды, а не id: роли из AD появляются
    # при первом входе пользователя, а seed сценариев идёт раньше.
    roles: Mapped[list[str]] = mapped_column(JSONB, default=list)
    model_role: Mapped[str] = mapped_column(String(32), default="chat")
    # Текст шаблона Jinja2 (не имя файла): админ правит его в редакторе.
    prompt_template: Mapped[str] = mapped_column(Text, default="")
    # Инструменты сценария; null — все включённые.
    tools: Mapped[list[str] | None] = mapped_column(JSONB)
    # Коды баз знаний; пусто — все доступные пользователю.
    knowledge_bases: Mapped[list[str]] = mapped_column(JSONB, default=list)
    rag_mode: Mapped[str] = mapped_column(String(8), default="auto")  # auto | tool | off
    requires_attachment: Mapped[bool] = mapped_column(Boolean, default=False)
    attachment_hint: Mapped[str | None] = mapped_column(String(200))  # «Приложите договор»
    starter_prompts: Mapped[list[str]] = mapped_column(JSONB, default=list)
    thinking_default: Mapped[bool | None] = mapped_column(Boolean)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Откуда сценарий: seed из config/scenarios или создан в админке.
    source: Mapped[str] = mapped_column(String(16), default="admin")
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
