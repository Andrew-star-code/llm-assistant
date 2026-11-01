"""Админка «Модели» и «Инструменты» (§13.2, §9.1).

* Модели — реестр по ролям из ``config/models.yaml`` (смена модели — правкой конфига и по
  runbook), состояние эндпоинтов и видимость по ролям пользователей: сценарий на модели, скрытой
  от пользователя, ему не виден. Роли, без которых чат не работает (``chat`` и служебные), не
  ограничиваются.
* Инструменты — включение и выключение глобально (поверх ``tools.enabled``) и статистика вызовов.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from app.core.db import utcnow
from app.core.deps import DbDep, SettingsDep
from app.core.errors import AppError, NotFoundError
from app.modules.admin import app_settings as keys
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.llm.health import check_all
from app.modules.rbac.permissions import Perm
from app.modules.scenarios.models import Scenario
from app.modules.tools.models import ToolCall
from app.modules.tools.registry import all_tools

router = APIRouter(prefix="/admin", tags=["admin"])

ModelsManager = Annotated[CurrentUser, Depends(require(Perm.MODELS_MANAGE))]
ToolsManager = Annotated[CurrentUser, Depends(require(Perm.TOOLS_MANAGE))]
# Без этих ролей не работают чат, заголовки, поиск — их видимость не ограничивается.
UNRESTRICTED = frozenset({"chat", "utility", "guard", "embed", "rerank"})
STATS_DAYS = 30


class ModelInfo(BaseModel):
    role: str
    model: str
    base_url: str
    api: str
    context_length: int | None
    max_output_tokens: int | None
    supports_tools: bool
    thinking_mode: str
    restrictable: bool = Field(description="Можно ли ограничить видимость по ролям.")
    visible_to: list[str] = Field(description="Коды ролей пользователей; пусто — всем.")
    scenarios: list[str] = Field(description="Сценарии на этой модели.")


class ModelHealthOut(BaseModel):
    role: str
    ok: bool
    latency_ms: int | None
    detail: str | None


class VisibilityIn(BaseModel):
    roles: list[str] = Field(default_factory=list, description="Коды ролей; пусто — всем.")


class ToolInfo(BaseModel):
    name: str
    description: str
    visibility: str
    required_permissions: list[str]
    in_config: bool = Field(description="Разрешён конфигурацией (tools.enabled).")
    enabled: bool = Field(description="Предлагается модели (конфиг и админка).")
    calls: int
    errors: int
    avg_duration_ms: int | None
    last_used_at: datetime | None


class ToolToggleIn(BaseModel):
    enabled: bool


async def _models(db: DbDep, settings: SettingsDep) -> list[ModelInfo]:
    visibility = await keys.model_visibility(db)
    usage: dict[str, list[str]] = {}
    for name, role in (await db.execute(select(Scenario.name, Scenario.model_role))).all():
        usage.setdefault(role, []).append(name)
    return [
        ModelInfo(
            role=role,
            model=ep.model,
            base_url=ep.base_url,
            api=ep.api,
            context_length=ep.context_length,
            max_output_tokens=ep.max_output_tokens,
            supports_tools=ep.supports_tools,
            thinking_mode=ep.thinking.mode,
            restrictable=role not in UNRESTRICTED,
            visible_to=visibility.get(role, []),
            scenarios=sorted(usage.get(role, [])),
        )
        for role, ep in settings.models.items()
    ]


@router.get("/models", response_model=list[ModelInfo], operation_id="adminListModels")
async def list_models(db: DbDep, settings: SettingsDep, _: ModelsManager) -> list[ModelInfo]:
    return await _models(db, settings)


@router.get("/models/health", response_model=list[ModelHealthOut], operation_id="adminModelsHealth")
async def models_health(settings: SettingsDep, _: ModelsManager) -> list[ModelHealthOut]:
    """Живая проверка каждого эндпоинта (до 3 с на модель, параллельно)."""
    return [ModelHealthOut(**vars(h)) for h in await check_all(settings.models)]


@router.put(
    "/models/{role}/visibility", response_model=ModelInfo, operation_id="adminSetModelVisibility"
)
async def set_visibility(
    role: str,
    body: VisibilityIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    actor: ModelsManager,
) -> ModelInfo:
    if role not in settings.models:
        raise NotFoundError("Модель не найдена")
    if role in UNRESTRICTED:
        raise AppError(
            "Без этой модели не работает чат — ограничить её нельзя",
            code="not_restrictable",
            status_code=422,
        )
    current = await keys.model_visibility(db)
    roles = sorted({r.strip() for r in body.roles if r.strip()})
    before = current.get(role, [])
    if roles:
        current[role] = roles
    else:
        current.pop(role, None)
    await keys.set_value(db, keys.MODEL_VISIBILITY, current or None, updated_by=actor.id)
    await audit.record(
        db, actor_id=actor.id, action="models.visibility", target_type="model", target_id=role,
        details={"before": before, "after": roles}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return next(m for m in await _models(db, settings) if m.role == role)


async def _tools(db: DbDep, settings: SettingsDep) -> list[ToolInfo]:
    disabled = await keys.disabled_tools(db)
    since = utcnow() - timedelta(days=STATS_DAYS)
    stats = {
        tool: (calls, errors, avg, last)
        for tool, calls, errors, avg, last in (
            await db.execute(
                select(
                    ToolCall.tool,
                    func.count(),
                    func.sum(case((ToolCall.status != "ok", 1), else_=0)),
                    func.avg(ToolCall.duration_ms),
                    func.max(ToolCall.created_at),
                )
                .where(ToolCall.created_at >= since)
                .group_by(ToolCall.tool)
            )
        ).all()
    }
    result = []
    for name, tool in sorted(all_tools().items()):
        in_config = settings.tools.enabled is None or name in settings.tools.enabled
        calls, errors, avg, last = stats.get(name, (0, 0, None, None))
        result.append(
            ToolInfo(
                name=name,
                description=tool.description,
                visibility=tool.visibility,
                required_permissions=sorted(tool.required_permissions),
                in_config=in_config,
                enabled=in_config and name not in disabled,
                calls=int(calls),
                errors=int(errors or 0),
                avg_duration_ms=int(avg) if avg is not None else None,
                last_used_at=last,
            )
        )
    return result


@router.get("/tools", response_model=list[ToolInfo], operation_id="adminListTools")
async def list_tools(db: DbDep, settings: SettingsDep, _: ToolsManager) -> list[ToolInfo]:
    """Инструменты со статистикой вызовов за 30 дней."""
    return await _tools(db, settings)


@router.put("/tools/{name}", response_model=ToolInfo, operation_id="adminToggleTool")
async def toggle_tool(
    name: str,
    body: ToolToggleIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    actor: ToolsManager,
) -> ToolInfo:
    """Выключенный инструмент не предлагается модели ни в одном чате со следующего сообщения."""
    if name not in all_tools():
        raise NotFoundError("Инструмент не найден")
    in_config = settings.tools.enabled is None or name in settings.tools.enabled
    if body.enabled and not in_config:
        raise AppError(
            "Инструмент выключен в конфигурации (tools.enabled)",
            code="disabled_in_config",
            status_code=422,
        )
    disabled = await keys.disabled_tools(db)
    if body.enabled:
        disabled.discard(name)
    else:
        disabled.add(name)
    await keys.set_value(db, keys.TOOLS_DISABLED, sorted(disabled) or None, updated_by=actor.id)
    await audit.record(
        db, actor_id=actor.id, action="tools.toggle", target_type="tool", target_id=name,
        details={"enabled": body.enabled}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return next(t for t in await _tools(db, settings) if t.name == name)
