"""Вызовы инструментов ``tool_calls`` (§8.4, §14) — для трассировки и админки.

Записи с ``visibility = hidden`` никогда не отдаются пользовательскому API (§9.6).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin


class ToolCall(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "tool_calls"

    message_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("messages.id"), index=True)
    call_id: Mapped[str] = mapped_column(String(128))
    tool: Mapped[str] = mapped_column(String(64), index=True)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result_preview: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # ok | error | timeout
    duration_ms: Mapped[int] = mapped_column(Integer)
    visibility: Mapped[str] = mapped_column(String(16))  # visible | hidden
    iteration: Mapped[int] = mapped_column(Integer)
    # Строка статуса для истории чата: i18n-ключ и параметры («Читаю документ {name}»).
    label: Mapped[str] = mapped_column(String(64))
    label_params: Mapped[dict[str, str] | None] = mapped_column(JSONB)
