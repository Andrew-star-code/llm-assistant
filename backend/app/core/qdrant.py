"""Qdrant. На этапе 0 нужна только проверка готовности; клиент поиска — в modules/rag (этап 4)."""

from __future__ import annotations

import httpx

from app.core.config import Settings


def create_qdrant_http(settings: Settings) -> httpx.AsyncClient:
    headers = {}
    if settings.qdrant_api_key is not None:
        headers["api-key"] = settings.qdrant_api_key.get_secret_value()
    return httpx.AsyncClient(base_url=settings.qdrant_url, headers=headers, timeout=5.0)


async def ping(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    response.raise_for_status()
