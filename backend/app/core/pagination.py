"""Курсорная пагинация (§14: списки отдаются с курсорной пагинацией).

Курсор — непрозрачная строка: base64 от JSON ``[sort_value, id]`` последнего элемента страницы.
Сортировка — по убыванию ``(sort_value, id)``, поэтому новые записи не сдвигают страницы.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.errors import AppError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


def encode_cursor(sort_value: datetime | str | int, item_id: UUID | int) -> str:
    value: Any = sort_value.isoformat() if isinstance(sort_value, datetime) else sort_value
    raw = json.dumps([value, str(item_id)], ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[Any, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value, item_id = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError) as exc:
        raise AppError("Некорректный курсор пагинации", code="bad_cursor") from exc
    return value, str(item_id)


def decode_datetime_cursor(cursor: str) -> tuple[datetime, str]:
    value, item_id = decode_cursor(cursor)
    try:
        return datetime.fromisoformat(str(value)), item_id
    except ValueError as exc:
        raise AppError("Некорректный курсор пагинации", code="bad_cursor") from exc
