"""Owner-reported outcome loop after an approved export.

Additive table run_outcomes for Slice 6. Each row is an immutable
owner self-report bound to one approved and exported run revision in
the actor workspace. No provider measurement, no ROI, no auto-post,
and no seeded real-looking rows.

Columns mirror launchcrew.outcome_log bounds without duplicating its
helper: channel is the exact closed set, posted_date is a real DATE,
likes/comments/clicks/sales are distinct bounded nonnegative ints
0..1000000, note is 1..500 chars with no control characters and no
whitespace-only value, provenance is always self_reported, actor is
the verified server actor (never demo_placeholder), and created_at is
the server timestamp.

Workspace isolation follows migration 006: workspace_id has no
persistent DEFAULT so an omitted owner fails closed, a plain FK to
workspaces plus a composite FK (run_id, workspace_id) to
runs(id, workspace_id) denies cross-workspace parent links at the DB
layer, and the read index is workspace-scoped. Rows are immutable by
convention: the API offers POST and GET only, with no PUT or DELETE.
Historical rows keep their stored export_revision after later edits;
new logs are gated in application SQL on the current approved and
exported revision.
"""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None

# Closed channel set, kept identical to launchcrew.outcome_log.KNOWN_CHANNELS.
_CHANNELS = ("email", "facebook", "in_person", "instagram", "linkedin",
             "other", "phone", "sms", "web", "x")
_CHANNEL_LIST = ", ".join("'%s'" % channel for channel in _CHANNELS)


def upgrade():
    op.create_table(
        'run_outcomes',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('run_id', sa.Text, nullable=False),
        sa.Column('workspace_id', sa.Text, nullable=False),
        sa.Column('export_revision', sa.Integer, nullable=False),
        sa.Column('channel', sa.Text, nullable=False),
        sa.Column('posted_date', sa.Date, nullable=False),
        sa.Column('likes', sa.Integer, nullable=False),
        sa.Column('comments', sa.Integer, nullable=False),
        sa.Column('clicks', sa.Integer, nullable=False),
        sa.Column('sales', sa.Integer, nullable=False),
        sa.Column('note', sa.Text, nullable=False),
        sa.Column('provenance', sa.Text, nullable=False),
        sa.Column('actor', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name='run_outcomes_workspace_fkey'),
        sa.ForeignKeyConstraint(['run_id', 'workspace_id'],
                                ['runs.id', 'runs.workspace_id'],
                                name='run_outcomes_run_workspace_fkey'),
        sa.CheckConstraint('export_revision >= 0',
                           name='run_outcomes_revision_non_negative'),
        sa.CheckConstraint('channel IN (%s)' % _CHANNEL_LIST,
                           name='run_outcomes_channel'),
        sa.CheckConstraint('likes >= 0 AND likes <= 1000000',
                           name='run_outcomes_likes_bounds'),
        sa.CheckConstraint('comments >= 0 AND comments <= 1000000',
                           name='run_outcomes_comments_bounds'),
        sa.CheckConstraint('clicks >= 0 AND clicks <= 1000000',
                           name='run_outcomes_clicks_bounds'),
        sa.CheckConstraint('sales >= 0 AND sales <= 1000000',
                           name='run_outcomes_sales_bounds'),
        sa.CheckConstraint("char_length(note) >= 1 AND char_length(note) <= 500 "
                           "AND btrim(note) <> ''",
                           name='run_outcomes_note_length'),
        sa.CheckConstraint("note !~ '[[:cntrl:]]'",
                           name='run_outcomes_note_no_control'),
        sa.CheckConstraint("provenance = 'self_reported'",
                           name='run_outcomes_provenance'),
        sa.CheckConstraint("btrim(actor) <> '' AND actor <> 'demo_placeholder'",
                           name='run_outcomes_actor_signed_in'),
    )
    op.create_index('run_outcomes_workspace_run', 'run_outcomes',
                    ['workspace_id', 'run_id', 'created_at', 'id'])


def downgrade():
    op.drop_index('run_outcomes_workspace_run', table_name='run_outcomes')
    op.drop_table('run_outcomes')
