"""A6: allow payload-free analytics pulls to keep no raw payload.

Additive only. raw_provider_payload becomes nullable so a refresh
with no provider response stores NULL (nothing was received) instead
of a stand-in object. Payload pulls still store their dict.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '033'
down_revision = '032'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('analytics_pulls', 'raw_provider_payload',
                    existing_type=JSONB, nullable=True)


def downgrade():
    op.execute("UPDATE analytics_pulls SET raw_provider_payload='{}'::jsonb"
               ' WHERE raw_provider_payload IS NULL')
    op.alter_column('analytics_pulls', 'raw_provider_payload',
                    existing_type=JSONB, nullable=False)
