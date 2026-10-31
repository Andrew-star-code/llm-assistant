"""Чаты, папки, сообщения (дерево, полнотекстовый поиск) и обратная связь (этап 2, §14).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31 19:10:51.682135+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('folders',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_folders_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_folders'))
    )
    op.create_index(op.f('ix_folders_user_id'), 'folders', ['user_id'], unique=False)
    op.create_table('chats',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('folder_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=True),
    sa.Column('scenario_id', sa.Uuid(), nullable=True),
    sa.Column('pinned', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('active_leaf_id', sa.Uuid(), nullable=True),
    sa.Column('thinking_enabled', sa.Boolean(), nullable=True),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['deleted_by'], ['users.id'], name=op.f('fk_chats_deleted_by_users')),
    sa.ForeignKeyConstraint(['folder_id'], ['folders.id'], name=op.f('fk_chats_folder_id_folders'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_chats_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chats'))
    )
    op.create_index(op.f('ix_chats_deleted_by'), 'chats', ['deleted_by'], unique=False)
    op.create_index(op.f('ix_chats_folder_id'), 'chats', ['folder_id'], unique=False)
    op.create_index(op.f('ix_chats_user_id'), 'chats', ['user_id'], unique=False)
    op.create_index('ix_chats_user_last_message', 'chats', ['user_id', sa.literal_column('last_message_at DESC')], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('messages',
    sa.Column('chat_id', sa.Uuid(), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), server_default='', nullable=False),
    sa.Column('reasoning', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('thinking', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('model', sa.String(length=256), nullable=True),
    sa.Column('finish_reason', sa.String(length=32), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('reasoning_tokens', sa.Integer(), nullable=True),
    sa.Column('ttft_ms', sa.Integer(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('error', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('trace', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('search_vector', postgresql.TSVECTOR(), sa.Computed("to_tsvector('russian', coalesce(content, ''))", persisted=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], name=op.f('fk_messages_chat_id_chats')),
    sa.ForeignKeyConstraint(['parent_id'], ['messages.id'], name=op.f('fk_messages_parent_id_messages')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    op.create_index(op.f('ix_messages_chat_id'), 'messages', ['chat_id'], unique=False)
    op.create_index('ix_messages_content_trgm', 'messages', ['content'], unique=False, postgresql_using='gin', postgresql_ops={'content': 'gin_trgm_ops'})
    op.create_index(op.f('ix_messages_parent_id'), 'messages', ['parent_id'], unique=False)
    op.create_index('ix_messages_search', 'messages', ['search_vector'], unique=False, postgresql_using='gin')
    op.create_table('feedback',
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('rating', sa.SmallInteger(), nullable=False),
    sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_feedback_message_id_messages')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_feedback_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_feedback')),
    sa.UniqueConstraint('message_id', 'user_id', name=op.f('uq_feedback_message_id'))
    )
    op.create_index(op.f('ix_feedback_message_id'), 'feedback', ['message_id'], unique=False)
    op.create_index(op.f('ix_feedback_user_id'), 'feedback', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_feedback_user_id'), table_name='feedback')
    op.drop_index(op.f('ix_feedback_message_id'), table_name='feedback')
    op.drop_table('feedback')
    op.drop_index('ix_messages_search', table_name='messages', postgresql_using='gin')
    op.drop_index(op.f('ix_messages_parent_id'), table_name='messages')
    op.drop_index('ix_messages_content_trgm', table_name='messages', postgresql_using='gin', postgresql_ops={'content': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_messages_chat_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_index('ix_chats_user_last_message', table_name='chats', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index(op.f('ix_chats_user_id'), table_name='chats')
    op.drop_index(op.f('ix_chats_folder_id'), table_name='chats')
    op.drop_index(op.f('ix_chats_deleted_by'), table_name='chats')
    op.drop_table('chats')
    op.drop_index(op.f('ix_folders_user_id'), table_name='folders')
    op.drop_table('folders')
