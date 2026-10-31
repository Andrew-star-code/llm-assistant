"""Настройки, которые меняются в админке (§13.2 «Настройки»); значения по умолчанию — из конфига."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.admin.models import AppSetting

FIRST_LOGIN_NOTICE = "first_login_notice"


async def get_value(db: AsyncSession, key: str, default: Any) -> Any:
    row = await db.get(AppSetting, key)
    return default if row is None else row.value


async def first_login_notice(db: AsyncSession, settings: Settings) -> str:
    # TODO(stage-6): редактор текста в разделе админки «Настройки».
    value = await get_value(db, FIRST_LOGIN_NOTICE, settings.auth.first_login_notice)
    return str(value)
