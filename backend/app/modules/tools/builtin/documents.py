"""Инструменты чтения вложений чата (§9.2, §9.3)."""

from __future__ import annotations

import csv
import io
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.ingestion import index
from app.modules.ingestion.parsers import decode_text, markdown_table, split_pages
from app.modules.tools.base import NoArgs, Tool, ToolContext, ToolError, ToolFile, ToolResult
from app.modules.tools.registry import register_tool

MAX_PAGES_PER_CALL = 30
FILE_HINT = "Имя файла из списка вложений (или его id)."


def resolve_file(ctx: ToolContext, reference: str) -> ToolFile:
    """Файл чата по имени или id. Только вложения текущего чата — список строит сервер."""
    ref = reference.strip()
    files = ctx.attachments
    for file in files:
        if str(file.id) == ref or file.filename == ref:
            return file
    lowered = [f for f in files if f.filename.casefold() == ref.casefold()]
    if len(lowered) == 1:
        return lowered[0]
    partial = [f for f in files if ref.casefold() in f.filename.casefold()]
    if len(partial) == 1:
        return partial[0]
    names = ", ".join(f"«{f.filename}»" for f in files) or "нет"
    raise ToolError(f"файл «{reference}» не найден среди вложений. Доступны: {names}")


async def read_pages(ctx: ToolContext, file: ToolFile) -> list[str]:
    if not file.text_key:
        raise ToolError(f"текст файла «{file.filename}» недоступен")
    data = await ctx.services.storage.get(file.text_key)
    if data is None:
        raise ToolError(f"текст файла «{file.filename}» недоступен")
    return split_pages(data.decode("utf-8"))


class FileArg(BaseModel):
    file: str = Field(description=FILE_HINT)


@register_tool
class ListAttachments(Tool):
    name = "list_attachments"
    description = "Список файлов, приложенных к чату: имя, тип, размер, число страниц."
    args_model = NoArgs
    status_label = "tools.list_attachments"
    timeout_s = 10
    needs_attachments = True

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        lines = [
            f"- «{f.filename}» ({f.file_type}, {f.size // 1024} КБ, страниц: {f.pages or '—'})"
            for f in ctx.attachments
        ]
        return ToolResult("\n".join(lines) or "Вложений нет.")


class ReadDocumentArgs(FileArg):
    page_from: int = Field(1, ge=1, description="С какой страницы читать.")
    page_to: int | None = Field(None, ge=1, description="По какую страницу; по умолчанию +10.")


@register_tool
class ReadDocument(Tool):
    name = "read_document"
    description = (
        "Текст вложения по страницам. Используй, когда в контексте только оглавление большого "
        "документа или нужно перечитать конкретные страницы. Не больше 30 страниц за вызов."
    )
    args_model = ReadDocumentArgs
    status_label = "tools.read_document"
    timeout_s = 30
    needs_attachments = True

    def label_params(self, args: Any) -> dict[str, str]:
        return {"name": args.file}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        file = resolve_file(ctx, args.file)
        pages = await read_pages(ctx, file)
        start = min(args.page_from, len(pages))
        end = min(args.page_to or start + 9, len(pages), start + MAX_PAGES_PER_CALL - 1)
        parts = [f"<!-- page: {n} -->\n{pages[n - 1]}" for n in range(start, end + 1)]
        tail = f"\n\n[Страницы {start}–{end} из {len(pages)}.]"
        return ToolResult(
            "\n\n".join(parts) + tail, data={"file": file.filename, "pages": [start, end]}
        )


@register_tool
class GetDocumentOutline(Tool):
    name = "get_document_outline"
    description = (
        "Оглавление вложения: заголовки с номерами страниц, таблицы, листы, число страниц."
    )
    args_model = FileArg
    status_label = "tools.get_document_outline"
    timeout_s = 10
    needs_attachments = True

    def label_params(self, args: Any) -> dict[str, str]:
        return {"name": args.file}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        file = resolve_file(ctx, args.file)
        return ToolResult(outline_text(file))


