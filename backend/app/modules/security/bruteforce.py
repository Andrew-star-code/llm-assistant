"""Защита от перебора паролей (§6.2 п. 3, §13.4): счётчики неудач по логину и по IP в Redis.

После ``max_failures`` неудач за ``window_minutes`` логин (или IP) блокируется на ``lock_minutes``.
Порог по логину должен быть ниже политики блокировки AD — иначе перебор через портал будет
блокировать сотрудникам доменные учётки.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from redis.asyncio import Redis

from app.core.config import BruteforceRule, BruteforceSettings

_PREFIX = "bf"


def _keys(kind: str, value: str) -> tuple[str, str]:
    return f"{_PREFIX}:fail:{kind}:{value}", f"{_PREFIX}:lock:{kind}:{value}"


@dataclass(frozen=True)
class FailureResult:
    login_locked: bool
    ip_locked: bool


class BruteforceGuard:
    def __init__(self, redis: Redis, settings: BruteforceSettings) -> None:
        self.redis = redis
        self.settings = settings

    async def locked(
        self, login: str, ip: str | None
    ) -> Literal["locked_ip", "locked_login"] | None:
        """Причина отказа (``locked_ip`` / ``locked_login``) или None."""
        if ip and await self.redis.exists(_keys("ip", ip)[1]):
            return "locked_ip"
        if await self.redis.exists(_keys("login", login)[1]):
            return "locked_login"
        return None

    async def _register(self, kind: str, value: str, rule: BruteforceRule) -> bool:
        counter, lock = _keys(kind, value)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(counter)
            pipe.expire(counter, rule.window_minutes * 60, nx=True)
            count, _ = await pipe.execute()
        if int(count) >= rule.max_failures:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.set(lock, "1", ex=rule.lock_minutes * 60)
                pipe.delete(counter)
                await pipe.execute()
            return True
        return False

    async def register_failure(self, login: str, ip: str | None) -> FailureResult:
        login_locked = await self._register("login", login, self.settings.per_login)
        ip_locked = await self._register("ip", ip, self.settings.per_ip) if ip else False
        return FailureResult(login_locked, ip_locked)

    async def reset_login(self, login: str) -> None:
        await self.redis.delete(_keys("login", login)[0])

    async def unlock_login(self, login: str) -> None:
        await self.redis.delete(*_keys("login", login))
