"""Настройки, которые меняются в админке (§13.2 «Настройки»); значения по умолчанию — из конфига."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SearchSettings, Settings
from app.modules.admin.models import AppSetting

FIRST_LOGIN_NOTICE = "first_login_notice"
# Порог реранкера подбирают на реальных документах — меняется в админке без перезапуска.
RERANK_THRESHOLD = "rag.search.rerank.score_threshold"
RETENTION_DAYS = "retention.deleted_days"
# {роль модели: [коды ролей пользователей]}; нет записи или пусто — модель видна всем.
MODEL_VISIBILITY = "models.visibility"
# Глобально выключенные инструменты (поверх ``tools.enabled`` из конфига).
TOOLS_DISABLED = "tools.disabled"
# Раздел «Настройки» (§13.2): значения поверх конфига, действуют без перезапуска.
APP_NAME = "branding.name"
LOGO = "branding.logo"  # {"key": …, "mime": …, "version": …}
COMPANY_NAME = "chat.company_name"
NOTICE_UPDATED_AT = "notice.updated_at"  # после него уведомление нужно подтвердить заново
MAX_FILE_MB = "files.max_file_mb"
MAX_FILES_PER_MESSAGE = "files.max_files_per_message"
DEFAULT_ADDRESS_FORM = "users.default_address_form"
SYSTEM_PROMPT = "prompts.system_base"  # шаблон базового системного промпта вместо файла
GUARD_BLOCK = "moderation.guard_block"  # категории guard-модели, по которым ответ блокируется


async def all_values(db: AsyncSession) -> dict[str, Any]:
    return {row.key: row.value for row in await db.scalars(select(AppSetting))}


async def effective(db: AsyncSession, settings: Settings) -> Settings:
    """Конфиг с правками из админки — одной выборкой; читается на каждый запрос, без кэша."""
    values = await all_values(db)
    if not values:
        return settings

    def section(model: Any, mapping: dict[str, str]) -> Any:
        update = {field: values[key] for field, key in mapping.items() if key in values}
        return model.model_copy(update=update) if update else model

    update: dict[str, Any] = {
        "chat": section(settings.chat, {"company_name": COMPANY_NAME}),
        "files": section(
            settings.files,
            {"max_file_mb": MAX_FILE_MB, "max_files_per_message": MAX_FILES_PER_MESSAGE},
        ),
        "users": section(settings.users, {"default_address_form": DEFAULT_ADDRESS_FORM}),
        "retention": section(settings.retention, {"deleted_days": RETENTION_DAYS}),
    }
    if APP_NAME in values:
        update["app_name"] = values[APP_NAME]
    return settings.model_copy(update=update)


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


async def retention_days(db: AsyncSession, settings: Settings) -> int:
    """Через сколько дней удалённые чаты стираются физически; 0 — никогда (§14)."""
    return int(await get_value(db, RETENTION_DAYS, settings.retention.deleted_days))


async def model_visibility(db: AsyncSession) -> dict[str, list[str]]:
    value = await get_value(db, MODEL_VISIBILITY, {})
    return {str(k): [str(c) for c in v] for k, v in dict(value).items() if v}


async def hidden_model_roles(db: AsyncSession, role_codes: Iterable[str]) -> frozenset[str]:
    """Роли моделей, которые пользователю с этими ролями не видны (сценарии с ними скрыты)."""
    codes = set(role_codes)
    return frozenset(
        model for model, allowed in (await model_visibility(db)).items() if not codes & set(allowed)
    )


async def disabled_tools(db: AsyncSession) -> set[str]:
    return {str(t) for t in await get_value(db, TOOLS_DISABLED, [])}


async def enabled_tools(db: AsyncSession, settings: Settings) -> list[str] | None:
    """Включённые инструменты: конфиг минус выключенные в админке (None — все из реестра)."""
    disabled = await disabled_tools(db)
    if settings.tools.enabled is None:
        if not disabled:
            return None
        from app.modules.tools.registry import all_tools

        return [name for name in all_tools() if name not in disabled]
    return [name for name in settings.tools.enabled if name not in disabled]


async def guard_block_categories(db: AsyncSession) -> list[str]:
    return [str(c) for c in await get_value(db, GUARD_BLOCK, [])]


async def first_login_notice(db: AsyncSession, settings: Settings) -> str:
    value = await get_value(db, FIRST_LOGIN_NOTICE, settings.auth.first_login_notice)
    return str(value)


async def notice_required(db: AsyncSession, accepted_at: datetime | None) -> bool:
    """Подтвердить уведомление: ещё не подтверждал или текст обновлён с запросом подтверждения."""
    if accepted_at is None:
        return True
    updated = await get_value(db, NOTICE_UPDATED_AT, None)
    return updated is not None and accepted_at < datetime.fromisoformat(str(updated))


async def system_prompt_override(db: AsyncSession) -> str | None:
    value = await get_value(db, SYSTEM_PROMPT, None)
    return str(value) if value else None
