"""Operator model budget grant: USD 10 of planning reservations.

Sets the single global planning balance to 10,000,000 micros (USD 10)
only when it is currently zero, so a fresh or fully spent balance
receives the grant while a partial balance is never overwritten. At
4,000,000 micros per bounded Standard call this funds two full model
calls with 2,000,000 micros left over. This is a local planning
reservation counter only, never an external provider hard cap: real
metered billing still happens on the key owner's provider account.

Downgrade removes the grant only when it is untouched; a partially
spent balance refuses rather than silently dropping remainder.
"""

from alembic import op

revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None

GRANT_MICROS = 10000000


def upgrade():
    op.execute(
        "UPDATE model_budget SET remaining_micros = %d, updated_at = now() "
        "WHERE id = 'global' AND remaining_micros = 0" % GRANT_MICROS
    )


def downgrade():
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM model_budget WHERE id = 'global' "
        "AND remaining_micros <> %d) THEN "
        "RAISE EXCEPTION 'Cannot downgrade: model budget partially spent; "
        "spend down or reconcile before restoring the zero default.' "
        "USING ERRCODE = 'P0001'; "
        "END IF; END $$;" % GRANT_MICROS
    )
    op.execute(
        "UPDATE model_budget SET remaining_micros = 0, updated_at = now() "
        "WHERE id = 'global' AND remaining_micros = %d" % GRANT_MICROS
    )
