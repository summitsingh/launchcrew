#!/usr/bin/env python3
"""LaunchCrew demo database role binding job, memory only, no secret logging.

Runs ONLY inside the private ECS bootstrap one-off task defined in
deploy/aws/fargate.yaml (BootstrapTaskDefinition, image built from
containers/bootstrap-db.Containerfile). ECS injects secret VALUES into this
process memory via task definition Secrets entries. Nothing here reads
operator files, process argument vectors, or shared state, and nothing here
logs a password, connection URL, or raw database error text. Stdout
redaction only covers this process: server-side statement logging is outside
this job, so operators keep it off for secret-bearing statements.

Modes, selected by argv flag only (no secret ever appears in argv):
  --bind    ensure the exact owned database exists first via the built-in
            postgres maintenance database as the exact master (same host,
            port, password, pinned verify-full TLS), creating exactly the
            owned database if absent with a safe identifier and an
            idempotent existence precondition, refusing a foreign existing
            owner or a wrong identity and never touching other databases,
            then create exact owned roles if missing (stamped with an
            ownership comment), bind each role password to the matching
            injected secret URL password, then apply the privilege split
            in two connections. The RDS master is NOSUPERUSER CREATEROLE,
            not a true postgres superuser, so it creates, stamps, and
            password binds roles plus schema ACLs only. A direct migration
            connection then applies runtime DML-only object grants plus
            its own default privileges on migration-owned objects.
            Existing roles are rebound only with the ownership stamp and
            no superuser, bypassrls, create, replication, or membership
            takeover risk. The only permitted membership is the exact
            native Postgres 16 creator administration row. Idempotent:
            safe to rerun; reports each completed phase.
  --verify  read-only proof with the runtime URL only at head 008: SELECT
            works, the alembic schema version equals 008, the connected
            identity equals the runtime role, a rolled-back write proves DML
            without committing, runtime CREATE/ALTER/DROP each fail with
            SQLSTATE 42501, the global model budget reads zero, runtime
            direct model ledger and budget DML each fail with 42501, exact
            reserve and finalize EXECUTE grants allow only the runtime role
            with no PUBLIC and no default future EXECUTE. The reserve,
            finalize, and trigger functions plus both model tables must be
            owned exactly by the expected migration role name carried in the
            nonsecret MIGRATION_USER metadata, failing closed on wrong owner.
            The run_outcomes table must exist at 008, owned by the migration
            role, with its workspace isolation and self-report CHECK and FK
            constraints plus no workspace_id DEFAULT, and the runtime role
            must hold SELECT, INSERT, UPDATE, DELETE with no TRUNCATE,
            REFERENCES, or TRIGGER. Never connects as master or migration
            here, and never commits. No provider key is read or injected here.
  --verify-role-state
            read-only current-state equivalence proof with both runtime and
            migration URLs, no master secret, zero writes including zero
            rolled-back writes, never commits. Proves both role password
            authentications via successful connections, both role flags and
            exact native memberships, both ownership markers, expected schema
            and every relation and function ownership by the migration role,
            schema and table and sequence grants plus default grants for
            future objects, model table and function ownership and EXECUTE
            scope with no PUBLIC, plus the actual alembic head and critical
            schema properties including voice_profile at 007 and 008 and the
            run_outcomes table at 008 only. Head 008 returns 0, head 007
            ready for the single 008 migration returns 10, any other head or
            any partial or inconsistent state returns 1 and requires a
            separately reviewed repair. Never logs a password, URL, or
            statement with secret material.

TLS guard: LAUNCHCREW_DB_TLS_MODE must be verify-full and
DATABASE_SSL_ROOTCERT must be an existing CA bundle file, otherwise the job
fails closed before any connection. Connections use sslmode verify-full with
that bundle. URL parsing matches the effective-host policy of
backend/store.py: the URL authority alone decides the destination, so query
reroutes (host, hostaddr, service, servicefile, sslrootcert) and ambient
libpq routing variables (PGHOST, PGHOSTADDR, PGSERVICE, PGSERVICEFILE) are
refused instead of interpreted.

Stdlib plus psycopg only. No backend framework import.
"""

import os
import re
import sys
import urllib.parse

IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
DBNAME = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
MANAGED_COMMENT = "launchcrew-managed"
NATIVE_BOOTSTRAP_OID = 10
PHASES_BIND = ("db-ensure", "password-binding", "schema-acls",
               "runtime-grants", "default-privileges")
ROOTCERT_ENV = "DATABASE_SSL_ROOTCERT"
EXPECTED_HEAD = "008"
PREDECESSOR_HEAD = "007"
MODEL_TABLES = ("model_budget", "model_calls")
OUTCOME_TABLE = "run_outcomes"
OUTCOME_CONSTRAINTS = (
    "run_outcomes_workspace_fkey",
    "run_outcomes_run_workspace_fkey",
    "run_outcomes_revision_non_negative",
    "run_outcomes_channel",
    "run_outcomes_likes_bounds",
    "run_outcomes_comments_bounds",
    "run_outcomes_clicks_bounds",
    "run_outcomes_sales_bounds",
    "run_outcomes_note_length",
    "run_outcomes_note_no_control",
    "run_outcomes_provenance",
    "run_outcomes_actor_signed_in",
)
MODEL_RESERVE_FUNC = "model_reserve_call"
MODEL_RESERVE_SIG = "(TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, INTEGER)"
MODEL_FINALIZE_FUNC = "model_finalize_call"
MODEL_FINALIZE_SIG = "(TEXT, TEXT, TEXT, INTEGER, INTEGER, INTEGER)"
MODEL_TRIGGER_FUNC = "model_no_direct"
MODEL_TRIGGER_SIG = "()"
VERIFY_PROBE = "_lc_verify_probe"
MAINTENANCE_DB = "postgres"
_SQLSTATE_RE = re.compile(r"^[0-9A-Z]{5}$")
_ERROR_CLASS_RE = re.compile(r"^[A-Za-z_]{1,64}$")
# Query keys that reroute the effective destination or replace the pinned CA
# file even when the URL authority looks right. Matched case-insensitively
# after percent-decoding, exactly like backend/store.py.
_REJECTED_QUERY_KEYS = frozenset({'host', 'hostaddr', 'service',
                                  'servicefile', 'sslrootcert'})
# Ambient libpq routing overrides. Presence alone is refused; values are
# never read or logged.
_REJECTED_PG_ENV_VARS = ('PGHOST', 'PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE')

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


def _check_host(label, value):
    cleaned = (value or "").strip().lower()
    if not cleaned or "," in cleaned or " " in cleaned:
        raise ValueError("invalid %s" % label)
    if not HOST.match(cleaned):
        raise ValueError("invalid %s" % label)
    return cleaned


def _check_dbname(label, value):
    if not DBNAME.match(value or ""):
        raise ValueError("invalid %s" % label)
    return value


def _check_port(value):
    try:
        port = int((value or "5432").strip())
    except ValueError:
        raise ValueError("invalid DB_PORT")
    if port < 1 or port > 65535:
        raise ValueError("invalid DB_PORT")
    return port


def _tls_guard():
    if os.environ.get("LAUNCHCREW_DB_TLS_MODE", "") != "verify-full":
        raise ValueError("LAUNCHCREW_DB_TLS_MODE must be verify-full")
    bundle = os.environ.get(ROOTCERT_ENV, "")
    if not bundle or not os.path.isfile(bundle):
        raise ValueError("DATABASE_SSL_ROOTCERT bundle missing")
    return bundle


def _reject_ambient_pg_overrides():
    for name in _REJECTED_PG_ENV_VARS:
        if name in os.environ:
            raise ValueError(
                "Refused: ambient %s is set; routing comes only from the URL" % name)


