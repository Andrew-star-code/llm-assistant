"""Интеграционные тесты: настоящие PostgreSQL и Redis (testcontainers) и mock-AD (Samba AD DC).

Контейнеры поднимаются один раз на сессию pytest; между тестами таблицы очищаются, Redis
сбрасывается. mock-AD стартует ~40 с и только если тесту нужен провайдер ldap.
Образы — те же, что в deploy/compose (закреплены по digest).
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

import docker
import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer
from testcontainers.core.container import DockerContainer

from app.core.config import REPO_ROOT, Settings, get_settings, load_settings
from app.main import create_app

POSTGRES_IMAGE = (
    "postgres:17.11-bookworm"
    "@sha256:839fbb5a4942a7758dd93e18b42ea5649807491a0545b5eeeb8f0b8bb11857a5"
)
REDIS_IMAGE = (
    "redis:7.4.12-alpine@sha256:8da19c7399dca900c6822a1cf30f9d2285585e2c4b457ff4095b0f4500054d3f"
)
QDRANT_IMAGE = (
    "qdrant/qdrant:v1.19.2@sha256:b7b0444c4c351c970b98e90a6f89c2ee4287c65b44e52b4cb503fa5b2aa927ad"
)
MOCK_AD_IMAGE = "ai-assistant/mock-ad:test"
MOCK_AD_SVC_PASSWORD = "Svc-Test-Passw0rd!"
USER_PASSWORD = "Passw0rd!"

DEV_USERS = [
    {
        "login": "ivanov",
        "last_name": "Иванов",
        "first_name": "Иван",
        "middle_name": "Петрович",
        "title": "Руководитель ИТ-отдела",
        "department": "ИТ-отдел",
        "groups": ["CN=AI-Admins,CN=Users,DC=corp,DC=local"],
    },
    {
        "login": "petrov",
        "last_name": "Петров",
        "first_name": "Сергей",
        "middle_name": "Алексеевич",
        "title": "Бухгалтер",
        "department": "Бухгалтерия",
        "manager": "ivanov",
    },
    {"login": "kim", "last_name": "Ким", "first_name": "Александр", "department": "ИТ-отдел"},
]


@dataclass(frozen=True)
class Infra:
    database_url: str
    redis_url: str


@pytest.fixture(scope="session")
def infra() -> Iterator[Infra]:
    with (
        PostgresContainer(POSTGRES_IMAGE, username="t", password="t", dbname="t") as pg,
        RedisContainer(REDIS_IMAGE) as rd,
    ):
        host = pg.get_container_host_ip()
        url = f"postgresql+asyncpg://t:t@{host}:{pg.get_exposed_port(5432)}/t"
        os.environ["APP_DATABASE_URL"] = url
        get_settings.cache_clear()
        command.upgrade(Config(str(REPO_ROOT / "backend" / "alembic.ini")), "head")
        os.environ.pop("APP_DATABASE_URL")
        get_settings.cache_clear()
        redis_url = f"redis://{rd.get_container_host_ip()}:{rd.get_exposed_port(6379)}/0"
        yield Infra(database_url=url, redis_url=redis_url)


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    """Qdrant для поиска по вложениям; стартует только для тестов, которым он нужен."""
    container = DockerContainer(QDRANT_IMAGE).with_exposed_ports(6333)
    with container:
        url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(6333)}"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{url}/readyz", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise AssertionError("Qdrant не поднялся за 60 с")
        yield url


@dataclass(frozen=True)
class MockAd:
    url: str
    ca_file: Path
    password_file: Path
    container: DockerContainer

    def exec(self, *cmd: str) -> str:
        code, output = self.container.get_wrapped_container().exec_run(list(cmd))
        text = output.decode() if isinstance(output, bytes) else ""
        assert code == 0, text
        return text


@pytest.fixture(scope="session")
def mock_ad(tmp_path_factory: pytest.TempPathFactory) -> Iterator[MockAd]:
    client = docker.from_env()
    client.images.build(path=str(REPO_ROOT / "deploy" / "mock-ad"), tag=MOCK_AD_IMAGE, rm=True)
    export = tmp_path_factory.mktemp("mock-ad-export")
    export.chmod(0o777)
    secret = tmp_path_factory.mktemp("secrets") / "ldap_bind_password"
    secret.write_text(MOCK_AD_SVC_PASSWORD, encoding="utf-8")
    container = (
        DockerContainer(MOCK_AD_IMAGE)
        .with_env("MOCK_AD_ADMIN_PASSWORD", "Adm1n-Test-Passw0rd!")
        .with_env("MOCK_AD_SVC_PASSWORD", MOCK_AD_SVC_PASSWORD)
        .with_env("MOCK_AD_USER_PASSWORD", USER_PASSWORD)
        .with_exposed_ports(636)
        .with_volume_mapping(str(export), "/export", "rw")
        .with_kwargs(cap_add=["SYS_ADMIN"], hostname="dc1", domainname="corp.local")
    )
    with container:
        deadline = time.monotonic() + 180
        healthy = False
        while time.monotonic() < deadline:
            logs = container.get_logs()[0].decode(errors="replace")
            if "запуск samba" in logs and (export / "ca.pem").exists():
                code, _ = container.get_wrapped_container().exec_run(
                    ["ldapsearch", "-x", "-H", "ldap://127.0.0.1", "-b", "", "-s", "base"]
                )
                if code == 0:
                    healthy = True
                    break
            time.sleep(2)
        assert healthy, "mock-AD не поднялся за 180 с"
        port = container.get_exposed_port(636)
        yield MockAd(f"ldaps://localhost:{port}", export / "ca.pem", secret, container)


def make_settings(infra: Infra, tmp_path: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": infra.database_url,
        "redis_url": infra.redis_url,
        "storage": {"root": str(tmp_path / "storage")},
        "auth": {
            "providers": ["dev"],
            "bootstrap_admins": ["ivanov"],
            "dev_users": DEV_USERS,
            "session": {"cookie_secure": False},
        },
        "ldap": {"urls": [], "sync_interval_minutes": 0},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return load_settings(**base)


def ldap_overrides(ad: MockAd, **ldap: Any) -> dict[str, Any]:
    return {
        "auth": {"providers": ["ldap", "dev"]},
        "ldap": {
            "urls": [ad.url],
            "ca_cert_file": str(ad.ca_file),
            "bind_password_file": str(ad.password_file),
            "sync_interval_minutes": 0,
            **ldap,
        },
    }


@pytest.fixture
async def clean_db(infra: Infra) -> None:
    engine = create_async_engine(infra.database_url)
    async with engine.begin() as conn:
        # audit_log защищён триггером от DELETE; TRUNCATE его не вызывает.
        await conn.execute(
            text(
                "TRUNCATE audit_log, login_events, sessions, user_roles, role_permissions, roles, "
                "permissions, app_settings, users CASCADE"
            )
        )
    await engine.dispose()
    import redis.asyncio as aioredis

    client = aioredis.Redis.from_url(infra.redis_url)
    await client.flushdb()
    await client.aclose()


class ApiClient:
    """httpx-клиент с cookie и автоматическим CSRF-заголовком для изменяющих запросов."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.http = client

    async def _csrf(self) -> str:
        token = self.http.cookies.get("csrftoken")
        if not token:
            token = (await self.http.get("/api/auth/csrf")).json()["csrf_token"]
        return str(token)

    async def get(self, url: str, **kw: Any) -> httpx.Response:
        return await self.http.get(url, **kw)

    async def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        headers = {"X-CSRF-Token": await self._csrf(), **kw.pop("headers", {})}
        return await self.http.request(method, url, headers=headers, **kw)

    async def post(self, url: str, **kw: Any) -> httpx.Response:
        return await self.request("POST", url, **kw)

    async def login(self, login: str, password: str = "", provider: str = "dev") -> httpx.Response:
        return await self.post(
            "/api/auth/login", json={"login": login, "password": password, "provider": provider}
        )


