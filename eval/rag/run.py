"""Оценка поиска по базам знаний (§10.6): hit@5 и MRR для четырёх конфигураций.

    uv run python eval/rag/run.py [--check] [--json report.json]

Корпус ``eval/rag/corpus`` индексируется тем же кодом, что и базы знаний (разбор, чанкинг, dense +
BM25), но в отдельную коллекцию ``eval_rag_chunks`` — рабочие базы не затрагиваются. Модели и Qdrant
берутся из конфигурации приложения (``APP_ENV``, ``APP_CONFIG_DIR``, ``APP_*``): на дев-стенде —
fake-llm и TEI, на сервере — настоящие bge-m3 и реранкер; именно там цифры имеют смысл.

``--check`` завершается с ошибкой, если гибрид с реранкером хуже любой другой конфигурации по hit@5
или MRR (рабочая конфигурация должна быть не хуже остальных).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.core.config import Settings, get_settings
from app.modules.ingestion.parsers import split_pages
from app.modules.llm.registry import ModelRegistry
from app.modules.rag.search import Scope, search
from app.modules.rag.store import DocumentRef, qdrant_client, write_document
from app.workers.jobs import make_chunks, parse_bytes

HERE = Path(__file__).resolve().parent
COLLECTION = "eval_rag_chunks"
EVAL_KB = uuid.UUID("00000000-0000-0000-0000-00000000e7a1")
CONFIGS: dict[str, dict[str, bool]] = {
    "dense": {"use_dense": True, "use_bm25": False, "use_rerank": False},
    "bm25": {"use_dense": False, "use_bm25": True, "use_rerank": False},
    "hybrid": {"use_dense": True, "use_bm25": True, "use_rerank": False},
    "hybrid+rerank": {"use_dense": True, "use_bm25": True, "use_rerank": True},
}
WORKING = "hybrid+rerank"
K = 5


@dataclass
class Score:
    hits: int = 0
    rr: float = 0.0
    total: int = 0

    @property
    def hit_at_k(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def mrr(self) -> float:
        return self.rr / self.total if self.total else 0.0


async def index_corpus(settings: Settings, registry: ModelRegistry) -> dict[str, str]:
    """Индексирует корпус; возвращает document_id → имя файла."""
    client = qdrant_client(settings)
    names: dict[str, str] = {}
    try:
        if await client.collection_exists(COLLECTION):
            await client.delete_collection(COLLECTION)
        for path in sorted((HERE / "corpus").glob("*")):
            parsed = await parse_bytes(path.read_bytes(), path.suffix.lstrip("."), settings)
            parsed.pages = split_pages(parsed.markdown()) or parsed.pages
            doc_id = uuid.uuid5(EVAL_KB, path.stem)
            ref = DocumentRef(
                collection=COLLECTION,
                document_id=doc_id,
                version=1,
                title=path.stem,
                level="global",
                kb_id=EVAL_KB,
            )
            await write_document(
                client,
                registry,
                ref,
                make_chunks(parsed, path.stem, settings),
                settings.rag.search.bm25,
            )
            names[str(doc_id)] = path.stem
    finally:
        await client.close()
    return names


async def evaluate(settings: Settings) -> dict[str, Any]:
    questions = yaml.safe_load((HERE / "questions.yaml").read_text("utf-8"))["questions"]
    registry = ModelRegistry(settings)
    try:
        names = await index_corpus(settings, registry)
        scope = Scope(kb_ids=(EVAL_KB,), kb_collection=COLLECTION)
        scores: dict[str, dict[str, Score]] = {c: defaultdict(Score) for c in CONFIGS}
        misses: dict[str, list[str]] = defaultdict(list)
        # Пропущенные стадии (например, реранкер не ответил) — иначе «гибрид + реранкер» молча
        # превращается в гибрид без реранкера и сравнение теряет смысл.
        degraded: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        client = qdrant_client(settings)
        try:
            for item in questions:
                for config, flags in CONFIGS.items():
                    result = await search(
                        client,
                        registry,
                        settings.rag.search,
                        query=item["q"],
                        scope=scope,
                        use_dense=flags["use_dense"],
                        use_bm25=flags["use_bm25"],
                        use_rerank=flags["use_rerank"],
                    )
                    for stage in result.degraded:
                        degraded[config][stage] += 1
                    ranked: list[str] = []
                    for fragment in result.fragments:
                        name = names.get(fragment.document_id, "?")
                        if name not in ranked:
                            ranked.append(name)
                    rank = next(
                        (i for i, name in enumerate(ranked, 1) if name in item["expected"]), None
                    )
                    for bucket in ("all", item["type"]):
                        s = scores[config][bucket]
                        s.total += 1
                        s.hits += int(rank is not None and rank <= K)
                        s.rr += 1 / rank if rank else 0.0
                    if config == WORKING and (rank is None or rank > K):
                        misses[config].append(f"{item['q']} → {ranked[:K]}")
        finally:
            await client.close()
            cleanup = qdrant_client(settings)
            await cleanup.delete_collection(COLLECTION)
            await cleanup.close()
    finally:
        await registry.close()
    return {
        "configs": {
            config: {
                bucket: {"hit@5": round(s.hit_at_k, 3), "mrr": round(s.mrr, 3), "n": s.total}
                for bucket, s in sorted(buckets.items())
            }
            for config, buckets in scores.items()
        },
        "misses": dict(misses),
        "degraded": {c: dict(stages) for c, stages in degraded.items()},
        "models": {
            "embed": settings.models["embed"].model,
            "rerank": f"{settings.models['rerank'].model} ({settings.models['rerank'].api})",
        },
    }


def check(report: dict[str, Any]) -> list[str]:
    """Рабочая конфигурация не хуже остальных по hit@5 и MRR (§10.6)."""
    working = report["configs"][WORKING]["all"]
    problems = [
        f"{config}: стадия {stage} пропущена в {count} запросах — сравнение недействительно"
        for config, stages in report.get("degraded", {}).items()
        for stage, count in stages.items()
    ]
    for config, buckets in report["configs"].items():
        if config == WORKING:
            continue
        for metric in ("hit@5", "mrr"):
            if buckets["all"][metric] > working[metric] + 1e-9:
                problems.append(
                    f"{WORKING} хуже {config} по {metric}: "
                    f"{working[metric]} < {buckets['all'][metric]}"
                )
    return problems


def render(report: dict[str, Any]) -> str:
    types = sorted({b for c in report["configs"].values() for b in c if b != "all"})
    head = "| Конфигурация | hit@5 | MRR | " + " | ".join(f"hit@5 {t}" for t in types) + " |"
    lines = [head, "|" + " --- |" * (3 + len(types))]
    for config, buckets in report["configs"].items():
        cells = [config, str(buckets["all"]["hit@5"]), str(buckets["all"]["mrr"])]
        cells += [str(buckets.get(t, {}).get("hit@5", "—")) for t in types]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Ошибка, если рабочая хуже других")
    parser.add_argument("--json", type=Path, help="Сохранить отчёт в JSON")
    parser.add_argument(
        "--rerank-timeout",
        type=float,
        default=120,
        help="Тайм-аут реранкера, с: eval меряет качество, а не скорость (CPU — медленно)",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    settings.rag.search.rerank.timeout_s = args.rerank_timeout
    report = asyncio.run(evaluate(settings))
    print(f"Модели: {report['models']['embed']}, реранкер {report['models']['rerank']}")
    print(render(report))
    for miss in report["misses"].get(WORKING, []):
        print(f"  промах {WORKING}: {miss}")
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    problems = check(report)
    for problem in problems:
        print(f"ОШИБКА: {problem}", file=sys.stderr)
    return 1 if args.check and problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
