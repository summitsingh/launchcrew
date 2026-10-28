"""One SQLAlchemy Postgres layer; migrations run through Alembic only."""
import os
from functools import lru_cache
from sqlalchemy import create_engine, text
from launchcrew import agents
from backend.adapter import ROOT


def _is_local_url(url):
    lowered = url.lower()
    return 'localhost' in lowered or '127.0.0.1' in lowered or '@/' in lowered


def _require_verified_db_tls(url):
    # Deployment database TLS, fail-closed, never weakened.
    # For any non-local Postgres URL, the URL must carry
    # sslmode=verify-full, which verifies both the certificate chain
    # and the hostname. sslmode=require, prefer, or disable are rejected,
    # because require does not verify the hostname, and prefer and
    # disable do not verify the certificate at all.
    # Local URLs, localhost or 127.0.0.1, are exempt, for local
    # development and for isolated test clusters only, and must never
    # be used for a deployment. No certificate value, password, or
    # secret is logged here, only the requirement that failed.
    if _is_local_url(url):
        return
    if 'sslmode=verify-full' not in url.lower():
        raise ValueError('Non-local DATABASE_URL must use sslmode=verify-full')
    if 'sslmode=disable' in url.lower() or 'sslmode=prefer' in url.lower():
        raise ValueError('Non-local DATABASE_URL must not use sslmode=disable or prefer')


@lru_cache
def engine():
    url = os.environ['DATABASE_URL']
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    if not url.startswith('postgresql+psycopg://'):
        raise ValueError('Postgres required')
    _require_verified_db_tls(url)
    connect_args = {}
    ssl_rootcert = os.environ.get('DATABASE_SSL_ROOTCERT')
    if ssl_rootcert:
        connect_args['sslrootcert'] = ssl_rootcert
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


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
