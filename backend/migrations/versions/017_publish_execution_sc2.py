"""SC2 autonomous Ready-slot publish executor state.

Additive only. One publish_executor_settings row per workspace carries
the owner kill switch; one publish_executions row per slot per channel
carries the deterministic idempotency key, the bounded retry trail,
and the platform result. A needs_approval schedule state records slots
that dropped out of Ready after a post-approval edit.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'publish_executor_settings',
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), primary_key=True),
        sa.Column('kill_switch_paused', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_by', sa.Text, nullable=True),
        sa.Column('reason', sa.Text, nullable=True),
    )
    op.create_table(
        'publish_executions',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('slot_id', sa.Text, sa.ForeignKey('calendar_slots.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('channel', sa.Text, nullable=False),
        sa.Column('idempotency_key', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False, server_default='pending'),
        sa.Column('platform_post_id', sa.Text, nullable=True),
        sa.Column('live_url', sa.Text, nullable=True),
        sa.Column('attempt_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('max_auto_retries', sa.Integer, nullable=False, server_default='2'),
        sa.Column('attempts', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('last_error', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending','posted','failed','skipped_needs_approval',"
                           "'paused_by_kill_switch')",
                           name='publish_executions_status'),
        sa.UniqueConstraint('idempotency_key', name='publish_executions_idempotency_key'),
    )
    op.create_index('publish_executions_workspace_slot', 'publish_executions',
                    ['workspace_id', 'slot_id'])
    op.create_index('publish_executions_workspace_status', 'publish_executions',
                    ['workspace_id', 'status'])
    op.drop_constraint('calendar_slot_schedule_state', 'calendar_slots', type_='check')
    op.create_check_constraint('calendar_slot_schedule_state', 'calendar_slots',
                               "schedule_state IN ('draft','ready','needs_approval')")


def downgrade():
    op.drop_constraint('calendar_slot_schedule_state', 'calendar_slots', type_='check')
    op.create_check_constraint('calendar_slot_schedule_state', 'calendar_slots',
                               "schedule_state IN ('draft','ready')")
    op.drop_index('publish_executions_workspace_status', table_name='publish_executions')
    op.drop_index('publish_executions_workspace_slot', table_name='publish_executions')
    op.drop_table('publish_executions')
    op.drop_table('publish_executor_settings')
