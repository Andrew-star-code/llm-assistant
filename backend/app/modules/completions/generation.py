"""Генерация ответа (§2.2, §8): фоновая asyncio-задача на каждый ответ ассистента.

Шаги: сборка промпта → запрос к модели со стримингом → дельты в Redis Stream → сохранение
ответа, токенов и трассировки в Postgres → автозаголовок → ``message.end``.

* «Стоп» может попасть в любой процесс api: отмена — флаг ``gen:cancel:<id>`` в Redis; исполнитель
  проверяет его между чанками, закрывает запрос к модели и сохраняет частичный ответ (``stopped``).
* Остановка процесса: задачи отменяются и сохраняют ответ со статусом ``interrupted``; ответы,
  чьи исполнители умерли, помечает ``mark_orphaned_interrupted`` при старте.
"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import openai
import structlog
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.db import utcnow
from app.modules.chats.models import Chat, Message
from app.modules.chats.service import branch
from app.modules.completions.prompt import (
    PromptRenderer,
    PromptUser,
    Turn,
    build_messages,
    system_prompt,
)
from app.modules.completions.streaming import (
    ALIVE_TTL_SECONDS,
    PROTOCOL_VERSION,
    EventWriter,
    alive_key,
    cancel_key,
)
from app.modules.llm.registry import ModelRegistry
from app.modules.llm.stream import Delta, Finish, Usage, parse_stream
from app.modules.llm.tokens import TokenCounter
from app.modules.users.models import User
from app.modules.users.service import address_of

log = structlog.stdlib.get_logger("app.completions")

CHAT_ROLE = "chat"
UTILITY_ROLE = "utility"
CANCEL_CHECK_INTERVAL = 0.2
TITLE_MAX_WORDS = 6
TITLE_MAX_CHARS = 80


@dataclass
class GenerationResult:
    content: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    status: str = "completed"
    finish_reason: str | None = None
    usage: Usage | None = None
    ttft_ms: int | None = None
    error: dict[str, Any] | None = None


def clean_title(raw: str) -> str | None:
    """Первые слова ответа служебной модели без кавычек, разметки и точки в конце."""
    line = next((ln for ln in raw.strip().splitlines() if ln.strip()), "")
    line = re.sub(r"^(заголовок|title)\s*:\s*", "", line.strip(), flags=re.IGNORECASE)
    line = line.strip(" \t\"'«»`*#.").strip()
    words = line.split()
    if not words:
        return None
    return " ".join(words[:TITLE_MAX_WORDS])[:TITLE_MAX_CHARS]


def fallback_title(message: str) -> str:
    words = message.split()
    title = " ".join(words[:TITLE_MAX_WORDS])[:TITLE_MAX_CHARS]
    return title + ("…" if len(words) > TITLE_MAX_WORDS else "")


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, openai.APIStatusError):
        retryable = exc.status_code >= 500 or exc.status_code == 429
        return {
            "code": f"model_http_{exc.status_code}",
            "message": "Модель вернула ошибку",
            "retryable": retryable,
        }
    if isinstance(exc, openai.APITimeoutError):
        return {"code": "model_timeout", "message": "Модель не ответила вовремя", "retryable": True}
    if isinstance(exc, openai.APIConnectionError):
        return {"code": "model_unavailable", "message": "Модель недоступна", "retryable": True}
    return {"code": "internal_error", "message": "Не удалось получить ответ", "retryable": True}


class GenerationManager:
    def __init__(
        self,
        *,
        settings: Settings,
        redis: Redis,
        sessions: async_sessionmaker[AsyncSession],
        registry: ModelRegistry,
        renderer: PromptRenderer,
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.sessions = sessions
        self.registry = registry
        self.renderer = renderer
        self.tasks: dict[UUID, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------ управление

    async def start(self, message_id: UUID) -> None:
        # Ключ живости ставится до запуска задачи: SSE-читатель, пришедший раньше первого
        # события, будет ждать, а не решит, что генерация умерла.
        await self.redis.set(alive_key(message_id), "1", ex=ALIVE_TTL_SECONDS)
        task = asyncio.create_task(self._run(message_id), name=f"generation:{message_id}")
        self.tasks[message_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(message_id, None))

    async def request_stop(self, message_id: UUID) -> None:
        await self.redis.set(cancel_key(message_id), "1", ex=ALIVE_TTL_SECONDS * 10)

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def mark_orphaned_interrupted(self) -> int:
        """При старте: ответы в статусе streaming без живого исполнителя → interrupted."""
        async with self.sessions() as db:
            rows = (await db.scalars(select(Message).where(Message.status == "streaming"))).all()
            count = 0
            for message in rows:
                if message.id in self.tasks or await self.redis.exists(alive_key(message.id)):
                    continue
                message.status = "interrupted"
                message.error = {"code": "interrupted", "message": "Генерация прервана"}
                count += 1
            await db.commit()
        if count:
            log.warning("completions.orphans_interrupted", count=count)
        return count

    # ------------------------------------------------------------------ генерация

    async def _keep_alive(self, message_id: UUID) -> None:
        while True:
            await self.redis.set(alive_key(message_id), "1", ex=ALIVE_TTL_SECONDS)
            await asyncio.sleep(ALIVE_TTL_SECONDS / 3)

    async def _load(
        self, db: AsyncSession, message_id: UUID
    ) -> tuple[Message, Chat, User, list[Message]]:
        message = await db.get(Message, message_id)
        if message is None:
            raise LookupError(message_id)
        chat = await db.get(Chat, message.chat_id)
        user = await db.get(User, chat.user_id) if chat else None
        if chat is None or user is None:
            raise LookupError(message_id)
        all_messages = (
            await db.scalars(
                select(Message).where(Message.chat_id == chat.id, Message.deleted_at.is_(None))
            )
        ).all()
        return message, chat, user, branch(all_messages, message.parent_id)

    async def _run(self, message_id: UUID) -> None:
        started = time.monotonic()
        writer = EventWriter(self.redis, message_id, self.settings.chat.stream_ttl_seconds)
        keepalive = asyncio.create_task(self._keep_alive(message_id))
        result = GenerationResult()
        trace: dict[str, Any] = {}
        is_first_answer = False
        question = ""
        try:
            async with self.sessions() as db:
                message, chat, user, chain = await self._load(db, message_id)
                question = chain[-1].content if chain else ""
                history = [
                    Turn(m.role, m.content)  # type: ignore[arg-type]
                    for m in chain[:-1]
                    if m.status in ("completed", "stopped") and m.content
                ]
                is_first_answer = chat.title is None
                plan = self.registry.plan(CHAT_ROLE, thinking=message.thinking)
                prompt_user = PromptUser(
                    full_name=user.full_name,
                    title=user.title,
                    department=user.department,
                    address=address_of(user, self.settings),
                )
                prompt = build_messages(
                    system=system_prompt(self.renderer, self.settings, prompt_user, utcnow()),
                    history=history,
                    message=question,
                    endpoint=plan.endpoint,
                    counter=TokenCounter(plan.endpoint.tokenizer),
                )
                chat_id, parent_id = chat.id, message.parent_id
                message.model = plan.endpoint.model
                message.thinking = plan.thinking
                await db.commit()

            trace = {
                "model_role": plan.role,
                "model": plan.endpoint.model,
                "thinking": plan.thinking,
                **prompt.trace(),
            }
            await writer.emit(
                "message.start",
                {
                    "message_id": str(message_id),
                    "chat_id": str(chat_id),
                    "parent_id": str(parent_id) if parent_id else None,
                    "model": plan.endpoint.model,
                    "thinking": plan.thinking,
                    "protocol_version": PROTOCOL_VERSION,
                },
            )
            await self._stream(
                message_id, plan.role, prompt.messages, plan.params, writer, result, started
            )
            if result.usage is None:
                counter = TokenCounter(plan.endpoint.tokenizer)
                result.usage = Usage(
                    prompt_tokens=prompt.prompt_tokens,
                    completion_tokens=counter.count(
                        "".join(result.content) + "".join(result.reasoning)
                    ),
                    reasoning_tokens=counter.count("".join(result.reasoning)) or None,
                )
                trace["usage_estimated"] = True
        except asyncio.CancelledError:
            result.status = "interrupted"
            result.error = {"code": "interrupted", "message": "Генерация прервана"}
            await self._finish(message_id, result, trace, started, writer, title_for=None)
            raise
        except Exception as exc:
            log.exception("completions.failed", message_id=str(message_id))
            result.status = "error"
            result.error = _error_payload(exc)
            trace["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            await writer.emit("error", result.error)
        finally:
            keepalive.cancel()
        title_for = question if is_first_answer and result.status == "completed" else None
        await self._finish(message_id, result, trace, started, writer, title_for=title_for)

    async def _stream(
        self,
        message_id: UUID,
        role: str,
        messages: list[dict[str, Any]],
        params: dict[str, Any],
        writer: EventWriter,
        result: GenerationResult,
        started: float,
    ) -> None:
        client = self.registry.client(role)
        stream: AsyncStream[ChatCompletionChunk] = await client.chat.completions.create(  # type: ignore[call-overload]
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            **params,
        )
        last_check = time.monotonic()
        try:
            async for item in parse_stream(stream):
                if isinstance(item, Delta):
                    if result.ttft_ms is None:
                        result.ttft_ms = int((time.monotonic() - started) * 1000)
                    (result.content if item.kind == "content" else result.reasoning).append(
                        item.text
                    )
                    await writer.delta(item.kind, item.text)
                elif isinstance(item, Usage):
                    result.usage = item
                elif isinstance(item, Finish):
                    result.finish_reason = item.reason
                if time.monotonic() - last_check >= CANCEL_CHECK_INTERVAL:
                    last_check = time.monotonic()
                    if await self.redis.exists(cancel_key(message_id)):
                        result.status = "stopped"
                        result.finish_reason = "stop_requested"
                        break
        finally:
            await stream.close()
        if result.status != "stopped" and await self.redis.exists(cancel_key(message_id)):
            result.status = "stopped"

    async def _generate_title(self, question: str) -> str:
        try:
            plan = self.registry.plan(UTILITY_ROLE, thinking=False)
            params = {**plan.params, "max_tokens": 32}
            prompt = self.renderer.render("utility/title.md.j2", message=question[:2000])
            response = await asyncio.wait_for(
                self.registry.client(UTILITY_ROLE).chat.completions.create(
                    messages=[{"role": "user", "content": prompt}], **params
                ),
                timeout=self.settings.chat.title_timeout_seconds,
            )
            title = clean_title(response.choices[0].message.content or "")
            if title:
                return title
        except Exception as exc:
            log.warning("completions.title_failed", error=f"{type(exc).__name__}: {exc}"[:300])
        return fallback_title(question)

    async def _finish(
        self,
        message_id: UUID,
        result: GenerationResult,
        trace: dict[str, Any],
        started: float,
        writer: EventWriter,
        *,
        title_for: str | None,
    ) -> None:
        """Сохраняет ответ в БД и закрывает поток событий. Вызывается ровно один раз."""
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = result.usage
        title = await self._generate_title(title_for) if title_for else None
        chat_id: UUID | None = None
        try:
            async with self.sessions() as db:
                message = await db.get(Message, message_id)
                if message is not None:
                    message.content = "".join(result.content)
                    message.reasoning = "".join(result.reasoning) or None
                    message.status = result.status
                    message.finish_reason = result.finish_reason
                    message.ttft_ms = result.ttft_ms
                    message.latency_ms = latency_ms
                    message.error = (
                        {k: v for k, v in result.error.items() if k != "retryable"}
                        if result.error
                        else None
                    )
                    message.trace = {**(message.trace or {}), **trace}
                    if usage:
                        message.prompt_tokens = usage.prompt_tokens
                        message.completion_tokens = usage.completion_tokens
                        message.reasoning_tokens = usage.reasoning_tokens
                    values: dict[str, Any] = {"last_message_at": utcnow()}
                    if title:
                        values["title"] = title
                    await db.execute(
                        update(Chat).where(Chat.id == message.chat_id).values(**values)
                    )
                    chat_id = message.chat_id
                    await db.commit()
                    # TODO(stage-8): списание токенов в лимиты и usage_records (§12.3).
                    # TODO(stage-7): проверка guard-моделью (§9.6).
            with suppress(asyncio.CancelledError):
                if usage:
                    await writer.emit(
                        "usage",
                        {
                            "prompt_tokens": usage.prompt_tokens,
                            "completion_tokens": usage.completion_tokens,
                            "reasoning_tokens": usage.reasoning_tokens,
                        },
                    )
                if title and chat_id:
                    await writer.emit("title", {"chat_id": str(chat_id), "title": title})
                await writer.emit(
                    "message.end", {"status": result.status, "finish_reason": result.finish_reason}
                )
                await writer.close()
        finally:
            await self.redis.delete(alive_key(message_id), cancel_key(message_id))
            log.info(
                "completions.done",
                message_id=str(message_id),
                status=result.status,
                latency_ms=latency_ms,
                ttft_ms=result.ttft_ms,
            )
