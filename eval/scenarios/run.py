"""Эталонные запросы сценариев (§18): ответ модели сценария + оценка LLM-судьёй, сравнение с
прошлым прогоном.

    uv run python eval/scenarios/run.py [--only contract_review] [--report report.json]
        [--baseline eval/scenarios/baseline.json]

Для каждого кейса собирается тот же системный промпт, что в чате сценария (базовый, данные
пользователя-примера, промпт сценария из БД или из seed), модель сценария отвечает без RAG и
инструментов, затем служебная модель оценивает ответ по критерию от 1 до 5. Цифры имеют смысл на
настоящих моделях; на fake-llm проверяется только сам прогон. Ручная проверка выборки — по отчёту.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.core.config import Settings, get_settings
from app.modules.completions.prompt import PromptRenderer, PromptUser, system_prompt
from app.modules.llm.registry import ModelRegistry
from app.modules.scenarios.models import Scenario
from app.modules.scenarios.service import load_seed, now_text, render_prompt

HERE = Path(__file__).resolve().parent
JUDGE_ROLE = "utility"
USER = PromptUser(
    full_name="Иванов Иван Петрович",
    title="Юрисконсульт",
    department="Юридический отдел",
    address="Иван Петрович",
)
JUDGE = """Оцени ответ ассистента по критерию. Поставь целую оценку от 1 (не выполнен) до 5
(выполнен полностью и без ошибок). Ответь одной строкой: «Оценка: N» и кратко почему.

Вопрос: {q}
Критерий: {criteria}
Ответ ассистента:
<<<
{answer}
>>>"""


def load_cases(only: str | None = None) -> dict[str, list[dict[str, str]]]:
    cases: dict[str, list[dict[str, str]]] = {}
    for path in sorted(HERE.glob("*.yaml")):
        data = yaml.safe_load(path.read_text("utf-8"))
        if only and data["scenario"] != only:
            continue
        cases[data["scenario"]] = data["cases"]
    return cases


def score_of(text: str) -> int | None:
    match = re.search(r"Оценка:\s*([1-5])", text)
    return int(match.group(1)) if match else None


async def _complete(registry: ModelRegistry, role: str, messages: list[dict[str, str]]) -> str:
    plan = registry.plan(role, thinking=False)
    response = await registry.client(role).chat.completions.create(
        messages=messages,  # type: ignore[arg-type]
        **{**plan.params, "max_tokens": 1500},
    )
    return response.choices[0].message.content or ""


async def evaluate(settings: Settings, only: str | None = None) -> dict[str, Any]:
    renderer = PromptRenderer(settings.config_dir / "prompts")
    scenarios = {s.code: s for s in load_seed(settings.config_dir)}
    registry = ModelRegistry(settings)
    now = datetime.now(UTC)
    report: dict[str, Any] = {"generated_at": now.isoformat(), "scenarios": {}}
    try:
        for code, cases in load_cases(only).items():
            spec = scenarios[code]
            scenario = Scenario(code=code, name=spec.name, prompt_template=spec.prompt_template)
            system = "\n\n".join(
                x
                for x in (
                    system_prompt(renderer, settings, USER, now),
                    render_prompt(
                        scenario,
                        {
                            "user": USER.__dict__,
                            "company": settings.chat.company_name,
                            "now": now_text(now, settings.chat.timezone),
                        },
                    ),
                )
                if x
            )
            results: list[dict[str, Any]] = []
            for case in cases:
                answer = await _complete(
                    registry,
                    spec.model_role,
                    [{"role": "system", "content": system}, {"role": "user", "content": case["q"]}],
                )
                verdict = await _complete(
                    registry,
                    JUDGE_ROLE,
                    [{"role": "user", "content": JUDGE.format(answer=answer[:6000], **case)}],
                )
                results.append(
                    {**case, "answer": answer, "verdict": verdict, "score": score_of(verdict)}
                )
            scored: list[int] = [r["score"] for r in results if r["score"] is not None]
            report["scenarios"][code] = {
                "mean": round(sum(scored) / len(scored), 2) if scored else None,
                "scored": len(scored),
                "total": len(results),
                "cases": results,
            }
    finally:
        await registry.close()
    return report


def compare(report: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    lines = []
    for code, data in report["scenarios"].items():
        before = baseline.get("scenarios", {}).get(code, {}).get("mean")
        now = data["mean"]
        delta = "" if before is None or now is None else f" ({now - before:+.2f} к прошлому)"
        lines.append(
            f"{code}: средняя оценка {now} из 5, оценено {data['scored']}/{data['total']}{delta}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="Код сценария")
    parser.add_argument("--report", type=Path, default=HERE / "report.json")
    parser.add_argument("--baseline", type=Path, help="Прошлый отчёт для сравнения")
    args = parser.parse_args(argv)
    report = asyncio.run(evaluate(get_settings(), args.only))
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    baseline = (
        json.loads(args.baseline.read_text("utf-8"))
        if args.baseline and args.baseline.exists()
        else {}
    )
    for line in compare(report, baseline):
        print(line)
    print(f"Отчёт: {args.report}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
