"""Индекс вложений чата в Qdrant для ``search_in_documents`` (§9.2, §10.2).

Коллекция ``attachment_chunks``: именованный вектор ``dense`` (bge-m3), payload — ``file_id``,
``owner_id``, ``page``, ``chunk_index``, ``text``. Право на поиск задаёт сервер: фильтр по id
файлов текущего чата, а не аргументы модели.

TODO(stage-4): разрежённый вектор ``bm25``, гибридный поиск с RRF и реранкер — общий конвейер §10.4.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from qdrant_client import AsyncQdrantClient, models

from app.core.config import Settings
from app.modules.llm.registry import ModelRegistry

COLLECTION = "attachment_chunks"
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150
EMBED_BATCH = 32


@dataclass(frozen=True)
class Chunk:
    page: int
    index: int
    text: str


@dataclass(frozen=True)
class Hit:
    file_id: str
    page: int
    text: str
    score: float


def chunk_pages(pages: Sequence[str], *, title: str) -> list[Chunk]:
    """Чанки по страницам с перекрытием; к каждому — «Документ: … / стр. N» для контекста."""
    chunks: list[Chunk] = []
    for page_number, text in enumerate(pages, start=1):
        text = text.strip()
        start = 0
        while start < len(text):
            end = min(len(text), start + CHUNK_CHARS)
            if end < len(text):
                cut = text.rfind("\n", start + CHUNK_CHARS // 2, end)
                end = cut if cut > 0 else end
            body = text[start:end].strip()
            if body:
                chunks.append(
                    Chunk(
                        page_number, len(chunks), f"Документ: {title} / стр. {page_number}\n{body}"
                    )
                )
            if end >= len(text):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def qdrant_client(settings: Settings) -> AsyncQdrantClient:
    api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    return AsyncQdrantClient(
        url=settings.qdrant_url, api_key=api_key, timeout=30, check_compatibility=False
    )


async def embed(registry: ModelRegistry, texts: Sequence[str]) -> list[list[float]]:
    endpoint = registry.get("embed")
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = list(texts[start : start + EMBED_BATCH])
        response = await registry.client("embed").embeddings.create(
            model=endpoint.model, input=batch
        )
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
    return vectors


async def ensure_collection(client: AsyncQdrantClient, dim: int) -> None:
    if await client.collection_exists(COLLECTION):
        return
    await client.create_collection(
        COLLECTION,
        vectors_config={"dense": models.VectorParams(size=dim, distance=models.Distance.COSINE)},
    )
    for field in ("file_id", "owner_id"):
        await client.create_payload_index(COLLECTION, field, models.PayloadSchemaType.KEYWORD)


async def index_file(
    client: AsyncQdrantClient,
    registry: ModelRegistry,
    *,
    file_id: UUID,
    owner_id: UUID,
    title: str,
    pages: Sequence[str],
) -> int:
    chunks = chunk_pages(pages, title=title)
    await delete_file(client, file_id)
    if not chunks:
        return 0
    vectors = await embed(registry, [c.text for c in chunks])
    await ensure_collection(client, len(vectors[0]))
    points = [
        models.PointStruct(
            id=str(uuid5(NAMESPACE_URL, f"{file_id}/{chunk.index}")),
            vector={"dense": vector},
            payload={
                "file_id": str(file_id),
                "owner_id": str(owner_id),
                "page": chunk.page,
                "chunk_index": chunk.index,
                "text": chunk.text,
            },
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    await client.upsert(COLLECTION, points=points, wait=True)
    return len(points)


async def delete_file(client: AsyncQdrantClient, file_id: UUID) -> None:
    if not await client.collection_exists(COLLECTION):
        return
    await client.delete(
        COLLECTION,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="file_id", match=models.MatchValue(value=str(file_id))
                    )
                ]
            )
        ),
    )


async def search(
    client: AsyncQdrantClient,
    registry: ModelRegistry,
    *,
    query: str,
    file_ids: Sequence[UUID],
    limit: int = 6,
) -> list[Hit]:
    """Поиск только по переданным файлам — их список строит сервер (вложения текущего чата)."""
    if not file_ids or not await client.collection_exists(COLLECTION):
        return []
    [vector] = await embed(registry, [query])
    response = await client.query_points(
        COLLECTION,
        query=vector,
        using="dense",
        limit=limit,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="file_id", match=models.MatchAny(any=[str(f) for f in file_ids])
                )
            ]
        ),
        with_payload=True,
    )
    return [
        Hit(
            file_id=str(point.payload["file_id"]) if point.payload else "",
            page=int(point.payload["page"]) if point.payload else 0,
            text=str(point.payload["text"]) if point.payload else "",
            score=point.score,
        )
        for point in response.points
    ]
