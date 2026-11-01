"""SC1 brand account connections with per-account live capabilities.

Additive only. One social_connections row per workspace per platform
carries the encrypted server-side token, the granted scopes with
plain-language descriptions, and the fetched live account capabilities
that feed the S2 capabilities table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'social_connections',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('platform', sa.Text, nullable=False),
        sa.Column('account_handle', sa.Text, nullable=True),
        sa.Column('account_name', sa.Text, nullable=True),
        sa.Column('external_account_id', sa.Text, nullable=True),
        sa.Column('account_type', sa.Text, nullable=False, server_default='brand'),
        sa.Column('encrypted_token', sa.Text, nullable=True),
        sa.Column('scopes', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('scopes_plain', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('capabilities', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('status', sa.Text, nullable=False, server_default='connected'),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column('disconnected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "platform IN ('instagram','facebook','threads','x','tiktok','pinterest','youtube','linkedin',"
            "'reddit','wordpress','discord','telegram')",
            name='social_connections_platform'),
        sa.CheckConstraint(
            "account_type IN ('brand','personal')",
            name='social_connections_account_type'),
        sa.CheckConstraint(
            "status IN ('connected','disconnected','review_pending_flag')",
            name='social_connections_status'),
        sa.UniqueConstraint('workspace_id', 'platform', name='social_connections_workspace_platform'),
    )
    op.create_index('social_connections_workspace', 'social_connections', ['workspace_id'])
    op.create_index('social_connections_workspace_status', 'social_connections', ['workspace_id', 'status'])


def downgrade():
    op.drop_index('social_connections_workspace_status', table_name='social_connections')
    op.drop_index('social_connections_workspace', table_name='social_connections')
    op.drop_table('social_connections')
