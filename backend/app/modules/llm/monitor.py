"""Монитор здоровья моделей (§13.5, §16.6): задача ``models.health`` в ``scheduler`` раз в минуту.

Каждый эндпоинт проверяется (``llm.health``); после ``model_health_failures`` неудач подряд —
инцидент ``model_health`` (роль ``chat`` — critical, остальные — high) с последними строками логов
контейнера через Docker API только на чтение, если он задан. Пока модель лежит, повторы не
плодят записи; когда она снова отвечает — системный комментарий в инциденте.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ModelEndpoint, Settings
from app.modules.incidents import service as incidents
from app.modules.incidents.models import Incident, IncidentComment
from app.modules.llm.health import Health, check_all

log = structlog.stdlib.get_logger("app.llm.monitor")

LOG_TAIL = 100


def fingerprint(role: str) -> str:
    return f"model_health:{role}"


def _demux(raw: bytes) -> str:
    """Поток логов Docker без TTY: кадры «тип(1) 000 длина(4) данные»; с TTY — просто текст."""
    if len(raw) < 8 or raw[0] not in (0, 1, 2) or raw[1:4] != b"\x00\x00\x00":
        return raw.decode("utf-8", "replace")
    out: list[str] = []
    pos = 0
    while pos + 8 <= len(raw):
        size = int.from_bytes(raw[pos + 4 : pos + 8], "big")
        out.append(raw[pos + 8 : pos + 8 + size].decode("utf-8", "replace"))
        pos += 8 + size
    return "".join(out)


async def container_logs(docker_url: str, container: str, *, limit_s: float = 5.0) -> list[str]:
    """Последние строки логов контейнера (только чтение: GET /containers/{name}/logs)."""
    if docker_url.startswith("unix://"):
        transport = httpx.AsyncHTTPTransport(uds=docker_url.removeprefix("unix://"))
        base = "http://docker"
    else:
        transport = httpx.AsyncHTTPTransport()
        base = docker_url.rstrip("/")
    async with httpx.AsyncClient(transport=transport, base_url=base, timeout=limit_s) as client:
        response = await client.get(
            f"/containers/{container}/logs",
            params={"stdout": 1, "stderr": 1, "tail": LOG_TAIL, "timestamps": 1},
        )
        response.raise_for_status()
    return _demux(response.content).splitlines()[-LOG_TAIL:]


async def _logs(settings: Settings, endpoint: ModelEndpoint) -> dict[str, Any]:
    url, container = settings.monitoring.docker_url, endpoint.container
    if not url or not container:
        return {
            "container_logs": None,
            "logs_note": "Docker API не настроен (monitoring.docker_url)",
        }
    try:
        return {"container": container, "container_logs": await container_logs(url, container)}
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        note = (
            f"Контейнер «{container}» не найден (models.<роль>.container)"
            if status == 404
            else f"Docker API ответил {status}"
        )
        return {"container": container, "container_logs": None, "logs_note": note}
    except (httpx.HTTPError, OSError) as exc:
        return {
            "container": container,
            "container_logs": None,
            "logs_note": f"Docker API недоступен: {type(exc).__name__}",
        }


async def _recovered(sessions: async_sessionmaker[AsyncSession], role: str, health: Health) -> None:
    async with sessions() as db:
        incident = await db.scalar(
            select(Incident)
            .where(Incident.fingerprint == fingerprint(role), Incident.status.in_(incidents.OPEN))
            .order_by(Incident.last_seen.desc())
            .limit(1)
        )
        if incident is not None:
            text = f"Модель снова отвечает (проверка за {health.latency_ms} мс)."
            db.add(IncidentComment(incident_id=incident.id, author_id=None, text=text))
            await db.commit()


async def check_models(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], redis: Redis
) -> list[Health]:
    threshold = settings.monitoring.model_health_failures
    results = await check_all(settings.models, limit_s=settings.monitoring.model_health_timeout_s)
    for health in results:
        key = f"model_health:fails:{health.role}"
        if health.ok:
            failed = int(await redis.getdel(key) or 0)
            if failed >= threshold:
                await _recovered(sessions, health.role, health)
            continue
        failures = int(await redis.incr(key))
        await redis.expire(key, 24 * 3600)
        if failures != threshold:
            continue  # ещё рано или инцидент по этому сбою уже есть
        endpoint = settings.models[health.role]
        await incidents.report(
            sessions,
            type="model_health",
            severity="critical" if health.role == "chat" else "high",
            title=f"Модель {health.role} ({endpoint.model}) недоступна: {health.detail}",
            fingerprint=fingerprint(health.role),
            payload={
                "role": health.role,
                "model": endpoint.model,
                "base_url": endpoint.base_url,
                "detail": health.detail,
                "failures": failures,
                **await _logs(settings, endpoint),
            },
        )
        log.warning("models.unhealthy", role=health.role, detail=health.detail)
    return results
