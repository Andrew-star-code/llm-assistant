"""Политики лимитов и учёт расхода (§12, §14)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPkMixin, utcnow

SCOPES = ("global", "role", "user")
KINDS = ("chat", "title", "guard")


class LimitPolicy(UUIDPkMixin, CreatedAtMixin, Base):
    """Политика лимита (§12.2): глобальная, ролевая (``target_id`` — роль) или персональная
    (``target_id`` — пользователь). Временная — с ``expires_at``: после него не действует."""

    __tablename__ = "limit_policies"

    scope: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    metric: Mapped[str] = mapped_column(String(32))
    window: Mapped[str | None] = mapped_column(String(16))
    limit: Mapped[int] = mapped_column(BigInteger)
    model_role: Mapped[str | None] = mapped_column(String(32))
    thinking: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class UsageRecord(Base):
    """Списание токенов (§12.3): строка на каждый вызов модели. Секционирована по месяцам
    (``ts``): разделы создаёт задача ``limits.partitions``; без раздела строка попадает в
    ``usage_records_default`` и переносится при создании раздела."""

    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_user_ts", "user_id", "ts"),
        {"postgresql_partition_by": "RANGE (ts)"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=utcnow)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    # Без внешних ключей: учёт переживает физическое удаление чата (статистика и аудит).
    chat_id: Mapped[UUID | None] = mapped_column(Uuid)
    message_id: Mapped[UUID | None] = mapped_column(Uuid)
    model_role: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    thinking: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
