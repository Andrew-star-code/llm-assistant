"""Вычисление ролей пользователя из данных AD (§6.2 п. 7, §6.3). Чистые функции — без БД."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.config import LdapSettings

DEPARTMENT_ROLE_PREFIX = "dept:"


@dataclass(frozen=True)
class RoleSpec:
    code: str
    name: str
    kind: str  # department | custom


def department_role(department: str) -> RoleSpec:
    clean = " ".join(department.split())
    return RoleSpec(f"{DEPARTMENT_ROLE_PREFIX}{clean}", f"Отдел: {clean}", "department")


def compute_directory_roles(
    attributes: Mapping[str, str | None], groups: Sequence[str], ldap: LdapSettings
) -> list[RoleSpec]:
    """Роли из AD: автоматическая роль отдела, правила по атрибутам и группы AD.

    ``attributes`` — значения по ключам маппинга ``ldap.attributes`` (department, title, …).
    Сравнение правил — без учёта регистра; DN групп — тоже.
    """
    roles: dict[str, RoleSpec] = {}
    department = (attributes.get("department") or "").strip()
    if ldap.department_roles.auto and department:
        spec = department_role(department)
        roles[spec.code] = spec

    for rule in ldap.department_roles.rules:
        value = (attributes.get(rule.attribute) or "").casefold()
        if not value:
            continue
        hit = (rule.equals is not None and value == rule.equals.casefold()) or (
            rule.contains is not None and rule.contains.casefold() in value
        )
        if hit:
            for code in rule.roles:
                roles.setdefault(code, RoleSpec(code, code, "custom"))

    normalized_groups = {g.casefold() for g in groups}
    for mapping in ldap.group_roles:
        if mapping.group_dn.casefold() in normalized_groups:
            for code in mapping.roles:
                roles.setdefault(code, RoleSpec(code, code, "custom"))
    return list(roles.values())
