"""«Лог из консоли» для инцидентов (§13.5).

Обработчик логирования копит отформатированные строки текущего запроса (до ``REQUEST_LINES``) и
держит кольцевой буфер последних строк процесса (``RECENT_LINES``). При необработанной ошибке оба
фрагмента попадают в инцидент вместе со стеком. Строки уже прошли ``redact_secrets``, а тексты
сообщений по правилам проекта на уровне INFO не логируются.
"""

from __future__ import annotations

import logging
from collections import deque
from contextvars import ContextVar

REQUEST_LINES = 200
RECENT_LINES = 300

_request: ContextVar[deque[str] | None] = ContextVar("log_capture_request", default=None)
_recent: deque[str] = deque(maxlen=RECENT_LINES)


class CaptureHandler(logging.Handler):
    """Копит строки: все — в кольцевой буфер процесса, строки запроса — в его буфер."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return
        _recent.append(line)
        buffer = _request.get()
        if buffer is not None:
            buffer.append(line)


def start_request() -> deque[str]:
    """Новый буфер строк для текущего запроса (контекст asyncio-задачи запроса)."""
    buffer: deque[str] = deque(maxlen=REQUEST_LINES)
    _request.set(buffer)
    return buffer


def request_lines(buffer: deque[str] | None = None) -> list[str]:
    source = buffer if buffer is not None else _request.get()
    return list(source or ())


def recent_lines(limit: int = 100) -> list[str]:
    return list(_recent)[-limit:]
