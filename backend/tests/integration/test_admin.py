"""RBAC и админка: доступ по правам, блокировка, разлогин, роли, аудит (этап 1, §13, §18.2)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.modules.admin.router import router as admin_router
from app.modules.audit.models import AuditLog
from tests.integration.conftest import ApiClient, Infra, make_settings


async def _user_id(admin: ApiClient, login: str) -> str:
    page = (await admin.get("/api/admin/users", params={"q": login})).json()
    return str(next(u["id"] for u in page["items"] if u["login"] == login))


async def test_bootstrap_admin_sees_admin_and_ordinary_user_gets_403(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    settings = make_settings(infra, tmp_path)
    _, admin = await make_client(settings)
    _, user = await make_client(settings)

    me = (await admin.login("ivanov")).json()
    assert "superadmin" in {r["code"] for r in me["roles"]}
    assert "admin.access" in me["permissions"]
    assert (await admin.get("/api/admin/users")).status_code == 200

    me_user = (await user.login("petrov")).json()
    assert me_user["permissions"] == []
    response = await user.get("/api/admin/users")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def _admin_routes() -> list[APIRoute]:
    from app.modules.incidents.router import router as incidents_router
    from app.modules.kb.admin_router import router as kb_admin_router
    from app.modules.scenarios.admin_router import router as scenarios_admin_router

    routers = (admin_router, kb_admin_router, incidents_router, scenarios_admin_router)
    return [r for router in routers for r in router.routes if isinstance(r, APIRoute)]


async def test_every_admin_endpoint_requires_permission(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    """§18.2: каждый админ-эндпоинт требует своего права; обычный пользователь получает 403."""
    app, user = await make_client(make_settings(infra, tmp_path))
    routes = _admin_routes()
    assert len(routes) >= 10
    for route in routes:
        deps = [d.call for d in route.dependant.dependencies]
        assert any(hasattr(d, "required_permissions") for d in deps), route.path
    # Все админ-маршруты действительно опубликованы под /api/admin.
    published = {p for p in app.openapi()["paths"] if p.startswith("/api/admin")}
    assert published == {f"/api{r.path}" for r in routes}

    await user.login("petrov")
    dummy = str(uuid.uuid4())
    for route in routes:
        path = "/api" + re.sub(r"\{[a-z_]+\}", dummy, route.path)
        for method in route.methods or set():
            body = {"reason": "x", "role_ids": [], "login": "x"}
            response = await user.request(method, path, json=body)
            assert response.status_code == 403, (method, path, response.text)


async def test_block_revokes_sessions_and_prevents_login(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    settings = make_settings(infra, tmp_path)
    app, admin = await make_client(settings)
    _, user = await make_client(settings)
    await admin.login("ivanov")
    await user.login("petrov")
    assert (await user.get("/api/auth/me")).status_code == 200

    petrov_id = await _user_id(admin, "petrov")
    response = await admin.post(
        f"/api/admin/users/{petrov_id}/block", json={"reason": "Увольнение"}
    )
    assert response.status_code == 200
    assert response.json()["revoked"] == 1
    assert (await user.get("/api/auth/me")).status_code == 401
    assert (await user.login("petrov")).status_code == 401

    card = (await admin.get(f"/api/admin/users/{petrov_id}")).json()
    assert card["is_blocked"] is True and card["blocked_reason"] == "Увольнение"
    assert card["recent_logins"][0]["failure_reason"] == "blocked"

    assert (await admin.post(f"/api/admin/users/{petrov_id}/unblock")).status_code == 204
    assert (await user.login("petrov")).status_code == 200

    audit = (await admin.get("/api/admin/audit")).json()["items"]
    actions = [a["action"] for a in audit]
    assert actions[:2] == ["user.unblock", "user.block"]
    assert audit[1]["actor_name"] == "Иванов Иван Петрович"

    # Журнал аудита — только вставка (§13.6).
    async with app.state.db_sessions() as db:
        with pytest.raises(DBAPIError, match="запрещены"):
            await db.execute(text("UPDATE audit_log SET action = 'x'"))
        await db.rollback()
        assert len((await db.scalars(select(AuditLog))).all()) == 2


async def test_admin_cannot_block_self(make_client: Any, infra: Infra, tmp_path: Path) -> None:
    _, admin = await make_client(make_settings(infra, tmp_path))
    me = (await admin.login("ivanov")).json()
    response = await admin.post(f"/api/admin/users/{me['id']}/block", json={"reason": "x"})
    assert response.status_code == 400


async def test_logout_user_and_revoke_session(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    settings = make_settings(infra, tmp_path)
    _, admin = await make_client(settings)
    _, user = await make_client(settings)
    await admin.login("ivanov")
    await user.login("kim")
    kim_id = await _user_id(admin, "kim")

    card = (await admin.get(f"/api/admin/users/{kim_id}")).json()
    assert len(card["sessions"]) == 1
    session_id = card["sessions"][0]["id"]
    assert (await admin.request("DELETE", f"/api/admin/sessions/{session_id}")).status_code == 204
    assert (await user.get("/api/auth/me")).status_code == 401

    await user.login("kim")
    response = await admin.post(f"/api/admin/users/{kim_id}/logout")
    assert response.json() == {"revoked": 1}
    assert (await user.get("/api/auth/me")).status_code == 401


async def test_manual_roles_and_admin_role_protection(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    settings = make_settings(infra, tmp_path)
    _, superadmin = await make_client(settings)
    _, admin = await make_client(settings)
    await superadmin.login("ivanov")
    roles = {r["code"]: r for r in (await superadmin.get("/api/admin/roles")).json()}
    assert {"superadmin", "admin", "kb_manager"} <= roles.keys()
    assert "admin.admins.manage" not in roles["admin"]["permissions"]

    _, petrov = await make_client(settings)
    await petrov.login("petrov")
    await admin.login("kim")
    petrov_id = await _user_id(superadmin, "petrov")
    kim_id = await _user_id(superadmin, "kim")
    response = await superadmin.request(
        "PUT", f"/api/admin/users/{kim_id}/roles", json={"role_ids": [roles["admin"]["id"]]}
    )
    assert response.status_code == 200
    assert "admin" in {r["code"] for r in response.json()["roles"]}

    # Обычный admin не может выдавать админские роли — только superadmin.
    await admin.login("kim")
    forbidden = await admin.request(
        "PUT", f"/api/admin/users/{petrov_id}/roles", json={"role_ids": [roles["admin"]["id"]]}
    )
    assert forbidden.status_code == 403
    dept = await admin.request(
        "PUT",
        f"/api/admin/users/{petrov_id}/roles",
        json={"role_ids": [roles["dept:ИТ-отдел"]["id"]]},
    )
    assert dept.status_code == 400

    audit = (await superadmin.get("/api/admin/audit", params={"action": "user.roles"})).json()
    assert audit["items"][0]["details"] == {"added": ["admin"], "removed": []}


async def test_users_search_and_pagination(make_client: Any, infra: Infra, tmp_path: Path) -> None:
    settings = make_settings(infra, tmp_path)
    _, admin = await make_client(settings)
    for login in ("kim", "petrov"):
        _, c = await make_client(settings)
        await c.login(login)
    await admin.login("ivanov")

    first = (await admin.get("/api/admin/users", params={"limit": 2})).json()
    assert [u["login"] for u in first["items"]] == ["ivanov", "kim"]
    second = (
        await admin.get("/api/admin/users", params={"limit": 2, "cursor": first["next_cursor"]})
    ).json()
    assert [u["login"] for u in second["items"]] == ["petrov"]
    assert second["next_cursor"] is None
    found = (await admin.get("/api/admin/users", params={"q": "бухгалт"})).json()
    assert [u["login"] for u in found["items"]] == ["petrov"]

    logins = (await admin.get("/api/admin/logins", params={"success": True})).json()
    assert {e["login_attempted"] for e in logins["items"]} == {"ivanov", "kim", "petrov"}
