"""Сценарии и связь чатов со сценарием, тестовые чаты (этап 5, §8.7, §14).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31 23:09:55.964970+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('scenarios',
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('icon', sa.String(length=64), nullable=True),
    sa.Column('roles', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('model_role', sa.String(length=32), nullable=False),
    sa.Column('prompt_template', sa.Text(), nullable=False),
    sa.Column('tools', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('knowledge_bases', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rag_mode', sa.String(length=8), nullable=False),
    sa.Column('requires_attachment', sa.Boolean(), nullable=False),
    sa.Column('attachment_hint', sa.String(length=200), nullable=True),
    sa.Column('starter_prompts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('thinking_default', sa.Boolean(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scenarios')),
    sa.UniqueConstraint('code', name=op.f('uq_scenarios_code'))
    )
    op.add_column('chats', sa.Column('is_test', sa.Boolean(), server_default='false', nullable=False))
    op.create_index(op.f('ix_chats_scenario_id'), 'chats', ['scenario_id'], unique=False)
    op.create_foreign_key(op.f('fk_chats_scenario_id_scenarios'), 'chats', 'scenarios', ['scenario_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_chats_scenario_id_scenarios'), 'chats', type_='foreignkey')
    op.drop_index(op.f('ix_chats_scenario_id'), table_name='chats')
    op.drop_column('chats', 'is_test')
    op.drop_table('scenarios')
