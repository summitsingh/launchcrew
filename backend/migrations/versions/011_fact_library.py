"""Per-product facts library with per-variant confirmed fact sets.

Gap 5 storage: named products owned by one workspace, each holding
named variants. A variant stores one product-facts input object (the
same typed shape as POST /api/runs product_facts) plus an explicit
confirmed flag. Runs bind a snapshot copy of the variant facts at
creation time, so later library edits never rewrite a stored run
receipt. Downgrade refuses when library rows exist so no committed
facts are silently orphaned.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fact_products',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint('workspace_id', 'name', name='fact_products_workspace_name'),
    )
    op.create_index('fact_products_workspace', 'fact_products', ['workspace_id', 'id'])
    op.create_table(
        'fact_variants',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('product_id', sa.Text, sa.ForeignKey('fact_products.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('facts', JSONB, nullable=False),
        sa.Column('confirmed', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint('product_id', 'name', name='fact_variants_product_name'),
    )
    op.create_index('fact_variants_workspace', 'fact_variants', ['workspace_id', 'id'])
    op.create_index('fact_variants_product', 'fact_variants', ['product_id', 'id'])


def downgrade():
    op.execute(
        'DO $$ BEGIN '
        'IF EXISTS (SELECT 1 FROM fact_variants) THEN '
        'RAISE EXCEPTION \'Cannot downgrade: fact_variants rows exist; delete library variants before restoring the pre-library schema.\' USING ERRCODE = \'P0001\'; '
        'END IF; END $$;'
    )
    op.execute(
        'DO $$ BEGIN '
        'IF EXISTS (SELECT 1 FROM fact_products) THEN '
        'RAISE EXCEPTION \'Cannot downgrade: fact_products rows exist; delete library products before restoring the pre-library schema.\' USING ERRCODE = \'P0001\'; '
        'END IF; END $$;'
    )
    op.drop_table('fact_variants')
    op.drop_table('fact_products')
