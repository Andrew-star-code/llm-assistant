"""eval/scenarios (§18): эталоны есть для каждого встроенного сценария, разбор оценки судьи."""

from __future__ import annotations

import importlib.util
import sys
from typing import Any

from app.core.config import DEFAULT_CONFIG_DIR, REPO_ROOT
from app.modules.scenarios.service import load_seed


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location(
        "eval_scenarios_run", REPO_ROOT / "eval/scenarios/run.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_builtin_scenario_has_10_to_20_cases() -> None:
    run = load_runner()
    cases = run.load_cases()
    assert set(cases) == {s.code for s in load_seed(DEFAULT_CONFIG_DIR)}
    for items in cases.values():
        assert 10 <= len(items) <= 20
        assert all(item["q"].strip() and item["criteria"].strip() for item in items)


def test_judge_score_parsing() -> None:
    run = load_runner()
    assert run.score_of("Оценка: 4 — почти всё верно") == 4
    assert run.score_of("Не могу оценить") is None
