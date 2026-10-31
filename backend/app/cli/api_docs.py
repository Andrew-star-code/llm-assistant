"""Генерация docs/reference/api.md из схемы OpenAPI (§17.4)."""

from __future__ import annotations

import json
from typing import Any

HEADER = """# Справочник API

> Файл сгенерирован командой `make gen-api` из OpenAPI бэкенда. Не правьте вручную.
> Полная схема — `frontend/src/api/openapi.json`; интерактивно в dev — `/api/docs`.
"""

METHODS = ("get", "post", "put", "patch", "delete")


def build_openapi() -> dict[str, Any]:
    from app.core.config import AppEnv, load_settings
    from app.main import create_app

    # Схема строится без подключения к БД; окружение dev, чтобы /api/openapi.json был включён.
    return create_app(load_settings(env=AppEnv.DEV)).openapi()


def dump_openapi(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def render(schema: dict[str, Any]) -> str:
    rows = ["| Метод | Путь | operationId | Описание | Ответы |", "| --- | --- | --- | --- | --- |"]
    for path, item in sorted(schema.get("paths", {}).items()):
        for method in METHODS:
            op = item.get(method)
            if not op:
                continue
            codes = ", ".join(sorted(op.get("responses", {})))
            summary = (op.get("summary") or "").replace("|", "\\|")
            op_id = op.get("operationId", "")
            rows.append(f"| {method.upper()} | `{path}` | `{op_id}` | {summary} | {codes} |")
    return "\n".join([HEADER, *rows]) + "\n"
