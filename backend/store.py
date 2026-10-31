"""One SQLAlchemy Postgres layer; migrations run through Alembic only."""
import os
import pathlib
from functools import lru_cache
from urllib.parse import parse_qsl, urlsplit
from sqlalchemy import create_engine, text
from launchcrew import agents
from backend.adapter import ROOT

_LOCAL_HOSTNAMES = frozenset({'localhost', 'db', '127.0.0.1', '::1'})

# Query keys that reroute the EFFECTIVE database destination or replace the
# pinned CA file, even when the URL authority looks local. Verified against
# the installed SQLAlchemy psycopg dialect (create_connect_args, no
# connection): a ?host= query value overrides the authority hostname, a
# ?hostaddr= value sets the network destination while the authority stays
# cosmetic, and ?service= / ?servicefile= hand routing to a service file.
# ?sslrootcert= would compete with the DATABASE_SSL_ROOTCERT file that
# engine() pins into connect_args, so its effective value would be
# driver-dependent. All five are refused outright instead of interpreted.
# Keys match case-insensitively after percent-decoding (parse_qsl decodes
# %XX escapes, so %68ost still reads as host); surrounding whitespace is
# ignored. Values are never logged.
_REJECTED_QUERY_KEYS = frozenset({'host', 'hostaddr', 'service', 'servicefile', 'sslrootcert'})

# Ambient libpq environment overrides that can reroute the connection without
# touching the URL authority at all. The dialect passes host explicitly from
# the URL, but hostaddr, service, and servicefile fall back to these
# variables when they are absent from the connect arguments, and an empty
# authority would fall back to PGHOST. Presence alone is refused; values are
# never read, never compared, and never logged.
_REJECTED_PG_ENV_VARS = ('PGHOST', 'PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE')


def _db_hostname(url):
    # Strict host parse: only the URL hostname counts, never userinfo,
    # path, or query substrings. Unparseable URLs fail closed (non-local).
    try:
        return (urlsplit(url).hostname or '').strip().lower()
    except Exception:
        return ''


def _is_local_host(url):
    return _db_hostname(url) in _LOCAL_HOSTNAMES


def _single_sslmode(url):
    # Strict TLS query parse: exactly one sslmode value is unambiguous.
    # Duplicate sslmode keys are rejected even when identical, because the
    # winning value is driver-dependent. Matching is case-insensitive on
    # both key and value (percent-decoded first by parse_qsl); surrounding
    # whitespace is ignored. Routing and CA-pin overrides are rejected
    # here too, so the authority hostname the caller sees is the destination
    # the driver uses. No parameter value is ever echoed.
    try:
        query = urlsplit(url).query
    except Exception:
        raise ValueError('DATABASE_URL is not a parseable URL')
    modes = []
    seen_sslrootcert = False
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered_key = key.strip().lower()
        if lowered_key == 'sslmode':
            modes.append(value.strip().lower())
        elif lowered_key == 'sslrootcert':
            if seen_sslrootcert:
                raise ValueError('DATABASE_URL has ambiguous duplicate sslrootcert parameters')
            seen_sslrootcert = True
        elif lowered_key in _REJECTED_QUERY_KEYS:
            raise ValueError(
                'DATABASE_URL must not carry a %s query parameter; routing comes only from the URL host' % lowered_key)
    if len(modes) > 1:
        raise ValueError('DATABASE_URL has ambiguous duplicate sslmode parameters')
    if seen_sslrootcert:
        raise ValueError('DATABASE_URL must not carry a sslrootcert query parameter; the CA bundle comes only from DATABASE_SSL_ROOTCERT')
    hostname = _db_hostname(url)
    if ',' in hostname:
        raise ValueError('DATABASE_URL must name a single database host')
    return modes[0] if modes else None


def _reject_ambient_pg_overrides():
    # Fail closed when ambient libpq routing variables are present. Only
    # presence is inspected; no value is read or reported.
    for name in _REJECTED_PG_ENV_VARS:
        if name in os.environ:
            raise ValueError(
                'Refused: ambient %s is set; database routing comes only from DATABASE_URL' % name)


