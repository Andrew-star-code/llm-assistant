"""Генерация docs/reference/config.md из Pydantic-моделей настроек (§16.4)."""

from __future__ import annotations

import types
import typing
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, SecretStr
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from app.core.config import REPO_ROOT, ModelEndpoint, Settings

HEADER = """# Справочник конфигурации

> Файл сгенерирован командой `make docs-config` из `backend/app/core/config.py`. Не правьте вручную.

Источники по убыванию приоритета: переменные окружения `APP_*` (вложенность через `__`) →
файлы секретов `/run/secrets/<имя переменной в нижнем регистре>` → `config/app.<env>.yaml` и
`config/models.<env>.yaml` → `config/app.yaml` и `config/models.yaml`.
Секреты (тип `secret`) задаются только через окружение или файлы секретов.
"""


def _type_name(annotation: Any) -> str:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if annotation is SecretStr:
        return "secret"
    if origin is typing.Literal:
        return " \\| ".join(str(a) for a in args)
    if origin in (typing.Union, types.UnionType):
        parts = [_type_name(a) for a in args if a is not type(None)]
        suffix = " \\| null" if type(None) in args else ""
        return " \\| ".join(parts) + suffix
    if origin is list:
        return f"list[{_type_name(args[0])}]"
    if origin is dict:
        return f"dict[{_type_name(args[0])}, {_type_name(args[1])}]"
    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return " \\| ".join(str(m.value) for m in annotation)
        return annotation.__name__
    return str(annotation)


_NO_DEFAULT = object()


def _field_default(field: FieldInfo) -> Any:
    if field.default_factory is not None:
        return field.default_factory()  # type: ignore[call-arg]
    if field.default is PydanticUndefined:
        return _NO_DEFAULT
    return field.default


def _format_default(field: FieldInfo, value: Any) -> str:
    if "SecretStr" in str(field.annotation):
        return "—"
    if value is _NO_DEFAULT:
        return "обязательно"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, Path):
        value = str(value.relative_to(REPO_ROOT)) if value.is_relative_to(REPO_ROOT) else str(value)
    text = repr(value) if not isinstance(value, str) else (f"`{value}`" if value else '""')
    return text.replace("|", "\\|")


def _model_type(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _rows(
    model: type[BaseModel], prefix: str, env_prefix: str | None, defaults: Any = None
) -> list[str]:
    """Строки таблицы; значения по умолчанию вложенных секций берутся из экземпляра родителя."""
    rows: list[str] = []
    for name, field in model.model_fields.items():
        path = f"{prefix}{name}"
        value = getattr(defaults, name) if defaults is not None else _field_default(field)
        nested = _model_type(field.annotation)
        if nested is not None:
            env_next = f"{env_prefix}{name.upper()}__" if env_prefix else None
            nested_defaults = value if isinstance(value, BaseModel) else None
            rows.extend(_rows(nested, f"{path}.", env_next, nested_defaults))
            continue
        env = f"`{env_prefix}{name.upper()}`" if env_prefix else "—"
        desc = (field.description or "").replace("|", "\\|")
        default = _format_default(field, value)
        rows.append(f"| `{path}` | {_type_name(field.annotation)} | {default} | {env} | {desc} |")
    return rows


def render() -> str:
    table_head = (
        "| Параметр | Тип | По умолчанию | Переменная окружения | Описание |\n"
        "| --- | --- | --- | --- | --- |"
    )
    parts = [HEADER, "## Приложение\n", table_head, *_rows(Settings, "", "APP_")]
    parts += [
        "\n## Модель в реестре `models.<роль>`\n",
        "Роли `chat`, `utility`, `embed`, `rerank` обязательны. Переменная окружения: "
        "`APP_MODELS__<РОЛЬ>__<ПАРАМЕТР>`, например `APP_MODELS__CHAT__BASE_URL`.\n",
        table_head,
        *_rows(ModelEndpoint, "models.<роль>.", None),
    ]
    return "\n".join(parts) + "\n"
