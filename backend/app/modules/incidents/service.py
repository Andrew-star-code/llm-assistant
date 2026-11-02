"""Запись инцидентов с группировкой по отпечатку (§13.5).

Открытый инцидент с тем же отпечатком получает +1 к счётчику; решённый — открывается снова,
а «ложное срабатывание» только считает повторы (иначе ложная тревога возвращалась бы снова).
``throttle_s`` ограничивает частоту записи из горячего пути (например, «реранкер недоступен» —
не чаще раза в 10 минут, §10.4): отметка в Redis видна всем процессам api и воркера.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import utcnow
from app.modules.incidents.models import Incident

log = structlog.stdlib.get_logger("app.incidents")

OPEN = ("new", "in_progress")
STATUSES = ("new", "in_progress", "resolved", "false_positive")
SEVERITIES = ("low", "medium", "warning", "high", "critical")
HIGH = ("high", "critical")


async def report(
    sessions: async_sessionmaker[AsyncSession],
    *,
    type: str,
    severity: str,
    title: str,
    fingerprint: str | None = None,
    payload: dict[str, Any] | None = None,
    user_id: UUID | None = None,
    chat_id: UUID | None = None,
    message_id: UUID | None = None,
    redis: Redis | None = None,
    throttle_s: int = 0,
    keep: tuple[str, ...] = (),
) -> bool:
    """Создаёт или обновляет инцидент; False — запись пропущена из-за ``throttle_s``.

    Ошибка записи инцидента не должна ломать основной сценарий — она только логируется.
    ``keep`` — ключи payload, которые повтор не перезаписывает (например, первая цитата).
    """
    key = fingerprint or f"{type}:{title}"
    if redis is not None and throttle_s > 0:
        fresh = await redis.set(f"incident:throttle:{key}", "1", ex=throttle_s, nx=True)
        if not fresh:
            return False
    try:
        async with sessions() as db:
            await upsert(
                db,
                type=type,
                severity=severity,
                title=title,
                fingerprint=key,
                payload=payload,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                keep=keep,
            )
            await db.commit()
    except Exception:
        log.exception("incidents.report_failed", type=type)
        return False
    log.warning("incidents.reported", type=type, severity=severity, fingerprint=key)
    return True


async def upsert(
    db: AsyncSession,
    *,
    type: str,
    severity: str,
    title: str,
    fingerprint: str,
    payload: dict[str, Any] | None,
    user_id: UUID | None,
    chat_id: UUID | None,
    message_id: UUID | None,
    keep: tuple[str, ...] = (),
) -> Incident:
    now = utcnow()
    existing = await db.scalar(
        select(Incident)
        .where(Incident.fingerprint == fingerprint)
        .order_by(Incident.last_seen.desc())
        .limit(1)
    )
    if existing is not None:
        existing.occurrences += 1
        existing.last_seen = now
        if payload:
            previous = existing.payload or {}
            kept = {k: previous[k] for k in keep if k in previous}
            existing.payload = {**payload, **kept}
        if existing.status == "resolved":
            existing.status = "new"  # повтор после решения открывает инцидент снова
            existing.resolution = None
        return existing
    incident = Incident(
        type=type,
        severity=severity,
        status="new",
        fingerprint=fingerprint,
        title=title[:300],
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        payload=payload,
        occurrences=1,
        first_seen=now,
        last_seen=now,
    )
    db.add(incident)
    return incident
