"""Инцидент ``system_error`` из исключения (§13.5): стек, логи запроса, окружение, отпечаток.

Отпечаток — тип исключения, место в нашем коде (последний кадр из ``app/``) и сообщение без
чисел, id и путей: одинаковые ошибки группируются, повтор увеличивает счётчик.
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
import traceback
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import log_capture
from app.modules.incidents import service

STACK_LIMIT = 20_000
_NOISE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # uuid
    r"|0x[0-9a-f]+|\b[0-9a-f]{16,}\b|\d+",
    re.IGNORECASE,
)


def normalize(message: str) -> str:
    return _NOISE.sub("#", message)[:200]


def location(exc: BaseException) -> str:
    """Последний кадр стека в коде приложения (``app/…``), иначе — последний вообще."""
    frames = traceback.extract_tb(exc.__traceback__)
    ours = [f for f in frames if f"{os.sep}app{os.sep}" in f.filename]
    candidates = ours or list(frames)
    if not candidates:
        return "?"
    frame = candidates[-1]
    path = frame.filename.split(f"{os.sep}app{os.sep}", 1)[-1]
    return f"app/{path}:{frame.lineno} in {frame.name}"


def fingerprint(exc: BaseException) -> str:
    raw = f"{type(exc).__name__}|{location(exc)}|{normalize(str(exc))}"
    return "system_error:" + hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()


def payload(
    exc: BaseException, *, context: dict[str, Any], request_lines: Sequence[str]
) -> dict[str, Any]:
    stack = "".join(traceback.format_exception(exc))
    return {
        "exception": type(exc).__name__,
        "message": str(exc)[:1000],
        "location": location(exc),
        "stack": stack[-STACK_LIMIT:],
        "logs": list(request_lines),
        "recent_logs": log_capture.recent_lines(100),
        "environment": {
            "app_env": os.environ.get("APP_ENV"),
            "host": socket.gethostname(),
            "pid": os.getpid(),
        },
        **context,
    }


async def report_exception(
    sessions: async_sessionmaker[AsyncSession],
    exc: BaseException,
    *,
    context: dict[str, Any],
    request_lines: Sequence[str] = (),
    user_id: UUID | None = None,
    chat_id: UUID | None = None,
    message_id: UUID | None = None,
) -> bool:
    """Записывает или обновляет ``system_error``; ошибки самой записи только логируются."""
    title = f"{type(exc).__name__}: {str(exc)[:200]}" if str(exc) else type(exc).__name__
    return await service.report(
        sessions,
        type="system_error",
        severity="high",
        title=f"{title} ({location(exc)})",
        fingerprint=fingerprint(exc),
        payload=payload(exc, context=context, request_lines=request_lines),
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
    )
