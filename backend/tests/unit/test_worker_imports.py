"""Точки входа воркера и CLI регистрируют все модели (дефект из проверки на рабочей станции).

В тестах воркер работает в режиме eager внутри api, где модели уже загружены, — поэтому каждая
точка входа проверяется в отдельном чистом процессе: импорт и разрешение внешних ключей.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.core.config import REPO_ROOT

CODE = """
import {module}
from app.core.db import Base
Base.metadata.sorted_tables  # разрешает все ForeignKey; без моделей — NoReferencedTableError
"""


@pytest.mark.parametrize(
    "module",
    [
        "app.workers.celery_app",
        "app.cli.kb",
        "app.cli.security",
        "app.workers.kb_jobs",
        "app.cli.generator",
    ],
)
def test_entry_point_registers_all_tables(module: str) -> None:
    result = subprocess.run(  # noqa: S603 — фиксированная команда, текущий интерпретатор
        [sys.executable, "-c", CODE.format(module=module)],
        cwd=REPO_ROOT / "backend",
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={"PATH": "/usr/bin:/bin", "APP_ENV": "test"},
    )
    assert result.returncode == 0, result.stderr[-2000:]
