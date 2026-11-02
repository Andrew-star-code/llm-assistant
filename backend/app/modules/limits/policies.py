"""Эффективные лимиты пользователя (§12.2).

Ключ политики — метрика, окно, роль модели и признак «только thinking». Для каждого ключа:
персональная политика (не истёкшая), иначе максимальная из ролевых, иначе глобальная из админки,
иначе строка ``limits.defaults`` конфига. Временная политика перестаёт действовать сама: срок
сверяется при каждом расчёте.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.limits.models import LimitPolicy

Source = Literal["config", "global", "role", "user"]


@dataclass(frozen=True, order=True)
class Key:
    metric: str
    window: str | None = None
    model_role: str | None = None
    thinking: bool = False

    def applies(self, model_role: str | None, thinking: bool) -> bool:
        """Действует ли политика на генерацию этой роли модели и режима."""
        role_ok = self.model_role is None or self.model_role == model_role
        return role_ok and (not self.thinking or thinking)


@dataclass(frozen=True)
class Effective:
    key: Key
    limit: int
    source: Source
    policy_id: UUID | None = None
    target_id: UUID | None = None  # роль, давшая лимит (source == "role")
    expires_at: datetime | None = None


def key_of(policy: LimitPolicy) -> Key:
    return Key(policy.metric, policy.window, policy.model_role, policy.thinking)


def active(now: datetime) -> object:
    return or_(LimitPolicy.expires_at.is_(None), LimitPolicy.expires_at > now)


async def effective(
    db: AsyncSession,
    settings: Settings,
    *,
    user_id: UUID,
    role_ids: Iterable[UUID],
    now: datetime,
) -> list[Effective]:
    roles = list(role_ids)
    conditions = [LimitPolicy.scope == "global"]
    conditions.append((LimitPolicy.scope == "user") & (LimitPolicy.target_id == user_id))
    if roles:
        conditions.append((LimitPolicy.scope == "role") & LimitPolicy.target_id.in_(roles))
    rows = (
        await db.scalars(
            select(LimitPolicy)
            .where(or_(*conditions), active(now))  # type: ignore[arg-type]
            .order_by(LimitPolicy.created_at)
        )
    ).all()
    return resolve(settings, rows)


def resolve(settings: Settings, rows: Iterable[LimitPolicy]) -> list[Effective]:
    """Чистая функция разрешения (для unit-тестов): строки уже отфильтрованы по сроку."""
    by_scope: dict[str, dict[Key, list[LimitPolicy]]] = {"user": {}, "role": {}, "global": {}}
    for row in rows:
        by_scope[row.scope].setdefault(key_of(row), []).append(row)
    defaults = {
        Key(r.metric, r.window, r.model_role, r.thinking): r.limit for r in settings.limits.defaults
    }
    keys = set(defaults) | {k for scope in by_scope.values() for k in scope}
    result: list[Effective] = []
    for key in sorted(keys, key=_sort_key):
        if personal := by_scope["user"].get(key):
            row = personal[-1]  # самая новая персональная
            result.append(_from_row(key, row, "user"))
        elif role_rows := by_scope["role"].get(key):
            row = max(role_rows, key=lambda r: r.limit)
            result.append(_from_row(key, row, "role"))
        elif global_rows := by_scope["global"].get(key):
            result.append(_from_row(key, global_rows[-1], "global"))
        else:
            result.append(Effective(key=key, limit=defaults[key], source="config"))
    return result


def _from_row(key: Key, row: LimitPolicy, source: Source) -> Effective:
    return Effective(
        key=key,
        limit=int(row.limit),
        source=source,
        policy_id=row.id,
        target_id=row.target_id,
        expires_at=row.expires_at,
    )


METRIC_ORDER = (
    "messages",
    "tokens",
    "concurrent_generations",
    "uploads",
    "personal_kb_storage",
    "personal_kb_documents",
)
WINDOW_ORDER = (None, "minute", "hour", "day", "week", "month")


def _sort_key(key: Key) -> tuple[int, int, str, bool]:
    metric = METRIC_ORDER.index(key.metric) if key.metric in METRIC_ORDER else 99
    window = WINDOW_ORDER.index(key.window) if key.window in WINDOW_ORDER else 99
    return metric, window, key.model_role or "", key.thinking
