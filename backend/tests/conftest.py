"""Общие фикстуры тестов бэкенда."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import REPO_ROOT, AppEnv, Settings, load_settings
from app.main import create_app

CONFIG_DIR = REPO_ROOT / "config"


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тесты не зависят от APP_* окружения разработчика."""
    import os

    for key in list(os.environ):
        if key.startswith("APP_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("APP_CONFIG_DIR", str(CONFIG_DIR))
    monkeypatch.setenv("APP_ENV", AppEnv.TEST.value)


@pytest.fixture
def config_dir() -> Path:
    return CONFIG_DIR


@pytest.fixture
def settings() -> Settings:
    return load_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    application = create_app(settings)

    async def ok() -> None:
        return None

    # ASGITransport не запускает lifespan, поэтому проверки готовности задаём напрямую.
    application.state.readiness_checks = {"postgres": ok, "redis": ok, "qdrant": ok}
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
