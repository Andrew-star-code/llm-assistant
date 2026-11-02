"""Лимиты (§12): проверка и резервирование до запроса, списание по факту, остатки.

* ``Limits.reserve_generation`` — до генерации: все применимые лимиты ``messages`` и ``tokens``
  и слот одновременной генерации, атомарно (Lua). Отказ — ``LimitExceeded`` (HTTP 429).
* ``Limits.commit_tokens`` — после ответа (любого статуса): фактические токены в счётчики и строка
  в ``usage_records``; разовый перерасход последним ответом допускается (§12.3).
* ``Limits.reserve_upload`` — загрузки; ``kb_quota`` — квота личной базы по политикам.
* ``Limits.status`` — остатки по всем метрикам с временем сброса (профиль, поле ввода, SSE).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.errors import AppError
from app.modules.limits import policies
from app.modules.limits.counters import Check, Counters, Slot, counter_key, slot_key, spread
from app.modules.limits.models import UsageRecord
from app.modules.limits.policies import Effective, Key
from app.modules.limits.windows import period
from app.modules.rbac import service as rbac

GENERATION_METRICS = ("messages", "tokens")
KB_METRICS = ("personal_kb_storage", "personal_kb_documents")

_WINDOW_ADJ = {
    "minute": "Минутный",
    "hour": "Часовой",
    "day": "Дневной",
    "week": "Недельный",
    "month": "Месячный",
}
_METRIC_GEN = {"messages": "сообщений", "tokens": "токенов", "uploads": "загрузок файлов"}


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int | None = None

    @property
    def total(self) -> int:
        # completion_tokens у vLLM уже включает размышления (§12.1: «включая размышления»).
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class MetricStatus:
    key: Key
    limit: int
    used: int
    reset_at: datetime | None
    source: str
    expires_at: datetime | None
    target_id: UUID | None

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    @property
    def ratio(self) -> float:
        return 1.0 if self.limit <= 0 else self.used / self.limit


@dataclass(frozen=True)
class Reservation:
    """Что зарезервировано до генерации: откатывается, если запрос не дошёл до старта."""

    user_id: UUID
    member: str | None
    increments: list[tuple[str, int, int]]


class LimitExceeded(AppError):  # noqa: N818 — имя из §12.3, код ответа limit_exceeded
    status_code = 429
    code = "limit_exceeded"


def _when_text(reset_at: datetime, now: datetime, tz: str) -> str:
    local = reset_at.astimezone(ZoneInfo(tz))
    today = now.astimezone(ZoneInfo(tz)).date()
    # «в 00:00» — сброс сегодня или в ближайшую полночь; дальше — с датой.
    next_midnight = (local.date() - today).days == 1 and (local.hour, local.minute) == (0, 0)
    if local.date() == today or next_midnight:
        return f"в {local:%H:%M}"
    return f"{local:%d.%m} в {local:%H:%M}"


def exceeded(key: Key, limit: int, used: int, now: datetime, tz: str) -> LimitExceeded:
    """429 с понятным текстом и ``{metric, window, limit, used, reset_at}`` в ``details``."""
    reset_at = period(now, key.window, tz)[1] if key.window else None
    if key.metric == "concurrent_generations":
        message = (
            f"Одновременно можно вести не больше {limit} ответов — дождитесь окончания одного из "
            "них или остановите его"
        )
    else:
        what = _METRIC_GEN.get(key.metric, key.metric)
        if key.thinking:
            what += " в режиме размышлений"
        if key.model_role:
            what += f" для модели «{key.model_role}»"
        prefix = _WINDOW_ADJ.get(key.window or "", "")
        message = f"{prefix} лимит {what} исчерпан".strip().capitalize()
        if reset_at is not None:
            message += f", обновится {_when_text(reset_at, now, tz)}"
        message += ". Если нужно больше — обратитесь к администратору"
    return LimitExceeded(
        message,
        details={
            "metric": key.metric,
            "window": key.window,
            "model_role": key.model_role,
            "thinking": key.thinking,
            "limit": limit,
            "used": used,
            "reset_at": reset_at.isoformat() if reset_at else None,
        },
    )


async def effective(
    db: AsyncSession, settings: Settings, user_id: UUID, now: datetime | None = None
) -> list[Effective]:
    roles = await rbac.user_roles(db, user_id)
    return await policies.effective(
        db, settings, user_id=user_id, role_ids=[r.role.id for r in roles], now=now or utcnow()
    )


async def kb_quota(db: AsyncSession, settings: Settings, user_id: UUID) -> tuple[int, int]:
    """Квота личной базы по политикам (§7.8): (документов, МБ)."""
    limits = {e.key.metric: e.limit for e in await effective(db, settings, user_id)}
    return limits.get("personal_kb_documents", 0), limits.get("personal_kb_storage", 0)


class Limits:
    def __init__(self, settings: Settings, redis: Redis) -> None:
        self.settings = settings
        self.counters = Counters(redis)

    @property
    def tz(self) -> str:
        return self.settings.chat.timezone

    @property
    def enabled(self) -> bool:
        return self.settings.limits.enabled

    # ------------------------------------------------------------------ генерации

    async def reserve_generation(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        model_role: str,
        thinking: bool,
        message_id: UUID,
    ) -> Reservation:
        """Проверяет ``messages``, ``tokens`` и слот генерации и резервирует их (§12.3)."""
        now = utcnow()
        increments = spread(
            user_id, "messages", 1, now, self.tz, model_role=model_role, thinking=thinking
        )
        member = str(message_id)
        if not self.enabled:
            return Reservation(user_id, None, [])
        all_rules = await effective(db, self.settings, user_id, now)
        rules = [
            e
            for e in all_rules
            if e.key.metric in GENERATION_METRICS and e.key.applies(model_role, thinking)
        ]
        checks = [
            Check(
                key=self._key(user_id, e.key, now),
                limit=e.limit,
                add=1 if e.key.metric == "messages" else 0,
            )
            for e in rules
        ]
        concurrent = next((e for e in all_rules if e.key.metric == "concurrent_generations"), None)
        slot = None
        if concurrent is not None:
            now_ms = int(now.timestamp() * 1000)
            slot = Slot(
                key=slot_key(user_id),
                member=member,
                limit=concurrent.limit,
                now_ms=now_ms,
                expire_ms=now_ms + self.settings.limits.slot_ttl_s * 1000,
            )
        failed, used = await self.counters.reserve(checks, increments, slot)
        if failed == 0:
            return Reservation(user_id, member if slot else None, increments)
        if failed <= len(rules):
            rule = rules[failed - 1]
            raise exceeded(rule.key, rule.limit, used, now, self.tz)
        if concurrent is None:  # не бывает: отказ по слотам только при политике слотов
            raise RuntimeError("slot refusal without a concurrency policy")
        raise exceeded(concurrent.key, concurrent.limit, used, now, self.tz)

    async def cancel(self, reservation: Reservation) -> None:
        """Запрос не дошёл до генерации: вернуть сообщение в лимит и освободить слот."""
        await self.counters.add([(k, -amount, ttl) for k, amount, ttl in reservation.increments])
        if reservation.member:
            await self.counters.release_slot(slot_key(reservation.user_id), reservation.member)

    async def refresh_slot(self, user_id: UUID, message_id: UUID) -> None:
        expire = int(utcnow().timestamp() * 1000) + self.settings.limits.slot_ttl_s * 1000
        await self.counters.refresh_slot(slot_key(user_id), str(message_id), expire)

    async def release_slot(self, user_id: UUID, message_id: UUID) -> None:
        await self.counters.release_slot(slot_key(user_id), str(message_id))

    async def commit_tokens(
        self,
        *,
        user_id: UUID,
        model_role: str,
        thinking: bool,
        usage: Usage,
    ) -> None:
        """Фактические токены ответа — в счётчики (после commit строки ``usage_records``)."""
        if usage.total <= 0:
            return
        await self.counters.add(
            spread(
                user_id, "tokens", usage.total, utcnow(), self.tz,
                model_role=model_role, thinking=thinking,
            )
        )  # fmt: skip

    # ------------------------------------------------------------------ загрузки

    async def reserve_upload(self, db: AsyncSession, user_id: UUID) -> Reservation:
        now = utcnow()
        increments = spread(user_id, "uploads", 1, now, self.tz)
        if not self.enabled:
            return Reservation(user_id, None, [])
        rules = [
            e for e in await effective(db, self.settings, user_id, now) if e.key.metric == "uploads"
        ]
        checks = [Check(self._key(user_id, e.key, now), e.limit, 1) for e in rules]
        failed, used = await self.counters.reserve(checks, increments)
        if failed:
            rule = rules[failed - 1]
            raise exceeded(rule.key, rule.limit, used, now, self.tz)
        return Reservation(user_id, None, increments)

    # ------------------------------------------------------------------ остатки

    def _key(self, user_id: UUID, key: Key, now: datetime) -> str:
        if key.window is None:
            raise ValueError(f"у метрики {key.metric} нет окна")
        return counter_key(
            user_id, key.metric, key.window, now, self.tz,
            model_role=key.model_role, thinking=key.thinking,
        )  # fmt: skip

    async def status(
        self, db: AsyncSession, user_id: UUID, now: datetime | None = None
    ) -> list[MetricStatus]:
        now = now or utcnow()
        rules = await effective(db, self.settings, user_id, now)
        windowed = [e for e in rules if e.key.window]
        values = await self.counters.get([self._key(user_id, e.key, now) for e in windowed])
        used: dict[Key, int] = {e.key: v for e, v in zip(windowed, values, strict=True)}
        kb_used: tuple[int, int] | None = None
        result: list[MetricStatus] = []
        for e in rules:
            value = used.get(e.key, 0)
            if e.key.metric == "concurrent_generations":
                value = await self.counters.slots(slot_key(user_id), int(now.timestamp() * 1000))
            elif e.key.metric in KB_METRICS:
                if kb_used is None:
                    kb_used = await _kb_usage(db, self.settings, user_id)
                value = kb_used[0] if e.key.metric == "personal_kb_documents" else kb_used[1]
            result.append(
                MetricStatus(
                    key=e.key,
                    limit=e.limit,
                    used=value,
                    reset_at=period(now, e.key.window, self.tz)[1] if e.key.window else None,
                    source=e.source,
                    expires_at=e.expires_at,
                    target_id=e.target_id,
                )
            )
        return result

    async def reset(self, user_id: UUID, metric: str | None = None) -> int:
        return await self.counters.reset(user_id, metric)


def nearest(statuses: list[MetricStatus]) -> MetricStatus | None:
    """Метрика, ближайшая к исчерпанию, среди ограничивающих все сообщения (поле ввода)."""
    candidates = [
        s
        for s in statuses
        if s.key.metric in GENERATION_METRICS and s.key.model_role is None and not s.key.thinking
    ]
    if not candidates:
        return None
    # При равенстве — сообщения: «осталось 37 из 200 сообщений» понятнее токенов (§12.4).
    return max(candidates, key=lambda s: (s.ratio, s.key.metric == "messages"))


async def _kb_usage(db: AsyncSession, settings: Settings, user_id: UUID) -> tuple[int, int]:
    """(документов, МБ с округлением вверх) в личной базе — через сервис ``kb``."""
    from app.modules.kb import service as kb

    documents, size = await kb.personal_usage(db, user_id)
    return documents, -(-size // (1024 * 1024))


def record_usage(
    db: AsyncSession,
    *,
    user_id: UUID,
    kind: str,
    model_role: str,
    thinking: bool,
    usage: Usage,
    chat_id: UUID | None = None,
    message_id: UUID | None = None,
    ts: datetime | None = None,
) -> None:
    """Строка ``usage_records`` в транзакции вызывающего (commit — у него)."""
    db.add(
        UsageRecord(
            ts=ts or utcnow(),
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            model_role=model_role,
            kind=kind,
            thinking=thinking,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            reasoning_tokens=usage.reasoning_tokens,
        )
    )


def status_payload(statuses: list[MetricStatus]) -> dict[str, Any]:
    """Остатки для SSE-события ``limits`` и ``GET /api/limits``."""
    near = nearest(statuses)
    return {
        "items": [
            {
                "metric": s.key.metric,
                "window": s.key.window,
                "model_role": s.key.model_role,
                "thinking": s.key.thinking,
                "limit": s.limit,
                "used": s.used,
                "remaining": s.remaining,
                "reset_at": s.reset_at.isoformat() if s.reset_at else None,
            }
            for s in statuses
        ],
        "nearest": None
        if near is None
        else {
            "metric": near.key.metric,
            "window": near.key.window,
            "limit": near.limit,
            "used": near.used,
            "remaining": near.remaining,
            "reset_at": near.reset_at.isoformat() if near.reset_at else None,
        },
        "blocked": any(
            s.exhausted
            for s in statuses
            if s.key.metric in GENERATION_METRICS
            and s.key.model_role is None
            and not s.key.thinking
        ),
    }


__all__ = [
    "LimitExceeded",
    "Limits",
    "MetricStatus",
    "Reservation",
    "Usage",
    "effective",
    "exceeded",
    "kb_quota",
    "nearest",
    "record_usage",
    "status_payload",
]
