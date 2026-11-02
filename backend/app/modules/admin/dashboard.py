"""Дашборд админки (§13.2, §16.6): активность, токены, время ответа, качество, модели, очереди.

Цифры считаются запросами к Postgres по ``messages`` и ``feedback`` (подробный учёт расхода по
вызовам — ``usage_records``, модуль ``limits``); тестовые чаты редактора сценариев не учитываются.
GPU — из Prometheus/DCGM, если задан ``monitoring.prometheus_url`` (на сервере — этап 10), иначе
блок без данных.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import httpx
import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Date, and_, case, cast, distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import DbDep, SettingsDep
from app.modules.admin.system_router import ModelHealthOut
from app.modules.auth.deps import CurrentUser, require
from app.modules.chats.models import Chat, Message
from app.modules.feedback.models import Feedback
from app.modules.files.models import File
from app.modules.incidents import service as incidents
from app.modules.incidents.models import Incident
from app.modules.kb.models import KbDocument, KbImport
from app.modules.llm.health import check_all
from app.modules.rbac.permissions import Perm
from app.modules.scenarios.models import Scenario

log = structlog.stdlib.get_logger("app.admin.dashboard")

router = APIRouter(prefix="/admin", tags=["admin"])

Viewer = Annotated[CurrentUser, Depends(require(Perm.DASHBOARD_VIEW))]


class ActiveUsers(BaseModel):
    day: int
    week: int
    month: int


class DayPoint(BaseModel):
    day: date
    active_users: int
    messages: int
    answers: int
    tokens: int
    errors: int
    ttft_avg_ms: int | None
    ttft_p95_ms: int | None


class ScenarioUsage(BaseModel):
    name: str
    chats: int
    messages: int


class Quality(BaseModel):
    answers: int
    errors: int
    error_share: float | None
    likes: int
    dislikes: int
    like_share: float | None
    ttft_avg_ms: int | None
    ttft_p95_ms: int | None


class Queues(BaseModel):
    kb_queued: int
    kb_processing: int
    kb_errors: int
    imports_running: int
    attachments_pending: int


class Incidents(BaseModel):
    open: int
    high: int


class Gpu(BaseModel):
    gpu: str
    utilization: float | None
    memory_used_mb: float | None
    memory_total_mb: float | None


class Dashboard(BaseModel):
    days: int
    active_users: ActiveUsers
    series: list[DayPoint]
    scenarios: list[ScenarioUsage]
    quality: Quality
    queues: Queues
    incidents: Incidents
    models: list[ModelHealthOut]
    gpus: list[Gpu] | None
    gpu_note: str | None


def _real() -> Any:
    """Сообщения из настоящих чатов (тестовые чаты редактора не считаются)."""
    return Chat.is_test.is_(False)


async def _active(db: AsyncSession, since: datetime) -> int:
    return int(
        await db.scalar(
            select(func.count(distinct(Chat.user_id)))
            .select_from(Message)
            .join(Chat, Chat.id == Message.chat_id)
            .where(_real(), Message.role == "user", Message.created_at >= since)
        )
        or 0
    )


async def _series(db: AsyncSession, since: datetime, days: int, tz: str) -> list[DayPoint]:
    day = cast(func.timezone(tz, Message.created_at), Date).label("day")
    is_answer = Message.role == "assistant"
    rows = (
        await db.execute(
            select(
                day,
                func.count(distinct(case((Message.role == "user", Chat.user_id)))),
                func.count().filter(Message.role == "user"),
                func.count().filter(is_answer),
                func.coalesce(
                    func.sum(
                        func.coalesce(Message.prompt_tokens, 0)
                        + func.coalesce(Message.completion_tokens, 0)
                    ),
                    0,
                ),
                func.count().filter(is_answer, Message.status == "error"),
                func.avg(Message.ttft_ms).filter(is_answer),
                func.percentile_cont(0.95).within_group(Message.ttft_ms).filter(is_answer),
            )
            .join(Chat, Chat.id == Message.chat_id)
            .where(_real(), Message.created_at >= since)
            .group_by(day)
        )
    ).all()
    by_day = {r[0]: r for r in rows}
    today = utcnow().astimezone(ZoneInfo(tz)).date()
    series = []
    for offset in range(days - 1, -1, -1):
        d = today - timedelta(days=offset)
        r = by_day.get(d)
        series.append(
            DayPoint(
                day=d,
                active_users=int(r[1]) if r else 0,
                messages=int(r[2]) if r else 0,
                answers=int(r[3]) if r else 0,
                tokens=int(r[4]) if r else 0,
                errors=int(r[5]) if r else 0,
                ttft_avg_ms=int(r[6]) if r and r[6] is not None else None,
                ttft_p95_ms=int(r[7]) if r and r[7] is not None else None,
            )
        )
    return series


async def _scenarios(db: AsyncSession, since: datetime) -> list[ScenarioUsage]:
    rows = (
        await db.execute(
            select(Scenario.name, func.count(distinct(Chat.id)), func.count(Message.id))
            .join(Chat, Chat.scenario_id == Scenario.id)
            .join(Message, Message.chat_id == Chat.id)
            .where(_real(), Message.role == "user", Message.created_at >= since)
            .group_by(Scenario.name)
            .order_by(func.count(Message.id).desc())
            .limit(10)
        )
    ).all()
    return [ScenarioUsage(name=n, chats=int(c), messages=int(m)) for n, c, m in rows]


async def _quality(db: AsyncSession, since: datetime) -> Quality:
    answers, errors, ttft_avg, ttft_p95 = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Message.status == "error"),
                func.avg(Message.ttft_ms),
                func.percentile_cont(0.95).within_group(Message.ttft_ms),
            )
            .join(Chat, Chat.id == Message.chat_id)
            .where(_real(), Message.role == "assistant", Message.created_at >= since)
        )
    ).one()
    votes = dict(
        (
            await db.execute(
                select(Feedback.rating, func.count())
                .where(Feedback.created_at >= since)
                .group_by(Feedback.rating)
            )
        ).all()
    )
    likes, dislikes = int(votes.get(1, 0)), int(votes.get(-1, 0))
    return Quality(
        answers=int(answers),
        errors=int(errors),
        error_share=round(errors / answers, 4) if answers else None,
        likes=likes,
        dislikes=dislikes,
        like_share=round(likes / (likes + dislikes), 4) if likes + dislikes else None,
        ttft_avg_ms=int(ttft_avg) if ttft_avg is not None else None,
        ttft_p95_ms=int(ttft_p95) if ttft_p95 is not None else None,
    )


async def _queues(db: AsyncSession) -> Queues:
    docs = dict(
        (
            await db.execute(
                select(KbDocument.status, func.count())
                .where(KbDocument.deleted_at.is_(None))
                .group_by(KbDocument.status)
            )
        ).all()
    )
    # В done импорт переводит только чтение (kb.service.import_out), поэтому running без документов
    # в работе уже закончен, даже если страницу базы никто не открывал.
    unfinished = exists().where(
        KbDocument.import_id == KbImport.id,
        KbDocument.deleted_at.is_(None),
        KbDocument.status.in_(("queued", "processing")),
    )
    imports = await db.scalar(
        select(func.count())
        .select_from(KbImport)
        .where(or_(KbImport.status == "scanning", and_(KbImport.status == "running", unfinished)))
    )
    pending = await db.scalar(
        select(func.count()).where(
            File.kind == "upload",
            File.deleted_at.is_(None),
            File.parse_status.in_(("pending", "processing")),
        )
    )
    return Queues(
        kb_queued=int(docs.get("queued", 0)),
        kb_processing=int(docs.get("processing", 0)),
        kb_errors=int(docs.get("error", 0)),
        imports_running=int(imports or 0),
        attachments_pending=int(pending or 0),
    )


async def _incidents(db: AsyncSession) -> Incidents:
    open_ = Incident.status.in_(incidents.OPEN)  # как в списке и счётчике меню
    total, high = (
        await db.execute(
            select(
                func.count().filter(open_),
                func.count().filter(open_, Incident.severity.in_(("high", "critical"))),
            )
        )
    ).one()
    return Incidents(open=int(total), high=int(high))


async def gpus(settings: Settings) -> tuple[list[Gpu] | None, str | None]:
    """Загрузка и память GPU из Prometheus (DCGM exporter); без адреса — нет данных."""
    url = settings.monitoring.prometheus_url
    if not url:
        return None, "Метрики GPU появятся на сервере: задайте monitoring.prometheus_url"
    queries = {
        "utilization": "DCGM_FI_DEV_GPU_UTIL",
        "used": "DCGM_FI_DEV_FB_USED",
        "free": "DCGM_FI_DEV_FB_FREE",
    }
    values: dict[str, dict[str, float]] = {}
    try:
        async with httpx.AsyncClient(timeout=settings.monitoring.timeout_s) as client:
            for name, query in queries.items():
                response = await client.get(
                    f"{url.rstrip('/')}/api/v1/query", params={"query": query}
                )
                response.raise_for_status()
                for item in response.json()["data"]["result"]:
                    gpu = str(item["metric"].get("gpu", item["metric"].get("GPU_I_ID", "?")))
                    values.setdefault(gpu, {})[name] = float(item["value"][1])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("dashboard.prometheus_failed", error=str(exc)[:200])
        return None, f"Prometheus недоступен ({type(exc).__name__})"
    result = []
    for gpu, v in sorted(values.items()):
        used, free = v.get("used"), v.get("free")
        result.append(
            Gpu(
                gpu=gpu,
                utilization=v.get("utilization"),
                memory_used_mb=used,
                memory_total_mb=used + free if used is not None and free is not None else None,
            )
        )
    return result, None


@router.get("/dashboard", response_model=Dashboard, operation_id="adminDashboard")
async def dashboard(
    db: DbDep,
    settings: SettingsDep,
    _: Viewer,
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> Dashboard:
    now = utcnow()
    since = now - timedelta(days=days)
    tz = settings.chat.timezone
    health, (gpu_list, gpu_note) = await asyncio.gather(
        check_all(settings.models, limit_s=2.0), gpus(settings)
    )
    return Dashboard(
        days=days,
        active_users=ActiveUsers(
            day=await _active(db, now - timedelta(days=1)),
            week=await _active(db, now - timedelta(days=7)),
            month=await _active(db, now - timedelta(days=30)),
        ),
        series=await _series(db, since, days, tz),
        scenarios=await _scenarios(db, since),
        quality=await _quality(db, since),
        queues=await _queues(db),
        incidents=await _incidents(db),
        models=[ModelHealthOut(**vars(h)) for h in health],
        gpus=gpu_list,
        gpu_note=gpu_note,
    )
