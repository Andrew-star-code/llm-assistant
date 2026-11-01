"""Выгрузки переписки и плановые задачи (этап 6, §13.3, §14): форматы, доступ только заказавшему,
срок хранения, предел размера, скорость выгрузки 1000 сообщений, очистка удалённого по сроку.
"""

from __future__ import annotations

import io
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.modules.admin.models import AppSetting
from app.modules.audit.models import AuditLog
from app.modules.chats.models import Chat, Message
from app.modules.exports.models import Export
from app.modules.ingestion.convert import soffice_binary
from app.modules.rbac.models import Role
from app.modules.tools.models import ToolCall
from app.modules.users.models import User
from app.workers import export_jobs
from tests.integration.conftest import ApiClient, Infra, chat_settings, new_chat, read_stream, send


async def _chat(client: ApiClient, text: str) -> tuple[str, str]:
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, text)
    answer_id = sent["assistant_message"]["id"]
    await read_stream(client, answer_id)
    return chat_id, answer_id


async def _export(admin: ApiClient, **body: Any) -> dict[str, Any]:
    response = await admin.post("/api/admin/exports", json=body)
    assert response.status_code == 202, response.text
    result: dict[str, Any] = response.json()
    return result


async def _download(admin: ApiClient, export_id: str) -> bytes:
    response = await admin.get(f"/api/admin/exports/{export_id}/download")
    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    return response.content


async def _stand(make_client: Any, infra: Infra, tmp_path: Path, url: str, **overrides: Any) -> Any:
    settings = chat_settings(infra, tmp_path, url, **overrides)
    app, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    _, kim = await make_client(settings)
    for client, login in ((admin, "ivanov"), (petrov, "petrov"), (kim, "kim")):
        assert (await client.login(login)).status_code == 200
    return settings, app, admin, petrov, kim


async def test_export_formats_access_and_audit(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, app, admin, petrov, kim = await _stand(make_client, infra, tmp_path, fake_llm_url)
    chat_id, answer_id = await _chat(petrov, "Расскажи про отпуск")
    await _chat(kim, "Как настроить принтер")
    async with app.state.db_sessions() as db:
        db.add(
            ToolCall(
                message_id=uuid.UUID(answer_id), call_id="h", tool="report_incident",
                arguments={}, result_preview="ok", status="ok", duration_ms=1,
                visibility="hidden", iteration=1, label="x",
            )
        )  # fmt: skip
        await db.commit()

    # JSON — полная: скрытые вызовы, все поля сообщения.
    done = await _export(admin, format="json", chat_id=chat_id)
    assert done["status"] == "ready" and done["chats"] == 1 and done["messages"] == 2
    assert done["filename"].endswith(".json") and done["expires_at"]
    data = json.loads(await _download(admin, done["id"]))
    [chat] = data["chats"]
    assert chat["user"]["login"] == "petrov"
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][1]["tool_calls"][0]["visibility"] == "hidden"

    # XLSX по фильтру (отдел): только чаты petrov, строка на сообщение.
    from openpyxl import load_workbook

    by_dept = await _export(admin, format="xlsx", filter={"department": "Бухгалтерия"})
    assert by_dept["status"] == "ready" and by_dept["chats"] == 1
    sheet = load_workbook(io.BytesIO(await _download(admin, by_dept["id"]))).active
    assert sheet is not None
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][0] == "Чат" and len(rows) == 3
    assert {r[2] for r in rows[1:]} == {"petrov"}
    assert "report_incident (скрытый)" in {r[18] for r in rows[1:]}

    # DOCX — читаемая стенограмма.
    from docx import Document

    docx = await _export(admin, format="docx", chat_id=chat_id)
    assert docx["status"] == "ready", docx
    text = "\n".join(
        p.text for p in Document(io.BytesIO(await _download(admin, docx["id"]))).paragraphs
    )
    assert "Расскажи про отпуск" in text and "Петров" in text

    # Неверный запрос: и чат, и фильтр сразу.
    bad = await admin.post(
        "/api/admin/exports", json={"format": "json", "chat_id": chat_id, "filter": {}}
    )
    assert bad.status_code == 422

    # Файл доступен только заказавшему — даже другому админу нет.
    async with app.state.db_sessions() as db:
        kim_id = await db.scalar(select(User.id).where(User.login == "kim"))
        role_id = await db.scalar(select(Role.id).where(Role.code == "admin"))
    await admin.request(
        "PUT", f"/api/admin/users/{kim_id}/roles", json={"role_ids": [str(role_id)]}
    )
    await kim.login("kim")
    assert (await kim.get(f"/api/admin/exports/{done['id']}/download")).status_code == 404
    assert (await kim.get("/api/admin/exports")).json() == []
    assert len((await admin.get("/api/admin/exports")).json()) == 3
    # Файл выгрузки не отдаётся через обычные файлы пользователя.
    async with app.state.db_sessions() as db:
        row = await db.get(Export, uuid.UUID(done["id"]))
        assert row is not None and row.file_id is not None
        file_id = row.file_id
    assert (await admin.get(f"/api/files/{file_id}/content")).status_code == 404

    async with app.state.db_sessions() as db:
        actions = (await db.scalars(select(AuditLog.action))).all()
    assert actions.count("chat.export") == 3 and actions.count("export.download") == 3


