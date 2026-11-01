"""Фреймворк инструментов (§9.1, §8.4): реестр, исполнение, инструменты чтения вложений."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, Field

from app.core.storage import LocalStorage
from app.modules.tools.base import Services, Tool, ToolContext, ToolError, ToolFile, ToolResult
from app.modules.tools.executor import execute, truncate
from app.modules.tools.registry import all_tools, available_tools, get_tool

STAGE3_TOOLS = {
    "list_attachments",
    "read_document",
    "get_document_outline",
    "read_spreadsheet",
    "search_in_documents",
    "create_document",
    "create_spreadsheet",
    "create_presentation",
}


class EchoArgs(BaseModel):
    text: str = Field(min_length=1)
    delay: float = 0.0
    fail: bool = False
    crash: bool = False


class Echo(Tool):
    """Тестовый инструмент: не регистрируется глобально, подставляется в реестр на время теста."""

    name = "echo_test"
    description = "Повторяет текст."
    args_model = EchoArgs
    status_label = "tools.echo"
    timeout_s = 1

    def label_params(self, args: Any) -> dict[str, str]:
        return {"text": args.text}

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        await asyncio.sleep(args.delay)
        if args.fail:
            raise ToolError("ожидаемая ошибка")
        if args.crash:
            raise RuntimeError("секретная деталь")
        return ToolResult(args.text * 3, data={"n": 3})


@pytest.fixture
def echo(monkeypatch: pytest.MonkeyPatch) -> Echo:
    from app.modules.tools import registry

    all_tools()
    tool = Echo()
    monkeypatch.setitem(registry._REGISTRY, tool.name, tool)
    return tool


def _ctx(storage: LocalStorage | None = None, files: tuple[ToolFile, ...] = ()) -> ToolContext:
    services = cast(
        Services,
        type("S", (), {"storage": storage, "settings": None, "sessions": None, "models": None}),
    )
    return ToolContext(
        user_id=uuid.uuid4(),
        permissions=frozenset(),
        chat_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        attachments=files,
        services=services,
    )


def test_registry_has_stage3_tools_with_valid_schemas() -> None:
    tools = all_tools()
    assert set(tools) >= STAGE3_TOOLS
    for tool in tools.values():
        schema = tool.schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == tool.name
        assert schema["function"]["parameters"]["type"] == "object"
        assert tool.status_label.startswith("tools.")
        assert tool.description


def test_available_tools_filters() -> None:
    names = {
        t.name
        for t in available_tools(
            enabled=None, scenario=None, permissions=frozenset(), has_attachments=False
        )
    }
    # Без вложений инструменты чтения не предлагаются — модель не будет звать их впустую.
    assert "read_document" not in names and "create_spreadsheet" in names
    with_files = available_tools(
        enabled=["read_document", "create_document"],
        scenario=["read_document"],
        permissions=frozenset(),
        has_attachments=True,
    )
    assert [t.name for t in with_files] == ["read_document"]


def test_available_tools_respects_permissions(echo: Echo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Echo, "required_permissions", frozenset({"data.query"}))
    kwargs: dict[str, Any] = {"enabled": None, "scenario": None, "has_attachments": False}
    assert echo not in available_tools(permissions=frozenset(), **kwargs)
    assert echo in available_tools(permissions=frozenset({"data.query"}), **kwargs)


async def test_execute_ok_and_label(echo: Echo) -> None:
    outcome = await execute(
        _ctx(),
        call_id="c1",
        name="echo_test",
        raw_arguments='{"text": "ab"}',
        allowed={"echo_test"},
        limit=100,
    )
    assert outcome.status == "ok" and outcome.content == "ababab"
    assert outcome.label == "tools.echo" and outcome.label_params == {"text": "ab"}
    assert outcome.arguments == {"text": "ab"} and outcome.data == {"n": 3}


@pytest.mark.parametrize(
    ("name", "arguments", "allowed", "status", "fragment"),
    [
        ("echo_test", "{}", {"echo_test"}, "error", "Ошибка аргументов"),
        ("echo_test", "{not json", {"echo_test"}, "error", "Ошибка аргументов"),
        ("echo_test", "[1]", {"echo_test"}, "error", "объектом JSON"),
        ("echo_test", '{"text": "x"}', set(), "error", "недоступен"),
        ("no_such_tool", "{}", {"no_such_tool"}, "error", "недоступен"),
        ("echo_test", '{"text": "x", "fail": true}', {"echo_test"}, "error", "ожидаемая ошибка"),
        ("echo_test", '{"text": "x", "delay": 3}', {"echo_test"}, "timeout", "не уложился"),
    ],
)
async def test_execute_errors_go_back_to_model(
    echo: Echo, name: str, arguments: str, allowed: set[str], status: str, fragment: str
) -> None:
    outcome = await execute(
        _ctx(), call_id="c", name=name, raw_arguments=arguments, allowed=allowed, limit=1000
    )
    assert outcome.status == status
    assert fragment in outcome.content


async def test_unexpected_exception_hides_details(echo: Echo) -> None:
    outcome = await execute(
        _ctx(),
        call_id="c",
        name="echo_test",
        raw_arguments='{"text": "x", "crash": true}',
        allowed={"echo_test"},
        limit=1000,
    )
    assert outcome.status == "error"
    assert "RuntimeError" in outcome.content and "секретная" not in outcome.content


async def test_result_is_truncated(echo: Echo) -> None:
    outcome = await execute(
        _ctx(),
        call_id="c",
        name="echo_test",
        raw_arguments='{"text": "' + "x" * 50 + '"}',
        allowed={"echo_test"},
        limit=40,
    )
    assert outcome.content.startswith("x" * 40)
    assert "обрезан" in outcome.content
    assert truncate("короткий", 100) == "короткий"


# ------------------------------------------------------------------ инструменты чтения


async def _file(storage: LocalStorage, name: str, pages: list[str]) -> ToolFile:
    file_id = uuid.uuid4()
    text = "\n\n".join(f"<!-- page: {i} -->\n{p}" for i, p in enumerate(pages, start=1))
    await storage.put(f"texts/{file_id}", text.encode())
    return ToolFile(
        id=file_id,
        filename=name,
        file_type="docx",
        size=2048,
        pages=len(pages),
        text_key=f"texts/{file_id}",
        storage_key=f"uploads/{file_id}",
        outline={
            "headings": [{"level": 1, "text": "Введение", "page": 1}],
            "tables": [],
            "sheets": [],
            "warnings": [],
        },
    )


async def _run(ctx: ToolContext, name: str, args: dict[str, Any]) -> str:
    tool = get_tool(name)
    assert tool is not None
    result = await tool.run(ctx, tool.args_model.model_validate(args))
    return result.content


async def test_read_document_pages_and_file_resolution(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    report = await _file(storage, "Отчёт за год.docx", [f"Страница {i}" for i in range(1, 41)])
    other = await _file(storage, "Приказ.docx", ["Текст приказа"])
    ctx = _ctx(storage, (report, other))

    text = await _run(ctx, "read_document", {"file": "отчёт", "page_from": 25, "page_to": 26})
    assert "Страница 25" in text and "Страница 26" in text and "Страница 27" not in text
    assert "[Страницы 25–26 из 40.]" in text
    # Не больше 30 страниц за вызов; по id тоже находит.
    text = await _run(ctx, "read_document", {"file": str(report.id), "page_to": 40})
    assert "[Страницы 1–30 из 40.]" in text

    listing = await _run(ctx, "list_attachments", {})
    assert "«Отчёт за год.docx»" in listing and "«Приказ.docx»" in listing
    outline = await _run(ctx, "get_document_outline", {"file": "Приказ.docx"})
    assert "Введение" in outline


async def test_foreign_file_reference_is_rejected(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    mine = await _file(storage, "Мой.docx", ["x"])
    ctx = _ctx(storage, (mine,))
    with pytest.raises(ToolError, match="не найден среди вложений"):
        await _run(ctx, "read_document", {"file": str(uuid.uuid4())})
    with pytest.raises(ToolError):
        await _run(ctx, "read_document", {"file": "../../etc/passwd"})
