"""Real Postgres integration tests isolated in a temporary schema."""
import os
from pathlib import Path
from uuid import uuid4
import pytest
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from backend import store
from backend.app import app


@pytest.fixture(scope='session', autouse=True)
def demo_photo_seed():
    """Supply the operator-placed runtime photo the media seed reads.

    The starter-asset seed reads a runtime photo under facts/demo_photos/
    that is never committed. This fixture supplies that precondition
    hermetically for fresh clones, and is a no-op when a real photo is
    already present.
    """
    from PIL import Image

    photos_dir = Path(__file__).resolve().parents[2] / 'facts' / 'demo_photos'
    if photos_dir.is_dir() and list(photos_dir.glob('*.jpg')):
        yield
        return
    created_dir = not photos_dir.is_dir()
    photos_dir.mkdir(parents=True, exist_ok=True)
    seed = photos_dir / 'test-seed.jpg'
    Image.new('RGB', (64, 48), (64, 72, 80)).save(seed, 'JPEG')
    try:
        yield
    finally:
        seed.unlink(missing_ok=True)
        if created_dir and photos_dir.is_dir():
            try:
                photos_dir.rmdir()
            except OSError:
                pass


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
        connection.execute(text('TRUNCATE fact_variants, fact_products, memory_items, campaign_days, campaigns, agents, runs, memory, calendar_slots, media_attachments, media_assets, viral_generations, viral_generation_credits, approvals, audit, auth_sessions, auth_live_verifications, sam_calls, social_connections, publish_executions, publish_executor_settings, workspace_api_keys, owner_templates, engagement_items, image_characters, image_generations RESTART IDENTITY CASCADE'))
        connection.execute(text("UPDATE sam_budget SET remaining_images=0 WHERE id='global'"))
    with TestClient(app, base_url='https://testserver') as client:
        yield client
    app.dependency_overrides.clear()
