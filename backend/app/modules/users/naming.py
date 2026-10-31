"""ФИО и форма обращения (§6.3, §11.1).

* Отчество берётся из атрибута ``middleName``; если его нет — выделяется из ``displayName`` по
  шаблону (например, ``{last} {first} {middle}``), если фамилия и имя совпали.
* Форма обращения по умолчанию — «Имя Отчество»; без отчества — по имени.
"""

from __future__ import annotations

import re
from typing import Literal

AddressForm = Literal["name_patronymic", "first_name", "full_name", "formal"]
ADDRESS_FORMS: tuple[AddressForm, ...] = ("name_patronymic", "first_name", "full_name", "formal")

_PLACEHOLDER = re.compile(r"\{(last|first|middle)\}")


def middle_from_display_name(
    display_name: str | None, pattern: str, last: str | None, first: str | None
) -> str | None:
    """Выделяет отчество из displayName по шаблону; None — если не удалось уверенно."""
    if not display_name or "{middle}" not in pattern:
        return None
    regex = ""
    pos = 0
    for match in _PLACEHOLDER.finditer(pattern):
        regex += re.escape(pattern[pos : match.start()]).replace(r"\ ", r"\s+")
        regex += rf"(?P<{match.group(1)}>\S+)"
        pos = match.end()
    regex += re.escape(pattern[pos:]).replace(r"\ ", r"\s+")
    found = re.fullmatch(regex, display_name.strip())
    if not found:
        return None
    groups = found.groupdict()
    if last and groups.get("last", last).casefold() != last.casefold():
        return None
    if first and groups.get("first", first).casefold() != first.casefold():
        return None
    return groups.get("middle")


def full_name(last: str | None, first: str | None, middle: str | None, fallback: str) -> str:
    parts = [p for p in (last, first, middle) if p]
    return " ".join(parts) if parts else fallback


def address(
    form: AddressForm, last: str | None, first: str | None, middle: str | None
) -> str | None:
    """Как модель обращается к пользователю; None — «на вы» без имени."""
    if form == "formal" or not first:
        return None
    if form == "first_name":
        return first
    if form == "full_name":
        return " ".join(p for p in (last, first, middle) if p)
    return f"{first} {middle}" if middle else first
