"""Redis: сессии, счётчики лимитов, брокер задач, потоки генерации (§2.1)."""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import Settings

# Запас тайм-аута чтения над самым долгим блокирующим вызовом (XREAD читателя SSE).
BLOCKING_MARGIN_SECONDS = 5


def create_redis(settings: Settings) -> Redis:
    """Клиент Redis процесса.

    * Тайм-аут чтения — больше самого долгого блокирующего вызова: читатель SSE ждёт события
      ``chat.heartbeat_seconds`` (``XREAD BLOCK``), а клиент по умолчанию рвёт чтение через 5 с —
      пауза в ответе (очередь, инструмент, раздумья модели) обрывала бы поток. Новый блокирующий
      вызов (``BLPOP``, ``XREAD``) должен ждать меньше этого тайм-аута.
    * Каждый открытый SSE-поток держит соединение на время ожидания, поэтому пул — с запасом
      (``redis_max_connections``), а не 100 по умолчанию.
    """
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        decode_responses=True,
        socket_timeout=settings.chat.heartbeat_seconds + BLOCKING_MARGIN_SECONDS,
        socket_connect_timeout=5,
        max_connections=settings.redis_max_connections,
    )


async def ping(client: Redis) -> None:
    await client.ping()