def _parse_db_url(label, url, expected_user, expected_host, expected_db):
    """Strict effective-destination parse of a database URL.

    Returns the connection fields with the percent-decoded password. The
    authority alone decides the destination: scheme must be postgresql,
    hostname, database name, and username must equal the expected owned
    target exactly, and exactly one sslmode=verify-full must be present with
    no rerouting query keys. Raises ValueError on anything else.
    """
    try:
        parts = urllib.parse.urlparse(url)
    except Exception:
        raise ValueError("%s is not a parseable URL" % label)
    if parts.scheme != "postgresql":
        raise ValueError("%s must use the postgresql scheme" % label)
    host = (parts.hostname or "").strip().lower()
    if not host or "," in host:
        raise ValueError("%s must name a single database host" % label)
    if host != expected_host:
        raise ValueError("%s host does not match the owned target" % label)
    try:
        port = parts.port or 5432
    except ValueError:
        raise ValueError("%s has an invalid port" % label)
    if port < 1 or port > 65535:
        raise ValueError("%s has an invalid port" % label)
    # Userinfo is parsed from the raw netloc so percent-encoding never
    # confuses the split: only a literal "@" ends the userinfo, and only the
    # first literal ":" separates the username from the password.
    netloc = parts.netloc
    if "@" not in netloc:
        raise ValueError("%s has no username" % label)
    userinfo = netloc.rsplit("@", 1)[0]
    if ":" not in userinfo:
        raise ValueError("%s has no password" % label)
    raw_user, raw_password = userinfo.split(":", 1)
    username = urllib.parse.unquote(raw_user)
    password = urllib.parse.unquote(raw_password)
    if username != expected_user:
        raise ValueError("%s username does not match the owned role" % label)
    if not password:
        raise ValueError("%s has no password" % label)
    dbname = (parts.path or "").lstrip("/")
    if not dbname or "/" in dbname:
        raise ValueError("%s must name a single database" % label)
    if dbname != expected_db:
        raise ValueError("%s database does not match the owned target" % label)
    try:
        items = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    except Exception:
        raise ValueError("%s has an unreadable query" % label)
    modes = []
    for key, value in items:
        lowered = key.strip().lower()
        if lowered == "sslmode":
            modes.append(value.strip().lower())
        elif lowered in _REJECTED_QUERY_KEYS:
            raise ValueError(
                "%s must not carry a %s query parameter; routing comes only from the URL host"
                % (label, lowered))
    if len(modes) != 1 or modes[0] != "verify-full":
        raise ValueError("%s requires exactly sslmode=verify-full" % label)
    return {"host": host, "port": port, "dbname": dbname,
            "user": username, "password": password}


def _quote_ident(name):
    _check_ident("identifier", name)
    return '"' + name.replace('"', '""') + '"'


def _quote_dbname(name):
    _check_dbname("database", name)
    return '"' + name.replace('"', '""') + '"'


def _error_detail(exc, fallback):
    """Safe bounded classification of a database exception.

    Returns SQLSTATE plus exception class only, never raw exception text,
    passwords, URLs, or connection fields. Both parts are allowlisted, so
    driver messages that echo connection fields cannot leak through logs.
    """
    parts = []
    sqlstate = getattr(exc, "sqlstate", None)
    if isinstance(sqlstate, str) and _SQLSTATE_RE.match(sqlstate):
        parts.append("sqlstate=%s" % sqlstate)
    cls = type(exc).__name__
    if isinstance(cls, str) and _ERROR_CLASS_RE.match(cls):
        parts.append("class=%s" % cls)
    if not parts:
        return fallback
    return " ".join(parts)


def _role_row(cur, name):
    cur.execute(
        "SELECT rolname, rolsuper, rolcanlogin, rolcreaterole, rolcreatedb, "
        "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
        (name,))
    return cur.fetchone()


def _role_comment(cur, name):
    cur.execute(
        "SELECT d.description FROM pg_shdescription d "
        "JOIN pg_roles r ON r.oid = d.objoid WHERE r.rolname = %s",
        (name,))
    row = cur.fetchone()
    return row[0] if row else None


def _role_memberships(cur, name):
    # Every membership row touching the managed role in either direction,
    # with grantor name plus grantor OID plus superuser flag plus all
    # three options. Postgres carries admin, inherit, and set options;
    # the automatic creator row is ADMIN TRUE, INHERIT FALSE, SET FALSE
    # with the native bootstrap superuser as grantor. The grantor is the
    # bootstrap OID 10 (postgres in community, rdsadmin on RDS), never
    # the creator and never a hardcoded name.
    cur.execute(
        "SELECT target.rolname, member.rolname, grantor.rolname, "
        "grantor.rolsuper, m.admin_option, m.inherit_option, "
        "m.set_option, m.grantor FROM pg_auth_members m "
        "JOIN pg_roles target ON target.oid = m.roleid "
        "JOIN pg_roles member ON member.oid = m.member "
        "JOIN pg_roles grantor ON grantor.oid = m.grantor "
        "WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = %s) "
        "OR m.member = (SELECT oid FROM pg_roles WHERE rolname = %s) "
        "ORDER BY target.rolname, member.rolname",
        (name, name))
    return cur.fetchall()


def _managed_verdict(cur, name, row, master_user):
    """Refuse existing roles this job does not own. Returns None when safe."""
    if len(row) > 1 and row[1]:
        return "existing superuser role refused: %s" % name
    if len(row) > 5:
        if row[3]:
            return "existing role with CREATEROLE refused: %s" % name
        if row[4]:
            return "existing role with CREATEDB refused: %s" % name
        if row[5]:
            return "existing role with REPLICATION refused: %s" % name
    if len(row) > 6 and row[6]:
        return "existing role with BYPASSRLS refused: %s" % name
    if _role_comment(cur, name) != MANAGED_COMMENT:
        return "existing role without ownership marker refused: %s" % name
    memberships = _role_memberships(cur, name)
    if not memberships:
        return None
    if len(memberships) > 1:
        return ("existing role with memberships refused: %s "
                "has %d membership rows" % (name, len(memberships)))
    first = memberships[0]
    if len(first) != 8:
        return ("existing role with memberships refused: %s "
                "has an unreadable grantor row" % name)
    (target, member, grantor, grantor_super, admin, inherit_opt,
     set_opt, grantor_oid) = first
    if target != name or member != master_user:
        return ("existing role with memberships refused: %s "
                "is not the exact creator row" % name)
    if not admin or inherit_opt or set_opt:
        return ("existing role with memberships refused: %s "
                "has changed membership options" % name)
    try:
        grantor_id = int(grantor_oid)
    except Exception:
        grantor_id = None
    if (grantor_id != NATIVE_BOOTSTRAP_OID or not grantor_super
            or grantor == master_user or grantor == name):
        return ("existing role with memberships refused: %s "
                "has a foreign grantor" % name)
    return None


def _connection_identity(cur):
    cur.execute("SELECT session_user, current_user")
    row = cur.fetchone()
    if not row or len(row) < 2:
        raise ValueError("identity lookup failed")
    return {"session_user": row[0], "current_user": row[1]}


def _schema_object_owners(cur, schema):
    # Every relation kind affected by the runtime grant split in the
    # isolated app schema with its owner name. GRANT ON ALL TABLES
    # covers ordinary tables, partitioned tables, views, materialized
    # views, and foreign tables; GRANT ON ALL SEQUENCES covers
    # sequences. All must be migration owned before any grant.
    cur.execute(
        "SELECT c.relname, c.relkind, owner.rolname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_roles owner ON owner.oid = c.relowner "
        "WHERE n.nspname = %s "
        "AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') "
        "ORDER BY c.relname",
        (schema,))
    return cur.fetchall()


