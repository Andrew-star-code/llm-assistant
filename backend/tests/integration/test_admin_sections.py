"""Админка этапа 6 (§13.2): обратная связь, дашборд, модели, инструменты, настройки.

Проверяется и действие: выключенный инструмент не предлагается модели, скрытая модель скрывает
сценарий, настройки (название, промпт, лимиты, обращение, уведомление) действуют без перезапуска.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.files.models import File
from app.modules.kb.models import KbDocument, KbImport, KnowledgeBase
from app.modules.rbac.models import Role
from app.modules.users.models import User
from tests.integration.conftest import ApiClient, Infra, chat_settings, new_chat, read_stream, send

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def _ask(client: ApiClient, text: str, chat_id: str | None = None) -> tuple[str, str]:
    chat_id = chat_id or await new_chat(client)
    sent = await send(client, chat_id, text)
    answer_id = sent["assistant_message"]["id"]
    events = await read_stream(client, answer_id)
    reply = "".join(e.data["text"] for e in events if e.event == "content.delta")
    return answer_id, reply


async def _grant(app: Any, admin: ApiClient, login: str, role_code: str) -> None:
    async with app.state.db_sessions() as db:
        user_id = await db.scalar(select(User.id).where(User.login == login))
        role_id = await db.scalar(select(Role.id).where(Role.code == role_code))
    response = await admin.request(
        "PUT", f"/api/admin/users/{user_id}/roles", json={"role_ids": [str(role_id)]}
    )
    assert response.status_code in (200, 204), response.text


async def _actions(app: Any) -> list[str]:
    async with app.state.db_sessions() as db:
        return list((await db.scalars(select(AuditLog.action))).all())


async def _stand(make_client: Any, infra: Infra, tmp_path: Path, url: str, **overrides: Any) -> Any:
    settings = chat_settings(infra, tmp_path, url, **overrides)
    app, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    _, kim = await make_client(settings)
    for client, login in ((admin, "ivanov"), (petrov, "petrov"), (kim, "kim")):
        assert (await client.login(login)).status_code == 200
    return settings, app, admin, petrov, kim


async def test_feedback_and_dashboard(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, app, admin, petrov, kim = await _stand(make_client, infra, tmp_path, fake_llm_url)
    disliked, _ = await _ask(petrov, "Сколько дней отпуска положено")
    liked, _ = await _ask(kim, "Как подключить принтер")
    await petrov.request(
        "PUT", f"/api/messages/{disliked}/feedback",
        json={"rating": -1, "reasons": ["inaccurate"], "comment": "Неверно посчитано"},
    )  # fmt: skip
    await kim.request("PUT", f"/api/messages/{liked}/feedback", json={"rating": 1})

    page = (await admin.get("/api/admin/feedback", params={"rating": -1})).json()
    [item] = page["items"]
    assert item["message_id"] == disliked and item["reasons"] == ["inaccurate"]
    assert item["question"] == "Сколько дней отпуска положено"
    assert item["user"]["login"] == "petrov" and item["comment"] == "Неверно посчитано"
    by_reason = await admin.get("/api/admin/feedback", params={"reason": "inaccurate"})
    assert len(by_reason.json()["items"]) == 1
    stats = (await admin.get("/api/admin/feedback/stats")).json()
    assert stats == {"likes": 1, "dislikes": 1, "reasons": {"inaccurate": 1}}

    from openpyxl import load_workbook

    exported = await admin.get("/api/admin/feedback/export")
    assert exported.status_code == 200
    sheet = load_workbook(io.BytesIO(exported.content)).active
    assert sheet is not None and sheet.max_row == 3
    assert "feedback.export" in await _actions(app)

    board = (await admin.get("/api/admin/dashboard")).json()
    assert board["active_users"] == {"day": 2, "week": 2, "month": 2}
    assert len(board["series"]) == 30
    today = board["series"][-1]
    assert today["messages"] == 2 and today["answers"] == 2 and today["tokens"] > 0
    assert board["quality"]["likes"] == 1 and board["quality"]["dislikes"] == 1
    assert board["quality"]["like_share"] == 0.5 and board["quality"]["errors"] == 0
    assert {m["role"] for m in board["models"]} >= {"chat", "embed"}
    assert all(m["ok"] for m in board["models"] if m["role"] == "chat")
    assert board["gpus"] is None and "prometheus_url" in board["gpu_note"]
    assert board["queues"]["attachments_pending"] == 0

    # kb_manager — ни обратной связи, ни дашборда.
    await _grant(app, admin, "kim", "kb_manager")
    await kim.login("kim")
    for path in ("/api/admin/feedback", "/api/admin/dashboard", "/api/admin/feedback/export"):
        assert (await kim.get(path)).status_code == 403, path


async def test_dashboard_counts_only_unfinished_imports(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Импорт с готовыми документами не «идёт», даже если страницу базы никто не открывал."""
    _, app, admin, _, _ = await _stand(make_client, infra, tmp_path, fake_llm_url)
    async with app.state.db_sessions() as db:
        owner = await db.scalar(select(User.id).where(User.login == "ivanov"))
        kb = KnowledgeBase(code="imports", name="Импорт", level="global", embed_model="m")
        db.add(kb)
        await db.flush()
        scanning = KbImport(kb_id=kb.id, path="/a", status="scanning")
        finished = KbImport(kb_id=kb.id, path="/b", status="running")
        active = KbImport(kb_id=kb.id, path="/c", status="running")
        db.add_all([scanning, finished, active])
        await db.flush()
        docs = []
        for imp, status, sha in ((finished, "ready", "a" * 64), (active, "queued", "b" * 64)):
            file = File(
                owner_id=owner, kind="kb_document", filename="x.txt", mime="text/plain",
                file_type="txt", size=1, sha256=sha, storage_key=f"kb/{sha}", parse_status="ready",
            )  # fmt: skip
            db.add(file)
            await db.flush()
            doc = KbDocument(
                kb_id=kb.id, file_id=file.id, title="x", status=status, sha256=sha, import_id=imp.id
            )
            db.add(doc)
            docs.append(doc)
        await db.commit()
        last_doc = docs[-1].id

    board = (await admin.get("/api/admin/dashboard")).json()
    assert board["queues"]["imports_running"] == 2  # сканируется и ждёт документ

    async with app.state.db_sessions() as db:
        doc = await db.get(KbDocument, last_doc)
        assert doc is not None
        doc.status = "ready"
        await db.commit()
    board = (await admin.get("/api/admin/dashboard")).json()
    assert board["queues"]["imports_running"] == 1  # осталось только сканирование


