"""Сборка FastAPI-приложения: настройки, логирование, middleware, роутеры.

Запуск: ``uvicorn app.main:create_app --factory``. Если конфиг невалиден, процесс завершается
с кодом 1 и понятным сообщением ещё до приёма запросов.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from app import __version__
from app.core import db, qdrant, redis
from app.core.config import AppEnv, Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.health import ReadinessCheck
from app.core.health import router as health_router
from app.core.logging import configure_logging
from app.core.request_context import RequestContextMiddleware

log = structlog.stdlib.get_logger("app")

API_PREFIX = "/api"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = db.create_engine(settings)
    redis_client = redis.create_redis(settings)
    qdrant_http = qdrant.create_qdrant_http(settings)

    app.state.db_engine = engine
    app.state.db_sessions = db.create_session_factory(engine)
    app.state.redis = redis_client
    app.state.qdrant_http = qdrant_http
    checks: dict[str, ReadinessCheck] = {
        "postgres": lambda: db.ping(engine),
        "redis": lambda: redis.ping(redis_client),
        "qdrant": lambda: qdrant.ping(qdrant_http),
    }
    app.state.readiness_checks = checks

    log.info("app.started", env=settings.env.value, version=__version__)
    try:
        yield
    finally:
        await qdrant_http.aclose()
        await redis_client.aclose()
        await engine.dispose()
        log.info("app.stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.logging)

    is_prod = settings.env == AppEnv.PROD
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if is_prod else f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=None if is_prod else f"{API_PREFIX}/openapi.json",
    )
    app.state.settings = settings

    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)
    # Бизнес-роутеры модулей подключаются здесь с префиксом API_PREFIX (этапы 1+).

    # Метрики для Prometheus; наружу не публикуются — nginx не проксирует /metrics (§16.6).
    app.mount("/metrics", make_asgi_app())
    return app
