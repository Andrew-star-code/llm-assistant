"""eval/rag (§10.6): скрипт индексирует корпус и считает hit@5 и MRR для четырёх конфигураций.

На моках (fake-llm) проверяем сам скрипт и свойства, которые не зависят от моделей: BM25 с русским
стеммингом находит все точные коды и словоформы. Сравнение рабочей конфигурации с остальными
(`--check`) имеет смысл только на настоящих моделях — его запускают на сервере (`make eval-rag`).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from app.core.config import REPO_ROOT
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
