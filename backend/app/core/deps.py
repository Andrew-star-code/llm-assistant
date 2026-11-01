"""Зависимости FastAPI для инфраструктуры: сессия БД, Redis, хранилище, настройки."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.storage import Storage


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Сессия БД на запрос; коммит — явно в сервисах, при исключении — откат."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_sessions
    async with factory() as session:
        yield session


def get_redis(request: Request) -> Redis:
    client: Redis = request.app.state.redis
    return client


def get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
StorageDep = Annotated[Storage, Depends(get_storage)]
