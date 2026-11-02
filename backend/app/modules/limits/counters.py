"""Счётчики лимитов в Redis (§12.3).

Счётчик окна — строка ``lim:{user}:{метрика}:{окно}:{роль модели|*}:{a|t}:{метка окна}``: расход
пишется сразу во все окна и в варианты «любая роль / эта роль», «все / только thinking», поэтому
новая политика видит настоящий расход с начала окна. Одновременные генерации — сортированное
множество ``lim:{user}:concurrent`` (член — id ответа, вес — срок): живая генерация продлевает
срок, упавший процесс перестаёт держать слот после ``limits.slot_ttl_s``.

Проверка и резервирование всех лимитов запроса — один скрипт Lua, то есть атомарно: параллельные
запросы не проскакивают между проверкой и списанием.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis

from app.modules.limits.windows import WINDOWS, period_key, ttl_seconds

# KEYS: n ключей проверки, затем m ключей списания, затем (если slot) ключ множества слотов.
# ARGV: n, m, slot, затем по 2 на проверку (limit, add), по 2 на списание (amount, ttl),
# затем (если slot) now_ms, member, expire_ms, slot_limit.
# Ответ: {0, 0} — успех; {i, used} — не прошла i-я проверка (n + 1 — слоты).
_RESERVE = """
local n = tonumber(ARGV[1])
local m = tonumber(ARGV[2])
local slot = tonumber(ARGV[3])
local a = 3
for i = 1, n do
  local limit = tonumber(ARGV[a + 1])
  local add = tonumber(ARGV[a + 2])
  a = a + 2
  local used = tonumber(redis.call('GET', KEYS[i]) or '0')
  if (add > 0 and used + add > limit) or (add == 0 and used >= limit) then
    return {i, used}
  end
end
local incs = a
a = a + 2 * m
local zkey, now, member, expire, slot_limit
if slot == 1 then
  zkey = KEYS[n + m + 1]
  now = tonumber(ARGV[a + 1])
  member = ARGV[a + 2]
  expire = tonumber(ARGV[a + 3])
  slot_limit = tonumber(ARGV[a + 4])
  redis.call('ZREMRANGEBYSCORE', zkey, '-inf', now)
  local count = redis.call('ZCARD', zkey)
  if count >= slot_limit then
    return {n + 1, count}
  end
end
for j = 1, m do
  local amount = tonumber(ARGV[incs + 1])
  local ttl = tonumber(ARGV[incs + 2])
  incs = incs + 2
  redis.call('INCRBY', KEYS[n + j], amount)
  redis.call('EXPIRE', KEYS[n + j], ttl)
end
if slot == 1 then
  redis.call('ZADD', zkey, expire, member)
  redis.call('PEXPIRE', zkey, expire - now + 60000)
end
return {0, 0}
"""


def counter_key(
    user_id: UUID,
    metric: str,
    window: str,
    when: datetime,
    tz: str,
    *,
    model_role: str | None = None,
    thinking: bool = False,
) -> str:
    role = model_role or "*"
    mode = "t" if thinking else "a"
    return f"lim:{user_id}:{metric}:{window}:{role}:{mode}:{period_key(when, window, tz)}"


def slot_key(user_id: UUID) -> str:
    return f"lim:{user_id}:concurrent"


def spread(
    user_id: UUID,
    metric: str,
    amount: int,
    when: datetime,
    tz: str,
    *,
    model_role: str | None = None,
    thinking: bool = False,
) -> list[tuple[str, int, int]]:
    """Ключи, в которые пишется расход: все окна × (любая роль, эта роль) × (все, thinking)."""
    roles: list[str | None] = [None] + ([model_role] if model_role else [])
    modes = [False] + ([True] if thinking else [])
    return [
        (
            counter_key(user_id, metric, w, when, tz, model_role=r, thinking=t),
            amount,
            ttl_seconds(when, w, tz),
        )
        for w in WINDOWS
        for r in roles
        for t in modes
    ]


@dataclass(frozen=True)
class Check:
    key: str
    limit: int
    add: int  # сколько запрос добавит; 0 — только «не исчерпан ли» (токены до ответа)


@dataclass(frozen=True)
class Slot:
    key: str
    member: str
    limit: int
    now_ms: int
    expire_ms: int


class Counters:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._reserve = redis.register_script(_RESERVE)

    async def reserve(
        self,
        checks: Sequence[Check],
        increments: Sequence[tuple[str, int, int]],
        slot: Slot | None = None,
    ) -> tuple[int, int]:
        """(0, 0) — зарезервировано; (i, used) — отказ по i-й проверке (len+1 — слоты)."""
        keys = [c.key for c in checks] + [k for k, _, _ in increments]
        args: list[str | int] = [len(checks), len(increments), 1 if slot else 0]
        for c in checks:
            args += [c.limit, c.add]
        for _, amount, ttl in increments:
            args += [amount, ttl]
        if slot is not None:
            keys.append(slot.key)
            args += [slot.now_ms, slot.member, slot.expire_ms, slot.limit]
        failed, used = await self._reserve(keys=keys, args=args)
        return int(failed), int(used)

    async def add(self, increments: Sequence[tuple[str, int, int]]) -> None:
        if not increments:
            return
        async with self.redis.pipeline(transaction=True) as pipe:
            for key, amount, ttl in increments:
                pipe.incrby(key, amount)
                pipe.expire(key, ttl)
            await pipe.execute()

    async def get(self, keys: Sequence[str]) -> list[int]:
        if not keys:
            return []
        values = await self.redis.mget(list(keys))
        return [int(v or 0) for v in values]

    async def slots(self, key: str, now_ms: int) -> int:
        return int(await self.redis.zcount(key, now_ms, "+inf"))

    async def refresh_slot(self, key: str, member: str, expire_ms: int) -> None:
        await self.redis.zadd(key, {member: expire_ms}, xx=True)

    async def release_slot(self, key: str, member: str) -> None:
        await self.redis.zrem(key, member)

    async def reset(self, user_id: UUID, metric: str | None = None) -> int:
        """Удаляет счётчики пользователя (все или одной метрики); возвращает число ключей."""
        pattern = f"lim:{user_id}:{metric}:*" if metric else f"lim:{user_id}:*"
        keys = [k async for k in self.redis.scan_iter(match=pattern, count=500)]
        if metric == "concurrent_generations":
            keys.append(slot_key(user_id))
        if keys:
            await self.redis.delete(*keys)
        return len(keys)
