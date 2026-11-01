"""Гибридный поиск с реранкером (§10.4).

1. В каждой доступной коллекции — запрос ``dense`` и запрос ``bm25`` с фильтром прав в каждом
   (фильтр строит сервер, ``Scope``). Запросы идут отдельно, а не одним prefetch Query API: так в
   трассировке видны ранги каждого списка, а отказ одного запроса не роняет другой.
2. Слияние RRF (``1 / (k + ранг)``, k = 60 — как в Qdrant) или DBSF; кандидаты всех коллекций —
   в один список без дублей.
3. До ``max_candidates`` лучших — в реранкер (``POST /v1/rerank``), балл 0..1 + бонус уровня →
   порог → не больше ``max_per_document`` с документа → ``final_k``.
4. Реранкер недоступен или не ответил за ``timeout_s`` → порядок RRF без порога, ``fallback_k``
   фрагментов, стадия помечается пропущенной (инцидент пишет вызывающий код).
5. Фрагменты расширяются соседними чанками того же документа и нумеруются для цитат.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import structlog
from qdrant_client import AsyncQdrantClient, models

from app.core.config import SearchSettings
from app.modules.llm.registry import ModelRegistry
from app.modules.rag.store import (
    ATTACHMENT_COLLECTION,
    KB_COLLECTION,
    PERSONAL_COLLECTION,
    bm25_document,
    chunk_id,
    embed,
)

log = structlog.stdlib.get_logger("app.rag")
RERANK_ROLE = "rerank"
SNIPPET_CHARS = 320


@dataclass(frozen=True)
class Scope:
    """Что пользователю можно искать — вычисляется сервером при каждом запросе (§10.1)."""

    kb_ids: tuple[UUID, ...] = ()  # общие и ролевые базы → kb_chunks
    owner_id: UUID | None = None  # личные базы → personal_chunks
    personal_kb_ids: tuple[UUID, ...] = ()
    attachment_ids: tuple[UUID, ...] = ()  # вложения текущего чата → attachment_chunks
    kb_names: dict[str, str] = field(default_factory=dict)
    kb_collection: str = KB_COLLECTION  # другая коллекция — только для eval/rag

    def filters(self) -> list[tuple[str, models.Filter]]:
        def any_of(key: str, values: Sequence[UUID]) -> models.FieldCondition:
            return models.FieldCondition(
                key=key, match=models.MatchAny(any=[str(v) for v in values])
            )

        result: list[tuple[str, models.Filter]] = []
        if self.kb_ids:
            result.append((self.kb_collection, models.Filter(must=[any_of("kb_id", self.kb_ids)])))
        if self.owner_id is not None and self.personal_kb_ids:
            owner = models.FieldCondition(
                key="owner_id", match=models.MatchValue(value=str(self.owner_id))
            )
            result.append(
                (
                    PERSONAL_COLLECTION,
                    models.Filter(must=[owner, any_of("kb_id", self.personal_kb_ids)]),
                )
            )
        if self.attachment_ids:
            result.append(
                (
                    ATTACHMENT_COLLECTION,
                    models.Filter(must=[any_of("document_id", self.attachment_ids)]),
                )
            )
        return result

    @property
    def empty(self) -> bool:
        return not self.filters()


@dataclass
class Candidate:
    collection: str
    chunk_id: str
    payload: dict[str, Any]
    dense_rank: int | None = None
    bm25_rank: int | None = None
    dense_score: float | None = None
    bm25_score: float | None = None
    fused: float = 0.0
    rerank: float | None = None
    score: float | None = None
    status: str = "candidate"  # selected | below_threshold | per_document | beyond_final_k | …

    @property
    def document_id(self) -> str:
        return str(self.payload.get("document_id", ""))

    def trace(self) -> dict[str, Any]:
        def r(value: float | None) -> float | None:
            return None if value is None else round(value, 4)

        return {
            "chunk_id": self.chunk_id,
            "collection": self.collection,
            "document_id": self.document_id,
            "title": self.payload.get("title"),
            "page": self.payload.get("page_from"),
            "dense_rank": self.dense_rank,
            "bm25_rank": self.bm25_rank,
            "rrf": r(self.fused),
            "rerank": r(self.rerank),
            "status": self.status,
        }


@dataclass(frozen=True)
class Fragment:
    index: int
    collection: str
    chunk_id: str
    document_id: str
    kb_id: str | None
    file_id: str | None
    level: str
    title: str
    kb_name: str | None
    page: int | None
    section: str | None
    text: str  # с соседними чанками — для промпта
    snippet: str  # для карточки источника
    score: float | None

    @property
    def kind(self) -> str:
        return "attachment" if self.collection == ATTACHMENT_COLLECTION else "kb"


@dataclass
class SearchResult:
    fragments: list[Fragment]
    trace: dict[str, Any]
    degraded: list[str]  # пропущенные стадии: dense, bm25, rerank


@dataclass
class _Lists:
    dense: dict[str, list[models.ScoredPoint]] = field(default_factory=dict)
    bm25: dict[str, list[models.ScoredPoint]] = field(default_factory=dict)


async def _query_lists(
    client: AsyncQdrantClient,
    registry: ModelRegistry,
    settings: SearchSettings,
    *,
    query: str,
    bm25_query: str,
    scope: Scope,
    stages: dict[str, str],
    use_dense: bool,
    use_bm25: bool,
) -> _Lists:
    lists = _Lists()
    targets = [(c, f) for c, f in scope.filters() if await client.collection_exists(c)]
    vector: list[float] | None = None
    if use_dense:
        try:
            [vector] = await embed(registry, [query])
        except Exception as exc:
            stages["dense"] = f"skipped: embed — {type(exc).__name__}"
    calls: list[tuple[str, str, Any]] = []
    for collection, flt in targets:
        if vector is not None:
            calls.append(
                (
                    "dense",
                    collection,
                    client.query_points(
                        collection, query=vector, using="dense", query_filter=flt,
                        limit=settings.prefetch.dense, with_payload=True,
                    ),
                )
            )  # fmt: skip
        if use_bm25:
            calls.append(
                (
                    "bm25",
                    collection,
                    client.query_points(
                        collection, query=bm25_document(bm25_query, settings.bm25), using="bm25",
                        query_filter=flt, limit=settings.prefetch.bm25, with_payload=True,
                    ),
                )
            )  # fmt: skip
    results = await asyncio.gather(*(c for _, _, c in calls), return_exceptions=True)
    for (kind, collection, _), result in zip(calls, results, strict=True):
        if isinstance(result, BaseException):
            stages[kind] = f"skipped: {collection} — {type(result).__name__}"
            log.warning("rag.query_failed", stage=kind, collection=collection, error=str(result))
            continue
        getattr(lists, kind)[collection] = list(result.points)
    stages.setdefault("dense", "ok" if use_dense else "disabled")
    stages.setdefault("bm25", "ok" if use_bm25 else "disabled")
    return lists


def _fuse(lists: _Lists, settings: SearchSettings) -> list[Candidate]:
    candidates: dict[str, Candidate] = {}

    def add(kind: str, collection: str, points: list[models.ScoredPoint]) -> None:
        for rank, point in enumerate(points, start=1):
            key = str(point.id)
            candidate = candidates.get(key) or Candidate(collection, key, dict(point.payload or {}))
            candidates[key] = candidate
            setattr(candidate, f"{kind}_rank", rank)
            setattr(candidate, f"{kind}_score", point.score)

    for collection, points in lists.dense.items():
        add("dense", collection, points)
    for collection, points in lists.bm25.items():
        add("bm25", collection, points)

    if settings.fusion == "rrf":
        for c in candidates.values():
            c.fused = sum(
                1 / (settings.rrf_k + rank) for rank in (c.dense_rank, c.bm25_rank) if rank
            )
    else:  # dbsf: нормировка каждого списка по mean ± 3σ, сумма
        for kind in ("dense", "bm25"):
            for points in getattr(lists, kind).values():
                scores = [p.score for p in points]
                if not scores:
                    continue
                mean = sum(scores) / len(scores)
                sigma = math.sqrt(sum((s - mean) ** 2 for s in scores) / len(scores)) or 1.0
                low, high = mean - 3 * sigma, mean + 3 * sigma
                for p in points:
                    norm = (min(max(p.score, low), high) - low) / (high - low)
                    candidates[str(p.id)].fused += norm
    return sorted(candidates.values(), key=lambda c: c.fused, reverse=True)


TEI_BATCH = 32  # text-embeddings-inference по умолчанию принимает не больше 32 текстов


def _rerank_url(base_url: str, api: str) -> str:
    url = base_url.rstrip("/")
    # У TEI нет префикса /v1 у реранка: http://rerank:80/v1 → http://rerank:80/rerank.
    if api == "tei" and url.endswith("/v1"):
        url = url[: -len("/v1")]
    return f"{url}/rerank"


async def rerank(
    registry: ModelRegistry, query: str, texts: Sequence[str], timeout_s: float
) -> list[float]:
    """Баллы реранкера 0..1 в порядке ``texts``.

    Форматы (``models.rerank.api``): ``openai`` — vLLM/Jina ``/v1/rerank`` (``documents`` →
    ``results[].relevance_score``); ``tei`` — text-embeddings-inference ``/rerank`` (``texts`` →
    список ``{index, score}``, пакетами по ``TEI_BATCH``, баллы через сигмоиду — тоже 0..1).
    """
    endpoint = registry.get(RERANK_ROLE)
    headers = {}
    if endpoint.api_key is not None:
        headers["Authorization"] = f"Bearer {endpoint.api_key.get_secret_value()}"
    url = _rerank_url(endpoint.base_url, endpoint.api)
    scores = [0.0] * len(texts)
    async with httpx.AsyncClient(timeout=timeout_s) as http:
        if endpoint.api == "tei":
            for start in range(0, len(texts), TEI_BATCH):
                batch = list(texts[start : start + TEI_BATCH])
                response = await http.post(
                    url,
                    json={"query": query, "texts": batch, "truncate": True, "raw_scores": False},
                    headers=headers,
                )
                response.raise_for_status()
                for item in response.json():
                    scores[start + int(item["index"])] = float(item["score"])
            return scores
        response = await http.post(
            url,
            json={"model": endpoint.model, "query": query, "documents": list(texts)},
            headers=headers,
        )
        response.raise_for_status()
        body = response.json()
    for item in body.get("results", []):
        scores[int(item["index"])] = float(item.get("relevance_score", item.get("score", 0.0)))
    return scores


async def _neighbors(
    client: AsyncQdrantClient, selected: list[Candidate], depth: int
) -> dict[str, dict[str, Any]]:
    """Payload соседних чанков (по вычисленным id) — для связности фрагментов."""
    if depth <= 0:
        return {}
    wanted: dict[str, set[str]] = {}
    for c in selected:
        index = int(c.payload.get("chunk_index", 0))
        version = int(c.payload.get("version", 1))
        for offset in range(-depth, depth + 1):
            if offset and index + offset >= 0:
                wanted.setdefault(c.collection, set()).add(
                    chunk_id(c.document_id, version, index + offset)
                )
    found: dict[str, dict[str, Any]] = {}
    for collection, ids in wanted.items():
        try:
            points = await client.retrieve(collection, ids=list(ids), with_payload=True)
        except Exception as exc:
            log.warning("rag.neighbors_failed", collection=collection, error=str(exc))
            continue
        found.update({str(p.id): dict(p.payload or {}) for p in points})
    return found


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"\w+", text.lower()) if len(w) > 1}


def best_page(payload: dict[str, Any], query: str) -> int | None:
    """Страница внутри чанка, где больше всего слов запроса (по основам); иначе первая."""
    first = payload.get("page_from")
    spans = payload.get("page_spans") or []
    if len(spans) < 2:
        return int(first) if first is not None else None
    body = str(payload.get("body", ""))
    wanted = _stems(query)
    best, best_score = int(first) if first is not None else None, 0
    for page, start, end in spans:
        score = len(wanted & _stems(body[start:end]))
        if score > best_score:
            best, best_score = int(page), score
    return best


def _expand(c: Candidate, neighbors: dict[str, dict[str, Any]], depth: int, taken: set[str]) -> str:
    index = int(c.payload.get("chunk_index", 0))
    version = int(c.payload.get("version", 1))
    parts: list[str] = []
    for offset in range(-depth, depth + 1):
        key = chunk_id(c.document_id, version, index + offset)
        if offset == 0:
            parts.append(str(c.payload.get("body", "")))
        elif key in neighbors and key not in taken:
            parts.append(str(neighbors[key].get("body", "")))
    return "\n\n".join(p for p in parts if p)


async def search(
    client: AsyncQdrantClient,
    registry: ModelRegistry,
    settings: SearchSettings,
    *,
    query: str,
    bm25_query: str | None = None,
    scope: Scope,
    use_dense: bool = True,
    use_bm25: bool = True,
    use_rerank: bool | None = None,
) -> SearchResult:
    started = time.monotonic()
    stages: dict[str, str] = {}
    trace: dict[str, Any] = {"query": query, "bm25_query": bm25_query or query, "stages": stages}
    if scope.empty:
        stages["scope"] = "empty"
        trace.update(candidates=[], selected=[], degraded=[], ms=0)
        return SearchResult([], trace, [])

    lists = await _query_lists(
        client, registry, settings, query=query, bm25_query=bm25_query or query, scope=scope,
        stages=stages, use_dense=use_dense, use_bm25=use_bm25,
    )  # fmt: skip
    ranked = _fuse(lists, settings)
    pool = ranked[: settings.rerank.max_candidates]
    for c in ranked[settings.rerank.max_candidates :]:
        c.status = "beyond_rerank_pool"

    rerank_on = settings.rerank.enabled if use_rerank is None else use_rerank
    reranked = False
    if pool and rerank_on:
        try:
            scores = await asyncio.wait_for(
                rerank(registry, query, [str(c.payload.get("text", "")) for c in pool],
                       settings.rerank.timeout_s),
                timeout=settings.rerank.timeout_s,
            )  # fmt: skip
            for c, score in zip(pool, scores, strict=True):
                c.rerank = score
                c.score = score + settings.level_boost.get(str(c.payload.get("level")), 0.0)
            reranked = True
            stages["rerank"] = "ok"
        except Exception as exc:
            stages["rerank"] = f"skipped: {type(exc).__name__}"
            log.warning("rag.rerank_failed", error=str(exc)[:200])
    elif pool:
        stages["rerank"] = "disabled"

    if reranked:
        ordered = sorted(pool, key=lambda c: c.score or 0.0, reverse=True)
        threshold, limit = settings.rerank.score_threshold, settings.final_k
    else:
        for c in pool:
            c.score = c.fused
        ordered = pool
        threshold, limit = None, (settings.fallback_k if rerank_on else settings.final_k)

    selected: list[Candidate] = []
    per_document: dict[str, int] = {}
    for c in ordered:
        if threshold is not None and (c.rerank or 0.0) < threshold:
            c.status = "below_threshold"
        elif per_document.get(c.document_id, 0) >= settings.max_per_document:
            c.status = "per_document"
        elif len(selected) >= limit:
            c.status = "beyond_final_k"
        else:
            c.status = "selected"
            selected.append(c)
            per_document[c.document_id] = per_document.get(c.document_id, 0) + 1

    neighbors = await _neighbors(client, selected, settings.neighbors)
    taken = {c.chunk_id for c in selected}
    fragments = []
    for number, c in enumerate(selected, start=1):
        p = c.payload
        kb_id = p.get("kb_id")
        section = " / ".join(p.get("section_path") or []) or None
        fragments.append(
            Fragment(
                index=number,
                collection=c.collection,
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                kb_id=str(kb_id) if kb_id else None,
                file_id=str(p["file_id"]) if p.get("file_id") else None,
                level=str(p.get("level", "")),
                title=str(p.get("title", "")),
                kb_name=scope.kb_names.get(str(kb_id)) if kb_id else None,
                page=best_page(p, f"{query} {bm25_query or ''}"),
                section=section,
                text=_expand(c, neighbors, settings.neighbors, taken),
                snippet=str(p.get("body", ""))[:SNIPPET_CHARS],
                score=c.score,
            )
        )
    degraded = [k for k, v in stages.items() if v.startswith("skipped")]
    trace.update(
        candidates=[c.trace() for c in ranked],
        selected=[f.chunk_id for f in fragments],
        degraded=degraded,
        ms=int((time.monotonic() - started) * 1000),
    )
    return SearchResult(fragments, trace, degraded)
