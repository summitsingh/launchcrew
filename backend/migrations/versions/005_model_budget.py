"""Global model budget plus durable call ledger.

Zero-default planning reservation in integer USD micros: one bounded
Standard call reserves a fixed 4 USD (4000000 micros). This is a local
planning reservation only, never an external provider hard cap. No grant
is issued here and no refill path exists; a private operator grant is
future separate work.

The ledger has no FK to runs: sync runs and Campaign execute model work
before their run row commits, while async runs commit before a worker.
Never locking run rows avoids a lock order cycle.
"""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'model_budget',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('remaining_micros', sa.BigInteger, nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 'global'", name='model_budget_single_row'),
        sa.CheckConstraint('remaining_micros >= 0', name='model_budget_non_negative'),
    )
    op.execute("INSERT INTO model_budget(id, remaining_micros) VALUES ('global', 0)")
    op.create_table(
        'model_calls',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('run_id', sa.Text, nullable=False),
        sa.Column('stage', sa.Text, nullable=False),
        sa.Column('attempt_id', sa.Text, nullable=False),
        sa.Column('request_digest', sa.Text, nullable=False),
        sa.Column('model', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('outcome', sa.Text, nullable=True),
        sa.Column('prompt_tokens', sa.Integer, nullable=True),
        sa.Column('completion_tokens', sa.Integer, nullable=True),
        sa.Column('total_tokens', sa.Integer, nullable=True),
        sa.Column('reservation_micros', sa.BigInteger, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('admitted','succeeded','failed_terminal','ambiguous_terminal')",
            name='model_call_status'),
        sa.CheckConstraint('reservation_micros = 4000000', name='model_call_fixed_reservation'),
        sa.CheckConstraint(
            'prompt_tokens IS NULL OR prompt_tokens >= 0',
            name='model_call_prompt_tokens_non_negative'),
        sa.CheckConstraint(
            'completion_tokens IS NULL OR completion_tokens >= 0',
            name='model_call_completion_tokens_non_negative'),
        sa.CheckConstraint(
            'total_tokens IS NULL OR total_tokens >= 0',
            name='model_call_total_tokens_non_negative'),
        sa.UniqueConstraint('run_id', 'stage', 'attempt_id', name='model_call_identity'),
    )
    op.create_index('model_calls_status', 'model_calls', ['status'])


def downgrade():
    op.drop_index('model_calls_status', table_name='model_calls')
    op.drop_table('model_calls')
    op.drop_table('model_budget')
