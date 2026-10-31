"""Протокол стриминга ответа (§8.5, docs/architecture/sse-protocol.md, ADR-0003).

Генерация пишет события в Redis Stream ``gen:{message_id}`` с порядковыми id ``0-<n>``;
SSE-эндпоинт читает их с позиции ``Last-Event-ID``, поэтому перезагрузка страницы или обрыв сети
не теряют ответ. Поток живёт в Redis ещё ``chat.stream_ttl_seconds`` после завершения; позже
состояние читается из БД (клиент после ``message.end`` перечитывает сообщение по REST).

Пока идёт генерация, процесс-исполнитель продлевает ключ ``gen:alive:{message_id}``: если ключа нет,
а сообщение всё ещё ``streaming``, процесс упал — сообщение помечается ``interrupted``.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal
from uuid import UUID

from redis.asyncio import Redis

PROTOCOL_VERSION = 1

EventType = Literal[
    "message.start",
    "reasoning.delta",
    "content.delta",
    "tool.start",
    "tool.end",
    "sources",
    "file",
    "usage",
    "limits",
    "title",
    "error",
    "message.end",
]

ALIVE_TTL_SECONDS = 30
# Дельты копятся и уходят пачкой не реже, чем раз в FLUSH_INTERVAL: меньше записей в Redis.
FLUSH_INTERVAL = 0.05
FLUSH_MAX_CHARS = 2048


def stream_key(message_id: UUID | str) -> str:
    return f"gen:{message_id}"


def alive_key(message_id: UUID | str) -> str:
    return f"gen:alive:{message_id}"


def cancel_key(message_id: UUID | str) -> str:
    return f"gen:cancel:{message_id}"


def _s(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def format_sse(seq: int, event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {seq}\nevent: {event}\ndata: {payload}\n\n"


class EventWriter:
    """Публикует события одного ответа в Redis Stream."""

    def __init__(self, redis: Redis, message_id: UUID, ttl_seconds: int) -> None:
        self.redis = redis
        self.key = stream_key(message_id)
        self.ttl = ttl_seconds
        self.seq = 0
        self._pending_kind: Literal["reasoning", "content"] | None = None
        self._pending: list[str] = []
        self._pending_chars = 0
        self._last_flush = time.monotonic()

    async def emit(self, event: EventType, data: dict[str, Any]) -> None:
        await self.flush()
        await self._add(event, data)

    async def _add(self, event: str, data: dict[str, Any]) -> None:
        self.seq += 1
        await self.redis.xadd(
            self.key,
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
            id=f"0-{self.seq}",
        )

    async def delta(self, kind: Literal["reasoning", "content"], text: str) -> None:
        if self._pending_kind not in (None, kind):
            await self.flush()
        self._pending_kind = kind
        self._pending.append(text)
        self._pending_chars += len(text)
        if (
            self._pending_chars >= FLUSH_MAX_CHARS
            or time.monotonic() - self._last_flush >= FLUSH_INTERVAL
        ):
            await self.flush()

    async def flush(self) -> None:
        if self._pending and self._pending_kind:
            await self._add(f"{self._pending_kind}.delta", {"text": "".join(self._pending)})
        self._pending, self._pending_chars, self._pending_kind = [], 0, None
        self._last_flush = time.monotonic()

    async def close(self) -> None:
        await self.flush()
        await self.redis.expire(self.key, self.ttl)


MessageState = Callable[[], Awaitable[str | None]]
MarkInterrupted = Callable[[], Awaitable[None]]


async def sse_events(
    redis: Redis,
    message_id: UUID,
    *,
    last_event_id: int,
    heartbeat_seconds: int,
    message_status: MessageState,
    mark_interrupted: MarkInterrupted,
) -> AsyncIterator[str]:
    """Генератор SSE: события с позиции ``last_event_id``, heartbeat, завершение на message.end."""
    key = stream_key(message_id)
    cursor = f"0-{last_event_id}"
    seq = last_event_id

    async def fallback() -> list[str] | None:
        """Потока в Redis нет или он стоит: решаем по состоянию в БД."""
        if await redis.exists(key) and await redis.exists(alive_key(message_id)):
            return None
        status = await message_status()
        if status == "streaming":
            if await redis.exists(alive_key(message_id)):
                return None
            await mark_interrupted()
            status = "interrupted"
            error = {"code": "interrupted", "message": "Генерация прервана", "retryable": True}
            return [
                format_sse(seq + 1, "error", error),
                format_sse(seq + 2, "message.end", {"status": status, "finish_reason": None}),
            ]
        if await redis.exists(key):
            return None  # поток ещё в Redis — дочитаем его
        return [format_sse(seq + 1, "message.end", {"status": status, "finish_reason": None})]

    if (final := await fallback()) is not None:
        for line in final:
            yield line
        return

    while True:
        # Тип ответа xread в redis-py размыт: [[key, [(id, {field: value}), …]], …].
        response: Any = await redis.xread({key: cursor}, count=200, block=heartbeat_seconds * 1000)
        if not response:
            if (final := await fallback()) is not None:
                for line in final:
                    yield line
                return
            yield ": ping\n\n"
            continue
        for _, entries in response:
            for entry_id, raw_fields in entries:
                fields = {_s(k): _s(v) for k, v in raw_fields.items()}
                cursor = _s(entry_id)
                seq = int(cursor.split("-")[1])
                event = fields["event"]
                yield format_sse(seq, event, json.loads(fields["data"]))
                if event == "message.end":
                    return
