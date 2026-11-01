"""Схемы раздела «Переписка» (§13.3): поиск, список и просмотр чатов всех пользователей."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.chats.schemas import SearchFragment


class ChatFilter(BaseModel):
    """Фильтр переписки: тот же для поиска, списка чатов и выгрузки по выборке."""

    q: str | None = Field(None, max_length=500, description="Слова или подстрока в сообщениях.")
    user_id: UUID | None = None
    department: str | None = Field(None, max_length=255)
    date_from: date | None = Field(
        None, description="С этой даты включительно (часовой пояс чата)."
    )
    date_to: date | None = Field(None, description="По эту дату включительно.")
    scenario_id: UUID | None = None
    model: str | None = Field(None, max_length=256)
    deleted: bool | None = Field(None, description="true — только удалённое, false — без него.")
    disliked: bool | None = Field(None, description="С дизлайком.")
    incident: bool | None = Field(None, description="С инцидентом.")
    attachments: bool | None = Field(None, description="С вложениями пользователя.")


class UserRef(BaseModel):
    id: UUID
    login: str
    full_name: str
    department: str | None


class ScenarioRef(BaseModel):
    id: UUID
    code: str
    name: str


class AdminMessageHit(BaseModel):
    message_id: UUID
    chat_id: UUID
    chat_title: str | None
    user: UserRef
    role: str
    created_at: datetime
    fragments: list[SearchFragment]
    model: str | None
    scenario: str | None
    deleted: bool = Field(description="Удалено само сообщение или весь чат.")
    is_test: bool
    disliked: bool
    has_incident: bool
    has_attachments: bool


class AdminChatItem(BaseModel):
    id: UUID
    title: str | None
    user: UserRef
    scenario: str | None
    is_test: bool
    created_at: datetime
    last_message_at: datetime | None
    deleted_at: datetime | None
    messages: int
    disliked: int
    incidents: int


class AdminToolCall(BaseModel):
    call_id: str
    tool: str
    visibility: str
    status: str
    iteration: int
    duration_ms: int
    arguments: dict[str, Any] | None
    result_preview: str | None
    created_at: datetime


class AdminSource(BaseModel):
    index: int
    kind: str
    title: str
    kb_name: str | None
    page: int | None
    section: str | None
    snippet: str
    score: float | None
    cited: bool
    document_id: UUID | None
    file_id: UUID | None


class AdminFeedback(BaseModel):
    rating: int
    reasons: list[str]
    comment: str | None
    created_at: datetime


class AdminFile(BaseModel):
    id: UUID
    kind: str
    filename: str
    size: int
    parse_status: str
    deleted_at: datetime | None


class AdminMessage(BaseModel):
    id: UUID
    parent_id: UUID | None
    role: str
    content: str
    reasoning: str | None
    status: str
    thinking: bool
    model: str | None
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    ttft_ms: int | None
    latency_ms: int | None
    reasoning_ms: int | None
    error: dict[str, Any] | None
    trace: dict[str, Any] | None
    created_at: datetime
    deleted_at: datetime | None
    tool_calls: list[AdminToolCall]
    sources: list[AdminSource]
    files: list[AdminFile]
    feedback: AdminFeedback | None


class AdminChatDetail(BaseModel):
    id: UUID
    title: str | None
    user: UserRef
    scenario: ScenarioRef | None
    is_test: bool
    created_at: datetime
    last_message_at: datetime | None
    deleted_at: datetime | None
    deleted_by: UserRef | None
    active_leaf_id: UUID | None
    messages: list[AdminMessage] = Field(description="Все сообщения всех веток по времени.")


class NamedRef(BaseModel):
    id: UUID
    name: str


class FilterOptions(BaseModel):
    departments: list[str]
    scenarios: list[NamedRef]
    models: list[str]


class PurgeIn(BaseModel):
    confirm: str = Field(description="id чата ещё раз — защита от удаления не того чата.")


class PurgeOut(BaseModel):
    messages: int
    files: int
