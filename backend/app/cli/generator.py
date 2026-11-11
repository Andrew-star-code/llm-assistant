"""``python -m app.cli generator run|check`` — исполнитель генерации (ADR-0013).

``run`` — процесс сервиса ``generator``: разбирает очередь заданий ``gen:queue``; по SIGTERM
дорабатывает идущие ответы (``generation.shutdown_grace_seconds``) и выходит.
``check`` — healthcheck контейнера: есть ли свежая отметка этого исполнителя в Redis.
"""

from __future__ import annotations

import asyncio
import signal

from app.core.config import Settings
from app.core.logging import configure_logging
from app.modules.completions.executor import Executor, alive, serve


def run(settings: Settings) -> int:
    configure_logging(settings.logging)

    def install(executor: Executor) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, executor.stop)

    asyncio.run(serve(settings, install_signals=install))
    return 0


def check(settings: Settings) -> int:
    if asyncio.run(alive(settings)):
        print("generator: исполнитель работает")
        return 0
    print("generator: нет отметки исполнителя в Redis")
    return 1
