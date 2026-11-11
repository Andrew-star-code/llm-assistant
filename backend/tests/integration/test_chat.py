"""Ядро чата (этап 2): стрим, переподключение, «Стоп», перегенерация, история, поиск, IDOR."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.modules.chats.models import Chat, Message
from tests.integration.conftest import (
    ApiClient,
    Infra,
    chat_settings,
    new_chat,
    read_stream,
    send,
)


async def _client(
    make_client: Any,
    infra: Infra,
    tmp_path: Path,
    url: str,
    login: str = "petrov",
    **overrides: Any,
) -> tuple[Any, ApiClient]:
    app, client = await make_client(chat_settings(infra, tmp_path, url, **overrides))
    await client.login(login)
    return app, client


async def test_message_stream_personalization_and_title(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    # Пустой чат в списке не показывается (§7.2).
    assert (await client.get("/api/chats")).json()["items"] == []

    sent = await send(client, chat_id, "Привет, как оформить отпуск?")
    assert sent["assistant_message"]["status"] == "streaming"
    events = await read_stream(client, sent["assistant_message"]["id"])
    names = [e.event for e in events]
    assert names[0] == "message.start" and names[-1] == "message.end"
    assert {"content.delta", "usage", "title"} <= set(names)
    assert [e.id for e in events] == list(range(1, len(events) + 1))
    assert events[0].data["protocol_version"] == 1
    assert events[-1].data == {"status": "completed", "finish_reason": "stop"}

    text = "".join(e.data["text"] for e in events if e.event == "content.delta")
    # Модель обращается по имени и отчеству в первом ответе (§11.1).
    assert (
        text == "Сергей Алексеевич, это ответ fake-llm на запрос: «Привет, как оформить отпуск?»."
    )

    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    assert detail["title"] == "Привет, как оформить отпуск"
    user_msg, answer = detail["messages"]
    assert answer["content"] == text and answer["status"] == "completed"
    assert answer["parent_id"] == user_msg["id"] and detail["active_leaf_id"] == answer["id"]
    assert answer["completion_tokens"] > 0 and answer["ttft_ms"] is not None
    listed = (await client.get("/api/chats")).json()["items"]
    assert [c["id"] for c in listed] == [chat_id]

    async with app.state.db_sessions() as db:
        row = await db.get(Message, answer["id"])
        assert row is not None and row.trace is not None
        assert row.trace["model"] == "fake-chat" and row.trace["history_turns_used"] == 0


async def test_heartbeat_is_a_ping_event_without_id(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Heartbeat — событие ``ping`` без ``id`` (§8.5): клиент видит, что поток жив, а позиция
    переподключения не сдвигается. Генерации нет — читатель ждёт и получает ping."""
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    async with app.state.db_sessions() as db:
        chat = await db.get(Chat, chat_id)
        assert chat is not None
        waiting = Message(chat_id=chat.id, role="assistant", status="streaming")
        db.add(waiting)
        await db.commit()
        message_id = str(waiting.id)
    from app.modules.completions.streaming import alive_key

    await app.state.redis.set(alive_key(waiting.id), "1", ex=3)  # «генерация ещё жива» 3 с
    response = await client.get(f"/api/messages/{message_id}/stream", timeout=30)
    blocks = [b for b in response.text.split("\n\n") if b.strip()]
    pings = [b for b in blocks if b.startswith("event: ping")]
    assert pings and all("id:" not in b for b in pings)
    assert blocks[-1].startswith("id: ") and "event: message.end" in blocks[-1]


async def test_reconnect_with_last_event_id(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "[[scenario:slow]] длинный ответ")
    message_id = sent["assistant_message"]["id"]
    full = await read_stream(client, message_id)
    tail = await read_stream(client, message_id, last_event_id=3)
    assert [e.id for e in tail] == [e.id for e in full if e.id > 3]
    assert tail[-1].event == "message.end"


