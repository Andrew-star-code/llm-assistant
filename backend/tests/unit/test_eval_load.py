"""Нагрузочный тест ``eval/load/run.py``: расчёт отчёта и сверка с целями §18.4 (без стенда)."""

from __future__ import annotations

import importlib.util
import sys
from typing import Any

from app.core.config import REPO_ROOT


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("eval_load_run", REPO_ROOT / "eval/load/run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load = _module()


def test_percentile_is_nearest_rank() -> None:
    values = [float(i) for i in range(1, 21)]
    assert load.percentile(values, 0.95) == 19.0
    assert load.percentile(values, 0.5) == 10.0
    assert load.percentile([3.0], 0.95) == 3.0


def _report(samples: list[Any]) -> Any:
    return load.build_report(
        samples, base_url="http://x", concurrency=10, prompt="п", duration_s=10.0
    )


def test_report_meets_targets() -> None:
    ok = load.Sample("completed", accept_s=0.1, ttft_s=0.5, total_s=9.0, tokens=300)
    ok.tokens_per_s = 33.0
    report = _report([ok] * 20)
    assert report.statuses == {"completed": 20} and report.answers_per_s == 2.0
    assert report.ttft_s == {"p50": 0.5, "p95": 0.5, "max": 0.5}
    assert report.checks == {"all_completed": True, "ttft_p95": True, "tokens_per_s": True}
    assert "все ответы завершены: да" in load.render(report)


def test_report_flags_missed_targets() -> None:
    slow = load.Sample("completed", accept_s=0.1, ttft_s=3.5, total_s=30.0, tokens=300)
    slow.tokens_per_s = 11.0
    limited = load.Sample("limited", accept_s=0.05, error="limit_exceeded")
    report = _report([slow] * 19 + [limited])
    assert report.statuses == {"completed": 19, "limited": 1}
    assert report.errors == {"limit_exceeded": 1}
    assert report.checks == {"all_completed": False, "ttft_p95": False, "tokens_per_s": False}
    # Без единого завершённого ответа отчёт не падает и цели не считаются достигнутыми.
    empty = _report([limited])
    assert empty.ttft_s == {} and not any(empty.checks.values())
    assert "нет данных" in load.render(empty)


def test_defaults_match_dev_stand() -> None:
    args = load.parse_args([])
    assert args.concurrency == 10 and args.provider == "dev" and args.admin is None
    assert len(args.logins.split(",")) * 2 >= args.concurrency  # лимит — 2 ответа на пользователя
