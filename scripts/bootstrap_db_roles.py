#!/usr/bin/env python3
"""LaunchCrew demo database role binding job, memory only, no secret logging.

Runs ONLY inside the private ECS bootstrap one-off task defined in
deploy/aws/fargate.yaml (BootstrapTaskDefinition, image built from
containers/bootstrap-db.Containerfile). ECS injects secret VALUES into this
process memory via task-definition Secrets entries. Nothing here reads
operator files, process argument vectors, or shared state, and nothing here
logs a password, connection URL, or raw database error text.

Modes, selected by argv flag only (no secret ever appears in argv):
  --bind    create exact owned roles if missing, bind each role password to
            the matching injected secret URL password, then apply the
            privilege split from deploy/aws/db-roles.sql (runtime DML-only,
            migration DDL, default privileges for migration-created tables).
            Idempotent: safe to rerun; reports each completed phase.
  --verify  read-only proof with the runtime URL only: SELECT works, the
            alembic schema version row exists, and runtime CREATE/ALTER/DROP
            each fail. Never connects as master or migration here.

TLS guard: LAUNCHCREW_DB_TLS_MODE must be verify-full and
DATABASE_SSL_ROOTCERT must be an existing CA bundle file, otherwise the job
fails closed before any connection. Master connections use sslmode
verify-full with that bundle. Runtime verify mode additionally requires the
runtime URL itself to carry sslmode=verify-full.

Stdlib plus psycopg only. No backend framework import.
"""

import os
import re
import sys
import urllib.parse

IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
PHASES_BIND = ("password-binding", "runtime-grants", "migration-grants",
               "default-privileges")
ROOTCERT_ENV = "DATABASE_SSL_ROOTCERT"

_known_secrets: list = []


def _redact(text):
    out = str(text)
    for secret in _known_secrets:
        if secret:
            out = out.replace(secret, "***")
    return out


def _fail(phase, detail=""):
    # Never emit raw exception text: drivers may echo connection fields.
    # Only the phase name and a redacted short detail leave this process.
    suffix = " " + _redact(detail) if detail else ""
    print("bootstrap-db-roles: FAIL: %s%s" % (phase, suffix), flush=True)
    return 1


def _ok(phase):
    print("bootstrap-db-roles: %s ok" % phase, flush=True)


def _env(name, required=True):
    value = os.environ.get(name, "")
    if required and not value:
        raise ValueError("missing %s" % name)
    return value


def _check_ident(label, value):
    if not IDENT.match(value or ""):
        raise ValueError("invalid %s" % label)
    return value


def _tls_guard():
    if os.environ.get("LAUNCHCREW_DB_TLS_MODE", "") != "verify-full":
        raise ValueError("LAUNCHCREW_DB_TLS_MODE must be verify-full")
    bundle = os.environ.get(ROOTCERT_ENV, "")
    if not bundle or not os.path.isfile(bundle):
        raise ValueError("DATABASE_SSL_ROOTCERT bundle missing")
    return bundle


def _url_password(label, url):
    # Password lives in process memory only; callers must never print url.
    parts = urllib.parse.urlparse(url)
    if not parts.password:
        raise ValueError("%s has no password" % label)
    if "sslmode=verify-full" not in (parts.query or ""):
        raise ValueError("%s requires sslmode=verify-full" % label)
    return parts.password


def _quote_ident(name):
    _check_ident("identifier", name)
    return '"' + name.replace('"', '""') + '"'


def _role_exists(cur, name):
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    return cur.fetchone() is not None


