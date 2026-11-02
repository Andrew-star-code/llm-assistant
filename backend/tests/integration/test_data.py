"""Семантический слой и SQL (этап 9, §9.5): инструменты данных через data-gateway, «Кадровый бот»,
отказ изменяющих запросов, аудит каждого запроса. Шлюз — в процессе, источник — SQLite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.integration.conftest import (
    DATA_GATEWAY_SECRET,
    ApiClient,
    Infra,
    chat_settings,
    new_chat,
    read_stream,
    send,
)


def _settings(
    infra: Infra, tmp_path: Path, fake_llm_url: str, gateway: str | None, **kw: Any
) -> Any:
    data: dict[str, Any] = {"url": gateway, "secret": DATA_GATEWAY_SECRET} if gateway else {}
    data |= kw.pop("data_gateway", {})
    return chat_settings(infra, tmp_path, fake_llm_url, data_gateway=data, **kw)


async def _ask(client: ApiClient, chat_id: str, text: str) -> tuple[str, list[Any]]:
    sent = await send(client, chat_id, text)
    events = await read_stream(client, sent["assistant_message"]["id"])
    reply = "".join(e.data["text"] for e in events if e.event == "content.delta")
    return reply, events


async def _audit(admin: ApiClient, action: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = (
        await admin.get("/api/admin/audit", params={"action": action})
    ).json()["items"]
    return items


async def test_hr_bot_finds_phone_in_phonebook(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, data_gateway_url: str
) -> None:
    """Критерий этапа 9: «Найди телефон Петрова из бухгалтерии» → ответ из справочника."""
    settings = _settings(infra, tmp_path, fake_llm_url, data_gateway_url)
    _, admin = await make_client(settings)
    _, kim = await make_client(settings)
    await admin.login("ivanov")
    await kim.login("kim")
    scenarios = {s["code"]: s for s in (await kim.get("/api/scenarios")).json()}
    hr = scenarios["hr_bot"]
    assert hr["name"] == "Кадровый бот"
    chat_id = (await kim.post("/api/chats", json={"scenario_id": hr["id"]})).json()["id"]
    reply, events = await _ask(kim, chat_id, "Найди телефон Петрова из бухгалтерии")
    assert reply == (
        "Телефон Петров Сергей Алексеевич (Бухгалтерия): +7 (495) 100-20-02, внутренний 2002."
    )
    [start] = [e for e in events if e.event == "tool.start"]
    assert start.data["tool"] == "search_employees"
    assert start.data["params"] == {"query": "Петров"}

    # Критерий: каждый запрос к данным виден в аудите — пользователь, SQL, число строк.
    [entry] = await _audit(admin, "data.function")
    assert entry["actor_name"] == "Ким Александр" and entry["target_id"] == "search_employees"
    details = entry["details"]
    assert details["status"] == "ok" and details["rows"] == 1
    assert details["sql"].startswith("SELECT TOP (:limit) full_name")
    assert details["params"] == {"query": "Петров", "department": "Бухгалтерия", "limit": 20}
    assert details["chat_id"] == chat_id


async def test_sql_changes_are_rejected_and_audited(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, data_gateway_url: str
) -> None:
    """Критерий этапа 9: изменяющие запросы и запрещённые таблицы отклоняются; аудит — у всех."""
    settings = _settings(infra, tmp_path, fake_llm_url, data_gateway_url)
    _, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    await admin.login("ivanov")
    await petrov.login("petrov")
    chat_id = await new_chat(petrov)
    reply, events = await _ask(
        petrov, chat_id, "[[scenario:tool:run_sql_query]] DELETE FROM dbo.v_phonebook"
    )
    [end] = [e for e in events if e.event == "tool.end"]
    assert end.data["status"] == "error"
    assert "только SELECT" in reply
    reply, _ = await _ask(
        petrov, chat_id, "[[scenario:tool:run_sql_query]] SELECT name FROM sys.tables"
    )
    assert "не описана в каталоге" in reply
    ok, _ = await _ask(
        petrov,
        chat_id,
        "[[scenario:tool:run_sql_query]] SELECT department, COUNT(*) AS n FROM dbo.v_phonebook "
        "GROUP BY department",
    )
    assert "Найдено строк: 4" in ok

    entries = await _audit(admin, "data.query")
    assert [e["details"]["status"] for e in entries] == ["ok", "rejected", "rejected"]
    assert entries[2]["details"]["sql"] == "DELETE FROM dbo.v_phonebook"
    assert entries[0]["details"]["sql"].startswith("SELECT TOP 1000 department")
    assert entries[0]["details"]["rows"] == 4 and entries[0]["target_id"] == "phonebook"
    assert {e["actor_name"] for e in entries} == {"Петров Сергей Алексеевич"}


async def test_failed_attempts_limit_and_csv_for_large_results(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, data_gateway_url: str
) -> None:
    settings = _settings(
        infra, tmp_path, fake_llm_url, data_gateway_url,
        data_gateway={"preview_rows": 2, "max_failed_attempts": 2},
    )  # fmt: skip
    _, petrov = await make_client(settings)
    await petrov.login("petrov")
    chat_id = await new_chat(petrov)
    # Три неудачных запроса за один ответ: третий уже не уходит в шлюз.
    reply, events = await _ask(
        petrov,
        chat_id,
        "[[scenario:tool:run_sql_query+run_sql_query+run_sql_query]] UPDATE dbo.v_phonebook "
        "SET phone = N'1'",
    )
    statuses = [e.data["status"] for e in events if e.event == "tool.end"]
    assert statuses == ["error", "error", "error"]
    assert "лимит неудачных попыток исчерпан" in reply
    # Больше preview_rows строк: модель видит две, весь результат — CSV-карточкой.
    chat2 = await new_chat(petrov)
    reply, events = await _ask(
        petrov, chat2, "[[scenario:tool:run_sql_query]] SELECT full_name FROM dbo.v_phonebook"
    )
    [file_event] = [e for e in events if e.event == "file"]
    assert file_event.data["name"].endswith(".csv")
    assert "Найдено строк: 6" in reply


async def test_data_tools_offered_only_with_gateway(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, data_gateway_url: str
) -> None:
    data_tools = {
        "list_datasets", "describe_dataset", "call_data_function", "run_sql_query",
        "search_employees",
    }  # fmt: skip
    for gateway, expected in ((None, set()), (data_gateway_url, data_tools)):
        settings = _settings(infra, tmp_path, fake_llm_url, gateway)
        _, admin = await make_client(settings)
        await admin.login("ivanov")
        chat_id = await new_chat(admin)
        await _ask(admin, chat_id, "Привет")
        detail = (await admin.get(f"/api/admin/chats/{chat_id}")).json()
        offered = set(detail["messages"][-1]["trace"]["tools_offered"])
        assert offered & data_tools == expected
    # Каталог и описание набора — через инструменты.
    reply, _ = await _ask(admin, chat_id, "[[scenario:tool:list_datasets]] что есть")
    assert "phonebook — Телефонный справочник" in reply and "search_employees(" in reply
    reply, _ = await _ask(admin, chat_id, "[[scenario:tool:describe_dataset]] телефон")
    assert "dbo.v_phonebook" in reply


async def test_admin_datasources_catalog_test_call_and_journal(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str, data_gateway_url: str
) -> None:
    settings = _settings(infra, tmp_path, fake_llm_url, data_gateway_url)
    _, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    await admin.login("ivanov")
    await petrov.login("petrov")
    catalog = (await admin.get("/api/admin/data/catalog")).json()
    assert catalog["configured"] and catalog["catalog_error"] is None
    [dataset] = catalog["datasets"]
    assert dataset["view"] == "dbo.v_phonebook" and dataset["source"] == "mssql_main"
    assert catalog["functions"][0]["sql"].startswith("SELECT TOP (:limit)")
    called = await admin.post(
        "/api/admin/data/functions/search_employees/test", json={"params": {"query": "Смирнов"}}
    )
    assert called.status_code == 200 and called.json()["rows"][0][0] == "Смирнова Анна Викторовна"
    bad = await admin.post("/api/admin/data/functions/search_employees/test", json={"params": {}})
    assert bad.status_code == 422 and "обязателен" in bad.json()["error"]["message"]
    journal = (await admin.get("/api/admin/data/queries")).json()["items"]
    assert [j["status"] for j in journal] == ["rejected", "ok"]
    assert journal[1]["user"] == "Иванов Иван Петрович" and journal[1]["rows"] == 1
    found = (await admin.get("/api/admin/data/queries", params={"q": "Смирнов"})).json()
    assert found["items"] == []  # поиск — по пользователю, цели и SQL, не по параметрам
    assert (await petrov.get("/api/admin/data/catalog")).status_code == 403
    # Без шлюза — раздел честно говорит, что источник не настроен.
    _, bare = await make_client(_settings(infra, tmp_path, fake_llm_url, None))
    await bare.login("ivanov")
    assert (await bare.get("/api/admin/data/catalog")).json() == {
        "configured": False, "datasets": [], "functions": [], "catalog_error": None, "error": None,
        "error_code": None,
    }  # fmt: skip
    # Шлюз настроен, но не отвечает: в разделе — код ошибки, ответ модели говорит о сбое,
    # а не «никого не нашёл» (проверка этапа 9).
    down = _settings(infra, tmp_path, fake_llm_url, "http://127.0.0.1:9")
    _, admin_down = await make_client(down)
    _, kim = await make_client(down)
    await admin_down.login("ivanov")
    await kim.login("kim")
    broken = (await admin_down.get("/api/admin/data/catalog")).json()
    assert broken["error_code"] == "unavailable" and broken["error"] == "шлюз данных недоступен"
    hr = next(s for s in (await kim.get("/api/scenarios")).json() if s["code"] == "hr_bot")
    chat_id = (await kim.post("/api/chats", json={"scenario_id": hr["id"]})).json()["id"]
    reply, events = await _ask(kim, chat_id, "Найди телефон Петрова из бухгалтерии")
    assert [e.data["status"] for e in events if e.event == "tool.end"] == ["error"]
    assert reply == "Не удалось обратиться к телефонному справочнику: шлюз данных недоступен"
