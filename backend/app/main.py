"""Сборка FastAPI-приложения: настройки, логирование, middleware, роутеры.

Запуск: ``uvicorn app.main:create_app --factory``. Если конфиг невалиден, процесс завершается
с кодом 1 и понятным сообщением ещё до приёма запросов.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, FastAPI
from prometheus_client import make_asgi_app

from app import __version__
from app.core import db, qdrant, redis
from app.core.config import AppEnv, Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.health import ReadinessCheck
from app.core.health import router as health_router
from app.core.logging import configure_logging
from app.core.request_context import RequestContextMiddleware
from app.core.storage import LocalStorage
from app.modules.admin.chats_router import router as admin_chats_router
from app.modules.admin.dashboard import router as admin_dashboard_router
from app.modules.admin.feedback_router import router as admin_feedback_router
from app.modules.admin.roles_router import router as admin_roles_router
from app.modules.admin.router import router as admin_router
from app.modules.admin.security_router import router as admin_security_router
from app.modules.admin.settings_router import public as branding_router
from app.modules.admin.settings_router import router as admin_settings_router
from app.modules.admin.system_router import router as admin_system_router
from app.modules.auth.deps import verify_csrf
from app.modules.auth.providers.base import AuthProvider
from app.modules.auth.providers.dev import DevProvider
from app.modules.auth.providers.ldap import LdapDirectory, LdapProvider
from app.modules.auth.router import router as auth_router
from app.modules.auth.service import LoginService
from app.modules.auth.sessions import SessionStore
from app.modules.chats.router import router as chats_router
from app.modules.completions.executor import watch_queue
from app.modules.completions.generation import GenerationManager
from app.modules.completions.prompt import PromptRenderer
from app.modules.completions.router import router as completions_router
from app.modules.data.admin_router import router as admin_data_router
from app.modules.exports.router import router as exports_router
from app.modules.feedback.router import router as feedback_router
from app.modules.files.router import router as files_router
from app.modules.incidents.router import router as incidents_router
from app.modules.kb.admin_router import router as kb_admin_router
from app.modules.kb.router import router as kb_router
from app.modules.limits.admin_router import router as admin_limits_router
from app.modules.limits.router import router as limits_router
from app.modules.limits.service import Limits
from app.modules.llm.registry import ModelRegistry
from app.modules.rbac.service import ensure_system_rbac
from app.modules.scenarios.admin_router import router as scenarios_admin_router
from app.modules.scenarios.router import router as scenarios_router
from app.modules.scenarios.service import seed as seed_scenarios
from app.modules.security.bruteforce import BruteforceGuard
from app.modules.security.ipblocks import Blocklist
from app.modules.users.router import router as profile_router
from app.modules.users.sync import run_periodic_sync
from app.workers.dispatch import Dispatcher

log = structlog.stdlib.get_logger("app")

API_PREFIX = "/api"


def _read_secret_file(path: Path | None) -> str:
    return path.read_text(encoding="utf-8").strip() if path else ""


def init_services(app: FastAPI) -> None:
    """Создаёт клиенты и сервисы в app.state. Вызывается из lifespan и из тестов."""
    settings: Settings = app.state.settings
    engine = db.create_engine(settings)
    redis_client = redis.create_redis(settings)
    app.state.db_engine = engine
    app.state.db_sessions = db.create_session_factory(engine)
    app.state.redis = redis_client
    app.state.qdrant_http = qdrant.create_qdrant_http(settings)
    app.state.storage = LocalStorage(settings.storage.root)
    app.state.sessions = SessionStore(redis_client, settings.auth.session)
    app.state.bruteforce = BruteforceGuard(redis_client, settings.auth.bruteforce)

    providers: dict[str, AuthProvider] = {}
    app.state.ldap_directory = None
    if "ldap" in settings.auth.providers:
        directory = LdapDirectory(
            settings.ldap, read_password=lambda: _read_secret_file(settings.ldap.bind_password_file)
        )
        app.state.ldap_directory = directory
        providers["ldap"] = LdapProvider(directory)
    if "dev" in settings.auth.providers:
        providers["dev"] = DevProvider(settings.auth.dev_users)
    app.state.models = ModelRegistry(settings)
    app.state.dispatcher = Dispatcher(settings)
    app.state.limits = Limits(settings, redis_client)
    app.state.generations = GenerationManager(
        settings=settings,
        redis=redis_client,
        sessions=app.state.db_sessions,
        registry=app.state.models,
        renderer=PromptRenderer(settings.config_dir / "prompts"),
        storage=app.state.storage,
        dispatcher=app.state.dispatcher,
        limits=app.state.limits,
    )
    app.state.blocklist = Blocklist(ttl_s=settings.security.blocklist_cache_s, redis=redis_client)
    app.state.login_service = LoginService(
        settings=settings,
        providers=providers,
        sessions=app.state.sessions,
        bruteforce=app.state.bruteforce,
        storage=app.state.storage,
        blocklist=app.state.blocklist,
    )


async def close_services(app: FastAPI) -> None:
    await app.state.generations.shutdown()
    await app.state.models.close()
    await app.state.qdrant_http.aclose()
    await app.state.redis.aclose()
    await app.state.db_engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    init_services(app)
    engine = app.state.db_engine
    redis_client = app.state.redis
    qdrant_http = app.state.qdrant_http
    checks: dict[str, ReadinessCheck] = {
        "postgres": lambda: db.ping(engine),
        "redis": lambda: redis.ping(redis_client),
        "qdrant": lambda: qdrant.ping(qdrant_http),
    }
    app.state.readiness_checks = checks

    try:
        async with app.state.db_sessions() as session:
            await ensure_system_rbac(session)
    except Exception:
        # Например, миграции ещё не применены: /ready покажет, что не так, процесс не падает.
        log.exception("rbac.bootstrap_failed")

    try:
        async with app.state.db_sessions() as session:
            await seed_scenarios(session, settings.config_dir)
    except Exception:
        log.exception("scenarios.seed_failed")

    try:
        await app.state.generations.mark_orphaned_interrupted()
    except Exception:
        log.exception("completions.orphans_check_failed")

    # Ответы упавших или остановленных процессов не должны висеть в «streaming» (§8.5).
    sweep_task = asyncio.create_task(app.state.generations.sweep_orphans())
    background = [sweep_task]
    if settings.generation.mode == "queue":
        # Длина очереди и число исполнителей — в /metrics (§16.6, ADR-0013).
        background.append(asyncio.create_task(watch_queue(redis_client)))
    sync_task = None
    if app.state.ldap_directory is not None and settings.ldap.sync_interval_minutes > 0:
        sync_task = asyncio.create_task(
            run_periodic_sync(
                redis_client,
                app.state.db_sessions,
                app.state.ldap_directory,
                settings=settings,
                storage=app.state.storage,
                sessions=app.state.sessions,
            )
        )

    log.info("app.started", env=settings.env.value, version=__version__)
    try:
        yield
    finally:
        for task in background:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if sync_task is not None:
            sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await sync_task
        await close_services(app)
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
        swagger_ui_oauth2_redirect_url=None,
        openapi_url=None if is_prod else f"{API_PREFIX}/openapi.json",
    )
    app.state.settings = settings

    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)

    # Все бизнес-роутеры — под /api и с проверкой CSRF на изменяющих запросах (§15).
    api = APIRouter(prefix=API_PREFIX, dependencies=[Depends(verify_csrf)])
    api.include_router(auth_router)
    api.include_router(profile_router)
    api.include_router(chats_router)
    api.include_router(completions_router)
    api.include_router(feedback_router)
    api.include_router(files_router)
    api.include_router(kb_router)
    api.include_router(limits_router)
    api.include_router(kb_admin_router)
    api.include_router(incidents_router)
    api.include_router(scenarios_router)
    api.include_router(scenarios_admin_router)
    api.include_router(admin_chats_router)
    api.include_router(admin_dashboard_router)
    api.include_router(admin_feedback_router)
    api.include_router(admin_system_router)
    api.include_router(admin_settings_router)
    api.include_router(admin_roles_router)
    api.include_router(admin_security_router)
    api.include_router(admin_limits_router)
    api.include_router(admin_data_router)
    api.include_router(branding_router)
    api.include_router(exports_router)
    api.include_router(admin_router)
    app.include_router(api)

    # Метрики для Prometheus; наружу не публикуются — nginx не проксирует /metrics (§16.6).
    app.mount("/metrics", make_asgi_app())
    return app
