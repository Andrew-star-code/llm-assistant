"""Провайдер dev: вход под seed-пользователем из конфига без пароля (§6.1).

Включается только вне prod — это проверяет валидация конфига при старте.
"""

from __future__ import annotations

from app.core.config import DevUser
from app.modules.auth.providers.base import AuthFailure, DirectoryUser

DEV_GUID_PREFIX = "dev:"


def _to_directory_user(user: DevUser, by_login: dict[str, DevUser]) -> DirectoryUser:
    manager = by_login.get(user.manager) if user.manager else None
    display = " ".join(p for p in (user.last_name, user.first_name, user.middle_name) if p)
    return DirectoryUser(
        guid=f"{DEV_GUID_PREFIX}{user.login}",
        login=user.login,
        full_name_raw=display,
        upn=user.email or None,
        email=user.email or None,
        last_name=user.last_name,
        first_name=user.first_name,
        middle_name=user.middle_name or None,
        title=user.title or None,
        department=user.department or None,
        company=user.company or None,
        office=user.office or None,
        phone=user.phone or None,
        mobile=user.mobile or None,
        manager_name=(
            " ".join(p for p in (manager.last_name, manager.first_name, manager.middle_name) if p)
            if manager
            else None
        ),
        groups=list(user.groups),
    )


class DevProvider:
    name = "dev"

    def __init__(self, users: list[DevUser]) -> None:
        self._users = {u.login.lower(): u for u in users}

    def list_users(self) -> list[DirectoryUser]:
        return [_to_directory_user(u, self._users) for u in self._users.values()]

    async def authenticate(self, login: str, password: str) -> DirectoryUser:
        user = self._users.get(login)
        if user is None:
            raise AuthFailure("user_not_found")
        return _to_directory_user(user, self._users)
