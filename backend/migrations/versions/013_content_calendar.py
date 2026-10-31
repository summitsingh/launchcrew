"""Content calendar slots scoped to workspaces.

One row per placed day slot. Slot types and statuses are closed sets
enforced at the database layer. Pillars accept the five built-in values
plus any owner-added non-empty label; format is free text.
"""
from alembic import op
import sqlalchemy as sa

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'calendar_slots',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('slot_date', sa.Date, nullable=False),
        sa.Column('slot_type', sa.Text, nullable=False),
        sa.Column('pillar', sa.Text, nullable=False, server_default='product'),
        sa.Column('format', sa.Text, nullable=False, server_default=''),
        sa.Column('status', sa.Text, nullable=False, server_default='drafted'),
        sa.Column('run_id', sa.Text, nullable=True),
        sa.Column('campaign_id', sa.Text, nullable=True),
        sa.Column('campaign_day', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("slot_type IN ('feed_post','story','reel')", name='calendar_slot_type'),
        sa.CheckConstraint("status IN ('drafted','checked','approved','exported','verified')",
                           name='calendar_slot_status'),
        sa.ForeignKeyConstraint(['run_id', 'workspace_id'], ['runs.id', 'runs.workspace_id']),
        sa.ForeignKeyConstraint(['campaign_id', 'workspace_id'],
                                ['campaigns.id', 'campaigns.workspace_id']),
    )
    op.create_index('calendar_slots_workspace_date', 'calendar_slots', ['workspace_id', 'slot_date'])
    op.create_index('calendar_slots_workspace_run', 'calendar_slots', ['workspace_id', 'run_id'])


def downgrade():
    op.drop_index('calendar_slots_workspace_run', table_name='calendar_slots')
    op.drop_index('calendar_slots_workspace_date', table_name='calendar_slots')
    op.drop_table('calendar_slots')
