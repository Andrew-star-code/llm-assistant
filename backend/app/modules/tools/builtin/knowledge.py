"""Поиск по базам знаний (§9.2, §10.4) — тот же конвейер, что в режиме ``auto``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, Field

from app.modules.rag.search import Fragment
from app.modules.rag.service import fragments_context, run_search, source_card
from app.modules.tools.base import Tool, ToolContext, ToolError, ToolResult
from app.modules.tools.registry import register_tool


def render_fragments(ctx: ToolContext, fragments: Sequence[Fragment]) -> ToolResult:
    """Фрагменты с номерами для цитат — сквозными для всего ответа (``ctx.sources``)."""
    numbered = ctx.sources.add(fragments)
    parts = []
    for f in fragments_context(numbered):
        where = ", ".join(
            x for x in (f["kb_name"], f"стр. {f['page']}" if f["page"] else None) if x
        )
        parts.append(f"[{f['index']}] «{f['title']}»{f' ({where})' if where else ''}\n{f['text']}")
    text = "\n\n".join(parts) + "\n\nСсылайся на фрагменты номерами в квадратных скобках: [1], [2]."
    return ToolResult(text, sources=[source_card(f) for f in numbered])


class SearchKbArgs(BaseModel):
    query: str = Field(
        min_length=2,
        description="Поисковый запрос: суть вопроса; номера, коды, ФИО и термины — дословно.",
    )
    knowledge_base: str | None = Field(
        None, description="Искать только в этой базе (название из списка доступных)."
    )


@register_tool
class SearchKnowledgeBase(Tool):
    name = "search_knowledge_base"
    description = (
        "Поиск по базам знаний компании (регламенты, шаблоны, личные документы пользователя). "
        "Используй, когда нужных сведений нет в уже найденных фрагментах или нужно уточнить. "
        "Возвращает фрагменты с номерами для ссылок [n]."
    )
    args_model = SearchKbArgs
    status_label = "tools.search_knowledge_base"
    timeout_s = 30
    needs_knowledge = True

    def label_params(self, args: Any) -> dict[str, str]:
        return {"query": args.query}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        scope = replace(ctx.kb_scope, attachment_ids=())
        if args.knowledge_base:
            wanted = args.knowledge_base.strip().casefold()
            ids = {k for k, name in scope.kb_names.items() if name.casefold() == wanted}
            if not ids:
                names = ", ".join(f"«{n}»" for n in scope.kb_names.values()) or "нет"
                raise ToolError(f"базы «{args.knowledge_base}» нет среди доступных: {names}")
            # Модель может только сузить область, но не расширить (§10.1).
            scope = replace(
                scope,
                kb_ids=tuple(k for k in scope.kb_ids if str(k) in ids),
                personal_kb_ids=tuple(k for k in scope.personal_kb_ids if str(k) in ids),
            )
        if scope.empty:
            return ToolResult("У пользователя нет доступных баз знаний.")
        result = await run_search(
            ctx.services.search(), scope, query=args.query, user_id=ctx.user_id,
            chat_id=ctx.chat_id, message_id=ctx.message_id,
        )  # fmt: skip
        if not result.fragments:
            return ToolResult(
                "В доступных базах знаний ничего не найдено.", data={"trace": result.trace}
            )
        rendered = render_fragments(ctx, result.fragments)
        rendered.data = {"trace": result.trace}
        return rendered
