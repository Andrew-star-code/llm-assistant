"""Завершение ответа (§8.8): сохранение в БД, учёт токенов и лимиты, заголовок чата, метрики,
закрытие потока событий. ``finish`` вызывается ровно один раз на ответ при любом исходе.
"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import suppress
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.db import utcnow
from app.modules.chats.models import Chat, Message
from app.modules.completions.state import (
    RESULT_PREVIEW_CHARS,
    UTILITY_ROLE,
    Deps,
    GenerationResult,
)
from app.modules.completions.streaming import (
    EventWriter,
    alive_key,
    cancel_key,
)
from app.modules.limits import service as limits_service
from app.modules.llm.stream import Usage
from app.modules.rag.models import MessageSource
from app.modules.rag.service import (
    cited_indexes,
)
from app.modules.tools.models import ToolCall

log = structlog.stdlib.get_logger("app.completions")

TITLE_MAX_WORDS = 6
TITLE_MAX_CHARS = 80


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


def observe(result: GenerationResult, latency_ms: int, context: dict[str, Any]) -> None:
    """Метрики завершённого ответа (§16.6). Метки — только из закрытых наборов."""
    role = result.model_role or "unknown"
    metrics.GENERATIONS.labels(role, result.status).inc()
    metrics.GENERATION_DURATION.labels(role).observe(latency_ms / 1000)
    if result.ttft_ms is not None:
        metrics.GENERATION_TTFT.labels(role).observe(result.ttft_ms / 1000)
    if result.usage is not None:
        tokens = metrics.GENERATION_TOKENS
        tokens.labels(role, "prompt").inc(result.usage.prompt_tokens)
        tokens.labels(role, "completion").inc(result.usage.completion_tokens)
        tokens.labels(role, "reasoning").inc(result.usage.reasoning_tokens or 0)
    if result.model_retries:
        metrics.MODEL_RETRIES.labels(role).inc(result.model_retries)
    for outcome in result.tools:
        # Имя, которое выдумала модель, в метку не идёт — иначе число рядов не ограничено.
        tool = metrics.UNKNOWN_TOOL if outcome.label == "tools.unknown" else outcome.tool
        metrics.TOOL_CALLS.labels(tool, outcome.status).inc()
        metrics.TOOL_DURATION.labels(tool).observe(outcome.duration_ms / 1000)
    for key, kind in (
        ("history_dropped", "history"),
        ("tool_results_dropped", "tool_results_dropped"),
        ("tool_results_truncated", "tool_results_truncated"),
    ):
        if context.get(key):
            metrics.CONTEXT_TRIMS.labels(kind).inc()


async def generate_title(deps: Deps, question: str, result: GenerationResult) -> str:
    try:
        plan = deps.registry.plan(UTILITY_ROLE, thinking=False)
        params = {**plan.params, "max_tokens": 32}
        prompt = deps.renderer.render("utility/title.md.j2", message=question[:2000])
        response = await asyncio.wait_for(
            deps.registry.client(UTILITY_ROLE).chat.completions.create(
                messages=[{"role": "user", "content": prompt}], **params
            ),
            timeout=deps.settings.chat.title_timeout_seconds,
        )
        if response.usage is not None:
            result.title_usage = Usage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                reasoning_tokens=None,
            )
        title = clean_title(response.choices[0].message.content or "")
        if title:
            return title
    except Exception as exc:
        log.warning("completions.title_failed", error=f"{type(exc).__name__}: {exc}"[:300])
    return fallback_title(question)


def record_usage(db: AsyncSession, message: Message, result: GenerationResult) -> None:
    """Строки ``usage_records``: ответ (``chat``) и заголовок (``title``) — §12.3, §14."""
    if result.user_id is None:
        return
    if result.usage is not None and result.model_role is not None:
        limits_service.record_usage(
            db, user_id=result.user_id, kind="chat", model_role=result.model_role,
            thinking=result.thinking, usage=result.usage, chat_id=message.chat_id,
            message_id=message.id,
        )  # fmt: skip
    if result.title_usage is not None:
        limits_service.record_usage(
            db, user_id=result.user_id, kind="title", model_role=UTILITY_ROLE,
            thinking=False, usage=result.title_usage, chat_id=message.chat_id,
            message_id=message.id,
        )  # fmt: skip


async def charge(deps: Deps, result: GenerationResult) -> dict[str, Any] | None:
    """Списывает токены ответа в лимиты и возвращает остатки для события ``limits``.

    Заголовок и guard — служебные вызовы: пишутся в учёт, но лимит пользователя не тратят.
    Сбой Redis не должен ломать уже сохранённый ответ — он только логируется.
    """
    if result.user_id is None:
        return None
    try:
        if result.usage is not None and result.model_role is not None:
            await deps.limits.commit_tokens(
                user_id=result.user_id, model_role=result.model_role,
                thinking=result.thinking, usage=result.usage,
            )  # fmt: skip
        async with deps.sessions() as db:
            statuses = await deps.limits.status(db, result.user_id)
        return limits_service.status_payload(statuses, deps.limits.tz)
    except Exception:
        log.exception("completions.limits_charge_failed")
        return None


async def finish(
    deps: Deps,
    message_id: UUID,
    result: GenerationResult,
    trace: dict[str, Any],
    started: float,
    writer: EventWriter,
    *,
    title_for: str | None,
    title_now: str | None = None,
) -> None:
    """Сохраняет ответ в БД и закрывает поток событий. Вызывается ровно один раз."""
    latency_ms = int((time.monotonic() - started) * 1000)
    observe(result, latency_ms, trace.get("context") or {})
    usage = result.usage
    title = await generate_title(deps, title_for, result) if title_for else title_now
    chat_id: UUID | None = None
    try:
        async with deps.sessions() as db:
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
                if result.reasoning_started is not None and result.reasoning_ms is None:
                    result.reasoning_ms = int((time.monotonic() - result.reasoning_started) * 1000)
                if result.reasoning_ms is not None:
                    trace["reasoning_ms"] = result.reasoning_ms
                if result.tools:
                    trace["tools"] = [
                        {
                            "call_id": o.call_id,
                            "tool": o.tool,
                            "status": o.status,
                            "duration_ms": o.duration_ms,
                            "visibility": o.visibility,
                            "arguments": o.arguments,
                            "result_preview": o.content[:2000],
                        }
                        for o in result.tools
                    ]
                    for outcome in result.tools:
                        db.add(
                            ToolCall(
                                message_id=message_id,
                                call_id=outcome.call_id,
                                tool=outcome.tool,
                                arguments=outcome.arguments,
                                result_preview=outcome.content[:RESULT_PREVIEW_CHARS],
                                status=outcome.status,
                                duration_ms=outcome.duration_ms,
                                visibility=outcome.visibility,
                                iteration=outcome.iteration,
                                label=outcome.label,
                                label_params=outcome.label_params or None,
                            )
                        )
                if result.book and result.book.fragments:
                    cited = cited_indexes(message.content)
                    trace["sources"] = {
                        "offered": len(result.book.fragments),
                        "cited": sorted(cited),
                    }
                    for f in result.book.fragments:
                        db.add(
                            MessageSource(
                                message_id=message_id, index=f.index, kind=f.kind,
                                kb_id=UUID(f.kb_id) if f.kb_id else None,
                                document_id=UUID(f.document_id) if f.kind == "kb" else None,
                                file_id=UUID(f.file_id) if f.file_id else None,
                                chunk_id=f.chunk_id, title=f.title[:255], kb_name=f.kb_name,
                                page=f.page, section=f.section, snippet=f.snippet,
                                score=f.score, cited=f.index in cited,
                            )
                        )  # fmt: skip
                message.trace = {**(message.trace or {}), **trace}
                if usage:
                    message.prompt_tokens = usage.prompt_tokens
                    message.completion_tokens = usage.completion_tokens
                    message.reasoning_tokens = usage.reasoning_tokens
                record_usage(db, message, result)
                values: dict[str, Any] = {"last_message_at": utcnow()}
                if title:
                    values["title"] = title
                await db.execute(update(Chat).where(Chat.id == message.chat_id).values(**values))
                chat_id = message.chat_id
                await db.commit()
        # Фактические токены — в счётчики лимитов, после записи учёта (§12.3).
        limits_payload = await charge(deps, result)
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
            if limits_payload is not None:
                await writer.emit("limits", limits_payload)
            if title and chat_id:
                await writer.emit("title", {"chat_id": str(chat_id), "title": title})
            await writer.emit(
                "message.end", {"status": result.status, "finish_reason": result.finish_reason}
            )
            await writer.close()
    finally:
        await deps.redis.delete(alive_key(message_id), cancel_key(message_id))
        if result.user_id is not None:
            await deps.limits.release_slot(result.user_id, message_id)
        log.info(
            "completions.done",
            message_id=str(message_id),
            status=result.status,
            latency_ms=latency_ms,
            ttft_ms=result.ttft_ms,
        )
