"""Авто-поиск по базам знаний перед ответом (режим ``auto``, §8.3) и карточки источников."""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.modules.completions.prompt import (
    Turn,
)
from app.modules.completions.state import (
    Deps,
    GenerationResult,
)
from app.modules.completions.streaming import (
    EventWriter,
)
from app.modules.llm.tokens import TokenCounter
from app.modules.rag.search import Fragment
from app.modules.rag.service import (
    SourceBook,
    fragments_context,
    rewrite_query,
    run_search,
    source_card,
)
from app.modules.rag.service import Turn as RagTurn
from app.modules.tools.base import ToolContext
from app.modules.tools.executor import ToolOutcome

log = structlog.stdlib.get_logger("app.completions")


async def emit_sources(writer: EventWriter, book: SourceBook) -> None:
    # Каждый раз — полный список: клиент заменяет карточки, а не дописывает.
    await writer.emit("sources", {"items": [source_card(f) for f in book.fragments]})


async def auto_rag(
    deps: Deps,
    context: ToolContext,
    writer: EventWriter,
    result: GenerationResult,
    *,
    question: str,
    history: list[Turn],
    budget: int,
    counter: TokenCounter,
) -> tuple[str | None, dict[str, Any]]:
    """Режим ``auto`` (§8.3): переформулировка → гибридный поиск → фрагменты в промпт.

    Для пользователя это шаг «Ищу в базах знаний…» — как вызов инструмента, и в истории тоже.
    """
    started = time.monotonic()
    call_id, tool, label = "rag-auto", "search_knowledge_base", "tools.search_knowledge_base"
    rewritten = await rewrite_query(
        deps.registry, deps.renderer, deps.settings, question,
        [RagTurn(t.role, t.content) for t in history],
    )  # fmt: skip
    params = {"query": rewritten}
    await writer.emit(
        "tool.start", {"call_id": call_id, "tool": tool, "label": label, "params": params}
    )
    status = "ok"
    trace: dict[str, Any] = {"rewritten": rewritten}
    fragments: list[Fragment] = []
    try:
        # BM25 получает и исходный текст: точные коды не потеряются при переформулировке.
        bm25_query = rewritten if rewritten == question else f"{rewritten}\n{question}"
        found = await run_search(
            deps.services.search(), context.kb_scope, query=rewritten, bm25_query=bm25_query,
            user_id=context.user_id, chat_id=context.chat_id, message_id=context.message_id,
        )  # fmt: skip
        fragments = found.fragments
        trace.update(found.trace)
    except Exception as exc:
        log.exception("completions.rag_failed", message_id=str(context.message_id))
        status = "error"
        trace["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    # Бюджет фрагментов (§8.3): лишние — с конца списка, они наименее релевантны.
    kept: list[Fragment] = []
    used = 0
    for fragment in fragments:
        cost = counter.count(fragment.text)
        if kept and used + cost > budget:
            break
        kept.append(fragment)
        used += cost
    numbered = context.sources.add(kept)
    trace["fragments"] = len(numbered)
    trace["tokens"] = used
    knowledge = (
        deps.renderer.render("system/knowledge.md.j2", fragments=fragments_context(numbered))
        if status == "ok"
        else None
    )
    await writer.emit(
        "tool.end",
        {"call_id": call_id, "tool": tool, "label": label, "status": status, "params": params},
    )
    if numbered:
        await emit_sources(writer, context.sources)
    result.tools.append(
        ToolOutcome(
            call_id=call_id, tool=tool, arguments={"query": rewritten, "mode": "auto"},
            content=f"фрагментов: {len(numbered)}", status=status,
            duration_ms=int((time.monotonic() - started) * 1000), visibility="visible",
            label=label, label_params=params, iteration=0,
        )
    )  # fmt: skip
    return knowledge, trace
