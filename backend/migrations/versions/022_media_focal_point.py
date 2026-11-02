"""Media focal point: owner-set crop focus per asset, additive only.

Adds nullable focal_x and focal_y relative coordinates to media_assets.
NULL keeps the historical centered behavior. Derivatives recomputed
under a focal point carry the focal digest and never overwrite the
original bytes, dimensions, or aspect.
"""

from alembic import op
import sqlalchemy as sa

revision = '022'
down_revision = '021'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('media_assets', sa.Column('focal_x', sa.Float, nullable=True))
    op.add_column('media_assets', sa.Column('focal_y', sa.Float, nullable=True))


def downgrade():
    op.drop_column('media_assets', 'focal_y')
    op.drop_column('media_assets', 'focal_x')
