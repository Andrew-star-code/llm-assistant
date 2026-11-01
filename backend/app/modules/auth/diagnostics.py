"""Диагностика AD (§6.7): ``python -m app.cli ad check`` и страница «Диагностика AD».

Показывает доступность каждого контроллера и TLS, bind сервисной учёткой, найденную запись,
итоговые атрибуты, ФИО и форму обращения, отдел и вычисленные роли. Пароль пользователя
проверяется только по явному запросу (``--password-prompt``), в админке — никогда.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from ldap3.core.exceptions import LDAPException
from pydantic import BaseModel

from app.core.config import Settings
from app.modules.auth.providers.base import AuthFailure, DirectoryUser
from app.modules.auth.providers.ldap import DirectoryUnavailable, LdapDirectory
from app.modules.auth.service import normalize_login
from app.modules.rbac.compute import compute_directory_roles
from app.modules.rbac.permissions import SUPERADMIN
from app.modules.users import naming
from app.modules.users.service import resolve_middle_name


class ControllerOut(BaseModel):
    url: str
    ok: bool
    duration_ms: float
    error: str | None = None


class StepOut(BaseModel):
    ok: bool
    error: str | None = None


class RoleSpecOut(BaseModel):
    code: str
    name: str
    source: Literal["department", "rule", "group", "bootstrap"]


class DirectoryEntryOut(BaseModel):
    dn: str | None
    guid: str
    disabled: bool
    in_access_group: bool
    groups: list[str]
    attributes: dict[str, str | None]


class DiagnosticsReport(BaseModel):
    login: str
    controllers: list[ControllerOut]
    service_bind: StepOut
    user_found: bool
    entry: DirectoryEntryOut | None = None
    full_name: str | None = None
    middle_name_source: Literal["attribute", "display_name", "none"] | None = None
    address_form: str | None = None
    address: str | None = None
    department: str | None = None
    roles: list[RoleSpecOut] = []
    password_check: StepOut | None = None
    ok: bool


def _entry(du: DirectoryUser, directory: LdapDirectory) -> DirectoryEntryOut:
    attrs = {
        "displayName": du.full_name_raw,
        "sn": du.last_name,
        "givenName": du.first_name,
        "middleName": du.middle_name,
        "title": du.title,
        "department": du.department,
        "company": du.company,
        "office": du.office,
        "mail": du.email,
        "userPrincipalName": du.upn,
        "telephoneNumber": du.phone,
        "mobile": du.mobile,
        "manager": du.manager_dn,
        "manager (ФИО)": du.manager_name,
        "employeeID": du.employee_id,
        "thumbnailPhoto": f"{len(du.photo)} байт" if du.photo else None,
    }
    return DirectoryEntryOut(
        dn=du.dn,
        guid=du.guid,
        disabled=du.disabled,
        in_access_group=directory.in_access_group(du),
        groups=du.groups,
        attributes=attrs,
    )


def _roles(du: DirectoryUser, settings: Settings) -> list[RoleSpecOut]:
    rule_codes = {c for r in settings.ldap.department_roles.rules for c in r.roles}
    out = []
    for spec in compute_directory_roles(du.rule_attributes(), du.groups, settings.ldap):
        if spec.kind == "department":
            source: Literal["department", "rule", "group", "bootstrap"] = "department"
        else:
            source = "rule" if spec.code in rule_codes else "group"
        out.append(RoleSpecOut(code=spec.code, name=spec.name, source=source))
    if du.login in {a.lower() for a in settings.auth.bootstrap_admins}:
        out.append(RoleSpecOut(code=SUPERADMIN, name=SUPERADMIN, source="bootstrap"))
    return out


def run_diagnostics_sync(
    directory: LdapDirectory, settings: Settings, raw_login: str, password: str | None = None
) -> DiagnosticsReport:
    try:
        login = normalize_login(
            raw_login,
            netbios_domain=settings.ldap.netbios_domain,
            upn_suffix=settings.ldap.upn_suffix,
        )
    except AuthFailure:
        login = raw_login.strip()
    controllers = [ControllerOut(**c.__dict__) for c in directory.check_controllers()]

    try:
        directory.service_connection().unbind()
        service_bind = StepOut(ok=True)
    except (DirectoryUnavailable, AuthFailure, LDAPException, OSError) as exc:
        reason = exc.reason if isinstance(exc, AuthFailure) else str(exc)
        return DiagnosticsReport(
            login=login,
            controllers=controllers,
            service_bind=StepOut(ok=False, error=reason),
            user_found=False,
            ok=False,
        )

    du = directory.lookup(login)
    report = DiagnosticsReport(
        login=login,
        controllers=controllers,
        service_bind=service_bind,
        user_found=du is not None,
        ok=du is not None,
    )
    if du is not None:
        middle = resolve_middle_name(du, settings)
        form = settings.users.default_address_form
        report.entry = _entry(du, directory)
        report.middle_name_source = (
            "attribute" if du.middle_name else ("display_name" if middle else "none")
        )
        report.full_name = naming.full_name(
            du.last_name, du.first_name, middle, du.full_name_raw or du.login
        )
        report.address_form = form
        report.address = naming.address(form, du.last_name, du.first_name, middle)
        report.department = du.department
        report.roles = _roles(du, settings)
        report.ok = not du.disabled and report.entry.in_access_group

    if password is not None:
        try:
            directory.verify_password(login, password)
            report.password_check = StepOut(ok=True)
        except AuthFailure as exc:
            report.password_check = StepOut(ok=False, error=exc.reason)
        except DirectoryUnavailable as exc:
            report.password_check = StepOut(ok=False, error=str(exc))
        report.ok = report.ok and report.password_check.ok
    return report


async def run_diagnostics(
    directory: LdapDirectory, settings: Settings, login: str, password: str | None = None
) -> DiagnosticsReport:
    return await asyncio.to_thread(run_diagnostics_sync, directory, settings, login, password)
