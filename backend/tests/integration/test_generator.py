"""Исполнитель генерации (ADR-0013): api ставит задание в очередь, выполняет отдельный процесс.

Исполнитель здесь — тот же ``Executor``, что в сервисе ``generator``, запущенный задачей в цикле
теста со своим ``GenerationManager`` (как отдельный процесс: общие с api только Redis и БД).
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.core.config import REPO_ROOT
from app.modules.chats.models import Message
from app.modules.completions.executor import Executor, alive, parse_job
from app.modules.completions.generation import GenerationManager
from app.modules.completions.prompt import PromptRenderer
from app.modules.completions.streaming import QUEUE_KEY, alive_key, executor_key, stream_key
from tests.integration.conftest import (
    ApiClient,
    Infra,
    chat_settings,
    new_chat,
    read_stream,
    send,
)


async def _client(
    make_client: Any, infra: Infra, tmp_path: Path, url: str, **generation: Any
) -> tuple[FastAPI, ApiClient]:
    settings = chat_settings(infra, tmp_path, url, generation={"mode": "queue", **generation})
    app, client = await make_client(settings)
    await client.login("petrov")
    return app, client


def _executor(app: FastAPI) -> Executor:
    state = app.state
    manager = GenerationManager(
        settings=state.settings,
        redis=state.redis,
        sessions=state.db_sessions,
        registry=state.models,
        renderer=PromptRenderer(state.settings.config_dir / "prompts"),
        storage=state.storage,
        dispatcher=state.dispatcher,
        limits=state.limits,
    )
    return Executor(manager, state.redis, state.settings, name="test")


@asynccontextmanager
async def running(executor: Executor) -> AsyncIterator[asyncio.Task[None]]:
    task = asyncio.create_task(executor.run())
    try:
        yield task
    finally:
        executor.stop()
        await task


async def _status(app: FastAPI, message_id: str) -> str:
    async with app.state.db_sessions() as db:
        row = await db.get(Message, uuid.UUID(message_id))
        assert row is not None
        return str(row.status)


async def _wait(condition: Any) -> None:
    """Ждёт состояния исполнителя или Redis: событий для подписки у них нет — только опрос."""
    async with asyncio.timeout(10):
        while not await condition():  # noqa: ASYNC110
            await asyncio.sleep(0.02)


def test_parse_job() -> None:
    message_id = uuid.uuid4()
    assert parse_job(json.dumps({"message_id": str(message_id), "request_id": "r1"})) == (
        message_id,
        "r1",
    )
    assert parse_job(json.dumps({"message_id": str(message_id)})) == (message_id, None)
    for bad in ("", "не json", "[]", '{"message_id": "x"}', "{}"):
        assert parse_job(bad) is None


async def test_api_only_enqueues_and_job_waits_for_executor(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Задание переживает отсутствие исполнителя и «перезапуск» api, затем выполняется."""
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "Вопрос через очередь")
    message_id = sent["assistant_message"]["id"]

    # api ничего не генерирует сам: задание лежит в очереди, ответ ждёт.
    assert not app.state.generations.tasks
    [raw] = await app.state.redis.lrange(QUEUE_KEY, 0, -1)
    assert json.loads(raw)["message_id"] == message_id and json.loads(raw)["request_id"]
    assert not await app.state.redis.exists(stream_key(message_id))
    # Стартующий api проверяет осиротевшие ответы — ожидающий в очереди к ним не относится.
    assert await app.state.generations.mark_orphaned_interrupted() == 0
    assert await _status(app, message_id) == "streaming"

    executor = _executor(app)
    async with running(executor):
        events = await read_stream(client, message_id)
        assert await alive(app.state.settings, "test")
    text = "".join(e.data["text"] for e in events if e.event == "content.delta")
    assert text.endswith("ответ fake-llm на запрос: «Вопрос через очередь».")
    assert events[-1].data == {"status": "completed", "finish_reason": "stop"}
    assert await app.state.redis.llen(QUEUE_KEY) == 0
    # Исполнитель остановлен — отметки больше нет (healthcheck `generator check`).
    assert not await app.state.redis.exists(executor_key("test"))


async def test_expired_job_is_not_executed(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "Не дождусь")
    message_id = sent["assistant_message"]["id"]
    # Время ожидания вышло: ключ истёк, проверка осиротевших пометила ответ прерванным.
    await app.state.redis.delete(alive_key(message_id))
    assert await app.state.generations.mark_orphaned_interrupted() == 1

    executor = _executor(app)
    async with running(executor):
        await _wait(lambda: _is_zero(app.state.redis.llen(QUEUE_KEY)))
    assert not executor.manager.tasks
    assert await _status(app, message_id) == "interrupted"
    assert not await app.state.redis.exists(stream_key(message_id))


