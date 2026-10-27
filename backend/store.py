"""One SQLAlchemy Postgres layer; migrations run through Alembic only."""
import os
from functools import lru_cache
from sqlalchemy import create_engine, text
from launchcrew import agents
from backend.adapter import ROOT


@lru_cache
def engine():
    url = os.environ['DATABASE_URL']
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    if not url.startswith('postgresql+psycopg://'):
        raise ValueError('Postgres required')
    return create_engine(url, pool_pre_ping=True)


def connect():
    return engine().begin()


def initialize():
    # No implicit DDL: alembic upgrade head must precede API startup.
    with connect() as db:
        for profile in agents.list_agents(ROOT / 'agents'):
            import json
            db.execute(text('INSERT INTO agents(name,profile) VALUES (:name,CAST(:profile AS jsonb)) ON CONFLICT DO NOTHING'),
                       {'name': profile['name'].lower(), 'profile': json.dumps(profile)})


def audit(db, run_id, action, actor='demo_placeholder'):
    db.execute(text('INSERT INTO audit(run_id,action,actor) VALUES (:run_id,:action,:actor)'),
               {'run_id': run_id, 'action': action, 'actor': actor})
