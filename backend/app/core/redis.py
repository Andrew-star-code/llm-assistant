"""Redis: сессии, счётчики лимитов, брокер задач, потоки генерации (§2.1)."""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url.get_secret_value(), decode_responses=True)


async def ping(client: Redis) -> None:
    await client.ping()
