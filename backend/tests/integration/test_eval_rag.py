"""eval/rag (§10.6): скрипт индексирует корпус и считает hit@5 и MRR для четырёх конфигураций.

На моках (fake-llm) проверяем сам скрипт и свойства, которые не зависят от моделей: BM25 с русским
стеммингом находит все точные коды и словоформы. Сравнение рабочей конфигурации с остальными
(`--check`) имеет смысл только на настоящих моделях — его запускают на сервере (`make eval-rag`).
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.config import REPO_ROOT
from app.modules.rag.store import qdrant_client
from tests.integration.conftest import Infra, chat_settings


def load_eval() -> Any:
    spec = importlib.util.spec_from_file_location("eval_rag_run", REPO_ROOT / "eval/rag/run.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses ищут модуль класса в sys.modules
    spec.loader.exec_module(module)
    return module


async def test_eval_rag_reports_four_configs(
    infra: Infra, tmp_path: Path, fake_llm_url: str, qdrant_url: str
) -> None:
    run = load_eval()
    settings = chat_settings(infra, tmp_path, fake_llm_url, qdrant_url=qdrant_url)
    report = await run.evaluate(settings)
    configs = report["configs"]
    assert set(configs) == {"dense", "bm25", "hybrid", "hybrid+rerank"}
    for buckets in configs.values():
        assert buckets["all"]["n"] == 48
        assert {"exact_id", "word_form", "paraphrase", "english"} <= set(buckets)
        assert all(0 <= b["hit@5"] <= 1 and 0 <= b["mrr"] <= 1 for b in buckets.values())
    # Свойства BM25 (Qdrant, russian): точные коды и другие словоформы находятся всегда.
    assert configs["bm25"]["exact_id"]["hit@5"] == 1.0
    assert configs["bm25"]["word_form"]["hit@5"] == 1.0
    assert configs["hybrid"]["exact_id"]["hit@5"] == 1.0
    assert "|" in run.render(report)
    # Все стадии отработали — иначе --check считает сравнение недействительным.
    assert report["degraded"] == {}
    assert not [p for p in run.check(report) if "пропущена" in p]
    # Вопросы без ответа — отдельно от hit@5/MRR; порог подбирается по трассе рабочей конфигурации.
    assert report["no_answer"]["hybrid+rerank"]["n"] == 8
    assert [r["threshold"] for r in report["threshold_sweep"]] == list(run.SWEEP)
    assert report["recommended_threshold"] in run.SWEEP
    assert "Порог реранкера" in run.render_sweep(report)


def test_threshold_sweep_reselects_from_trace(infra: Infra, tmp_path: Path) -> None:
    run = load_eval()
    settings = chat_settings(infra, tmp_path, "http://unused")
    settings.rag.search.final_k = 3
    settings.rag.search.max_per_document = 2

    def cand(doc: str, score: float | None) -> dict[str, Any]:
        return {"document_id": doc, "rerank": score}

    # Правильный документ b — с низким баллом (как у настоящего реранкера на коротких запросах).
    answerable = [cand("a", 0.9), cand("a", 0.8), cand("a", 0.7), cand("b", 0.015), cand("c", None)]
    noise = [cand("a", 0.02), cand("c", 0.004)]
    # Не больше двух фрагментов на документ.
    assert run.reselect(answerable, 0.0, settings) == ["a", "b"]
    assert run.reselect(answerable, 0.02, settings) == ["a"]
    names = {"a": "A", "b": "B", "c": "C"}
    traces = [
        ({"q": "1", "expected": ["B"], "type": "paraphrase"}, answerable),
        ({"q": "2", "expected": [], "type": "no_answer"}, noise),
    ]
    rows = {r["threshold"]: r for r in run.sweep(traces, names, settings)}
    assert rows[0.01]["hit@5"] == 1.0 and rows[0.01]["empty_no_answer"] == "0/1"
    assert rows[0.02]["hit@5"] == 0.0 and rows[0.03]["empty_no_answer"] == "1/1"
    assert run.recommend(list(rows.values())) == 0.01


async def test_eval_rag_on_real_knowledge_bases(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, qdrant_url: str
) -> None:
    """Прогон по настоящей базе: без индексации, документ — по названию, порог — из админки."""
    run = load_eval()
    settings = chat_settings(infra, tmp_path, fake_llm_url, qdrant_url=qdrant_url)
    _, admin = await make_client(settings)
    await admin.login("ivanov")
    code = f"real-{uuid.uuid4().hex[:6]}"
    body = {"code": code, "name": "Реальная", "level": "global", "role_ids": []}
    kb_id = (await admin.post("/api/admin/kb", json=body)).json()["id"]
    docs = {
        "Регламент отпусков.md": "# Отпуск\n\nЕжегодный отпуск — 28 календарных дней.",
        "VPN.md": "# VPN\n\nOpenVPN: если не подключается, проверьте код 2FA.",
    }
    for name, text in docs.items():
        response = await admin.post(
            f"/api/admin/kb/{kb_id}/documents",
            files={"file": (name, text.encode(), "text/markdown")},
        )
        assert response.json()["status"] == "ready", response.text
    url = "/api/admin/kb/search-settings"
    assert (await admin.request("PUT", url, json={"score_threshold": 0.0123})).status_code == 200

    questions = tmp_path / "questions.yaml"
    items = [
        {"q": "OpenVPN", "expected": ["VPN"], "type": "english"},
        {"q": "отпусков календарных", "expected": ["Регламент отпусков"], "type": "word_form"},
        {"q": "что-то", "expected": ["Опечатка"], "type": "paraphrase"},
        {"q": "рецепт борща", "expected": [], "type": "no_answer"},
    ]
    questions.write_text(yaml.safe_dump({"questions": items}, allow_unicode=True), "utf-8")
    report = await run.evaluate(settings, kb_codes=[code], questions_path=questions)

    assert report["source"] == f"базы {code}" and report["threshold"] == 0.0123
    assert report["warnings"] == ["в базах нет готового документа «Опечатка»"]
    assert report["configs"]["bm25"]["all"]["n"] == 3
    assert report["configs"]["bm25"]["english"]["hit@5"] == 1.0
    assert report["configs"]["bm25"]["word_form"]["hit@5"] == 1.0
    assert report["no_answer"]["hybrid+rerank"]["n"] == 1
    # Настоящая коллекция не тронута.
    client = qdrant_client(settings)
    try:
        assert await client.collection_exists("kb_chunks")
        assert not await client.collection_exists(run.COLLECTION)
    finally:
        await client.close()

    with pytest.raises(SystemExit, match="Нет баз знаний с кодами: nope"):
        await run.evaluate(settings, kb_codes=["nope"], questions_path=questions)
