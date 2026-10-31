"""Исполнение вызовов инструментов (§8.4): валидация, тайм-аут, обрезка результата, трассировка.

Ошибка инструмента не роняет генерацию: модель получает текст ошибки и решает, что делать дальше.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import ValidationError

from app.modules.tools.base import ToolContext, ToolError
from app.modules.tools.registry import get_tool

log = structlog.stdlib.get_logger("app.tools")


@dataclass
class ToolOutcome:
    call_id: str
    tool: str
    arguments: dict[str, Any] | None
    content: str
    status: str  # ok | error | timeout
    duration_ms: int
    visibility: str
    label: str
    label_params: dict[str, str] = field(default_factory=dict)
    files: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] | None = None
    iteration: int = 0  # номер шага цикла инструментов, заполняет генерация


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[…результат обрезан: показаны {limit} из {len(text)} символов]"


async def execute(
    ctx: ToolContext, *, call_id: str, name: str, raw_arguments: str, allowed: set[str], limit: int
) -> ToolOutcome:
    started = time.monotonic()
    tool = get_tool(name) if name in allowed else None

    def outcome(content: str, status: str, **extra: Any) -> ToolOutcome:
        return ToolOutcome(
            call_id=call_id,
            tool=name,
            arguments=extra.pop("arguments", None),
            content=truncate(content, limit),
            status=status,
            duration_ms=int((time.monotonic() - started) * 1000),
            visibility=tool.visibility if tool else "visible",
            label=tool.status_label if tool else "tools.unknown",
            **extra,
        )

    if tool is None:
        return outcome(f"Ошибка: инструмент «{name}» недоступен.", "error")
    try:
        arguments = json.loads(raw_arguments or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("аргументы должны быть объектом JSON")
        args = tool.args_model.model_validate(arguments)
    except (ValueError, ValidationError) as exc:
        return outcome(f"Ошибка аргументов инструмента {name}: {str(exc)[:1000]}", "error")
    params = tool.label_params(args)
    try:
        result = await asyncio.wait_for(tool.run(ctx, args), timeout=tool.timeout_s)
    except TimeoutError:
        return outcome(
            f"Инструмент {name} не уложился в {tool.timeout_s} с.",
            "timeout",
            arguments=arguments,
            label_params=params,
        )
    except ToolError as exc:
        return outcome(f"Ошибка: {exc}", "error", arguments=arguments, label_params=params)
    except Exception as exc:
        log.exception("tools.failed", tool=name)
        return outcome(
            f"Инструмент {name} завершился с ошибкой ({type(exc).__name__}).",
            "error",
            arguments=arguments,
            label_params=params,
        )
    return outcome(
        result.content,
        "ok",
        arguments=arguments,
        label_params=params,
        files=result.files,
        data=result.data,
    )
