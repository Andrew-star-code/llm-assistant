"""RAG (этап 4): слияние списков, выбор страницы, нумерация цитат, права менеджера БЗ."""

from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import models

from app.core.config import SearchSettings
from app.modules.kb.models import KnowledgeBase
from app.modules.kb.service import manageable
from app.modules.rag.search import Fragment, Scope, _fuse, _Lists, best_page
from app.modules.rag.service import SourceBook, cited_indexes


def point(pid: str, score: float, doc: str = "d") -> models.ScoredPoint:
    return models.ScoredPoint(id=pid, version=0, score=score, payload={"document_id": doc})


def test_rrf_combines_ranks_from_both_lists() -> None:
    lists = _Lists(
        dense={"kb_chunks": [point("a", 0.9), point("b", 0.8)]},
        bm25={"kb_chunks": [point("b", 7.0), point("c", 3.0)]},
    )
    ranked = _fuse(lists, SearchSettings())
    assert [c.chunk_id for c in ranked] == ["b", "a", "c"]
    b = ranked[0]
    assert (b.dense_rank, b.bm25_rank) == (2, 1)
    assert abs(b.fused - (1 / 62 + 1 / 61)) < 1e-9


def test_dbsf_normalizes_scores() -> None:
    lists = _Lists(dense={"x": [point("a", 0.9), point("b", 0.1)]}, bm25={})
    ranked = _fuse(lists, SearchSettings(fusion="dbsf"))
    assert ranked[0].chunk_id == "a" and 0 <= ranked[1].fused <= ranked[0].fused <= 1


def test_best_page_picks_page_with_query_words() -> None:
    body = "Введение и общие слова\n\nДоговор поставки 17-42 подписан\n\nЗаключение"
    first = body.index("Договор")
    payload: dict[str, Any] = {
        "page_from": 1,
        "body": body,
        "page_spans": [[1, 0, first - 2], [2, first, first + 31], [3, first + 33, len(body)]],
    }
    assert best_page(payload, "договора поставки") == 2
    assert best_page(payload, "ничего общего с текстом нет") == 1
    assert best_page({"page_from": 4}, "что угодно") == 4


def fragment(chunk: str) -> Fragment:
    return Fragment(
        index=1,
        collection="kb_chunks",
        chunk_id=chunk,
        document_id="d",
        kb_id=None,
        file_id=None,
        level="global",
        title="T",
        kb_name=None,
        page=1,
        section=None,
        text="t",
        snippet="s",
        score=0.5,
    )


def test_source_book_numbers_are_global_and_stable() -> None:
    book = SourceBook()
    first = book.add([fragment("a"), fragment("b")])
    again = book.add([fragment("b"), fragment("c")])
    assert [f.index for f in first] == [1, 2]
    assert [f.index for f in again] == [2, 3]  # тот же фрагмент — тот же номер
    assert cited_indexes("Срок 10 дней [1], оплата [3]. Массив a[0]") == {1, 3, 0}


def test_scope_filters_are_built_by_server() -> None:
    owner = uuid.uuid4()
    scope = Scope(kb_ids=(uuid.uuid4(),), owner_id=owner, personal_kb_ids=(uuid.uuid4(),))
    collections = [c for c, _ in scope.filters()]
    assert collections == ["kb_chunks", "personal_chunks"]
    personal = scope.filters()[1][1]
    assert any(getattr(cond, "key", None) == "owner_id" for cond in (personal.must or []))
    assert Scope().empty


def test_kb_manager_scope() -> None:
    role_a, role_b = uuid.uuid4(), uuid.uuid4()
    role_kb = KnowledgeBase(level="role")
    global_kb = KnowledgeBase(level="global")
    personal = KnowledgeBase(level="personal")
    assert manageable(role_kb, manage_all=False, own_role_ids={role_a}, kb_role_ids=[role_a])
    assert not manageable(role_kb, manage_all=False, own_role_ids={role_b}, kb_role_ids=[role_a])
    assert not manageable(global_kb, manage_all=False, own_role_ids={role_a}, kb_role_ids=[])
    assert manageable(global_kb, manage_all=True, own_role_ids=set(), kb_role_ids=[])
    assert not manageable(personal, manage_all=True, own_role_ids=set(), kb_role_ids=[])
