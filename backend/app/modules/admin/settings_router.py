"""Админка «Настройки» (§13.2) и публичные название и логотип (страница входа, шапка).

Значения хранятся в ``app_settings`` поверх конфига и действуют со следующего запроса, без
перезапуска; ``null`` в запросе возвращает значение из конфига. Менять может только
``admin.settings.manage`` (superadmin, §13.1); каждое изменение — в аудит.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import DbDep, SettingsDep, StorageDep
from app.core.errors import AppError, NotFoundError
from app.modules.admin import app_settings as keys
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip, require
from app.modules.moderation.policy import load_policy
from app.modules.rbac.permissions import Perm
from app.modules.scenarios.service import check_template
from app.modules.users.naming import AddressForm

router = APIRouter(prefix="/admin/settings", tags=["admin"])
public = APIRouter(prefix="/branding", tags=["branding"])

Manager = Annotated[CurrentUser, Depends(require(Perm.SETTINGS_MANAGE))]
LOGO_MAX_BYTES = 512 * 1024
LOGO_TYPES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
LONG_TEXT = {"notice_text", "system_prompt"}


class SettingsValues(BaseModel):
    app_name: str
    company_name: str
    notice_text: str
    retention_days: int
    max_file_mb: int
    max_files_per_message: int
    default_address_form: AddressForm
    system_prompt: str
    guard_block_categories: list[str] = Field(
        default_factory=list, description="Категории guard-модели, по которым ответ блокируется."
    )


class SettingsOut(SettingsValues):
    defaults: SettingsValues = Field(description="Значения из конфигурации.")
    overridden: list[str] = Field(description="Поля, заданные в админке.")
    notice_updated_at: datetime | None
    has_logo: bool
    logo_version: str | None
    guard_categories: list[str] = Field(description="Категории guard-модели из политики.")


class SettingsIn(BaseModel):
    """Меняются только переданные поля; ``null`` — вернуть значение из конфигурации."""

    app_name: str | None = Field(None, min_length=1, max_length=100)
    company_name: str | None = Field(None, min_length=1, max_length=200)
    notice_text: str | None = Field(None, min_length=1, max_length=10_000)
    require_notice_reaccept: bool = Field(
        False, description="Попросить всех подтвердить уведомление заново."
    )
    retention_days: int | None = Field(None, ge=0, le=3650)
    max_file_mb: int | None = Field(None, ge=1, le=500)
    max_files_per_message: int | None = Field(None, ge=1, le=50)
    default_address_form: AddressForm | None = None
    system_prompt: str | None = Field(None, min_length=1, max_length=20_000)
    guard_block_categories: list[str] | None = None


class Branding(BaseModel):
    app_name: str
    logo_url: str | None


FIELDS: dict[str, str] = {
    "app_name": keys.APP_NAME,
    "company_name": keys.COMPANY_NAME,
    "notice_text": keys.FIRST_LOGIN_NOTICE,
    "retention_days": keys.RETENTION_DAYS,
    "max_file_mb": keys.MAX_FILE_MB,
    "max_files_per_message": keys.MAX_FILES_PER_MESSAGE,
    "default_address_form": keys.DEFAULT_ADDRESS_FORM,
    "system_prompt": keys.SYSTEM_PROMPT,
    "guard_block_categories": keys.GUARD_BLOCK,
}


def _defaults(settings: Settings) -> SettingsValues:
    base = settings.config_dir / "prompts" / "system" / "base.md.j2"
    return SettingsValues(
        app_name=settings.app_name,
        company_name=settings.chat.company_name,
        notice_text=settings.auth.first_login_notice,
        retention_days=settings.retention.deleted_days,
        max_file_mb=settings.files.max_file_mb,
        max_files_per_message=settings.files.max_files_per_message,
        default_address_form=settings.users.default_address_form,
        system_prompt=base.read_text("utf-8").strip() if base.exists() else "",
        guard_block_categories=[],
    )


async def _out(db: DbDep, settings: Settings) -> SettingsOut:
    values = await keys.all_values(db)
    defaults = _defaults(settings)
    current = {field: values.get(key, getattr(defaults, field)) for field, key in FIELDS.items()}
    logo = values.get(keys.LOGO)
    updated = values.get(keys.NOTICE_UPDATED_AT)
    return SettingsOut(
        **current,
        defaults=defaults,
        overridden=[field for field, key in FIELDS.items() if key in values],
        notice_updated_at=datetime.fromisoformat(updated) if updated else None,
        has_logo=bool(logo),
        logo_version=logo.get("version") if logo else None,
        guard_categories=load_policy(settings.config_dir).guard_categories,
    )


@router.get("", response_model=SettingsOut, operation_id="adminGetSettings")
async def get_settings(db: DbDep, settings: SettingsDep, _: Manager) -> SettingsOut:
    return await _out(db, settings)


@router.put("", response_model=SettingsOut, operation_id="adminUpdateSettings")
async def update_settings(
    body: SettingsIn, request: Request, db: DbDep, settings: SettingsDep, actor: Manager
) -> SettingsOut:
    if body.system_prompt:
        check_template(body.system_prompt)
    if body.guard_block_categories:
        known = set(load_policy(settings.config_dir).guard_categories)
        unknown = [c for c in body.guard_block_categories if c not in known]
        if unknown:
            raise AppError(
                f"Неизвестные категории guard: {', '.join(unknown)}",
                code="bad_guard_category",
                status_code=422,
            )
    changed: dict[str, Any] = {}
    for field, key in FIELDS.items():
        if field not in body.model_fields_set:
            continue
        value = getattr(body, field)
        await keys.set_value(db, key, value, updated_by=actor.id)
        # Длинные тексты в аудит не копируем — только факт изменения.
        changed[field] = (
            ("изменён" if value is not None else "сброшен") if field in LONG_TEXT else value
        )
    if body.require_notice_reaccept:
        await keys.set_value(db, keys.NOTICE_UPDATED_AT, utcnow().isoformat(), updated_by=actor.id)
        changed["require_notice_reaccept"] = True
    if changed:
        await audit.record(
            db, actor_id=actor.id, action="settings.update", target_type="app_settings",
            target_id="settings", details=changed, ip=client_ip(request),
        )  # fmt: skip
    await db.commit()
    return await _out(db, settings)


def _image_type(data: bytes) -> str | None:
    for magic, mime in LOGO_TYPES.items():
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.post("/logo", response_model=SettingsOut, operation_id="adminUploadLogo")
async def upload_logo(
    file: UploadFile,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    actor: Manager,
) -> SettingsOut:
    """Логотип: PNG, JPEG или WebP до 512 КБ (SVG не принимается — в нём бывают скрипты)."""
    data = await file.read(LOGO_MAX_BYTES + 1)
    if len(data) > LOGO_MAX_BYTES:
        raise AppError("Логотип больше 512 КБ", code="too_large", status_code=413)
    mime = _image_type(data)
    if mime is None:
        raise AppError("Логотип — PNG, JPEG или WebP", code="unsupported", status_code=415)
    old = await keys.get_value(db, keys.LOGO, None)
    version = uuid.uuid4().hex[:12]
    key = f"branding/logo-{version}"
    await storage.put(key, data)
    await keys.set_value(
        db, keys.LOGO, {"key": key, "mime": mime, "version": version}, updated_by=actor.id
    )
    await audit.record(
        db, actor_id=actor.id, action="settings.logo", target_type="app_settings",
        target_id="logo", details={"size": len(data), "mime": mime}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    if old:
        await storage.delete(str(old["key"]))
    return await _out(db, settings)


@router.delete("/logo", response_model=SettingsOut, operation_id="adminDeleteLogo")
async def delete_logo(
    request: Request, db: DbDep, settings: SettingsDep, storage: StorageDep, actor: Manager
) -> SettingsOut:
    old = await keys.get_value(db, keys.LOGO, None)
    await keys.set_value(db, keys.LOGO, None, updated_by=actor.id)
    await audit.record(
        db, actor_id=actor.id, action="settings.logo", target_type="app_settings",
        target_id="logo", details={"deleted": True}, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    if old:
        await storage.delete(str(old["key"]))
    return await _out(db, settings)


@public.get("", response_model=Branding, operation_id="getBranding")
async def branding(db: DbDep, settings: SettingsDep) -> Branding:
    """Название и логотип — без входа: нужны странице входа."""
    values = await keys.all_values(db)
    logo = values.get(keys.LOGO)
    return Branding(
        app_name=str(values.get(keys.APP_NAME, settings.app_name)),
        logo_url=f"/api/branding/logo?v={logo['version']}" if logo else None,
    )


@public.get(
    "/logo",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
    operation_id="getBrandingLogo",
)
async def logo(db: DbDep, storage: StorageDep) -> Response:
    value = await keys.get_value(db, keys.LOGO, None)
    data = await storage.get(str(value["key"])) if value else None
    if not value or data is None:
        raise NotFoundError("Логотип не задан")
    return Response(
        content=data,
        media_type=str(value["mime"]),
        # URL с версией (?v=) — кэшировать можно надолго.
        headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )
