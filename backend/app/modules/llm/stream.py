"""Разбор стрима OpenAI-совместимого API vLLM в события оркестратора.

vLLM с ``--reasoning-parser`` отдаёт размышления отдельным полем дельты: в новых версиях
``reasoning``, в старых — ``reasoning_content``; понимаем оба.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from openai.types.chat import ChatCompletionChunk


@dataclass(frozen=True)
class Delta:
    kind: Literal["reasoning", "content"]
    text: str


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int | None


@dataclass(frozen=True)
class Finish:
    reason: str | None


@dataclass(frozen=True)
class ToolCallDelta:
    """Кусок вызова инструмента: id и имя приходят в первом куске, аргументы — частями."""

    index: int
    id: str | None
    name: str | None
    arguments: str


StreamItem = Delta | Usage | Finish | ToolCallDelta


def _reasoning_of(delta: Any) -> str | None:
    extra = getattr(delta, "model_extra", None) or {}
    value = extra.get("reasoning") or extra.get("reasoning_content")
    return value if isinstance(value, str) and value else None


async def parse_stream(chunks: AsyncIterator[ChatCompletionChunk]) -> AsyncIterator[StreamItem]:
    async for chunk in chunks:
        if chunk.usage is not None:
            details = chunk.usage.completion_tokens_details
            yield Usage(
                prompt_tokens=chunk.usage.prompt_tokens,
                completion_tokens=chunk.usage.completion_tokens,
                reasoning_tokens=details.reasoning_tokens if details else None,
            )
        for choice in chunk.choices:
            if reasoning := _reasoning_of(choice.delta):
                yield Delta("reasoning", reasoning)
            if choice.delta.content:
                yield Delta("content", choice.delta.content)
            for call in choice.delta.tool_calls or []:
                function = call.function
                yield ToolCallDelta(
                    index=call.index,
                    id=call.id,
                    name=function.name if function else None,
                    arguments=(function.arguments or "") if function else "",
                )
            if choice.finish_reason:
                yield Finish(choice.finish_reason)
