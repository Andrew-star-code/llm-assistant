"""Файлы и инструменты (этап 3): загрузка с проверками, разбор, вложения в промпте, цикл
инструментов, генерация файлов, скачивание, превью, IDOR. Воркер — в режиме eager.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.chats.models import Message
from app.modules.files.models import File
from app.modules.incidents.models import Incident
from app.modules.ingestion.convert import soffice_binary, tesseract_available
from app.modules.ingestion.parsers import ParsedDocument
from app.modules.tools.models import ToolCall
from app.workers import jobs
from tests import samples
from tests.integration.conftest import (
    ApiClient,
    Infra,
    SseEvent,
    chat_settings,
    new_chat,
    read_stream,
    send,
)

CONTEXT = 12_000
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _client(
    make_client: Any,
    infra: Infra,
    tmp_path: Path,
    url: str,
    *,
    login: str = "petrov",
    **overrides: Any,
) -> tuple[Any, ApiClient]:
    app, client = await make_client(chat_settings(infra, tmp_path, url, **overrides))
    await client.login(login)
    return app, client


async def upload(
    client: ApiClient, name: str, data: bytes, mime: str = "application/octet-stream"
) -> Any:
    return await client.post("/api/files", files={"file": (name, data, mime)})


async def upload_ready(client: ApiClient, name: str, data: bytes) -> dict[str, Any]:
    response = await upload(client, name, data)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    # Воркер в режиме eager: к ответу разбор уже завершён.
    assert body["parse_status"] == "ready", body
    return body


def text_of(events: list[SseEvent]) -> str:
    return "".join(e.data["text"] for e in events if e.event == "content.delta")


async def ask(client: ApiClient, chat_id: str, text: str, **body: Any) -> list[SseEvent]:
    sent = await send(client, chat_id, text, **body)
    return await read_stream(client, sent["assistant_message"]["id"])


# ------------------------------------------------------------------ загрузка и проверки


async def test_upload_validation_errors_and_service_keeps_working(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url, files={"max_file_mb": 1})
    cases = [
        ("program.exe", b"MZ\x90\x00" * 10, 415, "unsupported"),
        ("report.pdf", b"MZ\x90\x00 not a pdf", 415, "type_mismatch"),
        ("empty.txt", b"", 422, "empty"),
        ("bomb.docx", samples.zip_bomb_docx(400), 422, "zip_bomb"),
        ("big.txt", b"a" * (1024 * 1024 + 1), 413, "too_large"),
    ]
    for name, data, status, code in cases:
        response = await upload(client, name, data)
        assert response.status_code == status, (name, response.text)
        error = response.json()["error"]
        assert error["code"] == code and error["message"], name

    # Сервис после всех отказов работает: обычная загрузка и ответ.
    ok = await upload_ready(client, "notes.md", "# Заметки\n\nВсё хорошо.".encode())
    assert ok["file_type"] == "md" and ok["pages"] == 1
    chat_id = await new_chat(client)
    events = await ask(client, chat_id, "Привет")
    assert events[-1].data["status"] == "completed"


async def test_limits_endpoint(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    limits = (await client.get("/api/files/limits")).json()
    assert limits["max_file_mb"] == 50 and limits["max_files_per_message"] == 10
    assert {"docx", "pdf", "xlsx", "csv", "py"} <= set(limits["accept"])


async def test_broken_document_gets_parse_error(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    response = await upload(client, "broken.pdf", b"%PDF-1.7\nnot really a pdf")
    assert response.status_code == 201
    body = response.json()
    assert body["parse_status"] == "error" and "PDF" in body["parse_error"]
    # Непрочитанный файл к сообщению не прикладывается.
    chat_id = await new_chat(client)
    sent = await client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "Что в файле?", "attachment_ids": [body["id"]]},
    )
    assert sent.status_code == 400 and sent.json()["error"]["code"] == "file_not_ready"


async def test_worker_crash_marks_attachment_failed_and_requeue_on_start(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, monkeypatch: Any
) -> None:
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)

    # Сбой вне разбора (запись результата): вложение — «ошибка», а не вечное «читаю…».
    def broken_outline(self: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(ParsedDocument, "outline", broken_outline)
    response = await upload(client, "notes.md", "# Заметки\n\nТекст.".encode())
    assert response.status_code == 201
    body = response.json()
    assert body["parse_status"] == "error" and "RuntimeError" in body["parse_error"], body
    async with app.state.db_sessions() as db:
        incident = await db.scalar(
            select(Incident)
            .where(Incident.type == "worker_failed")
            .order_by(Incident.last_seen.desc())
        )
    assert incident is not None and incident.payload["file_id"] == body["id"]
    monkeypatch.undo()

    # Задача потерялась (воркер умер): при старте воркера файл возвращается в очередь.
    async with app.state.db_sessions() as db:
        row = await db.get(File, uuid.UUID(body["id"]))
        assert row is not None
        row.parse_status = "processing"
        await db.commit()
    settings = app.state.settings

    async def parse(file_id: str) -> None:
        await jobs.parse_job(file_id, settings)

    assert await jobs.requeue_files_job(settings, parse) >= 1
    ready = (await client.get(f"/api/files/{body['id']}")).json()
    assert ready["parse_status"] == "ready" and ready["parse_error"] is None


# ------------------------------------------------------------------ вложения в промпте


async def test_docx_30_pages_full_text_in_prompt(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, qdrant_url: str
) -> None:
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url, qdrant_url=qdrant_url)
    file = await upload_ready(client, "Отчёт.docx", samples.docx_pages(30, needle_page=25))
    assert file["pages"] == 30 and file["mime"] == DOCX_MIME

    chat_id = await new_chat(client)
    sent = await send(
        client, chat_id, "[[scenario:find]] «Кодовое слово»", attachment_ids=[file["id"]]
    )
    assert [f["id"] for f in sent["user_message"]["files"]] == [file["id"]]
    events = await read_stream(client, sent["assistant_message"]["id"])
    assert text_of(events) == f"Нашёл в документе: {samples.NEEDLE}"

    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    question = detail["messages"][0]
    assert question["files"][0]["filename"] == "Отчёт.docx"
    async with app.state.db_sessions() as db:
        answer = await db.get(Message, sent["assistant_message"]["id"])
        assert answer is not None and answer.trace is not None
        assert answer.trace["attachments"]["mode"] == "full"

    # Повторная отправка того же файла в другое сообщение — отказ.
    again = await client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "ещё", "attachment_ids": [file["id"]]},
    )
    assert again.json()["error"]["code"] == "file_attached"


async def test_large_document_outline_and_read_tool(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, qdrant_url: str
) -> None:
    # Бюджет на полный текст крошечный → в промпте только оглавление, модель дочитывает.
    app, client = await _client(
        make_client,
        infra,
        tmp_path,
        fake_llm_url,
        qdrant_url=qdrant_url,
        files={"full_text_budget_share": 0.001, "outline_preview_chars": 200},
    )
    file = await upload_ready(client, "Отчёт.docx", samples.docx_pages(30, needle_page=25))
    chat_id = await new_chat(client)

    # Целиком документ в промпт не попал, но авто-RAG нашёл фрагмент во вложении (гибрид + реранк).
    events = await ask(
        client, chat_id, "[[scenario:find]] «Кодовое слово»", attachment_ids=[file["id"]]
    )
    assert text_of(events) == f"Нашёл в документе: {samples.NEEDLE} [1]"
    [sources] = [e for e in events if e.event == "sources"]
    card = sources.data["items"][0]
    assert card["kind"] == "attachment" and card["file_id"] == file["id"]
    assert card["title"] == "Отчёт.docx" and card["page"] is not None

    events = await ask(client, chat_id, "[[scenario:tool:read_document]] стр. 25 «Кодовое слово»")
    names = [e.event for e in events]
    assert names.index("tool.start") < names.index("tool.end") < names.index("content.delta")
    # Первый шаг — авто-поиск по базам и вложениям (§8.3), затем инструмент модели.
    assert [e.data["tool"] for e in events if e.event == "tool.end"] == [
        "search_knowledge_base",
        "read_document",
    ]
    start = next(
        e for e in events if e.event == "tool.start" and e.data["tool"] != "search_knowledge_base"
    )
    end = next(e for e in events if e.event == "tool.end" and e.data["tool"] == "read_document")
    assert start.data["tool"] == "read_document" and start.data["label"] == "tools.read_document"
    assert start.data["params"] == {"name": "Отчёт.docx"}
    assert end.data["status"] == "ok" and end.data["params"] == {"name": "Отчёт.docx"}
    assert text_of(events) == f"Готово. Результат инструмента: {samples.NEEDLE}"

    # Шаги видны в истории сообщения (§7.4) и сохранены в tool_calls и трассировке.
    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    answer = detail["messages"][-1]
    auto, step = answer["tools"]
    assert (
        auto["tool"] == "search_knowledge_base" and auto["label"] == "tools.search_knowledge_base"
    )
    assert step["tool"] == "read_document" and step["status"] == "ok"
    async with app.state.db_sessions() as db:
        row = await db.get(Message, answer["id"])
        assert row is not None and row.trace is not None
        assert row.trace["attachments"]["mode"] == "outline"
        assert row.trace["tools"][1]["arguments"]["page_from"] == 25
        assert row.trace["rag"]["stages"] == {"dense": "ok", "bm25": "ok", "rerank": "ok"}
        calls = (
            await db.scalars(
                select(ToolCall).where(ToolCall.message_id == row.id).order_by(ToolCall.iteration)
            )
        ).all()
        assert [(c.tool, c.iteration) for c in calls] == [
            ("search_knowledge_base", 0),
            ("read_document", 1),
        ]

    # Поиск по документу — через Qdrant, только по вложениям этого чата.
    events = await ask(client, chat_id, "[[scenario:tool:search_in_documents]] «Кодовое слово»")
    # Тот же фрагмент, что нашёл авто-поиск, — тот же номер цитаты.
    assert text_of(events) == f"Готово. Результат инструмента: {samples.NEEDLE} [1]"


async def test_parallel_tools_and_iteration_limit(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, client = await _client(
        make_client, infra, tmp_path, fake_llm_url, tools={"max_iterations": 2}
    )
    file = await upload_ready(client, "a.txt", "Строка про отпуск.".encode())
    chat_id = await new_chat(client)
    events = await ask(
        client,
        chat_id,
        "[[scenario:tool:list_attachments+get_document_outline]]",
        attachment_ids=[file["id"]],
    )
    assert [e.data["tool"] for e in events if e.event == "tool.end"] == [
        "list_attachments",
        "get_document_outline",
    ]
    assert "«a.txt»" in text_of(events)

    events = await ask(client, chat_id, "[[scenario:tool_loop]]")
    assert len([e for e in events if e.event == "tool.end"]) == 2
    assert "превышено число шагов" in text_of(events)
    assert events[-1].data == {"status": "completed", "finish_reason": "max_iterations"}
    # Админ узнаёт об этом инцидентом уровня warning (§8.4) — без текста пользователя.
    async with app.state.db_sessions() as db:
        [incident] = (
            await db.scalars(select(Incident).where(Incident.type == "tool_loop_limit"))
        ).all()
        assert incident.severity == "warning" and incident.message_id is not None
        assert incident.payload == {
            "max_iterations": 2,
            "model_role": "chat",
            "tools": ["list_attachments"],
        }


async def test_past_tool_results_stay_in_history(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Уточняющий вопрос: модель видит прошлый вызов инструмента и его результат (§8.1)."""
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    file = await upload_ready(client, "a.txt", "Строка про отпуск: 28 дней.".encode())
    chat_id = await new_chat(client)
    await ask(client, chat_id, "[[scenario:tool:read_document]]", attachment_ids=[file["id"]])
    events = await ask(client, chat_id, "[[scenario:recall]] «отпуск»")
    assert text_of(events) == (
        "В истории вызовы: read_document; результатов: 1. Нашёл: Строка про отпуск: 28 дней."
    )
    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    async with app.state.db_sessions() as db:
        row = await db.get(Message, detail["messages"][-1]["id"])
        assert row is not None and row.trace is not None
        assert row.trace["history_tool_steps"] == 1
        assert row.trace["context"]["peak_tokens"] <= row.trace["context"]["budget"]


