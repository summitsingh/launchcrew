"""S5 cross-post verification board: per-slot per-channel delivery rows.

Additive only. One calendar_slot_deliveries row per slot per channel
carries the delivery state (not_posted, posted, verified, failed), the
owner-marked live URL, the last verification match kind, the differing
field on mismatch, a plain-language failure reason, and a JSONB audit
trail of timestamped attempts in chronological order.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'calendar_slot_deliveries',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('slot_id', sa.Text, sa.ForeignKey('calendar_slots.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('channel', sa.Text, nullable=False),
        sa.Column('delivery_state', sa.Text, nullable=False, server_default='not_posted'),
        sa.Column('live_url', sa.Text, nullable=True),
        sa.Column('match_kind', sa.Text, nullable=True),
        sa.Column('differing_field', sa.Text, nullable=True),
        sa.Column('failure_reason', sa.Text, nullable=True),
        sa.Column('attempts', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("delivery_state IN ('not_posted','posted','verified','failed')",
                           name='calendar_delivery_state'),
        sa.CheckConstraint("match_kind IS NULL OR match_kind IN ('exact','trimmed_by_rule','mismatch')",
                           name='calendar_delivery_match_kind'),
        sa.UniqueConstraint('slot_id', 'channel', name='calendar_delivery_slot_channel'),
    )
    op.create_index('calendar_deliveries_workspace_slot', 'calendar_slot_deliveries',
                    ['workspace_id', 'slot_id'])
    op.create_index('calendar_deliveries_workspace_state', 'calendar_slot_deliveries',
                    ['workspace_id', 'delivery_state'])


def downgrade():
    op.drop_index('calendar_deliveries_workspace_state', table_name='calendar_slot_deliveries')
    op.drop_index('calendar_deliveries_workspace_slot', table_name='calendar_slot_deliveries')
    op.drop_table('calendar_slot_deliveries')
