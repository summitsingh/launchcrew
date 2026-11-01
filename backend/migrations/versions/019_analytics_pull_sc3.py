"""SC3 analytics pull: provider metrics per verified delivery with honesty rule.

Additive only. One analytics_pulls row per slot per channel carries
the latest provider metrics refresh (manual or scheduled) for a
verified delivery. Each canonical metric (reach, likes, comments,
clicks, shares) stores either a nonnegative integer or the exact
string "not reported" when the platform does not offer it; omitted
or unsupported metrics are never coerced to 0. outcome_id links to
the synced run_outcomes row when the slot names a run.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'analytics_pulls',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('slot_id', sa.Text, sa.ForeignKey('calendar_slots.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('channel', sa.Text, nullable=False),
        sa.Column('run_id', sa.Text, nullable=True),
        sa.Column('outcome_id', sa.Text, nullable=True),
        sa.Column('source_label', sa.Text, nullable=False),
        sa.Column('refresh_mode', sa.Text, nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('metrics', JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column('reported_metrics', JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('unreported_metrics', JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('raw_provider_payload', JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("refresh_mode IN ('manual','scheduled')",
                           name='analytics_pulls_refresh_mode'),
        sa.UniqueConstraint('slot_id', 'channel',
                            name='analytics_pulls_slot_channel'),
    )
    op.create_index('analytics_pulls_workspace_slot', 'analytics_pulls',
                    ['workspace_id', 'slot_id'])
    op.create_index('analytics_pulls_workspace_channel', 'analytics_pulls',
                    ['workspace_id', 'channel'])


def downgrade():
    op.drop_index('analytics_pulls_workspace_channel', table_name='analytics_pulls')
    op.drop_index('analytics_pulls_workspace_slot', table_name='analytics_pulls')
    op.drop_table('analytics_pulls')
