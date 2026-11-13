"""Вложения в промпте (§8.1 п. 6, §9.3).

Если текст всех вложений чата меньше ``files.full_text_budget_share`` бюджета контекста, он целиком
идёт в системный промпт. Иначе — оглавление и начало каждого документа, а модель дочитывает
инструментами ``read_document``, ``search_in_documents``, ``read_spreadsheet``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import ModelEndpoint, Settings
from app.core.storage import Storage
from app.modules.completions.prompt import DEFAULT_CONTEXT, DEFAULT_RESERVE, PromptRenderer
from app.modules.files.models import File
from app.modules.ingestion.parsers import PAGE_SPLIT
from app.modules.llm.tokens import CHARS_PER_TOKEN, TokenCounter
from app.modules.tools.base import ToolFile
from app.modules.tools.builtin.documents import outline_text


@dataclass(frozen=True)
class AttachmentsBlock:
    text: str | None
    mode: str  # none | full | outline
    files: tuple[ToolFile, ...]
    tokens: int
    # Данные шаблона — чтобы ужать блок под остаток контекста без повторного чтения файлов.
    items: tuple[dict[str, Any], ...] = ()
    shrunk: bool = False


def tool_file(row: File) -> ToolFile:
    return ToolFile(
        id=row.id,
        filename=row.filename,
        file_type=row.file_type,
        size=row.size,
        pages=row.pages,
        text_key=row.text_key,
        storage_key=row.storage_key,
        outline=row.outline,
    )


def _plain(markdown: str) -> str:
    """Маркеры страниц остаются: по ним модель ссылается на страницы («стр. 12»)."""
    return PAGE_SPLIT.sub(lambda m: f"[стр. {m.group(1)}]", markdown).strip()


async def build_attachments(
    rows: Sequence[File],
    *,
    storage: Storage,
    renderer: PromptRenderer,
    settings: Settings,
    endpoint: ModelEndpoint,
    counter: TokenCounter,
) -> AttachmentsBlock:
    ready = [r for r in rows if r.kind == "upload" and r.parse_status == "ready" and r.text_key]
    files = tuple(tool_file(r) for r in ready)
    if not ready:
        return AttachmentsBlock(None, "none", files, 0)

    texts: dict[str, str] = {}
    for row in ready:
        data = await storage.get(row.text_key or "")
        texts[str(row.id)] = _plain(data.decode("utf-8")) if data else ""

    budget = (endpoint.context_length or DEFAULT_CONTEXT) - (
        endpoint.max_output_tokens or DEFAULT_RESERVE
    )
    limit = int(budget * settings.files.full_text_budget_share)
    total_chars = sum(len(t) for t in texts.values())
    # Точный подсчёт — только если текст в принципе может поместиться
    # (миллионы символов не считаем).
    full = (
        total_chars <= limit * CHARS_PER_TOKEN * 2
        and counter.count("".join(texts.values())) <= limit
    )
    mode = "full" if full else "outline"
    preview_chars = settings.files.outline_preview_chars
    context = [
        {
            "name": f.filename,
            "type": f.file_type,
            "pages": f.pages or "—",
            "text": texts[str(f.id)],
            "outline": outline_text(f),
            "preview": texts[str(f.id)][:preview_chars],
        }
        for f in files
    ]
    text = renderer.render("system/attachments.md.j2", files=context, mode=mode)
    return AttachmentsBlock(text, mode, files, counter.count(text), items=tuple(context))


def fit_attachments(
    block: AttachmentsBlock, *, limit: int, renderer: PromptRenderer, counter: TokenCounter
) -> AttachmentsBlock:
    """Ужимает блок вложений до ``limit`` токенов (§8.3): модель с малым контекстом должна
    ответить, а не отказать из-за размера оглавления.

    Ступени — от щадящей к крайней: оглавление и начало вместо полного текста, затем короче
    начало, короче оглавление, в конце — только имена файлов. Полный текст модель дочитывает
    инструментами. Не помещается и последняя ступень — возвращается она: отказ — дело вызывающего.
    """
    if not block.items or block.tokens <= limit:
        return block
    preview = max((len(i["preview"]) for i in block.items), default=0)
    steps = [(preview, 200), (preview // 2, 200), (preview // 4, 100), (1000, 50), (0, 20), (0, 1)]
    if block.mode == "outline":
        steps = steps[1:]  # первая ступень — то, что уже есть
    best = block
    for chars, lines in steps:
        items = [
            {
                **item,
                "preview": item["text"][: min(chars, preview)],
                "outline": "\n".join(item["outline"].splitlines()[:lines]),
            }
            for item in block.items
        ]
        text = renderer.render("system/attachments.md.j2", files=items, mode="outline")
        best = replace(block, text=text, mode="outline", tokens=counter.count(text), shrunk=True)
        if best.tokens <= limit:
            break
    return best
