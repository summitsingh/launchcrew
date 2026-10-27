"""Real Postgres integration tests isolated in a temporary schema."""
import os
from uuid import uuid4
import pytest
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from backend import store
from backend.app import app


@pytest.fixture(scope='session')
def test_engine():
    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+psycopg://', 1)
    admin = create_engine(url)
    schema = 'test_' + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text('CREATE SCHEMA ' + schema))
    db = create_engine(url, connect_args={'options': '-csearch_path=' + schema})
    original = store.engine
    store.engine = lambda: db
    command.upgrade(Config('alembic.ini'), 'head')
    yield db
    store.engine = original
    db.dispose()
    with admin.begin() as connection:
        connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
    admin.dispose()


@pytest.fixture
def client(test_engine, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'false')
    with test_engine.begin() as connection:
        connection.execute(text('TRUNCATE agents, runs, memory, approvals, audit, auth_sessions RESTART IDENTITY CASCADE'))
    with TestClient(app, base_url='https://testserver') as client:
        yield client
    app.dependency_overrides.clear()
