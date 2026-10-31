"""Вход через AD (mock-AD, Samba AD DC) — критерии приёмки этапа 1 (§19) и тесты §18.2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.cli.ad import format_report, make_directory
from app.modules.auth.diagnostics import run_diagnostics_sync
from app.modules.security.models import LoginEvent
from app.modules.users.models import User
from app.modules.users.sync import sync_all
from tests.integration.conftest import (
    USER_PASSWORD,
    ApiClient,
    Infra,
    MockAd,
    ldap_overrides,
    make_settings,
)

ACCESS_GROUP = "CN=AI-Assistant-Users,CN=Users,DC=corp,DC=local"


async def _reasons(app: Any, login: str) -> list[str | None]:
    async with app.state.db_sessions() as db:
        rows = await db.scalars(
            select(LoginEvent.failure_reason)
            .where(LoginEvent.login_attempted == login)
            .order_by(LoginEvent.ts)
        )
        return list(rows.all())


async def _ldap_client(
    make_client: Any, infra: Infra, ad: MockAd, tmp_path: Path, **ldap: Any
) -> tuple[Any, ApiClient]:
    app, client = await make_client(make_settings(infra, tmp_path, **ldap_overrides(ad, **ldap)))
    return app, client


async def test_login_profile_photo_and_roles(
    make_client: Any, infra: Infra, mock_ad: MockAd, tmp_path: Path
) -> None:
    """Вход пользователем mock-AD; профиль: ФИО, должность, отдел, телефоны, руководитель, фото."""
    _, client = await _ldap_client(make_client, infra, mock_ad, tmp_path)
    response = await client.login("kim", USER_PASSWORD, provider="ldap")
    assert response.status_code == 200, response.text
    profile = (await client.get("/api/profile")).json()
    assert profile["full_name"] == "Ким Александр"
    assert profile["middle_name"] is None
    assert profile["address"] == "Александр"
    assert profile["title"] == "Инженер технической поддержки"
    assert profile["department"] == "ИТ-отдел"
    assert profile["phone"] == "+7 (495) 100-10-02"
    assert profile["mobile"] == "+7 (900) 100-10-02"
    assert profile["manager_name"] == "Иванов Иван Петрович"
    assert profile["company"] == "ООО «Корпорация»"
    # Автоматическая роль отдела.
    assert "dept:ИТ-отдел" in {r["code"] for r in profile["roles"]}
    photo = await client.get("/api/profile/photo")
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/jpeg"
    assert photo.content.startswith(b"\xff\xd8")


@pytest.mark.parametrize("login", ["sidorova", "CORP\\sidorova", "Sidorova@corp.local"])
async def test_login_formats_and_rule_role(
    make_client: Any, infra: Infra, mock_ad: MockAd, tmp_path: Path, login: str
) -> None:
    _, client = await _ldap_client(make_client, infra, mock_ad, tmp_path)
    me = (await client.login(login, USER_PASSWORD, provider="ldap")).json()
    assert me["login"] == "sidorova"
    assert me["address"] == "Елена Николаевна"
    assert {"dept:Юридический отдел", "legal"} <= {r["code"] for r in me["roles"]}


async def test_bootstrap_admin_from_ad(
    make_client: Any, infra: Infra, mock_ad: MockAd, tmp_path: Path
) -> None:
    _, client = await _ldap_client(make_client, infra, mock_ad, tmp_path)
    me = (await client.login("ivanov", USER_PASSWORD, provider="ldap")).json()
    assert "superadmin" in {r["code"] for r in me["roles"]}
    assert (await client.get("/api/admin/users")).status_code == 200


async def test_disabled_user_cannot_log_in(
    make_client: Any, infra: Infra, mock_ad: MockAd, tmp_path: Path
) -> None:
    app, client = await _ldap_client(make_client, infra, mock_ad, tmp_path)
    response = await client.login("kuznetsov", USER_PASSWORD, provider="ldap")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Неверный логин или пароль"
    assert await _reasons(app, "kuznetsov") == ["ad_disabled"]


async def test_empty_password_rejected_before_ad(
    make_client: Any, infra: Infra, mock_ad: MockAd, tmp_path: Path
) -> None:
    app, client = await _ldap_client(make_client, infra, mock_ad, tmp_path)
    response = await client.login("ivanov", "", provider="ldap")
    assert response.status_code == 401
    assert await _reasons(app, "ivanov") == ["empty_password"]


async def test_access_group_with_nesting(
    make_client: Any, infra: Infra, mock_ad: MockAd, tmp_path: Path
) -> None:
    app, client = await _ldap_client(
        make_client, infra, mock_ad, tmp_path, access_group=ACCESS_GROUP
    )
    assert (await client.login("volkov", USER_PASSWORD, provider="ldap")).status_code == 401
    assert await _reasons(app, "volkov") == ["not_in_access_group"]
    # ivanov — только в AI-Admins, которая вложена в AI-Assistant-Users.
    assert (await client.login("ivanov", USER_PASSWORD, provider="ldap")).status_code == 200


async def test_sixth_failed_attempt_locks_login(
    make_client: Any, infra: Infra, mock_ad: MockAd, tmp_path: Path
) -> None:
    """5 неудач за 15 минут блокируют логин: шестая попытка отклоняется даже с верным паролем."""
    app, client = await _ldap_client(make_client, infra, mock_ad, tmp_path)
    for _ in range(5):
        assert (await client.login("petrov", "wrong", provider="ldap")).status_code == 401
    assert (await client.login("petrov", USER_PASSWORD, provider="ldap")).status_code == 401
    reasons = await _reasons(app, "petrov")
    assert reasons == ["bad_credentials"] * 5 + ["locked_login"]
    # Порог AD (10) не достигнут: блокировка — только у нас, доменная учётка цела.
    out = mock_ad.exec("samba-tool", "user", "show", "petrov", "--attributes=lockoutTime")
    assert "lockoutTime: 0" in out or "lockoutTime" not in out


async def test_ldap_injection_in_login_is_rejected(
    make_client: Any, infra: Infra, mock_ad: MockAd, tmp_path: Path
) -> None:
    app, client = await _ldap_client(make_client, infra, mock_ad, tmp_path)
    for login in ("*", "ivanov)(sAMAccountName=*", "iv*nov"):
        assert (await client.login(login, USER_PASSWORD, provider="ldap")).status_code == 401
    async with app.state.db_sessions() as db:
        reasons = set((await db.scalars(select(LoginEvent.failure_reason))).all())
    assert reasons == {"invalid_login"}


async def test_ad_diagnostics_report(infra: Infra, mock_ad: MockAd, tmp_path: Path) -> None:
    """``ad check`` выводит атрибуты, ФИО, форму обращения, отдел и роли."""
    settings = make_settings(infra, tmp_path, **ldap_overrides(mock_ad))
    directory = make_directory(settings)
    report = run_diagnostics_sync(directory, settings, "CORP\\ivanov", password=USER_PASSWORD)
    assert report.ok
    assert all(c.ok for c in report.controllers)
    assert report.service_bind.ok
    assert report.full_name == "Иванов Иван Петрович"
    assert report.middle_name_source == "attribute"
    assert report.address == "Иван Петрович"
    assert report.department == "ИТ-отдел"
    assert {(r.code, r.source) for r in report.roles} >= {
        ("dept:ИТ-отдел", "department"), ("it", "rule"), ("superadmin", "bootstrap"),
    }  # fmt: skip
    assert report.password_check is not None and report.password_check.ok
    text = format_report(report)
    for fragment in (
        "Иванов Иван Петрович",
        "Иван Петрович",
        "Отдел: ИТ-отдел",
        "Итог: вход возможен",
    ):
        assert fragment in text

    bad = run_diagnostics_sync(directory, settings, "ivanov", password="wrong")
    assert bad.password_check is not None and bad.password_check.error == "bad_credentials"
    assert not run_diagnostics_sync(directory, settings, "nobody").user_found


async def test_admin_ad_diagnostics_page_writes_audit(
    make_client: Any, infra: Infra, mock_ad: MockAd, tmp_path: Path
) -> None:
    _, client = await _ldap_client(make_client, infra, mock_ad, tmp_path)
    await client.login("ivanov", USER_PASSWORD, provider="ldap")
    report = (await client.post("/api/admin/ad/diagnostics", json={"login": "kim"})).json()
    assert report["user_found"] and report["address"] == "Александр"
    assert report["password_check"] is None
    audit = (await client.get("/api/admin/audit")).json()["items"]
    assert audit[0]["action"] == "ad.diagnostics" and audit[0]["target_id"] == "kim"


async def test_sync_blocks_and_logs_out_user_disabled_in_ad(
    make_client: Any, infra: Infra, mock_ad: MockAd, tmp_path: Path
) -> None:
    app, client = await _ldap_client(make_client, infra, mock_ad, tmp_path)
    assert (await client.login("smirnova", USER_PASSWORD, provider="ldap")).status_code == 200
    mock_ad.exec("samba-tool", "user", "disable", "smirnova")
    try:
        stats = await sync_all(
            app.state.db_sessions,
            app.state.ldap_directory,
            settings=app.state.settings,
            storage=app.state.storage,
            sessions=app.state.sessions,
        )
        assert stats.disabled == 1 and stats.errors == 0
        assert (await client.get("/api/auth/me")).status_code == 401
        async with app.state.db_sessions() as db:
            user = await db.scalar(select(User).where(User.login == "smirnova"))
            assert user is not None and user.ad_disabled
    finally:
        mock_ad.exec("samba-tool", "user", "enable", "smirnova")
    await sync_all(
        app.state.db_sessions, app.state.ldap_directory, settings=app.state.settings,
        storage=app.state.storage, sessions=app.state.sessions,
    )  # fmt: skip
    assert (await client.login("smirnova", USER_PASSWORD, provider="ldap")).status_code == 200
