"""SC4 media library: upload once, format facts, non-destructive derivatives.

Additive only. One media_assets row per uploaded image or video carries
its recorded format facts (dimensions, aspect, duration) plus the
digest of the immutable original and the channel-ready crop derivatives
stored alongside it. One media_attachments row per slot attachment binds
an asset to a slot and one or more channels with the resolved
per-channel derivative mapping and the Checker format validation.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'media_assets',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('filename', sa.Text, nullable=False),
        sa.Column('media_type', sa.Text, nullable=False),
        sa.Column('mime_type', sa.Text, nullable=True),
        sa.Column('width', sa.Integer, nullable=False),
        sa.Column('height', sa.Integer, nullable=False),
        sa.Column('aspect_ratio', sa.Text, nullable=False),
        sa.Column('duration_seconds', sa.Float, nullable=True),
        sa.Column('sha256_digest', sa.Text, nullable=False),
        sa.Column('original_data_b64', sa.Text, nullable=True),
        sa.Column('derivatives', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("media_type IN ('image','video')", name='media_assets_type'),
    )
    op.create_index('media_assets_workspace', 'media_assets', ['workspace_id'])
    op.create_table(
        'media_attachments',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('asset_id', sa.Text, sa.ForeignKey('media_assets.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('slot_id', sa.Text, sa.ForeignKey('calendar_slots.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('run_id', sa.Text, nullable=True),
        sa.Column('channels', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('channel_derivatives', JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column('use_original_without_derivative', sa.Boolean, nullable=False,
                  server_default=sa.text('false')),
        sa.Column('format_validation', JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index('media_attachments_workspace_slot', 'media_attachments',
                    ['workspace_id', 'slot_id'])
    op.create_index('media_attachments_workspace_asset', 'media_attachments',
                    ['workspace_id', 'asset_id'])


def downgrade():
    op.drop_index('media_attachments_workspace_asset', table_name='media_attachments')
    op.drop_index('media_attachments_workspace_slot', table_name='media_attachments')
    op.drop_table('media_attachments')
    op.drop_index('media_assets_workspace', table_name='media_assets')
    op.drop_table('media_assets')
