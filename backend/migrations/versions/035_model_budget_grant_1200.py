"""Apply a judging-window operator grant with a $1,200.00 minimum balance.

One-way, idempotent minimum balance of 1200000000 micros. Higher balances are never reduced.
This local reservation counter is not an external provider billing cap.
"""
from alembic import op

revision = '035'
down_revision = '034'
branch_labels = None
depends_on = None

GRANT_MICROS = 1200000000


def upgrade():
    op.execute("INSERT INTO model_budget(id, remaining_micros) VALUES ('global', 0) "
               "ON CONFLICT (id) DO NOTHING")
    op.execute(
        "UPDATE model_budget SET remaining_micros = %d, updated_at = now() "
        "WHERE id = 'global' AND remaining_micros < %d"
        % (GRANT_MICROS, GRANT_MICROS)
    )
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM model_budget WHERE id = 'global' "
        "AND remaining_micros >= %d) THEN "
        "RAISE EXCEPTION 'Top-up refused: global model budget is below "
        "1200000000 micros after grant.' USING ERRCODE = 'P0001'; "
        "END IF; END $$;" % GRANT_MICROS
    )


def downgrade():
    op.execute(
        "DO $$ BEGIN RAISE EXCEPTION 'Downgrade refused: the public demo grant "
        "is one-way; the pre-grant remainder was not recorded.' "
        "USING ERRCODE = 'P0001'; END $$;"
    )
