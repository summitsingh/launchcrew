"""Incremental stage receipts for async runs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('run_steps',
                    sa.Column('id', sa.BigInteger, sa.Identity(), primary_key=True),
                    sa.Column('run_id', sa.Text, sa.ForeignKey('runs.id'), nullable=False),
                    sa.Column('seq', sa.Integer, nullable=False),
                    sa.Column('stage', sa.Text, nullable=False),
                    sa.Column('state', sa.Text, nullable=False),
                    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
                    sa.Column('profile', sa.Text, nullable=False, server_default=''),
                    sa.Column('evidence', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
                    sa.CheckConstraint("state IN ('started','completed','failed')", name='run_step_state'))
    op.create_index('run_steps_order', 'run_steps', ['run_id', 'seq', 'id'])
    op.create_index('run_steps_run_time', 'run_steps', ['run_id', 'observed_at', 'id'])


def downgrade():
    op.drop_table('run_steps')
