"""Все модели SQLAlchemy — для Alembic autogenerate и генерации docs/reference/db-schema.md."""

from app.modules.admin.models import AppSetting
from app.modules.audit.models import AuditLog
from app.modules.auth.models import UserSession
from app.modules.chats.models import Chat, Folder, Message
from app.modules.exports.models import Export
from app.modules.feedback.models import Feedback
from app.modules.files.models import File
from app.modules.incidents.models import Incident
from app.modules.kb.models import KbDocument, KbImport, KbRole, KnowledgeBase
from app.modules.rag.models import MessageSource
from app.modules.rbac.models import Permission, Role, RolePermission, UserRole
from app.modules.scenarios.models import Scenario
from app.modules.security.models import LoginEvent
from app.modules.tools.models import ToolCall
from app.modules.users.models import User

__all__ = [
    "AppSetting",
    "AuditLog",
    "Chat",
    "Export",
    "Feedback",
    "File",
    "Folder",
    "Incident",
    "KbDocument",
    "KbImport",
    "KbRole",
    "KnowledgeBase",
    "LoginEvent",
    "Message",
    "MessageSource",
    "Permission",
    "Role",
    "RolePermission",
    "Scenario",
    "ToolCall",
    "User",
    "UserRole",
    "UserSession",
]