def _function_owners(cur, schema):
    # Every function in the isolated app schema with its owner name.
    # All must be migration owned before any EXECUTE grant. Empty before
    # migration 005, which is safe to skip.
    cur.execute(
        "SELECT p.proname, owner.rolname FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_roles owner ON owner.oid = p.proowner "
        "WHERE n.nspname = %s ORDER BY p.proname",
        (schema,))
    return cur.fetchall()


def _schema_owner(cur, schema):
    cur.execute(
        "SELECT owner.rolname FROM pg_namespace n "
        "JOIN pg_roles owner ON owner.oid = n.nspowner "
        "WHERE n.nspname = %s",
        (schema,))
    row = cur.fetchone()
    return row[0] if row else None


def _database_owner(cur, dbname):
    cur.execute(
        "SELECT owner.rolname FROM pg_database d "
        "JOIN pg_roles owner ON owner.oid = d.datdba "
        "WHERE d.datname = %s",
        (dbname,))
    row = cur.fetchone()
    return row[0] if row else None


def _schema_preflight(cur, schema, master_user, dbname):
    # Returns None when the isolated schema is safe to mutate.
    # Allowed: explicit master owned schema, or native
    # pg_database_owner schema only when the actual current database
    # owner is the master. Anything else is refused with no takeover.
    owner = _schema_owner(cur, schema)
    if not owner:
        return "schema %s is missing" % schema
    if owner == master_user:
        return None
    if owner == "pg_database_owner":
        db_owner = _database_owner(cur, dbname)
        if db_owner == master_user:
            return None
        return "schema %s is not owned by the master" % schema
    return "schema %s is not owned by the master" % schema


