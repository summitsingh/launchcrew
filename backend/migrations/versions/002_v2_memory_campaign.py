"""Editable explicit memory and individually reviewed campaign packs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('memory_items',
                    sa.Column('id', sa.Text, primary_key=True),
                    sa.Column('kind', sa.Text, nullable=False),
                    sa.Column('title', sa.Text, nullable=False),
                    sa.Column('content', JSONB, nullable=False),
                    sa.Column('source_run_id', sa.Text, sa.ForeignKey('runs.id')),
                    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
                    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
                    sa.CheckConstraint("kind IN ('brand_fact','profile','approval_example','blocked_rule')", name='memory_item_kind'))
    op.create_table('campaigns',
                    sa.Column('id', sa.Text, primary_key=True),
                    sa.Column('idea', sa.Text, nullable=False),
                    sa.Column('agent_name', sa.Text, nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table('campaign_days',
                    sa.Column('campaign_id', sa.Text, sa.ForeignKey('campaigns.id'), primary_key=True),
                    sa.Column('day', sa.Integer, primary_key=True),
                    sa.Column('run_id', sa.Text, sa.ForeignKey('runs.id'), nullable=False, unique=True),
                    sa.CheckConstraint('day BETWEEN 1 AND 7', name='campaign_day_range'))


def downgrade():
    for table in ('campaign_days', 'campaigns', 'memory_items'):
        op.drop_table(table)
