"""A5: flag deliveries posted by the simulated transport.

Additive only. calendar_slot_deliveries.simulated marks rows whose post
came from the simulated publish transport, so the board can chip them.
Manual owner mark-posted rows and verification attempts are unaffected.
"""

from alembic import op
import sqlalchemy as sa

revision = '032'
down_revision = '031'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('calendar_slot_deliveries',
                  sa.Column('simulated', sa.Boolean(), nullable=False,
                            server_default=sa.text('false')))


def downgrade():
    op.drop_column('calendar_slot_deliveries', 'simulated')