def do_bind():
    import psycopg

    bundle = _tls_guard()
    _reject_ambient_pg_overrides()
    host = _check_host("DB_HOST", _env("DB_HOST"))
    port = _check_port(os.environ.get("DB_PORT", "5432"))
    dbname = _check_dbname("DB_NAME", _env("DB_NAME"))
    master_user = _check_ident("DB_MASTER_USER", _env("DB_MASTER_USER"))
    master_password = _env("MASTER_DB_PASSWORD")
    runtime_url = _env("RUNTIME_DB_URL")
    migration_url = _env("MIGRATION_DB_URL")
    runtime_user = _check_ident("RUNTIME_USER", _env("RUNTIME_USER"))
    migration_user = _check_ident("MIGRATION_USER", _env("MIGRATION_USER"))
    schema = _check_ident("APP_SCHEMA", os.environ.get("APP_SCHEMA", "public"))
    if runtime_user == migration_user:
        raise ValueError("RUNTIME_USER and MIGRATION_USER must be distinct roles")
    if runtime_user == master_user or migration_user == master_user:
        raise ValueError("runtime and migration roles must differ from the master user")
    runtime = _parse_db_url("RUNTIME_DB_URL", runtime_url,
                            runtime_user, host, dbname)
    migration = _parse_db_url("MIGRATION_DB_URL", migration_url,
                              migration_user, host, dbname)
    if runtime["port"] != port:
        raise ValueError("RUNTIME_DB_URL port does not match DB_PORT")
    if migration["port"] != port:
        raise ValueError("MIGRATION_DB_URL port does not match DB_PORT")
    for secret in (master_password, runtime_url, migration_url,
                   runtime["password"], migration["password"]):
        _known_secrets.append(secret)
    if not host or " " in host:
        raise ValueError("invalid DB_HOST")

    done = []
    qi_runtime = _quote_ident(runtime_user)
    qi_migration = _quote_ident(migration_user)
    qi_schema = _quote_ident(schema)
    qi_dbname = _quote_dbname(dbname)
    # Phase 0: ensure the exact owned database exists. Connect as the exact
    # master to the built-in postgres maintenance database with the same
    # host, port, password, and pinned verify-full TLS, then create exactly
    # the owned database if absent. The maintenance name is a constant,
    # never from the environment, and no other database is ever inspected
    # or mutated. CREATE DATABASE cannot run inside a transaction block,
    # so the read transaction is rolled back and autocommit is enabled for
    # the single CREATE. No retry on ambiguous failure; the host inspects
    # the journal and reruns only after review.
    try:
        maint_conn = psycopg.connect(host=host, port=port,
                                     dbname=MAINTENANCE_DB,
                                     user=master_user,
                                     password=master_password,
                                     sslmode="verify-full",
                                     sslrootcert=bundle)
    except Exception as exc:
        return _fail("connect", "maintenance %s"
                     % _error_detail(exc, "connection-failed"))
    try:
        maint_conn.autocommit = False
        mcur = maint_conn.cursor()
        try:
            maint_identity = _connection_identity(mcur)
        except Exception:
            try:
                maint_conn.rollback()
            except Exception:
                pass
            return _fail("connect",
                         "maintenance master identity lookup failed")
        if (maint_identity["session_user"] != master_user
                or maint_identity["current_user"] != master_user):
            try:
                maint_conn.rollback()
            except Exception:
                pass
            return _fail("connect",
                         "maintenance master identity mismatch")
        try:
            existing_owner = _database_owner(mcur, dbname)
        except Exception:
            try:
                maint_conn.rollback()
            except Exception:
                pass
            return _fail("db-safety", "catalog check failed")
        if existing_owner is not None:
            try:
                maint_conn.rollback()
            except Exception:
                pass
            if existing_owner != master_user:
                return _fail("db-safety",
                             "existing database with foreign owner refused")
        else:
            try:
                maint_conn.rollback()
            except Exception:
                pass
            try:
                maint_conn.autocommit = True
            except Exception:
                return _fail("db-create", "autocommit failed")
            create_exc = None
            try:
                mcur.execute("CREATE DATABASE %s" % qi_dbname)
            except Exception as exc:
                if getattr(exc, "sqlstate", None) != "42P04":
                    return _fail("db-create",
                                 _error_detail(exc, "create-failed"))
                create_exc = exc
            try:
                final_owner = _database_owner(mcur, dbname)
            except Exception:
                return _fail("db-safety", "catalog check failed")
            if final_owner is None:
                if create_exc is not None:
                    return _fail("db-create",
                                 _error_detail(create_exc, "create-failed"))
                return _fail("db-create", "database missing after create")
            if final_owner != master_user:
                return _fail("db-safety",
                             "existing database with foreign owner refused")
        done.append("db-ensure")
        _ok("db-ensure")
    finally:
        try:
            maint_conn.close()
        except Exception:
            pass
    try:
        conn = psycopg.connect(host=host, port=port, dbname=dbname,
                               user=master_user, password=master_password,
                               sslmode="verify-full", sslrootcert=bundle)
    except Exception as exc:
        return _fail("connect", _error_detail(exc, "connection-failed"))
    try:
        conn.autocommit = False
        cur = conn.cursor()
        # DDL statements cannot take server-side bound parameters, so the
        # password binds below use a client-side binding cursor: the password
        # is composed into a quoted literal in this process memory only,
        # never in argv, files, or logs, and travels to the server inside
        # the statement text over TLS. Server-side statement logging is
        # outside this job, so it stays off for secret-bearing statements.
        bind_cur = psycopg.ClientCursor(conn)
        try:
            identity = _connection_identity(cur)
        except Exception:
            conn.rollback()
            return _fail("connect", "master identity lookup failed")
        if (identity["session_user"] != master_user
                or identity["current_user"] != master_user):
            conn.rollback()
            return _fail("connect", "master identity mismatch")
        # Validate both managed roles before mutating either, so a bad
        # second role never leaves a half rebound first role behind.
        try:
            plans = []
            for user in (runtime_user, migration_user):
                row = _role_row(cur, user)
                if row is None:
                    plans.append(("create", user, None))
                else:
                    verdict = _managed_verdict(cur, user, row, master_user)
                    if verdict is not None:
                        conn.rollback()
                        return _fail("role-safety", verdict)
                    plans.append(("rebind", user, row))
        except ValueError as exc:
            conn.rollback()
            return _fail("role-safety", str(exc))
        except Exception:
            conn.rollback()
            return _fail("role-safety", "catalog check failed")
        try:
            schema_verdict = _schema_preflight(cur, schema, master_user,
                                               dbname)
        except Exception:
            conn.rollback()
            return _fail("schema-safety", "catalog check failed")
        if schema_verdict is not None:
            conn.rollback()
            return _fail("schema-safety", schema_verdict)
        try:
            master_inventory = _schema_object_owners(cur, schema)
            master_functions = _function_owners(cur, schema)
        except Exception:
            conn.rollback()
            return _fail("runtime-grants", "catalog check failed")
        for relname, _relkind, owner in master_inventory:
            if owner != migration_user:
                conn.rollback()
                return _fail("runtime-grants",
                             "unexpected owner %s on %s" % (owner,
                                                           relname))
        for proname, owner in master_functions:
            if owner != migration_user:
                conn.rollback()
                return _fail("runtime-grants",
                             "unexpected owner %s on %s" % (owner,
                                                           proname))
        try:
            # Phase 1: exact owned roles exist, passwords bound in memory.
            # One transaction for create plus marker plus password, so a
            # failure never leaves an unmarked role behind.
            passwords = {runtime_user: runtime["password"],
                         migration_user: migration["password"]}
            for action, user, row in plans:
                if action == "create":
                    cur.execute("CREATE ROLE %s WITH LOGIN"
                                % _quote_ident(user))
                    cur.execute("COMMENT ON ROLE %s IS '%s'"
                                % (_quote_ident(user), MANAGED_COMMENT))
                else:
                    if len(row) > 2 and not row[2]:
                        cur.execute("ALTER ROLE %s WITH LOGIN"
                                    % _quote_ident(user))
                bind_cur.execute("ALTER ROLE %s WITH PASSWORD %%s"
                                 % _quote_ident(user), (passwords[user],))
            conn.commit()
            done.append("password-binding")
            _ok("password-binding")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _fail("password-binding",
                         "completed: %s" % ",".join(done))
        # Phase 2: schema ACLs only. The NOSUPERUSER master keeps database
        # and schema ownership; object grants move to the migration
        # connection below because the master cannot grant on objects it
        # does not own and cannot set another role's default privileges.
        try:
            cur.execute("REVOKE CREATE ON SCHEMA %s FROM PUBLIC" % qi_schema)
            cur.execute("GRANT USAGE ON SCHEMA %s TO %s"
                        % (qi_schema, qi_runtime))
            cur.execute("REVOKE CREATE ON SCHEMA %s FROM %s"
                        % (qi_schema, qi_runtime))
            cur.execute("GRANT USAGE, CREATE ON SCHEMA %s TO %s"
                        % (qi_schema, qi_migration))
            conn.commit()
            done.append("schema-acls")
            _ok("schema-acls")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _fail("schema-acls",
                         "completed: %s" % ",".join(done))
    finally:
        try:
            conn.close()
        except Exception:
            pass
    # Migration connection over the validated private URL fields in RAM,
    # never the raw URL string, with the same pinned TLS bundle.
    try:
        mconn = psycopg.connect(host=migration["host"], port=migration["port"],
                                dbname=migration["dbname"],
                                user=migration["user"],
                                password=migration["password"],
                                sslmode="verify-full", sslrootcert=bundle)
    except Exception as exc:
        return _fail("migration-connect", "%s completed: %s"
                     % (_error_detail(exc, "connection-failed"),
                        ",".join(done)))
    try:
        mconn.autocommit = False
        mcur = mconn.cursor()
        try:
            identity = _connection_identity(mcur)
        except Exception:
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("migration-identity",
                         "completed: %s" % ",".join(done))
        if (identity["session_user"] != migration_user
                or identity["current_user"] != migration_user):
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("migration-identity",
                         "completed: %s" % ",".join(done))
        # Phase 3 plus Phase 4 in one migration transaction: recheck the
        # inventory on this connection, then apply runtime ACLs plus
        # default privileges atomically. Any failure rolls back, so a
        # partial REVOKE without its GRANT never persists.
        try:
            mig_inventory = _schema_object_owners(mcur, schema)
            for relname, _relkind, owner in mig_inventory:
                if owner != migration_user:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("runtime-grants",
                                 "unexpected owner %s on %s" % (owner,
                                                               relname))
            mig_functions = _function_owners(mcur, schema)
            for proname, owner in mig_functions:
                if owner != migration_user:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("runtime-grants",
                                 "unexpected owner %s on %s" % (owner,
                                                               proname))
            mcur.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %s "
                         "FROM %s" % (qi_schema, qi_runtime))
            mcur.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                         "IN SCHEMA %s TO %s" % (qi_schema, qi_runtime))
            mcur.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA %s "
                         "FROM %s" % (qi_schema, qi_runtime))
            mcur.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %s "
                         "TO %s" % (qi_schema, qi_runtime))
            present_tables = {rel for rel, _kind, _own in mig_inventory}
            for model_table in MODEL_TABLES:
                if model_table in present_tables:
                    mcur.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE, "
                                 "REFERENCES, TRIGGER ON TABLE %s.%s FROM %s"
                                 % (qi_schema, _quote_ident(model_table),
                                    qi_runtime))
            present_funcs = {name for name, _own in mig_functions}
            if MODEL_RESERVE_FUNC in present_funcs:
                mcur.execute("REVOKE EXECUTE ON FUNCTION %s.%s%s FROM PUBLIC"
                             % (qi_schema, _quote_ident(MODEL_RESERVE_FUNC),
                                MODEL_RESERVE_SIG))
                mcur.execute("GRANT EXECUTE ON FUNCTION %s.%s%s TO %s"
                             % (qi_schema, _quote_ident(MODEL_RESERVE_FUNC),
                                MODEL_RESERVE_SIG, qi_runtime))
            if MODEL_FINALIZE_FUNC in present_funcs:
                mcur.execute("REVOKE EXECUTE ON FUNCTION %s.%s%s FROM PUBLIC"
                             % (qi_schema, _quote_ident(MODEL_FINALIZE_FUNC),
                                MODEL_FINALIZE_SIG))
                mcur.execute("GRANT EXECUTE ON FUNCTION %s.%s%s TO %s"
                             % (qi_schema, _quote_ident(MODEL_FINALIZE_FUNC),
                                MODEL_FINALIZE_SIG, qi_runtime))
            if MODEL_TRIGGER_FUNC in present_funcs:
                mcur.execute("REVOKE EXECUTE ON FUNCTION %s.%s%s FROM PUBLIC"
                             % (qi_schema, _quote_ident(MODEL_TRIGGER_FUNC),
                                MODEL_TRIGGER_SIG))
                mcur.execute("REVOKE EXECUTE ON FUNCTION %s.%s%s FROM %s"
                             % (qi_schema, _quote_ident(MODEL_TRIGGER_FUNC),
                                MODEL_TRIGGER_SIG, qi_runtime))
        except Exception:
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("runtime-grants",
                         "completed: %s" % ",".join(done))
        # Phase 4: later migration-created tables keep the runtime split.
        # Executed as migration for its own role, which a NOSUPERUSER
        # master could never set for another role. Function defaults deny
        # PUBLIC globally only, with no blanket future runtime EXECUTE
        # grant, so a later SECURITY DEFINER function stays owner-only by
        # default. Explicit exact runtime EXECUTE grants on
        # model_reserve_call and model_finalize_call in the runtime-grants
        # phase plus migration 005 discovery keep fresh migration and
        # post-bind correct without needing the runtime role for default
        # function grants.
        try:
            mcur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE %s IN SCHEMA %s "
                         "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %s"
                         % (qi_migration, qi_schema, qi_runtime))
            mcur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE %s IN SCHEMA %s "
                         "GRANT USAGE, SELECT ON SEQUENCES TO %s"
                         % (qi_migration, qi_schema, qi_runtime))
            mcur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE %s "
                         "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
                         % qi_migration)
        except Exception:
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("default-privileges",
                         "completed: %s" % ",".join(done))
        try:
            mconn.commit()
        except Exception:
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("default-privileges",
                         "completed: %s" % ",".join(done))
        done.append("runtime-grants")
        _ok("runtime-grants")
        done.append("default-privileges")
        _ok("default-privileges")
    finally:
        try:
            mconn.close()
        except Exception:
            pass
    print("bootstrap-db-roles: BIND COMPLETE phases=%s" % ",".join(done),
          flush=True)
    return 0