async def test_tools_toggle_and_model_visibility(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, app, admin, petrov, kim = await _stand(make_client, infra, tmp_path, fake_llm_url)
    tools = {t["name"]: t for t in (await admin.get("/api/admin/tools")).json()}
    assert tools["create_document"]["enabled"] and tools["create_document"]["calls"] == 0

    # Выключенный инструмент не предлагается модели со следующего сообщения.
    off = await admin.request("PUT", "/api/admin/tools/create_document", json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False
    answer_id, _ = await _ask(petrov, "Сделай документ")
    async with app.state.db_sessions() as db:
        from app.modules.chats.models import Message

        message = await db.get(Message, uuid.UUID(answer_id))
        assert message is not None and message.trace is not None
        offered = message.trace["tools_offered"]
    assert "create_document" not in offered and "create_spreadsheet" in offered
    await admin.request("PUT", "/api/admin/tools/create_document", json={"enabled": True})
    assert (
        await admin.request("PUT", "/api/admin/tools/nope", json={"enabled": True})
    ).status_code == 404

    # Модели: реестр, состояние, видимость.
    models = {m["role"]: m for m in (await admin.get("/api/admin/models")).json()}
    assert models["chat"]["restrictable"] is False and models["coder"]["restrictable"] is True
    health = {h["role"]: h for h in (await admin.get("/api/admin/models/health")).json()}
    assert health["chat"]["ok"] is True
    denied = await admin.request(
        "PUT", "/api/admin/models/chat/visibility", json={"roles": ["legal"]}
    )
    assert denied.status_code == 422

    body: dict[str, Any] = {
        "code": f"coder-{uuid.uuid4().hex[:6]}", "name": "Код-ревью", "description": "x",
        "icon": "sparkles", "roles": [], "model_role": "coder", "prompt_template": "Ревью кода.",
        "tools": None, "knowledge_bases": [], "rag_mode": "off", "requires_attachment": False,
        "starter_prompts": [], "thinking_default": None, "is_active": True, "sort_order": 0,
    }  # fmt: skip
    created = await admin.post("/api/admin/scenarios", json=body)
    assert created.status_code == 201, created.text
    scenario = created.json()
    visible = {s["id"] for s in (await petrov.get("/api/scenarios")).json()}
    assert scenario["id"] in visible
    limited = await admin.request(
        "PUT", "/api/admin/models/coder/visibility", json={"roles": ["it"]}
    )
    assert limited.json()["visible_to"] == ["it"] and limited.json()["scenarios"] == ["Код-ревью"]
    assert scenario["id"] not in {s["id"] for s in (await petrov.get("/api/scenarios")).json()}
    started = await petrov.post("/api/chats", json={"scenario_id": scenario["id"]})
    assert started.status_code == 404
    await _grant(app, admin, "kim", "it")
    await kim.login("kim")
    assert scenario["id"] in {s["id"] for s in (await kim.get("/api/scenarios")).json()}

    actions = await _actions(app)
    assert actions.count("tools.toggle") == 2 and "models.visibility" in actions


async def test_settings_apply_without_restart(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    settings, app, admin, petrov, kim = await _stand(make_client, infra, tmp_path, fake_llm_url)
    initial = (await admin.get("/api/admin/settings")).json()
    assert initial["overridden"] == [] and initial["app_name"] == settings.app_name
    assert "Ты — корпоративный ИИ-ассистент" in initial["system_prompt"]
    assert (await petrov.post("/api/auth/notice/accept")).status_code == 204
    assert (await petrov.get("/api/auth/me")).json()["notice"]["required"] is False

    bad = await admin.request("PUT", "/api/admin/settings", json={"system_prompt": "{{ company"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "bad_template"
    changed = await admin.request(
        "PUT",
        "/api/admin/settings",
        json={
            "app_name": "Помощник Корпорации",
            "company_name": "ООО «Ромашка»",
            "max_file_mb": 1,
            "default_address_form": "first_name",
            "system_prompt": "Особые правила компании {{ company }}.",
            "notice_text": "Новый текст уведомления.",
            "require_notice_reaccept": True,
        },
    )
    assert changed.status_code == 200, changed.text
    assert set(changed.json()["overridden"]) == {
        "app_name", "company_name", "max_file_mb", "default_address_form", "system_prompt",
        "notice_text",
    }  # fmt: skip

    assert (await petrov.get("/api/branding")).json()["app_name"] == "Помощник Корпорации"
    assert (await petrov.get("/api/files/limits")).json()["max_file_mb"] == 1
    big = await petrov.post(
        "/api/files", files={"file": ("big.txt", b"a" * (1024 * 1024 + 1), "text/plain")}
    )
    assert big.status_code == 413
    assert (await petrov.get("/api/profile")).json()["address"] == "Сергей"
    me = (await petrov.get("/api/auth/me")).json()
    assert me["notice"] == {"required": True, "text": "Новый текст уведомления."}
    # Базовый системный промпт из админки — уже в следующем сообщении.
    _, reply = await _ask(petrov, "[[scenario:find]] «Особые правила»")
    assert reply == "Нашёл в документе: Особые правила компании ООО «Ромашка»."

    # Логотип: PNG — да, SVG — нет; виден без входа.
    logo = await admin.post("/api/admin/settings/logo", files={"file": ("l.png", PNG, "image/png")})
    assert logo.status_code == 200 and logo.json()["has_logo"] is True
    svg = await admin.post(
        "/api/admin/settings/logo", files={"file": ("l.svg", b"<svg/>", "image/svg+xml")}
    )
    assert svg.status_code == 415
    url = (await petrov.get("/api/branding")).json()["logo_url"]
    image = await petrov.get(url)
    assert image.status_code == 200 and image.content == PNG
    assert image.headers["content-type"] == "image/png"

    # Сброс к конфигу.
    reset = await admin.request(
        "PUT", "/api/admin/settings", json={"system_prompt": None, "max_file_mb": None}
    )
    assert "system_prompt" not in reset.json()["overridden"]
    assert reset.json()["max_file_mb"] == settings.files.max_file_mb
    _, reply = await _ask(petrov, "[[scenario:find]] «Особые правила»")
    assert reply.startswith("В документах нет")

    # Настройки — только superadmin: у роли admin их нет.
    await _grant(app, admin, "kim", "admin")
    await kim.login("kim")
    assert (await kim.get("/api/admin/settings")).status_code == 403
    assert (await kim.get("/api/admin/dashboard")).status_code == 200
    audit = await admin.get("/api/admin/audit", params={"action": "settings.update"})
    details = audit.json()["items"][-1]["details"]
    assert details["system_prompt"] == "изменён" and details["max_file_mb"] == 1
