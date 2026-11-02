"""Выполнение подготовленных запросов (§9.5): только чтение, тайм-аут, ограничение строк.

Драйверы синхронные (pyodbc), поэтому запрос идёт в отдельном потоке, а ожидание ограничено
тайм-аутом источника. Транзакция всегда откатывается; у источника — логин только на чтение.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, create_engine, event, text

from data_gateway.catalog import Source
from data_gateway.guard import Prepared


class QueryFailed(Exception):  # noqa: N818 — исход запроса, текст уходит модели
    """Ошибка источника; текст уходит модели, чтобы она исправила запрос."""


@dataclass
class Result:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool  # строк было больше, чем max_rows
    duration_ms: int


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date, dtime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return (
            float(value) if value == value.to_integral_value() or abs(value) < 1e15 else str(value)
        )
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} байт>"
    return value


class Executor:
    def __init__(self, secrets_dir: Path) -> None:
        self.secrets_dir = secrets_dir
        self._engines: dict[tuple[str, str], Engine] = {}

    def _engine(self, source: Source) -> Engine:
        url = source.resolved_url(self.secrets_dir)
        key = (source.name, url)
        engine = self._engines.get(key)
        if engine is None:
            engine = create_engine(url, pool_pre_ping=True, pool_size=4, max_overflow=4)
            timeout = source.timeout_s

            @event.listens_for(engine, "connect")
            def _on_connect(dbapi_connection: Any, _: Any) -> None:
                # pyodbc: тайм-аут запроса на стороне драйвера (сервер прервёт выполнение).
                if hasattr(dbapi_connection, "timeout"):
                    dbapi_connection.timeout = timeout

            self._engines[key] = engine
        return engine

    def _run(self, source: Source, prepared: Prepared) -> Result:
        started = time.monotonic()
        engine = self._engine(source)
        with engine.connect() as conn:
            try:
                cursor = conn.execute(text(prepared.sql), prepared.params)
                columns = list(cursor.keys())
                rows = cursor.fetchmany(prepared.max_rows + 1)
            finally:
                conn.rollback()  # только чтение: ничего не фиксируется
        truncated = len(rows) > prepared.max_rows
        return Result(
            columns=columns,
            rows=[[_jsonable(v) for v in row] for row in rows[: prepared.max_rows]],
            truncated=truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    async def run(self, source: Source, prepared: Prepared) -> Result:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._run, source, prepared), timeout=source.timeout_s + 2
            )
        except TimeoutError as exc:
            raise QueryFailed(
                f"запрос выполнялся дольше {source.timeout_s} с — сузьте условия"
            ) from exc
        except Exception as exc:  # ошибки драйвера и SQL — модели, без строки подключения
            message = str(getattr(exc, "orig", exc)).splitlines()[0][:500]
            raise QueryFailed(f"ошибка источника: {message}") from exc

    def dispose(self) -> None:
        for engine in self._engines.values():
            engine.dispose()
        self._engines.clear()
