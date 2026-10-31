"""Базы знаний, документы, импорт, источники ответов и инциденты (этап 4, §14).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31 22:29:08.371934+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('knowledge_bases',
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('level', sa.String(length=16), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('embed_model', sa.String(length=200), nullable=False),
    sa.Column('chunking', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_knowledge_bases_created_by_users')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_knowledge_bases_owner_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_bases')),
    sa.UniqueConstraint('code', name=op.f('uq_knowledge_bases_code'))
    )
    op.create_index(op.f('ix_knowledge_bases_level'), 'knowledge_bases', ['level'], unique=False)
    op.create_index(op.f('ix_knowledge_bases_owner_id'), 'knowledge_bases', ['owner_id'], unique=False)
    op.create_table('kb_imports',
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('skipped', sa.Integer(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_kb_imports_created_by_users')),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], name=op.f('fk_kb_imports_kb_id_knowledge_bases')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_imports'))
    )
    op.create_index(op.f('ix_kb_imports_kb_id'), 'kb_imports', ['kb_id'], unique=False)
    op.create_table('kb_roles',
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], name=op.f('fk_kb_roles_kb_id_knowledge_bases'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_kb_roles_role_id_roles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('kb_id', 'role_id', name=op.f('pk_kb_roles'))
    )
    op.create_index(op.f('ix_kb_roles_role_id'), 'kb_roles', ['role_id'], unique=False)
    op.create_table('incidents',
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('fingerprint', sa.String(length=128), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('chat_id', sa.Uuid(), nullable=True),
    sa.Column('message_id', sa.Uuid(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('occurrences', sa.Integer(), nullable=False),
    sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('assigned_to', sa.Uuid(), nullable=True),
    sa.Column('resolution', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], name=op.f('fk_incidents_assigned_to_users')),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], name=op.f('fk_incidents_chat_id_chats')),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_incidents_message_id_messages')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_incidents_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incidents'))
    )
    op.create_index(op.f('ix_incidents_chat_id'), 'incidents', ['chat_id'], unique=False)
    op.create_index(op.f('ix_incidents_fingerprint'), 'incidents', ['fingerprint'], unique=False)
    op.create_index(op.f('ix_incidents_last_seen'), 'incidents', ['last_seen'], unique=False)
    op.create_index(op.f('ix_incidents_message_id'), 'incidents', ['message_id'], unique=False)
    op.create_index(op.f('ix_incidents_status'), 'incidents', ['status'], unique=False)
    op.create_index(op.f('ix_incidents_type'), 'incidents', ['type'], unique=False)
    op.create_index(op.f('ix_incidents_user_id'), 'incidents', ['user_id'], unique=False)
    op.create_table('kb_documents',
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('file_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('chunks', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('import_id', sa.Uuid(), nullable=True),
    sa.Column('source_path', sa.Text(), nullable=True),
    sa.Column('uploaded_by', sa.Uuid(), nullable=True),
    sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['files.id'], name=op.f('fk_kb_documents_file_id_files')),
    sa.ForeignKeyConstraint(['import_id'], ['kb_imports.id'], name=op.f('fk_kb_documents_import_id_kb_imports')),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], name=op.f('fk_kb_documents_kb_id_knowledge_bases')),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_kb_documents_uploaded_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_documents'))
    )
    op.create_index(op.f('ix_kb_documents_file_id'), 'kb_documents', ['file_id'], unique=False)
    op.create_index(op.f('ix_kb_documents_import_id'), 'kb_documents', ['import_id'], unique=False)
    op.create_index(op.f('ix_kb_documents_kb_id'), 'kb_documents', ['kb_id'], unique=False)
    op.create_index(op.f('ix_kb_documents_sha256'), 'kb_documents', ['sha256'], unique=False)
    op.create_index(op.f('ix_kb_documents_status'), 'kb_documents', ['status'], unique=False)
    op.create_index(op.f('ix_kb_documents_uploaded_by'), 'kb_documents', ['uploaded_by'], unique=False)
    op.create_table('message_sources',
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('index', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=True),
    sa.Column('document_id', sa.Uuid(), nullable=True),
    sa.Column('file_id', sa.Uuid(), nullable=True),
    sa.Column('chunk_id', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('kb_name', sa.String(length=200), nullable=True),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('section', sa.Text(), nullable=True),
    sa.Column('snippet', sa.Text(), nullable=False),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('cited', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['kb_documents.id'], name=op.f('fk_message_sources_document_id_kb_documents')),
    sa.ForeignKeyConstraint(['file_id'], ['files.id'], name=op.f('fk_message_sources_file_id_files')),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], name=op.f('fk_message_sources_kb_id_knowledge_bases')),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_message_sources_message_id_messages')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_message_sources'))
    )
    op.create_index(op.f('ix_message_sources_document_id'), 'message_sources', ['document_id'], unique=False)
    op.create_index(op.f('ix_message_sources_file_id'), 'message_sources', ['file_id'], unique=False)
    op.create_index(op.f('ix_message_sources_kb_id'), 'message_sources', ['kb_id'], unique=False)
    op.create_index(op.f('ix_message_sources_message_id'), 'message_sources', ['message_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_message_sources_message_id'), table_name='message_sources')
    op.drop_index(op.f('ix_message_sources_kb_id'), table_name='message_sources')
    op.drop_index(op.f('ix_message_sources_file_id'), table_name='message_sources')
    op.drop_index(op.f('ix_message_sources_document_id'), table_name='message_sources')
    op.drop_table('message_sources')
    op.drop_index(op.f('ix_kb_documents_uploaded_by'), table_name='kb_documents')
    op.drop_index(op.f('ix_kb_documents_status'), table_name='kb_documents')
    op.drop_index(op.f('ix_kb_documents_sha256'), table_name='kb_documents')
    op.drop_index(op.f('ix_kb_documents_kb_id'), table_name='kb_documents')
    op.drop_index(op.f('ix_kb_documents_import_id'), table_name='kb_documents')
    op.drop_index(op.f('ix_kb_documents_file_id'), table_name='kb_documents')
    op.drop_table('kb_documents')
    op.drop_index(op.f('ix_incidents_user_id'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_type'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_status'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_message_id'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_last_seen'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_fingerprint'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_chat_id'), table_name='incidents')
    op.drop_table('incidents')
    op.drop_index(op.f('ix_kb_roles_role_id'), table_name='kb_roles')
    op.drop_table('kb_roles')
    op.drop_index(op.f('ix_kb_imports_kb_id'), table_name='kb_imports')
    op.drop_table('kb_imports')
    op.drop_index(op.f('ix_knowledge_bases_owner_id'), table_name='knowledge_bases')
    op.drop_index(op.f('ix_knowledge_bases_level'), table_name='knowledge_bases')
    op.drop_table('knowledge_bases')
