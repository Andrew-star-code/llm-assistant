"""Безопасность входов (этап 7, §13.4): перебор с одного IP → блокировка и инцидент, ручные
блокировки и доверенные подсети, флаги риска событий входа, всплеск сообщений.

IP клиента задаётся заголовком X-Forwarded-For от «доверенного прокси» 127.0.0.1 (так тестовый
транспорт представляется приложению).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.cli.security import _unblock as cli_unblock
from app.core.config import Settings
from app.modules.security.rules import off_hours
from tests.integration.conftest import (
    ApiClient,
    Infra,
    chat_settings,
    make_settings,
    new_chat,
    read_stream,
    send,
)

ALWAYS = {"work_hours": {"start": "00:00", "end": "23:59", "weekdays": [1, 2, 3, 4, 5, 6, 7]}}


async def _client(make_client: Any, settings: Settings, ip: str | None = None) -> Any:
    app, client = await make_client(settings)
    if ip:
        client.http.headers["X-Forwarded-For"] = ip
    return app, client


def _settings(infra: Infra, tmp_path: Path, **overrides: Any) -> Settings:
    return make_settings(
        infra, tmp_path, trusted_proxies=["127.0.0.1"], security=ALWAYS, **overrides
    )


async def _incidents(admin: ApiClient, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = (await admin.get("/api/admin/incidents", params=params)).json()[
        "items"
    ]
    return items


async def test_twenty_failures_from_one_ip_block_it_and_create_incident(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    """Критерий этапа 7: 20 неудачных входов с одного IP блокируют IP и создают инцидент."""
    settings = _settings(infra, tmp_path)
    _, admin = await _client(make_client, settings)
    _, attacker = await _client(make_client, settings, "203.0.113.7")
    _, victim = await _client(make_client, settings, "203.0.113.7")  # работал с того же адреса
    _, colleague = await _client(make_client, settings, "203.0.113.8")
    await admin.login("ivanov")
    assert (await victim.login("kim")).status_code == 200

    # Разные логины — по логину блокировки нет, срабатывает правило по IP.
    for i in range(20):
        assert (await attacker.login(f"nobody{i}")).status_code == 401
    assert (await attacker.login("petrov")).status_code == 401  # даже верный вход

    [incident] = await _incidents(admin, type="security")
    assert incident["severity"] == "high" and "203.0.113.7" in incident["title"]
    card = (await admin.get(f"/api/admin/incidents/{incident['id']}")).json()
    assert card["payload"]["rule"] == "bruteforce_ip" and len(card["payload"]["logins"]) == 20
    [block] = (await admin.get("/api/admin/ip-blocks")).json()
    assert block["cidr"] == "203.0.113.7/32" and block["source"] == "auto" and block["until"]

    # Заблокированный адрес не работает и с уже открытой сессией; соседний — работает.
    blocked = await victim.get("/api/auth/me")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "ip_blocked"
    assert (await colleague.login("petrov")).status_code == 200
    events = (await admin.get("/api/admin/logins", params={"login": "petrov"})).json()["items"]
    assert any(e["failure_reason"] == "locked_ip" for e in events)

    # Снять блокировку — вход снова работает (и Redis-блокировка за перебор тоже снята).
    assert (await admin.request("DELETE", f"/api/admin/ip-blocks/{block['id']}")).status_code == 204
    assert (await attacker.login("petrov")).status_code == 200
    audit = (await admin.get("/api/admin/audit", params={"action": "ip.unblock"})).json()
    assert len(audit["items"]) == 1


async def test_manual_blocks_and_trusted_networks(
    make_client: Any, infra: Infra, tmp_path: Path
) -> None:
    settings = _settings(infra, tmp_path)
    _, admin = await _client(make_client, settings)
    _, office = await _client(make_client, settings, "198.51.100.5")
    _, branch = await _client(make_client, settings, "192.0.2.9")
    await admin.login("ivanov")
    assert (await branch.login("kim")).status_code == 200

    wide = await admin.post("/api/admin/ip-blocks", json={"cidr": "10.0.0.0/8", "reason": "x"})
    assert wide.status_code == 422 and wide.json()["error"]["code"] == "cidr_too_wide"
    own = await admin.post("/api/admin/ip-blocks", json={"cidr": "127.0.0.1", "reason": "x"})
    assert own.status_code == 422 and own.json()["error"]["code"] == "self_block"
    created = await admin.post(
        "/api/admin/ip-blocks", json={"cidr": "192.0.2.0/24", "reason": "Филиал на проверке"}
    )
    assert created.status_code == 201 and created.json()["created_by"] == "Иванов Иван Петрович"
    assert (await branch.get("/api/auth/me")).status_code == 403

    # Доверенная подсеть (NAT офиса): перебор даёт инцидент, но адрес не блокируется.
    trusted = await admin.post(
        "/api/admin/trusted-networks", json={"cidr": "198.51.100.0/24", "note": "Офис"}
    )
    assert trusted.status_code == 201
    for i in range(20):
        await office.login(f"ghost{i}")
    assert (await office.login("petrov")).status_code == 200
    [incident] = await _incidents(admin, type="security")
    assert "без блокировки" in incident["title"]
    blocks = {b["cidr"] for b in (await admin.get("/api/admin/ip-blocks")).json()}
    assert blocks == {"192.0.2.0/24"}

    # CLI снимает блокировку, если админка с этого адреса недоступна: по адресу — все подсети,
    # что его содержат; процессы api узнают об этом сразу (версия в Redis).
    assert await cli_unblock(settings, "192.0.2.9") == 0
    assert (await branch.get("/api/auth/me")).status_code == 200
    assert (await admin.get("/api/admin/ip-blocks")).json() == []
    audit = (await admin.get("/api/admin/audit", params={"action": "ip.unblock"})).json()["items"]
    assert audit[0]["actor_id"] is None and audit[0]["details"]["via"] == "cli"


async def test_login_risk_flags_and_review(make_client: Any, infra: Infra, tmp_path: Path) -> None:
    settings = _settings(infra, tmp_path)
    app, admin = await _client(make_client, settings)
    _, first = await _client(make_client, settings, "10.0.1.5")
    _, second = await _client(make_client, settings, "10.0.2.5")
    _, kim = await _client(make_client, settings, "10.0.1.6")
    await admin.login("ivanov")

    assert (await first.login("petrov")).status_code == 200  # первый вход — без флагов
    await app.state.bruteforce.register_failure("petrov", "10.0.2.5")  # неудача перед успехом
    assert (await second.login("petrov")).status_code == 200
    events = (await admin.get("/api/admin/logins", params={"login": "petrov"})).json()["items"]
    latest, earliest = events[0], events[-1]
    assert earliest["risk_flags"] == []
    assert set(latest["risk_flags"]) == {"after_failures", "new_subnet", "concurrent_subnets"}

    # Попытка заблокированного пользователя — флаг.
    kim_id = (await kim.login("kim")).json()["id"]
    await admin.post(f"/api/admin/users/{kim_id}/block", json={"reason": "Проверка"})
    assert (await kim.login("kim")).status_code == 401
    flagged = (await admin.get("/api/admin/logins", params={"flagged": "true"})).json()["items"]
    assert {e["login_attempted"] for e in flagged} == {"petrov", "kim"}
    assert next(e for e in flagged if e["login_attempted"] == "kim")["risk_flags"] == [
        "blocked_attempt"
    ]

    reviewed = await admin.post(f"/api/admin/logins/{latest['id']}/review")
    assert reviewed.status_code == 200 and reviewed.json()["reviewed_at"]
    open_ = (
        await admin.get("/api/admin/logins", params={"flagged": "true", "unreviewed": "true"})
    ).json()["items"]
    assert [e["login_attempted"] for e in open_] == ["kim"]


def test_off_hours_uses_company_timezone() -> None:
    settings = Settings(chat={"timezone": "Europe/Moscow"})
    # Понедельник 06:30 UTC = 09:30 Москвы — рабочее время; 19:30 UTC = 22:30 — нет.
    assert not off_hours(datetime(2026, 11, 2, 6, 30, tzinfo=UTC), settings)
    assert off_hours(datetime(2026, 11, 2, 19, 30, tzinfo=UTC), settings)
    assert off_hours(datetime(2026, 11, 1, 9, 0, tzinfo=UTC), settings)  # воскресенье


async def test_message_burst_creates_incident(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    settings = chat_settings(
        infra, tmp_path, fake_llm_url, security={"message_burst": {"max_messages": 3}}
    )
    _, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    await admin.login("ivanov")
    await petrov.login("petrov")
    chat_id = await new_chat(petrov)
    for i in range(5):
        sent = await send(petrov, chat_id, f"Сообщение {i}")
        await read_stream(petrov, sent["assistant_message"]["id"])
    [incident] = await _incidents(admin, type="security")
    assert "Аномальный объём" in incident["title"] and incident["user"]["login"] == "petrov"
    assert incident["occurrences"] == 1  # один на окно, а не на каждое сообщение сверх порога