async def test_second_turn_has_history_and_no_greeting(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    first = await send(client, chat_id, "Первый вопрос")
    await read_stream(client, first["assistant_message"]["id"])
    second = await send(client, chat_id, "Второй вопрос")
    assert second["user_message"]["parent_id"] == first["assistant_message"]["id"]
    events = await read_stream(client, second["assistant_message"]["id"])
    text = "".join(e.data["text"] for e in events if e.event == "content.delta")
    assert text == "Это ответ fake-llm на запрос: «Второй вопрос»."
    assert "title" not in {e.event for e in events}  # заголовок — только после первого ответа


async def test_stop_saves_partial_answer(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "[[scenario:slow]] остановите меня")
    message_id = sent["assistant_message"]["id"]
    await asyncio.sleep(0.6)
    assert (await client.post(f"/api/messages/{message_id}/stop")).status_code == 202
    events = await read_stream(client, message_id)
    assert events[-1].data["status"] == "stopped"

    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    answer = detail["messages"][-1]
    assert answer["status"] == "stopped"
    assert answer["content"].startswith("Слово1")
    assert not answer["content"].endswith("Слово40.")
    assert answer["completion_tokens"] > 0  # фактические токены списаны даже без usage модели


async def test_regenerate_creates_sibling_versions(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "Вопрос")
    first_id = sent["assistant_message"]["id"]
    await read_stream(client, first_id)

    response = await client.post(f"/api/messages/{first_id}/regenerate", json={})
    assert response.status_code == 202
    second = response.json()
    assert second["parent_id"] == sent["user_message"]["id"]
    await read_stream(client, second["id"])

    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    answers = [m for m in detail["messages"] if m["role"] == "assistant"]
    assert [a["id"] for a in answers] == [first_id, second["id"]]
    assert detail["active_leaf_id"] == second["id"]
    # Переключение на первую версию сохраняется в чате (§8.6).
    patched = await client.request(
        "PATCH", f"/api/chats/{chat_id}", json={"active_leaf_id": first_id}
    )
    assert patched.status_code == 200
    assert (await client.get(f"/api/chats/{chat_id}")).json()["active_leaf_id"] == first_id


async def test_model_error_then_retry(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "[[scenario:error_500]] упади")
    events = await read_stream(client, sent["assistant_message"]["id"])
    error = next(e for e in events if e.event == "error")
    assert error.data == {
        "code": "model_http_500",
        "message": "Модель вернула ошибку",
        "retryable": True,
    }
    assert events[-1].data["status"] == "error"
    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    assert detail["messages"][-1]["error"] == {
        "code": "model_http_500",
        "message": "Модель вернула ошибку",
    }
    # По упавшему ответу модель заголовок не придумывает — берутся первые слова вопроса.
    assert detail["title"] == "[[scenario:error_500]] упади"


async def test_transient_model_failure_is_retried(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Краткий сбой модели до первого слова ответа пользователь не замечает."""
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    question = f"[[scenario:flaky]] вопрос {uuid.uuid4().hex[:8]}"
    sent = await send(client, chat_id, question)
    events = await read_stream(client, sent["assistant_message"]["id"])
    # 503, затем обрыв до первого слова, затем ответ — два автоповтора, ошибки в стриме нет.
    assert "error" not in {e.event for e in events}
    text = "".join(e.data["text"] for e in events if e.event == "content.delta")
    assert text.startswith("Ответ fake-llm после сбоев")
    assert events[-1].data == {"status": "completed", "finish_reason": "stop"}
    async with app.state.db_sessions() as db:
        row = await db.get(Message, uuid.UUID(sent["assistant_message"]["id"]))
        assert row is not None and row.trace is not None
        assert row.trace["model_retries"] == 2


async def test_model_failure_without_retries_and_broken_stream(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url, chat={"model_retries": 0})
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, f"[[scenario:flaky]] вопрос {uuid.uuid4().hex[:8]}")
    events = await read_stream(client, sent["assistant_message"]["id"])
    assert next(e for e in events if e.event == "error").data["code"] == "model_http_503"

    # Обрыв после начала ответа не повторяется (текст задвоился бы): частичный ответ и ошибка
    # «модель недоступна» с кнопкой «Повторить».
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "[[scenario:disconnect]] оборвись")
    events = await read_stream(client, sent["assistant_message"]["id"])
    assert next(e for e in events if e.event == "error").data == {
        "code": "model_unavailable",
        "message": "Модель недоступна",
        "retryable": True,
    }
    text = "".join(e.data["text"] for e in events if e.event == "content.delta")
    assert text.startswith("Начинаю отвечать")


async def test_thinking_mode(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    info = (await client.get("/api/models/chat")).json()
    assert info == {"thinking_available": True, "thinking_default": False}
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "Подумай", thinking=True)
    assert sent["assistant_message"]["thinking"] is True
    events = await read_stream(client, sent["assistant_message"]["id"])
    reasoning = "".join(e.data["text"] for e in events if e.event == "reasoning.delta")
    assert reasoning.startswith("Пользователь спрашивает")
    assert events[0].data["thinking"] is True
    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    assert detail["thinking_enabled"] is True
    assert detail["messages"][-1]["reasoning"] == reasoning
    assert detail["messages"][-1]["reasoning_tokens"] > 0
    assert detail["messages"][-1]["reasoning_ms"] is not None


async def test_busy_chat_rejects_second_message(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "[[scenario:slow]] долго")
    response = await client.post(f"/api/chats/{chat_id}/messages", json={"content": "ещё"})
    assert response.status_code == 409
    await client.post(f"/api/messages/{sent['assistant_message']['id']}/stop")
    await read_stream(client, sent["assistant_message"]["id"])


async def test_interrupted_generation_is_reported(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Исполнитель умер (нет ключа живости) — сообщение помечается interrupted (§2.2)."""
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    async with app.state.db_sessions() as db:
        chat = await db.get(Chat, chat_id)
        assert chat is not None
        user_msg = Message(chat_id=chat.id, role="user", content="вопрос", status="completed")
        db.add(user_msg)
        await db.flush()
        orphan = Message(
            chat_id=chat.id, parent_id=user_msg.id, role="assistant", status="streaming"
        )
        db.add(orphan)
        await db.commit()
        orphan_id = str(orphan.id)
    events = await read_stream(client, orphan_id)
    assert [e.event for e in events] == ["error", "message.end"]
    assert events[-1].data["status"] == "interrupted"
    async with app.state.db_sessions() as db:
        row = await db.get(Message, orphan_id)
        assert row is not None and row.status == "interrupted"

    # То же при старте процесса для всех «осиротевших» ответов.
    async with app.state.db_sessions() as db:
        row = await db.get(Message, orphan_id)
        assert row is not None
        row.status = "streaming"
        await db.commit()
    assert await app.state.generations.mark_orphaned_interrupted() == 1


async def test_crashed_generation_with_partial_stream_ends_for_readers(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Процесс упал посреди ответа (проверка этапа 8): в Redis — начало потока, ключ живости
    истёк. Проверка «осиротевших» закрывает ответ и освобождает слот генерации, а читатель потока
    получает error и message.end, а не бесконечные ping."""
    from app.modules.completions.streaming import EventWriter
    from app.modules.limits.counters import slot_key

    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    async with app.state.db_sessions() as db:
        chat = await db.get(Chat, chat_id)
        assert chat is not None
        user_msg = Message(chat_id=chat.id, role="user", content="вопрос", status="completed")
        db.add(user_msg)
        await db.flush()
        orphan = Message(
            chat_id=chat.id, parent_id=user_msg.id, role="assistant", status="streaming"
        )
        db.add(orphan)
        await db.commit()
        orphan_id, user_id = orphan.id, chat.user_id
    redis = app.state.redis
    writer = EventWriter(redis, orphan_id, 600)
    await writer.emit("message.start", {"message_id": str(orphan_id)})
    await writer.delta("content", "Начало ответа")
    await writer.flush()
    await redis.zadd(slot_key(user_id), {str(orphan_id): 4_102_444_800_000})  # слот «навсегда»

    assert await app.state.generations.mark_orphaned_interrupted() == 1
    assert await redis.zscore(slot_key(user_id), str(orphan_id)) is None
    events = await read_stream(client, str(orphan_id))
    assert [e.event for e in events] == ["message.start", "content.delta", "error", "message.end"]
    assert events[-1].data["status"] == "interrupted"
    # Переподключение с позиции последнего события — сразу конец, без повтора начала.
    after = await read_stream(client, str(orphan_id), last_event_id=2)
    assert [e.event for e in after] == ["error", "message.end"]


async def test_delete_search_pin_and_folders(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chats = []
    for text in (
        "Как оформить командировку в Казань",
        "Порядок предоставления отпусков",
        "SKU-12345 где заказ",
    ):
        chat_id = await new_chat(client)
        sent = await send(client, chat_id, text)
        await read_stream(client, sent["assistant_message"]["id"])
        chats.append(chat_id)

    # Поиск по слову из сообщения в другой словоформе и по коду (§7.2).
    hits = (await client.get("/api/chats/search", params={"q": "отпуск"})).json()
    assert [h["chat_id"] for h in hits] == [chats[1]]
    assert any(f["match"] for f in hits[0]["fragments"])
    assert hits[0]["message_id"] is not None
    code_hits = (await client.get("/api/chats/search", params={"q": "SKU-12345"})).json()
    assert [h["chat_id"] for h in code_hits] == [chats[2]]

    # Закрепление и папки.
    await client.request(
        "PATCH", f"/api/chats/{chats[0]}", json={"pinned": True, "title": "Командировка"}
    )
    pinned = (await client.get("/api/chats", params={"pinned": True})).json()["items"]
    assert [(c["id"], c["title"]) for c in pinned] == [(chats[0], "Командировка")]
    folder = (await client.post("/api/folders", json={"name": "Кадры"})).json()
    await client.request("PATCH", f"/api/chats/{chats[1]}", json={"folder_id": folder["id"]})
    in_folder = (await client.get("/api/chats", params={"folder_id": folder["id"]})).json()["items"]
    assert [c["id"] for c in in_folder] == [chats[1]]
    await client.request("DELETE", f"/api/folders/{folder['id']}", params={"chats": "move"})
    assert (await client.get(f"/api/chats/{chats[1]}")).json()["folder_id"] is None

    # Мягкое удаление: у пользователя чата нет, в БД — есть.
    assert (await client.request("DELETE", f"/api/chats/{chats[1]}")).status_code == 204
    assert (await client.get(f"/api/chats/{chats[1]}")).status_code == 404
    assert chats[1] not in [c["id"] for c in (await client.get("/api/chats")).json()["items"]]
    assert (await client.get("/api/chats/search", params={"q": "отпуск"})).json() == []
    async with app.state.db_sessions() as db:
        row = await db.scalar(select(Chat).where(Chat.id == chats[1]))
        assert row is not None and row.deleted_at is not None


async def test_feedback(make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str) -> None:
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "вопрос")
    answer_id = sent["assistant_message"]["id"]
    await read_stream(client, answer_id)
    body = {"rating": -1, "reasons": ["inaccurate", "incomplete"], "comment": " мало деталей "}
    response = await client.request("PUT", f"/api/messages/{answer_id}/feedback", json=body)
    assert response.json() == {
        "rating": -1,
        "reasons": ["inaccurate", "incomplete"],
        "comment": "мало деталей",
    }
    like = await client.request(
        "PUT", f"/api/messages/{answer_id}/feedback", json={"rating": 1, "reasons": ["other"]}
    )
    assert like.json()["reasons"] == []  # причины — только у дизлайка
    detail = (await client.get(f"/api/chats/{chat_id}")).json()
    assert detail["messages"][-1]["feedback"]["rating"] == 1
    await client.request("DELETE", f"/api/messages/{answer_id}/feedback")
    assert (await client.get(f"/api/chats/{chat_id}")).json()["messages"][-1]["feedback"] is None


async def test_idor_other_users_chat_is_invisible(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """§18.2: пользователь B не может прочитать, изменить или удалить объекты пользователя A."""
    _, owner = await _client(make_client, infra, tmp_path, fake_llm_url, login="petrov")
    _, other = await _client(make_client, infra, tmp_path, fake_llm_url, login="kim")
    chat_id = await new_chat(owner)
    sent = await send(owner, chat_id, "секрет")
    answer_id = sent["assistant_message"]["id"]
    await read_stream(owner, answer_id)
    folder_id = (await owner.post("/api/folders", json={"name": "Моя"})).json()["id"]

    attempts = [
        ("GET", f"/api/chats/{chat_id}", None),
        ("PATCH", f"/api/chats/{chat_id}", {"title": "взлом"}),
        ("DELETE", f"/api/chats/{chat_id}", None),
        ("POST", f"/api/chats/{chat_id}/messages", {"content": "x"}),
        ("GET", f"/api/messages/{answer_id}/stream", None),
        ("POST", f"/api/messages/{answer_id}/regenerate", {}),
        ("POST", f"/api/messages/{answer_id}/stop", None),
        ("PUT", f"/api/messages/{answer_id}/feedback", {"rating": 1}),
        ("DELETE", f"/api/messages/{answer_id}/feedback", None),
        ("PATCH", f"/api/folders/{folder_id}", {"name": "x"}),
        ("DELETE", f"/api/folders/{folder_id}", None),
    ]
    for method, url, body in attempts:
        response = await other.request(method, url, json=body)
        assert response.status_code == 404, (method, url, response.status_code)
    # Перенос своего чата в чужую папку тоже невозможен.
    own = await new_chat(other)
    response = await other.request("PATCH", f"/api/chats/{own}", json={"folder_id": folder_id})
    assert response.status_code == 404
    assert (await other.get("/api/chats/search", params={"q": "секрет"})).json() == []
    assert (await other.get("/api/folders")).json() == []
    assert (await owner.get(f"/api/chats/{chat_id}")).json()["title"] is not None
