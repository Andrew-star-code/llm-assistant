"""Схемы API файлов."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

ParseStatus = Literal["pending", "processing", "ready", "error"]


class FileOut(BaseModel):
    id: UUID
    kind: Literal["upload", "generated"]
    filename: str
    mime: str
    file_type: str
    size: int
    parse_status: ParseStatus
    parse_error: str | None
    pages: int | None
    has_preview: bool
    chat_id: UUID | None
    message_id: UUID | None
    created_at: datetime


class FileLimits(BaseModel):
    max_file_mb: int
    max_files_per_message: int
    accept: list[str]
