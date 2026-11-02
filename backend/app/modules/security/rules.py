"""Правила подозрительности (§13.4): флаги событий входа и инциденты безопасности.

| Правило | Действие |
| --- | --- |
| 5 неудач по логину за 15 минут | блокировка логина (``bruteforce``) |
| 20 неудач с IP за 15 минут | блокировка IP на час + инцидент «перебор паролей» |
| успех сразу после неудач | флаг ``after_failures`` |
| новая подсеть для пользователя | флаг ``new_subnet`` (низкий) |
| вход вне рабочего времени | флаг ``off_hours`` (низкий) |
| одновременные сессии из разных подсетей | флаг ``concurrent_subnets`` |
| попытка заблокированного или отключённого в AD | флаг ``blocked_attempt`` |
| больше 60 сообщений за 10 минут | инцидент «аномальный объём запросов» |
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.auth.models import UserSession
from app.modules.incidents import service as incidents
from app.modules.security.ipblocks import Network, subnet_of
from app.modules.security.models import IpBlock, LoginEvent

# Уровень флага — для подсветки в журнале входов.
FLAG_LEVELS = {
    "after_failures": "medium",
    "concurrent_subnets": "medium",
    "blocked_attempt": "medium",
    "new_subnet": "low",
    "off_hours": "low",
}
BLOCKED_REASONS = frozenset({"blocked", "ad_disabled"})
HISTORY = 200


def _subnet(ip: str | None, settings: Settings) -> Network | None:
    if not ip:
        return None
    sec = settings.security
    return subnet_of(ip, sec.subnet_prefix_v4, sec.subnet_prefix_v6)


def off_hours(now: datetime, settings: Settings) -> bool:
    hours = settings.security.work_hours
    local = now.astimezone(ZoneInfo(settings.chat.timezone))
    start, end = time.fromisoformat(hours.start), time.fromisoformat(hours.end)
    return local.isoweekday() not in hours.weekdays or not start <= local.time() < end


def failure_flags(reason: str) -> list[str]:
    return ["blocked_attempt"] if reason in BLOCKED_REASONS else []


async def success_flags(
    db: AsyncSession,
    *,
    user_id: UUID,
    ip: str | None,
    now: datetime,
    settings: Settings,
    failures_before: int,
    trusted: bool,
) -> list[str]:
    flags: list[str] = []
    if failures_before > 0:
        flags.append("after_failures")
    current = _subnet(ip, settings)
    if current is not None and not trusted:
        previous = (
            await db.scalars(
                select(LoginEvent.ip)
                .where(
                    LoginEvent.user_id == user_id,
                    LoginEvent.success.is_(True),
                    LoginEvent.ip.is_not(None),
                )
                .order_by(LoginEvent.ts.desc())
                .limit(HISTORY)
            )
        ).all()
        known = {_subnet(p, settings) for p in previous}
        # Первый вход — не «новая подсеть»: сравнивать не с чем.
        if previous and current not in known:
            flags.append("new_subnet")
    if off_hours(now, settings):
        flags.append("off_hours")
    if current is not None:
        others = (
            await db.scalars(
                select(UserSession.ip).where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                    UserSession.ip.is_not(None),
                )
            )
        ).all()
        if any(_subnet(o, settings) not in (None, current) for o in others):
            flags.append("concurrent_subnets")
    return flags


async def block_bruteforce_ip(
    db: AsyncSession,
    *,
    ip: str,
    settings: Settings,
    now: datetime,
    trusted: bool,
) -> None:
    """20 неудач с IP: блокировка на ``lock_minutes`` (кроме доверенных подсетей) и инцидент.

    Пишет в ту же транзакцию, что и событие входа; commit — у вызывающего.
    """
    rule = settings.auth.bruteforce.per_ip
    until = now + timedelta(minutes=rule.lock_minutes)
    logins = sorted(
        set(
            (
                await db.scalars(
                    select(LoginEvent.login_attempted).where(
                        LoginEvent.ip == ip,
                        LoginEvent.success.is_(False),
                        LoginEvent.ts >= now - timedelta(minutes=rule.window_minutes),
                    )
                )
            ).all()
        )
    )[:50]
    network = subnet_of(ip, 32, 128)
    if not trusted and network is not None:
        db.add(
            IpBlock(
                cidr=str(network), source="auto", until=until,
                reason=f"Перебор паролей: {rule.max_failures} неудач за {rule.window_minutes} мин",
            )
        )  # fmt: skip
    await incidents.upsert(
        db,
        type="security",
        severity="high",
        title=f"Перебор паролей с {ip}"
        + (" (доверенная подсеть, без блокировки)" if trusted else ""),
        fingerprint=f"security:bruteforce:{ip}",
        payload={
            "rule": "bruteforce_ip",
            "ip": ip,
            "failures": rule.max_failures,
            "window_minutes": rule.window_minutes,
            "blocked_until": None if trusted else until.isoformat(),
            "trusted": trusted,
            "logins": logins,
        },
        user_id=None,
        chat_id=None,
        message_id=None,
    )


async def track_message(
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    login: str,
    settings: Settings,
) -> None:
    """Аномальный объём: больше ``max_messages`` за окно — инцидент (один на окно)."""
    rule = settings.security.message_burst
    key = f"security:burst:{user_id}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, rule.window_minutes * 60, nx=True)
        count, _ = await pipe.execute()
    if int(count) != rule.max_messages + 1:
        return
    await incidents.report(
        sessions,
        type="security",
        severity="warning",
        title=f"Аномальный объём запросов: {login} — больше {rule.max_messages} сообщений "
        f"за {rule.window_minutes} мин",
        fingerprint=f"security:burst:{user_id}",
        payload={
            "rule": "message_burst",
            "login": login,
            "max_messages": rule.max_messages,
            "window_minutes": rule.window_minutes,
        },
        user_id=user_id,
    )
