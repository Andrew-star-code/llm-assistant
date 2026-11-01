"""Приложение Celery воркера (§2.1, §4). Брокер и хранилище результатов — Redis (отдельная БД).

Запуск воркеров: ``celery -A app.workers.celery_app worker -Q files -c 2`` (вложения и генерация
файлов) и ``… -Q kb -c 2`` (индексация баз знаний и массовый импорт) — отдельные очереди, чтобы
многочасовой импорт не задерживал файлы пользователей.
Задачи — тонкие обёртки над async-функциями ``app.workers.jobs``: так тот же код выполняется
и в тестах (без брокера), и в воркере.
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery, signals

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.workers import export_jobs, jobs, kb_jobs

QUEUE = "files"
KB_QUEUE = "kb"


def broker_url(settings: Settings) -> str:
    base = settings.redis_url.get_secret_value().rsplit("/", 1)[0]
    return f"{base}/{settings.worker.broker_db}"


def make_celery(settings: Settings) -> Celery:
    url = broker_url(settings)
    app = Celery("ai_assistant", broker=url, backend=url)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_expires=3600,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_queue=QUEUE,
        task_time_limit=settings.files.parse_timeout_seconds + 60,
        broker_connection_retry_on_startup=True,
        worker_hijack_root_logger=False,
        # Плановые задачи — сервис scheduler (celery beat); выполняет их воркер очереди files.
        beat_schedule={
            "exports-cleanup": {"task": "exports.cleanup", "schedule": 3600.0},
            "retention-purge": {"task": "retention.purge", "schedule": 6 * 3600.0},
        },
    )
    return app


celery_app = make_celery(get_settings())


@signals.setup_logging.connect  # type: ignore[untyped-decorator]
def _setup_logging(**_: Any) -> None:
    # Те же JSON-логи, что у api; секреты и тексты документов не логируются.
    configure_logging(get_settings().logging)


@celery_app.task(name="files.parse")  # type: ignore[untyped-decorator]
def parse_file_task(file_id: str) -> None:
    asyncio.run(jobs.parse_job(file_id, get_settings()))


@celery_app.task(name="files.requeue")  # type: ignore[untyped-decorator]
def requeue_files_task() -> int:
    async def enqueue(file_id: str) -> None:
        celery_app.send_task("files.parse", args=[file_id], queue=QUEUE)

    return asyncio.run(jobs.requeue_files_job(get_settings(), enqueue))


@celery_app.task(name="exports.build")  # type: ignore[untyped-decorator]
def export_task(export_id: str) -> None:
    asyncio.run(export_jobs.export_job(export_id, get_settings()))


@celery_app.task(name="exports.cleanup")  # type: ignore[untyped-decorator]
def cleanup_exports_task() -> int:
    return asyncio.run(export_jobs.cleanup_exports_job(get_settings()))


@celery_app.task(name="retention.purge")  # type: ignore[untyped-decorator]
def retention_task() -> int:
    return asyncio.run(export_jobs.retention_job(get_settings()))


@celery_app.task(name="files.generate")  # type: ignore[untyped-decorator]
def generate_file_task(spec: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(jobs.generate_job(spec, get_settings()))


def _send(name: str) -> kb_jobs.Enqueue:
    async def enqueue(arg: str) -> None:
        celery_app.send_task(name, args=[arg], queue=KB_QUEUE)

    return enqueue


@celery_app.task(name="kb.index")  # type: ignore[untyped-decorator]
def index_document_task(document_id: str) -> None:
    asyncio.run(kb_jobs.index_document_job(document_id, get_settings()))


@celery_app.task(name="kb.import")  # type: ignore[untyped-decorator]
def import_task(import_id: str) -> None:
    asyncio.run(kb_jobs.import_job(import_id, get_settings(), _send("kb.index")))


@celery_app.task(name="kb.requeue")  # type: ignore[untyped-decorator]
def requeue_task() -> dict[str, int]:
    return asyncio.run(kb_jobs.requeue_job(get_settings(), _send("kb.index"), _send("kb.import")))


@signals.worker_ready.connect  # type: ignore[untyped-decorator]
def _requeue_on_start(sender: Any = None, **_: Any) -> None:
    # После перезапуска: воркер kb продолжает импорт и индексацию (§10.3), воркер files —
    # разбор вложений, оставшихся «в очереди» или «в обработке».
    consumer = getattr(sender, "task_consumer", None)
    queues = {q.name for q in consumer.queues} if consumer is not None else set()
    if KB_QUEUE in queues:
        celery_app.send_task("kb.requeue", queue=KB_QUEUE)
    if QUEUE in queues:
        celery_app.send_task("files.requeue", queue=QUEUE)
