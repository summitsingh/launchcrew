"""Durable SAM admission ledger plus one-shot global budget.

No grant is issued here: the global budget defaults to zero and any
later grant arrives only through operator-controlled backfill, never
through a public route. Provider file IDs are never persisted.
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sam_budget',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('remaining_images', sa.Integer, nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 'global'", name='sam_budget_single_row'),
        sa.CheckConstraint('remaining_images >= 0', name='sam_budget_non_negative'),
    )
    op.execute("INSERT INTO sam_budget(id, remaining_images) VALUES ('global', 0)")
    op.create_table(
        'sam_calls',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('run_id', sa.Text, sa.ForeignKey('runs.id'), nullable=False),
        sa.Column('revision', sa.Integer, nullable=False),
        sa.Column('photo_sha256', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('label', sa.Text, nullable=True),
        sa.Column('reason', sa.Text, nullable=True),
        sa.Column('policy_version', sa.Text, nullable=False, server_default='photo-geometry/v1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('admitted','succeeded','failed_terminal')", name='sam_call_status'),
        sa.CheckConstraint("label IN ('detected','not_detected','possible_clipping','unknown','not_run')", name='sam_call_label'),
        sa.UniqueConstraint('run_id', 'revision', name='sam_call_run_revision'),
    )
    op.create_index('sam_calls_run', 'sam_calls', ['run_id', 'revision'])


def downgrade():
    op.drop_index('sam_calls_run', table_name='sam_calls')
    op.drop_table('sam_calls')
    op.drop_table('sam_budget')
