"""Owner-saved post templates: named run starting points, workspace owned.

A template stores the run creation inputs (idea, stage agent names,
checker profile, optional product facts) so an owner can reuse a
proven setup without retyping. Applying a template creates a brand
new run through the normal pipeline and gates: the missing-core
facts gate applies with no template waiver, and the run binds a
snapshot copy so later template edits never rewrite a stored run.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '023'
down_revision = '022'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'owner_templates',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('idea', sa.Text, nullable=False),
        sa.Column('agent_name', sa.Text, nullable=False, server_default='Maker'),
        sa.Column('scout_name', sa.Text, nullable=True),
        sa.Column('maker_name', sa.Text, nullable=True),
        sa.Column('checker_name', sa.Text, nullable=True),
        sa.Column('checker_profile', sa.Text, nullable=False, server_default='standard'),
        sa.Column('product_facts', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint('workspace_id', 'name', name='owner_templates_workspace_name'),
        sa.CheckConstraint("checker_profile IN ('standard','strict')",
                           name='owner_templates_profile'),
    )
    op.create_index('owner_templates_workspace', 'owner_templates', ['workspace_id', 'id'])


def downgrade():
    op.execute(
        'DO $$ BEGIN '
        'IF EXISTS (SELECT 1 FROM owner_templates) THEN '
        'RAISE EXCEPTION \'Cannot downgrade: owner_templates rows exist; delete templates before restoring the pre-template schema.\' USING ERRCODE = \'P0001\'; '
        'END IF; END $$;'
    )
    op.drop_table('owner_templates')
