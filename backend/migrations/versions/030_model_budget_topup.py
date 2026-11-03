"""Operator model budget top-up: restore the global planning balance to USD 10.

Owner-ordered on 2026-11-03 to fund the two R3 one-shot live proofs
(one Spark generation, one SAM segmentation). The 026 grant funds two
bounded Standard calls and leaves a designed remainder, so a used
grant sits at a partial balance the verify gate now admits but the
proofs cannot spend twice from. This tops any balance below the grant
back up to exactly 10,000,000 micros.

It never lowers a balance and never creates an off-path value: after
the update the row must read exactly 10,000,000 or the migration
fails loudly. Like 026 this is a local planning reservation counter
only, never an external provider hard cap: real metered billing still
happens on the key owner's provider account.

Downgrade is one-way on purpose: the pre-top-up remainder is not
recorded anywhere, so there is nothing honest to restore.
"""

from alembic import op

revision = '030'
down_revision = '029'
branch_labels = None
depends_on = None

GRANT_MICROS = 10000000


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
        "exactly 10000000 micros after top-up.' USING ERRCODE = 'P0001'; "
        "END IF; END $$;" % GRANT_MICROS
    )


def downgrade():
    op.execute(
        "DO $$ BEGIN "
        "RAISE EXCEPTION 'Downgrade refused: the R3 top-up is one-way; "
        "the pre-top-up remainder was not recorded.' "
        "USING ERRCODE = 'P0001'; END $$;"
    )
