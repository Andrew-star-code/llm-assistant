"""ASGI-middleware: request_id, access-лог и метрики HTTP.

request_id берётся из заголовка ``X-Request-ID`` (если он корректен) или генерируется,
попадает во все записи лога этого запроса и возвращается клиенту в том же заголовке.
Тело запроса и ответа не логируется.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

import structlog
from prometheus_client import Counter, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import log_capture

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_QUIET_PATHS = frozenset({"/health", "/ready", "/metrics"})

HTTP_REQUESTS = Counter(
    "app_http_requests_total", "HTTP-запросы к api", ["method", "route", "status"]
)
HTTP_DURATION = Histogram(
    "app_http_request_duration_seconds", "Длительность HTTP-запросов к api", ["method", "route"]
)

log = structlog.stdlib.get_logger("app.http")


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER.encode():
            candidate = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.match(candidate) else None
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        # Строки лога этого запроса — для инцидента при ошибке (обработчик ошибок работает уже
        # снаружи middleware, поэтому буфер лежит и в state запроса).
        state["log_lines"] = log_capture.start_request()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                if not any(name.lower() == REQUEST_ID_HEADER.encode() for name, _ in headers):
                    headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - started
            route = getattr(scope.get("route"), "path", None) or "<unmatched>"
            method = scope["method"]
            HTTP_REQUESTS.labels(method, route, str(status_code)).inc()
            HTTP_DURATION.labels(method, route).observe(duration)
            path = scope["path"]
            level = logging.DEBUG if path in _QUIET_PATHS else logging.INFO
            log.log(
                level,
                "http.request",
                method=method,
                path=path,
                route=route,
                status=status_code,
                duration_ms=round(duration * 1000, 1),
            )
            structlog.contextvars.clear_contextvars()
