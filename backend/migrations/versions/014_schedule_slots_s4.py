"""S4 schedule slots: planned times, channel selection, and validate gate.

Additive only. New columns on calendar_slots carry planning data
(planning only, never publishes); existing rows backfill from
owner daily defaults per slot type. A new calendar_schedule_defaults
table stores the owner-set daily default time per slot type.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('calendar_slots',
                  sa.Column('planned_time', sa.Text, nullable=True))
    op.add_column('calendar_slots',
                  sa.Column('selected_channels', JSONB, nullable=False,
                            server_default=sa.text("'[]'::jsonb")))
    op.add_column('calendar_slots',
                  sa.Column('approved_channels', JSONB, nullable=False,
                            server_default=sa.text("'[]'::jsonb")))
    op.add_column('calendar_slots',
                  sa.Column('schedule_state', sa.Text, nullable=False,
                            server_default='draft'))
    op.execute("UPDATE calendar_slots SET planned_time = CASE slot_type "
               "WHEN 'feed_post' THEN '09:00' WHEN 'story' THEN '13:00' "
               "WHEN 'reel' THEN '18:00' ELSE '09:00' END "
               "WHERE planned_time IS NULL")
    op.execute("UPDATE calendar_slots SET schedule_state = 'draft' "
               "WHERE schedule_state IS NULL OR schedule_state NOT IN ('draft', 'ready')")
    op.create_check_constraint('calendar_slot_schedule_state',
                               'calendar_slots',
                               "schedule_state IN ('draft','ready')")
    op.create_table(
        'calendar_schedule_defaults',
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('slot_type', sa.Text, nullable=False),
        sa.Column('planned_time', sa.Text, nullable=False, server_default='09:00'),
        sa.PrimaryKeyConstraint('workspace_id', 'slot_type', name='calendar_schedule_defaults_pkey'),
        sa.CheckConstraint("slot_type IN ('feed_post','story','reel')",
                           name='calendar_schedule_defaults_slot_type'),
    )


def downgrade():
    op.drop_table('calendar_schedule_defaults')
    op.drop_constraint('calendar_slot_schedule_state', 'calendar_slots', type_='check')
    op.drop_column('calendar_slots', 'schedule_state')
    op.drop_column('calendar_slots', 'approved_channels')
    op.drop_column('calendar_slots', 'selected_channels')
    op.drop_column('calendar_slots', 'planned_time')
