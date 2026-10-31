"""Схемы API сценариев."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.scenarios.service import RagMode, ScenarioSpec


class ScenarioCard(BaseModel):
    """Карточка на стартовом экране (§7.9) — то, что нужно пользователю."""

    id: UUID
    code: str
    name: str
    description: str | None
    icon: str | None
    starter_prompts: list[str]
    requires_attachment: bool
    attachment_hint: str | None
    thinking_available: bool = Field(description="Модель сценария поддерживает «Размышлять».")
    thinking_default: bool


class ScenarioRef(BaseModel):
    id: UUID
    name: str
    icon: str | None
    requires_attachment: bool
    attachment_hint: str | None


class ScenarioOut(ScenarioSpec):
    """Сценарий в админке — все поля."""

    id: UUID
    source: str
    created_at: datetime
    unknown_roles: list[str] = Field(
        default_factory=list, description="Коды ролей, которых пока нет в системе."
    )
    unknown_knowledge_bases: list[str] = Field(default_factory=list)


class NamedOption(BaseModel):
    code: str
    name: str


class ScenarioOptions(BaseModel):
    """Что можно выбрать в редакторе."""

    model_roles: list[str]
    tools: list[str]
    knowledge_bases: list[NamedOption]
    roles: list[NamedOption]
    icons: list[str]
    variables: dict[str, str]
    rag_modes: list[RagMode]


class TestChatOut(BaseModel):
    chat_id: UUID
