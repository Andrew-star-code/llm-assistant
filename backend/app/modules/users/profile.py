"""Сборка профиля пользователя для API (§6.5)."""

from __future__ import annotations

from app.core.config import Settings
from app.modules.rbac.service import AssignedRole
from app.modules.users.models import User
from app.modules.users.schemas import Profile, RoleOut, UserSettings
from app.modules.users.service import address_form_of, address_of


def role_out(roles: list[AssignedRole]) -> list[RoleOut]:
    return [
        RoleOut(code=r.role.code, name=r.role.name, kind=r.role.kind, source=r.source)
        for r in roles
    ]


def build_profile(user: User, roles: list[AssignedRole], settings: Settings) -> Profile:
    return Profile(
        id=user.id,
        login=user.login,
        full_name=user.full_name,
        last_name=user.last_name,
        first_name=user.first_name,
        middle_name=user.middle_name,
        title=user.title,
        department=user.department,
        company=user.company,
        office=user.office,
        email=user.email,
        phone=user.phone,
        mobile=user.mobile,
        manager_name=user.manager_name,
        has_photo=user.photo_key is not None,
        roles=role_out(roles),
        address_form=address_form_of(user, settings),
        address_form_is_default=user.address_form is None,
        address=address_of(user, settings),
        settings=UserSettings.model_validate(user.settings or {}),
        last_login_at=user.last_login_at,
    )


def photo_media_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"GIF8"):
        return "image/gif"
    return "image/jpeg"
