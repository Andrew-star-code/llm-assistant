"""Хранилище файлов: интерфейс ``Storage`` и реализация на томе (ADR-0009).

Ключи — внутренние (``photos/<uuid>``, позже ``uploads/<uuid>``); имя файла пользователя никогда
не используется как путь (§15). Переход на S3 — новая реализация интерфейса (FUTURE).
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Protocol

_KEY_RE = re.compile(r"^[a-z0-9_-]+(/[A-Za-z0-9_.-]+)+$")


class Storage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes | None: ...
    async def delete(self, key: str) -> None: ...


class LocalStorage:
    """Файлы в каталоге ``root``; запись атомарная (временный файл + rename)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        if not _KEY_RE.match(key) or ".." in key:
            raise ValueError(f"недопустимый ключ хранилища: {key!r}")
        return self.root / key

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
            tmp.write_bytes(data)
            tmp.replace(path)

        await asyncio.to_thread(write)

    async def get(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            return None

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)