async def _is_zero(value: Any) -> bool:
    return int(await value) == 0


async def test_stop_while_queued(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "[[scenario:slow]] передумал")
    message_id = sent["assistant_message"]["id"]
    assert (await client.post(f"/api/messages/{message_id}/stop")).status_code in (200, 202, 204)

    async with running(_executor(app)):
        events = await read_stream(client, message_id)
    assert events[-1].data == {"status": "stopped", "finish_reason": "stop_requested"}
    assert not [e for e in events if e.event == "content.delta"]


async def test_shutdown_lets_running_answers_finish(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "[[scenario:slow]] доработай меня")
    message_id = sent["assistant_message"]["id"]

    executor = _executor(app)
    run = asyncio.create_task(executor.run())
    await _wait(lambda: _has(executor, message_id))
    executor.stop()  # SIGTERM: новых заданий не брать, идущие — доработать
    # Сообщение, пришедшее во время остановки, остаётся в очереди следующему исполнителю.
    other = await send(client, await new_chat(client), "Подожду следующего")
    await run
    assert await _status(app, message_id) == "completed"
    assert await app.state.redis.llen(QUEUE_KEY) == 1
    assert await _status(app, other["assistant_message"]["id"]) == "streaming"

    async with running(_executor(app)):
        events = await read_stream(client, other["assistant_message"]["id"])
    assert events[-1].data["status"] == "completed"


async def _has(executor: Executor, message_id: str) -> bool:
    return uuid.UUID(message_id) in executor.manager.tasks


async def test_shutdown_without_grace_interrupts(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, client = await _client(
        make_client, infra, tmp_path, fake_llm_url, shutdown_grace_seconds=0
    )
    chat_id = await new_chat(client)
    sent = await send(client, chat_id, "[[scenario:slow]] не успею")
    message_id = sent["assistant_message"]["id"]
    executor = _executor(app)
    run = asyncio.create_task(executor.run())
    await _wait(lambda: _has(executor, message_id))
    executor.stop()
    await run
    assert await _status(app, message_id) == "interrupted"


async def test_max_concurrent_keeps_the_rest_in_queue(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    app, client = await _client(make_client, infra, tmp_path, fake_llm_url, max_concurrent=1)
    first = await send(client, await new_chat(client), "[[scenario:slow]] первый")
    second = await send(client, await new_chat(client), "второй")
    executor = _executor(app)
    async with running(executor):
        await _wait(lambda: _has(executor, first["assistant_message"]["id"]))
        # Место одно: второй ответ ждёт в очереди, пока идёт первый.
        await asyncio.sleep(0.2)
        assert len(executor.manager.tasks) == 1
        assert await app.state.redis.llen(QUEUE_KEY) == 1
        for sent in (first, second):
            events = await read_stream(client, sent["assistant_message"]["id"])
            assert events[-1].data["status"] == "completed"


async def test_generator_process_runs_jobs_and_exits_on_sigterm(
    make_client: Any, infra: Infra, tmp_path: Path, fake_llm_url: str
) -> None:
    """Настоящая точка входа сервиса: ``python -m app.cli generator run`` отдельным процессом."""
    _, client = await _client(make_client, infra, tmp_path, fake_llm_url)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "APP_ENV": "test",
        "APP_DATABASE_URL": infra.database_url,
        "APP_REDIS_URL": infra.redis_url,
        "APP_STORAGE__ROOT": str(tmp_path / "storage"),
        "APP_GENERATION__MODE": "queue",
        **{
            f"APP_MODELS__{role.upper()}__{key}": value
            for role in ("chat", "utility", "guard", "rerank", "embed")
            for key, value in (("BASE_URL", fake_llm_url), ("MODEL", f"fake-{role}"))
        },
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.cli",
        "generator",
        "run",
        cwd=REPO_ROOT / "backend",
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        sent = await send(client, await new_chat(client), "Вопрос отдельному процессу")
        events = await read_stream(client, sent["assistant_message"]["id"])
        assert events[-1].data == {"status": "completed", "finish_reason": "stop"}
        process.send_signal(signal.SIGTERM)
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        assert process.returncode == 0, stderr.decode()[-2000:]
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
