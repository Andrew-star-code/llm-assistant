"""Инциденты (этап 7, §13.5): system_error со стеком и логами запроса, группировка повторов,
жизненный цикл, комментарии, сводка для меню, права.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import structlog

from tests.integration.conftest import Infra, make_settings

log = structlog.stdlib.get_logger("app.test")


async def test_unhandled_error_creates_incident_with_stack_and_request_logs(
    make_client: Any, infra: Infra, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Критерий этапа 7: исключение → инцидент со стеком и логами; повтор — счётчик."""
    settings = make_settings(infra, tmp_path)
    _, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    await admin.login("ivanov")
    await petrov.login("petrov")

    from app.modules.users import router as users_router

    orders = iter((101, 202))

    def boom(*_: Any) -> None:
        order = next(orders)
        log.info("boom.prepare", order=order)  # строка лога этого запроса попадёт в инцидент
        raise RuntimeError(f"Сломалось на заказе {order}")

    monkeypatch.setattr(users_router, "build_profile", boom)

    first = await petrov.get("/api/profile")
    assert first.status_code == 500 and first.json()["error"]["code"] == "internal_error"
    request_id = first.json()["error"]["request_id"]
    # Другое число в сообщении — та же ошибка: счётчик, а не новый инцидент.
    assert (await petrov.get("/api/profile")).status_code == 500

    page = (await admin.get("/api/admin/incidents", params={"type": "system_error"})).json()
    [item] = page["items"]
    assert item["occurrences"] == 2 and item["severity"] == "high" and item["status"] == "new"
    assert item["user"]["login"] == "petrov"
    assert "RuntimeError" in item["title"] and "users/router.py" in item["title"]
    card = (await admin.get(f"/api/admin/incidents/{item['id']}")).json()
    payload = card["payload"]
    assert "Traceback" in payload["stack"] and "Сломалось на заказе 202" in payload["stack"]
    assert payload["method"] == "GET" and payload["path"] == "/api/profile"
    assert payload["endpoint"].endswith("/profile")
    assert any("boom.prepare" in line for line in payload["logs"])
    assert payload["recent_logs"] and payload["environment"]["pid"]
    assert request_id  # первый запрос тоже есть в логах процесса
    assert any(request_id in line for line in payload["recent_logs"])

    summary = (await admin.get("/api/admin/incidents/summary")).json()
    assert summary == {"new": 1, "new_high": 1, "open": 1}


async def test_incident_lifecycle_comments_and_permissions(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    settings = make_settings(infra, tmp_path)
    app, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    await admin.login("ivanov")
    await petrov.login("petrov")
    from app.modules.incidents import service

    for _ in range(2):
        await service.report(
            app.state.db_sessions, type="security", severity="warning",
            title="Перебор паролей", fingerprint="security:test",
        )  # fmt: skip
    [item] = (await admin.get("/api/admin/incidents")).json()["items"]
    url = f"/api/admin/incidents/{item['id']}"
    me = (await admin.get("/api/auth/me")).json()
    assignees = (await admin.get("/api/admin/incidents/assignees")).json()
    assert me["id"] in {a["id"] for a in assignees}

    taken = await admin.request(
        "PATCH", url, json={"status": "in_progress", "assigned_to": me["id"]}
    )
    assert taken.status_code == 200 and taken.json()["assignee"]["login"] == "ivanov"
    commented = await admin.post(f"{url}/comments", json={"text": "Проверяю журнал входов"})
    assert commented.status_code == 201
    assert [c["text"] for c in commented.json()["comments"]] == ["Проверяю журнал входов"]
    resolved = await admin.request(
        "PATCH", url, json={"status": "resolved", "resolution": "IP заблокирован"}
    )
    assert resolved.json()["status"] == "resolved"

    # Повтор после решения открывает инцидент снова.
    await service.report(
        app.state.db_sessions, type="security", severity="warning", title="Перебор паролей",
        fingerprint="security:test",
    )  # fmt: skip
    card = (await admin.get(url)).json()
    assert card["status"] == "new" and card["occurrences"] == 3 and card["resolution"] is None
    # Ложное срабатывание не открывается повтором — только счётчик.
    await admin.request("PATCH", url, json={"status": "false_positive"})
    await service.report(
        app.state.db_sessions, type="security", severity="warning", title="Перебор паролей",
        fingerprint="security:test",
    )  # fmt: skip
    card = (await admin.get(url)).json()
    assert card["status"] == "false_positive" and card["occurrences"] == 4
    assert (await admin.get("/api/admin/incidents", params={"status": "open"})).json()[
        "items"
    ] == []
    # Дашборд считает открытыми те же статусы, что список и меню (дефект проверки этапа 7).
    board = (await admin.get("/api/admin/dashboard")).json()
    assert board["incidents"] == {"open": 0, "high": 0}

    assert (await petrov.get(url)).status_code == 403
    assert (await petrov.request("PATCH", url, json={"status": "resolved"})).status_code == 403
    audit = (await admin.get("/api/admin/audit", params={"action": "incident.update"})).json()
    assert len(audit["items"]) == 3
