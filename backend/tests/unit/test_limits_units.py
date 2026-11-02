"""Правила лимитов без Redis и БД (§12): окна, разрешение политик, текст отказа."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.config import ConfigError, LimitRule, Settings, load_settings
from app.modules.limits.models import LimitPolicy
from app.modules.limits.partitions import months
from app.modules.limits.policies import Key, resolve
from app.modules.limits.service import exceeded
from app.modules.limits.windows import period, period_key

TZ = "Europe/Moscow"


def test_windows_follow_calendar_in_company_timezone() -> None:
    # Понедельник 2 ноября 2026, 21:30 UTC = вторник 00:30 по Москве.
    when = datetime(2026, 11, 2, 21, 30, tzinfo=UTC)
    start, end = period(when, "day", TZ)
    assert start.isoformat() == "2026-11-03T00:00:00+03:00"
    assert end.isoformat() == "2026-11-04T00:00:00+03:00"
    week_start, week_end = period(when, "week", TZ)
    assert week_start.isoformat() == "2026-11-02T00:00:00+03:00"  # понедельник
    assert week_end.isoformat() == "2026-11-09T00:00:00+03:00"
    month_start, month_end = period(datetime(2026, 12, 31, 22, 0, tzinfo=UTC), "month", TZ)
    assert month_start.isoformat() == "2027-01-01T00:00:00+03:00"
    assert month_end.isoformat() == "2027-02-01T00:00:00+03:00"
    assert period(when, "hour", TZ)[1].isoformat() == "2026-11-03T01:00:00+03:00"
    assert period_key(when, "day", TZ) == "20261103"
    assert period_key(when, "week", TZ) == "2026W45"


def _policy(scope: str, metric: str, limit: int, **kw: object) -> LimitPolicy:
    row = LimitPolicy(
        id=uuid4(), scope=scope, metric=metric, limit=limit, thinking=False,
        target_id=uuid4() if scope != "global" else None, **kw,
    )  # fmt: skip
    if row.window is None and metric in ("messages", "tokens", "uploads"):
        row.window = "day"
    return row


def test_personal_beats_role_beats_global_beats_config() -> None:
    settings = Settings()
    rows = [
        _policy("global", "messages", 150),
        _policy("role", "messages", 300),
        _policy("role", "messages", 400),
        _policy("role", "tokens", 5_000_000),
        _policy("user", "uploads", 7),
        _policy("global", "uploads", 50),
    ]
    by_key = {e.key: e for e in resolve(settings, rows)}
    messages = by_key[Key("messages", "day")]
    assert (messages.limit, messages.source) == (400, "role")  # максимальная из ролевых
    assert by_key[Key("tokens", "day")].limit == 5_000_000
    assert (by_key[Key("uploads", "day")].limit, by_key[Key("uploads", "day")].source) == (
        7,
        "user",
    )
    assert by_key[Key("concurrent_generations")].source == "config"
    # Персональная ниже ролевой — всё равно действует (поднять и опустить можно персонально).
    lowered = resolve(settings, [*rows, _policy("user", "messages", 10)])
    assert next(e for e in lowered if e.key == Key("messages", "day")).limit == 10


def test_qualified_policies_apply_only_to_their_generations() -> None:
    thinking = Key("tokens", "day", thinking=True)
    coder = Key("messages", "day", model_role="coder")
    assert thinking.applies("chat", thinking=True) and not thinking.applies("chat", thinking=False)
    assert coder.applies("coder", thinking=False) and not coder.applies("chat", thinking=False)
    assert Key("messages", "day").applies("coder", thinking=True)


def test_limit_rule_shape_is_validated() -> None:
    with pytest.raises(ValueError, match="нужно окно"):
        LimitRule(metric="messages", limit=1)
    with pytest.raises(ValueError, match="окно не задаётся"):
        LimitRule(metric="concurrent_generations", window="day", limit=1)
    with pytest.raises(ValueError, match="не поддерживаются"):
        LimitRule(metric="uploads", window="day", limit=1, thinking=True)
    with pytest.raises(ConfigError, match="одинаковым ключом"):
        load_settings(
            limits={
                "defaults": [
                    {"metric": "messages", "window": "day", "limit": 1},
                    {"metric": "messages", "window": "day", "limit": 2},
                ]
            }
        )


def test_exceeded_message_is_human_and_carries_reset_at() -> None:
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)  # 15:00 по Москве
    error = exceeded(Key("messages", "day"), 200, 200, now, TZ)
    assert error.status_code == 429 and error.code == "limit_exceeded"
    assert error.message == (
        "Дневной лимит сообщений исчерпан, обновится в 00:00. "
        "Если нужно больше — обратитесь к администратору"
    )
    assert error.details == {
        "metric": "messages",
        "window": "day",
        "model_role": None,
        "thinking": False,
        "limit": 200,
        "used": 200,
        "reset_at": "2026-11-03T00:00:00+03:00",
    }
    weekly = exceeded(Key("tokens", "week", thinking=True), 10, 12, now, TZ)
    assert weekly.message.startswith(
        "Недельный лимит токенов в режиме размышлений исчерпан, обновится 09.11 в 00:00"
    )
    slots = exceeded(Key("concurrent_generations"), 2, 2, now, TZ)
    assert "не больше 2 ответов" in slots.message and slots.details["reset_at"] is None


def test_usage_partitions_cover_current_and_next_months() -> None:
    names = [m[0] for m in months(datetime(2026, 12, 15, tzinfo=UTC), 2)]
    assert names == ["usage_records_2026_12", "usage_records_2027_01", "usage_records_2027_02"]