def do_bind():
    import psycopg

    bundle = _tls_guard()
    host = _env("DB_HOST")
    port = os.environ.get("DB_PORT", "5432")
    dbname = _env("DB_NAME")
    master_user = _env("DB_MASTER_USER")
    master_password = _env("MASTER_DB_PASSWORD")
    runtime_url = _env("RUNTIME_DB_URL")
    migration_url = _env("MIGRATION_DB_URL")
    runtime_user = _check_ident("RUNTIME_USER", _env("RUNTIME_USER"))
    migration_user = _check_ident("MIGRATION_USER", _env("MIGRATION_USER"))
    schema = _check_ident("APP_SCHEMA", os.environ.get("APP_SCHEMA", "public"))
    for secret in (master_password, runtime_url, migration_url):
        _known_secrets.append(secret)
    runtime_password = _url_password("RUNTIME_DB_URL", runtime_url)
    migration_password = _url_password("MIGRATION_DB_URL", migration_url)
    _known_secrets.extend((runtime_password, migration_password))
    if not host or " " in host:
        raise ValueError("invalid DB_HOST")

    done = []
    try:
        conn = psycopg.connect(host=host, port=port, dbname=dbname,
                               user=master_user, password=master_password,
                               sslmode="verify-full", sslrootcert=bundle)
    except Exception:
        return _fail("connect")
    try:
        conn.autocommit = True
        cur = conn.cursor()
        qi_runtime = _quote_ident(runtime_user)
        qi_migration = _quote_ident(migration_user)
        qi_schema = _quote_ident(schema)
        try:
            # Phase 1: exact owned roles exist, passwords bound in memory.
            for user, password in ((runtime_user, runtime_password),
                                   (migration_user, migration_password)):
                if not _role_exists(cur, user):
                    cur.execute("CREATE ROLE %s WITH LOGIN"
                                % _quote_ident(user))
                cur.execute("ALTER ROLE %s WITH PASSWORD %%s"
                            % _quote_ident(user), (password,))
            done.append("password-binding")
            _ok("password-binding")
        except Exception:
            conn.rollback() if hasattr(conn, "rollback") else None
            return _fail("password-binding",
                         "completed: %s" % ",".join(done))
        # Phase 2: runtime DML-only split, mirrors db-roles.sql exactly.
        try:
            cur.execute("REVOKE CREATE ON SCHEMA %s FROM PUBLIC" % qi_schema)
            cur.execute("GRANT USAGE ON SCHEMA %s TO %s"
                        % (qi_schema, qi_runtime))
            cur.execute("REVOKE CREATE ON SCHEMA %s FROM %s"
                        % (qi_schema, qi_runtime))
            cur.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %s "
                        "FROM %s" % (qi_schema, qi_runtime))
            cur.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                        "IN SCHEMA %s TO %s" % (qi_schema, qi_runtime))
            cur.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA %s "
                        "FROM %s" % (qi_schema, qi_runtime))
            cur.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %s "
                        "TO %s" % (qi_schema, qi_runtime))
            done.append("runtime-grants")
            _ok("runtime-grants")
        except Exception:
            return _fail("runtime-grants",
                         "completed: %s" % ",".join(done))
        # Phase 3: migration DDL split, the only schema change path.
        try:
            cur.execute("GRANT USAGE, CREATE ON SCHEMA %s TO %s"
                        % (qi_schema, qi_migration))
            cur.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA %s "
                        "TO %s" % (qi_schema, qi_migration))
            cur.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA %s "
                        "TO %s" % (qi_schema, qi_migration))
            done.append("migration-grants")
            _ok("migration-grants")
        except Exception:
            return _fail("migration-grants",
                         "completed: %s" % ",".join(done))
        # Phase 4: later migration-created tables keep the runtime split.
        try:
            cur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE %s IN SCHEMA %s "
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %s"
                        % (qi_migration, qi_schema, qi_runtime))
            cur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE %s IN SCHEMA %s "
                        "GRANT USAGE, SELECT ON SEQUENCES TO %s"
                        % (qi_migration, qi_schema, qi_runtime))
            done.append("default-privileges")
            _ok("default-privileges")
        except Exception:
            return _fail("default-privileges",
                         "completed: %s" % ",".join(done))
    finally:
        try:
            conn.close()
        except Exception:
            pass
    print("bootstrap-db-roles: BIND COMPLETE phases=%s" % ",".join(done),
          flush=True)
    return 0


def do_verify():
    import psycopg

    bundle = _tls_guard()
    runtime_url = _env("RUNTIME_DB_URL")
    _known_secrets.append(runtime_url)
    _url_password("RUNTIME_DB_URL", runtime_url)  # enforces verify-full
    try:
        conn = psycopg.connect(runtime_url, sslrootcert=bundle)
    except Exception:
        return _fail("verify-connect")
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1")
            row = cur.fetchone()
            if not row or row[0] != 1:
                return _fail("verify-read")
            _ok("verify-read")
        except Exception:
            return _fail("verify-read")
        try:
            cur.execute("SELECT version_num FROM alembic_version")
            version = cur.fetchone()
            if not version or not version[0]:
                return _fail("verify-schema")
            print("bootstrap-db-roles: verify-schema ok revision=%s"
                  % _redact(version[0]), flush=True)
        except Exception:
            return _fail("verify-schema")
        conn.rollback()
        for stmt, label in (
                ("CREATE TABLE _lc_verify_nope (id integer primary key)",
                 "verify-runtime-no-create"),
                ("ALTER TABLE alembic_version ADD COLUMN _lc_nope integer",
                 "verify-runtime-no-alter"),
                ("DROP TABLE alembic_version",
                 "verify-runtime-no-drop")):
            try:
                cur.execute(stmt)
                conn.rollback()
                return _fail(label)
            except Exception:
                conn.rollback()
                _ok(label)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    print("bootstrap-db-roles: VERIFY COMPLETE runtime read-only, "
          "schema present, DDL refused", flush=True)
    return 0


def main(argv):
    if len(argv) != 2 or argv[1] not in ("--bind", "--verify"):
        print("usage: bootstrap_db_roles.py [--bind|--verify]", flush=True)
        return 2
    try:
        if argv[1] == "--bind":
            return do_bind()
        return do_verify()
    except ValueError as exc:
        return _fail("config", str(exc))
    except Exception:
        return _fail("internal")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
