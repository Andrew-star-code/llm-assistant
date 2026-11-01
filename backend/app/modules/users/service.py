"""Пользователи: создание и обновление из каталога (ключ — objectGUID), фото, ФИО."""

from __future__ import annotations

import hashlib
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.storage import Storage
from app.modules.auth.providers.base import DirectoryUser
from app.modules.auth.providers.dev import DEV_GUID_PREFIX
from app.modules.users import naming
from app.modules.users.models import User

log = structlog.stdlib.get_logger("app.users")

MAX_PHOTO_BYTES = 512 * 1024


def resolve_middle_name(du: DirectoryUser, settings: Settings) -> str | None:
    if du.middle_name:
        return du.middle_name
    return naming.middle_from_display_name(
        du.full_name_raw,
        settings.ldap.attributes.display_name_pattern,
        du.last_name,
        du.first_name,
    )


def address_form_of(user: User, settings: Settings) -> naming.AddressForm:
    form = user.address_form or settings.users.default_address_form
    for known in naming.ADDRESS_FORMS:
        if form == known:
            return known
    return "name_patronymic"


def address_of(user: User, settings: Settings) -> str | None:
    return naming.address(
        address_form_of(user, settings), user.last_name, user.first_name, user.middle_name
    )


def is_dev_guid(guid: str) -> bool:
    return guid.startswith(DEV_GUID_PREFIX)


async def _find_existing(db: AsyncSession, du: DirectoryUser) -> User | None:
    user = await db.scalar(select(User).where(User.ad_guid == du.guid))
    if user is not None:
        return user
    by_login = await db.scalar(select(User).where(User.login == du.login))
    if by_login is None:
        return None
    if is_dev_guid(by_login.ad_guid) or is_dev_guid(du.guid):
        # Тот же человек вошёл другим провайдером на дев-стенде — берём ту же запись.
        return by_login
    # Логин занят другой учёткой AD (учётку пересоздали): старую запись освобождаем от логина.
    log.warning("users.login_reassigned", login=du.login, old_user_id=str(by_login.id))
    by_login.login = f"{by_login.login}~{str(by_login.id)[:8]}"
    await db.flush()
    return None


async def _store_photo(user: User, photo: bytes | None, storage: Storage) -> None:
    if not photo or len(photo) > MAX_PHOTO_BYTES:
        if user.photo_key and not photo:
            await storage.delete(user.photo_key)
            user.photo_key = user.photo_sha256 = None
        return
    digest = hashlib.sha256(photo).hexdigest()
    if digest == user.photo_sha256 and user.photo_key:
        return
    key = f"photos/{user.id}"
    await storage.put(key, photo)
    user.photo_key, user.photo_sha256 = key, digest


async def upsert_from_directory(
    db: AsyncSession,
    du: DirectoryUser,
    *,
    settings: Settings,
    storage: Storage,
    now: datetime | None = None,
) -> User:
    """Создаёт или обновляет пользователя по данным каталога. Коммит — на вызывающей стороне."""
    now = now or utcnow()
    user = await _find_existing(db, du)
    if user is not None and is_dev_guid(du.guid) and not is_dev_guid(user.ad_guid):
        # Вход провайдером dev под пользователем из AD: данные AD не перезаписываем.
        return user
    if user is None:
        user = User(ad_guid=du.guid, login=du.login, full_name=du.login, ad_groups=[], settings={})
        db.add(user)
        await db.flush()

    middle = resolve_middle_name(du, settings)
    user.ad_guid = du.guid
    user.login = du.login
    user.upn = du.upn
    user.email = du.email
    user.last_name = du.last_name
    user.first_name = du.first_name
    user.middle_name = middle
    user.full_name = naming.full_name(
        du.last_name, du.first_name, middle, du.full_name_raw or du.login
    )
    user.title = du.title
    user.department = du.department
    user.company = du.company
    user.office = du.office
    user.phone = du.phone
    user.mobile = du.mobile
    user.manager_dn = du.manager_dn
    user.manager_name = du.manager_name
    user.employee_id = du.employee_id
    user.ad_groups = list(du.groups)
    user.ad_disabled = du.disabled
    user.synced_at = now
    await _store_photo(user, du.photo, storage)
    await db.flush()
    return user
