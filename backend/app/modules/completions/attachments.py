"""Вложения в промпте (§8.1 п. 6, §9.3).

Если текст всех вложений чата меньше ``files.full_text_budget_share`` бюджета контекста, он целиком
идёт в системный промпт. Иначе — оглавление и начало каждого документа, а модель дочитывает
инструментами ``read_document``, ``search_in_documents``, ``read_spreadsheet``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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
    return AttachmentsBlock(text, mode, files, counter.count(text))
