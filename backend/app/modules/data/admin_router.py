"""Админка «Источники данных» (§13.2, SHOULD): каталог шлюза, тестовый вызов функции, журнал
SQL-запросов (только чтение). Право ``admin.datasources.view``; тестовый вызов — в аудит."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.config import Settings
from app.core.deps import DbDep
from app.core.errors import AppError
from app.core.pagination import DEFAULT_LIMIT, Page, decode_datetime_cursor, encode_cursor
from app.modules.audit import service as audit
from app.modules.audit.models import AuditLog
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.data.client import DataGateway, GatewayError, identity_of
from app.modules.rbac.permissions import Perm
from app.modules.users.models import User

router = APIRouter(prefix="/admin/data", tags=["admin"])

Viewer = Annotated[CurrentUser, Depends(require(Perm.DATASOURCES_VIEW))]
ACTIONS = ("data.query", "data.function")


class CatalogOut(BaseModel):
    configured: bool
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    functions: list[dict[str, Any]] = Field(default_factory=list)
    catalog_error: str | None = None
    error: str | None = None  # текст ошибки шлюза
    error_code: str | None = None  # unavailable — шлюз не отвечает


class TestCallIn(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class TestCallOut(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    sql: str


class QueryLogOut(BaseModel):
    id: UUID
    ts: datetime
    user: str | None
    action: str
    target: str | None
    sql: str | None
    status: str | None
    rows: int | None
    duration_ms: int | None
    error: str | None
    chat_id: str | None


def _gateway(request: Request) -> DataGateway | None:
    settings: Settings = request.app.state.settings
    if not settings.data_gateway.url:
        return None
    return DataGateway(settings)


@router.get("/catalog", response_model=CatalogOut, operation_id="adminDataCatalog")
async def catalog(request: Request, db: DbDep, actor: Viewer) -> CatalogOut:
    gateway = _gateway(request)
    if gateway is None:
        return CatalogOut(configured=False)
    try:
        data = await gateway.catalog(await identity_of(db, actor.id, admin=True))
    except GatewayError as exc:
        return CatalogOut(configured=True, error=exc.message, error_code=exc.code)
    return CatalogOut(
        configured=True,
        datasets=data["datasets"],
        functions=data["functions"],
        catalog_error=data.get("catalog_error"),
    )


@router.post(
    "/functions/{name}/test", response_model=TestCallOut, operation_id="adminDataTestFunction"
)
async def test_function(
    name: str, body: TestCallIn, request: Request, db: DbDep, actor: Viewer
) -> TestCallOut:
    """Тестовый вызов функции от имени админа (видит все функции); пишется в аудит."""
    gateway = _gateway(request)
    if gateway is None:
        raise AppError("Шлюз данных не настроен", code="not_configured", status_code=409)
    details: dict[str, Any] = {"params": body.params, "via": "admin_test"}
    try:
        result = await gateway.call(await identity_of(db, actor.id, admin=True), name, body.params)
    except GatewayError as exc:
        await audit.record(
            db, actor_id=actor.id, action="data.function", target_type="data_function",
            target_id=name, details={**details, "status": exc.code, "error": exc.message},
            ip=client_ip(request),
        )  # fmt: skip
        await db.commit()
        raise AppError(exc.message, code=exc.code, status_code=422) from exc
    await audit.record(
        db, actor_id=actor.id, action="data.function", target_type="data_function",
        target_id=name,
        details={
            **details, "sql": result.get("sql"), "status": "ok", "rows": result.get("row_count"),
            "duration_ms": result.get("duration_ms"),
        },
        ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return TestCallOut.model_validate(result)


@router.get("/queries", response_model=Page[QueryLogOut], operation_id="adminDataQueries")
async def queries(
    db: DbDep,
    _: Viewer,
    q: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = DEFAULT_LIMIT,
) -> Page[QueryLogOut]:
    """Журнал SQL-запросов и вызовов функций — из аудита (только чтение)."""
    stmt = (
        select(AuditLog, User.full_name)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(AuditLog.action.in_(ACTIONS))
    )
    if q and (term := q.strip()):
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                User.full_name.ilike(like),
                User.login.ilike(like),
                AuditLog.target_id.ilike(like),
                AuditLog.details["sql"].astext.ilike(like),
            )
        )
    if cursor:
        ts, last_id = decode_datetime_cursor(cursor)
        stmt = stmt.where(
            or_(AuditLog.ts < ts, (AuditLog.ts == ts) & (AuditLog.id < UUID(last_id)))
        )
    rows = (
        await db.execute(stmt.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(limit + 1))
    ).all()
    items = [
        QueryLogOut(
            id=e.id,
            ts=e.ts,
            user=name,
            action=e.action,
            target=e.target_id,
            sql=e.details.get("sql"),
            status=e.details.get("status"),
            rows=e.details.get("rows"),
            duration_ms=e.details.get("duration_ms"),
            error=e.details.get("error"),
            chat_id=e.details.get("chat_id"),
        )
        for e, name in rows[:limit]
    ]
    last = rows[limit - 1][0] if len(rows) > limit else None
    next_cursor = encode_cursor(last.ts, last.id) if last else None
    return Page(items=items, next_cursor=next_cursor)
