"""Схемы API входа."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.users.schemas import RoleOut, UserSettings


class DevUserOut(BaseModel):
    login: str
    full_name: str
    title: str | None
    department: str | None


class ProvidersOut(BaseModel):
    providers: list[Literal["ldap", "dev"]]
    dev_users: list[DevUserOut] = Field(default_factory=list)


class CsrfOut(BaseModel):
    csrf_token: str


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=256)
    password: str = Field("", max_length=1024)
    provider: Literal["ldap", "dev"] = "ldap"


class Notice(BaseModel):
    required: bool
    text: str


class Me(BaseModel):
    id: UUID
    login: str
    full_name: str
    first_name: str | None
    middle_name: str | None
    address: str | None
    title: str | None
    department: str | None
    has_photo: bool
    roles: list[RoleOut]
    permissions: list[str]
    settings: UserSettings
    notice: Notice
