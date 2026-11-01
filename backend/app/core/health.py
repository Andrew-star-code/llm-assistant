"""Проверки живости и готовности.

* ``GET /health`` — процесс жив (для restart-политики Docker); зависимости не трогает.
* ``GET /ready`` — готов принимать трафик: PostgreSQL, Redis и Qdrant отвечают.
  Если хотя бы одна проверка не прошла — 503 с подробностями по каждой.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

ReadinessCheck = Callable[[], Awaitable[None]]

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class CheckResult(BaseModel):
    status: Literal["ok", "error"]
    duration_ms: float
    error: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckResult]


@router.get("/health", response_model=HealthResponse, operation_id="health")
async def health() -> HealthResponse:
    return HealthResponse()


async def _run_check(check: ReadinessCheck, timeout_s: float) -> CheckResult:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(check(), timeout=timeout_s)
    except TimeoutError:
        error: str | None = f"нет ответа за {timeout_s} с"
    except Exception as exc:
        # Текст исключения может быть длинным; DSN с паролем драйверы в него не включают.
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    else:
        error = None
    return CheckResult(
        status="error" if error else "ok",
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        error=error,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Зависимость недоступна"}},
    operation_id="ready",
)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    checks: dict[str, ReadinessCheck] = request.app.state.readiness_checks
    timeout_s: float = request.app.state.settings.readiness_timeout_s
    results = await asyncio.gather(*(_run_check(c, timeout_s) for c in checks.values()))
    by_name = dict(zip(checks, results, strict=True))
    ok = all(r.status == "ok" for r in results)
    if not ok:
        response.status_code = 503
    return ReadinessResponse(status="ready" if ok else "not_ready", checks=by_name)