async def test_past_tool_results_can_be_switched_off(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(
        make_client, infra, tmp_path, fake_llm_url, tools={"history_result_max_chars": 0}
    )
    file = await upload_ready(client, "a.txt", "Строка про отпуск: 28 дней.".encode())
    chat_id = await new_chat(client)
    await ask(client, chat_id, "[[scenario:tool:read_document]]", attachment_ids=[file["id"]])
    events = await ask(client, chat_id, "[[scenario:recall]] «отпуск»")
    assert text_of(events) == "В истории вызовы: нет; результатов: 0."


async def test_tool_results_are_fitted_into_context(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Результаты инструментов больше остатка контекста обрезаются, ответ не падает (§8.4)."""
    # Каждое чтение 20 страниц упирается в ``tools.result_max_chars`` (≈7 тыс. токенов), а после
    # промпта в контексте остаётся столько же на оба. Запас в обе стороны — тысячи токенов:
    # тест не зависит от правок промптов.
    text = "Кодовое слово: Сириус.\n" + "Обычная строка длинного документа.\n" * 2500
    app, client = await _client(
        make_client,
        infra,
        tmp_path,
        fake_llm_url,
        models={
            "chat": {
                "base_url": fake_llm_url,
                "model": "fake-chat",
                "supports_tools": True,
                "context_length": CONTEXT,
                "max_output_tokens": 1000,
            }
        },
        files={"full_text_budget_share": 0.001, "outline_preview_chars": 200},
    )
    file = await upload_ready(client, "big.md", text.encode())
    chat_id = await new_chat(client)
    events = await ask(
        client,
        chat_id,
        "[[scenario:tool:read_document+read_document]] стр. 1–20 «Кодовое слово»",
        attachment_ids=[file["id"]],
    )
    assert events[-1].data == {"status": "completed", "finish_reason": "stop"}
    assert text_of(events) == "Готово. Результат инструмента: Кодовое слово: Сириус."
    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    async with app.state.db_sessions() as db:
        row = await db.get(Message, detail["messages"][-1]["id"])
        assert row is not None and row.trace is not None
        context = row.trace["context"]
        assert context["tool_results_truncated"] == 2
        assert context["peak_tokens"] <= context["budget"] == CONTEXT - 1000


async def test_unknown_tool_call_is_reported_to_model(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    # Без вложений read_document не предлагается — вызов отклоняется сервером.
    events = await ask(client, chat_id, "[[scenario:tool:read_document]] стр. 1")
    end = next(e for e in events if e.event == "tool.end")
    assert end.data["status"] == "error"
    assert "недоступен" in text_of(events)
    assert events[-1].data["status"] == "completed"


# ------------------------------------------------------------------ генерация файлов


async def _generated(client: ApiClient, chat_id: str, text: str) -> tuple[dict[str, Any], str]:
    events = await ask(client, chat_id, text)
    [file_event] = [e for e in events if e.event == "file"]
    assert events[-1].data["status"] == "completed"
    return file_event.data, text_of(events)


async def test_generate_excel_and_word(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    from openpyxl import load_workbook

    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)

    xlsx, text = await _generated(client, chat_id, "[[scenario:tool:create_spreadsheet]] Excel")
    assert xlsx["name"] == "Продажи по кварталам.xlsx"
    assert xlsx["preview"] is (soffice_binary() is not None)
    assert "создан" in text
    download = await client.get(f"/api/files/{xlsx['file_id']}/content")
    assert download.status_code == 200
    assert "attachment;" in download.headers["content-disposition"]
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in download.headers  # иначе Chromium теряет имя файла
    sheet = load_workbook(io.BytesIO(download.content)).active
    assert sheet is not None and sheet["B6"].value == "=SUM(B2:B5)"
    if xlsx["preview"]:
        preview = await client.get(f"/api/files/{xlsx['file_id']}/preview")
        assert preview.status_code == 200 and preview.content.startswith(b"%PDF-")

    docx, _ = await _generated(client, chat_id, "[[scenario:tool:create_document]] Word")
    content = (await client.get(f"/api/files/{docx['file_id']}/content")).content
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        assert "<m:oMath" in zf.read("word/document.xml").decode()

    # Файлы ответа — в истории: карточки после перезагрузки страницы.
    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    assert [f["filename"] for f in detail["messages"][1]["files"]] == [xlsx["name"]]
    assert detail["messages"][3]["files"][0]["kind"] == "generated"
    assert [s["tool"] for s in detail["messages"][3]["tools"]] == ["create_document"]


@pytest.mark.skipif(soffice_binary() is None, reason="нужен LibreOffice")
async def test_generate_pdf(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    pdf, _ = await _generated(client, chat_id, "[[scenario:tool:create_pdf]]")
    inline = await client.get(f"/api/files/{pdf['file_id']}/content?download=false")
    assert inline.headers["content-type"] == "application/pdf"
    assert inline.headers["content-disposition"].startswith("inline;")
    assert inline.headers["content-security-policy"] == "sandbox"


@pytest.mark.skipif(not tesseract_available(), reason="нужен Tesseract")
async def test_scanned_pdf_answer(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    file = await upload_ready(client, "Скан.pdf", samples.scanned_pdf("SCAN TEST 2026 OCR"))
    chat_id = await new_chat(client)
    events = await ask(
        client, chat_id, "[[scenario:find]] «SCAN TEST»", attachment_ids=[file["id"]]
    )
    assert text_of(events).startswith("Нашёл в документе: SCAN TEST 2026")


# ------------------------------------------------------------------ доступ


async def test_files_are_private(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    settings = chat_settings(infra, tmp_path, fake_llm_url)
    _, owner = await make_client(settings)
    await owner.login("petrov")
    _, other = await make_client(settings)
    await other.login("kim")

    file = await upload_ready(owner, "Секрет.md", "# Секрет".encode())
    for path in ("", "/content", "/preview"):
        assert (await other.get(f"/api/files/{file['id']}{path}")).status_code == 404
    assert (await other.request("DELETE", f"/api/files/{file['id']}")).status_code == 404

    chat_id = await new_chat(other)
    response = await other.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "Что там?", "attachment_ids": [file["id"]]},
    )
    assert response.status_code == 404

    # Владелец может удалить неприложенный файл.
    assert (await owner.request("DELETE", f"/api/files/{file['id']}")).status_code == 204
    assert (await owner.get(f"/api/files/{file['id']}")).status_code == 404
