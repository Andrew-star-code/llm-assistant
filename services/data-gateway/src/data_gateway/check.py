"""``python -m data_gateway check`` — самопроверка образа (``make test-data-gateway``).

Каталог читается и проходит проверку; к каждому источнику — ``SELECT 1`` через его драйвер (для
MS SQL — pyodbc и Microsoft ODBC Driver 18); функция ``search_employees`` (если есть) находит
сотрудника. Код возврата 0 — всё в порядке.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from data_gateway.catalog import load
from data_gateway.executor import Executor, QueryFailed
from data_gateway.guard import Prepared, prepare_function


async def _check() -> int:
    catalog_dir = Path(os.environ.get("DG_CATALOG_DIR", "/srv/catalog"))
    catalog = load(catalog_dir)
    print(f"✓ каталог: наборов {len(catalog.datasets)}, функций {len(catalog.functions)}")
    executor = Executor(Path(os.environ.get("DG_SECRETS_DIR", "/run/secrets")))
    failed = 0
    try:
        for source in catalog.sources.values():
            probe = Prepared(source=source.name, tsql="SELECT 1", sql="SELECT 1", max_rows=1)
            try:
                await executor.run(source, probe)
                print(f"✓ источник {source.name} ({source.dialect}): подключение")
            except QueryFailed as exc:
                failed += 1
                print(f"✗ источник {source.name}: {exc}")
        function = catalog.functions.get("search_employees")
        if function is not None and not failed:
            query = os.environ.get("DG_CHECK_QUERY", "Петров")
            prepared = prepare_function(function, {"query": query}, catalog)
            try:
                result = await executor.run(catalog.sources[function.source], prepared)
                print(f"✓ search_employees «{query}»: строк {len(result.rows)}")
                if not result.rows:
                    failed += 1
                    print("✗ ожидалась хотя бы одна строка")
            except QueryFailed as exc:
                failed += 1
                print(f"✗ search_employees: {exc}")
    finally:
        executor.dispose()
    print("Шлюз готов" if not failed else f"Ошибок: {failed}")
    return 1 if failed else 0


def main() -> int:
    return asyncio.run(_check())
