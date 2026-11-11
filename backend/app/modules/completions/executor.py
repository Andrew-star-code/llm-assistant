"""Исполнитель генерации — сервис ``generator`` (ADR-0013).

``api`` в режиме ``generation.mode = queue`` кладёт задания в список Redis ``gen:queue``;
исполнитель забирает их и запускает те же задачи ``GenerationManager``, что раньше жили в ``api``.
Перезапуск ``api`` идущие ответы не трогает, а исполнитель по SIGTERM перестаёт брать задания и
дорабатывает свои.

* Задание исполняется один раз: оно удаляется из очереди при получении. Упавший посреди ответа
  исполнитель оставляет ``interrupted`` — повтор с начала задвоил бы события, уже ушедшие
  пользователю.
* Задание берётся, только если жив ключ ``gen:alive:<id>`` (его поставил ``api`` на время
  ожидания): просроченное уже помечено прерванным, выполнять его нельзя.
* Не больше ``generation.max_concurrent`` ответов сразу — остальные ждут в очереди.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import UUID

import structlog
from redis.asyncio import Redis

import app.models  # noqa: F401 — регистрирует все таблицы: в этом процессе нет роутеров api
from app.core import db
from app.core import redis as redis_core
from app.core.config import Settings
from app.core.storage import LocalStorage
from app.modules.completions.generation import GenerationManager
from app.modules.completions.prompt import PromptRenderer
from app.modules.completions.streaming import (
    ALIVE_TTL_SECONDS,
    EXECUTOR_TTL_SECONDS,
    QUEUE_KEY,
    alive_key,
    executor_key,
)
from app.modules.limits.service import Limits
from app.modules.llm.registry import ModelRegistry
from app.workers.dispatch import Dispatcher

log = structlog.stdlib.get_logger("app.generator")

POLL_SECONDS = 1


def parse_job(raw: str | bytes) -> tuple[UUID, str | None] | None:
    """Задание очереди: ``{"message_id": …, "request_id": …}``; мусор — ``None``."""
    try:
        job = json.loads(raw)
        request_id = job.get("request_id")
        return UUID(job["message_id"]), request_id if isinstance(request_id, str) else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


class Executor:
    def __init__(
        self, manager: GenerationManager, redis: Redis, settings: Settings, name: str | None = None
    ) -> None:
        self.manager = manager
        self.redis = redis
        self.settings = settings.generation
        self.name = name or socket.gethostname()
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        """Перестать брать задания и доработать идущие (обработчик SIGTERM)."""
        self._stopping.set()

    async def run(self) -> None:
        """Цикл очереди; возвращается после ``stop()`` и доработки идущих ответов."""
        heartbeat = asyncio.create_task(self._heartbeat())
        log.info("generator.started", name=self.name, max_concurrent=self.settings.max_concurrent)
        try:
            while not self._stopping.is_set():
                try:
                    await self._step()
                except Exception:
                    # Redis недоступен и т. п.: исполнитель не должен умирать вместе с ответами.
                    log.exception("generator.loop_failed")
                    await asyncio.sleep(POLL_SECONDS)
            await self.manager.drain(self.settings.shutdown_grace_seconds)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            with suppress(Exception):
                await self.redis.delete(executor_key(self.name))
            log.info("generator.stopped", name=self.name)

    async def _step(self) -> None:
        tasks = list(self.manager.tasks.values())
        if len(tasks) >= self.settings.max_concurrent:
            # Мест нет: ждём, пока какой-нибудь ответ закончится; задания остаются в очереди.
            await asyncio.wait(tasks, timeout=POLL_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            return
        item = await self.redis.blpop([QUEUE_KEY], timeout=POLL_SECONDS)
        if item is None:
            return
        if self._stopping.is_set():
            # SIGTERM пришёл, пока ждали очередь: задание — обратно в голову, следующему.
            await self.redis.lpush(QUEUE_KEY, item[1])
            return
        job = parse_job(item[1])
        if job is None:
            log.warning("generator.bad_job")
            return
        message_id, request_id = job
        # Берём, только если задание ещё ждёт: истёкший ключ значит, что ответ уже прерван.
        if not await self.redis.set(alive_key(message_id), "1", ex=ALIVE_TTL_SECONDS, xx=True):
            log.warning("generator.job_expired", message_id=str(message_id))
            return
        self.manager.launch(message_id, request_id or "")

    async def _heartbeat(self) -> None:
        """Отметка «исполнитель жив» для healthcheck (``generator check``) и мониторинга."""
        while True:
            with suppress(Exception):
                await self.redis.set(
                    executor_key(self.name),
                    json.dumps({"active": len(self.manager.tasks)}),
                    ex=EXECUTOR_TTL_SECONDS,
                )
            await asyncio.sleep(EXECUTOR_TTL_SECONDS / 3)


async def serve(
    settings: Settings, *, install_signals: Callable[[Executor], None] | None = None
) -> None:
    """Процесс исполнителя: свои клиенты БД, Redis и моделей, цикл очереди, аккуратное закрытие."""
    engine = db.create_engine(settings)
    redis = redis_core.create_redis(settings)
    registry = ModelRegistry(settings)
    manager = GenerationManager(
        settings=settings,
        redis=redis,
        sessions=db.create_session_factory(engine),
        registry=registry,
        renderer=PromptRenderer(settings.config_dir / "prompts"),
        storage=LocalStorage(settings.storage.root),
        dispatcher=Dispatcher(settings),
        limits=Limits(settings, redis),
    )
    executor = Executor(manager, redis, settings)
    if install_signals is not None:
        install_signals(executor)
    try:
        await executor.run()
    finally:
        closers: list[Awaitable[None]] = [registry.close(), redis.aclose(), engine.dispose()]
        for closer in closers:
            with suppress(Exception):
                await closer


async def alive(settings: Settings, name: str | None = None) -> bool:
    """Есть ли свежая отметка исполнителя ``name`` (по умолчанию — этого контейнера)."""
    redis = redis_core.create_redis(settings)
    try:
        return bool(await redis.exists(executor_key(name or socket.gethostname())))
    finally:
        await redis.aclose()
