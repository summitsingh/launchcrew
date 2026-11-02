"""Owner-saved virtual characters for AI product shoots.

A character is a reusable virtual model: a name plus appearance notes
the owner writes (build, style, look) and optional scene defaults. No
real-person likeness is claimed or stored; characters are original
concepts the owner describes. Generation jobs reference a character by
id and the prompt builder binds its appearance into the shoot prompt.
"""

from alembic import op
import sqlalchemy as sa

revision = '028'
down_revision = '026'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'image_characters',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('workspace_id', sa.Text, sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('appearance', sa.Text, nullable=False),
        sa.Column('style_notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint('workspace_id', 'name', name='image_characters_workspace_name'),
    )
    op.create_index('image_characters_workspace', 'image_characters', ['workspace_id', 'id'])


def downgrade():
    op.execute(
        'DO $$ BEGIN '
        'IF EXISTS (SELECT 1 FROM image_characters) THEN '
        'RAISE EXCEPTION \'Cannot downgrade: image_characters rows exist; delete characters before restoring the pre-character schema.\' USING ERRCODE = \'P0001\'; '
        'END IF; END $$;'
    )
    op.drop_table('image_characters')
