"""Owner-confirmed live sign-in record for Google and Facebook.

Health reports enabled_verified only when this table holds one row for
google and one row for facebook. Rows are written only by the
owner-operated proof script after a real end-to-end sign-in for each
provider, never by the OAuth callback and never by mocked tests.
"""

from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'auth_live_verifications',
        sa.Column('provider', sa.Text, primary_key=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('note', sa.Text, nullable=False, server_default=''),
    )
    op.create_check_constraint(
        'auth_live_verifications_provider',
        'auth_live_verifications',
        "provider IN ('google', 'facebook')",
    )


def downgrade():
    op.drop_table('auth_live_verifications')
