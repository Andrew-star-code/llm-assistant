"""Все модели SQLAlchemy — для Alembic autogenerate и генерации docs/reference/db-schema.md."""

from app.modules.admin.models import AppSetting
from app.modules.audit.models import AuditLog
from app.modules.auth.models import UserSession
from app.modules.rbac.models import Permission, Role, RolePermission, UserRole
from app.modules.security.models import LoginEvent
from app.modules.users.models import User

__all__ = [
    "AppSetting",
    "AuditLog",
    "LoginEvent",
    "Permission",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
    "UserSession",
]
