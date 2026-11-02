"""Engagement triage intake: deterministic queue with staged handling.

Additive only. One engagement_items row per owner-logged platform
comment or DM carries the deterministic triage label plus the staged
reply state machine: none to draft to approved to handled. Approval
records readiness for a manual reply outside the product; nothing here
sends, hides, or deletes anything on a platform. Downgrade refuses
when rows exist so no logged engagement is silently dropped.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '025'
down_revision = '024'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'engagement_items',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('platform', sa.Text, nullable=False),
        sa.Column('kind', sa.Text, nullable=False),
        sa.Column('external_ref', sa.Text, nullable=False),
        sa.Column('author_handle', sa.Text, nullable=False),
        sa.Column('text', sa.Text, nullable=False),
        sa.Column('triage', sa.Text, nullable=False),
        sa.Column('reply_draft', sa.Text, nullable=True),
        sa.Column('reply_status', sa.Text, nullable=False, server_default='none'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint('workspace_id', 'platform', 'external_ref',
                            name='engagement_items_workspace_ref'),
        sa.CheckConstraint("kind IN ('comment','dm')", name='engagement_items_kind'),
        sa.CheckConstraint("triage IN ('question','complaint','praise','spam_risk','neutral')",
                           name='engagement_items_triage'),
        sa.CheckConstraint("reply_status IN ('none','draft','approved','handled')",
                           name='engagement_items_reply_status'),
    )
    op.create_index('engagement_items_workspace', 'engagement_items', ['workspace_id', 'id'])


def downgrade():
    op.execute(
        'DO $$ BEGIN '
        'IF EXISTS (SELECT 1 FROM engagement_items) THEN '
        'RAISE EXCEPTION \'Cannot downgrade: engagement_items rows exist; clear the queue before restoring the pre-triage schema.\' USING ERRCODE = \'P0001\'; '
        'END IF; END $$;'
    )
    op.drop_table('engagement_items')
