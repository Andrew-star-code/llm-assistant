"""Инструменты генерации файлов (§9.2, §9.4). Сами файлы создаёт воркер (pandoc, LibreOffice)."""

from __future__ import annotations

from typing import Any

from app.modules.files.generate import DocumentSpec, PresentationSpec, SpreadsheetSpec
from app.modules.tools.base import Tool, ToolContext, ToolError, ToolResult
from app.modules.tools.registry import register_tool
from app.workers.dispatch import TaskTimeout


async def _generate(ctx: ToolContext, kind: str, args: Any) -> ToolResult:
    spec = {
        "kind": kind,
        "args": args.model_dump(mode="json"),
        "owner_id": str(ctx.user_id),
        "chat_id": str(ctx.chat_id),
        "message_id": str(ctx.message_id),
    }
    try:
        result = await ctx.services.dispatcher.generate(spec)
    except TaskTimeout as exc:
        raise ToolError("создание файла заняло слишком много времени") from exc
    if "error" in result:
        raise ToolError(str(result["error"]))
    size_kb = max(1, int(result["size"]) // 1024)
    return ToolResult(
        f"Файл «{result['filename']}» создан ({size_kb} КБ) и показан пользователю карточкой "
        "с кнопками «Скачать» и «Просмотр». Не вставляй ссылку на файл в ответ.",
        files=[result],
        data={"file_id": result["file_id"]},
    )


@register_tool
class CreateDocument(Tool):
    name = "create_document"
    description = (
        "Создать документ из Markdown: docx (Word, по корпоративному шаблону; формулы LaTeX "
        "в $…$ становятся формулами Word), pdf, odt, md, html, txt. Используй, когда пользователь "
        "просит оформить текст файлом («оформи в Word», «сделай PDF»)."
    )
    args_model = DocumentSpec
    status_label = "tools.create_document"
    timeout_s = 240

    def label_params(self, args: Any) -> dict[str, str]:
        return {"name": f"{args.title}.{args.format}"}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        return await _generate(ctx, "document", args)


@register_tool
class CreateSpreadsheet(Tool):
    name = "create_spreadsheet"
    description = (
        "Создать таблицу XLSX или CSV из описания листов: колонки (заголовок, тип, формат) и "
        "строки. Формулы Excel — строки, начинающиеся с «=». "
        "Используй для «сделай таблицу в Excel»."
    )
    args_model = SpreadsheetSpec
    status_label = "tools.create_spreadsheet"
    timeout_s = 120

    def label_params(self, args: Any) -> dict[str, str]:
        return {"name": f"{args.title}.{args.format}"}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        return await _generate(ctx, "spreadsheet", args)


@register_tool
class CreatePresentation(Tool):
    name = "create_presentation"
    description = (
        "Создать презентацию PPTX по корпоративному шаблону: слайды с заголовком, пунктами "
        "и заметками."
    )
    args_model = PresentationSpec
    status_label = "tools.create_presentation"
    timeout_s = 120

    def label_params(self, args: Any) -> dict[str, str]:
        return {"name": f"{args.title}.pptx"}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        return await _generate(ctx, "presentation", args)
