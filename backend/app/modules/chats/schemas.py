"""Схемы API чатов, папок, сообщений и поиска."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.files.schemas import FileOut

MessageStatus = Literal["completed", "streaming", "stopped", "error", "interrupted"]
DislikeReason = Literal["inaccurate", "off_topic", "code_error", "incomplete", "other"]


class FolderOut(BaseModel):
    id: UUID
    name: str
    sort_order: int
    created_at: datetime


class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class FolderUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    sort_order: int | None = None


class ChatListItem(BaseModel):
    id: UUID
    title: str | None
    folder_id: UUID | None
    pinned: bool
    last_message_at: datetime | None
    created_at: datetime


class ChatCreate(BaseModel):
    folder_id: UUID | None = None
    thinking_enabled: bool | None = None


class ChatUpdate(BaseModel):
    """Частичное обновление: меняются только переданные поля."""

    title: str | None = Field(None, min_length=1, max_length=300)
    pinned: bool | None = None
    folder_id: UUID | None = None
    active_leaf_id: UUID | None = None
    thinking_enabled: bool | None = None


class FeedbackOut(BaseModel):
    rating: Literal[1, -1]
    reasons: list[DislikeReason]
    comment: str | None


class MessageError(BaseModel):
    code: str
    message: str


class ToolStep(BaseModel):
    """Шаг цикла инструментов в истории (§7.4): скрытые инструменты сюда не попадают (§9.6)."""

    call_id: str
    tool: str
    status: Literal["ok", "error", "timeout"]
    label: str = Field(description="i18n-ключ строки статуса, например tools.read_document.")
    params: dict[str, str] = Field(default_factory=dict)
    duration_ms: int


class MessageOut(BaseModel):
    id: UUID
    chat_id: UUID
    parent_id: UUID | None
    role: Literal["user", "assistant"]
    content: str
    reasoning: str | None
    status: MessageStatus
    thinking: bool
    model: str | None
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    ttft_ms: int | None
    reasoning_ms: int | None = Field(None, description="Время размышления, мс (§7.4).")
    latency_ms: int | None
    error: MessageError | None
    created_at: datetime
    feedback: FeedbackOut | None = None
    files: list[FileOut] = Field(
        default_factory=list, description="Вложения вопроса или файлы, созданные в ответе."
    )
    tools: list[ToolStep] = Field(default_factory=list)


class ChatDetail(ChatListItem):
    active_leaf_id: UUID | None
    thinking_enabled: bool | None
    messages: list[MessageOut] = Field(description="Все сообщения чата (дерево через parent_id).")


class SendMessageIn(BaseModel):
    content: str = Field(min_length=1)
    parent_id: UUID | None = Field(
        None, description="Ответ, к которому продолжаем ветку; по умолчанию — активная ветка."
    )
    thinking: bool | None = Field(None, description="Режим размышлений; null — как в чате.")
    attachment_ids: list[UUID] = Field(
        default_factory=list, description="Загруженные и прочитанные файлы (POST /files)."
    )


class SendMessageOut(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut


class RegenerateIn(BaseModel):
    thinking: bool | None = None


class SearchFragment(BaseModel):
    text: str
    match: bool


class SearchHit(BaseModel):
    chat_id: UUID
    chat_title: str | None
    message_id: UUID | None
    fragments: list[SearchFragment] = Field(
        description="Фрагмент текста с отмеченными совпадениями."
    )
    last_message_at: datetime | None


class FeedbackIn(BaseModel):
    rating: Literal[1, -1]
    reasons: list[DislikeReason] = Field(default_factory=list)
    comment: str | None = Field(None, max_length=2000)


class ChatModelInfo(BaseModel):
    thinking_available: bool
    thinking_default: bool
