"""Дашборд: метрики GPU из Prometheus/DCGM (§16.6) и поведение без адреса или при сбое."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.modules.admin import dashboard

METRICS = {
    "DCGM_FI_DEV_GPU_UTIL": [("0", "87"), ("1", "12")],
    "DCGM_FI_DEV_FB_USED": [("0", "70000"), ("1", "1000")],
    "DCGM_FI_DEV_FB_FREE": [("0", "11000"), ("1", "80000")],
}


def _handler(request: httpx.Request) -> httpx.Response:
    query = request.url.params["query"]
    result = [{"metric": {"gpu": gpu}, "value": [0, value]} for gpu, value in METRICS[query]]
    return httpx.Response(200, json={"status": "success", "data": {"result": result}})


@pytest.fixture
def mock_prometheus(monkeypatch: pytest.MonkeyPatch) -> None:
    real = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


async def test_gpus_from_prometheus(mock_prometheus: None) -> None:
    settings = Settings(monitoring={"prometheus_url": "http://prometheus:9090"})
    gpus, note = await dashboard.gpus(settings)
    assert note is None and gpus is not None
    assert [(g.gpu, g.utilization, g.memory_total_mb) for g in gpus] == [
        ("0", 87.0, 81000.0),
        ("1", 12.0, 81000.0),
    ]


async def test_gpus_without_prometheus_or_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    gpus, note = await dashboard.gpus(Settings())
    assert gpus is None and note and "prometheus_url" in note

    real = httpx.AsyncClient

    def broken(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(lambda r: httpx.Response(503)), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", broken)
    gpus, note = await dashboard.gpus(Settings(monitoring={"prometheus_url": "http://p:9090"}))
    assert gpus is None and note and "недоступен" in note
