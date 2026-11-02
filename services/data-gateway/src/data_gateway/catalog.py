"""Каталог семантического слоя (§9.5): ``sources.yaml``, ``datasets/*.yaml``, ``functions/*.yaml``.

Каталог перечитывается без перезапуска: при каждом обращении сверяются времена изменения файлов.
Ошибка в новой версии не роняет шлюз — остаётся последняя корректная, ошибка видна в ``/health``.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Dialect = Literal["mssql", "sqlite", "postgresql"]
# Диалект sqlglot, в который переводится проверенный T-SQL перед выполнением.
SQLGLOT_DIALECT = {"mssql": "tsql", "sqlite": "sqlite", "postgresql": "postgres"}
_SECRET = re.compile(r"\$\{([A-Z0-9_]+)\}")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Model):
    """Подключение. ``url`` — URL SQLAlchemy; ``${ИМЯ}`` подставляется из секрета
    ``/run/secrets/<имя в нижнем регистре>`` или переменной окружения ``ИМЯ``."""

    name: str
    dialect: Dialect = "mssql"
    url: str
    timeout_s: int = Field(15, ge=1, le=300)
    max_rows: int = Field(1000, ge=1, le=100_000)
    description: str | None = None

    def resolved_url(self, secrets_dir: Path) -> str:
        def secret(match: re.Match[str]) -> str:
            name = match.group(1)
            path = secrets_dir / name.lower()
            if path.is_file():
                return path.read_text(encoding="utf-8").strip()
            value = os.environ.get(name)
            if value is None:
                raise KeyError(f"секрет {name} не задан")
            return value

        return _SECRET.sub(secret, self.url)


class Column(_Model):
    name: str
    type: str = "string"
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    pii: bool = False  # персональные данные: модель видит пометку, ответ — по правилам компании


class RlsRule(_Model):
    """Построчный доступ: ``column = значение атрибута пользователя``, кроме ролей ``unless_roles``.

    Значение — шаблон ``{user.department}``, ``{user.login}``; пустой атрибут — строк нет.
    """

    column: str
    equals: str
    unless_roles: list[str] = Field(default_factory=list)


class Example(_Model):
    question: str
    sql: str


class Dataset(_Model):
    name: str
    title: str
    description: str
    source: str
    view: str  # schema.view в источнике
    columns: list[Column]
    relations: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)  # пусто — всем
    rls: list[RlsRule] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)

    @property
    def view_key(self) -> tuple[str, str]:
        schema, _, name = self.view.rpartition(".")
        return (schema or "dbo").lower(), name.lower()

    @model_validator(mode="after")
    def _check_rls(self) -> Dataset:
        names = {c.name.lower() for c in self.columns}
        for rule in self.rls:
            if rule.column.lower() not in names:
                raise ValueError(f"RLS: колонки {rule.column!r} нет в наборе {self.name}")
        return self


class Param(_Model):
    type: Literal["string", "integer", "number", "boolean", "date"] = "string"
    description: str = ""
    required: bool = True
    default: Any = None
    min_length: int | None = None
    max_length: int | None = 200
    min: float | None = None
    max: float | None = None
    enum: list[str] | None = None


class Function(_Model):
    name: str
    description: str
    source: str
    roles: list[str] = Field(default_factory=list)
    params: dict[str, Param] = Field(default_factory=dict)
    sql: str
    columns: list[Column] = Field(default_factory=list)  # описание результата для модели

    @field_validator("name")
    @classmethod
    def _snake(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", value):
            raise ValueError("имя функции — snake_case")
        return value


class Catalog(_Model):
    sources: dict[str, Source]
    datasets: dict[str, Dataset]
    functions: dict[str, Function]

    @model_validator(mode="after")
    def _check_sources(self) -> Catalog:
        items: list[Dataset | Function] = [*self.datasets.values(), *self.functions.values()]
        for item in items:
            if item.source not in self.sources:
                raise ValueError(f"{item.name}: источник {item.source!r} не описан")
        return self


def visible(roles: list[str], user_roles: frozenset[str]) -> bool:
    return not roles or bool(set(roles) & user_roles)


def _read(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load(directory: Path) -> Catalog:
    raw_sources = _read(directory / "sources.yaml").get("sources", [])
    sources = {s["name"]: s for s in raw_sources}
    datasets = {}
    for path in sorted((directory / "datasets").glob("*.yaml")):
        data = _read(path)
        datasets[data["name"]] = data
    functions = {}
    for path in sorted((directory / "functions").glob("*.yaml")):
        data = _read(path)
        functions[data["name"]] = data
    return Catalog.model_validate(
        {"sources": sources, "datasets": datasets, "functions": functions}
    )


class CatalogStore:
    """Последняя корректная версия каталога; перечитывается, когда меняются файлы."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()
        self._stamp: tuple[tuple[str, float], ...] | None = None
        self._catalog: Catalog | None = None
        self.error: str | None = None

    def _signature(self) -> tuple[tuple[str, float], ...]:
        files = sorted(self.directory.rglob("*.yaml"))
        return tuple((str(p), p.stat().st_mtime) for p in files)

    def get(self) -> Catalog:
        with self._lock:
            stamp = self._signature()
            if stamp != self._stamp:
                try:
                    self._catalog = load(self.directory)
                    self.error = None
                except (OSError, KeyError, yaml.YAMLError, ValidationError) as exc:
                    self.error = f"{type(exc).__name__}: {exc}"[:2000]
                    if self._catalog is None:
                        raise
                self._stamp = stamp
            assert self._catalog is not None  # noqa: S101 — выше либо загружен, либо исключение
            return self._catalog
