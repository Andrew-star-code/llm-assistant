"""Здоровье исполнителя генерации (ADR-0013, §13.5): проверка раз в минуту из ``scheduler``.

В режиме очереди ответы генерирует только сервис ``generator``. Если его нет, сообщения ждут
``generation.queue_ttl_seconds`` и завершаются как прерванные — без этой проверки причину видно
только в логах. После ``monitoring.model_health_failures`` проверок подряд без исполнителя —
инцидент ``generator_health`` (critical); когда исполнитель вернулся — комментарий в инциденте.
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.completions.executor import queue_stats
from app.modules.incidents import service as incidents
from app.modules.incidents.models import Incident, IncidentComment

log = structlog.stdlib.get_logger("app.generator")

FINGERPRINT = "generator_health"
FAILS_KEY = "generator_health:fails"


async def check_executor(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], redis: Redis
) -> bool:
    """True — исполнитель есть (или он не нужен: ``generation.mode = inline``)."""
    if settings.generation.mode != "queue":
        return True
    threshold = settings.monitoring.model_health_failures
    length, executors = await queue_stats(redis)
    if executors:
        failed = int(await redis.getdel(FAILS_KEY) or 0)
        if failed >= threshold:
            await _recovered(sessions, executors)
        return True
    failures = int(await redis.incr(FAILS_KEY))
    await redis.expire(FAILS_KEY, 24 * 3600)
    if failures == threshold:  # раньше — рано, позже — инцидент по этому сбою уже есть
        await incidents.report(
            sessions,
            type="generator_health",
            severity="critical",
            title="Нет исполнителя генерации: ответы не начинаются",
            fingerprint=FINGERPRINT,
            payload={
                "queue_length": length,
                "failures": failures,
                "queue_ttl_seconds": settings.generation.queue_ttl_seconds,
                "hint": "Сервис generator не запущен или не отмечается в Redis: "
                "docker compose ps generator, логи generator, "
                "python -m app.cli generator check.",
            },
        )
        log.warning("generator.unhealthy", queue_length=length)
    return False


async def _recovered(sessions: async_sessionmaker[AsyncSession], executors: int) -> None:
    async with sessions() as db:
        incident = await db.scalar(
            select(Incident)
            .where(Incident.fingerprint == FINGERPRINT, Incident.status.in_(incidents.OPEN))
            .order_by(Incident.last_seen.desc())
            .limit(1)
        )
        if incident is not None:
            text = f"Исполнитель генерации снова работает (исполнителей: {executors})."
            db.add(IncidentComment(incident_id=incident.id, author_id=None, text=text))
            await db.commit()
