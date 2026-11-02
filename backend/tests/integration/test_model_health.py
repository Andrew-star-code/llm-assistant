"""Монитор здоровья моделей (этап 7, §13.5): остановленная модель → инцидент model_health с
логами контейнера; повторы его не плодят; восстановление — системный комментарий.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis

from app.modules.llm import monitor
from tests.integration.conftest import Infra, chat_settings

DOCKER_LOG = (
    b"\x02\x00\x00\x00\x00\x00\x00\x22CUDA out of memory, shutting down\n"
    b"\x01\x00\x00\x00\x00\x00\x00\x0fEngine stopped\n"
)


async def test_stopped_model_creates_model_health_incident(
    make_client: Any,
    infra: Infra,
    tmp_path: Path,
    fake_llm_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Критерий этапа 7: остановка контейнера модели создаёт инцидент model_health."""
    settings = chat_settings(
        infra, tmp_path, fake_llm_url, monitoring={"docker_url": "http://docker-proxy:2375"}
    )
    live = settings.models["utility"]
    # «Контейнер остановлен»: на адресе модели никто не слушает.
    settings.models["utility"] = live.model_copy(
        update={"base_url": "http://127.0.0.1:9/v1", "container": "llm-utility"}
    )
    app, admin = await make_client(settings)
    await admin.login("ivanov")

    requested: list[str] = []

    def docker(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, content=DOCKER_LOG)

    real = httpx.AsyncHTTPTransport
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_: httpx.MockTransport(docker))
    redis = Redis.from_url(infra.redis_url)
    try:
        first = await monitor.check_models(settings, app.state.db_sessions, redis)
        assert "utility" in {h.role for h in first if not h.ok}
        page = (await admin.get("/api/admin/incidents", params={"type": "model_health"})).json()
        assert page["items"] == []  # одна неудача — ещё не инцидент
        for _ in range(3):
            await monitor.check_models(settings, app.state.db_sessions, redis)
        items = (await admin.get("/api/admin/incidents", params={"type": "model_health"})).json()
        [item] = [i for i in items["items"] if "utility" in i["title"]]
        assert item["severity"] == "high" and item["occurrences"] == 1
        card = (await admin.get(f"/api/admin/incidents/{item['id']}")).json()
        payload = card["payload"]
        assert payload["role"] == "utility" and payload["container"] == "llm-utility"
        assert payload["container_logs"] == ["CUDA out of memory, shutting down", "Engine stopped"]
        assert requested == ["/containers/llm-utility/logs"]

        # Модель снова отвечает — системный комментарий в том же инциденте.
        monkeypatch.setattr(httpx, "AsyncHTTPTransport", real)
        settings.models["utility"] = live
        await monitor.check_models(settings, app.state.db_sessions, redis)
        card = (await admin.get(f"/api/admin/incidents/{item['id']}")).json()
        [comment] = card["comments"]
        assert comment["author"] is None and comment["text"].startswith("Модель снова отвечает")
        summary = (await admin.get("/api/admin/incidents/summary")).json()
        assert summary["new_high"] >= 1
    finally:
        await redis.aclose()


def test_docker_log_stream_with_and_without_tty() -> None:
    assert monitor._demux(DOCKER_LOG).splitlines() == [
        "CUDA out of memory, shutting down",
        "Engine stopped",
    ]
    assert monitor._demux(b"plain tty output\n") == "plain tty output\n"


async def test_logs_note_explains_missing_container(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import ModelEndpoint, Settings

    def missing(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "No such container"})

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_: httpx.MockTransport(missing))
    settings = Settings(monitoring={"docker_url": "http://docker-proxy:2375"})
    endpoint = ModelEndpoint(base_url="http://llm:8000/v1", model="m", container="llm-x")
    result = await monitor._logs(settings, endpoint)
    assert result["container_logs"] is None
    assert result["logs_note"] == "Контейнер «llm-x» не найден (models.<роль>.container)"
