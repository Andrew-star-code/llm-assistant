"""Чанкинг по структуре документа (§10.3).

Вход — страницы Markdown (маркеры `<!-- page: N -->` уже сняты, см. ``split_pages``). Документ
режется по заголовкам, затем раздел — рекурсивно до ``max_tokens`` (абзацы → строки → предложения
→ отрезки) с перекрытием ``overlap``. Таблицы и блоки кода не режутся, если влезают в потолок;
большая таблица режется по строкам с повтором шапки. Мелкие соседние разделы склеиваются, пока
чанк меньше ``min_tokens``. К тексту чанка спереди добавляются строки «Документ: …» и «Раздел: …»,
чтобы фрагмент был понятен без соседей (и для эмбеддингов, и для BM25).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from app.core.config import ChunkingSettings

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SENTENCE_END = re.compile(r"(?<=[.!?…;])\s+")


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str  # с префиксом «Документ / Раздел» — то, что индексируется
    body: str  # сам фрагмент — для цитаты и сниппета
    page_from: int
    page_to: int
    section_path: tuple[str, ...]
    # Где в ``body`` какая страница: (страница, начало, конец) — для «открыть на странице».
    page_spans: tuple[tuple[int, int, int], ...] = ()


@dataclass
class _Block:
    text: str
    page: int
    section: tuple[str, ...]
    kind: str = "text"  # text | table | code | heading


@dataclass
class _Draft:
    blocks: list[_Block] = field(default_factory=list)
    tokens: int = 0


def _blocks(pages: Sequence[str]) -> Iterator[_Block]:
    """Абзацы, таблицы, блоки кода и заголовки с номером страницы и путём раздела."""
    path: list[tuple[int, str]] = []
    for page_number, page in enumerate(pages, start=1):
        lines = page.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            heading = HEADING.match(line)
            if heading:
                level = len(heading.group(1))
                path = [(lvl, t) for lvl, t in path if lvl < level] + [
                    (level, heading.group(2).strip())
                ]
                yield _Block(line.strip(), page_number, tuple(t for _, t in path), "heading")
                i += 1
                continue
            section = tuple(t for _, t in path)
            if line.lstrip().startswith("```"):
                end = i + 1
                while end < len(lines) and not lines[end].lstrip().startswith("```"):
                    end += 1
                yield _Block("\n".join(lines[i : end + 1]), page_number, section, "code")
                i = end + 1
                continue
            if line.lstrip().startswith("|"):
                end = i
                while end < len(lines) and lines[end].lstrip().startswith("|"):
                    end += 1
                yield _Block("\n".join(lines[i:end]), page_number, section, "table")
                i = end
                continue
            end = i
            while (
                end < len(lines)
                and lines[end].strip()
                and not HEADING.match(lines[end])
                and not lines[end].lstrip().startswith(("|", "```"))
            ):
                end += 1
            yield _Block("\n".join(lines[i:end]), page_number, section, "text")
            i = end


def _split_text(text: str, limit: int, count: Callable[[str], int]) -> list[str]:
    """Рекурсивно: строки → предложения → слова, пока куски не станут не больше ``limit``."""
    if count(text) <= limit:
        return [text]
    for pattern in ("\n", SENTENCE_END, " "):
        parts = text.split(pattern) if isinstance(pattern, str) else pattern.split(text)
        if len(parts) > 1:
            joiner = pattern if isinstance(pattern, str) else " "
            pieces: list[str] = []
            current = ""
            for part in parts:
                candidate = f"{current}{joiner}{part}" if current else part
                if current and count(candidate) > limit:
                    pieces.append(current)
                    current = part
                else:
                    current = candidate
            if current:
                pieces.append(current)
            return [p for piece in pieces for p in _split_text(piece, limit, count)]
    # Одно «слово» длиннее лимита (base64, длинный идентификатор) — режем по символам.
    size = max(1, len(text) * limit // max(count(text), 1))
    return [text[i : i + size] for i in range(0, len(text), size)]


def _split_table(block: _Block, limit: int, count: Callable[[str], int]) -> list[_Block]:
    rows = block.text.splitlines()
    head, body = rows[:2], rows[2:]
    parts: list[_Block] = []
    current = list(head)
    for row in body:
        if len(current) > len(head) and count("\n".join([*current, row])) > limit:
            parts.append(_Block("\n".join(current), block.page, block.section, "table"))
            current = list(head)
        current.append(row)
    parts.append(_Block("\n".join(current), block.page, block.section, "table"))
    return parts


def chunk_pages(
    pages: Sequence[str],
    *,
    title: str,
    settings: ChunkingSettings,
    count: Callable[[str], int],
) -> list[Chunk]:
    # Запас под строки «Документ / Раздел», чтобы весь чанк укладывался в потолок.
    limit = max(settings.max_tokens - 48, settings.min_tokens)
    # Мелкие куски (большие таблицы, длинные абзацы) готовим заранее.
    units: list[_Block] = []
    for block in _blocks(pages):
        if count(block.text) <= limit:
            units.append(block)
        elif block.kind == "table":
            units.extend(_split_table(block, limit, count))
        else:
            units.extend(
                _Block(t, block.page, block.section, block.kind)
                for t in _split_text(block.text, settings.target_tokens, count)
            )

    overlap_tokens = int(settings.target_tokens * settings.overlap)
    drafts: list[_Draft] = []
    draft = _Draft()

    def flush(carry: bool) -> None:
        nonlocal draft
        if not draft.blocks or all(b.kind == "heading" for b in draft.blocks):
            return
        drafts.append(draft)
        tail: list[_Block] = []
        if carry and overlap_tokens:
            used = 0
            for block in reversed(draft.blocks):
                size = count(block.text)
                if block.kind == "heading" or used + size > overlap_tokens:
                    break
                tail.insert(0, block)
                used += size
        draft = _Draft(tail, sum(count(b.text) for b in tail))

    for unit in units:
        size = count(unit.text)
        if unit.kind == "heading":
            # Новый раздел — новый чанк, если текущий уже не мелкий; перекрытие — внутри раздела.
            if draft.tokens >= settings.min_tokens:
                flush(carry=False)
                draft = _Draft()
        elif (
            draft.tokens > 0
            and draft.tokens + size > settings.target_tokens
            and (draft.tokens + size > limit or draft.tokens >= settings.min_tokens)
        ):
            flush(carry=True)
        draft.blocks.append(unit)
        draft.tokens += size
    flush(carry=False)

    chunks: list[Chunk] = []
    for draft in drafts:
        content = [b for b in draft.blocks if b.kind != "heading"] or draft.blocks
        section = next((b.section for b in content if b.section), ())
        spans: list[tuple[int, int, int]] = []
        offset = 0
        for block in draft.blocks:
            end = offset + len(block.text)
            if spans and spans[-1][0] == block.page:
                spans[-1] = (block.page, spans[-1][1], end)
            else:
                spans.append((block.page, offset, end))
            offset = end + 2
        body = "\n\n".join(b.text for b in draft.blocks)
        header = [f"Документ: {title}"]
        if section:
            header.append(f"Раздел: {' / '.join(section)}")
        chunks.append(
            Chunk(
                index=len(chunks),
                text="\n".join(header) + "\n\n" + body,
                body=body,
                page_from=min(b.page for b in draft.blocks),
                page_to=max(b.page for b in draft.blocks),
                section_path=section,
                page_spans=tuple(spans),
            )
        )
    return chunks
