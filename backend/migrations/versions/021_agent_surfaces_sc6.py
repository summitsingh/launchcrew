"""SC6 agent surfaces: workspace API keys for the REST API, MCP server, and CLI.

Additive only. One workspace_api_keys row per owner-created key carries
the SHA-256 hash of the raw workspace key (the raw key is never stored),
the scopes it grants, and a revocation flag. All four surfaces (Web UI,
REST API, hosted MCP server, CLI) resolve the same workspace_id from the
key so they read and write the exact same workspace state.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'workspace_api_keys',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('label', sa.Text, nullable=False, server_default=''),
        sa.Column('key_prefix', sa.Text, nullable=False),
        sa.Column('key_hash', sa.Text, nullable=False),
        sa.Column('scopes', JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('revoked', sa.Boolean, nullable=False,
                  server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index('workspace_api_keys_workspace', 'workspace_api_keys', ['workspace_id'])
    op.create_index('workspace_api_keys_hash', 'workspace_api_keys', ['key_hash'])


def downgrade():
    op.drop_index('workspace_api_keys_hash', table_name='workspace_api_keys')
    op.drop_index('workspace_api_keys_workspace', table_name='workspace_api_keys')
    op.drop_table('workspace_api_keys')
