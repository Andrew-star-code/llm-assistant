from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import LdapSettings
from app.core.errors import AppError
from app.core.pagination import decode_cursor, encode_cursor
from app.core.storage import LocalStorage
from app.modules.auth.providers.base import AuthFailure, DirectoryUser
from app.modules.auth.providers.dev import DevProvider
from app.modules.auth.providers.ldap import LdapDirectory, classify_bind_error
from app.modules.auth.service import normalize_login
from app.modules.rbac.compute import compute_directory_roles
from app.modules.users import naming


def _norm(raw: str) -> str:
    return normalize_login(raw, netbios_domain="CORP", upn_suffix="corp.local")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ivanov", "ivanov"),
        ("  Ivanov ", "ivanov"),
        ("CORP\\ivanov", "ivanov"),
        ("corp\\IVANOV", "ivanov"),
        ("ivanov@corp.local", "ivanov"),
        ("ivanov@CORP.LOCAL", "ivanov"),
        ("i.ivanov-2", "i.ivanov-2"),
        ("Иванов", "иванов"),
    ],
)
def test_normalize_login(raw: str, expected: str) -> None:
    assert _norm(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "OTHER\\ivanov", "ivanov@evil.local", "*", "iv*nov", "a)(b", "ivanov\x00", "-x", "a b"],
)
def test_normalize_login_rejects(raw: str) -> None:
    with pytest.raises(AuthFailure) as exc:
        _norm(raw)
    assert exc.value.reason == "invalid_login"


def test_user_filter_escapes_values() -> None:
    """Вторая линия защиты: даже если в логин попадут спецсимволы, фильтр их экранирует."""
    from ldap3.utils.conv import escape_filter_chars

    settings = LdapSettings()
    query = settings.user_filter.format(username=escape_filter_chars("a*)(cn=*"))
    assert query.endswith("(sAMAccountName=a\\2a\\29\\28cn=\\2a))")


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("80090308: LdapErr: AcceptSecurityContext error, data 52e, v1db1", "bad_credentials"),
        ("... data 533, v1db1", "ad_disabled"),
        ("... data 775, v1db1", "ad_locked"),
        ("... data 773, v1db1", "password_expired"),
        ("Invalid credentials", "bad_credentials"),
    ],
)
def test_classify_bind_error(message: str, reason: str) -> None:
    assert classify_bind_error(message) == reason


def test_access_group_is_case_insensitive() -> None:
    directory = LdapDirectory(
        LdapSettings(access_group="CN=AI-Assistant-Users,CN=Users,DC=corp,DC=local")
    )
    user = DirectoryUser(
        guid="g", login="x", groups=["cn=ai-assistant-users,cn=users,dc=corp,dc=local"]
    )
    assert directory.in_access_group(user)
    assert not directory.in_access_group(DirectoryUser(guid="g", login="x"))
    assert LdapDirectory(LdapSettings()).in_access_group(DirectoryUser(guid="g", login="x"))


@pytest.mark.parametrize(
    ("display", "pattern", "expected"),
    [
        ("Иванов Иван Петрович", "{last} {first} {middle}", "Петрович"),
        ("Иванов  Иван   Петрович", "{last} {first} {middle}", "Петрович"),
        ("Иван Петрович Иванов", "{first} {middle} {last}", "Петрович"),
        ("Иванов Иван", "{last} {first} {middle}", None),
        ("Петров Иван Петрович", "{last} {first} {middle}", None),  # фамилия не совпала
        (None, "{last} {first} {middle}", None),
        ("Иванов Иван Петрович", "{last} {first}", None),
    ],
)
def test_middle_from_display_name(display: str | None, pattern: str, expected: str | None) -> None:
    assert naming.middle_from_display_name(display, pattern, "Иванов", "Иван") == expected


@pytest.mark.parametrize(
    ("form", "middle", "expected"),
    [
        ("name_patronymic", "Петрович", "Иван Петрович"),
        ("name_patronymic", None, "Иван"),
        ("first_name", "Петрович", "Иван"),
        ("full_name", "Петрович", "Иванов Иван Петрович"),
        ("formal", "Петрович", None),
    ],
)
def test_address_forms(form: naming.AddressForm, middle: str | None, expected: str | None) -> None:
    assert naming.address(form, "Иванов", "Иван", middle) == expected


def test_compute_directory_roles() -> None:
    settings = LdapSettings.model_validate(
        {
            "department_roles": {
                "auto": True,
                "rules": [
                    {"attribute": "department", "equals": "юридический отдел", "roles": ["legal"]},
                    {"attribute": "title", "contains": "руководитель", "roles": ["management"]},
                ],
            },
            "group_roles": [
                {"group_dn": "CN=AI-Admins,CN=Users,DC=corp,DC=local", "roles": ["it"]}
            ],
        }
    )
    roles = compute_directory_roles(
        {"department": "Юридический  отдел", "title": "Руководитель отдела"},
        ["cn=ai-admins,cn=users,dc=corp,dc=local"],
        settings,
    )
    assert [(r.code, r.name, r.kind) for r in roles] == [
        ("dept:Юридический отдел", "Отдел: Юридический отдел", "department"),
        ("management", "management", "custom"),
        ("it", "it", "custom"),
    ]
    # equals сравнивает значение как есть (без схлопывания пробелов) — правило не сработало.
    assert compute_directory_roles({}, [], settings) == []


async def test_dev_provider() -> None:
    from app.core.config import DevUser

    provider = DevProvider(
        [
            DevUser(login="boss", last_name="Иванов", first_name="Иван", middle_name="Петрович"),
            DevUser(login="kim", last_name="Ким", first_name="Александр", manager="boss"),
        ]
    )
    user = await provider.authenticate("kim", "")
    assert user.guid == "dev:kim" and user.manager_name == "Иванов Иван Петрович"
    with pytest.raises(AuthFailure):
        await provider.authenticate("nobody", "")


async def test_local_storage(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    await storage.put("photos/abc", b"data")
    assert await storage.get("photos/abc") == b"data"
    await storage.delete("photos/abc")
    assert await storage.get("photos/abc") is None
    for bad in ("../etc/passwd", "photos/../../x", "/abs/path", "photos"):
        with pytest.raises(ValueError, match="недопустимый ключ"):
            await storage.put(bad, b"x")


def test_cursor_roundtrip() -> None:
    cursor = encode_cursor("Иванов", 42)
    assert decode_cursor(cursor) == ("Иванов", "42")
    with pytest.raises(AppError):
        decode_cursor("@@@")
