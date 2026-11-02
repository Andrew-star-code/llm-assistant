"""Лимиты (этап 8, §12): счётчики Redis (Lua), разделы usage_records, применение в API."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.db import create_session_factory
from app.modules.limits.counters import Check, Counters, Slot
from app.modules.limits.partitions import ensure_partitions
from app.modules.users.models import User
from tests.integration.conftest import (
    Infra,
    chat_settings,
    make_settings,
    new_chat,
    read_stream,
    send,
)

TZ = "Europe/Moscow"


async def test_reserve_is_atomic_under_parallel_requests(infra: Infra, clean_db: None) -> None:
    """Lua: проверка и резервирование одним шагом — 10 параллельных запросов, лимит 3."""
    redis = Redis.from_url(infra.redis_url, decode_responses=True)
    counters = Counters(redis)
    key = f"lim:test:{uuid4()}"
    now_ms = int(datetime.now(UTC).timestamp() * 1000)

    async def one(i: int) -> tuple[int, int]:
        return await counters.reserve(
            [Check(key, limit=3, add=1)],
            [(key, 1, 60)],
            Slot(f"{key}:slots", f"m{i}", limit=2, now_ms=now_ms, expire_ms=now_ms + 60_000),
        )

    try:
        results = await asyncio.gather(*(one(i) for i in range(10)))
        assert sum(1 for failed, _ in results if failed == 0) == 2  # слотов меньше, чем сообщений
        assert {failed for failed, _ in results if failed} == {2}  # отказ по слотам (n + 1)
        assert await redis.get(key) == "2"
        # Просроченный слот (упавший процесс) освобождается сам при следующей проверке.
        late = now_ms + 61_000
        failed, _ = await counters.reserve(
            [Check(key, 3, 1)], [(key, 1, 60)],
            Slot(f"{key}:slots", "m-late", limit=2, now_ms=late, expire_ms=late + 60_000),
        )  # fmt: skip
        assert failed == 0
        failed, used = await counters.reserve([Check(key, 3, 1)], [(key, 1, 60)])
        assert (failed, used) == (1, 3)  # сообщения кончились
    finally:
        await redis.aclose()


async def test_usage_partitions_move_rows_from_default(
    infra: Infra, clean_db: None, tmp_path: Path
) -> None:
    settings = make_settings(infra, tmp_path, limits={"partitions_ahead": 3})
    engine = create_async_engine(infra.database_url)
    sessions = create_session_factory(engine)
    user_id = uuid4()
    try:
        async with sessions() as db:
            names = list(
                (
                    await db.execute(
                        text(
                            "SELECT c.relname FROM pg_inherits i JOIN pg_class c "
                            "ON c.oid = i.inhrelid WHERE i.inhparent = 'usage_records'::regclass"
                        )
                    )
                ).scalars()
            )
            assert "usage_records_default" in names and len(names) >= 4  # миграция: 3 месяца
            # Строка далёкого месяца без раздела попадает в раздел по умолчанию…
            db.add(
                User(id=user_id, ad_guid=user_id.hex, login=f"u{user_id.hex[:8]}", full_name="Т")
            )
            await db.flush()
            future = datetime(2030, 5, 10, tzinfo=UTC)
            await db.execute(
                text(
                    "INSERT INTO usage_records (id, ts, user_id, model_role, kind, thinking, "
                    "prompt_tokens, completion_tokens) VALUES (:id, :ts, :u, 'chat', 'chat', "
                    "false, 10, 5)"
                ),
                {"id": uuid4(), "ts": future, "u": user_id},
            )
            await db.commit()
            # …и переезжает в созданный раздел.
            created = await ensure_partitions(db, settings, datetime(2030, 4, 1, tzinfo=UTC))
            await db.commit()
            assert "usage_records_2030_05" in created
            moved = await db.scalar(text("SELECT count(*) FROM usage_records_2030_05"))
            left = await db.scalar(
                text("SELECT count(*) FROM usage_records_default WHERE ts >= '2030-05-01'")
            )
            assert (moved, left) == (1, 0)
            assert await ensure_partitions(db, settings, datetime(2030, 4, 1, tzinfo=UTC)) == []
            for name in created:  # не оставлять разделы будущего другим тестам
                await db.execute(text(f"DROP TABLE {name}"))
            await db.commit()
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- применение в API


def _limits(**metrics: int) -> dict[str, Any]:
    """Глобальные политики конфига: ``messages=2`` → 2 сообщения в день и т. п."""
    rules: list[dict[str, Any]] = []
    for metric, value in metrics.items():
        rule: dict[str, Any] = {"metric": metric, "limit": value}
        if metric in ("messages", "tokens", "uploads"):
            rule["window"] = "day"
        rules.append(rule)
    return {"defaults": rules}


async def test_exceeded_limit_gives_429_with_reset_at(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Критерий этапа 8: превышение — 429 с ``reset_at`` и понятным сообщением."""
    settings = chat_settings(
        infra, tmp_path, fake_llm_url, limits=_limits(messages=2, tokens=10**9)
    )
    _, petrov = await make_client(settings)
    await petrov.login("petrov")
    chat_id = await new_chat(petrov)
    # Отклонённый запрос лимит не тратит.
    bad = await petrov.post(
        f"/api/chats/{chat_id}/messages", json={"content": "x", "parent_id": str(uuid4())}
    )
    assert bad.status_code == 400
    for text_ in ("Первый", "Второй"):
        sent = await send(petrov, chat_id, text_)
        events = await read_stream(petrov, sent["assistant_message"]["id"])
    limits_event = next(e for e in events if e.event == "limits")
    assert limits_event.data["nearest"]["metric"] == "messages"
    assert limits_event.data["nearest"]["remaining"] == 0 and limits_event.data["blocked"]

    third = await petrov.post(f"/api/chats/{chat_id}/messages", json={"content": "Третий"})
    assert third.status_code == 429
    error = third.json()["error"]
    assert error["code"] == "limit_exceeded"
    assert error["message"].startswith("Дневной лимит сообщений исчерпан, обновится в 00:00")
    details = error["details"]
    assert (details["metric"], details["window"], details["limit"], details["used"]) == (
        "messages", "day", 2, 2,
    )  # fmt: skip
    reset_at = datetime.fromisoformat(details["reset_at"])
    assert reset_at > datetime.now(UTC) and reset_at.astimezone(ZoneInfo(TZ)).hour == 0
    # Перегенерация — тоже запрос к модели.
    last = (await petrov.get(f"/api/chats/{chat_id}")).json()["messages"][-1]
    regen = await petrov.post(f"/api/messages/{last['id']}/regenerate", json={})
    assert regen.status_code == 429

    mine = (await petrov.get("/api/limits")).json()
    assert mine["blocked"] is True
    messages = next(i for i in mine["items"] if i["metric"] == "messages")
    assert (messages["used"], messages["remaining"]) == (2, 0)
    # Токены списаны по факту ответа, учёт — в usage_records (ответы и заголовок).
    tokens = next(i for i in mine["items"] if i["metric"] == "tokens")
    engine = create_async_engine(infra.database_url)
    try:
        async with create_session_factory(engine)() as db:
            rows = (
                await db.execute(
                    text(
                        "SELECT kind, sum(prompt_tokens + completion_tokens) FROM usage_records "
                        "GROUP BY kind"
                    )
                )
            ).all()
    finally:
        await engine.dispose()
    by_kind = dict(rows)
    assert set(by_kind) == {"chat", "title"}
    assert tokens["used"] == by_kind["chat"] > 0  # заголовок лимит пользователя не тратит