def _refused_ddl(exc):
    # Only an insufficient-privilege refusal counts as DDL proof. A generic
    # network, syntax, or missing-table error must never pass.
    return getattr(exc, "sqlstate", None) == "42501"


def _has_priv(cur, func, obj, priv):
    cur.execute("SELECT %s(%%s, %%s)" % func, (obj, priv))
    row = cur.fetchone()
    return bool(row and row[0])


def _constraint_def(cur, schema, table, name):
    cur.execute(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname = %s AND t.relname = %s AND c.conname = %s",
        (schema, table, name))
    row = cur.fetchone()
    return str(row[0]) if row and row[0] else ""


def _outcome_constraint_names(cur, schema):
    cur.execute(
        "SELECT c.conname FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname = %s AND t.relname = %s",
        (schema, OUTCOME_TABLE))
    return {str(row[0]) for row in (cur.fetchall() or []) if row}


def _column_default(cur, schema, table, column):
    cur.execute(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s "
        "AND column_name = %s",
        (schema, table, column))
    row = cur.fetchone()
    return row[0] if row else None


def do_verify_role_state():
    import psycopg

    bundle = _tls_guard()
    _reject_ambient_pg_overrides()
    host = _check_host("DB_HOST", _env("DB_HOST"))
    port = _check_port(os.environ.get("DB_PORT", "5432"))
    dbname = _check_dbname("DB_NAME", _env("DB_NAME"))
    master_user = _check_ident("DB_MASTER_USER", _env("DB_MASTER_USER"))
    runtime_url = _env("RUNTIME_DB_URL")
    migration_url = _env("MIGRATION_DB_URL")
    runtime_user = _check_ident("RUNTIME_USER", _env("RUNTIME_USER"))
    migration_user = _check_ident("MIGRATION_USER", _env("MIGRATION_USER"))
    schema = _check_ident("APP_SCHEMA", os.environ.get("APP_SCHEMA", "public"))
    if runtime_user == migration_user:
        raise ValueError("RUNTIME_USER and MIGRATION_USER must be distinct roles")
    if runtime_user == master_user or migration_user == master_user:
        raise ValueError("runtime and migration roles must differ from the master user")
    runtime = _parse_db_url("RUNTIME_DB_URL", runtime_url,
                            runtime_user, host, dbname)
    migration = _parse_db_url("MIGRATION_DB_URL", migration_url,
                              migration_user, host, dbname)
    if runtime["port"] != port:
        raise ValueError("RUNTIME_DB_URL port does not match DB_PORT")
    if migration["port"] != port:
        raise ValueError("MIGRATION_DB_URL port does not match DB_PORT")
    for secret in (runtime_url, migration_url,
                   runtime["password"], migration["password"]):
        _known_secrets.append(secret)
    try:
        rconn = psycopg.connect(host=runtime["host"], port=runtime["port"],
                                dbname=runtime["dbname"], user=runtime["user"],
                                password=runtime["password"],
                                sslmode="verify-full", sslrootcert=bundle)
    except Exception as exc:
        return _fail("role-state-runtime-connect",
                     _error_detail(exc, "connection-failed"))
    try:
        rconn.autocommit = False
        rcur = rconn.cursor()
        try:
            ident = _connection_identity(rcur)
        except Exception:
            try:
                rconn.rollback()
            except Exception:
                pass
            return _fail("role-state-runtime-identity")
        if (ident["session_user"] != runtime_user
                or ident["current_user"] != runtime_user):
            try:
                rconn.rollback()
            except Exception:
                pass
            return _fail("role-state-runtime-identity")
        _ok("role-state-runtime-connect")
        try:
            for user in (runtime_user, migration_user):
                row = _role_row(rcur, user)
                if row is None:
                    try:
                        rconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-role-missing")
                verdict = _managed_verdict(rcur, user, row, master_user)
                if verdict is not None:
                    try:
                        rconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-role-safety")
        except Exception:
            try:
                rconn.rollback()
            except Exception:
                pass
            return _fail("role-state-role-catalog")
        _ok("role-state-roles")
        try:
            rconn.rollback()
        except Exception:
            pass
    finally:
        try:
            rconn.close()
        except Exception:
            pass
    try:
        mconn = psycopg.connect(host=migration["host"], port=migration["port"],
                                dbname=migration["dbname"], user=migration["user"],
                                password=migration["password"],
                                sslmode="verify-full", sslrootcert=bundle)
    except Exception as exc:
        return _fail("role-state-migration-connect",
                     _error_detail(exc, "connection-failed"))
    try:
        mconn.autocommit = False
        mcur = mconn.cursor()
        try:
            ident = _connection_identity(mcur)
        except Exception:
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("role-state-migration-identity")
        if (ident["session_user"] != migration_user
                or ident["current_user"] != migration_user):
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("role-state-migration-identity")
        _ok("role-state-migration-connect")
        try:
            for user in (runtime_user, migration_user):
                row = _role_row(mcur, user)
                if row is None:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-role-missing")
                verdict = _managed_verdict(mcur, user, row, master_user)
                if verdict is not None:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-role-safety")
        except Exception:
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("role-state-role-catalog")
        try:
            owner = _schema_owner(mcur, schema)
            if not owner:
                try:
                    mconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-schema-missing")
            if owner != master_user:
                if owner != "pg_database_owner":
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-schema-owner")
                try:
                    db_owner = _database_owner(mcur, dbname)
                except Exception:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-schema-catalog")
                if db_owner != master_user:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-schema-owner")
            _ok("role-state-schema")
        except Exception:
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("role-state-schema-catalog")
        try:
            inventory = _schema_object_owners(mcur, schema)
            funcs = _function_owners(mcur, schema)
        except Exception:
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("role-state-ownership-catalog")
        for relname, _relkind, relowner in inventory:
            if relowner != migration_user:
                try:
                    mconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-ownership")
        for proname, funcowner in funcs:
            if funcowner != migration_user:
                try:
                    mconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-ownership")
        _ok("role-state-ownership")
        try:
            mcur.execute("SELECT version_num FROM alembic_version")
            version = mcur.fetchone()
            head = str(version[0]) if version and version[0] else ""
            if head not in ("007", "008"):
                try:
                    mconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-head")
            print("bootstrap-db-roles: role-state-head ok revision=%s"
                  % _redact(head), flush=True)
        except Exception:
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("role-state-head")
        try:
            names = {rel for rel, _kind, _own in inventory}
            if "workspaces" not in names:
                try:
                    mconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-workspaces-missing")
            if "alembic_version" not in names:
                try:
                    mconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-alembic-missing")
            for model_table in MODEL_TABLES:
                if model_table not in names:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-model-missing")
            fnames = {name for name, _own in funcs}
            for want in (MODEL_RESERVE_FUNC, MODEL_FINALIZE_FUNC,
                          MODEL_TRIGGER_FUNC):
                if want not in fnames:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-model-missing")
            cdef = _constraint_def(mcur, schema, "memory_items",
                                   "memory_item_kind")
            if not cdef or "brand_fact" not in cdef:
                try:
                    mconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-check-missing")
            has_voice = "voice_profile" in cdef
            if head == "007" and not has_voice:
                try:
                    mconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-check-007")
            if head == "008" and not has_voice:
                try:
                    mconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-check-008")
            if head == "007" and OUTCOME_TABLE in names:
                try:
                    mconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-outcome-unexpected")
            if head == "008":
                if OUTCOME_TABLE not in names:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-outcome-missing")
                owners = {rel: own for rel, _kind, own in inventory}
                if owners.get(OUTCOME_TABLE) != migration_user:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-outcome-owner")
                present = _outcome_constraint_names(mcur, schema)
                for want in OUTCOME_CONSTRAINTS:
                    if want not in present:
                        try:
                            mconn.rollback()
                        except Exception:
                            pass
                        return _fail("role-state-outcome-constraints")
                if _column_default(mcur, schema, OUTCOME_TABLE,
                                   "workspace_id") is not None:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-outcome-default")
                actor_def = _constraint_def(mcur, schema, OUTCOME_TABLE,
                                            "run_outcomes_actor_signed_in")
                if not actor_def or "demo_placeholder" not in actor_def:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-outcome-actor")
                prov_def = _constraint_def(mcur, schema, OUTCOME_TABLE,
                                           "run_outcomes_provenance")
                if not prov_def or "self_reported" not in prov_def:
                    try:
                        mconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-outcome-provenance")
            _ok("role-state-schema-props")
        except Exception:
            try:
                mconn.rollback()
            except Exception:
                pass
            return _fail("role-state-schema-props")
        try:
            mconn.rollback()
        except Exception:
            pass
    finally:
        try:
            mconn.close()
        except Exception:
            pass
    try:
        gconn = psycopg.connect(host=runtime["host"], port=runtime["port"],
                                dbname=runtime["dbname"], user=runtime["user"],
                                password=runtime["password"],
                                sslmode="verify-full", sslrootcert=bundle)
    except Exception:
        return _fail("role-state-grants-connect")
    try:
        gconn.autocommit = False
        gcur = gconn.cursor()
        try:
            if not _has_priv(gcur, "has_schema_privilege", schema, "USAGE"):
                try:
                    gconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-schema-grant")
            if _has_priv(gcur, "has_schema_privilege", schema, "CREATE"):
                try:
                    gconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-schema-grant")
            gcur.execute(
                "SELECT c.relname, c.relkind FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s "
                "AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') "
                "ORDER BY c.relname",
                (schema,))
            rels = gcur.fetchall() or []
            for relname, relkind in rels:
                qname = "%s.%s" % (schema, relname)
                if relkind == "S":
                    if not _has_priv(gcur, "has_sequence_privilege",
                                     qname, "USAGE"):
                        try:
                            gconn.rollback()
                        except Exception:
                            pass
                        return _fail("role-state-sequence-grant")
                    if not _has_priv(gcur, "has_sequence_privilege",
                                     qname, "SELECT"):
                        try:
                            gconn.rollback()
                        except Exception:
                            pass
                        return _fail("role-state-sequence-grant")
                    continue
                if relname in MODEL_TABLES:
                    if not _has_priv(gcur, "has_table_privilege",
                                     qname, "SELECT"):
                        try:
                            gconn.rollback()
                        except Exception:
                            pass
                        return _fail("role-state-model-grant")
                    for priv in ("INSERT", "UPDATE", "DELETE",
                                 "TRUNCATE", "REFERENCES", "TRIGGER"):
                        if _has_priv(gcur, "has_table_privilege",
                                     qname, priv):
                            try:
                                gconn.rollback()
                            except Exception:
                                pass
                            return _fail("role-state-model-grant")
                    continue
                for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    if not _has_priv(gcur, "has_table_privilege",
                                     qname, priv):
                        try:
                            gconn.rollback()
                        except Exception:
                            pass
                        return _fail("role-state-table-grant")
                for priv in ("TRUNCATE", "REFERENCES", "TRIGGER"):
                    if _has_priv(gcur, "has_table_privilege", qname, priv):
                        try:
                            gconn.rollback()
                        except Exception:
                            pass
                        return _fail("role-state-table-grant")
            _ok("role-state-grants")
        except Exception:
            try:
                gconn.rollback()
            except Exception:
                pass
            return _fail("role-state-grants")
        try:
            gcur.execute(
                "SELECT p.proname FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = %s AND p.proname IN (%s, %s, %s)",
                (schema, MODEL_RESERVE_FUNC, MODEL_FINALIZE_FUNC,
                 MODEL_TRIGGER_FUNC))
            grows = gcur.fetchall() or []
            if sorted(str(r[0]) for r in grows) != sorted(
                    [MODEL_RESERVE_FUNC, MODEL_FINALIZE_FUNC,
                     MODEL_TRIGGER_FUNC]):
                try:
                    gconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-model-functions")
            for proname, sig in ((MODEL_RESERVE_FUNC, MODEL_RESERVE_SIG),
                                 (MODEL_FINALIZE_FUNC,
                                  MODEL_FINALIZE_SIG)):
                qfunc = "%s.%s%s" % (_quote_ident(schema),
                                     _quote_ident(proname), sig)
                if not _has_priv(gcur, "has_function_privilege",
                                 qfunc, "EXECUTE"):
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-model-functions")
            qtrig = "%s.%s%s" % (_quote_ident(schema),
                                 _quote_ident(MODEL_TRIGGER_FUNC),
                                 MODEL_TRIGGER_SIG)
            if _has_priv(gcur, "has_function_privilege", qtrig, "EXECUTE"):
                try:
                    gconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-model-functions")
            gcur.execute(
                "SELECT e.grantee, e.privilege_type FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace, "
                "LATERAL aclexplode(coalesce(p.proacl, "
                "acldefault(%s, p.proowner))) AS e "
                "WHERE n.nspname = %s AND p.proname IN (%s, %s, %s)",
                ("f", schema, MODEL_RESERVE_FUNC, MODEL_FINALIZE_FUNC,
                 MODEL_TRIGGER_FUNC))
            facls = gcur.fetchall() or []
            for grantee, priv in facls:
                try:
                    g_int = int(grantee)
                except Exception:
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-model-functions")
                if g_int == 0 and str(priv).upper() == "EXECUTE":
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-model-functions")
            _ok("role-state-model-functions")
        except Exception:
            try:
                gconn.rollback()
            except Exception:
                pass
            return _fail("role-state-model-functions")
        try:
            gcur.execute(
                "SELECT e.grantee, e.privilege_type FROM pg_default_acl, "
                "LATERAL aclexplode(defaclacl) AS e "
                "WHERE defaclobjtype = %s", ("f",))
            defaults = gcur.fetchall() or []
            gcur.execute("SELECT oid FROM pg_roles WHERE rolname = %s",
                         (runtime_user,))
            oid_row = gcur.fetchone()
            if not oid_row:
                try:
                    gconn.rollback()
                except Exception:
                    pass
                return _fail("role-state-model-defaults")
            rt_oid = oid_row[0]
            for grantee, priv in defaults:
                try:
                    g_int = int(grantee)
                    r_int = int(rt_oid)
                except Exception:
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-model-defaults")
                if str(priv).upper() == "EXECUTE" and (
                        g_int == 0 or g_int == r_int):
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-model-defaults")
            gcur.execute(
                "SELECT e.grantee, e.privilege_type FROM pg_default_acl d "
                "JOIN pg_roles r ON r.oid = d.defaclrole "
                "JOIN pg_namespace n ON n.oid = d.defaclnamespace "
                "CROSS JOIN LATERAL aclexplode(d.defaclacl) AS e "
                "WHERE d.defaclobjtype = %s AND r.rolname = %s "
                "AND n.nspname = %s",
                ("r", migration_user, schema))
            tdefs = gcur.fetchall() or []
            tprivs = set()
            for grantee, priv in tdefs:
                try:
                    g_int = int(grantee)
                    r_int = int(rt_oid)
                except Exception:
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-table-defaults")
                if g_int == 0:
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-table-defaults")
                if g_int == r_int:
                    tprivs.add(str(priv).upper())
            for want in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if want not in tprivs:
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-table-defaults")
            gcur.execute(
                "SELECT e.grantee, e.privilege_type FROM pg_default_acl d "
                "JOIN pg_roles r ON r.oid = d.defaclrole "
                "JOIN pg_namespace n ON n.oid = d.defaclnamespace "
                "CROSS JOIN LATERAL aclexplode(d.defaclacl) AS e "
                "WHERE d.defaclobjtype = %s AND r.rolname = %s "
                "AND n.nspname = %s",
                ("S", migration_user, schema))
            sdefs = gcur.fetchall() or []
            sprivs = set()
            for grantee, priv in sdefs:
                try:
                    g_int = int(grantee)
                    r_int = int(rt_oid)
                except Exception:
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-sequence-defaults")
                if g_int == 0:
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-sequence-defaults")
                if g_int == r_int:
                    sprivs.add(str(priv).upper())
            for want in ("USAGE", "SELECT"):
                if want not in sprivs:
                    try:
                        gconn.rollback()
                    except Exception:
                        pass
                    return _fail("role-state-sequence-defaults")
            _ok("role-state-model-defaults")
        except Exception:
            try:
                gconn.rollback()
            except Exception:
                pass
            return _fail("role-state-model-defaults")
        try:
            gconn.rollback()
        except Exception:
            pass
    finally:
        try:
            gconn.close()
        except Exception:
            pass
    if head == "008":
        print("bootstrap-db-roles: ROLE-STATE COMPLETE head=008 "
              "roles=2 read-only, no master, repair not needed", flush=True)
        return 0
    print("bootstrap-db-roles: ROLE-STATE COMPLETE head=007 "
          "roles=2 read-only, ready for single 008 migration", flush=True)
    return 10


