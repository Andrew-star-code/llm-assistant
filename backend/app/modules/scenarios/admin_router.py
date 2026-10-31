"""Админка «Сценарии» (§13.2): редактор и тестовый чат. Право — ``admin.scenarios.manage``.

Изменения действуют сразу: генерация читает сценарий из БД на каждое сообщение. Каждое изменение
пишется в аудит вместе с изменёнными полями.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import DbDep
from app.core.errors import AppError, NotFoundError
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.chats.models import Chat
from app.modules.kb.models import LEVEL_PERSONAL, KnowledgeBase
from app.modules.llm.registry import ModelRegistry
from app.modules.rbac.models import Role
from app.modules.rbac.permissions import Perm
from app.modules.scenarios import service
from app.modules.scenarios.models import Scenario
from app.modules.scenarios.schemas import NamedOption, ScenarioOptions, ScenarioOut, TestChatOut
from app.modules.scenarios.service import ICONS, TEMPLATE_VARIABLES, ScenarioSpec
from app.modules.tools.registry import all_tools

router = APIRouter(prefix="/admin/scenarios", tags=["admin"])
Manager = Annotated[CurrentUser, Depends(require(Perm.SCENARIOS_MANAGE))]


async def _known(db: AsyncSession) -> tuple[set[str], set[str]]:
    roles = set((await db.scalars(select(Role.code))).all())
    bases = set(
        (
            await db.scalars(
                select(KnowledgeBase.code).where(
                    KnowledgeBase.deleted_at.is_(None), KnowledgeBase.level != LEVEL_PERSONAL
                )
            )
        ).all()
    )
    return roles, bases


def _out(scenario: Scenario, roles: set[str], bases: set[str]) -> ScenarioOut:
    spec = ScenarioSpec.model_validate(scenario, from_attributes=True)
    return ScenarioOut(
        **spec.model_dump(),
        id=scenario.id,
        source=scenario.source,
        created_at=scenario.created_at,
        unknown_roles=[r for r in scenario.roles if r not in roles],
        unknown_knowledge_bases=[k for k in scenario.knowledge_bases if k not in bases],
    )


def _validate(spec: ScenarioSpec, request: Request) -> None:
    """Проверки редактора: шаблон, модель и инструменты существуют."""
    registry: ModelRegistry = request.app.state.models
    if spec.model_role not in registry.roles():
        raise AppError(
            f"Модели с ролью «{spec.model_role}» нет в реестре", code="bad_model", status_code=422
        )
    unknown = sorted(set(spec.tools or []) - set(all_tools()))
    if unknown:
        raise AppError(
            f"Неизвестные инструменты: {', '.join(unknown)}", code="bad_tools", status_code=422
        )
    if spec.icon and spec.icon not in ICONS:
        raise AppError("Неизвестная иконка", code="bad_icon", status_code=422)
    service.check_template(spec.prompt_template)


async def _get(db: AsyncSession, scenario_id: UUID) -> Scenario:
    scenario = await db.get(Scenario, scenario_id)
    if scenario is None:
        raise NotFoundError("Сценарий не найден")
    return scenario


@router.get("", response_model=list[ScenarioOut], operation_id="adminListScenarios")
async def list_scenarios(db: DbDep, _: Manager) -> list[ScenarioOut]:
    rows = (await db.scalars(select(Scenario).order_by(Scenario.sort_order, Scenario.name))).all()
    roles, bases = await _known(db)
    return [_out(s, roles, bases) for s in rows]


@router.get("/options", response_model=ScenarioOptions, operation_id="adminScenarioOptions")
async def options(request: Request, db: DbDep, _: Manager) -> ScenarioOptions:
    """Что можно выбрать в редакторе: модели, инструменты, базы, роли, иконки, переменные."""
    registry: ModelRegistry = request.app.state.models
    bases = (
        await db.scalars(
            select(KnowledgeBase)
            .where(KnowledgeBase.deleted_at.is_(None), KnowledgeBase.level != LEVEL_PERSONAL)
            .order_by(KnowledgeBase.name)
        )
    ).all()
    roles = (await db.scalars(select(Role).where(Role.kind != "system").order_by(Role.name))).all()
    return ScenarioOptions(
        model_roles=[r for r in registry.roles() if r not in {"embed", "rerank", "guard"}],
        tools=sorted(name for name, tool in all_tools().items() if tool.visibility == "visible"),
        knowledge_bases=[NamedOption(code=b.code, name=b.name) for b in bases],
        roles=[NamedOption(code=r.code, name=r.name) for r in roles],
        icons=list(ICONS),
        variables=TEMPLATE_VARIABLES,
        rag_modes=["auto", "tool", "off"],
    )


@router.get("/{scenario_id}", response_model=ScenarioOut, operation_id="adminGetScenario")
async def get_scenario(scenario_id: UUID, db: DbDep, _: Manager) -> ScenarioOut:
    roles, bases = await _known(db)
    return _out(await _get(db, scenario_id), roles, bases)


@router.post("", response_model=ScenarioOut, status_code=201, operation_id="adminCreateScenario")
async def create_scenario(
    body: ScenarioSpec, request: Request, db: DbDep, actor: Manager
) -> ScenarioOut:
    _validate(body, request)
    if await db.scalar(select(Scenario.id).where(Scenario.code == body.code)):
        raise AppError("Сценарий с таким кодом уже есть", code="scenario_exists", status_code=409)
    scenario = Scenario(source="admin")
    service.apply_spec(scenario, body)
    db.add(scenario)
    await db.flush()
    await audit.record(
        db,
        actor_id=actor.id,
        action="scenario.create",
        target_type="scenario",
        target_id=scenario.id,
        details={"code": body.code},
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(scenario)
    roles, bases = await _known(db)
    return _out(scenario, roles, bases)


@router.put("/{scenario_id}", response_model=ScenarioOut, operation_id="adminUpdateScenario")
async def update_scenario(
    scenario_id: UUID, body: ScenarioSpec, request: Request, db: DbDep, actor: Manager
) -> ScenarioOut:
    """Полная замена полей; действует со следующего сообщения во всех чатах сценария."""
    scenario = await _get(db, scenario_id)
    _validate(body, request)
    if body.code != scenario.code and await db.scalar(
        select(Scenario.id).where(Scenario.code == body.code)
    ):
        raise AppError("Сценарий с таким кодом уже есть", code="scenario_exists", status_code=409)
    before = ScenarioSpec.model_validate(scenario, from_attributes=True).model_dump()
    service.apply_spec(scenario, body)
    after = body.model_dump()
    changed: dict[str, Any] = {k: after[k] for k in after if after[k] != before[k]}
    if "prompt_template" in changed:
        changed["prompt_template"] = f"{len(body.prompt_template)} символов"
    await audit.record(
        db,
        actor_id=actor.id,
        action="scenario.update",
        target_type="scenario",
        target_id=scenario.id,
        details={"code": scenario.code, "changed": changed},
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(scenario)
    roles, bases = await _known(db)
    return _out(scenario, roles, bases)


@router.delete("/{scenario_id}", status_code=204, operation_id="adminDeleteScenario")
async def delete_scenario(scenario_id: UUID, request: Request, db: DbDep, actor: Manager) -> None:
    """Удаление: чаты сценария продолжаются как обычные (scenario_id → null)."""
    scenario = await _get(db, scenario_id)
    await audit.record(
        db,
        actor_id=actor.id,
        action="scenario.delete",
        target_type="scenario",
        target_id=scenario.id,
        details={"code": scenario.code},
        ip=client_ip(request),
    )
    await db.delete(scenario)
    await db.commit()


@router.post(
    "/{scenario_id}/test-chat",
    response_model=TestChatOut,
    status_code=201,
    operation_id="adminScenarioTestChat",
)
async def test_chat(scenario_id: UUID, db: DbDep, actor: Manager) -> TestChatOut:
    """Тестовый чат прямо в редакторе: от имени админа, без проверки ролей сценария, не виден в
    истории. Генерация читает сохранённую версию — после «Сохранить» тест сразу её видит."""
    scenario = await _get(db, scenario_id)
    chat = Chat(user_id=actor.id, scenario_id=scenario.id, is_test=True, title=None)
    db.add(chat)
    await db.commit()
    return TestChatOut(chat_id=chat.id)
