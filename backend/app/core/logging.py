"""Логирование: structlog, JSON в stdout, request_id в каждой записи.

Правила (§15, §20): не логировать пароли, токены, cookie и тексты сообщений на уровне INFO.
Процессор ``redact_secrets`` — страховка: значения ключей из ``SENSITIVE_KEYS`` заменяются
на ``***`` даже если их передали по ошибке.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.core.config import LoggingSettings
from app.core.log_capture import CaptureHandler

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "authorization",
        "cookie",
        "set-cookie",
        "session_id",
        "csrf_token",
        "bind_password",
    }
)
REDACTED = "***"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: REDACTED if str(k).lower() in SENSITIVE_KEYS else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(_redact(v) for v in value)
    return value


def redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact(event_dict[key])
    return event_dict


def configure_logging(settings: LoggingSettings) -> None:
    """Настраивает structlog и stdlib logging (uvicorn, sqlalchemy) на единый формат."""
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_secrets,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if settings.format == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    def formatter(render: structlog.types.Processor) -> logging.Formatter:
        return structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                render,
            ],
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter(renderer))
    # Те же строки — в буферы для инцидентов (core/log_capture): лог запроса и последние строки.
    # Без цветов: ANSI-коды консоли в карточке инцидента нечитаемы.
    capture = CaptureHandler()
    capture.setFormatter(
        formatter(
            renderer if settings.format == "json" else structlog.dev.ConsoleRenderer(colors=False)
        )
    )

    root = logging.getLogger()
    root.handlers[:] = [handler, capture]
    root.setLevel(settings.level)

    # Болтливые библиотеки даже в DEBUG пишут не ниже INFO — иначе их строки забивают лог.
    for name in ("httpcore", "httpx", "asyncio", "watchfiles", "multipart", "python_multipart"):
        logging.getLogger(name).setLevel(max(root.level, logging.INFO))

    # uvicorn пишет свой access-лог; у нас он свой, с request_id (см. request_context).
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").handlers[:] = []
    logging.getLogger("uvicorn.access").propagate = False


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
