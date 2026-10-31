from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.core.errors import NotFoundError


async def test_request_id_is_generated(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert len(response.headers["x-request-id"]) == 32


async def test_request_id_is_propagated(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


async def test_invalid_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert response.headers["x-request-id"] != "bad id\twith spaces"


async def test_app_error_format(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get("/test/not-found")
    async def _not_found() -> None:
        raise NotFoundError("Чат не найден")

    response = await client.get("/test/not-found", headers={"X-Request-ID": "rid-1"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Чат не найден", "request_id": "rid-1"}
    }


async def test_unhandled_error_hides_details(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get("/test/boom")
    async def _boom() -> None:
        raise RuntimeError("secret internal detail")

    response = await client.get("/test/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "secret internal detail" not in response.text
    assert body["error"]["request_id"] == response.headers["x-request-id"]
