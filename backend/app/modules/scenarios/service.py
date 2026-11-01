"""Сценарии: схема, seed из ``config/scenarios``, видимость по ролям, рендер промпта (§8.7).

Сценарий читается из БД на каждое сообщение, поэтому правка в админке действует сразу, без
перезапуска и без кэша. Шаблон промпта правит админ — он рендерится в песочнице Jinja2
(``SandboxedEnvironment``): без доступа к атрибутам Python и с неопределёнными переменными как
пустой строкой, чтобы опечатка в шаблоне не роняла чат (проверку делает редактор при сохранении).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import structlog
import yaml
from jinja2 import TemplateError, Undefined
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.modules.admin import app_settings
from app.modules.scenarios.models import Scenario

log = structlog.stdlib.get_logger("app.scenarios")

RagMode = Literal["auto", "tool", "off"]
# Иконки карточек — из набора, который знает фронтенд (frontend/src/features/scenarios/iconMap.ts).
ICONS = (
    "file-signature",
    "life-buoy",
    "scale",
    "briefcase",
    "users",
    "calculator",
    "book-open",
    "megaphone",
    "shield",
    "graduation-cap",
    "file-text",
    "sparkles",
)
TEMPLATE_VARIABLES = {
    "user.full_name": "ФИО пользователя",
    "user.title": "должность",
    "user.department": "подразделение",
    "user.address": "обращение («Иван Петрович»)",
    "company": "название компании",
    "now": "дата и время",
    "scenario.name": "название сценария",
}


class ScenarioSpec(BaseModel):
    """Сценарий из YAML и из редактора админки — одна схема."""

    code: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(None, max_length=500)
    icon: str | None = Field(None, max_length=64)
    roles: list[str] = Field(default_factory=list, description="Коды ролей; пусто — всем.")
    model_role: str = Field("chat", min_length=1, max_length=32)
    prompt_template: str = Field("", max_length=20_000, description="Текст шаблона Jinja2.")
    tools: list[str] | None = Field(None, description="Инструменты; null — все включённые.")
    knowledge_bases: list[str] = Field(
        default_factory=list, description="Коды баз знаний; пусто — все доступные."
    )
    rag_mode: RagMode = "auto"
    requires_attachment: bool = False
    attachment_hint: str | None = Field(None, max_length=200)
    starter_prompts: list[str] = Field(default_factory=list, max_length=6)
    thinking_default: bool | None = None
    is_active: bool = True
    sort_order: int = 0


class _Quiet(Undefined):
    """Неизвестная переменная — пустая строка (опечатку ловит проверка в редакторе)."""

    def __str__(self) -> str:
        return ""


_ENV = SandboxedEnvironment(autoescape=False, undefined=_Quiet)


def render_admin_template(text: str, context: dict[str, Any]) -> str:
    """Шаблон из админки (базовый системный промпт) — в той же песочнице, что промпт сценария."""
    try:
        return _ENV.from_string(text).render(**context).strip()
    except TemplateError as exc:
        log.warning("prompts.admin_template_failed", error=str(exc)[:200])
        return ""


def check_template(text: str) -> None:
    """Шаблон компилируется и рендерится на примере; иначе — ошибка для редактора."""
    try:
        _ENV.from_string(text).render(**sample_context())
    except TemplateError as exc:
        raise AppError(
            f"Ошибка в шаблоне промпта: {exc}", code="bad_template", status_code=422
        ) from exc


def sample_context() -> dict[str, Any]:
    return {
        "user": {
            "full_name": "Иванов Иван Петрович",
            "title": "Юрисконсульт",
            "department": "Юридический отдел",
            "address": "Иван Петрович",
        },
        "company": "ООО «Корпорация»",
        "now": "01.11.2026 10:00",
        "scenario": {"name": "Сценарий"},
    }


def render_prompt(scenario: Scenario, context: dict[str, Any]) -> str:
    try:
        variables = {**context, "scenario": {"name": scenario.name, "code": scenario.code}}
        return _ENV.from_string(scenario.prompt_template).render(**variables).strip()
    except TemplateError as exc:
        # Сломанный шаблон (сохранён в обход проверки) — ответ без промпта сценария, а не ошибка.
        log.warning("scenarios.render_failed", code=scenario.code, error=str(exc)[:200])
        return ""


def visible(
    scenario: Scenario, role_codes: Iterable[str], hidden_models: frozenset[str] = frozenset()
) -> bool:
    """Активен, виден ролям пользователя и его модель пользователю не скрыта (админка «Модели»)."""
    return (
        scenario.is_active
        and (not scenario.roles or bool(set(scenario.roles) & set(role_codes)))
        and scenario.model_role not in hidden_models
    )


async def visible_for(db: AsyncSession, scenario: Scenario, role_codes: Iterable[str]) -> bool:
    codes = set(role_codes)
    return visible(scenario, codes, await app_settings.hidden_model_roles(db, codes))


async def list_visible(db: AsyncSession, role_codes: Iterable[str]) -> list[Scenario]:
    codes = set(role_codes)
    hidden = await app_settings.hidden_model_roles(db, codes)
    rows = (
        await db.scalars(
            select(Scenario)
            .where(Scenario.is_active.is_(True))
            .order_by(Scenario.sort_order, Scenario.name)
        )
    ).all()
    return [s for s in rows if visible(s, codes, hidden)]


async def get_visible(db: AsyncSession, scenario_id: UUID, role_codes: Iterable[str]) -> Scenario:
    """Сценарий, доступный пользователю; чужой или выключенный — 404 (не раскрываем наличие)."""
    scenario = await db.get(Scenario, scenario_id)
    if scenario is None or not await visible_for(db, scenario, role_codes):
        raise NotFoundError("Сценарий недоступен")
    return scenario


def apply_spec(scenario: Scenario, spec: ScenarioSpec) -> None:
    for key, value in spec.model_dump().items():
        setattr(scenario, key, value)


def load_seed(config_dir: Path) -> list[ScenarioSpec]:
    """Сценарии из ``config/scenarios/*.yaml``; ``prompt_template`` — путь в ``config/prompts``."""
    specs = []
    for path in sorted((config_dir / "scenarios").glob("*.yaml")):
        raw = yaml.safe_load(path.read_text("utf-8")) or {}
        template = raw.get("prompt_template") or ""
        if template.endswith(".j2"):
            raw["prompt_template"] = (config_dir / "prompts" / template).read_text("utf-8")
        specs.append(ScenarioSpec.model_validate(raw))
    return specs


async def seed(db: AsyncSession, config_dir: Path) -> int:
    """Добавляет встроенные сценарии, которых ещё нет; правки админа не перезаписываются."""
    existing = set((await db.scalars(select(Scenario.code))).all())
    added = 0
    for spec in load_seed(config_dir):
        if spec.code in existing:
            continue
        scenario = Scenario(source="seed")
        apply_spec(scenario, spec)
        db.add(scenario)
        added += 1
    await db.commit()
    if added:
        log.info("scenarios.seeded", added=added)
    return added


def now_text(now: datetime, timezone: str) -> str:
    from app.modules.completions.prompt import format_now

    return format_now(now, timezone)
