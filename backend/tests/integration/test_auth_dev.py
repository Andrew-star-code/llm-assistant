"""Вход провайдером dev, сессии, CSRF, профиль, уведомление при первом входе (этап 1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.modules.security.models import LoginEvent
from tests.integration.conftest import Infra, make_settings


async def test_login_sets_session_and_csrf_cookies(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    _, client = await make_client(make_settings(infra, tmp_path))
    response = await client.login("petrov")
    assert response.status_code == 200, response.text
    me = response.json()
    assert me["full_name"] == "Петров Сергей Алексеевич"
    assert me["address"] == "Сергей Алексеевич"
    assert me["notice"]["required"] is True
    cookies = response.headers.get_list("set-cookie")
    sid = next(c for c in cookies if c.startswith("sid="))
    assert "HttpOnly" in sid and "SameSite=lax" in sid
    assert any(c.startswith("csrftoken=") and "HttpOnly" not in c for c in cookies)

    assert (await client.get("/api/auth/me")).status_code == 200
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_unsafe_request_without_csrf_is_rejected(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    _, client = await make_client(make_settings(infra, tmp_path))
    response = await client.http.post(
        "/api/auth/login", json={"login": "petrov", "provider": "dev"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"

    await client.login("petrov")
    # Токен из cookie до входа больше не подходит: после входа он привязан к сессии.
    wrong = await client.http.post("/api/auth/logout", headers={"X-CSRF-Token": "forged"})
    assert wrong.status_code == 403


async def test_unknown_user_gets_generic_error_and_journal_has_reason(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    app, client = await make_client(make_settings(infra, tmp_path))
    response = await client.login("nobody")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Неверный логин или пароль"
    async with app.state.db_sessions() as db:
        event = await db.scalar(select(LoginEvent).where(LoginEvent.login_attempted == "nobody"))
    assert event is not None and event.success is False
    assert event.failure_reason == "user_not_found"


async def test_ldap_provider_not_enabled(make_client: Any, infra: Infra, tmp_path: Path) -> None:
    _, client = await make_client(make_settings(infra, tmp_path))
    response = await client.login("petrov", "x", provider="ldap")
    assert response.status_code == 401


async def test_notice_profile_and_settings(make_client: Any, infra: Infra, tmp_path: Path) -> None:
    _, client = await make_client(make_settings(infra, tmp_path))
    await client.login("petrov")
    assert (await client.post("/api/auth/notice/accept")).status_code == 204
    assert (await client.get("/api/auth/me")).json()["notice"]["required"] is False

    profile = (await client.get("/api/profile")).json()
    assert profile["department"] == "Бухгалтерия"
    assert profile["manager_name"] == "Иванов Иван Петрович"
    assert {r["code"] for r in profile["roles"]} == {"dept:Бухгалтерия"}
    assert profile["address_form"] == "name_patronymic"
    assert profile["address_form_is_default"] is True

    updated = await client.request(
        "PATCH", "/api/profile/settings", json={"address_form": "full_name", "theme": "dark"}
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["address"] == "Петров Сергей Алексеевич"
    assert body["settings"]["theme"] == "dark"

    reset = await client.request("PATCH", "/api/profile/settings", json={"address_form": None})
    assert reset.json()["address_form_is_default"] is True
    assert reset.json()["settings"]["theme"] == "dark"
    assert (await client.get("/api/profile/photo")).status_code == 404


async def test_user_without_middle_name_is_addressed_by_first_name(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    _, client = await make_client(make_settings(infra, tmp_path))
    me = (await client.login("kim")).json()
    assert me["full_name"] == "Ким Александр"
    assert me["address"] == "Александр"


async def test_department_role_and_attribute_rule(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    """Роль отдела создаётся автоматически; правило config/app.yaml «содержит ИТ» даёт роль it."""
    _, client = await make_client(make_settings(infra, tmp_path))
    me = (await client.login("kim")).json()
    assert {(r["code"], r["name"], r["source"]) for r in me["roles"]} == {
        ("dept:ИТ-отдел", "Отдел: ИТ-отдел", "ad"),
        ("it", "it", "ad"),
    }
