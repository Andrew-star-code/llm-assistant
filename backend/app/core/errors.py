"""Единый формат ошибок API.

Тело любой ошибки: ``{"error": {"code": "...", "message": "...", "request_id": "..."}}``.
``message`` — текст для пользователя; подробности (стек, причины) — только в логах и инцидентах.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = structlog.stdlib.get_logger("app.errors")


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Ожидаемая ошибка предметной области с HTTP-статусом и кодом для клиента."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _response(
    request: Request, status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    request_id = _request_id(request)
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=request_id, details=details)
    )
    # Обработчик Exception работает снаружи RequestContextMiddleware, поэтому заголовок — здесь.
    headers = {"X-Request-ID": request_id} if request_id else None
    return JSONResponse(
        status_code=status, content=body.model_dump(exclude_none=True), headers=headers
    )


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # pragma: no cover — обработчик зарегистрирован на AppError
        raise exc
    return _response(request, exc.status_code, exc.code, exc.message, exc.details)


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # TODO(stage-7): создавать инцидент system_error с захватом логов запроса (§13.5).
    log.exception("unhandled_error", exc_type=type(exc).__name__, request_id=_request_id(request))
    return _response(request, 500, "internal_error", "Внутренняя ошибка сервера")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
