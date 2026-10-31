"""fake-llm поднимается настоящим uvicorn на свободном порту — так проверяются SSE и обрыв."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator

import pytest
import uvicorn
from openai import AsyncOpenAI

from fake_llm.app import FakeSettings, create_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    port = _free_port()
    app = create_app(FakeSettings(slow_delay_s=0.01, embed_dim=64))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("fake-llm не стартовал за 10 с")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
async def client(base_url: str) -> AsyncIterator[AsyncOpenAI]:
    async with AsyncOpenAI(base_url=f"{base_url}/v1", api_key="test", max_retries=0) as c:
        yield c