def outline_text(file: ToolFile) -> str:
    outline = file.outline or {}
    lines = [f"Файл «{file.filename}»: страниц — {file.pages or '—'}."]
    if outline.get("virtual_pages"):
        lines.append("Страницы условные (~3000 символов), разметки страниц в файле нет.")
    for heading in outline.get("headings", [])[:200]:
        indent = "  " * (int(heading.get("level", 1)) - 1)
        lines.append(f"{indent}- {heading.get('text')} (стр. {heading.get('page', '?')})")
    for sheet in outline.get("sheets", []):
        lines.append(
            f"Лист «{sheet['name']}»: {sheet['rows']}×{sheet['cols']} ({sheet['dimensions']})"
        )
    for table in outline.get("tables", [])[:100]:
        lines.append(
            f"Таблица {table['index']}: стр. {table['page']}, {table['rows']}×{table['cols']}"
        )
    return "\n".join(lines)


class ReadSpreadsheetArgs(FileArg):
    sheet: str | None = Field(None, description="Имя листа; по умолчанию первый.")
    range: str | None = Field(
        None, description="Диапазон, например «A1:F50»; по умолчанию первые 200 строк."
    )
    format: Literal["markdown", "csv"] = "markdown"


@register_tool
class ReadSpreadsheet(Tool):
    name = "read_spreadsheet"
    description = "Лист и диапазон таблицы (XLSX, CSV) как Markdown или CSV — для больших таблиц."
    args_model = ReadSpreadsheetArgs
    status_label = "tools.read_spreadsheet"
    timeout_s = 30
    needs_attachments = True

    def label_params(self, args: Any) -> dict[str, str]:
        return {"name": args.file}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        file = resolve_file(ctx, args.file)
        data = await ctx.services.storage.get(file.storage_key)
        if data is None:
            raise ToolError("файл недоступен")
        if file.file_type in {"csv", "tsv"}:
            text = decode_text(data)
            rows = list(
                csv.reader(io.StringIO(text), delimiter="\t" if file.file_type == "tsv" else ",")
            )
            rows = rows[:201]
        elif file.file_type == "xlsx":
            rows = _xlsx_rows(data, args.sheet, args.range)
        else:
            raise ToolError("это не таблица XLSX или CSV — используй read_document")
        if args.format == "csv":
            buffer = io.StringIO()
            csv.writer(buffer).writerows(rows)
            return ToolResult(buffer.getvalue())
        return ToolResult(markdown_table([[str(c) for c in r] for r in rows], max_rows=1000))


def _xlsx_rows(data: bytes, sheet_name: str | None, cell_range: str | None) -> list[list[Any]]:
    import openpyxl

    sheet: Any
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if sheet_name:
            if sheet_name not in workbook.sheetnames:
                raise ToolError(
                    f"листа «{sheet_name}» нет. Листы: {', '.join(workbook.sheetnames)}"
                )
            sheet = workbook[sheet_name]
        else:
            sheet = workbook.worksheets[0]
        if cell_range:
            try:
                cells = sheet[cell_range]
            except (ValueError, KeyError) as exc:
                raise ToolError(f"некорректный диапазон «{cell_range}»") from exc
            rows = [[c.value if c.value is not None else "" for c in row] for row in cells]
        else:
            rows = [
                [v if v is not None else "" for v in row]
                for row in sheet.iter_rows(max_row=200, values_only=True)
            ]
        return rows[:1000]
    finally:
        workbook.close()


class SearchArgs(BaseModel):
    query: str = Field(min_length=2, description="Что искать: вопрос или ключевые слова.")
    file: str | None = Field(None, description="Искать только в этом файле. " + FILE_HINT)


@register_tool
class SearchInDocuments(Tool):
    name = "search_in_documents"
    description = (
        "Смысловой поиск по вложениям чата: возвращает подходящие фрагменты с номерами страниц. "
        "Используй для больших документов, чтобы найти нужное место, затем при необходимости — "
        "read_document."
    )
    args_model = SearchArgs
    status_label = "tools.search_in_documents"
    timeout_s = 30
    needs_attachments = True

    def label_params(self, args: Any) -> dict[str, str]:
        return {"query": args.query}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        files = [resolve_file(ctx, args.file)] if args.file else list(ctx.attachments)
        names = {str(f.id): f.filename for f in files}
        client = index.qdrant_client(ctx.services.settings)
        try:
            hits = await index.search(
                client, ctx.services.models, query=args.query, file_ids=[f.id for f in files]
            )
        finally:
            await client.close()
        if not hits:
            return ToolResult("Ничего не найдено во вложениях.")
        parts = [
            f"[{i}] «{names.get(h.file_id, '?')}», стр. {h.page}:\n{h.text}"
            for i, h in enumerate(hits, start=1)
        ]
        return ToolResult("\n\n".join(parts), data={"hits": len(hits)})
