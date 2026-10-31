"""Работа воркера (§9.3, §9.4): async-функции, которые вызывают задачи Celery и тесты.

* ``parse_job`` — разбор вложения: статус ``processing`` → Markdown с маркерами страниц и
  оглавление в хранилище → чанки в Qdrant для ``search_in_documents`` → ``ready`` или ``error``
  с понятной причиной (её видит пользователь в чипе файла).
* ``generate_job`` — создание файла по запросу модели и PDF-превью для Office-форматов.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.storage import LocalStorage
from app.modules.files.generate import (
    DocumentSpec,
    GeneratedFile,
    GenerationError,
    PresentationSpec,
    SpreadsheetSpec,
    create_document,
    create_presentation,
    create_spreadsheet,
    preview_pdf,
)
from app.modules.files.models import File
from app.modules.ingestion.index import index_file, qdrant_client
from app.modules.ingestion.parsers import ParseError, parse_file
from app.modules.llm.registry import ModelRegistry

log = structlog.stdlib.get_logger("app.worker")


@dataclass
class WorkerContext:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    storage: LocalStorage


@asynccontextmanager
async def worker_context(settings: Settings) -> AsyncIterator[WorkerContext]:
    # NullPool: у каждой задачи свой цикл событий, соединения между ними не переиспользуются.
    engine = create_async_engine(settings.database_url.get_secret_value(), poolclass=NullPool)
    try:
        yield WorkerContext(
            settings=settings,
            sessions=async_sessionmaker(engine, expire_on_commit=False),
            storage=LocalStorage(settings.storage.root),
        )
    finally:
        await engine.dispose()


async def _set_status(
    ctx: WorkerContext, file_id: str, status: str, error: str | None = None
) -> None:
    async with ctx.sessions() as db:
        row = await db.get(File, uuid.UUID(file_id))
        if row is not None:
            row.parse_status = status
            row.parse_error = error
            await db.commit()


async def parse_job(file_id: str, settings: Settings) -> None:
    async with worker_context(settings) as ctx:
        async with ctx.sessions() as db:
            row = await db.get(File, uuid.UUID(file_id))
            if row is None or row.deleted_at is not None:
                return
            row.parse_status = "processing"
            await db.commit()
            storage_key, file_type, filename, owner_id = (
                row.storage_key,
                row.file_type,
                row.filename,
                row.owner_id,
            )
        data = await ctx.storage.get(storage_key)
        if data is None:
            await _set_status(ctx, file_id, "error", "файл не найден в хранилище")
            return
        try:
            with tempfile.TemporaryDirectory(prefix="parse-") as tmp:
                source = Path(tmp) / f"source.{file_type}"
                source.write_bytes(data)
                parsed = await asyncio.wait_for(
                    asyncio.to_thread(parse_file, source, file_type, settings.files),
                    timeout=settings.files.parse_timeout_seconds,
                )
        except ParseError as exc:
            await _set_status(ctx, file_id, "error", str(exc))
            return
        except TimeoutError:
            await _set_status(ctx, file_id, "error", "превышено время обработки документа")
            return
        except Exception:
            log.exception("worker.parse_failed", file_id=file_id)
            await _set_status(ctx, file_id, "error", "не удалось обработать файл")
            return

        markdown = parsed.markdown()
        text_key = f"texts/{file_id}"
        await ctx.storage.put(text_key, markdown.encode("utf-8"))
        outline = parsed.outline()
        registry = ModelRegistry(settings)
        client = qdrant_client(settings)
        try:
            outline["search_chunks"] = await index_file(
                client,
                registry,
                file_id=uuid.UUID(file_id),
                owner_id=owner_id,
                title=filename,
                pages=parsed.pages,
            )
        except Exception as exc:
            # Без индекса документ всё равно читается целиком и инструментами чтения.
            log.warning("worker.index_failed", file_id=file_id, error=str(exc)[:300])
            outline["warnings"].append("поиск по документу недоступен")
        finally:
            await client.close()
            await registry.close()

        async with ctx.sessions() as db:
            row = await db.get(File, uuid.UUID(file_id))
            if row is None:
                return
            row.text_key = text_key
            row.pages = len(parsed.pages)
            row.chars = len(markdown)
            row.outline = outline
            row.parse_status = "ready"
            row.parse_error = None
            await db.commit()
        log.info("worker.parsed", file_id=file_id, pages=len(parsed.pages), parser=parsed.parser)


def _build(spec: dict[str, Any], settings: Settings) -> GeneratedFile:
    kind = spec["kind"]
    args = spec["args"]
    templates = settings.config_dir / "templates"
    timeout = settings.files.convert_timeout_seconds
    if kind == "document":
        return create_document(
            DocumentSpec.model_validate(args), templates=templates, timeout=timeout
        )
    if kind == "spreadsheet":
        return create_spreadsheet(SpreadsheetSpec.model_validate(args))
    if kind == "presentation":
        return create_presentation(PresentationSpec.model_validate(args), templates=templates)
    raise GenerationError(f"неизвестный тип файла: {kind}")


async def generate_job(spec: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Создаёт файл и запись ``files`` (kind=generated). Ошибка — ``{"error": "…"}``."""
    try:
        generated = await asyncio.to_thread(_build, spec, settings)
    except GenerationError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        log.exception("worker.generate_failed")
        return {"error": f"не удалось создать файл: {type(exc).__name__}"}

    preview = await asyncio.to_thread(
        preview_pdf,
        generated.data,
        generated.file_type,
        timeout=settings.files.convert_timeout_seconds,
    )
    async with worker_context(settings) as ctx:
        file_id = uuid.uuid4()
        storage_key = f"generated/{file_id}"
        await ctx.storage.put(storage_key, generated.data)
        preview_key = None
        if preview is not None:
            preview_key = f"previews/{file_id}"
            await ctx.storage.put(preview_key, preview)
        async with ctx.sessions() as db:
            row = File(
                id=file_id,
                owner_id=uuid.UUID(spec["owner_id"]),
                chat_id=uuid.UUID(spec["chat_id"]),
                message_id=uuid.UUID(spec["message_id"]),
                kind="generated",
                filename=generated.filename,
                mime=generated.mime,
                file_type=generated.file_type,
                size=len(generated.data),
                sha256=hashlib.sha256(generated.data).hexdigest(),
                storage_key=storage_key,
                preview_key=preview_key,
                parse_status="ready",
            )
            db.add(row)
            await db.commit()
    return {
        "file_id": str(file_id),
        "filename": generated.filename,
        "mime": generated.mime,
        "file_type": generated.file_type,
        "size": len(generated.data),
        "has_preview": preview_key is not None,
    }
