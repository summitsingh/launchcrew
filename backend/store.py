"""One SQLAlchemy Postgres layer; migrations run through Alembic only."""
import os
import pathlib
from functools import lru_cache
from sqlalchemy import create_engine, text
from launchcrew import agents
from backend.adapter import ROOT


def _is_local_host(url):
    lowered = url.lower()
    return 'localhost' in lowered or '127.0.0.1' in lowered or '@db:' in lowered or '@db/' in lowered


def _db_tls_mode():
    # Explicit production verification mode, fail-closed in deploy config.
    # Modes:
    # - "verify-full": enforce sslmode=verify-full and a real sslrootcert
    #   file, for any host, including localhost. Cloud config sets this.
    # - "local": allow plain Postgres only for local hosts, localhost,
    #   127.0.0.1, or the compose service hostname db. Local compose
    #   sets this explicitly. It is absent from cloud config, and it
    #   never allows a non-local host, so setting "local" in cloud
    #   config with an RDS host still fails.
    # - unset: allow local hosts only, require verify-full for any other
    #   host. This keeps existing local tests, which use 127.0.0.1 and
    #   do not set a mode, working, without weakening cloud config,
    #   because cloud config always sets "verify-full" explicitly.
    return os.environ.get('LAUNCHCREW_DB_TLS_MODE', '').strip().lower()


def _require_verified_db_tls(url):
    # Deployment database TLS, fail-closed, never weakened.
    # sslmode=verify-full verifies both certificate chain and hostname.
    # sslmode=require, prefer, or disable are rejected, because require
    # does not verify hostname, and prefer and disable do not verify
    # the certificate at all. No certificate value, password, or secret
    # is logged here, only the requirement that failed.
    mode = _db_tls_mode()
    if mode == 'local':
        if not _is_local_host(url):
            raise ValueError('LAUNCHCREW_DB_TLS_MODE=local allows only localhost, 127.0.0.1, or db hosts')
        return
    if mode == 'verify-full':
        if 'sslmode=verify-full' not in url.lower():
            raise ValueError('LAUNCHCREW_DB_TLS_MODE=verify-full requires sslmode=verify-full in DATABASE_URL')
        ssl_rootcert = os.environ.get('DATABASE_SSL_ROOTCERT')
        if not ssl_rootcert or not pathlib.Path(ssl_rootcert).is_file():
            raise ValueError('LAUNCHCREW_DB_TLS_MODE=verify-full requires DATABASE_SSL_ROOTCERT to point to an existing CA bundle file')
        return
    if mode not in ('',):
        raise ValueError('LAUNCHCREW_DB_TLS_MODE must be verify-full, local, or unset')
    if _is_local_host(url):
        return
    if 'sslmode=verify-full' not in url.lower():
        raise ValueError('Non-local DATABASE_URL must use sslmode=verify-full')


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
