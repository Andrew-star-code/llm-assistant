"""Лимиты (этап 8, §12, §14): политики ``limit_policies`` и учёт ``usage_records``,
секционированный по месяцам (раздел по умолчанию + текущий и два следующих месяца; дальше разделы
создаёт задача ``limits.partitions`` в ``scheduler``).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-02 04:00:00.000000+00:00
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _month(year: int, month: int, shift: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + shift
    return index // 12, index % 12 + 1


def upgrade() -> None:
    op.create_table(
        "limit_policies",
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("window", sa.String(length=16), nullable=True),
        sa.Column("limit", sa.BigInteger(), nullable=False),
        sa.Column("model_role", sa.String(length=32), nullable=True),
        sa.Column("thinking", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_limit_policies_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_limit_policies")),
    )
    op.create_index(op.f("ix_limit_policies_created_by"), "limit_policies", ["created_by"])
    op.create_index(op.f("ix_limit_policies_target_id"), "limit_policies", ["target_id"])

    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("model_role", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("thinking", sa.Boolean(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_usage_records_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", "ts", name=op.f("pk_usage_records")),
        postgresql_partition_by="RANGE (ts)",
    )
    op.create_index("ix_usage_records_user_ts", "usage_records", ["user_id", "ts"])
    op.execute("CREATE TABLE usage_records_default PARTITION OF usage_records DEFAULT")
    now = datetime.now(UTC)
    for shift in range(3):
        year, month = _month(now.year, now.month, shift)
        end_year, end_month = _month(now.year, now.month, shift + 1)
        op.execute(
            f"CREATE TABLE usage_records_{year:04d}_{month:02d} PARTITION OF usage_records "
            f"FOR VALUES FROM ('{year:04d}-{month:02d}-01') TO ('{end_year:04d}-{end_month:02d}-01')"
        )


def downgrade() -> None:
    op.drop_table("usage_records")  # разделы удаляются вместе с родительской таблицей
    op.drop_index(op.f("ix_limit_policies_target_id"), table_name="limit_policies")
    op.drop_index(op.f("ix_limit_policies_created_by"), table_name="limit_policies")
    op.drop_table("limit_policies")
