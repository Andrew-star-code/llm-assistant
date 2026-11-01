"""Админка «Переписка» (этап 6, §13.3, §18.2): поиск по слову, фильтры, просмотр с аудитом,
скрытые вызовы инструментов, восстановление, физическое удаление, права kb_manager и admin.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.chats.models import Message
from app.modules.rbac.models import Role
from app.modules.tools.models import ToolCall
from app.modules.users.models import User
from tests.integration.conftest import ApiClient, Infra, chat_settings, new_chat, read_stream, send


async def _chat_with_answer(client: ApiClient, text: str) -> tuple[str, str]:
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, text)
    answer_id = sent["assistant_message"]["id"]
    await read_stream(client, answer_id)
    return chat_id, answer_id


async def _grant(app: Any, admin: ApiClient, login: str, role_code: str) -> None:
    async with app.state.db_sessions() as db:
        user_id = await db.scalar(select(User.id).where(User.login == login))
        role_id = await db.scalar(select(Role.id).where(Role.code == role_code))
    response = await admin.request(
        "PUT", f"/api/admin/users/{user_id}/roles", json={"role_ids": [str(role_id)]}
    )
    assert response.status_code in (200, 204), response.text


async def _audit(app: Any, action: str) -> list[AuditLog]:
    async with app.state.db_sessions() as db:
        return list((await db.scalars(select(AuditLog).where(AuditLog.action == action))).all())


async def stand(make_client: Any, infra: Infra, tmp_path: Path, url: str) -> Any:
    settings = chat_settings(infra, tmp_path, url)
    app, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    _, kim = await make_client(settings)
    for client, login in ((admin, "ivanov"), (petrov, "petrov"), (kim, "kim")):
        assert (await client.login(login)).status_code == 200
    return app, admin, petrov, kim


async def test_admin_finds_message_by_word_and_view_is_audited(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, admin, petrov, kim = await stand(make_client, infra, tmp_path, fake_llm_url)
    chat_id, answer_id = await _chat_with_answer(petrov, "Подготовь квартальный отчёт ZEBRA-17")
    other_id, _ = await _chat_with_answer(kim, "Как настроить принтер")
    await petrov.request(
        "PUT", f"/api/messages/{answer_id}/feedback", json={"rating": -1, "reasons": ["inaccurate"]}
    )

    # Другая словоформа (русская морфология) и код целиком (подстрока).
    for q in ("квартального отчёта", "ZEBRA-17"):
        hits = (await admin.get("/api/admin/messages", params={"q": q})).json()["items"]
        # Совпасть может и вопрос, и ответ (заглушка модели повторяет вопрос).
        assert {h["chat_id"] for h in hits} == {chat_id}, q
        hit = next(h for h in hits if h["role"] == "user")
        assert hit["user"]["login"] == "petrov"
        assert any(f["match"] for f in hit["fragments"])

    # Фильтры: отдел, дизлайк, период, пользователь.
    by_dept = await admin.get("/api/admin/messages", params={"department": "Бухгалтерия"})
    assert {h["chat_id"] for h in by_dept.json()["items"]} == {chat_id}
    disliked = (await admin.get("/api/admin/messages", params={"disliked": "true"})).json()
    assert [h["message_id"] for h in disliked["items"]] == [answer_id]
    future = await admin.get("/api/admin/messages", params={"date_from": "2100-01-01"})
    assert future.json()["items"] == []
    chats = (await admin.get("/api/admin/chats", params={"disliked": "true"})).json()["items"]
    assert [c["id"] for c in chats] == [chat_id] and chats[0]["messages"] == 2
    everyone = (await admin.get("/api/admin/chats")).json()["items"]
    assert {c["id"] for c in everyone} == {chat_id, other_id}
    options = (await admin.get("/api/admin/chats/filters")).json()
    assert "Бухгалтерия" in options["departments"] and options["models"]

    # Скрытый вызов инструмента: админ видит, пользователь — нет (§9.6).
    async with app.state.db_sessions() as db:
        db.add(
            ToolCall(
                message_id=uuid.UUID(answer_id), call_id="hidden-1", tool="report_incident",
                arguments={"category": "test"}, result_preview="ok", status="ok",
                duration_ms=5, visibility="hidden", iteration=1, label="tools.status.hidden",
            )
        )  # fmt: skip
        await db.commit()

    detail = (await admin.get(f"/api/admin/chats/{chat_id}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    answer = detail["messages"][1]
    assert answer["feedback"]["rating"] == -1 and answer["model"]
    assert [c["tool"] for c in answer["tool_calls"]] == ["report_incident"]
    assert answer["tool_calls"][0]["visibility"] == "hidden"
    assert detail["user"]["login"] == "petrov"
    own = (await petrov.get(f"/api/chats/{chat_id}")).json()
    assert all(t["tool"] != "report_incident" for m in own["messages"] for t in m["tools"])

    [view] = await _audit(app, "chat.view")
    assert view.target_id == chat_id and view.details == {
        "user_id": detail["user"]["id"],
        "login": "petrov",
    }
    assert (await admin.get(f"/api/admin/chats/{uuid.uuid4()}")).status_code == 404


async def test_deleted_chat_restore_and_purge(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, admin, petrov, kim = await stand(make_client, infra, tmp_path, fake_llm_url)
    chat_id, answer_id = await _chat_with_answer(petrov, "Секретный план удаления")
    assert (await petrov.request("DELETE", f"/api/chats/{chat_id}")).status_code == 204
    assert (await petrov.get(f"/api/chats/{chat_id}")).status_code == 404

    # Удалённое видно админу и находится фильтром «удалённые».
    deleted = (await admin.get("/api/admin/messages", params={"deleted": "true"})).json()
    assert {h["chat_id"] for h in deleted["items"]} == {chat_id}
    assert all(h["deleted"] for h in deleted["items"])
    alive = (await admin.get("/api/admin/messages", params={"deleted": "false"})).json()
    assert alive["items"] == []
    detail = (await admin.get(f"/api/admin/chats/{chat_id}")).json()
    assert detail["deleted_at"] and detail["deleted_by"]["login"] == "petrov"

    restored = await admin.post(f"/api/admin/chats/{chat_id}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["deleted_at"] is None
    assert (await petrov.get(f"/api/chats/{chat_id}")).status_code == 200
    assert (await admin.post(f"/api/admin/chats/{chat_id}/restore")).status_code == 409
    assert len(await _audit(app, "chat.restore")) == 1

    # Физическое удаление — только superadmin: у роли admin этого права нет.
    await _grant(app, admin, "kim", "admin")
    assert (await kim.login("kim")).status_code == 200
    assert (await kim.get(f"/api/admin/chats/{chat_id}")).status_code == 200
    denied = await kim.post(f"/api/admin/chats/{chat_id}/purge", json={"confirm": chat_id})
    assert denied.status_code == 403
    wrong = await admin.post(f"/api/admin/chats/{chat_id}/purge", json={"confirm": "да"})
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "confirm_mismatch"
    purged = await admin.post(f"/api/admin/chats/{chat_id}/purge", json={"confirm": chat_id})
    assert purged.status_code == 200, purged.text
    assert purged.json() == {"messages": 2, "files": 0}
    assert (await admin.get(f"/api/admin/chats/{chat_id}")).status_code == 404
    assert (await petrov.get(f"/api/chats/{chat_id}")).status_code == 404
    async with app.state.db_sessions() as db:
        assert await db.get(Message, uuid.UUID(answer_id)) is None
    [entry] = await _audit(app, "chat.purge")
    # В аудите — кто и сколько, без содержимого переписки.
    assert entry.details is not None and "Секретный" not in str(entry.details)
    assert entry.details["messages"] == 2


async def test_purge_removes_chat_files(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, admin, petrov, _ = await stand(make_client, infra, tmp_path, fake_llm_url)
    upload = await petrov.post(
        "/api/files", files={"file": ("заметка.md", "# Заметка\n\nТекст.".encode(), "text/md")}
    )
    file_id = upload.json()["id"]
    chat_id = await new_chat(petrov)
    sent = await send(petrov, chat_id, "Что в файле?", attachment_ids=[file_id])
    await read_stream(petrov, sent["assistant_message"]["id"])
    storage = app.state.storage
    async with app.state.db_sessions() as db:
        from app.modules.files.models import File

        row = await db.get(File, uuid.UUID(file_id))
        assert row is not None and row.chat_id == uuid.UUID(chat_id)
        key = row.storage_key
    assert await storage.get(key) is not None
    purged = await admin.post(f"/api/admin/chats/{chat_id}/purge", json={"confirm": chat_id})
    assert purged.json() == {"messages": 2, "files": 1}
    assert await storage.get(key) is None
    assert (await petrov.get(f"/api/files/{file_id}")).status_code == 404


async def test_kb_manager_does_not_see_correspondence(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Критерий этапа 6: kb_manager без роли admin не видит переписку."""
    app, admin, petrov, kim = await stand(make_client, infra, tmp_path, fake_llm_url)
    chat_id, _ = await _chat_with_answer(petrov, "Личная переписка")
    await _grant(app, admin, "kim", "kb_manager")
    me = (await kim.login("kim")).json()
    assert "admin.access" in me["permissions"]
    assert not {p for p in me["permissions"] if p.startswith("admin.chats")}
    for path in (
        "/api/admin/messages",
        "/api/admin/chats",
        "/api/admin/chats/filters",
        f"/api/admin/chats/{chat_id}",
    ):
        assert (await kim.get(path)).status_code == 403, path
    assert (await kim.post(f"/api/admin/chats/{chat_id}/restore")).status_code == 403
    assert await _audit(app, "chat.view") == []
