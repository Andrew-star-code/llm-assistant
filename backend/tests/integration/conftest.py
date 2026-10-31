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
MOCK_AD_IMAGE = "ai-assistant/mock-ad:test"
MOCK_AD_SVC_PASSWORD = "Svc-Test-Passw0rd!"
USER_PASSWORD = "Passw0rd!"

DEV_USERS = [
    {"login": "ivanov", "last_name": "Иванов", "first_name": "Иван", "middle_name": "Петрович",
     "title": "Руководитель ИТ-отдела", "department": "ИТ-отдел",
     "groups": ["CN=AI-Admins,CN=Users,DC=corp,DC=local"]},
    {"login": "petrov", "last_name": "Петров", "first_name": "Сергей", "middle_name": "Алексеевич",
     "title": "Бухгалтер", "department": "Бухгалтерия", "manager": "ivanov"},
    {"login": "kim", "last_name": "Ким", "first_name": "Александр", "department": "ИТ-отдел"},
]  # fmt: skip


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
