"""Файлы (вложения и сгенерированные) и вызовы инструментов (этап 3, §14).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31 21:16:11.619046+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('files',
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('chat_id', sa.Uuid(), nullable=True),
    sa.Column('message_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('mime', sa.String(length=128), nullable=False),
    sa.Column('file_type', sa.String(length=16), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=256), nullable=False),
    sa.Column('text_key', sa.String(length=256), nullable=True),
    sa.Column('preview_key', sa.String(length=256), nullable=True),
    sa.Column('parse_status', sa.String(length=16), nullable=False),
    sa.Column('parse_error', sa.Text(), nullable=True),
    sa.Column('pages', sa.Integer(), nullable=True),
    sa.Column('chars', sa.Integer(), nullable=True),
    sa.Column('outline', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], name=op.f('fk_files_chat_id_chats')),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_files_message_id_messages')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_files_owner_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_files'))
    )
    op.create_index(op.f('ix_files_chat_id'), 'files', ['chat_id'], unique=False)
    op.create_index(op.f('ix_files_message_id'), 'files', ['message_id'], unique=False)
    op.create_index(op.f('ix_files_owner_id'), 'files', ['owner_id'], unique=False)
    op.create_index(op.f('ix_files_sha256'), 'files', ['sha256'], unique=False)
    op.create_table('tool_calls',
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('call_id', sa.String(length=128), nullable=False),
    sa.Column('tool', sa.String(length=64), nullable=False),
    sa.Column('arguments', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('result_preview', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('visibility', sa.String(length=16), nullable=False),
    sa.Column('iteration', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=64), nullable=False),
    sa.Column('label_params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_tool_calls_message_id_messages')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_calls'))
    )
    op.create_index(op.f('ix_tool_calls_message_id'), 'tool_calls', ['message_id'], unique=False)
    op.create_index(op.f('ix_tool_calls_tool'), 'tool_calls', ['tool'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tool_calls_tool'), table_name='tool_calls')
    op.drop_index(op.f('ix_tool_calls_message_id'), table_name='tool_calls')
    op.drop_table('tool_calls')
    op.drop_index(op.f('ix_files_sha256'), table_name='files')
    op.drop_index(op.f('ix_files_owner_id'), table_name='files')
    op.drop_index(op.f('ix_files_message_id'), table_name='files')
    op.drop_index(op.f('ix_files_chat_id'), table_name='files')
    op.drop_table('files')
