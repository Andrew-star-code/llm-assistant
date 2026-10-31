"""Фреймворк инструментов (§9.1).

Инструмент — класс с описанием для модели, схемой аргументов (Pydantic → JSON Schema) и ``run``.
Права проверяет сервер по сессии пользователя (``ToolContext``), а не по аргументам модели.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.storage import Storage
from app.modules.llm.registry import ModelRegistry
from app.workers.dispatch import Dispatcher


@dataclass(frozen=True)
class ToolFile:
    """Вложение чата, доступное инструментам (снимок на момент генерации)."""

    id: UUID
    filename: str
    file_type: str
    size: int
    pages: int | None
    text_key: str | None
    storage_key: str
    outline: dict[str, Any] | None


@dataclass(frozen=True)
class Services:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    storage: Storage
    models: ModelRegistry
    dispatcher: Dispatcher


@dataclass(frozen=True)
class ToolContext:
    user_id: UUID  # из сессии, не от модели
    permissions: frozenset[str]
    chat_id: UUID
    message_id: UUID
    attachments: tuple[ToolFile, ...]
    services: Services


@dataclass
class ToolResult:
    content: str  # что увидит модель (обрезается до бюджета)
    files: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] | None = None  # для трассировки


class NoArgs(BaseModel):
    pass


class Tool(ABC):
    name: ClassVar[str]  # snake_case, уникально
    description: ClassVar[str]  # для модели: когда вызывать и когда нет
    args_model: ClassVar[type[BaseModel]] = NoArgs
    visibility: ClassVar[Literal["visible", "hidden"]] = "visible"
    status_label: ClassVar[str]  # i18n-ключ строки статуса «Читаю документ…»
    timeout_s: ClassVar[int] = 60
    required_permissions: ClassVar[frozenset[str]] = frozenset()
    needs_attachments: ClassVar[bool] = False  # без вложений в чате инструмент не предлагается

    @abstractmethod
    async def run(self, ctx: ToolContext, args: Any) -> ToolResult: ...

    def label_params(self, args: Any) -> dict[str, str]:
        """Параметры строки статуса, например имя файла."""
        return {}

    @classmethod
    def schema(cls) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": cls.args_model.model_json_schema(),
            },
        }


class ToolError(Exception):
    """Ожидаемая ошибка инструмента; текст уходит модели, генерация продолжается (§8.4)."""
