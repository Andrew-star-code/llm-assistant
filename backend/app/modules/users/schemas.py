"""Схемы API профиля."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.users.naming import AddressForm

ThemeMode = Literal["light", "dark", "system"]


class RoleOut(BaseModel):
    code: str
    name: str
    kind: str
    source: str


class UserSettings(BaseModel):
    theme: ThemeMode | None = None


class Profile(BaseModel):
    id: UUID
    login: str
    full_name: str
    last_name: str | None
    first_name: str | None
    middle_name: str | None
    title: str | None
    department: str | None
    company: str | None
    office: str | None
    email: str | None
    phone: str | None
    mobile: str | None
    manager_name: str | None
    has_photo: bool
    roles: list[RoleOut]
    address_form: AddressForm
    address_form_is_default: bool
    address: str | None = Field(
        description="Как ассистент обращается к пользователю; null — «на вы»."
    )
    settings: UserSettings
    last_login_at: datetime | None


class ProfileSettingsUpdate(BaseModel):
    """Частичное обновление: меняются только переданные поля."""

    address_form: AddressForm | None = Field(
        None, description="Форма обращения; null — вернуть значение по умолчанию."
    )
    theme: ThemeMode | None = None