def _require_ca_bundle():
    # CA check, used everywhere verify-full is required. The value is never
    # echoed: only the requirement that failed is reported.
    ssl_rootcert = os.environ.get('DATABASE_SSL_ROOTCERT')
    if not ssl_rootcert or not pathlib.Path(ssl_rootcert).is_file():
        raise ValueError('LAUNCHCREW_DB_TLS_MODE=verify-full requires DATABASE_SSL_ROOTCERT to point to an existing CA bundle file')


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
    _reject_ambient_pg_overrides()
    sslmode = _single_sslmode(url)
    if mode == 'local':
        if not _is_local_host(url):
            raise ValueError('LAUNCHCREW_DB_TLS_MODE=local allows only localhost, 127.0.0.1, or db hosts')
        return
    if mode == 'verify-full':
        if sslmode != 'verify-full':
            raise ValueError('LAUNCHCREW_DB_TLS_MODE=verify-full requires sslmode=verify-full in DATABASE_URL')
        _require_ca_bundle()
        return
    if mode not in ('',):
        raise ValueError('LAUNCHCREW_DB_TLS_MODE must be verify-full, local, or unset')
    if _is_local_host(url):
        return
    if sslmode != 'verify-full':
        raise ValueError('Non-local DATABASE_URL must use sslmode=verify-full')
    _require_ca_bundle()


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


DEMO_WORKSPACE = 'demo'


def workspace_for_actor(actor):
    if not actor or actor == 'demo_placeholder':
        return DEMO_WORKSPACE
    return str(actor)


def ensure_workspace(db, workspace_id, owner=None):
    db.execute(text('INSERT INTO workspaces(id, owner) VALUES (:id, :owner) ON CONFLICT DO NOTHING'),
               {'id': workspace_id, 'owner': owner or workspace_id})


def ensure_default_profiles(db, workspace_id):
    import json
    for profile in agents.list_agents(ROOT / 'agents'):
        db.execute(text('INSERT INTO agents(workspace_id,name,profile) VALUES (:ws,:name,CAST(:profile AS jsonb)) ON CONFLICT DO NOTHING'),
                   {'ws': workspace_id, 'name': profile['name'].lower(), 'profile': json.dumps(profile)})
    # Functional crew presets (Support, Designer, Analyst, Research) seed
    # alongside built-ins so they are selectable for any stage and execute
    # on the existing facts, check, and approval spine. Each preset carries
    # its own prompts and one distinct enforced Checker policy.
    presets_dir = ROOT / 'agent_presets'
    if presets_dir.is_dir():
        for profile in agents.list_agents(presets_dir):
            db.execute(text('INSERT INTO agents(workspace_id,name,profile) VALUES (:ws,:name,CAST(:profile AS jsonb)) ON CONFLICT DO NOTHING'),
                       {'ws': workspace_id, 'name': profile['name'].lower(), 'profile': json.dumps(profile)})


def ensure_workspace_seeded(db, actor):
    workspace_id = workspace_for_actor(actor)
    owner = 'demo' if workspace_id == DEMO_WORKSPACE else str(actor)
    ensure_workspace(db, workspace_id, owner)
    ensure_default_profiles(db, workspace_id)
    return workspace_id


def initialize():
    # No implicit DDL: alembic upgrade head must precede API startup.
    with connect() as db:
        ensure_workspace(db, DEMO_WORKSPACE, 'demo')
        ensure_default_profiles(db, DEMO_WORKSPACE)


def audit(db, run_id, action, actor='demo_placeholder', workspace_id=None):
    resolved = workspace_id or None
    if resolved is None:
        if run_id:
            row = db.execute(text('SELECT workspace_id FROM runs WHERE id=:id'), {'id': run_id}).fetchone()
            resolved = row[0] if row else workspace_for_actor(actor)
        else:
            resolved = workspace_for_actor(actor)
    ensure_workspace(db, resolved, 'demo' if resolved == DEMO_WORKSPACE else str(actor))
    db.execute(text('INSERT INTO audit(run_id,action,actor,workspace_id) VALUES (:run_id,:action,:actor,:ws)'),
               {'run_id': run_id, 'action': action, 'actor': actor, 'ws': resolved})
