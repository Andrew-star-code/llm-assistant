"""Админка «Роли» (решение 57): свои роли, массовое добавление по логинам и e-mail, снятие,
защита админских и отдельских ролей, удаление неиспользуемой роли, аудит.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.rbac.models import Role
from tests.integration.conftest import ApiClient, Infra, make_settings


async def _stand(make_client: Any, infra: Infra, tmp_path: Path) -> Any:
    settings = make_settings(infra, tmp_path)
    app, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    _, kim = await make_client(settings)
    for client, login in ((admin, "ivanov"), (petrov, "petrov"), (kim, "kim")):
        assert (await client.login(login)).status_code == 200
    return app, admin, petrov, kim


async def _role_id(app: Any, code: str) -> str:
    async with app.state.db_sessions() as db:
        return str(await db.scalar(select(Role.id).where(Role.code == code)))


async def _create(admin: ApiClient, code: str, name: str) -> dict[str, Any]:
    response = await admin.post("/api/admin/roles", json={"code": code, "name": name})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_custom_role_bulk_members_and_effect(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    app, admin, petrov, _ = await _stand(make_client, infra, tmp_path)
    bad = await admin.post("/api/admin/roles", json={"code": "Юристы", "name": "x"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "bad_code"
    role = await _create(admin, "Legal-Team", "Юристы")
    assert role["code"] == "legal-team" and role["editable"] and role["users"] == 0
    dup = await admin.post("/api/admin/roles", json={"code": "legal-team", "name": "x"})
    assert dup.status_code == 409

    # Столбец из Excel: логины в разном виде, дубль и неизвестный — одним запросом.
    added = await admin.post(
        f"/api/admin/roles/{role['id']}/members",
        json={"identifiers": ["petrov", "  KIM ", "CORP\\petrov", "nobody", ""]},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert sorted(u["login"] for u in body["added"]) == ["kim", "petrov"]
    assert body["already"] == [] and body["created"] == [] and body["not_found"] == ["nobody"]
    again = await admin.post(
        f"/api/admin/roles/{role['id']}/members", json={"identifiers": ["petrov"]}
    )
    assert [u["login"] for u in again.json()["already"]] == ["petrov"]
    page = (await admin.get(f"/api/admin/roles/{role['id']}/members")).json()
    assert {(m["login"], m["source"]) for m in page["items"]} == {
        ("kim", "manual"),
        ("petrov", "manual"),
    }
    assert (await admin.get(f"/api/admin/roles/{role['id']}")).json()["users"] == 2

    # Роль действует сразу: сценарий для неё виден её участникам.
    scenario = {
        "code": "legal-only", "name": "Для юристов", "description": "x", "icon": "sparkles",
        "roles": ["legal-team"], "model_role": "chat", "prompt_template": "x", "tools": None,
        "knowledge_bases": [], "rag_mode": "off", "requires_attachment": False,
        "starter_prompts": [], "thinking_default": None, "is_active": True, "sort_order": 0,
    }  # fmt: skip
    assert (await admin.post("/api/admin/scenarios", json=scenario)).status_code == 201
    assert "legal-only" in {s["code"] for s in (await petrov.get("/api/scenarios")).json()}

    # Снятие роли; удаление используемой роли запрещено, неиспользуемой — можно.
    kim_id = next(m["id"] for m in page["items"] if m["login"] == "kim")
    removed = await admin.post(
        f"/api/admin/roles/{role['id']}/members/remove", json={"user_ids": [kim_id]}
    )
    assert removed.json()["users"] == 1 and removed.json()["scenarios"] == ["Для юристов"]
    in_use = await admin.request("DELETE", f"/api/admin/roles/{role['id']}")
    assert in_use.status_code == 409 and "Для юристов" in in_use.json()["error"]["message"]
    spare = await _create(admin, "spare", "Запасная")
    assert (await admin.request("DELETE", f"/api/admin/roles/{spare['id']}")).status_code == 204

    async with app.state.db_sessions() as db:
        actions = (await db.scalars(select(AuditLog.action))).all()
    assert {"role.create", "role.members_add", "role.members_remove", "role.delete"} <= set(actions)


async def test_admin_and_department_roles_are_protected(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    app, admin, petrov, kim = await _stand(make_client, infra, tmp_path)
    department = await _role_id(app, "dept:Бухгалтерия")
    response = await admin.post(
        f"/api/admin/roles/{department}/members", json={"identifiers": ["kim"]}
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == "department_role"
    locked = await admin.request("PATCH", f"/api/admin/roles/{department}", json={"name": "x"})
    assert locked.status_code == 422

    # Обычный админ раздаёт пользовательские роли, но не админские.
    admin_role = await _role_id(app, "admin")
    granted = await admin.post(
        f"/api/admin/roles/{admin_role}/members", json={"identifiers": ["kim"]}
    )
    assert [u["login"] for u in granted.json()["added"]] == ["kim"]
    await kim.login("kim")
    superadmin = await _role_id(app, "superadmin")
    denied = await kim.post(f"/api/admin/roles/{superadmin}/members", json={"identifiers": ["kim"]})
    assert denied.status_code == 403
    custom = await _create(kim, "helpdesk", "Поддержка")
    ok = await kim.post(
        f"/api/admin/roles/{custom['id']}/members", json={"identifiers": ["petrov"]}
    )
    assert [u["login"] for u in ok.json()["added"]] == ["petrov"]
    # Пользователь без прав — 403.
    assert (await petrov.get(f"/api/admin/roles/{custom['id']}/members")).status_code == 403
