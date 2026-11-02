"""Админка «Лимиты» (§12.4, §13.2): политики, эффективные лимиты пользователя, сброс счётчиков.

Всё — под ``admin.limits.manage``; каждое изменение — запись в аудит. Временное повышение — это
персональная политика со сроком: после ``expires_at`` она перестаёт действовать сама.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.core.config import LimitMetric, LimitRule, LimitWindow, Settings
from app.core.db import utcnow
from app.core.deps import DbDep
from app.core.errors import AppError, NotFoundError
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.limits import policies
from app.modules.limits.models import LimitPolicy
from app.modules.limits.service import Limits
from app.modules.rbac.models import Role
from app.modules.rbac.permissions import Perm
from app.modules.users.models import User

router = APIRouter(prefix="/admin", tags=["admin"])

Manager = Annotated[CurrentUser, Depends(require(Perm.LIMITS_MANAGE))]
Scope = Literal["global", "role", "user"]


class Target(BaseModel):
    id: UUID
    name: str
    login: str | None = None  # у пользователя
    code: str | None = None  # у роли


class PolicyOut(BaseModel):
    id: UUID
    scope: Scope
    target: Target | None
    metric: str
    window: str | None
    limit: int
    model_role: str | None
    thinking: bool
    expires_at: datetime | None
    active: bool
    note: str | None
    created_at: datetime
    created_by: str | None


class DefaultOut(BaseModel):
    metric: str
    window: str | None
    limit: int
    model_role: str | None
    thinking: bool


class PoliciesOut(BaseModel):
    items: list[PolicyOut]
    defaults: list[DefaultOut]  # из config/app.yaml: перекрываются глобальной политикой
    model_roles: list[str]


class PolicyIn(BaseModel):
    scope: Scope
    target_id: UUID | None = None
    metric: LimitMetric
    window: LimitWindow | None = None
    limit: int = Field(ge=0, le=10**12)
    model_role: str | None = None
    thinking: bool = False
    expires_at: datetime | None = None
    note: str | None = Field(None, max_length=300)


class PolicyPatch(BaseModel):
    limit: int | None = Field(None, ge=0, le=10**12)
    expires_at: datetime | None = None
    note: str | None = Field(None, max_length=300)


class EffectiveOut(BaseModel):
    metric: str
    window: str | None
    model_role: str | None
    thinking: bool
    limit: int
    used: int
    remaining: int
    reset_at: datetime | None
    source: Literal["config", "global", "role", "user"]
    source_name: str | None  # имя роли, давшей лимит
    policy_id: UUID | None
    expires_at: datetime | None


class UserLimitsOut(BaseModel):
    timezone: str  # пояс компании: время сброса — по её часам
    items: list[EffectiveOut]


class ResetIn(BaseModel):
    metric: LimitMetric | None = Field(None, description="Пусто — все счётчики пользователя.")


def _limits(request: Request) -> Limits:
    limits: Limits = request.app.state.limits
    return limits


async def _targets(db: DbDep, rows: list[LimitPolicy]) -> dict[UUID, Target]:
    role_ids = {r.target_id for r in rows if r.scope == "role" and r.target_id}
    user_ids = {r.target_id for r in rows if r.scope == "user" and r.target_id}
    result: dict[UUID, Target] = {}
    if role_ids:
        for role in (await db.scalars(select(Role).where(Role.id.in_(role_ids)))).all():
            result[role.id] = Target(id=role.id, name=role.name, code=role.code)
    if user_ids:
        for user in (await db.scalars(select(User).where(User.id.in_(user_ids)))).all():
            result[user.id] = Target(id=user.id, name=user.full_name, login=user.login)
    return result


async def _names(db: DbDep, ids: set[UUID | None]) -> dict[UUID, str]:
    real = {i for i in ids if i}
    if not real:
        return {}
    return dict((await db.execute(select(User.id, User.full_name).where(User.id.in_(real)))).all())


def _out(row: LimitPolicy, target: Target | None, author: str | None) -> PolicyOut:
    now = utcnow()
    return PolicyOut(
        id=row.id,
        scope=row.scope,
        target=target,
        metric=row.metric,
        window=row.window,
        limit=int(row.limit),
        model_role=row.model_role,
        thinking=row.thinking,
        expires_at=row.expires_at,
        active=row.expires_at is None or row.expires_at > now,
        note=row.note,
        created_at=row.created_at,
        created_by=author,
    )


def _details(row: LimitPolicy) -> dict[str, object]:
    return {
        "scope": row.scope,
        "target_id": str(row.target_id) if row.target_id else None,
        "metric": row.metric,
        "window": row.window,
        "limit": int(row.limit),
        "model_role": row.model_role,
        "thinking": row.thinking,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


@router.get("/limits/policies", response_model=PoliciesOut, operation_id="adminListLimitPolicies")
async def list_policies(
    request: Request,
    db: DbDep,
    _: Manager,
    scope: Scope | None = None,
    target_id: UUID | None = None,
    include_expired: bool = False,
) -> PoliciesOut:
    settings: Settings = request.app.state.settings
    stmt = select(LimitPolicy)
    if scope:
        stmt = stmt.where(LimitPolicy.scope == scope)
    if target_id:
        stmt = stmt.where(LimitPolicy.target_id == target_id)
    if not include_expired:
        stmt = stmt.where(policies.active(utcnow()))  # type: ignore[arg-type]
    rows = list((await db.scalars(stmt.order_by(LimitPolicy.created_at.desc()).limit(500))).all())
    targets = await _targets(db, rows)
    names = await _names(db, {r.created_by for r in rows})
    return PoliciesOut(
        items=[
            _out(
                r,
                targets.get(r.target_id) if r.target_id else None,
                names.get(r.created_by) if r.created_by else None,
            )
            for r in rows
        ],
        defaults=[DefaultOut(**r.model_dump()) for r in settings.limits.defaults],
        model_roles=sorted(settings.models),
    )


async def _validate(request: Request, db: DbDep, body: PolicyIn) -> Target | None:
    settings: Settings = request.app.state.settings
    try:
        LimitRule(
            metric=body.metric, window=body.window, limit=body.limit,
            model_role=body.model_role, thinking=body.thinking,
        )  # fmt: skip
    except ValidationError as exc:
        reason = exc.errors()[0]["msg"].removeprefix("Value error, ")
        raise AppError(reason, code="bad_policy", status_code=422) from exc
    if body.model_role and body.model_role not in settings.models:
        raise AppError("Нет такой роли модели", code="bad_model_role", status_code=422)
    if body.expires_at is not None and body.expires_at <= utcnow():
        raise AppError("Срок действия уже прошёл", code="bad_expiry", status_code=422)
    if body.scope == "global":
        if body.target_id is not None:
            raise AppError("У глобальной политики нет цели", code="bad_target", status_code=422)
        return None
    if body.target_id is None:
        raise AppError("Укажите роль или пользователя", code="bad_target", status_code=422)
    if body.scope == "role":
        role = await db.get(Role, body.target_id)
        if role is None:
            raise NotFoundError("Роль не найдена")
        return Target(id=role.id, name=role.name, code=role.code)
    user = await db.get(User, body.target_id)
    if user is None:
        raise NotFoundError("Пользователь не найден")
    return Target(id=user.id, name=user.full_name, login=user.login)


@router.post(
    "/limits/policies",
    response_model=PolicyOut,
    status_code=201,
    operation_id="adminCreateLimitPolicy",
)
async def create_policy(body: PolicyIn, request: Request, db: DbDep, actor: Manager) -> PolicyOut:
    target = await _validate(request, db, body)
    duplicate = await db.scalar(
        select(LimitPolicy.id).where(
            LimitPolicy.scope == body.scope,
            LimitPolicy.target_id.is_(None)
            if body.target_id is None
            else LimitPolicy.target_id == body.target_id,
            LimitPolicy.metric == body.metric,
            LimitPolicy.window.is_(None)
            if body.window is None
            else LimitPolicy.window == body.window,
            LimitPolicy.model_role.is_(None)
            if body.model_role is None
            else LimitPolicy.model_role == body.model_role,
            LimitPolicy.thinking == body.thinking,
            policies.active(utcnow()),  # type: ignore[arg-type]
        )
    )
    if duplicate:
        raise AppError(
            "Такая политика уже есть — измените её значение или срок",
            code="exists",
            status_code=409,
        )
    row = LimitPolicy(
        scope=body.scope, target_id=body.target_id, metric=body.metric, window=body.window,
        limit=body.limit, model_role=body.model_role, thinking=body.thinking,
        expires_at=body.expires_at, note=body.note, created_by=actor.id,
    )  # fmt: skip
    db.add(row)
    await db.flush()
    await audit.record(
        db, actor_id=actor.id, action="limits.policy.create", target_type="limit_policy",
        target_id=row.id, details=_details(row), ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return _out(row, target, actor.user.full_name)


@router.patch(
    "/limits/policies/{policy_id}", response_model=PolicyOut, operation_id="adminUpdateLimitPolicy"
)
async def update_policy(
    policy_id: UUID, body: PolicyPatch, request: Request, db: DbDep, actor: Manager
) -> PolicyOut:
    row = await db.get(LimitPolicy, policy_id)
    if row is None:
        raise NotFoundError("Политика не найдена")
    before = _details(row)
    changes = body.model_dump(exclude_unset=True)
    if "limit" in changes and changes["limit"] is not None:
        row.limit = changes["limit"]
    if "expires_at" in changes:
        if body.expires_at is not None and body.expires_at <= utcnow():
            raise AppError("Срок действия уже прошёл", code="bad_expiry", status_code=422)
        row.expires_at = body.expires_at
    if "note" in changes:
        row.note = body.note
    row.updated_at = utcnow()
    await audit.record(
        db, actor_id=actor.id, action="limits.policy.update", target_type="limit_policy",
        target_id=row.id, details={"before": before, "after": _details(row)},
        ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    targets = await _targets(db, [row])
    names = await _names(db, {row.created_by})
    return _out(
        row,
        targets.get(row.target_id) if row.target_id else None,
        names.get(row.created_by) if row.created_by else None,
    )


@router.delete(
    "/limits/policies/{policy_id}", status_code=204, operation_id="adminDeleteLimitPolicy"
)
async def delete_policy(policy_id: UUID, request: Request, db: DbDep, actor: Manager) -> None:
    row = await db.get(LimitPolicy, policy_id)
    if row is None:
        raise NotFoundError("Политика не найдена")
    await audit.record(
        db, actor_id=actor.id, action="limits.policy.delete", target_type="limit_policy",
        target_id=row.id, details=_details(row), ip=client_ip(request),
    )  # fmt: skip
    await db.delete(row)
    await db.commit()


@router.get(
    "/users/{user_id}/limits",
    response_model=UserLimitsOut,
    operation_id="adminUserLimits",
)
async def user_limits(user_id: UUID, request: Request, db: DbDep, _: Manager) -> UserLimitsOut:
    """Эффективные лимиты пользователя, расход и откуда взялся каждый лимит."""
    if await db.get(User, user_id) is None:
        raise NotFoundError("Пользователь не найден")
    statuses = await _limits(request).status(db, user_id)
    role_ids = {s.target_id for s in statuses if s.source == "role" and s.target_id}
    roles = (
        {r.id: r.name for r in (await db.scalars(select(Role).where(Role.id.in_(role_ids)))).all()}
        if role_ids
        else {}
    )
    items = [
        EffectiveOut(
            metric=s.key.metric,
            window=s.key.window,
            model_role=s.key.model_role,
            thinking=s.key.thinking,
            limit=s.limit,
            used=s.used,
            remaining=s.remaining,
            reset_at=s.reset_at,
            source=s.source,
            source_name=roles.get(s.target_id) if s.target_id and s.source == "role" else None,
            policy_id=s.policy_id,
            expires_at=s.expires_at,
        )
        for s in statuses
    ]
    return UserLimitsOut(timezone=_limits(request).tz, items=items)


@router.post("/users/{user_id}/limits/reset", status_code=204, operation_id="adminResetUserLimits")
async def reset_limits(
    user_id: UUID, body: ResetIn, request: Request, db: DbDep, actor: Manager
) -> None:
    """Сброс счётчиков пользователя (всех или одной метрики) — расход с нуля до конца окна."""
    if await db.get(User, user_id) is None:
        raise NotFoundError("Пользователь не найден")
    removed = await _limits(request).reset(user_id, body.metric)
    await audit.record(
        db, actor_id=actor.id, action="limits.reset", target_type="user", target_id=user_id,
        details={"metric": body.metric, "counters": removed}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
