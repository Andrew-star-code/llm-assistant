from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_when_all_dependencies_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert set(body["checks"]) == {"postgres", "redis", "qdrant"}


async def test_ready_reports_failed_dependency(app: FastAPI, client: httpx.AsyncClient) -> None:
    async def broken() -> None:
        raise ConnectionError("connection refused")

    async def hanging() -> None:
        await asyncio.sleep(10)

    app.state.readiness_checks = {**app.state.readiness_checks, "redis": broken, "qdrant": hanging}
    app.state.settings.readiness_timeout_s = 0.05

    response = await client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["postgres"]["status"] == "ok"
    assert body["checks"]["redis"] == {
        "status": "error",
        "duration_ms": body["checks"]["redis"]["duration_ms"],
        "error": "ConnectionError: connection refused",
    }
    assert "нет ответа" in body["checks"]["qdrant"]["error"]


async def test_openapi_available_outside_prod(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/ready" in response.json()["paths"]
