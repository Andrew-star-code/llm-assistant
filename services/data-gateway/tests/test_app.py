"""HTTP API шлюза с источником SQLite: подпись, каталог по ролям, функции, запросы, RLS."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from data_gateway.app import GatewaySettings, create_app
from data_gateway.identity import Identity, sign
from fastapi.testclient import TestClient

SECRET = "test-secret-0123456789"
PETROV = Identity(user_id="u1", login="petrov", roles=frozenset({"dept:Бухгалтерия"}),
                  department="Бухгалтерия")  # fmt: skip

SALARIES: dict[str, Any] = {
    "name": "salaries_by_dept", "title": "Сотрудники отдела", "description": "Только свой отдел",
    "source": "mssql_main", "view": "dbo.v_dept_staff", "roles": [],
    "columns": [{"name": "full_name"}, {"name": "department"}],
    "rls": [{"column": "department", "equals": "{user.department}", "unless_roles": ["hr"]}],
}  # fmt: skip


MakeCatalog = Callable[..., Path]


@pytest.fixture
def client(tmp_path: Path, catalog_factory: MakeCatalog) -> TestClient:
    settings = GatewaySettings(catalog_dir=catalog_factory(tmp_path), secret=SECRET)
    return TestClient(create_app(settings))


def _headers(identity: Identity = PETROV, secret: str = SECRET) -> dict[str, str]:
    return sign(identity, secret)


def test_identity_signature_is_required(client: TestClient) -> None:
    with client:
        assert client.get("/v1/catalog").status_code == 401
        forged = client.get("/v1/catalog", headers=_headers(secret="wrong-secret-0000000"))
        assert forged.status_code == 401 and forged.json()["error"]["code"] == "unauthenticated"
        old = sign(PETROV, SECRET, now=0)
        assert client.get("/v1/catalog", headers=old).status_code == 401
        assert client.get("/v1/catalog", headers=_headers()).status_code == 200


def test_search_employees_function(client: TestClient) -> None:
    with client:
        response = client.post(
            "/v1/functions/search_employees",
            json={"params": {"query": "Петров", "department": "Бухгалтерия"}},
            headers=_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["columns"][:3] == ["full_name", "position", "department"]
        assert [r[0] for r in body["rows"]] == ["Петров Сергей Алексеевич"]
        assert body["rows"][0][3] == "+7 (495) 100-20-02"
        assert body["sql"].startswith("SELECT TOP (:limit)")
        assert body["params"] == {"query": "Петров", "department": None, "limit": 20} | {
            "department": "Бухгалтерия"
        }
        everyone = client.post(
            "/v1/functions/search_employees", json={"params": {"query": "Петров"}},
            headers=_headers(),
        )  # fmt: skip
        # Петров, Петрова и Иванов Иван Петрович (часть ФИО — и в отчестве).
        assert len(everyone.json()["rows"]) == 3
        bad = client.post(
            "/v1/functions/search_employees", json={"params": {"query": "x"}}, headers=_headers()
        )
        assert bad.status_code == 400 and "не короче 2" in bad.json()["error"]["message"]
        assert client.post("/v1/functions/nope", json={}, headers=_headers()).status_code == 404


def test_query_rejects_changes_and_applies_limit(client: TestClient) -> None:
    with client:
        ok = client.post(
            "/v1/query",
            json={"sql": "SELECT department, COUNT(*) AS n FROM dbo.v_phonebook "
                         "GROUP BY department ORDER BY n DESC"},
            headers=_headers(),
        )  # fmt: skip
        assert ok.status_code == 200, ok.text
        rows = {r[0]: r[1] for r in ok.json()["rows"]}
        assert rows["Бухгалтерия"] == 2 and rows["ИТ-отдел"] == 2
        assert ok.json()["sql"].startswith("SELECT TOP 1000 department")
        for sql in ("DELETE FROM dbo.v_phonebook", "SELECT salary FROM dbo.v_phonebook"):
            response = client.post("/v1/query", json={"sql": sql}, headers=_headers())
            assert response.status_code == 400 and response.json()["error"]["code"] == "rejected"
        # Данные на месте — изменение не прошло.
        again = client.post(
            "/v1/query", json={"sql": "SELECT COUNT(*) AS n FROM dbo.v_phonebook"},
            headers=_headers(),
        )  # fmt: skip
        assert again.json()["rows"] == [[6]]
        broken = client.post(
            "/v1/query",
            json={"sql": "SELECT full_name FROM dbo.v_phonebook WHERE full_name > 1/0"},
            headers=_headers(),
        )  # fmt: skip
        assert broken.status_code in (200, 422)  # SQLite делит на ноль без ошибки


def test_rls_filters_rows_by_department(tmp_path: Path, catalog_factory: MakeCatalog) -> None:
    settings = GatewaySettings(
        catalog_dir=catalog_factory(tmp_path, extra_datasets=[SALARIES]), secret=SECRET
    )
    with TestClient(create_app(settings)) as client:
        sql = {"sql": "SELECT full_name, department FROM dbo.v_dept_staff ORDER BY full_name"}
        response = client.post("/v1/query", json=sql, headers=_headers())
        body = response.json()
        assert response.status_code == 200, response.text
        assert body["rls"] == ["salaries_by_dept"] and body["params"] == {"rls_0": "Бухгалтерия"}
        assert [r[0] for r in body["rows"]] == [
            "Петров Сергей Алексеевич",
            "Смирнова Анна Викторовна",
        ]
        assert "WHERE department = :rls_0" in body["sql"]
        # Роль-исключение видит всех.
        hr = Identity(user_id="h", login="hr", roles=frozenset({"hr"}), department="Бухгалтерия")
        assert len(client.post("/v1/query", json=sql, headers=_headers(hr)).json()["rows"]) == 6


def test_catalog_by_roles_describe_and_admin_view(
    tmp_path: Path, catalog_factory: MakeCatalog
) -> None:
    restricted = {**SALARIES, "name": "hr_only", "view": "hr.v_x", "roles": ["hr"], "rls": []}
    settings = GatewaySettings(
        catalog_dir=catalog_factory(tmp_path, extra_datasets=[restricted]), secret=SECRET
    )
    with TestClient(create_app(settings)) as client:
        names = {
            d["name"] for d in client.get("/v1/catalog", headers=_headers()).json()["datasets"]
        }
        assert names == {"phonebook"}
        assert client.get("/v1/datasets/hr_only", headers=_headers()).status_code == 404
        described = client.get(
            "/v1/datasets/phonebook", params={"question": "телефон"}, headers=_headers()
        ).json()
        assert described["view"] == "dbo.v_phonebook" and len(described["examples"]) <= 5
        assert any(c["name"] == "phone" and c["pii"] for c in described["columns"])
        admin = Identity(user_id="a", login="ivanov", roles=frozenset(), admin=True)
        full = client.get("/v1/catalog", headers=_headers(admin)).json()
        assert {d["name"] for d in full["datasets"]} == {"phonebook", "hr_only"}
        assert full["functions"][0]["sql"].startswith("SELECT TOP (:limit)")
