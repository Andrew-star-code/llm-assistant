"""Сценарии: seed-файлы, рендер промпта в песочнице, видимость по ролям."""

from __future__ import annotations

import pytest

from app.core.config import DEFAULT_CONFIG_DIR
from app.core.errors import AppError
from app.modules.scenarios.models import Scenario
from app.modules.scenarios.service import (
    ICONS,
    check_template,
    load_seed,
    render_prompt,
    sample_context,
    visible,
)
from app.modules.tools.registry import all_tools


def test_seed_files_are_valid() -> None:
    specs = {s.code: s for s in load_seed(DEFAULT_CONFIG_DIR)}
    assert {"contract_review", "it_support"} <= set(specs)
    for spec in specs.values():
        check_template(spec.prompt_template)  # промпт из config/prompts/scenarios подставлен
        assert spec.prompt_template.strip()
        assert all(isinstance(p, str) for p in spec.starter_prompts)
        assert set(spec.tools or []) <= set(all_tools())
        assert spec.icon in ICONS


def test_prompt_renders_variables_in_sandbox() -> None:
    scenario = Scenario(
        code="x", name="Тест", prompt_template="{{ scenario.name }}: {{ user.address }} {{ nope }}!"
    )
    assert render_prompt(scenario, sample_context()) == "Тест: Иван Петрович !"
    # Песочница: доступ к внутренностям Python запрещён.
    with pytest.raises(AppError):
        check_template("{{ ''.__class__.__mro__[1].__subclasses__() }}")
    with pytest.raises(AppError):
        check_template("{% if %}")


def test_visibility_by_roles_and_activity() -> None:
    everyone = Scenario(roles=[], is_active=True)
    legal = Scenario(roles=["legal", "management"], is_active=True)
    off = Scenario(roles=[], is_active=False)
    assert visible(everyone, set())
    assert visible(legal, {"legal"}) and not visible(legal, {"it"})
    assert not visible(off, {"legal"})
