"""Периодическая синхронизация пользователей с AD (§6.4).

Обновляет атрибуты, фото и роли; пользователей, отключённых или удалённых в AD, помечает
``ad_disabled`` и разлогинивает. Пользователи провайдера dev не синхронизируются.

Пока нет Celery beat (этап 3), синхронизация идёт фоновой задачей api под Redis-блокировкой,
чтобы при нескольких процессах её выполнял один. TODO(stage-3): перенести в scheduler.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.storage import Storage
from app.modules.auth.providers.base import DirectoryUser
from app.modules.auth.providers.dev import DEV_GUID_PREFIX
from app.modules.auth.providers.ldap import DirectoryUnavailable, LdapDirectory
from app.modules.auth.sessions import SessionStore
from app.modules.rbac import service as rbac
from app.modules.rbac.compute import compute_directory_roles
from app.modules.users.models import User
from app.modules.users.service import upsert_from_directory

log = structlog.stdlib.get_logger("app.users.sync")

LOCK_KEY = "lock:ad-sync"


@dataclass
class SyncStats:
    checked: int = 0
    updated: int = 0
    disabled: int = 0
    errors: int = 0


async def sync_user(
    db: AsyncSession,
    user: User,
    found: DirectoryUser | None,
    *,
    settings: Settings,
    storage: Storage,
    sessions: SessionStore,
) -> bool:
    """Синхронизирует одного пользователя; True — пользователь отключён в AD."""
    if found is None or found.disabled or found.guid != user.ad_guid:
        # Нет записи, учётка отключена или логин теперь принадлежит другой учётке.
        if not user.ad_disabled:
            user.ad_disabled = True
            await sessions.revoke_user(db, user.id, by=None, reason="ad_disabled")
            log.info("users.sync.disabled", login=user.login)
        return True
    await upsert_from_directory(db, found, settings=settings, storage=storage)
    specs = compute_directory_roles(found.rule_attributes(), found.groups, settings.ldap)
    await rbac.sync_directory_roles(db, user.id, specs)
    return False


async def sync_all(
    factory: async_sessionmaker[AsyncSession],
    directory: LdapDirectory,
    *,
    settings: Settings,
    storage: Storage,
    sessions: SessionStore,
) -> SyncStats:
    stats = SyncStats()
    async with factory() as db:
        users = (
            await db.scalars(select(User).where(~User.ad_guid.startswith(DEV_GUID_PREFIX)))
        ).all()
        for user in users:
            stats.checked += 1
            try:
                found = await asyncio.to_thread(directory.lookup, user.login)
                disabled = await sync_user(
                    db, user, found, settings=settings, storage=storage, sessions=sessions
                )
                await db.commit()
            except DirectoryUnavailable:
                log.warning("users.sync.ad_unavailable")
                await db.rollback()
                stats.errors += 1
                break  # AD недоступен — не трогаем остальных
            except Exception:
                log.exception("users.sync.failed", login=user.login)
                await db.rollback()
                stats.errors += 1
                continue
            stats.disabled += int(disabled)
            stats.updated += int(not disabled)
    log.info("users.sync.done", **stats.__dict__)
    return stats


async def run_periodic_sync(
    redis: Redis,
    factory: async_sessionmaker[AsyncSession],
    directory: LdapDirectory,
    *,
    settings: Settings,
    storage: Storage,
    sessions: SessionStore,
) -> None:
    interval = settings.ldap.sync_interval_minutes * 60
    while True:
        await asyncio.sleep(interval)
        try:
            if await redis.set(LOCK_KEY, "1", nx=True, ex=max(interval - 10, 60)):
                await sync_all(
                    factory, directory, settings=settings, storage=storage, sessions=sessions
                )
        except Exception:
            log.exception("users.sync.loop_failed")
