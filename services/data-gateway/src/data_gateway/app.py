"""HTTP API шлюза данных (§9.5). Вызывает только ``api``; каждый запрос — с подписанной
идентичностью пользователя (``identity.py``). Аудит пишет ``api``: шлюз возвращает итоговый SQL.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from data_gateway.catalog import Catalog, CatalogStore, Dataset, Function, visible
from data_gateway.examples import Ranker
from data_gateway.executor import Executor, QueryFailed, Result
from data_gateway.guard import Prepared, Rejected, prepare_function, prepare_query
from data_gateway.identity import Identity, IdentityError, verify

log = logging.getLogger("data_gateway")


@dataclass
class GatewaySettings:
    catalog_dir: Path
    secret: str
    secrets_dir: Path = Path("/run/secrets")
    embed_url: str | None = None
    embed_model: str = "bge-m3"

    @classmethod
    def from_env(cls) -> GatewaySettings:
        secrets_dir = Path(os.environ.get("DG_SECRETS_DIR", "/run/secrets"))
        secret = os.environ.get("DG_SECRET")
        if not secret:
            path = Path(os.environ.get("DG_SECRET_FILE", secrets_dir / "data_gateway_secret"))
            secret = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        if len(secret) < 16:
            raise RuntimeError("DG_SECRET (или /run/secrets/data_gateway_secret) — не короче 16")
        return cls(
            catalog_dir=Path(os.environ.get("DG_CATALOG_DIR", "/srv/catalog")),
            secret=secret,
            secrets_dir=secrets_dir,
            embed_url=os.environ.get("DG_EMBED_URL") or None,
            embed_model=os.environ.get("DG_EMBED_MODEL", "bge-m3"),
        )


class QueryIn(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)


class CallIn(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class ResultOut(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    sql: str  # итоговый T-SQL после RLS и ограничения строк — для аудита
    params: dict[str, Any]
    datasets: list[str] = Field(default_factory=list)
    rls: list[str] = Field(default_factory=list)


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _identity(
    request: Request,
    x_dg_identity: Annotated[str | None, Header()] = None,
    x_dg_signature: Annotated[str | None, Header()] = None,
) -> Identity:
    settings: GatewaySettings = request.app.state.settings
    try:
        return verify(x_dg_identity, x_dg_signature, settings.secret)
    except IdentityError as exc:
        raise _error(401, "unauthenticated", str(exc)) from exc


User = Annotated[Identity, Depends(_identity)]


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    settings = settings or GatewaySettings.from_env()
    store = CatalogStore(settings.catalog_dir)
    executor = Executor(settings.secrets_dir)
    ranker = Ranker(settings.embed_url, settings.embed_model)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        store.get()  # каталог с ошибкой при старте — шлюз не стартует
        yield
        executor.dispose()

    app = FastAPI(title="data-gateway", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
        detail = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {"code": "error", "message": str(exc.detail)}
        )
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    def catalog() -> Catalog:
        return store.get()

    def dataset_brief(d: Dataset, admin: bool) -> dict[str, Any]:
        brief: dict[str, Any] = {"name": d.name, "title": d.title, "description": d.description}
        if admin:
            brief |= {
                "source": d.source,
                "view": d.view,
                "roles": d.roles,
                "rls": [r.model_dump() for r in d.rls],
                "columns": len(d.columns),
            }
        return brief

    def function_brief(f: Function, admin: bool) -> dict[str, Any]:
        brief: dict[str, Any] = {
            "name": f.name,
            "description": f.description,
            "params": {n: p.model_dump(exclude_none=True) for n, p in f.params.items()},
        }
        if admin:
            brief |= {"source": f.source, "roles": f.roles, "sql": f.sql}
        return brief

    @app.get("/health")
    async def health() -> dict[str, Any]:
        store.get()
        return {"status": "ok", "catalog_error": store.error}

    @app.get("/v1/catalog")
    async def list_catalog(user: User) -> dict[str, Any]:
        cat = catalog()

        def show(roles: list[str]) -> bool:
            return user.admin or visible(roles, user.roles)

        return {
            "datasets": [
                dataset_brief(d, user.admin) for d in cat.datasets.values() if show(d.roles)
            ],
            "functions": [
                function_brief(f, user.admin) for f in cat.functions.values() if show(f.roles)
            ],
            "catalog_error": store.error if user.admin else None,
        }

    @app.get("/v1/datasets/{name}")
    async def describe(name: str, user: User, question: str | None = None) -> dict[str, Any]:
        dataset = catalog().datasets.get(name)
        if dataset is None or not visible(dataset.roles, user.roles):
            raise _error(404, "not_found", f"набора {name!r} нет или он вам недоступен")
        rls = [r for r in dataset.rls if not set(r.unless_roles) & user.roles]
        return {
            "name": dataset.name,
            "title": dataset.title,
            "description": dataset.description,
            "view": dataset.view,
            "columns": [c.model_dump() for c in dataset.columns],
            "relations": dataset.relations,
            "metrics": dataset.metrics,
            "row_filter": [f"{r.column} = {r.equals}" for r in rls],
            "examples": [e.model_dump() for e in await ranker.top(question, dataset.examples)],
        }

    async def execute(prepared: Prepared, user: Identity, kind: str, name: str) -> ResultOut:
        cat = catalog()
        try:
            result: Result = await executor.run(cat.sources[prepared.source], prepared)
        except QueryFailed as exc:
            log.info("dg.failed kind=%s name=%s login=%s", kind, name, user.login)
            raise _error(422, "query_failed", str(exc)) from exc
        log.info(
            "dg.done kind=%s name=%s login=%s rows=%d ms=%d",
            kind, name, user.login, len(result.rows), result.duration_ms,
        )  # fmt: skip
        return ResultOut(
            columns=result.columns,
            rows=result.rows,
            row_count=len(result.rows),
            truncated=result.truncated,
            duration_ms=result.duration_ms,
            sql=prepared.tsql,
            params=prepared.params,
            datasets=prepared.datasets,
            rls=prepared.rls,
        )

    @app.post("/v1/functions/{name}", response_model=ResultOut)
    async def call_function(name: str, body: CallIn, user: User) -> ResultOut:
        cat = catalog()
        function = cat.functions.get(name)
        if function is None or not (user.admin or visible(function.roles, user.roles)):
            raise _error(404, "not_found", f"функции {name!r} нет или она вам недоступна")
        try:
            prepared = prepare_function(function, body.params, cat)
        except Rejected as exc:
            raise _error(400, "rejected", exc.message) from exc
        return await execute(prepared, user, "function", name)

    @app.post("/v1/query", response_model=ResultOut)
    async def query(body: QueryIn, user: User) -> ResultOut:
        try:
            prepared = prepare_query(body.sql, catalog(), user)
        except Rejected as exc:
            raise _error(400, "rejected", exc.message) from exc
        return await execute(prepared, user, "query", ",".join(prepared.datasets))

    return app
