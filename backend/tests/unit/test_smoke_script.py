"""Smoke-скрипт ``scripts/smoke.py``: разбор потока и вердикты (без стенда)."""

from __future__ import annotations

import importlib.util
import sys
from typing import Any

import pytest

from app.core.config import REPO_ROOT


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("smoke_script", REPO_ROOT / "scripts/smoke.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _module()


def test_answer_from_events() -> None:
    events = [
        (1, "message.start", {}, 0.0),
        (2, "content.delta", {"text": "Добрый "}, 1.0),
        (3, "content.delta", {"text": "день"}, 2.5),
        (4, "title", {"title": "Привет"}, 2.6),
        (5, "message.end", {"status": "completed"}, 2.7),
    ]
    answer = smoke.to_answer(events)
    assert (answer.status, answer.text, answer.deltas) == ("completed", "Добрый день", 2)
    assert answer.spread_s == 1.5
    assert answer.first("title") == {"title": "Привет"} and answer.first("file") is None
    # Оборванный поток — не «завершён».
    assert smoke.to_answer(events[:3]).status == "нет message.end"


def test_expect_raises_with_reason() -> None:
    smoke.expect(True, "не важно")
    with pytest.raises(smoke.CheckError, match="нет заголовка"):
        smoke.expect("", "у чата нет заголовка")


def test_defaults_are_for_dev_stand() -> None:
    args = smoke.parse_args([])
    assert (args.provider, args.login, args.admin, args.fake) == ("dev", "petrov", None, False)