@pytest.fixture
async def make_client(clean_db: None) -> AsyncIterator[Any]:
    """Фабрика: ``await make_client(settings)`` → (app, ApiClient); можно несколько клиентов."""
    stack: list[tuple[FastAPI, httpx.AsyncClient, Any]] = []

    async def factory(settings: Settings) -> tuple[FastAPI, ApiClient]:
        app = create_app(settings)
        ctx = app.router.lifespan_context(app)
        await ctx.__aenter__()
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        http = httpx.AsyncClient(transport=transport, base_url="http://test")
        stack.append((app, http, ctx))
        return app, ApiClient(http)

    yield factory
    for _, http, ctx in reversed(stack):
        await http.aclose()
        await ctx.__aexit__(None, None, None)


# ------------------------------------------------------------------ fake-llm и чат


@pytest.fixture(scope="session")
def fake_llm_url() -> Iterator[str]:
    """fake-llm настоящим uvicorn в отдельном потоке — с реальным стримингом."""
    import socket
    import threading

    import uvicorn

    from fake_llm.app import FakeSettings
    from fake_llm.app import create_app as create_fake

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(
            create_fake(FakeSettings(slow_delay_s=0.05)),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "fake-llm не стартовал"
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}/v1"
    server.should_exit = True
    thread.join(timeout=5)