async def test_parallel_requests_respect_concurrent_generations(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Критерий этапа 8: 10 параллельных запросов не превышают лимит одновременных генераций."""
    settings = chat_settings(
        infra, tmp_path, fake_llm_url, limits=_limits(concurrent_generations=2, messages=100)
    )
    _, petrov = await make_client(settings)
    await petrov.login("petrov")
    chats = [await new_chat(petrov) for _ in range(10)]
    responses = await asyncio.gather(
        *(
            petrov.post(f"/api/chats/{c}/messages", json={"content": "[[scenario:slow]] долго"})
            for c in chats
        )
    )
    accepted = [r for r in responses if r.status_code == 202]
    refused = [r for r in responses if r.status_code == 429]
    assert len(accepted) == 2 and len(refused) == 8
    assert {r.json()["error"]["details"]["metric"] for r in refused} == {"concurrent_generations"}
    status = (await petrov.get("/api/limits")).json()
    slots = next(i for i in status["items"] if i["metric"] == "concurrent_generations")
    assert slots["used"] == 2
    # Отказанные запросы не потратили сообщений.
    assert next(i for i in status["items"] if i["metric"] == "messages")["used"] == 2
    for response in accepted:
        await read_stream(petrov, response.json()["assistant_message"]["id"])
    # Генерации закончились — слоты свободны, новый запрос проходит.
    status = (await petrov.get("/api/limits")).json()
    assert next(i for i in status["items"] if i["metric"] == "concurrent_generations")["used"] == 0
    sent = await send(petrov, chats[5], "Снова")
    await read_stream(petrov, sent["assistant_message"]["id"])


async def test_uploads_limit_counts_attachments_and_personal_documents(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    settings = chat_settings(infra, tmp_path, fake_llm_url, limits=_limits(uploads=2))
    _, petrov = await make_client(settings)
    await petrov.login("petrov")
    files = {"file": ("a.txt", b"hello", "text/plain")}
    assert (await petrov.post("/api/files", files=files)).status_code == 201
    # Отклонённый файл (пустой) лимит не тратит.
    empty = await petrov.post("/api/files", files={"file": ("e.txt", b"", "text/plain")})
    assert empty.status_code >= 400 and empty.status_code != 429
    doc = {"file": ("note.txt", b"personal note", "text/plain")}
    assert (await petrov.post("/api/kb/personal/documents", files=doc)).status_code == 201
    third = await petrov.post("/api/files", files={"file": ("b.txt", b"x", "text/plain")})
    assert third.status_code == 429
    assert third.json()["error"]["details"]["metric"] == "uploads"


# --------------------------------------------------------------------------- админка


async def _ids(admin: Any, petrov: Any) -> tuple[str, str]:
    me = (await petrov.get("/api/auth/me")).json()
    roles = (await admin.get("/api/admin/roles")).json()
    dept = next(r for r in roles if r["code"] == "dept:Бухгалтерия")
    return me["id"], dept["id"]


def _effective(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    return next(r for r in rows if r["metric"] == metric and not r["model_role"])


async def test_personal_policy_overrides_role_and_temporary_expires(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Критерий этапа 8: персональная политика перекрывает ролевую, временная истекает сама."""
    settings = chat_settings(infra, tmp_path, fake_llm_url)
    _, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    await admin.login("ivanov")
    await petrov.login("petrov")
    user_id, role_id = await _ids(admin, petrov)
    url = f"/api/admin/users/{user_id}/limits"

    def policy(**kw: Any) -> dict[str, Any]:
        return {"metric": "messages", "window": "day", **kw}

    role = await admin.post(
        "/api/admin/limits/policies", json=policy(scope="role", target_id=role_id, limit=3)
    )
    assert role.status_code == 201 and role.json()["target"]["code"] == "dept:Бухгалтерия"
    row = _effective((await admin.get(url)).json()["items"], "messages")
    assert (row["limit"], row["source"], row["source_name"]) == (3, "role", "Отдел: Бухгалтерия")

    personal = await admin.post(
        "/api/admin/limits/policies", json=policy(scope="user", target_id=user_id, limit=1)
    )
    assert personal.status_code == 201
    row = _effective((await admin.get(url)).json()["items"], "messages")
    assert (row["limit"], row["source"]) == (1, "user")  # персональная ниже ролевой — действует
    chat_id = await new_chat(petrov)
    sent = await send(petrov, chat_id, "Один")
    await read_stream(petrov, sent["assistant_message"]["id"])
    refused = await petrov.post(f"/api/chats/{chat_id}/messages", json={"content": "Два"})
    assert refused.status_code == 429 and refused.json()["error"]["details"]["limit"] == 1

    # Временное повышение: персональная политика со сроком, потом лимит снова ролевой.
    await admin.request("DELETE", f"/api/admin/limits/policies/{personal.json()['id']}")
    expires = datetime.now(UTC) + timedelta(seconds=2)
    temporary = await admin.post(
        "/api/admin/limits/policies",
        json=policy(scope="user", target_id=user_id, limit=10, expires_at=expires.isoformat()),
    )
    assert temporary.status_code == 201
    row = _effective((await admin.get(url)).json()["items"], "messages")
    assert (row["limit"], row["source"], row["expires_at"] is not None) == (10, "user", True)
    sent = await send(petrov, chat_id, "Два")
    await read_stream(petrov, sent["assistant_message"]["id"])
    await asyncio.sleep(max(0.0, (expires - datetime.now(UTC)).total_seconds()) + 0.3)
    row = _effective((await admin.get(url)).json()["items"], "messages")
    assert (row["limit"], row["source"], row["used"]) == (3, "role", 2)  # без действий админа
    listed = (await admin.get("/api/admin/limits/policies")).json()
    assert [p["scope"] for p in listed["items"]] == ["role"]  # истёкшая не в списке
    with_expired = (
        await admin.get("/api/admin/limits/policies", params={"include_expired": "true"})
    ).json()
    assert {p["active"] for p in with_expired["items"]} == {True, False}

    # Сброс счётчиков и аудит.
    assert (await admin.post(f"{url}/reset", json={"metric": "messages"})).status_code == 204
    assert _effective((await admin.get(url)).json()["items"], "messages")["used"] == 0
    audit = (await admin.get("/api/admin/audit", params={"q": "limits"})).json()["items"]
    actions = {a["action"] for a in audit}
    assert {"limits.policy.create", "limits.policy.delete", "limits.reset"} <= actions


async def test_policy_validation_and_role_kb_quota(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    settings = chat_settings(infra, tmp_path, fake_llm_url)
    _, admin = await make_client(settings)
    _, petrov = await make_client(settings)
    await admin.login("ivanov")
    await petrov.login("petrov")
    user_id, role_id = await _ids(admin, petrov)
    base = "/api/admin/limits/policies"
    no_window = await admin.post(base, json={"scope": "global", "metric": "tokens", "limit": 5})
    assert no_window.status_code == 422 and no_window.json()["error"]["code"] == "bad_policy"
    target = await admin.post(
        base, json={"scope": "role", "metric": "tokens", "window": "day", "limit": 5}
    )
    assert target.json()["error"]["code"] == "bad_target"
    unknown_model = await admin.post(
        base,
        json={"scope": "global", "metric": "tokens", "window": "day", "limit": 5,
              "model_role": "nope"},
    )  # fmt: skip
    assert unknown_model.json()["error"]["code"] == "bad_model_role"
    body = {"scope": "global", "metric": "tokens", "window": "week", "limit": 5, "thinking": True}
    assert (await admin.post(base, json=body)).status_code == 201
    assert (await admin.post(base, json=body)).status_code == 409
    listed = (await admin.get(base)).json()
    assert {"metric": "messages", "window": "day", "limit": 200, "model_role": None,
            "thinking": False} in listed["defaults"]  # fmt: skip

    # Квота личной базы — ролевой политикой (§7.8).
    quota = {"scope": "role", "target_id": role_id, "metric": "personal_kb_documents", "limit": 1}
    assert (await admin.post(base, json=quota)).status_code == 201
    kb = (await petrov.get("/api/kb/personal")).json()
    assert kb["quota"]["max_documents"] == 1
    first = {"file": ("a.txt", b"first note", "text/plain")}
    assert (await petrov.post("/api/kb/personal/documents", files=first)).status_code == 201
    second = {"file": ("b.txt", b"second note", "text/plain")}
    refused = await petrov.post("/api/kb/personal/documents", files=second)
    assert refused.status_code == 413 and refused.json()["error"]["code"] == "quota_documents"
    mine = (await petrov.get("/api/limits")).json()
    docs = next(i for i in mine["items"] if i["metric"] == "personal_kb_documents")
    assert (docs["used"], docs["limit"]) == (1, 1)
    # Отказ квоты не тратит дневной лимит загрузок.
    uploads = next(i for i in mine["items"] if i["metric"] == "uploads")
    assert uploads["used"] == 1
    assert (await petrov.get(f"/api/admin/users/{user_id}/limits")).status_code == 403
