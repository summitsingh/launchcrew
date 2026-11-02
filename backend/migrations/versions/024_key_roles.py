"""Seat key roles: owner, editor, viewer per workspace key.

Additive only. Existing keys default to owner, preserving current
behavior. Viewer keys are read-only at the workspace gate; editor and
owner keys keep every granted scope.
"""

from alembic import op
import sqlalchemy as sa

revision = '024'
down_revision = '023'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workspace_api_keys',
                  sa.Column('role', sa.Text, nullable=False, server_default='owner'))
    op.create_check_constraint('workspace_api_keys_role', 'workspace_api_keys',
                               "role IN ('owner','editor','viewer')")


def downgrade():
    op.drop_constraint('workspace_api_keys_role', 'workspace_api_keys')
    op.drop_column('workspace_api_keys', 'role')
