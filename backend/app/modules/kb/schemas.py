"""Схемы API баз знаний."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

DocStatus = Literal["queued", "processing", "ready", "error"]
Level = Literal["global", "role", "personal"]


class DocumentOut(BaseModel):
    id: UUID
    kb_id: UUID
    title: str
    filename: str
    file_type: str
    size: int
    status: DocStatus
    error: str | None
    chunks: int
    pages: int | None
    version: int
    has_preview: bool
    created_at: datetime
    indexed_at: datetime | None


class QuotaOut(BaseModel):
    max_documents: int | None  # пусто — без ограничения (нет политики лимита)
    max_bytes: int | None
    used_documents: int
    used_bytes: int


class PersonalKbOut(BaseModel):
    id: UUID
    name: str
    quota: QuotaOut
    documents: list[DocumentOut]


class RoleRef(BaseModel):
    id: UUID
    code: str
    name: str


class StatusCounts(BaseModel):
    queued: int = 0
    processing: int = 0
    ready: int = 0
    error: int = 0


class KbOut(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    level: Level
    roles: list[RoleRef]
    documents: StatusCounts
    created_at: datetime
    can_edit: bool = Field(description="Можно менять саму базу (название, роли, удаление).")


class KbIn(BaseModel):
    code: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    level: Literal["global", "role"]
    role_ids: list[UUID] = Field(default_factory=list)


class KbUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    role_ids: list[UUID] | None = None


class ImportIn(BaseModel):
    path: str = Field(min_length=1, description="Папка относительно kb.import_root.")


class ImportOut(BaseModel):
    id: UUID
    kb_id: UUID
    path: str
    status: Literal["scanning", "running", "done", "error"]
    total: int
    skipped: int
    documents: StatusCounts
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class ImportFolder(BaseModel):
    path: str
    files: int


class SearchSettingsOut(BaseModel):
    score_threshold: float = Field(description="Действующий порог реранкера.")
    default_threshold: float = Field(description="Порог из конфигурации (rag.search.rerank).")
    overridden: bool = Field(description="Порог задан в админке, а не в конфигурации.")
    updated_at: datetime | None = None


class SearchSettingsIn(BaseModel):
    score_threshold: float | None = Field(
        ..., ge=0, le=1, description="Новый порог; null — вернуть значение из конфигурации."
    )
