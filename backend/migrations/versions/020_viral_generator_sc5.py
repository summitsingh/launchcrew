"""SC5 viral format generator: metered credits and owner-media packs.

Additive only. One viral_generation_credits row per workspace carries
the visible remaining credit balance plus the lifetime used count, so
generation fails closed at zero before any pipeline or provider call.
One viral_generations row per metered build links the owner-media
carousel or short video pack to the normal approval-bound Checked run.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'viral_generation_credits',
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), primary_key=True),
        sa.Column('remaining_credits', sa.Integer, nullable=False, server_default=sa.text('10')),
        sa.Column('total_used_credits', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint('remaining_credits >= 0', name='viral_credits_nonnegative'),
        sa.CheckConstraint('total_used_credits >= 0', name='viral_used_nonnegative'),
    )
    op.create_table(
        'viral_generations',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('output_format', sa.Text, nullable=False),
        sa.Column('media_mode', sa.Text, nullable=False),
        sa.Column('asset_ids', JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('confirmed_facts', sa.Text, nullable=False),
        sa.Column('run_id', sa.Text, nullable=True),
        sa.Column('slot_id', sa.Text, sa.ForeignKey('calendar_slots.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('credits_charged', sa.Integer, nullable=False,
                  server_default=sa.text('1')),
        sa.Column('remaining_credits_after', sa.Integer, nullable=True),
        sa.Column('media_provenance', sa.Text, nullable=False,
                  server_default='owner_upload_only'),
        sa.Column('frames_or_scenes', JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('checker_passed', sa.Boolean, nullable=False,
                  server_default=sa.text('false')),
        sa.Column('approval_state', sa.Text, nullable=False,
                  server_default='awaiting_human_approval'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("output_format IN ('carousel','short_video')",
                           name='viral_generations_format'),
        sa.CheckConstraint("media_mode IN ('screenshots','screen_recording')",
                           name='viral_generations_mode'),
    )
    op.create_index('viral_generations_workspace', 'viral_generations', ['workspace_id'])
    op.create_index('viral_generations_workspace_created', 'viral_generations',
                    ['workspace_id', 'created_at'])


def downgrade():
    op.drop_index('viral_generations_workspace_created', table_name='viral_generations')
    op.drop_index('viral_generations_workspace', table_name='viral_generations')
    op.drop_table('viral_generations')
    op.drop_table('viral_generation_credits')
