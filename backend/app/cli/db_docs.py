"""Генерация docs/reference/db-schema.md из моделей SQLAlchemy (§14, §17.4)."""

from __future__ import annotations

from sqlalchemy import Column, Table
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401 — регистрирует все таблицы
from app.core.db import Base

HEADER = """# Схема БД

> Файл сгенерирован командой `make docs-db` из моделей SQLAlchemy. Не правьте вручную.
> Ключевые таблицы и их назначение — [SPEC §14](../SPEC.md#14-модель-данных-postgresql).
"""


def _column(col: Column[object]) -> str:
    flags = []
    if col.primary_key:
        flags.append("PK")
    for fk in col.foreign_keys:
        flags.append(f"→ {fk.target_fullname}")
    if col.unique:
        flags.append("unique")
    if col.index:
        flags.append("index")
    nullable = "null" if col.nullable and not col.primary_key else "not null"
    col_type = col.type.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    return f"| `{col.name}` | {col_type} | {nullable} | {', '.join(flags)} |"


def _table(table: Table) -> list[str]:
    doc = (table.info or {}).get("doc", "")
    rows = [f"## `{table.name}`", ""]
    if doc:
        rows += [doc, ""]
    rows += ["| Колонка | Тип | NULL | Ключи и индексы |", "| --- | --- | --- | --- |"]
    rows += [_column(c) for c in table.columns]
    return [*rows, ""]


def render() -> str:
    parts = [HEADER]
    for name in sorted(Base.metadata.tables):
        parts += _table(Base.metadata.tables[name])
    return "\n".join(parts).rstrip() + "\n"
