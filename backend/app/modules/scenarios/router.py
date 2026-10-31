"""Сценарии для пользователя (§7.9): карточки по ролям."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.deps import DbDep
from app.modules.auth.deps import CurrentUser, CurrentUserDep
from app.modules.llm.registry import ModelRegistry
from app.modules.scenarios import service
from app.modules.scenarios.models import Scenario
from app.modules.scenarios.schemas import ScenarioCard

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def role_codes(current: CurrentUser) -> set[str]:
    return {r.role.code for r in current.roles}


def card(scenario: Scenario, registry: ModelRegistry) -> ScenarioCard:
    available = scenario.model_role in registry.roles() and registry.thinking_available(
        scenario.model_role
    )
    default = scenario.thinking_default
    if default is None:
        default = available and registry.get(scenario.model_role).thinking.default
    return ScenarioCard(
        id=scenario.id,
        code=scenario.code,
        name=scenario.name,
        description=scenario.description,
        icon=scenario.icon,
        starter_prompts=scenario.starter_prompts,
        requires_attachment=scenario.requires_attachment,
        attachment_hint=scenario.attachment_hint,
        thinking_available=available,
        thinking_default=bool(default and available),
    )


@router.get("", response_model=list[ScenarioCard], operation_id="listScenarios")
async def list_scenarios(
    request: Request, db: DbDep, current: CurrentUserDep
) -> list[ScenarioCard]:
    """Сценарии, доступные ролям пользователя (пустые роли сценария — всем)."""
    registry: ModelRegistry = request.app.state.models
    return [card(s, registry) for s in await service.list_visible(db, role_codes(current))]
