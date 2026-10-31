"""Пользователи, роли и права, сессии, журнал входов, аудит, настройки (этап 1, §14).

Журнал аудита — только вставка: UPDATE и DELETE запрещены триггером (§13.6).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31 18:25:24.437853+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('permissions',
    sa.Column('code', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_permissions'))
    )
    op.create_table('roles',
    sa.Column('code', sa.String(length=256), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
    sa.UniqueConstraint('code', name=op.f('uq_roles_code'))
    )
    op.create_table('users',
    sa.Column('ad_guid', sa.String(length=64), nullable=False),
    sa.Column('login', sa.String(length=128), nullable=False),
    sa.Column('upn', sa.String(length=256), nullable=True),
    sa.Column('email', sa.String(length=256), nullable=True),
    sa.Column('full_name', sa.String(length=512), nullable=False),
    sa.Column('last_name', sa.String(length=128), nullable=True),
    sa.Column('first_name', sa.String(length=128), nullable=True),
    sa.Column('middle_name', sa.String(length=128), nullable=True),
    sa.Column('title', sa.String(length=256), nullable=True),
    sa.Column('department', sa.String(length=256), nullable=True),
    sa.Column('company', sa.String(length=256), nullable=True),
    sa.Column('office', sa.String(length=256), nullable=True),
    sa.Column('phone', sa.String(length=64), nullable=True),
    sa.Column('mobile', sa.String(length=64), nullable=True),
    sa.Column('manager_dn', sa.Text(), nullable=True),
    sa.Column('manager_name', sa.String(length=512), nullable=True),
    sa.Column('employee_id', sa.String(length=64), nullable=True),
    sa.Column('photo_key', sa.String(length=256), nullable=True),
    sa.Column('photo_sha256', sa.String(length=64), nullable=True),
    sa.Column('ad_groups', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('address_form', sa.String(length=32), nullable=True),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('is_blocked', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('blocked_reason', sa.Text(), nullable=True),
    sa.Column('blocked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('blocked_by', sa.Uuid(), nullable=True),
    sa.Column('ad_disabled', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('notice_accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['blocked_by'], ['users.id'], name=op.f('fk_users_blocked_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('ad_guid', name=op.f('uq_users_ad_guid')),
    sa.UniqueConstraint('login', name=op.f('uq_users_login'))
    )
    op.create_index(op.f('ix_users_blocked_by'), 'users', ['blocked_by'], unique=False)
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_app_settings_updated_by_users')),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_app_settings'))
    )
    op.create_index(op.f('ix_app_settings_updated_by'), 'app_settings', ['updated_by'], unique=False)
    op.create_table('audit_log',
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target_type', sa.String(length=64), nullable=True),
    sa.Column('target_id', sa.String(length=128), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_log_actor_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index(op.f('ix_audit_log_action'), 'audit_log', ['action'], unique=False)
    op.create_index(op.f('ix_audit_log_actor_id'), 'audit_log', ['actor_id'], unique=False)
    op.create_index(op.f('ix_audit_log_target_id'), 'audit_log', ['target_id'], unique=False)
    op.create_index(op.f('ix_audit_log_ts'), 'audit_log', ['ts'], unique=False)
    op.create_table('login_events',
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('login_attempted', sa.String(length=256), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.Column('method', sa.String(length=16), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('failure_reason', sa.String(length=64), nullable=True),
    sa.Column('risk_flags', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], name=op.f('fk_login_events_reviewed_by_users')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_login_events_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_events'))
    )
    op.create_index(op.f('ix_login_events_login_attempted'), 'login_events', ['login_attempted'], unique=False)
    op.create_index(op.f('ix_login_events_reviewed_by'), 'login_events', ['reviewed_by'], unique=False)
    op.create_index(op.f('ix_login_events_ts'), 'login_events', ['ts'], unique=False)
    op.create_index(op.f('ix_login_events_user_id'), 'login_events', ['user_id'], unique=False)
    op.create_table('role_permissions',
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('permission_code', sa.String(length=128), nullable=False),
    sa.ForeignKeyConstraint(['permission_code'], ['permissions.code'], name=op.f('fk_role_permissions_permission_code_permissions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_role_permissions_role_id_roles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('role_id', 'permission_code', name=op.f('pk_role_permissions'))
    )
    op.create_index(op.f('ix_role_permissions_permission_code'), 'role_permissions', ['permission_code'], unique=False)
    op.create_table('sessions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by', sa.Uuid(), nullable=True),
    sa.Column('revoke_reason', sa.String(length=64), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['revoked_by'], ['users.id'], name=op.f('fk_sessions_revoked_by_users')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_sessions_token_hash'))
    )
    op.create_index(op.f('ix_sessions_revoked_by'), 'sessions', ['revoked_by'], unique=False)
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('user_roles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('granted_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['granted_by'], ['users.id'], name=op.f('fk_user_roles_granted_by_users')),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_user_roles_role_id_roles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_roles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role_id', 'source', name=op.f('pk_user_roles'))
    )
    op.create_index(op.f('ix_user_roles_granted_by'), 'user_roles', ['granted_by'], unique=False)
    op.create_index(op.f('ix_user_roles_role_id'), 'user_roles', ['role_id'], unique=False)

    op.execute(
        """
        CREATE FUNCTION audit_log_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log: изменение и удаление записей запрещены';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_append_only()")
    op.drop_index(op.f('ix_user_roles_role_id'), table_name='user_roles')
    op.drop_index(op.f('ix_user_roles_granted_by'), table_name='user_roles')
    op.drop_table('user_roles')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_revoked_by'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_role_permissions_permission_code'), table_name='role_permissions')
    op.drop_table('role_permissions')
    op.drop_index(op.f('ix_login_events_user_id'), table_name='login_events')
    op.drop_index(op.f('ix_login_events_ts'), table_name='login_events')
    op.drop_index(op.f('ix_login_events_reviewed_by'), table_name='login_events')
    op.drop_index(op.f('ix_login_events_login_attempted'), table_name='login_events')
    op.drop_table('login_events')
    op.drop_index(op.f('ix_audit_log_ts'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_target_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_actor_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_action'), table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_index(op.f('ix_app_settings_updated_by'), table_name='app_settings')
    op.drop_table('app_settings')
    op.drop_index(op.f('ix_users_blocked_by'), table_name='users')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('permissions')
