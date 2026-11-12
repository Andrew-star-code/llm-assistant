"""Общее состояние генерации одного ответа (§8): зависимости, результат, коды ошибок.

Шаги генерации — ``preparation`` → ``retrieval`` → ``toolloop`` → ``finish`` — получают одни и те же
зависимости (``Deps``) и пишут в один ``GenerationResult``; порядок шагов — ``generation._run``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import openai
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.core.storage import Storage
from app.modules.completions.prompt import (
    PromptRenderer,
)
from app.modules.limits.service import Limits
from app.modules.llm.registry import ModelRegistry
from app.modules.llm.stream import Usage
from app.modules.rag.service import (
    SourceBook,
)
from app.modules.tools.base import Services
from app.modules.tools.executor import ToolOutcome

CHAT_ROLE = "chat"
UTILITY_ROLE = "utility"
RESULT_PREVIEW_CHARS = 4000  # сколько символов результата инструмента хранит ``tool_calls``


class GuardBlocked(Exception):  # noqa: N818 — сигнал, а не ошибка
    """Guard-модель заблокировала запрос: модель не вызывается, в ответе — отказ."""


@dataclass(frozen=True)
class Deps:
    """Зависимости генерации; одни на процесс (api в режиме inline или исполнитель)."""

    settings: Settings
    redis: Redis
    sessions: async_sessionmaker[AsyncSession]
    registry: ModelRegistry
    renderer: PromptRenderer
    storage: Storage
    limits: Limits
    services: Services  # то, что доступно инструментам (``ToolContext.services``)


@dataclass
class GenerationResult:
    content: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    status: str = "completed"
    finish_reason: str | None = None
    usage: Usage | None = None
    ttft_ms: int | None = None
    reasoning_started: float | None = None
    reasoning_ms: int | None = None
    error: dict[str, Any] | None = None
    tools: list[ToolOutcome] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    book: SourceBook | None = None
    # Для учёта (§12.3): кто, какой ролью модели и в каком режиме генерировал.
    user_id: UUID | None = None
    chat_id: UUID | None = None
    model_role: str | None = None
    thinking: bool = False
    title_usage: Usage | None = None
    # Заполняются в начале подготовки: нужны для заголовка чата, даже если подготовка упала.
    question: str = ""
    is_first_answer: bool = False
    model_retries: int = 0  # автоповторов запроса к модели за ответ

    def add_usage(self, usage: Usage) -> None:
        if self.usage is None:
            self.usage = usage
            return
        self.usage = Usage(
            prompt_tokens=self.usage.prompt_tokens + usage.prompt_tokens,
            completion_tokens=self.usage.completion_tokens + usage.completion_tokens,
            reasoning_tokens=(self.usage.reasoning_tokens or 0) + (usage.reasoning_tokens or 0),
        )


def error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, openai.APIStatusError):
        retryable = exc.status_code >= 500 or exc.status_code == 429
        return {
            "code": f"model_http_{exc.status_code}",
            "message": "Модель вернула ошибку",
            "retryable": retryable,
        }
    if isinstance(exc, openai.APITimeoutError):
        return {"code": "model_timeout", "message": "Модель не ответила вовремя", "retryable": True}
    if isinstance(exc, openai.APIConnectionError):
        return {"code": "model_unavailable", "message": "Модель недоступна", "retryable": True}
    if isinstance(exc, AppError):
        # Ожидаемый отказ (вопрос или результаты не помещаются в контекст) — не сбой кода:
        # повтор не поможет, инцидент не нужен.
        return {"code": exc.code, "message": exc.message, "retryable": False}
    return {"code": "internal_error", "message": "Не удалось получить ответ", "retryable": True}
