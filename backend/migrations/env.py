"""Migration connection shares the backend SQLAlchemy engine."""
from alembic import context
from backend.store import engine
with engine().connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
