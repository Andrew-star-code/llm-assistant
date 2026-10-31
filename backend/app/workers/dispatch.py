"""Постановка задач воркеру из api.

В проде — Celery по имени задачи (api не импортирует код воркера). При ``worker.eager``
(только тесты) — та же async-функция в отдельном потоке с настройками приложения.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import Settings
from app.workers import jobs, kb_jobs


class TaskTimeout(Exception):  # noqa: N818
    """Воркер не вернул результат вовремя."""


class Dispatcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._celery: Any = None

    def _client(self) -> Any:
        if self._celery is None:
            from app.workers.celery_app import make_celery

            self._celery = make_celery(self.settings)
        return self._celery

    async def parse(self, file_id: str) -> None:
        if self.settings.worker.eager:
            await asyncio.to_thread(asyncio.run, jobs.parse_job(file_id, self.settings))
            return
        await asyncio.to_thread(self._client().send_task, "files.parse", args=[file_id])

    async def index_document(self, document_id: str) -> None:
        """Индексация документа базы знаний (очередь ``kb``)."""
        if self.settings.worker.eager:
            await asyncio.to_thread(
                asyncio.run, kb_jobs.index_document_job(document_id, self.settings)
            )
            return
        await asyncio.to_thread(
            self._client().send_task, "kb.index", args=[document_id], queue="kb"
        )

    async def import_folder(self, import_id: str) -> None:
        """Массовый импорт из папки; в eager-режиме документы индексируются сразу же."""
        if self.settings.worker.eager:
            settings = self.settings

            async def inline(document_id: str) -> None:
                await kb_jobs.index_document_job(document_id, settings)

            await asyncio.to_thread(
                asyncio.run, kb_jobs.import_job(import_id, self.settings, inline)
            )
            return
        await asyncio.to_thread(self._client().send_task, "kb.import", args=[import_id], queue="kb")

    async def generate(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Генерация файла в воркере (pandoc, LibreOffice); ждём результат."""
        timeout = self.settings.worker.task_timeout_seconds
        if self.settings.worker.eager:
            return await asyncio.to_thread(asyncio.run, jobs.generate_job(spec, self.settings))
        result = await asyncio.to_thread(self._client().send_task, "files.generate", args=[spec])
        try:
            value: dict[str, Any] = await asyncio.to_thread(result.get, timeout=timeout)
        except Exception as exc:
            if type(exc).__name__ == "TimeoutError":
                raise TaskTimeout from exc
            raise
        return value
