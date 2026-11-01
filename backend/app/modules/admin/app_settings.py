"""Настройки, которые меняются в админке (§13.2 «Настройки»); значения по умолчанию — из конфига."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SearchSettings, Settings
from app.modules.admin.models import AppSetting

FIRST_LOGIN_NOTICE = "first_login_notice"
# Порог реранкера подбирают на реальных документах — меняется в админке без перезапуска.
RERANK_THRESHOLD = "rag.search.rerank.score_threshold"


async def get_value(db: AsyncSession, key: str, default: Any) -> Any:
    row = await db.get(AppSetting, key)
    return default if row is None else row.value


async def set_value(db: AsyncSession, key: str, value: Any, *, updated_by: UUID | None) -> None:
    """Записывает значение (без commit); ``None`` — удалить: снова действует значение из конфига."""
    row = await db.get(AppSetting, key)
    if value is None:
        if row is not None:
            await db.delete(row)
        return
    if row is None:
        db.add(AppSetting(key=key, value=value, updated_by=updated_by))
    else:
        row.value = value
        row.updated_by = updated_by


async def search_settings(db: AsyncSession, settings: Settings) -> SearchSettings:
    """Параметры поиска с поправками из админки (читаются на каждый поиск — без кэша)."""
    base = settings.rag.search
    threshold = await get_value(db, RERANK_THRESHOLD, None)
    if threshold is None:
        return base
    rerank = base.rerank.model_copy(update={"score_threshold": float(threshold)})
    return base.model_copy(update={"rerank": rerank})


async def first_login_notice(db: AsyncSession, settings: Settings) -> str:
    # TODO(stage-6): редактор текста в разделе админки «Настройки».
    value = await get_value(db, FIRST_LOGIN_NOTICE, settings.auth.first_login_notice)
    return str(value)
