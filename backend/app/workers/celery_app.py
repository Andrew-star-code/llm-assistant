"""Приложение Celery воркера (§2.1, §4). Брокер и хранилище результатов — Redis (отдельная БД).

Запуск воркера: ``celery -A app.workers.celery_app worker -Q files -c 2``.
Задачи — тонкие обёртки над async-функциями ``app.workers.jobs``: так тот же код выполняется
и в тестах (без брокера), и в воркере.
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery, signals

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.workers import jobs

QUEUE = "files"


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


@celery_app.task(name="files.generate")  # type: ignore[untyped-decorator]
def generate_file_task(spec: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(jobs.generate_job(spec, get_settings()))
