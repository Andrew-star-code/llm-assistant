"""Запрос к модели и цикл инструментов (§8.4).

``run_loop``: запрос со стримингом → вызовы инструментов → их результаты → снова запрос, не больше
``tools.max_iterations``. Сообщения ведёт ``LoopContext`` (бюджет контекста). ``stream`` — один
запрос с автоповтором при кратком сбое модели, пока пользователю не ушло ни слова.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import openai
import structlog
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from app.modules.completions.context import LoopContext
from app.modules.completions.retrieval import emit_sources
from app.modules.completions.state import (
    Deps,
    GenerationResult,
)
from app.modules.completions.streaming import (
    EventWriter,
    cancel_key,
)
from app.modules.llm.stream import Delta, Finish, ToolCallDelta, Usage, parse_stream
from app.modules.tools.base import ToolContext
from app.modules.tools.executor import ToolOutcome, execute, preview_label_params

log = structlog.stdlib.get_logger("app.completions")

CANCEL_CHECK_INTERVAL = 0.2


@dataclass
class PendingCall:
    id: str = ""
    name: str = ""
    arguments: str = ""


MAX_ITERATIONS_NOTE = (
    "\n\nНе удалось завершить ответ: превышено число шагов с инструментами. "
    "Попробуйте уточнить или разбить запрос."
)


def transient(exc: Exception) -> bool:
    """Краткий сбой модели, который может пройти сам: соединение, перегрузка, 5xx, обрыв.

    Тайм-аут — не он: модель уже молчала ``timeout_s``, ждать столько же ещё раз незачем.
    """
    if isinstance(exc, openai.APITimeoutError):
        return False
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code >= 500 or exc.status_code == 429
    # Обрыв посреди стрима SDK тоже отдаёт как APIConnectionError.
    return isinstance(exc, openai.APIConnectionError)


async def run_loop(
    deps: Deps,
    message_id: UUID,
    role: str,
    loop: LoopContext,
    params: dict[str, Any],
    writer: EventWriter,
    result: GenerationResult,
    started: float,
    *,
    schemas: list[dict[str, Any]],
    allowed: set[str],
    context: ToolContext,
) -> None:
    """Цикл инструментов (§8.4): запрос → вызовы инструментов → их результаты → снова запрос.

    Сообщения ведёт ``LoopContext``: перед каждым запросом он возвращает их в бюджет контекста.
    """
    max_iterations = deps.settings.tools.max_iterations
    for iteration in range(1, max_iterations + 1):
        if iteration == 1 and await deps.redis.exists(cancel_key(message_id)):
            # «Стоп» пришёл, пока задание ждало исполнителя: модель не вызываем.
            result.status, result.finish_reason = "stopped", "stop_requested"
            return
        text, calls = await stream(
            deps, message_id, role, loop.messages, params, writer, result, started, schemas=schemas
        )
        if result.status == "stopped" or not calls:
            return
        loop.add_calls(
            {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in calls
                ],
            }
        )
        outcomes = await asyncio.gather(
            *(run_tool(deps, context, call, writer, allowed) for call in calls)
        )
        for outcome in outcomes:
            outcome.iteration = iteration
            result.tools.append(outcome)
            result.files.extend(outcome.files)
            loop.add_result(outcome.call_id, outcome.content)
        if await deps.redis.exists(cancel_key(message_id)):
            result.status = "stopped"
            return
        loop.fit()
    # Модель всё ещё вызывает инструменты — честно сообщаем, что не уложились.
    # TODO(stage-7): инцидент уровня warning (§8.4).
    result.content.append(MAX_ITERATIONS_NOTE)
    await writer.delta("content", MAX_ITERATIONS_NOTE)
    result.finish_reason = "max_iterations"


async def run_tool(
    deps: Deps, context: ToolContext, call: PendingCall, writer: EventWriter, allowed: set[str]
) -> ToolOutcome:
    from app.modules.tools.registry import get_tool

    tool = get_tool(call.name) if call.name in allowed else None
    visible = tool is None or tool.visibility == "visible"
    # Скрытые инструменты не порождают событий SSE (§9.6).
    if visible:
        await writer.emit(
            "tool.start",
            {
                "call_id": call.id,
                "tool": call.name,
                "label": tool.status_label if tool else "tools.unknown",
                "params": preview_label_params(tool, call.arguments),
            },
        )
    outcome = await execute(
        context,
        call_id=call.id,
        name=call.name,
        raw_arguments=call.arguments,
        allowed=allowed,
        limit=deps.settings.tools.result_max_chars,
    )
    if visible:
        await writer.emit(
            "tool.end",
            {
                "call_id": call.id,
                "tool": call.name,
                "status": outcome.status,
                "label": outcome.label,
                "params": outcome.label_params,
            },
        )
        if outcome.sources:
            await emit_sources(writer, context.sources)
        for file in outcome.files:
            await writer.emit(
                "file",
                {
                    "file_id": file["file_id"],
                    "name": file["filename"],
                    "mime": file["mime"],
                    "size": file["size"],
                    "preview": file["has_preview"],
                },
            )
    return outcome


async def stream(
    deps: Deps,
    message_id: UUID,
    role: str,
    messages: list[dict[str, Any]],
    params: dict[str, Any],
    writer: EventWriter,
    result: GenerationResult,
    started: float,
    *,
    schemas: list[dict[str, Any]],
) -> tuple[str, list[PendingCall]]:
    """Запрос к модели с автоповтором при кратком сбое (``chat.model_retries``).

    Повтор возможен, пока запрос не дал ни одной дельты: пользователь ещё ничего не увидел,
    а работа прошлых шагов цикла инструментов не пропадает. После первой дельты повтор
    задвоил бы текст — ошибка уходит пользователю, дальше решает он (§7.4: «Повторить»).
    """
    retries = deps.settings.chat.model_retries
    delay = deps.settings.chat.model_retry_backoff_seconds
    for attempt in range(retries):
        seen = len(result.content) + len(result.reasoning)
        try:
            return await stream_once(
                deps, message_id, role, messages, params, writer, result, started, schemas=schemas
            )
        except Exception as exc:
            emitted = len(result.content) + len(result.reasoning) != seen
            if emitted or not transient(exc):
                raise
            log.warning(
                "completions.model_retry",
                message_id=str(message_id),
                attempt=attempt + 1,
                error=type(exc).__name__,
            )
            result.model_retries += 1
        await asyncio.sleep(delay * 2**attempt)
        if await deps.redis.exists(cancel_key(message_id)):
            # «Стоп» во время ожидания: ответа ещё нет, повторять незачем.
            result.status = "stopped"
            result.finish_reason = "stop_requested"
            return "", []
    return await stream_once(
        deps, message_id, role, messages, params, writer, result, started, schemas=schemas
    )


async def stream_once(
    deps: Deps,
    message_id: UUID,
    role: str,
    messages: list[dict[str, Any]],
    params: dict[str, Any],
    writer: EventWriter,
    result: GenerationResult,
    started: float,
    *,
    schemas: list[dict[str, Any]],
) -> tuple[str, list[PendingCall]]:
    """Один запрос к модели со стримингом: текст этой итерации и вызовы инструментов."""
    client = deps.registry.client(role)
    extra: dict[str, Any] = {"tools": schemas, "tool_choice": "auto"} if schemas else {}
    stream: AsyncStream[ChatCompletionChunk] = await client.chat.completions.create(  # type: ignore[call-overload]
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        **params,
        **extra,
    )
    last_check = time.monotonic()
    text: list[str] = []
    calls: dict[int, PendingCall] = {}
    try:
        async for item in parse_stream(stream):
            if isinstance(item, Delta):
                now = time.monotonic()
                if result.ttft_ms is None:
                    result.ttft_ms = int((now - started) * 1000)
                if item.kind == "reasoning" and result.reasoning_started is None:
                    result.reasoning_started = now
                if (
                    item.kind == "content"
                    and result.reasoning_started is not None
                    and result.reasoning_ms is None
                ):
                    # Время размышления — от первой дельты размышлений до первой дельты ответа.
                    result.reasoning_ms = int((now - result.reasoning_started) * 1000)
                if item.kind == "content":
                    result.content.append(item.text)
                    text.append(item.text)
                else:
                    result.reasoning.append(item.text)
                await writer.delta(item.kind, item.text)
            elif isinstance(item, ToolCallDelta):
                call = calls.setdefault(item.index, PendingCall())
                call.id = call.id or (item.id or "")
                call.name = call.name or (item.name or "")
                call.arguments += item.arguments
            elif isinstance(item, Usage):
                result.add_usage(item)
            elif isinstance(item, Finish):
                result.finish_reason = item.reason
            if time.monotonic() - last_check >= CANCEL_CHECK_INTERVAL:
                last_check = time.monotonic()
                if await deps.redis.exists(cancel_key(message_id)):
                    result.status = "stopped"
                    result.finish_reason = "stop_requested"
                    break
    finally:
        await stream.close()
    if result.status != "stopped" and await deps.redis.exists(cancel_key(message_id)):
        result.status = "stopped"
    pending = [c for _, c in sorted(calls.items()) if c.name]
    for index, call in enumerate(pending):
        call.id = call.id or f"call_{index}"
    return "".join(text), pending
