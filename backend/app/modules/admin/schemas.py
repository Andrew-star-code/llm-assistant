"""Схемы админ-API этапа 1."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.users.schemas import RoleOut


class UserListItem(BaseModel):
    id: UUID
    login: str
    full_name: str
    title: str | None
    department: str | None
    is_blocked: bool
    ad_disabled: bool
    last_login_at: datetime | None


class SessionOut(BaseModel):
    id: UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    provider: str
    active: bool


class LoginEventOut(BaseModel):
    id: UUID
    ts: datetime
    user_id: UUID | None
    login_attempted: str
    ip: str | None
    user_agent: str | None
    method: str
    success: bool
    failure_reason: str | None
    risk_flags: list[str]
    reviewed_at: datetime | None = None


class UserCard(BaseModel):
    id: UUID
    login: str
    full_name: str
    upn: str | None
    email: str | None
    title: str | None
    department: str | None
    company: str | None
    office: str | None
    phone: str | None
    mobile: str | None
    manager_name: str | None
    employee_id: str | None
    has_photo: bool
    ad_groups: list[str]
    ad_disabled: bool
    is_blocked: bool
    blocked_reason: str | None
    blocked_until: datetime | None
    last_login_at: datetime | None
    synced_at: datetime | None
    created_at: datetime
    roles: list[RoleOut]
    sessions: list[SessionOut]
    recent_logins: list[LoginEventOut]


class BlockIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    until: datetime | None = Field(None, description="До какого момента; null — бессрочно.")


class RolesIn(BaseModel):
    role_ids: list[UUID] = Field(description="Полный набор ручных ролей пользователя.")


class RoleListItem(BaseModel):
    id: UUID
    code: str
    name: str
    kind: str
    description: str | None
    users: int
    permissions: list[str]


class AuditOut(BaseModel):
    id: UUID
    ts: datetime
    actor_id: UUID | None
    actor_name: str | None
    action: str
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]
    ip: str | None


class DiagnosticsIn(BaseModel):
    login: str = Field(min_length=1, max_length=256)


class RevokedOut(BaseModel):
    revoked: int
