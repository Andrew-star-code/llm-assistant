"""Проверка эндпоинтов моделей (§13.2 «Модели», дашборд; монитор здоровья — этап 7).

OpenAI-совместимый эндпоинт (vLLM, fake-llm) отвечает на ``GET {base_url}/models``;
text-embeddings-inference — на ``GET /health`` без ``/v1``. Проверяются параллельно с коротким
тайм-аутом, чтобы страница админки не зависала на недоступной модели.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from app.core.config import ModelEndpoint


@dataclass(frozen=True)
class Health:
    role: str
    ok: bool
    latency_ms: int | None
    detail: str | None


def _root(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


async def check(role: str, endpoint: ModelEndpoint, *, limit_s: float = 3.0) -> Health:
    headers = {}
    if endpoint.api_key:
        headers["Authorization"] = f"Bearer {endpoint.api_key.get_secret_value()}"
    urls = (
        [f"{_root(endpoint.base_url)}/health"]
        if endpoint.api == "tei"
        else [f"{endpoint.base_url.rstrip('/')}/models", f"{_root(endpoint.base_url)}/health"]
    )
    started = time.monotonic()
    detail = None
    async with httpx.AsyncClient(timeout=limit_s, headers=headers) as client:
        for url in urls:
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                detail = type(exc).__name__
                break  # сеть недоступна — второй адрес на том же хосте не поможет
            if response.status_code < 400:
                return Health(role, True, int((time.monotonic() - started) * 1000), None)
            detail = f"HTTP {response.status_code}"
    return Health(role, False, None, detail)


async def check_all(models: dict[str, ModelEndpoint], *, limit_s: float = 3.0) -> list[Health]:
    return list(
        await asyncio.gather(*(check(role, ep, limit_s=limit_s) for role, ep in models.items()))
    )