@pytest.mark.skipif(soffice_binary() is None, reason="нужен LibreOffice")
async def test_export_pdf(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, _, admin, petrov, _ = await _stand(make_client, infra, tmp_path, fake_llm_url)
    chat_id, _ = await _chat(petrov, "Привет")
    pdf = await _export(admin, format="pdf", chat_id=chat_id)
    assert pdf["status"] == "ready", pdf
    assert (await _download(admin, pdf["id"])).startswith(b"%PDF")


async def test_export_expiry_and_size_limit(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    settings, app, admin, petrov, _ = await _stand(
        make_client, infra, tmp_path, fake_llm_url, exports={"max_messages": 3}
    )
    chat_id, _ = await _chat(petrov, "Первый")
    await _chat(petrov, "Второй")
    too_big = await _export(admin, format="json", filter={})
    assert too_big["status"] == "error" and "предела 3" in too_big["error"]

    ok = await _export(admin, format="json", chat_id=chat_id)
    async with app.state.db_sessions() as db:
        row = await db.get(Export, uuid.UUID(ok["id"]))
        assert row is not None
        row.expires_at = utcnow() - timedelta(minutes=1)
        await db.commit()
    gone = await admin.get(f"/api/admin/exports/{ok['id']}/download")
    assert gone.status_code == 410
    assert await export_jobs.cleanup_exports_job(settings) == 1
    listed = (await admin.get(f"/api/admin/exports/{ok['id']}")).json()
    assert listed["status"] == "expired" and listed["filename"] is None


async def test_xlsx_export_of_1000_messages_under_a_minute(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Критерий этапа 6: выгрузка 1000 сообщений в XLSX готова меньше чем за минуту."""
    _, app, admin, _, _ = await _stand(make_client, infra, tmp_path, fake_llm_url)
    async with app.state.db_sessions() as db:
        petrov_id = await db.scalar(select(User.id).where(User.login == "petrov"))
        assert petrov_id is not None
        now = utcnow()
        for c in range(10):
            chat = Chat(user_id=petrov_id, title=f"Нагрузочный {c}", last_message_at=now)
            db.add(chat)
            await db.flush()
            parent = None
            for i in range(100):
                m = Message(
                    chat_id=chat.id, parent_id=parent, role="user" if i % 2 == 0 else "assistant",
                    content=f"Сообщение {i} " + "текст " * 80, status="completed",
                    created_at=now + timedelta(milliseconds=c * 1000 + i),
                )  # fmt: skip
                db.add(m)
                await db.flush()
                parent = m.id
        await db.commit()

    started = time.monotonic()
    export = await _export(admin, format="xlsx", filter={"user_id": str(petrov_id)})
    elapsed = time.monotonic() - started
    assert export["status"] == "ready" and export["messages"] == 1000, export
    assert elapsed < 60, elapsed
    from openpyxl import load_workbook

    sheet = load_workbook(io.BytesIO(await _download(admin, export["id"])), read_only=True).active
    assert sheet is not None
    assert sum(1 for _ in sheet.iter_rows(values_only=True)) == 1001


async def test_retention_purges_old_deleted_chats(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    settings, app, _, petrov, _ = await _stand(make_client, infra, tmp_path, fake_llm_url)
    old_id, _ = await _chat(petrov, "Старый удалённый")
    fresh_id, _ = await _chat(petrov, "Недавно удалённый")
    alive_id, _ = await _chat(petrov, "Живой")
    for chat_id in (old_id, fresh_id):
        assert (await petrov.request("DELETE", f"/api/chats/{chat_id}")).status_code == 204
    async with app.state.db_sessions() as db:
        old = await db.get(Chat, uuid.UUID(old_id))
        assert old is not None and old.deleted_at is not None
        old.deleted_at = utcnow() - timedelta(days=40)
        await db.commit()

    # По умолчанию очистка выключена (§14).
    assert await export_jobs.retention_job(settings) == 0
    # Срок из админки перекрывает конфиг.
    async with app.state.db_sessions() as db:
        db.add(AppSetting(key="retention.deleted_days", value=30))
        await db.commit()
    assert await export_jobs.retention_job(settings) == 1
    async with app.state.db_sessions() as db:
        assert await db.get(Chat, uuid.UUID(old_id)) is None
        assert await db.get(Chat, uuid.UUID(fresh_id)) is not None
        assert await db.get(Chat, uuid.UUID(alive_id)) is not None
        [entry] = (
            await db.scalars(select(AuditLog).where(AuditLog.action == "retention.purge"))
        ).all()
    assert entry.actor_id is None and entry.target_id == old_id
    assert entry.details is not None and entry.details["days"] == 30
