"""Схемы выгрузок (§13.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.admin.chat_schemas import ChatFilter

ExportFormat = Literal["json", "xlsx", "docx", "pdf"]
ExportStatus = Literal["queued", "running", "ready", "error", "expired"]


class ExportIn(BaseModel):
    format: ExportFormat
    chat_id: UUID | None = Field(None, description="Один чат; иначе — выборка по фильтру.")
    filter: ChatFilter | None = Field(None, description="Фильтр раздела «Переписка».")

    @model_validator(mode="after")
    def _one_source(self) -> ExportIn:
        if (self.chat_id is None) == (self.filter is None):
            raise ValueError("Укажите либо chat_id, либо filter")
        return self


class ExportOut(BaseModel):
    id: UUID
    format: ExportFormat
    status: ExportStatus
    filter: dict[str, Any]
    error: str | None
    chats: int | None
    messages: int | None
    filename: str | None
    size: int | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None
