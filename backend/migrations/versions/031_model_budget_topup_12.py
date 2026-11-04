"""Operator model budget top-up: restore the global planning balance to USD 12.

Owner-ordered on 2026-11-04 (WO-1): the balance read USD 2.00, so zero
new standard calls are admissible at the fixed USD 4.00 reservation and
the demo's planned fresh run fails at admission. This tops any balance
below the grant back up to exactly 12,000,000 micros, covering at least
three standard calls. The reservation amount is unchanged.

It never lowers a balance and never creates an off-path value: after
the update the row must read exactly 12,000,000 or the migration
fails loudly. Like 026 and 030 this is a local planning reservation
counter only, never an external provider hard cap: real metered billing
still happens on the key owner's provider account.

Downgrade is one-way on purpose: the pre-top-up remainder is not
recorded anywhere, so there is nothing honest to restore.
"""

from alembic import op

revision = '031'
down_revision = '030'
branch_labels = None
depends_on = None

GRANT_MICROS = 12000000


def upgrade():
    op.execute(
        "UPDATE model_budget SET remaining_micros = %d, updated_at = now() "
        "WHERE id = 'global' AND remaining_micros < %d"
        % (GRANT_MICROS, GRANT_MICROS)
    )
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM model_budget WHERE id = 'global' "
        "AND remaining_micros = %d) THEN "
        "RAISE EXCEPTION 'Top-up refused: global model budget is not "
        "exactly 12000000 micros after top-up.' USING ERRCODE = 'P0001'; "
        "END IF; END $$;" % GRANT_MICROS
    )


def downgrade():
    op.execute(
        "DO $$ BEGIN "
        "RAISE EXCEPTION 'Downgrade refused: the WO-1 top-up is one-way; "
        "the pre-top-up remainder was not recorded.' "
        "USING ERRCODE = 'P0001'; END $$;"
    )
