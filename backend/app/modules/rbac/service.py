"""Сервис ролей и прав: системные роли, роли из AD, ручные роли, вычисление прав пользователя."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.modules.rbac.compute import RoleSpec
from app.modules.rbac.models import Permission, Role, RolePermission, UserRole
from app.modules.rbac.permissions import (
    ADMIN_ROLE_CODES,
    PERMISSION_DESCRIPTIONS,
    SUPERADMIN,
    SYSTEM_ROLES,
    Perm,
)

SOURCE_AD = "ad"
SOURCE_MANUAL = "manual"
ALL_PERMISSIONS = frozenset(p.value for p in Perm)


@dataclass(frozen=True)
class AssignedRole:
    role: Role
    source: str


async def ensure_system_rbac(db: AsyncSession) -> None:
    """Создаёт недостающие права и системные роли. Существующие наборы прав ролей не трогает.

    Новое право (появилось в коде после установки) один раз выдаётся системным ролям, в набор
    которых оно входит по умолчанию, — иначе у существующих админов не было бы новых разделов.
    """
    existing_perms = set((await db.scalars(select(Permission.code))).all())
    new_perms = {p for p in PERMISSION_DESCRIPTIONS if p.value not in existing_perms}
    for perm in new_perms:
        db.add(Permission(code=perm.value, description=PERMISSION_DESCRIPTIONS[perm]))
    await db.flush()

    for spec in SYSTEM_ROLES:
        role = await db.scalar(select(Role).where(Role.code == spec.code))
        if role is None:
            role = Role(code=spec.code, name=spec.name, kind="system", description=spec.description)
            db.add(role)
            await db.flush()
            for perm in spec.permissions:
                db.add(RolePermission(role_id=role.id, permission_code=perm.value))
        elif existing_perms:
            for perm in spec.permissions & new_perms:
                db.add(RolePermission(role_id=role.id, permission_code=perm.value))
    await db.commit()


async def _ensure_role(db: AsyncSession, spec: RoleSpec) -> Role:
    role = await db.scalar(select(Role).where(Role.code == spec.code))
    if role is None:
        role = Role(code=spec.code, name=spec.name, kind=spec.kind)
        db.add(role)
        await db.flush()
    return role


async def sync_directory_roles(db: AsyncSession, user_id: UUID, specs: Sequence[RoleSpec]) -> None:
    """Приводит роли с source=ad к вычисленным из AD; ручные роли не трогает."""
    wanted = {(await _ensure_role(db, spec)).id for spec in specs}
    current = set(
        (
            await db.scalars(
                select(UserRole.role_id).where(
                    UserRole.user_id == user_id, UserRole.source == SOURCE_AD
                )
            )
        ).all()
    )
    if stale := current - wanted:
        await db.execute(
            delete(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.source == SOURCE_AD,
                UserRole.role_id.in_(stale),
            )
        )
    for role_id in wanted - current:
        db.add(UserRole(user_id=user_id, role_id=role_id, source=SOURCE_AD))
    await db.flush()


async def grant_role(
    db: AsyncSession, user_id: UUID, role_code: str, granted_by: UUID | None = None
) -> bool:
    """Выдаёт роль вручную; False — уже была."""
    role = await db.scalar(select(Role).where(Role.code == role_code))
    if role is None:
        raise NotFoundError(f"Роль {role_code} не найдена")
    exists = await db.get(UserRole, (user_id, role.id, SOURCE_MANUAL))
    if exists:
        return False
    db.add(UserRole(user_id=user_id, role_id=role.id, source=SOURCE_MANUAL, granted_by=granted_by))
    await db.flush()
    return True


async def user_roles(db: AsyncSession, user_id: UUID) -> list[AssignedRole]:
    rows = await db.execute(
        select(Role, UserRole.source)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .order_by(Role.kind, Role.name)
    )
    return [AssignedRole(role, source) for role, source in rows.all()]


async def permissions_for_roles(db: AsyncSession, role_ids: Iterable[UUID]) -> frozenset[str]:
    ids = list(role_ids)
    if not ids:
        return frozenset()
    return frozenset(
        (
            await db.scalars(
                select(RolePermission.permission_code).where(RolePermission.role_id.in_(ids))
            )
        ).all()
    )


def effective_permissions(roles: Sequence[AssignedRole], granted: frozenset[str]) -> frozenset[str]:
    if any(r.role.code == SUPERADMIN for r in roles):
        return ALL_PERMISSIONS
    return granted


async def set_manual_roles(
    db: AsyncSession,
    *,
    user_id: UUID,
    role_ids: Sequence[UUID],
    actor_id: UUID,
    actor_permissions: frozenset[str],
) -> tuple[list[str], list[str]]:
    """Заменяет ручные роли пользователя. Админские роли меняет только право admin.admins.manage.

    Возвращает (выданные коды, отозванные коды) — для аудита.
    """
    wanted = {r.id: r for r in (await db.scalars(select(Role).where(Role.id.in_(role_ids)))).all()}
    if len(wanted) != len(set(role_ids)):
        raise AppError("Указана несуществующая роль", code="unknown_role")
    current = {
        r.id: r
        for r in (
            await db.scalars(
                select(Role)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id, UserRole.source == SOURCE_MANUAL)
            )
        ).all()
    }
    added = [wanted[i] for i in wanted.keys() - current.keys()]
    removed = [current[i] for i in current.keys() - wanted.keys()]
    touches_admin = any(r.code in ADMIN_ROLE_CODES for r in (*added, *removed))
    if touches_admin and Perm.ADMINS_MANAGE.value not in actor_permissions:
        raise ForbiddenError("Назначать админские роли может только суперадминистратор")
    if any(r.kind == "department" for r in added):
        raise AppError(
            "Роли отделов вычисляются из AD и не выдаются вручную", code="department_role"
        )
    if user_id == actor_id and any(r.code == SUPERADMIN for r in removed):
        raise AppError("Нельзя снять роль суперадминистратора с самого себя", code="self_demotion")

    if removed:
        await db.execute(
            delete(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.source == SOURCE_MANUAL,
                UserRole.role_id.in_([r.id for r in removed]),
            )
        )
    for role in added:
        db.add(
            UserRole(user_id=user_id, role_id=role.id, source=SOURCE_MANUAL, granted_by=actor_id)
        )
    await db.flush()
    return sorted(r.code for r in added), sorted(r.code for r in removed)