def do_verify():
    import psycopg

    bundle = _tls_guard()
    _reject_ambient_pg_overrides()
    runtime_url = _env("RUNTIME_DB_URL")
    runtime_user = _check_ident("RUNTIME_USER", _env("RUNTIME_USER"))
    migration_user = _check_ident("MIGRATION_USER", _env("MIGRATION_USER"))
    host = _check_host("DB_HOST", _env("DB_HOST"))
    dbname = _check_dbname("DB_NAME", _env("DB_NAME"))
    # Verify connects with the parsed effective destination only, never the
    # raw URL string, so rerouting query keys or ambient variables cannot
    # silently move this proof to another database.
    target = _parse_db_url("RUNTIME_DB_URL", runtime_url,
                           runtime_user, host, dbname)
    _known_secrets.append(runtime_url)
    _known_secrets.append(target["password"])
    try:
        conn = psycopg.connect(host=target["host"], port=target["port"],
                               dbname=target["dbname"], user=target["user"],
                               password=target["password"],
                               sslmode="verify-full", sslrootcert=bundle)
    except Exception:
        return _fail("verify-connect")
    try:
        conn.autocommit = False
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
            if not version or version[0] != EXPECTED_HEAD:
                return _fail("verify-schema")
            print("bootstrap-db-roles: verify-schema ok revision=%s"
                  % _redact(version[0]), flush=True)
        except Exception:
            return _fail("verify-schema")
        try:
            cur.execute("SELECT current_user")
            identity = cur.fetchone()
            if not identity or identity[0] != runtime_user:
                return _fail("verify-identity")
            _ok("verify-identity")
        except Exception:
            return _fail("verify-identity")
        # Rolled-back write proof: DML must work for the runtime role, but
        # nothing here may commit a row change.
        try:
            cur.execute("INSERT INTO alembic_version (version_num) VALUES (%s)",
                        (VERIFY_PROBE,))
            if cur.rowcount != 1:
                conn.rollback()
                return _fail("verify-write")
            cur.execute("UPDATE alembic_version SET version_num = %s "
                        "WHERE version_num = %s", (VERIFY_PROBE, VERIFY_PROBE))
            if cur.rowcount != 1:
                conn.rollback()
                return _fail("verify-write")
            cur.execute("DELETE FROM alembic_version WHERE version_num = %s",
                        (VERIFY_PROBE,))
            if cur.rowcount != 1:
                conn.rollback()
                return _fail("verify-write")
            conn.rollback()
            _ok("verify-write")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _fail("verify-write")
        for stmt, label in (
                ("CREATE TABLE _lc_verify_nope (id integer primary key)",
                 "verify-runtime-no-create"),
                ("ALTER TABLE alembic_version ADD COLUMN _lc_nope integer",
                 "verify-runtime-no-alter"),
                ("DROP TABLE alembic_version",
                 "verify-runtime-no-drop")):
            try:
                cur.execute(stmt)
                try:
                    conn.rollback()
                except Exception:
                    pass
                return _fail(label)
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if not _refused_ddl(exc):
                    return _fail(label, "not a permission refusal")
                _ok(label)
        try:
            cur.execute("SELECT remaining_micros FROM public.model_budget "
                        "WHERE id = %s", ("global",))
            budget = cur.fetchone()
            if not budget or budget[0] != 0:
                try:
                    conn.rollback()
                except Exception:
                    pass
                return _fail("verify-model-budget-zero")
            conn.rollback()
            _ok("verify-model-budget-zero")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _fail("verify-model-budget-zero")
        for stmt, params in (
                ("INSERT INTO public.model_budget(id, remaining_micros) "
                 "VALUES (%s, %s)", ("other", 1)),
                ("UPDATE public.model_budget SET remaining_micros = %s "
                 "WHERE id = %s", (1, "global")),
                ("DELETE FROM public.model_budget WHERE id = %s",
                 ("global",)),
                ("INSERT INTO public.model_calls(id, run_id, stage, "
                 "attempt_id, request_digest, model, status, "
                 "reservation_micros) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                 ("mc_verify_probe", "verify_run", "Scout", "a1",
                  "0" * 64, "muse-spark-1.3", "admitted", 4000000)),
                ("UPDATE public.model_calls SET status = %s WHERE id = %s",
                 ("succeeded", "mc_nope")),
                ("DELETE FROM public.model_calls WHERE id = %s",
                 ("mc_nope",))):
            try:
                cur.execute(stmt, params)
                try:
                    conn.rollback()
                except Exception:
                    pass
                return _fail("verify-model-no-direct")
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if not _refused_ddl(exc):
                    return _fail("verify-model-no-direct",
                                 "not a permission refusal")
        _ok("verify-model-no-direct")
        try:
            cur.execute("SELECT oid FROM pg_roles WHERE rolname = %s",
                        (runtime_user,))
            oid_row = cur.fetchone()
            if not oid_row:
                conn.rollback()
                return _fail("verify-model-functions")
            rt_oid = oid_row[0]
            cur.execute(
                "SELECT p.proname, p.prosecdef, p.proconfig, owner.rolname "
                "FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "JOIN pg_roles owner ON owner.oid = p.proowner "
                "WHERE n.nspname = %s AND p.proname IN (%s, %s, %s) "
                "ORDER BY p.proname",
                ("public", "model_finalize_call", "model_no_direct",
                 "model_reserve_call"))
            func_rows = cur.fetchall()
            if not isinstance(func_rows, list) or len(func_rows) != 3:
                conn.rollback()
                return _fail("verify-model-functions")
            names = sorted(str(r[0]) for r in func_rows)
            if names != ["model_finalize_call", "model_no_direct",
                         "model_reserve_call"]:
                conn.rollback()
                return _fail("verify-model-functions")
            for row in func_rows:
                if (not isinstance(row, (list, tuple)) or len(row) != 4
                        or str(row[3]) != migration_user):
                    conn.rollback()
                    return _fail("verify-model-functions")
            for proname, secdef, proconfig, _owner in func_rows:
                cfg = list(proconfig or [])
                if proname == "model_no_direct":
                    want_path = ["pg_catalog", "pg_temp"]
                    if secdef:
                        conn.rollback()
                        return _fail("verify-model-functions")
                elif proname in ("model_reserve_call",
                                 "model_finalize_call"):
                    want_path = ["public", "pg_temp"]
                    if not secdef:
                        conn.rollback()
                        return _fail("verify-model-functions")
                else:
                    conn.rollback()
                    return _fail("verify-model-functions")
                got_paths = []
                for value in cfg:
                    text = str(value)
                    if text.startswith("search_path="):
                        raw = text.split("=", 1)[1]
                        parts = [p.strip().strip('"').strip()
                                 for p in raw.split(",")]
                        got_paths.append(parts)
                if len(got_paths) != 1 or got_paths[0] != want_path:
                    conn.rollback()
                    return _fail("verify-model-functions")
                cur.execute(
                    "SELECT e.grantee, e.privilege_type FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid = p.pronamespace, "
                    "LATERAL aclexplode(coalesce(p.proacl, "
                    "acldefault(%s, p.proowner))) AS e "
                    "WHERE n.nspname = %s AND p.proname = %s",
                    ("f", "public", proname))
                acls = cur.fetchall() or []
                for grantee, priv in acls:
                    try:
                        g_int = int(grantee)
                    except Exception:
                        conn.rollback()
                        return _fail("verify-model-functions")
                    if g_int == 0 and str(priv).upper() == "EXECUTE":
                        conn.rollback()
                        return _fail("verify-model-functions")
                has_runtime = False
                for grantee, priv in acls:
                    try:
                        g_int = int(grantee)
                        r_int = int(rt_oid)
                    except Exception:
                        conn.rollback()
                        return _fail("verify-model-functions")
                    if g_int == r_int and str(priv).upper() == "EXECUTE":
                        has_runtime = True
                if proname in ("model_reserve_call",
                               "model_finalize_call"):
                    if not has_runtime:
                        conn.rollback()
                        return _fail("verify-model-functions")
                else:
                    if has_runtime:
                        conn.rollback()
                        return _fail("verify-model-functions")
            conn.rollback()
            _ok("verify-model-functions")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _fail("verify-model-functions")
        try:
            cur.execute(
                "SELECT c.relname, owner.rolname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_roles owner ON owner.oid = c.relowner "
                "WHERE n.nspname = %s AND c.relname IN (%s, %s) "
                "ORDER BY c.relname",
                ("public", "model_budget", "model_calls"))
            table_rows = cur.fetchall() or []
            if not isinstance(table_rows, list):
                conn.rollback()
                return _fail("verify-model-owners")
            owned = []
            for row in table_rows:
                if (not isinstance(row, (list, tuple)) or len(row) != 2):
                    conn.rollback()
                    return _fail("verify-model-owners")
                owned.append((str(row[0]), str(row[1])))
            if sorted(owned) != [("model_budget", migration_user),
                                 ("model_calls", migration_user)]:
                conn.rollback()
                return _fail("verify-model-owners")
            conn.rollback()
            _ok("verify-model-owners")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _fail("verify-model-owners")
        try:
            cur.execute(
                "SELECT e.grantee, e.privilege_type FROM pg_default_acl, "
                "LATERAL aclexplode(defaclacl) AS e "
                "WHERE defaclobjtype = %s", ("f",))
            defaults = cur.fetchall() or []
            cur.execute("SELECT oid FROM pg_roles WHERE rolname = %s",
                        (runtime_user,))
            oid_row2 = cur.fetchone()
            if not oid_row2:
                conn.rollback()
                return _fail("verify-model-defaults")
            rt_oid2 = oid_row2[0]
            for grantee, priv in defaults:
                try:
                    g_int = int(grantee)
                    r_int = int(rt_oid2)
                except Exception:
                    conn.rollback()
                    return _fail("verify-model-defaults")
                if str(priv).upper() == "EXECUTE" and (
                        g_int == 0 or g_int == r_int):
                    conn.rollback()
                    return _fail("verify-model-defaults")
            conn.rollback()
            _ok("verify-model-defaults")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _fail("verify-model-defaults")
        try:
            cur.execute(
                "SELECT c.relname, owner.rolname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_roles owner ON owner.oid = c.relowner "
                "WHERE n.nspname = %s AND c.relname = %s",
                ("public", OUTCOME_TABLE))
            outcome_owner = cur.fetchone()
            if (not outcome_owner or len(outcome_owner) != 2
                    or str(outcome_owner[0]) != OUTCOME_TABLE
                    or str(outcome_owner[1]) != migration_user):
                conn.rollback()
                return _fail("verify-outcome-owner")
            conn.rollback()
            _ok("verify-outcome-owner")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _fail("verify-outcome-owner")
        try:
            names = _outcome_constraint_names(cur, "public")
            for want in OUTCOME_CONSTRAINTS:
                if want not in names:
                    conn.rollback()
                    return _fail("verify-outcome-constraints")
            if _column_default(cur, "public", OUTCOME_TABLE,
                               "workspace_id") is not None:
                conn.rollback()
                return _fail("verify-outcome-default")
            actor_def = _constraint_def(cur, "public", OUTCOME_TABLE,
                                        "run_outcomes_actor_signed_in")
            if not actor_def or "demo_placeholder" not in actor_def:
                conn.rollback()
                return _fail("verify-outcome-actor")
            prov_def = _constraint_def(cur, "public", OUTCOME_TABLE,
                                       "run_outcomes_provenance")
            if not prov_def or "self_reported" not in prov_def:
                conn.rollback()
                return _fail("verify-outcome-provenance")
            conn.rollback()
            _ok("verify-outcome-constraints")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _fail("verify-outcome-constraints")
        try:
            cur.execute("SELECT count(*) FROM public.run_outcomes")
            count_row = cur.fetchone()
            if not count_row or not isinstance(count_row[0], int):
                conn.rollback()
                return _fail("verify-outcome-read")
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if not _has_priv(cur, "has_table_privilege",
                                 "public." + OUTCOME_TABLE, priv):
                    conn.rollback()
                    return _fail("verify-outcome-grants")
            for priv in ("TRUNCATE", "REFERENCES", "TRIGGER"):
                if _has_priv(cur, "has_table_privilege",
                             "public." + OUTCOME_TABLE, priv):
                    conn.rollback()
                    return _fail("verify-outcome-grants")
            conn.rollback()
            _ok("verify-outcome-grants")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _fail("verify-outcome-grants")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    print("bootstrap-db-roles: VERIFY COMPLETE runtime read-only, "
          "schema 008, DDL refused, model and outcome guards ok", flush=True)
    return 0


def main(argv):
    if len(argv) != 2 or argv[1] not in ("--bind", "--verify",
                                        "--verify-role-state"):
        print("usage: bootstrap_db_roles.py [--bind|--verify|--verify-role-state]",
              flush=True)
        return 2
    try:
        if argv[1] == "--bind":
            return do_bind()
        if argv[1] == "--verify-role-state":
            return do_verify_role_state()
        return do_verify()
    except ValueError as exc:
        return _fail("config", str(exc))
    except Exception:
        return _fail("internal")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
