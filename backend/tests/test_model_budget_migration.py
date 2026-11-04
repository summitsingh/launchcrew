"""Grant recovery on real Postgres, isolated from other test balances."""
import importlib
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text


@pytest.mark.parametrize('balance', [None, 0, 2000000, 12000000, 16000000])
def test_grant_floor_preserves_higher_balances_and_is_idempotent(test_engine, monkeypatch, balance):
    migration = importlib.import_module('backend.migrations.versions.034_model_budget_grant_floor')
    with test_engine.connect() as db:
        transaction = db.begin()
        try:
            db.execute(text("DELETE FROM model_budget WHERE id='global'"))
            if balance is not None:
                db.execute(text("INSERT INTO model_budget(id,remaining_micros) VALUES ('global',:balance)"), {'balance': balance})
            monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(db)))
            migration.upgrade()
            migration.upgrade()
            assert db.execute(text("SELECT remaining_micros FROM model_budget WHERE id='global'")).scalar() == max(balance or 0, 12000000)
        finally:
            transaction.rollback()
