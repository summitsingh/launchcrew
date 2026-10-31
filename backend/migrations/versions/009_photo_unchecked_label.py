"""Allow explicit unchecked SAM verdict in the admission ledger.

Transport errors finalize as an unchecked verdict that does not block
text-only approval. Only a completed segmentation check binds photo state
into approval.
"""
from alembic import op

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('sam_call_label', 'sam_calls', type_='check')
    op.create_check_constraint(
        'sam_call_label', 'sam_calls',
        "label IN ('detected','not_detected','possible_clipping','unknown','not_run','unchecked')",
    )


def downgrade():
    op.drop_constraint('sam_call_label', 'sam_calls', type_='check')
    op.create_check_constraint(
        'sam_call_label', 'sam_calls',
        "label IN ('detected','not_detected','possible_clipping','unknown','not_run')",
    )
