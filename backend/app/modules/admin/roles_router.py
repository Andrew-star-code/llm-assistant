"""Админка «Роли» (§13.1, §13.2 «Пользователи»): свои роли и массовое назначение сотрудников.

Отдел из AD у заказчика не получить, поэтому пользовательские роли (юристы, ИТ, бухгалтерия)
создаются в админке и назначаются вручную (решение 57 в docs/status.md). Сотрудников добавляют
списком логинов или e-mail; кого ещё нет в системе (ни разу не входил), находим в AD и заводим.
Ручные назначения (``source = manual``) синхронизация с AD не трогает.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from app.core.deps import DbDep, SettingsDep, StorageDep
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, decode_cursor, encode_cursor
from app.modules.admin import app_settings
from app.modules.admin.chat_schemas import UserRef
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.auth.providers.base import AuthFailure
from app.modules.auth.providers.ldap import DirectoryUnavailable, LdapDirectory
from app.modules.auth.service import normalize_login
from app.modules.kb.models import KbRole, KnowledgeBase
from app.modules.rbac import service as rbac
from app.modules.rbac.compute import compute_directory_roles
from app.modules.rbac.models import Role, UserRole
from app.modules.rbac.permissions import ADMIN_ROLE_CODES, SUPERADMIN, Perm
from app.modules.scenarios.models import Scenario
from app.modules.users.models import User
from app.modules.users.service import upsert_from_directory

router = APIRouter(prefix="/admin/roles", tags=["admin"])

Viewer = Annotated[CurrentUser, Depends(require(Perm.USERS_VIEW))]
Manager = Annotated[CurrentUser, Depends(require(Perm.ROLES_MANAGE))]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CUSTOM = "custom"
MAX_BULK = 2000


class RoleIn(BaseModel):
    code: str = Field(min_length=1, max_length=64, description="Латиница: legal, it, accounting.")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)


class RoleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)


class RoleDetail(BaseModel):
    id: UUID
    code: str
    name: str
    kind: str
    description: str | None
    users: int
    editable: bool = Field(description="Свою роль можно переименовать и удалить.")
    knowledge_bases: list[str] = Field(description="Ролевые базы знаний этой роли.")
    scenarios: list[str] = Field(description="Сценарии, видимые этой роли.")


class Member(UserRef):
    source: str = Field(description="manual — назначен вручную; ad — из AD.")
    title: str | None
    last_login_at: datetime | None


class BulkIn(BaseModel):
    identifiers: list[str] = Field(
        min_length=1,
        max_length=MAX_BULK,
        description="Логины или e-mail (ivanov, ivanov@corp.local, CORP\\ivanov).",
    )


class BulkOut(BaseModel):
    added: list[UserRef]
    already: list[UserRef]
    created: list[str] = Field(description="Логины, заведённые из AD при добавлении.")
    not_found: list[str]


class RemoveIn(BaseModel):
    user_ids: list[UUID] = Field(min_length=1, max_length=MAX_BULK)


def _ref(user: User) -> UserRef:
    return UserRef(
        id=user.id, login=user.login, full_name=user.full_name, department=user.department
    )


async def _role(db: DbDep, role_id: UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise NotFoundError("Роль не найдена")
    return role


def _check_grantable(role: Role, actor: CurrentUser) -> None:
    if role.kind == "department":
        raise AppError(
            "Роли отделов вычисляются из AD и не выдаются вручную", code="department_role"
        )
    if role.code in ADMIN_ROLE_CODES and not actor.has(Perm.ADMINS_MANAGE):
        raise ForbiddenError("Назначать админские роли может только суперадминистратор")


async def _detail(db: DbDep, role: Role) -> RoleDetail:
    users = await db.scalar(
        select(func.count(func.distinct(UserRole.user_id))).where(UserRole.role_id == role.id)
    )
    bases = (
        await db.scalars(
            select(KnowledgeBase.name)
            .join(KbRole, KbRole.kb_id == KnowledgeBase.id)
            .where(KbRole.role_id == role.id, KnowledgeBase.deleted_at.is_(None))
            .order_by(KnowledgeBase.name)
        )
    ).all()
    scenarios = [
        s.name
        for s in (await db.scalars(select(Scenario).order_by(Scenario.name))).all()
        if role.code in (s.roles or [])
    ]
    return RoleDetail(
        id=role.id,
        code=role.code,
        name=role.name,
        kind=role.kind,
        description=role.description,
        users=int(users or 0),
        editable=role.kind == CUSTOM and role.code not in ADMIN_ROLE_CODES,
        knowledge_bases=list(bases),
        scenarios=scenarios,
    )


@router.post("", response_model=RoleDetail, status_code=201, operation_id="adminCreateRole")
async def create_role(body: RoleIn, request: Request, db: DbDep, actor: Manager) -> RoleDetail:
    code = body.code.strip().lower()
    if not CODE_RE.match(code):
        raise AppError("Код роли — латиница, цифры, «-» и «_»", code="bad_code", status_code=422)
    if await db.scalar(select(Role.id).where(Role.code == code)):
        raise AppError("Роль с таким кодом уже есть", code="role_exists", status_code=409)
    role = Role(code=code, name=body.name.strip(), kind=CUSTOM, description=body.description)
    db.add(role)
    await db.flush()
    await audit.record(
        db, actor_id=actor.id, action="role.create", target_type="role", target_id=role.id,
        details={"code": code, "name": role.name}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return await _detail(db, role)


@router.get("/{role_id}", response_model=RoleDetail, operation_id="adminGetRole")
async def get_role(role_id: UUID, db: DbDep, _: Viewer) -> RoleDetail:
    return await _detail(db, await _role(db, role_id))


@router.patch("/{role_id}", response_model=RoleDetail, operation_id="adminUpdateRole")
async def update_role(
    role_id: UUID, body: RoleUpdate, request: Request, db: DbDep, actor: Manager
) -> RoleDetail:
    role = await _role(db, role_id)
    if not (await _detail(db, role)).editable:
        raise AppError("Эту роль менять нельзя", code="role_locked", status_code=422)
    if body.name is not None:
        role.name = body.name.strip()
    if "description" in body.model_fields_set:
        role.description = body.description
    await audit.record(
        db, actor_id=actor.id, action="role.update", target_type="role", target_id=role.id,
        details=body.model_dump(exclude_unset=True), ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return await _detail(db, role)


@router.delete("/{role_id}", status_code=204, operation_id="adminDeleteRole")
async def delete_role(role_id: UUID, request: Request, db: DbDep, actor: Manager) -> None:
    """Удалить свою роль; если она открывает базы знаний или сценарии — сначала снимите их."""
    role = await _role(db, role_id)
    detail = await _detail(db, role)
    if not detail.editable:
        raise AppError("Эту роль удалить нельзя", code="role_locked", status_code=422)
    visibility = await app_settings.model_visibility(db)
    used = (
        detail.knowledge_bases
        + detail.scenarios
        + [f"модель {m}" for m, roles in visibility.items() if role.code in roles]
    )
    if used:
        raise AppError(
            f"Роль используется: {', '.join(used)} — сначала уберите её там",
            code="role_in_use",
            status_code=409,
        )
    await db.execute(delete(UserRole).where(UserRole.role_id == role.id))
    await db.delete(role)
    await audit.record(
        db, actor_id=actor.id, action="role.delete", target_type="role", target_id=role_id,
        details={"code": role.code, "users": detail.users}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()


@router.get("/{role_id}/members", response_model=Page[Member], operation_id="adminRoleMembers")
async def members(
    role_id: UUID,
    db: DbDep,
    _: Viewer,
    q: str | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[Member]:
    await _role(db, role_id)
    stmt = (
        select(User, UserRole.source)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_id == role_id)
    )
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.login.ilike(like)))
    if cursor:
        name, last_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                User.full_name > str(name),
                (User.full_name == str(name)) & (User.id > UUID(last_id)),
            )
        )
    rows = (await db.execute(stmt.order_by(User.full_name, User.id).limit(limit + 1))).all()
    items = [
        Member(
            **_ref(user).model_dump(),
            source=source,
            title=user.title,
            last_login_at=user.last_login_at,
        )
        for user, source in rows[:limit]
    ]
    last = items[-1] if len(rows) > limit else None
    return Page(items=items, next_cursor=encode_cursor(last.full_name, last.id) if last else None)


def _directory(request: Request) -> LdapDirectory | None:
    directory: LdapDirectory | None = request.app.state.ldap_directory
    return directory


async def _resolve(
    db: DbDep, raw: str, *, settings: Any, storage: Any, directory: LdapDirectory | None
) -> tuple[User | None, bool]:
    """Пользователь по логину или e-mail; кого нет в системе — из AD. (user, заведён_сейчас)."""
    value = raw.strip()
    if "@" in value:
        by_mail = await db.scalar(
            select(User).where(
                or_(func.lower(User.email) == value.lower(), func.lower(User.upn) == value.lower())
            )
        )
        if by_mail is not None:
            return by_mail, False
    try:
        login = normalize_login(
            value, netbios_domain=settings.ldap.netbios_domain, upn_suffix=settings.ldap.upn_suffix
        )
    except AuthFailure:
        return None, False
    user = await db.scalar(select(User).where(User.login == login))
    if user is not None or directory is None:
        return user, False
    found = await asyncio.to_thread(directory.lookup, login)
    if found is None or found.disabled:
        return None, False
    user = await upsert_from_directory(db, found, settings=settings, storage=storage)
    specs = compute_directory_roles(found.rule_attributes(), found.groups, settings.ldap)
    await rbac.sync_directory_roles(db, user.id, specs)
    return user, True


@router.post("/{role_id}/members", response_model=BulkOut, operation_id="adminAddRoleMembers")
async def add_members(
    role_id: UUID,
    body: BulkIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    actor: Manager,
) -> BulkOut:
    """Массовое добавление: список логинов или e-mail (например, столбец из Excel)."""
    role = await _role(db, role_id)
    _check_grantable(role, actor)
    directory = _directory(request)
    seen: set[str] = set()
    handled: set[UUID] = set()
    result = BulkOut(added=[], already=[], created=[], not_found=[])
    members_now = set(
        (await db.scalars(select(UserRole.user_id).where(UserRole.role_id == role.id))).all()
    )
    for raw in body.identifiers:
        key = raw.strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            user, created = await _resolve(
                db, raw, settings=settings, storage=storage, directory=directory
            )
        except DirectoryUnavailable:  # AD недоступен — остальные строки обрабатываем
            user, created = None, False
        if user is None:
            result.not_found.append(raw.strip())
            continue
        if user.id in handled:
            continue  # тот же сотрудник в другой записи (CORP\\login и login)
        handled.add(user.id)
        if created:
            result.created.append(user.login)
        if user.id in members_now:
            result.already.append(_ref(user))
            continue
        db.add(UserRole(user_id=user.id, role_id=role.id, source=rbac.SOURCE_MANUAL))
        members_now.add(user.id)
        result.added.append(_ref(user))
    await audit.record(
        db, actor_id=actor.id, action="role.members_add", target_type="role",
        target_id=role.id,
        details={
            "code": role.code, "added": [u.login for u in result.added],
            "created": result.created, "not_found": len(result.not_found),
        },
        ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return result


@router.post(
    "/{role_id}/members/remove", response_model=RoleDetail, operation_id="adminRemoveRoleMembers"
)
async def remove_members(
    role_id: UUID, body: RemoveIn, request: Request, db: DbDep, actor: Manager
) -> RoleDetail:
    """Снять роль, назначенную вручную; роли из AD пересчитывает синхронизация."""
    role = await _role(db, role_id)
    _check_grantable(role, actor)
    if role.code == SUPERADMIN and actor.id in body.user_ids:
        raise AppError("Нельзя снять роль суперадминистратора с самого себя", code="self_demotion")
    logins = (
        await db.scalars(
            select(User.login)
            .join(UserRole, UserRole.user_id == User.id)
            .where(
                UserRole.role_id == role.id,
                UserRole.source == rbac.SOURCE_MANUAL,
                UserRole.user_id.in_(body.user_ids),
            )
        )
    ).all()
    await db.execute(
        delete(UserRole).where(
            UserRole.role_id == role.id,
            UserRole.source == rbac.SOURCE_MANUAL,
            UserRole.user_id.in_(body.user_ids),
        )
    )
    await audit.record(
        db, actor_id=actor.id, action="role.members_remove", target_type="role",
        target_id=role.id, details={"code": role.code, "removed": sorted(logins)},
        ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return await _detail(db, role)
