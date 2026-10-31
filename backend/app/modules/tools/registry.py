"""Реестр инструментов: ``@register_tool`` и выбор набора для запроса (§9.1).

Набор в чате — пересечение трёх списков: включены глобально (``tools.enabled``, дальше — админка),
разрешены сценарием (этап 5), доступны ролям пользователя (``required_permissions``).
"""

from __future__ import annotations

from collections.abc import Iterable

from app.modules.tools.base import Tool

_REGISTRY: dict[str, Tool] = {}


def register_tool[T: type[Tool]](cls: T) -> T:
    if cls.name in _REGISTRY:
        raise ValueError(f"инструмент {cls.name!r} уже зарегистрирован")
    _REGISTRY[cls.name] = cls()
    return cls


def all_tools() -> dict[str, Tool]:
    _load_builtin()
    return dict(_REGISTRY)


def get_tool(name: str) -> Tool | None:
    return all_tools().get(name)


def available_tools(
    *,
    enabled: Iterable[str] | None,
    scenario: Iterable[str] | None,
    permissions: frozenset[str],
    has_attachments: bool,
) -> list[Tool]:
    tools = all_tools()
    names = set(tools)
    if enabled is not None:
        names &= set(enabled)
    if scenario is not None:
        names &= set(scenario)
    result = []
    for name in sorted(names):
        tool = tools[name]
        if not tool.required_permissions <= permissions:
            continue
        if tool.needs_attachments and not has_attachments:
            continue
        result.append(tool)
    return result


def _load_builtin() -> None:
    # Импорт регистрирует встроенные инструменты декоратором.
    from app.modules.tools import builtin  # noqa: F401
