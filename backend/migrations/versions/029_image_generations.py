"""Image generation jobs: billable provider calls with snapshots.

One row per successful generation run: provider, model, prompt, the
character snapshot used, aspect, count, and the stored media asset
ids. Failed provider calls store nothing here; attempts remain
visible in the audit log. Provider billing happens on the owner's
provider account; this table meters job counts only.

Downgrade refuses when rows exist so no generation record is
silently dropped.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '029'
down_revision = '028'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'image_generations',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('provider', sa.Text, nullable=False),
        sa.Column('model', sa.Text, nullable=False),
        sa.Column('character_id', sa.Text, nullable=True),
        sa.Column('character_snapshot', sa.Text, nullable=True),
        sa.Column('prompt', sa.Text, nullable=False),
        sa.Column('aspect', sa.Text, nullable=False),
        sa.Column('count', sa.Integer, nullable=False),
        sa.Column('asset_ids', JSONB, nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("provider IN ('openai','xai','gemini')",
                           name='image_generations_provider'),
    )
    op.create_index('image_generations_workspace', 'image_generations', ['workspace_id', 'id'])


def downgrade():
    op.execute(
        'DO $$ BEGIN '
        'IF EXISTS (SELECT 1 FROM image_generations) THEN '
        'RAISE EXCEPTION \'Cannot downgrade: image_generations rows exist; clear the queue before restoring the pre-generation schema.\' USING ERRCODE = \'P0001\'; '
        'END IF; END $$;'
    )
    op.drop_table('image_generations')
