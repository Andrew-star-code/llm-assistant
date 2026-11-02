"""Похожие примеры «вопрос → SQL» для ``describe_dataset`` (§9.5): до 5 по эмбеддингам.

Эмбеддинги — OpenAI-совместимый ``/v1/embeddings`` (bge-m3 стенда); вопросы примеров кэшируются.
Нет модели или она недоступна — первые примеры по порядку в каталоге.
"""

from __future__ import annotations

import math

import httpx

from data_gateway.catalog import Example

TOP = 5


class Ranker:
    def __init__(self, url: str | None, model: str, timeout_s: float = 5.0) -> None:
        self.url = url.rstrip("/") if url else None
        self.model = model
        self.timeout_s = timeout_s
        self._cache: dict[str, list[float]] = {}

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        missing = [t for t in texts if t not in self._cache]
        if missing:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    f"{self.url}/embeddings", json={"model": self.model, "input": missing}
                )
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda d: d["index"])
            for text, item in zip(missing, data, strict=True):
                self._cache[text] = item["embedding"]
        return [self._cache[t] for t in texts]

    async def top(self, question: str | None, examples: list[Example]) -> list[Example]:
        if not question or not self.url or len(examples) <= TOP:
            return examples[:TOP]
        try:
            vectors = await self._embed([question, *(e.question for e in examples)])
        except (httpx.HTTPError, KeyError, ValueError):
            return examples[:TOP]
        query, rest = vectors[0], vectors[1:]
        scored = sorted(zip(examples, rest, strict=True), key=lambda pair: -_cosine(query, pair[1]))
        return [e for e, _ in scored[:TOP]]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