DATA_GATEWAY_SECRET = "test-data-gateway-secret"


@pytest.fixture(scope="session")
def data_gateway_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """data-gateway в потоке: каталог репозитория, источник — SQLite с тестовым справочником."""
    import socket
    import threading

    import uvicorn
    from data_gateway.app import GatewaySettings
    from data_gateway.app import create_app as create_gateway
    from data_gateway.testing import make_catalog

    catalog = make_catalog(tmp_path_factory.mktemp("data-gateway"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    app = create_gateway(GatewaySettings(catalog_dir=catalog, secret=DATA_GATEWAY_SECRET))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "data-gateway не стартовал"
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def chat_settings(infra: Infra, tmp_path: Path, fake_llm_url: str, **overrides: Any) -> Settings:
    models: dict[str, Any] = {
        role: {"base_url": fake_llm_url, "model": f"fake-{role}"}
        for role in ("chat", "utility", "guard", "rerank", "embed")
    }
    models.update(overrides.pop("models", {}))  # подмена отдельных ролей, например rerank
    return make_settings(
        infra,
        tmp_path,
        models=models,
        # Автоповтор запроса к модели — без секундных пауз, чтобы тесты ошибок не тормозили.
        chat={
            "heartbeat_seconds": 1,
            "stream_ttl_seconds": 60,
            "model_retry_backoff_seconds": 0.01,
            **overrides.pop("chat", {}),
        },
        # Воркер в тестах — та же функция в потоке api (без Celery и брокера).
        worker={"eager": True},
        **overrides,
    )


@dataclass(frozen=True)
class SseEvent:
    id: int
    event: str
    data: dict[str, Any]


def parse_sse(text: str) -> list[SseEvent]:
    import json

    events = []
    for block in text.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":") or ": " not in line:
                continue
            key, value = line.split(": ", 1)
            fields[key] = value
        if fields.get("event") == "ping":
            continue  # heartbeat — без id, позицию потока не сдвигает
        if "event" in fields:
            events.append(SseEvent(int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return events


async def read_stream(
    client: ApiClient, message_id: str, last_event_id: int | None = None
) -> list[SseEvent]:
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}
    response = await client.get(f"/api/messages/{message_id}/stream", headers=headers, timeout=30)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


async def send(client: ApiClient, chat_id: str, text: str, **body: Any) -> dict[str, Any]:
    response = await client.post(f"/api/chats/{chat_id}/messages", json={"content": text, **body})
    assert response.status_code == 202, response.text
    result: dict[str, Any] = response.json()
    return result


async def new_chat(client: ApiClient) -> str:
    response = await client.post("/api/chats", json={})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])
