"""Лимиты (этап 8, §12): счётчики Redis (Lua), разделы usage_records, применение в API."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.db import create_session_factory
from app.modules.limits.counters import Check, Counters, Slot
from app.modules.limits.partitions import ensure_partitions
from app.modules.users.models import User
from tests.integration.conftest import Infra, make_settings


async def test_reserve_is_atomic_under_parallel_requests(infra: Infra, clean_db: None) -> None:
    """Lua: проверка и резервирование одним шагом — 10 параллельных запросов, лимит 3."""
    redis = Redis.from_url(infra.redis_url, decode_responses=True)
    counters = Counters(redis)
    key = f"lim:test:{uuid4()}"
    now_ms = int(datetime.now(UTC).timestamp() * 1000)

    async def one(i: int) -> tuple[int, int]:
        return await counters.reserve(
            [Check(key, limit=3, add=1)],
            [(key, 1, 60)],
            Slot(f"{key}:slots", f"m{i}", limit=2, now_ms=now_ms, expire_ms=now_ms + 60_000),
        )

    try:
        results = await asyncio.gather(*(one(i) for i in range(10)))
        assert sum(1 for failed, _ in results if failed == 0) == 2  # слотов меньше, чем сообщений
        assert {failed for failed, _ in results if failed} == {2}  # отказ по слотам (n + 1)
        assert await redis.get(key) == "2"
        # Просроченный слот (упавший процесс) освобождается сам при следующей проверке.
        late = now_ms + 61_000
        failed, _ = await counters.reserve(
            [Check(key, 3, 1)], [(key, 1, 60)],
            Slot(f"{key}:slots", "m-late", limit=2, now_ms=late, expire_ms=late + 60_000),
        )  # fmt: skip
        assert failed == 0
        failed, used = await counters.reserve([Check(key, 3, 1)], [(key, 1, 60)])
        assert (failed, used) == (1, 3)  # сообщения кончились
    finally:
        await redis.aclose()


async def test_usage_partitions_move_rows_from_default(
    infra: Infra, clean_db: None, tmp_path: Path
) -> None:
    settings = make_settings(infra, tmp_path, limits={"partitions_ahead": 3})
    engine = create_async_engine(infra.database_url)
    sessions = create_session_factory(engine)
    user_id = uuid4()
    try:
        async with sessions() as db:
            names = list(
                (
                    await db.execute(
                        text(
                            "SELECT c.relname FROM pg_inherits i JOIN pg_class c "
                            "ON c.oid = i.inhrelid WHERE i.inhparent = 'usage_records'::regclass"
                        )
                    )
                ).scalars()
            )
            assert "usage_records_default" in names and len(names) >= 4  # миграция: 3 месяца
            # Строка далёкого месяца без раздела попадает в раздел по умолчанию…
            db.add(
                User(id=user_id, ad_guid=user_id.hex, login=f"u{user_id.hex[:8]}", full_name="Т")
            )
            await db.flush()
            future = datetime(2030, 5, 10, tzinfo=UTC)
            await db.execute(
                text(
                    "INSERT INTO usage_records (id, ts, user_id, model_role, kind, thinking, "
                    "prompt_tokens, completion_tokens) VALUES (:id, :ts, :u, 'chat', 'chat', "
                    "false, 10, 5)"
                ),
                {"id": uuid4(), "ts": future, "u": user_id},
            )
            await db.commit()
            # …и переезжает в созданный раздел.
            created = await ensure_partitions(db, settings, datetime(2030, 4, 1, tzinfo=UTC))
            await db.commit()
            assert "usage_records_2030_05" in created
            moved = await db.scalar(text("SELECT count(*) FROM usage_records_2030_05"))
            left = await db.scalar(
                text("SELECT count(*) FROM usage_records_default WHERE ts >= '2030-05-01'")
            )
            assert (moved, left) == (1, 0)
            assert await ensure_partitions(db, settings, datetime(2030, 4, 1, tzinfo=UTC)) == []
            for name in created:  # не оставлять разделы будущего другим тестам
                await db.execute(text(f"DROP TABLE {name}"))
            await db.commit()
    finally:
        await engine.dispose()
