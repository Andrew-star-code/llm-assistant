"""Оценка поиска по базам знаний (§10.6): hit@5 и MRR для четырёх конфигураций.

    uv run python eval/rag/run.py [--check] [--json report.json]
    uv run python eval/rag/run.py --kb regulations,it-docs --questions my-questions.yaml

Корпус ``eval/rag/corpus`` индексируется тем же кодом, что и базы знаний (разбор, чанкинг, dense +
BM25), но в отдельную коллекцию ``eval_rag_chunks`` — рабочие базы не затрагиваются. Модели и Qdrant
берутся из конфигурации приложения (``APP_ENV``, ``APP_CONFIG_DIR``, ``APP_*``): на дев-стенде —
fake-llm и TEI, на сервере — настоящие bge-m3 и реранкер; именно там цифры имеют смысл.

``--check`` завершается с ошибкой, если гибрид с реранкером хуже любой другой конфигурации по hit@5
или MRR (рабочая конфигурация должна быть не хуже остальных).

Вопросы ``no_answer`` (ответа в корпусе нет) в hit@5 и MRR не входят: для них считается, сколько
раз поиск честно вернул пустой список. Порог реранкера подбирается по трассе рабочей конфигурации
(``threshold_sweep``): отбор повторяется для сетки порогов без новых запросов к моделям, а
``recommended_threshold`` — наибольший порог, при котором hit@5 и MRR не хуже, чем без порога.

``--kb`` — прогон по настоящим базам знаний (уже проиндексированным, ничего не пишется): ожидаемый
документ в вопросах — его название в базе. Так порог подбирают на реальных документах.
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
from app.workers.jobs import make_chunks, parse_bytes, worker_context

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
NO_ANSWER = "no_answer"
SWEEP = (0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.1, 0.15, 0.2, 0.3)


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


def first_rank(ranked: list[str], expected: list[str]) -> int | None:
    return next((i for i, name in enumerate(ranked, 1) if name in expected), None)


def reselect(candidates: list[dict[str, Any]], threshold: float, settings: Settings) -> list[str]:
    """Повтор отбора ``search`` по трассе с другим порогом: id документов по убыванию балла.

    Надбавок за уровень базы по умолчанию нет (``rag.search.level_boost``), поэтому порядок — по
    баллу реранкера.
    """
    search_settings = settings.rag.search
    scored = sorted(
        (c for c in candidates if c["rerank"] is not None), key=lambda c: c["rerank"], reverse=True
    )
    limit, per_doc_limit = search_settings.final_k, search_settings.max_per_document
    per_document: dict[str, int] = defaultdict(int)
    fragments = 0
    selected: list[str] = []
    for c in scored:
        if c["rerank"] < threshold or per_document[c["document_id"]] >= per_doc_limit:
            continue
        if fragments >= limit:
            break
        fragments += 1
        per_document[c["document_id"]] += 1
        if c["document_id"] not in selected:
            selected.append(c["document_id"])
    return selected


def sweep(
    traces: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    names: dict[str, str],
    settings: Settings,
) -> list[dict[str, Any]]:
    """hit@5, MRR и пустые ответы рабочей конфигурации для сетки порогов реранкера."""
    rows = []
    for threshold in SWEEP:
        score, empty, empty_no_answer, no_answer = Score(), 0, 0, 0
        for item, candidates in traces:
            ranked = [names.get(d, "?") for d in reselect(candidates, threshold, settings)]
            if item["type"] == NO_ANSWER:
                no_answer += 1
                empty_no_answer += int(not ranked)
                continue
            rank = first_rank(ranked, item["expected"])
            score.total += 1
            score.hits += int(rank is not None and rank <= K)
            score.rr += 1 / rank if rank else 0.0
            empty += int(not ranked)
        rows.append(
            {
                "threshold": threshold,
                "hit@5": round(score.hit_at_k, 3),
                "mrr": round(score.mrr, 3),
                "empty_answerable": empty,
                "empty_no_answer": f"{empty_no_answer}/{no_answer}",
            }
        )
    return rows


def recommend(rows: list[dict[str, Any]]) -> float | None:
    """Наибольший порог без потерь hit@5 и MRR относительно порога 0."""
    if not rows:
        return None
    base = rows[0]
    lossless = [
        r["threshold"]
        for r in rows
        if r["hit@5"] >= base["hit@5"] - 1e-9 and r["mrr"] >= base["mrr"] - 1e-9
    ]
    return float(max(lossless))


@dataclass
class RealBases:
    """Настоящие базы знаний для прогона: id, названия документов и действующий порог."""

    kb_ids: tuple[uuid.UUID, ...]
    titles: set[str]
    threshold: float


async def load_bases(settings: Settings, codes: list[str]) -> RealBases:
    from sqlalchemy import select

    from app.modules.admin import app_settings
    from app.modules.kb.models import KbDocument, KnowledgeBase

    async with worker_context(settings) as ctx, ctx.sessions() as db:
        rows = (
            await db.execute(
                select(KnowledgeBase.code, KnowledgeBase.id).where(
                    KnowledgeBase.code.in_(codes), KnowledgeBase.deleted_at.is_(None)
                )
            )
        ).all()
        found = {code: kb_id for code, kb_id in rows}
        unknown = [c for c in codes if c not in found]
        if unknown:
            raise SystemExit(f"Нет баз знаний с кодами: {', '.join(unknown)}")
        titles = set(
            (
                await db.scalars(
                    select(KbDocument.title).where(
                        KbDocument.kb_id.in_(found.values()),
                        KbDocument.deleted_at.is_(None),
                        KbDocument.status == "ready",
                    )
                )
            ).all()
        )
        # Порог, который действует в чате: с поправкой из админки, если она есть.
        effective = await app_settings.search_settings(db, settings)
    return RealBases(tuple(found.values()), titles, effective.rerank.score_threshold)


async def evaluate(
    settings: Settings,
    *,
    kb_codes: list[str] | None = None,
    questions_path: Path | None = None,
) -> dict[str, Any]:
    path = questions_path or HERE / "questions.yaml"
    questions = yaml.safe_load(path.read_text("utf-8"))["questions"]
    bases = await load_bases(settings, kb_codes) if kb_codes else None
    warnings: list[str] = []
    if bases is not None:
        # Опечатка в названии документа — тихий «промах»; лучше сказать сразу.
        missing = sorted({t for q in questions for t in q["expected"]} - bases.titles)
        warnings += [f"в базах нет готового документа «{t}»" for t in missing]
        settings.rag.search.rerank.score_threshold = bases.threshold
    registry = ModelRegistry(settings)
    try:
        names: dict[str, str] = {}
        if bases is None:
            names = await index_corpus(settings, registry)
            scope = Scope(kb_ids=(EVAL_KB,), kb_collection=COLLECTION)
        else:
            scope = Scope(kb_ids=bases.kb_ids)
        scores: dict[str, dict[str, Score]] = {c: defaultdict(Score) for c in CONFIGS}
        misses: dict[str, list[str]] = defaultdict(list)
        # Вопросы без ответа: сколько раз конфигурация вернула пустой список.
        no_answer: dict[str, Score] = defaultdict(Score)
        no_answer_top: dict[str, float | None] = {}
        traces: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
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
                    for c in result.trace["candidates"]:
                        names.setdefault(c["document_id"], str(c["title"]))
                    ranked: list[str] = []
                    for fragment in result.fragments:
                        name = names.get(fragment.document_id, fragment.title)
                        if name not in ranked:
                            ranked.append(name)
                    if config == WORKING and not result.degraded:
                        traces.append((item, result.trace["candidates"]))
                    if item["type"] == NO_ANSWER:
                        no_answer[config].total += 1
                        no_answer[config].hits += int(not ranked)
                        if config == WORKING:
                            top = [c["rerank"] for c in result.trace["candidates"] if c["rerank"]]
                            no_answer_top[item["q"]] = max(top, default=None)
                        continue
                    rank = first_rank(ranked, item["expected"])
                    for bucket in ("all", item["type"]):
                        s = scores[config][bucket]
                        s.total += 1
                        s.hits += int(rank is not None and rank <= K)
                        s.rr += 1 / rank if rank else 0.0
                    if config == WORKING and (rank is None or rank > K):
                        misses[config].append(f"{item['q']} → {ranked[:K]}")
        finally:
            await client.close()
            if bases is None:  # настоящие базы не трогаем
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
        "source": f"базы {', '.join(kb_codes)}" if kb_codes else "корпус eval/rag/corpus",
        "questions": str(path),
        "warnings": warnings,
        "misses": dict(misses),
        "no_answer": {config: {"empty": s.hits, "n": s.total} for config, s in no_answer.items()},
        "no_answer_top_rerank": no_answer_top,
        "threshold": settings.rag.search.rerank.score_threshold,
        "threshold_sweep": (rows := sweep(traces, names, settings)),
        "recommended_threshold": recommend(rows),
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


def render_sweep(report: dict[str, Any]) -> str:
    lines = [
        f"Порог реранкера: действует {report['threshold']}, "
        f"рекомендуется по eval {report['recommended_threshold']}",
        "| Порог | hit@5 | MRR | пусто (есть ответ) | пусто (нет ответа) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report["threshold_sweep"]:
        lines.append(
            f"| {r['threshold']} | {r['hit@5']} | {r['mrr']} | {r['empty_answerable']} "
            f"| {r['empty_no_answer']} |"
        )
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
    parser.add_argument(
        "--kb",
        help="Коды настоящих баз знаний через запятую: прогон по их документам без индексации",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        help="Свой файл вопросов (формат — eval/rag/questions.yaml; с --kb expected — названия "
        "документов в базе)",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    settings.rag.search.rerank.timeout_s = args.rerank_timeout
    codes = [c.strip() for c in args.kb.split(",") if c.strip()] if args.kb else None
    report = asyncio.run(evaluate(settings, kb_codes=codes, questions_path=args.questions))
    print(f"Источник: {report['source']}, вопросы: {report['questions']}")
    for warning in report["warnings"]:
        print(f"ВНИМАНИЕ: {warning}", file=sys.stderr)
    print(f"Модели: {report['models']['embed']}, реранкер {report['models']['rerank']}")
    print(render(report))
    for miss in report["misses"].get(WORKING, []):
        print(f"  промах {WORKING}: {miss}")
    for config, value in report["no_answer"].items():
        print(f"  без ответа, {config}: пустой список в {value['empty']} из {value['n']}")
    print(render_sweep(report))
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    problems = check(report)
    for problem in problems:
        print(f"ОШИБКА: {problem}", file=sys.stderr)
    return 1 if args.check and problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
