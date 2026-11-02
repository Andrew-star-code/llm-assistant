"""Окна лимитов по календарным границам в поясе компании (§12.1): «обновится в 00:00»
понятнее скользящего окна. Неделя начинается с понедельника."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

WINDOWS = ("minute", "hour", "day", "week", "month")


def _local(when: datetime, tz: str) -> datetime:
    return when.astimezone(ZoneInfo(tz))


def period(when: datetime, window: str, tz: str) -> tuple[datetime, datetime]:
    """Начало и конец окна, в котором лежит ``when`` (оба — aware, в поясе компании)."""
    zone = ZoneInfo(tz)
    local = _local(when, tz).replace(tzinfo=None)
    if window == "minute":
        start = local.replace(second=0, microsecond=0)
        end = start + timedelta(minutes=1)
    elif window == "hour":
        start = local.replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1)
    elif window == "day":
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif window == "week":
        day = local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=7)
    elif window == "month":
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)
    else:
        raise ValueError(f"неизвестное окно {window!r}")
    # Границы — по местным часам (переход на летнее время не сдвигает «полночь»).
    return start.replace(tzinfo=zone), end.replace(tzinfo=zone)


def period_key(when: datetime, window: str, tz: str) -> str:
    """Метка окна для ключа счётчика: ``20261102`` (день), ``2026W45`` (неделя) и т. п."""
    start, _ = period(when, window, tz)
    if window == "week":
        year, week, _ = start.isocalendar()
        return f"{year}W{week:02d}"
    return start.strftime(
        {"minute": "%Y%m%d%H%M", "hour": "%Y%m%d%H", "day": "%Y%m%d", "month": "%Y%m"}[window]
    )


def ttl_seconds(when: datetime, window: str, tz: str) -> int:
    """Срок жизни счётчика: до конца окна и ещё сутки запаса (часы процессов расходятся)."""
    _, end = period(when, window, tz)
    return max(1, int((end - when).total_seconds())) + 86_400
