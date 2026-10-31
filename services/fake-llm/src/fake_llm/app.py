"""OpenAI-совместимый fake-llm: /v1/chat/completions, /v1/embeddings, /v1/rerank, /v1/models.

Формат ответов повторяет vLLM: размышления — отдельным полем дельты (как с ``--reasoning-parser``),
вызовы инструментов — ``tool_calls`` по кускам, usage — последним чанком при
``stream_options.include_usage``. Имя поля размышлений настраивается (``FAKE_LLM_REASONING_FIELD``):
в разных версиях vLLM это ``reasoning`` или ``reasoning_content``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from fake_llm.scenarios import Scenario, Step, resolve, split_words, tool_call_payload


@dataclass(frozen=True)
class FakeSettings:
    slow_delay_s: float = 0.3
    reasoning_field: str = "reasoning"  # reasoning | reasoning_content | both
    embed_dim: int = 1024
    models: tuple[str, ...] = (
        "fake-chat",
        "fake-coder",
        "fake-utility",
        "fake-guard",
        "fake-embed",
        "fake-rerank",
    )

    @classmethod
    def from_env(cls) -> FakeSettings:
        models = os.environ.get("FAKE_LLM_MODELS")
        return cls(
            slow_delay_s=float(os.environ.get("FAKE_LLM_SLOW_DELAY_S", cls.slow_delay_s)),
            reasoning_field=os.environ.get("FAKE_LLM_REASONING_FIELD", cls.reasoning_field),
            embed_dim=int(os.environ.get("FAKE_LLM_EMBED_DIM", cls.embed_dim)),
            models=tuple(m.strip() for m in models.split(",")) if models else cls.models,
        )


class SimulatedDisconnect(Exception):  # noqa: N818 — имя описывает сценарий, а не ошибку
    """Обрыв стрима посреди ответа (сценарий disconnect)."""


def _count_tokens(text: str) -> int:
    return len(split_words(text))


def _prompt_tokens(body: dict[str, Any]) -> int:
    return sum(_count_tokens(json.dumps(m, ensure_ascii=False)) for m in body.get("messages", []))


def _reasoning_delta(settings: FakeSettings, text: str) -> dict[str, str]:
    if settings.reasoning_field == "both":
        return {"reasoning": text, "reasoning_content": text}
    return {settings.reasoning_field: text}


def _usage(body: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    reasoning = sum(_count_tokens(s.text) for s in scenario.steps if s.kind == "reasoning")
    completion = sum(_count_tokens(s.text) for s in scenario.steps) + sum(
        5 for s in scenario.steps if s.kind == "tool_call"
    )
    prompt = _prompt_tokens(body)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "completion_tokens_details": {"reasoning_tokens": reasoning},
    }


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": "server_error", "code": status}},
    )


def create_app(settings: FakeSettings | None = None) -> FastAPI:
    settings = settings or FakeSettings.from_env()
    app = FastAPI(title="fake-llm", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        data = [
            {"id": m, "object": "model", "created": 0, "owned_by": "fake-llm"}
            for m in settings.models
        ]
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions", response_model=None)
    async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
        body: dict[str, Any] = await request.json()
        scenario = resolve(body, settings.slow_delay_s)
        if scenario.http_error:
            return _error(scenario.http_error, f"fake-llm: ошибка по сценарию {scenario.name}")
        model = body.get("model", "fake-chat")
        if body.get("stream"):
            return StreamingResponse(
                _stream(settings, body, scenario, model), media_type="text/event-stream"
            )
        return JSONResponse(_complete(settings, body, scenario, model))

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> dict[str, Any]:
        body: dict[str, Any] = await request.json()
        inputs = body.get("input", [])
        texts: list[str] = [inputs] if isinstance(inputs, str) else list(inputs)
        dim = int(body.get("dimensions") or settings.embed_dim)
        data = [
            {"object": "embedding", "index": i, "embedding": embed(t, dim)}
            for i, t in enumerate(texts)
        ]
        tokens = sum(_count_tokens(t) for t in texts)
        return {
            "object": "list",
            "data": data,
            "model": body.get("model", "fake-embed"),
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        }

    @app.post("/v1/rerank")
    @app.post("/rerank")
    async def rerank(request: Request) -> dict[str, Any]:
        body: dict[str, Any] = await request.json()
        query: str = body.get("query", "")
        documents = [
            d if isinstance(d, str) else d.get("text", "") for d in body.get("documents", [])
        ]
        scores = [(overlap_score(query, d), i) for i, d in enumerate(documents)]
        scores.sort(key=lambda pair: pair[0], reverse=True)
        scored = [
            {"index": i, "document": {"text": documents[i]}, "relevance_score": score}
            for score, i in scores
        ]
        top_n = body.get("top_n") or len(scored)
        tokens = _count_tokens(query) * len(documents) + sum(_count_tokens(d) for d in documents)
        return {
            "id": f"rerank-{uuid.uuid4().hex}",
            "model": body.get("model", "fake-rerank"),
            "usage": {"total_tokens": tokens},
            "results": scored[:top_n],
        }

    return app


def _complete(
    settings: FakeSettings, body: dict[str, Any], scenario: Scenario, model: str
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": None}
    content = "".join(s.text for s in scenario.steps if s.kind == "content")
    reasoning = "".join(s.text for s in scenario.steps if s.kind == "reasoning")
    tool_calls = [
        tool_call_payload(s, f"call_{i}")
        for i, s in enumerate(scenario.steps)
        if s.kind == "tool_call"
    ]
    if content:
        message["content"] = content
    if reasoning:
        message.update(_reasoning_delta(settings, reasoning))
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": scenario.finish_reason}],
        "usage": _usage(body, scenario),
    }


async def _stream(
    settings: FakeSettings, body: dict[str, Any], scenario: Scenario, model: str
) -> AsyncIterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def pause() -> None:
        await asyncio.sleep(scenario.delay_s)

    yield chunk({"role": "assistant", "content": ""})
    tool_index = 0
    for step in scenario.steps:
        if step.kind == "disconnect":
            raise SimulatedDisconnect
        if step.kind in ("reasoning", "content"):
            for piece in split_words(step.text):
                await pause()
                delta = (
                    _reasoning_delta(settings, piece)
                    if step.kind == "reasoning"
                    else {"content": piece}
                )
                yield chunk(delta)
        elif step.kind == "tool_call":
            yield from_tool_call(chunk, step, tool_index)
            tool_index += 1

    yield chunk({}, scenario.finish_reason)
    if (body.get("stream_options") or {}).get("include_usage"):
        usage_payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [],
            "usage": _usage(body, scenario),
        }
        yield f"data: {json.dumps(usage_payload, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def from_tool_call(chunk: Any, step: Step, index: int) -> str:
    """Вызов инструмента: заголовок с именем, затем аргументы по кускам — как у vLLM."""
    payload = tool_call_payload(step, f"call_{uuid.uuid4().hex[:12]}")
    arguments = payload["function"]["arguments"]
    head = {
        "index": index,
        "id": payload["id"],
        "type": "function",
        "function": {"name": step.tool_name, "arguments": ""},
    }
    parts = [chunk({"tool_calls": [head]})]
    for i in range(0, len(arguments), 8):
        parts.append(
            chunk(
                {"tool_calls": [{"index": index, "function": {"arguments": arguments[i : i + 8]}}]}
            )
        )
    return "".join(parts)


def embed(text: str, dim: int) -> list[float]:
    """Детерминированный «мешок слов»: тексты с общими словами получают близкие векторы."""
    vector = [0.0] * dim
    words = re.findall(r"\w+", text.lower()) or [""]
    for word in words:
        seed = int.from_bytes(hashlib.sha256(word.encode()).digest()[:8], "big")
        rng = random.Random(seed)  # noqa: S311 — не криптография, нужна воспроизводимость
        for i in range(dim):
            vector[i] += rng.gauss(0.0, 1.0)
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _stems(text: str) -> set[str]:
    """Грубый «стемминг» для мока: первые 5 букв слова (договора/договору → догов)."""
    return {w[:5] for w in re.findall(r"\w+", text.lower()) if len(w) > 1}


def overlap_score(query: str, document: str) -> float:
    """Доля основ слов запроса, встречающихся в документе, — балл 0..1 для реранка."""
    q = _stems(query)
    d = _stems(document)
    return round(len(q & d) / len(q), 4) if q else 0.0
