"""Разделы ``usage_records`` по месяцам (§14): текущий и ``limits.partitions_ahead`` следующих.

Задача ``limits.partitions`` в ``scheduler`` раз в сутки создаёт недостающие разделы. Если строки
месяца уже попали в раздел по умолчанию (задача долго не запускалась), они переносятся в новый
раздел в той же транзакции — иначе PostgreSQL не даст его подключить.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings

PARENT = "usage_records"
DEFAULT = "usage_records_default"


def _shift(year: int, month: int, by: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + by
    return index // 12, index % 12 + 1


def months(now: datetime, ahead: int) -> list[tuple[str, str, str]]:
    """(имя раздела, начало, конец) — от текущего месяца на ``ahead`` вперёд (UTC)."""
    now = now.astimezone(UTC)
    result = []
    for shift in range(ahead + 1):
        y, m = _shift(now.year, now.month, shift)
        ey, em = _shift(now.year, now.month, shift + 1)
        result.append((f"{PARENT}_{y:04d}_{m:02d}", f"{y:04d}-{m:02d}-01", f"{ey:04d}-{em:02d}-01"))
    return result


async def ensure_partitions(db: AsyncSession, settings: Settings, now: datetime) -> list[str]:
    """Создаёт недостающие разделы; возвращает имена созданных. Commit — у вызывающего."""
    created: list[str] = []
    for name, start, end in months(now, settings.limits.partitions_ahead):
        if await db.scalar(text("SELECT to_regclass(:name)"), {"name": name}) is not None:
            continue
        # Имена и даты — из чисел выше, не из ввода пользователя.
        await db.execute(text(f"CREATE TABLE {name} (LIKE {PARENT} INCLUDING DEFAULTS)"))
        await db.execute(
            text(
                f"WITH moved AS (DELETE FROM {DEFAULT} WHERE ts >= :start AND ts < :end "  # noqa: S608 — имя раздела из чисел, не из ввода
                f"RETURNING *) INSERT INTO {name} SELECT * FROM moved"
            ),
            {"start": datetime.fromisoformat(start).replace(tzinfo=UTC),
             "end": datetime.fromisoformat(end).replace(tzinfo=UTC)},
        )  # fmt: skip
        await db.execute(
            text(
                f"ALTER TABLE {PARENT} ATTACH PARTITION {name} "
                f"FOR VALUES FROM ('{start}') TO ('{end}')"
            )
        )
        created.append(name)
    return created
