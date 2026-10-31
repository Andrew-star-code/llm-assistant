"""Хранилище фрагментов в Qdrant (§10.2).

Три коллекции документов с одинаковой схемой: именованный вектор ``dense`` (bge-m3, косинус) и
разрежённый ``bm25`` с модификатором IDF — BM25 считает сам Qdrant из текста (``qdrant/bm25``,
русский стемминг и стоп-слова) одинаково при записи и в запросе.

| Коллекция | Чьи фрагменты | Ключ документа |
| --- | --- | --- |
| ``kb_chunks`` | общие и ролевые базы | ``document_id`` (kb_documents) |
| ``personal_chunks`` | личные базы, ``owner_id`` — tenant-индекс | ``document_id`` |
| ``attachment_chunks`` | вложения чатов | ``document_id`` = id файла |

Id точки — ``uuid5(document_id:version:chunk_index)``: новая версия документа записывается рядом,
затем старые точки удаляются (поиск не видит «дыры»), а соседние чанки достаются по вычисленным id.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import structlog
from qdrant_client import AsyncQdrantClient, models

from app.core.config import Bm25Settings, Settings
from app.modules.ingestion.chunking import Chunk
from app.modules.llm.registry import ModelRegistry

log = structlog.stdlib.get_logger("app.rag")

KB_COLLECTION = "kb_chunks"
PERSONAL_COLLECTION = "personal_chunks"
ATTACHMENT_COLLECTION = "attachment_chunks"
COLLECTIONS = (KB_COLLECTION, PERSONAL_COLLECTION, ATTACHMENT_COLLECTION)
EMBED_ROLE = "embed"
EMBED_BATCH = 32
UPSERT_BATCH = 128
KEYWORD_FIELDS = ("kb_id", "document_id", "chat_id", "file_id", "level")


def chunk_id(document_id: UUID | str, version: int, index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"{document_id}:{version}:{index}"))


def qdrant_client(settings: Settings) -> AsyncQdrantClient:
    api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    return AsyncQdrantClient(
        url=settings.qdrant_url, api_key=api_key, timeout=30, check_compatibility=False
    )


def bm25_document(text: str, bm25: Bm25Settings) -> models.Document:
    return models.Document(
        text=text,
        model=bm25.model,
        options={"language": bm25.language, "avg_len": bm25.avg_len},
    )


async def embed(registry: ModelRegistry, texts: Sequence[str]) -> list[list[float]]:
    endpoint = registry.get(EMBED_ROLE)
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = list(texts[start : start + EMBED_BATCH])
        response = await registry.client(EMBED_ROLE).embeddings.create(
            model=endpoint.model, input=batch
        )
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
    return vectors


async def ensure_collection(client: AsyncQdrantClient, name: str, dim: int) -> None:
    """Создаёт коллекцию; коллекцию без ``bm25`` (вложения этапа 3) пересоздаёт."""
    if await client.collection_exists(name):
        info = await client.get_collection(name)
        sparse = info.config.params.sparse_vectors or {}
        if "bm25" in sparse:
            return
        # Только дев-стенды этапа 3: там были временные индексы вложений без BM25.
        log.warning("rag.collection_recreated", collection=name, reason="no bm25 vector")
        await client.delete_collection(name)
    await client.create_collection(
        name,
        vectors_config={"dense": models.VectorParams(size=dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    for field in KEYWORD_FIELDS:
        await client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
    owner_schema: Any = models.KeywordIndexParams(
        type=models.KeywordIndexType.KEYWORD, is_tenant=name == PERSONAL_COLLECTION
    )
    await client.create_payload_index(name, "owner_id", owner_schema)
    await client.create_payload_index(name, "chunk_index", models.PayloadSchemaType.INTEGER)


@dataclass(frozen=True)
class DocumentRef:
    """Чей документ пишем: ключи payload, по которым потом фильтрует сервер."""

    collection: str
    document_id: UUID
    version: int
    title: str
    level: str  # global | role | personal | attachment
    kb_id: UUID | None = None
    owner_id: UUID | None = None
    file_id: UUID | None = None
    chat_id: UUID | None = None


def _payload(ref: DocumentRef, chunk: Chunk, embed_model: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "document_id": str(ref.document_id),
        "version": ref.version,
        "level": ref.level,
        "title": ref.title,
        "chunk_index": chunk.index,
        "page_from": chunk.page_from,
        "page_to": chunk.page_to,
        "section_path": list(chunk.section_path),
        "page_spans": [list(span) for span in chunk.page_spans],
        "text": chunk.text,
        "body": chunk.body,
        "embed_model": embed_model,
    }
    for key in ("kb_id", "owner_id", "file_id", "chat_id"):
        value = getattr(ref, key)
        if value is not None:
            payload[key] = str(value)
    return payload


async def write_document(
    client: AsyncQdrantClient,
    registry: ModelRegistry,
    ref: DocumentRef,
    chunks: Sequence[Chunk],
    bm25: Bm25Settings,
) -> int:
    """Записывает фрагменты новой версии и удаляет точки прежних версий документа."""
    if chunks:
        vectors = await embed(registry, [c.text for c in chunks])
        await ensure_collection(client, ref.collection, len(vectors[0]))
        embed_model = registry.get(EMBED_ROLE).model
        points = [
            models.PointStruct(
                id=chunk_id(ref.document_id, ref.version, chunk.index),
                vector={"dense": vector, "bm25": bm25_document(chunk.text, bm25)},
                payload=_payload(ref, chunk, embed_model),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        for start in range(0, len(points), UPSERT_BATCH):
            await client.upsert(
                ref.collection, points=points[start : start + UPSERT_BATCH], wait=True
            )
    await delete_document(client, ref.collection, ref.document_id, keep_version=ref.version)
    return len(chunks)


async def delete_document(
    client: AsyncQdrantClient,
    collection: str,
    document_id: UUID,
    *,
    keep_version: int | None = None,
) -> None:
    """Удаляет точки документа (кроме версии ``keep_version``) — поиск перестаёт их видеть сразу."""
    if not await client.collection_exists(collection):
        return
    must: list[models.Condition] = [
        models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id)))
    ]
    must_not: list[models.Condition] = []
    if keep_version is not None:
        must_not.append(
            models.FieldCondition(key="version", match=models.MatchValue(value=keep_version))
        )
    await client.delete(
        collection,
        points_selector=models.FilterSelector(filter=models.Filter(must=must, must_not=must_not)),
        wait=True,
    )
