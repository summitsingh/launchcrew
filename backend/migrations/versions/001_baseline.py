"""Adopt the recovered Postgres schema and add server-side auth sessions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('agents', sa.Column('name', sa.Text, primary_key=True), sa.Column('profile', JSONB, nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table('runs', sa.Column('id', sa.Text, primary_key=True), sa.Column('receipt', JSONB, nullable=False), sa.Column('agent_name', sa.Text, sa.ForeignKey('agents.name'), nullable=False), sa.Column('state', sa.Text, nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.CheckConstraint("state IN ('pending_approval','approved_for_export')", name='run_state'))
    op.create_table('approvals', sa.Column('run_id', sa.Text, sa.ForeignKey('runs.id'), primary_key=True), sa.Column('approved_by', sa.Text, nullable=False), sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table('memory', sa.Column('run_id', sa.Text, sa.ForeignKey('runs.id'), primary_key=True), sa.Column('facts', JSONB, nullable=False))
    op.create_table('audit', sa.Column('id', sa.BigInteger, sa.Identity(), primary_key=True), sa.Column('run_id', sa.Text, sa.ForeignKey('runs.id')), sa.Column('action', sa.Text, nullable=False), sa.Column('actor', sa.Text, nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('runs_queue', 'runs', ['state', 'created_at', 'id'])
    op.create_index('audit_run_time', 'audit', ['run_id', 'created_at', 'id'])
    op.create_table('auth_sessions', sa.Column('id', sa.Text, primary_key=True), sa.Column('data', JSONB, nullable=False), sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('auth_sessions_expiry', 'auth_sessions', ['expires_at'])


def downgrade():
    for table in ('auth_sessions', 'audit', 'memory', 'approvals', 'runs', 'agents'):
        op.drop_table(table)
