"""Waitlist signups for the Plans page.

Gap 11 storage: a global waitlist_signups table keyed by normalized
(lowercase, trimmed) email. Duplicates are refused at the database
level by a unique constraint so no signup is stored twice and no
submission is lost to a race between concurrent inserts.
"""

from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'waitlist_signups',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('email', sa.Text, nullable=False),
        sa.Column('interest', sa.Text, nullable=False, server_default='general'),
        sa.Column('tier', sa.Text, nullable=False, server_default='pro'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint('email', name='waitlist_signups_email_unique'),
    )
    op.create_index('waitlist_signups_created', 'waitlist_signups', ['created_at'])


def downgrade():
    op.drop_table('waitlist_signups')
