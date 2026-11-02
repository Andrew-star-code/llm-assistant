"""Сценарии (этап 5): видимость по ролям, применение промпта, модели, инструментов, баз знаний,
режима RAG и thinking; правка без перезапуска; «нужно вложение»; тестовый чат редактора.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.chats.models import Message
from tests.integration.conftest import ApiClient, Infra, chat_settings, read_stream, send

IT = "it"  # роль kim и ivanov из правил ldap.department_roles (config/app.yaml); у petrov её нет


def spec(code: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "code": code,
        "name": f"Сценарий {code}",
        "description": "Для тестов",
        "icon": "sparkles",
        "roles": [],
        "model_role": "chat",
        "prompt_template": "Сценарий-маркер {{ scenario.name }} для {{ user.address }}.",
        "tools": None,
        "knowledge_bases": [],
        "rag_mode": "auto",
        "requires_attachment": False,
        "starter_prompts": ["Пример запроса"],
        "thinking_default": None,
        "is_active": True,
        "sort_order": 0,
    }
    return {**base, **overrides}


def uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


async def create(admin: ApiClient, body: dict[str, Any]) -> dict[str, Any]:
    response = await admin.post("/api/admin/scenarios", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def scenario_chat(client: ApiClient, scenario_id: str) -> str:
    response = await client.post("/api/chats", json={"scenario_id": scenario_id})
    assert response.status_code == 201, response.text
    assert response.json()["scenario"]["id"] == scenario_id
    return str(response.json()["id"])


async def ask(client: ApiClient, chat_id: str, text: str, **body: Any) -> tuple[str, str]:
    sent = await send(client, chat_id, text, **body)
    events = await read_stream(client, sent["assistant_message"]["id"])
    answer = "".join(e.data["text"] for e in events if e.event == "content.delta")
    return answer, str(sent["assistant_message"]["id"])


async def trace_of(app: Any, message_id: str) -> tuple[dict[str, Any], Message]:
    async with app.state.db_sessions() as db:
        row = await db.get(Message, uuid.UUID(message_id))
        assert row is not None and row.trace is not None
        return row.trace, row


@pytest.fixture
async def stand(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, qdrant_url: str
) -> tuple[Any, ApiClient, ApiClient, ApiClient]:
    settings = chat_settings(infra, tmp_path, fake_llm_url, qdrant_url=qdrant_url)
    app, admin = await make_client(settings)
    _, kim = await make_client(settings)
    _, petrov = await make_client(settings)
    for client, login in ((admin, "ivanov"), (kim, "kim"), (petrov, "petrov")):
        assert (await client.login(login)).status_code == 200
    return app, admin, kim, petrov


async def test_builtin_scenarios_are_seeded_and_filtered_by_roles(stand: Any) -> None:
    _, admin, kim, petrov = stand
    seeded = {s["code"]: s for s in (await admin.get("/api/admin/scenarios")).json()}
    assert {"contract_review", "it_support"} <= set(seeded)
    assert seeded["contract_review"]["source"] == "seed"
    assert "Анализ договоров" in seeded["contract_review"]["prompt_template"]
    assert seeded["contract_review"]["requires_attachment"] is True

    it_only = await create(admin, spec(uniq("it-only"), roles=[IT]))
    kim_codes = {s["code"] for s in (await kim.get("/api/scenarios")).json()}
    petrov_codes = {s["code"] for s in (await petrov.get("/api/scenarios")).json()}
    # ИТ-поддержка — всем; анализ договоров — только legal/management; свой — только роли it.
    assert "it_support" in kim_codes and "it_support" in petrov_codes
    assert "contract_review" not in kim_codes | petrov_codes
    assert it_only["code"] in kim_codes and it_only["code"] not in petrov_codes

    # Чужой сценарий нельзя ни выбрать, ни подставить в чат.
    response = await petrov.post("/api/chats", json={"scenario_id": it_only["id"]})
    assert response.status_code == 404
    own = (await petrov.post("/api/chats", json={})).json()["id"]
    patch = await petrov.request("PATCH", f"/api/chats/{own}", json={"scenario_id": it_only["id"]})
    assert patch.status_code == 404

    # Роли сценария сменились — продолжить чат нельзя, пока сценарий не сброшен.
    chat_id = await scenario_chat(kim, it_only["id"])
    await admin.request(
        "PUT", f"/api/admin/scenarios/{it_only['id']}", json=spec(it_only["code"], roles=["legal"])
    )
    blocked = await kim.post(f"/api/chats/{chat_id}/messages", json={"content": "Привет"})
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "scenario_unavailable"
    reset = await kim.request("PATCH", f"/api/chats/{chat_id}", json={"scenario_id": None})
    assert reset.status_code == 200
    answer, _ = await ask(kim, chat_id, "Привет")
    assert "fake-llm" in answer


async def test_scenario_prompt_tools_kb_thinking_and_model_apply(stand: Any) -> None:
    app, admin, kim, _ = stand
    marker = uniq("МАРКЕР").upper()
    bases = {}
    for code in (uniq("scenario-kb"), uniq("other-kb")):
        response = await admin.post(
            "/api/admin/kb", json={"code": code, "name": code, "level": "global", "role_ids": []}
        )
        bases[code] = response.json()["id"]
        doc = await admin.post(
            f"/api/admin/kb/{bases[code]}/documents",
            files={"file": (f"{code}.md", f"# {code}\n\nТекст {marker} базы {code}.".encode())},
        )
        assert doc.json()["status"] == "ready"
    scenario_kb, other_kb = list(bases)

    scenario = await create(
        admin,
        spec(
            uniq("legal-like"),
            tools=["search_knowledge_base"],
            knowledge_bases=[scenario_kb],
            thinking_default=True,
        ),
    )
    chat_id = await scenario_chat(kim, scenario["id"])
    answer, message_id = await ask(kim, chat_id, "[[scenario:find]] «Сценарий-маркер»")
    # Промпт сценария отрендерен: название и обращение к пользователю.
    assert answer == (f"Нашёл в документе: Сценарий-маркер {scenario['name']} для Александр.")
    trace, row = await trace_of(app, message_id)
    assert trace["scenario"] == scenario["code"]
    # ∩ с инструментами сценария; скрытый репорт (§9.6) сценарий не убирает.
    assert trace["tools_offered"] == ["report_incident", "search_knowledge_base"]
    assert row.thinking is True  # thinking_default сценария
    searched = {c["document_id"] for c in trace["rag"]["candidates"]}
    async with app.state.db_sessions() as db:
        from app.modules.kb.models import KbDocument

        kb_of = {
            str(d.id): str(d.kb_id)
            for d in (await db.scalars(select(KbDocument))).all()
            if str(d.id) in searched
        }
    assert set(kb_of.values()) == {bases[scenario_kb]}  # база сценария сужает поиск

    # Модель и режим RAG сценария; thinking можно выключить вручную.
    await admin.request(
        "PUT",
        f"/api/admin/scenarios/{scenario['id']}",
        json=spec(scenario["code"], model_role="utility", rag_mode="off", tools=[]),
    )
    _, message_id = await ask(kim, chat_id, "Ещё вопрос", thinking=False)
    trace, row = await trace_of(app, message_id)
    assert row.model == "fake-utility" and row.thinking is False
    assert trace["rag_mode"] == "off" and "rag" not in trace and trace["tools_offered"] == []
    assert other_kb  # вторая база существовала, но в поиск не попала


async def test_edit_applies_without_restart_and_is_audited(stand: Any) -> None:
    app, admin, kim, _ = stand
    scenario = await create(admin, spec(uniq("live")))
    chat_id = await scenario_chat(kim, scenario["id"])
    first, _ = await ask(kim, chat_id, "[[scenario:find]] «Версия»")
    assert first == "В документах нет «Версия»."

    body = spec(scenario["code"], prompt_template="Версия промпта номер два.")
    response = await admin.request("PUT", f"/api/admin/scenarios/{scenario['id']}", json=body)
    assert response.status_code == 200
    second, _ = await ask(kim, chat_id, "[[scenario:find]] «Версия»")
    assert second == "Нашёл в документе: Версия промпта номер два."

    async with app.state.db_sessions() as db:
        entry = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "scenario.update", AuditLog.target_id == scenario["id"]
            )
        )
    assert entry is not None and "prompt_template" in entry.details["changed"]


async def test_editor_validation(stand: Any) -> None:
    _, admin, kim, _ = stand
    code = uniq("bad")
    for body, error in (
        (spec(code, prompt_template="{{ user."), "bad_template"),
        (spec(code, tools=["no_such_tool"]), "bad_tools"),
        (spec(code, model_role="nope"), "bad_model"),
        (spec(code, icon="skull"), "bad_icon"),
    ):
        response = await admin.post("/api/admin/scenarios", json=body)
        assert response.status_code == 422 and response.json()["error"]["code"] == error
    options = (await admin.get("/api/admin/scenarios/options")).json()
    assert "search_knowledge_base" in options["tools"] and "chat" in options["model_roles"]
    assert "user.address" in options["variables"]
    assert (await kim.get("/api/admin/scenarios")).status_code == 403


async def test_requires_attachment(stand: Any) -> None:
    _, admin, kim, _ = stand
    scenario = await create(
        admin,
        spec(uniq("needs-file"), requires_attachment=True, attachment_hint="Приложите договор"),
    )
    chat_id = await scenario_chat(kim, scenario["id"])
    response = await kim.post(f"/api/chats/{chat_id}/messages", json={"content": "Проверь"})
    assert response.status_code == 422
    assert response.json()["error"] == {
        **response.json()["error"],
        "code": "attachment_required",
        "message": "Приложите договор",
    }
    upload = await kim.post(
        "/api/files", files={"file": ("договор.md", "# Договор\n\nТекст.".encode(), "text/plain")}
    )
    answer, _ = await ask(kim, chat_id, "Проверь", attachment_ids=[upload.json()["id"]])
    assert answer
    # Дальше файл уже в чате — следующие вопросы без нового вложения.
    again, _ = await ask(kim, chat_id, "А сроки?")
    assert again


async def test_editor_test_chat_ignores_roles_and_stays_out_of_history(stand: Any) -> None:
    _, admin, _, _ = stand
    scenario = await create(
        admin, spec(uniq("hidden"), roles=["legal"], is_active=False)
    )  # у ivanov роли legal нет, сценарий выключен
    response = await admin.post(f"/api/admin/scenarios/{scenario['id']}/test-chat")
    assert response.status_code == 201
    chat_id = response.json()["chat_id"]
    answer, _ = await ask(admin, chat_id, "[[scenario:find]] «Сценарий-маркер»")
    assert answer.startswith("Нашёл в документе: Сценарий-маркер")
    detail = (await admin.get(f"/api/chats/{chat_id}")).json()
    assert detail["is_test"] is True and detail["scenario"]["id"] == scenario["id"]
    listed = (await admin.get("/api/chats")).json()["items"]
    assert chat_id not in {c["id"] for c in listed}
