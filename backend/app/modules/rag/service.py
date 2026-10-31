"""RAG для оркестратора и инструментов: права, переформулировка, поиск, инциденты (§8.3, §10).

Права вычисляются сервером при каждом запросе: общие базы — всем, ролевые — по ролям
пользователя (``kb_roles``), личные — только владельцу. Модель может сузить поиск, но не расширить:
инструменты получают готовый ``Scope``.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.completions.prompt import PromptRenderer
from app.modules.incidents import service as incidents
from app.modules.kb.models import (
    LEVEL_GLOBAL,
    LEVEL_PERSONAL,
    LEVEL_ROLE,
    KbRole,
    KnowledgeBase,
)
from app.modules.llm.registry import ModelRegistry
from app.modules.rag.search import Fragment, Scope, SearchResult, search

log = structlog.stdlib.get_logger("app.rag")
UTILITY_ROLE = "utility"
CITATION = re.compile(r"\[(\d{1,2})\]")


async def accessible_bases(
    db: AsyncSession, user_id: UUID, role_ids: Iterable[UUID]
) -> list[KnowledgeBase]:
    roles = list(role_ids)
    role_kbs = select(KbRole.kb_id).where(KbRole.role_id.in_(roles)) if roles else None
    conditions = [
        KnowledgeBase.level == LEVEL_GLOBAL,
        (KnowledgeBase.level == LEVEL_PERSONAL) & (KnowledgeBase.owner_id == user_id),
    ]
    if role_kbs is not None:
        conditions.append((KnowledgeBase.level == LEVEL_ROLE) & KnowledgeBase.id.in_(role_kbs))
    rows = await db.scalars(
        select(KnowledgeBase).where(KnowledgeBase.deleted_at.is_(None), or_(*conditions))
    )
    return list(rows.all())


async def build_scope(
    db: AsyncSession,
    user_id: UUID,
    role_ids: Iterable[UUID],
    *,
    attachment_ids: Sequence[UUID] = (),
    only_kb_ids: Sequence[UUID] | None = None,
) -> Scope:
    """Область поиска пользователя; ``only_kb_ids`` (сценарий) может её только сузить."""
    bases = await accessible_bases(db, user_id, role_ids)
    if only_kb_ids is not None:
        allowed = set(only_kb_ids)
        bases = [b for b in bases if b.id in allowed or b.level == LEVEL_PERSONAL]
    shared = tuple(b.id for b in bases if b.level != LEVEL_PERSONAL)
    personal = tuple(b.id for b in bases if b.level == LEVEL_PERSONAL)
    return Scope(
        kb_ids=shared,
        owner_id=user_id if personal else None,
        personal_kb_ids=personal,
        attachment_ids=tuple(attachment_ids),
        kb_names={str(b.id): b.name for b in bases},
    )


@dataclass(frozen=True)
class Turn:
    role: str
    text: str


async def rewrite_query(
    registry: ModelRegistry,
    renderer: PromptRenderer,
    settings: Settings,
    question: str,
    history: Sequence[Turn],
) -> str:
    """Самостоятельный поисковый запрос от служебной модели; при сбое — исходный вопрос."""
    if not settings.rag.search.rewrite:
        return question
    try:
        plan = registry.plan(UTILITY_ROLE, thinking=False)
        prompt = renderer.render(
            "utility/rag_query.md.j2",
            message=question[:4000],
            history=[
                {"role": "Пользователь" if t.role == "user" else "Ассистент", "text": t.text[:1000]}
                for t in history[-4:]
            ],
        )
        response = await asyncio.wait_for(
            registry.client(UTILITY_ROLE).chat.completions.create(
                messages=[{"role": "user", "content": prompt}], **{**plan.params, "max_tokens": 128}
            ),
            timeout=settings.rag.search.rewrite_timeout_s,
        )
        rewritten = (response.choices[0].message.content or "").strip().strip("«»\"'")
        return rewritten.splitlines()[0][:1000] if rewritten else question
    except Exception as exc:
        log.warning("rag.rewrite_failed", error=f"{type(exc).__name__}: {exc}"[:200])
        return question


@dataclass(frozen=True)
class SearchContext:
    """Сервисы для поиска с записью инцидентов о пропущенных стадиях."""

    settings: Settings
    registry: ModelRegistry
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis | None


async def run_search(
    ctx: SearchContext,
    scope: Scope,
    *,
    query: str,
    bm25_query: str | None = None,
    user_id: UUID | None = None,
    chat_id: UUID | None = None,
    message_id: UUID | None = None,
    client: AsyncQdrantClient | None = None,
) -> SearchResult:
    from app.modules.rag.store import qdrant_client

    own = client is None
    qdrant = client or qdrant_client(ctx.settings)
    try:
        result = await search(
            qdrant, ctx.registry, ctx.settings.rag.search, query=query, bm25_query=bm25_query,
            scope=scope,
        )  # fmt: skip
    finally:
        if own:
            await qdrant.close()
    for stage in result.degraded:
        # Отказ стадии не ломает ответ, но админ должен узнать (не чаще раза в 10 минут).
        await incidents.report(
            ctx.sessions, type="rag_degraded", severity="warning",
            title=f"Поиск по базам знаний: стадия {stage} пропущена",
            fingerprint=f"rag_degraded:{stage}",
            payload={"stage": stage, "detail": result.trace["stages"].get(stage)},
            user_id=user_id, chat_id=chat_id, message_id=message_id,
            redis=ctx.redis, throttle_s=ctx.settings.rag.search.incident_throttle_s,
        )  # fmt: skip
    return result


def fragments_context(fragments: Sequence[Fragment]) -> list[dict[str, Any]]:
    return [
        {
            "index": f.index,
            "title": f.title,
            "kb_name": f.kb_name,
            "page": f.page,
            "section": f.section,
            "text": f.text,
        }
        for f in fragments
    ]


def source_card(f: Fragment) -> dict[str, Any]:
    """Карточка источника для события ``sources`` и ``message_sources`` (§10.5)."""
    return {
        "index": f.index,
        "kind": f.kind,
        "title": f.title,
        "kb_name": f.kb_name,
        "document_id": f.document_id if f.kind == "kb" else None,
        "file_id": f.file_id,
        "page": f.page,
        "section": f.section,
        "snippet": f.snippet,
        "score": None if f.score is None else round(f.score, 4),
    }


def cited_indexes(text: str) -> set[int]:
    return {int(m) for m in CITATION.findall(text)}


class SourceBook:
    """Сквозная нумерация источников ответа: авто-RAG и инструменты пишут сюда же.

    Один и тот же фрагмент получает один номер, сколько бы раз его ни нашли.
    """

    def __init__(self) -> None:
        self.fragments: list[Fragment] = []
        self._by_chunk: dict[str, Fragment] = {}

    def add(self, fragments: Sequence[Fragment]) -> list[Fragment]:
        from dataclasses import replace

        numbered = []
        for f in fragments:
            known = self._by_chunk.get(f.chunk_id)
            if known is None:
                known = replace(f, index=len(self.fragments) + 1)
                self.fragments.append(known)
                self._by_chunk[f.chunk_id] = known
            numbered.append(known)
        return numbered
