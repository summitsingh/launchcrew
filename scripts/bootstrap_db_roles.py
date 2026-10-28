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
  --bind    create exact owned roles if missing (stamped with an ownership
            comment), bind each role password to the matching injected
            secret URL password, then apply the privilege split in two
            connections. The RDS master is NOSUPERUSER CREATEROLE, not a
            true postgres superuser, so it creates, stamps, and password
            binds roles plus schema ACLs only. A direct migration
            connection then applies runtime DML-only object grants plus
            its own default privileges on migration-owned objects.
            Existing roles are rebound only with the ownership stamp and
            no superuser, bypassrls, create, replication, or membership
            takeover risk. The only permitted membership is the exact
            native Postgres 16 creator administration row. Idempotent:
            safe to rerun; reports each completed phase.
  --verify  read-only proof with the runtime URL only: SELECT works, the
            alembic schema version equals the expected head revision, the
            connected identity equals the runtime role, a rolled-back write
            proves DML without committing, and runtime CREATE/ALTER/DROP
            each fail with SQLSTATE 42501. Never connects as master or
            migration here, and never commits.

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
PHASES_BIND = ("password-binding", "schema-acls", "runtime-grants",
               "default-privileges")
ROOTCERT_ENV = "DATABASE_SSL_ROOTCERT"
EXPECTED_HEAD = "004"
VERIFY_PROBE = "_lc_verify_probe"
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
    # with grantor identity plus superuser flag plus all three options.
    # Postgres 16 carries admin, inherit, and set options; the automatic
    # creator row is ADMIN TRUE, INHERIT FALSE, SET FALSE with the
    # native bootstrap superuser as grantor.
    cur.execute(
        "SELECT target.rolname, member.rolname, grantor.rolname, "
        "grantor.rolsuper, m.admin_option, m.inherit_option, "
        "m.set_option FROM pg_auth_members m "
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
    target, member, grantor, grantor_super, admin, inherit_opt, set_opt = (
        memberships[0])
    if target != name or member != master_user:
        return ("existing role with memberships refused: %s "
                "is not the exact creator row" % name)
    if not admin or inherit_opt or set_opt:
        return ("existing role with memberships refused: %s "
                "has changed membership options" % name)
    if not grantor_super or grantor == master_user or grantor == name:
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
    # Regular tables, partitioned tables, and sequences in the isolated
    # app schema with their owner names. Views and indexes are out of
    # scope for the runtime grant split.
    cur.execute(
        "SELECT c.relname, c.relkind, owner.rolname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_roles owner ON owner.oid = c.relowner "
        "WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'S') "
        "ORDER BY c.relname",
        (schema,))
    return cur.fetchall()


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
    for secret in (master_password, runtime_url, migration_url,
                   runtime["password"], migration["password"]):
        _known_secrets.append(secret)
    if not host or " " in host:
        raise ValueError("invalid DB_HOST")

    done = []
    qi_runtime = _quote_ident(runtime_user)
    qi_migration = _quote_ident(migration_user)
    qi_schema = _quote_ident(schema)
    try:
        conn = psycopg.connect(host=host, port=port, dbname=dbname,
                               user=master_user, password=master_password,
                               sslmode="verify-full", sslrootcert=bundle)
    except Exception:
        return _fail("connect")
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
    except Exception:
        return _fail("migration-connect",
                     "completed: %s" % ",".join(done))
    try:
        mconn.autocommit = True
        mcur = mconn.cursor()
        try:
            identity = _connection_identity(mcur)
        except Exception:
            return _fail("migration-identity",
                         "completed: %s" % ",".join(done))
        if (identity["session_user"] != migration_user
                or identity["current_user"] != migration_user):
            return _fail("migration-identity",
                         "completed: %s" % ",".join(done))
        # Phase 3: runtime DML-only object split on migration-owned
        # objects. Inventory first; unexpected owners are refused and
        # never transferred.
        try:
            for relname, _relkind, owner in _schema_object_owners(mcur,
                                                                 schema):
                if owner != migration_user:
                    return _fail("runtime-grants",
                                 "unexpected owner %s on %s" % (owner,
                                                               relname))
            mcur.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %s "
                         "FROM %s" % (qi_schema, qi_runtime))
            mcur.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                         "IN SCHEMA %s TO %s" % (qi_schema, qi_runtime))
            mcur.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA %s "
                         "FROM %s" % (qi_schema, qi_runtime))
            mcur.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %s "
                         "TO %s" % (qi_schema, qi_runtime))
            done.append("runtime-grants")
            _ok("runtime-grants")
        except Exception:
            return _fail("runtime-grants",
                         "completed: %s" % ",".join(done))
        # Phase 4: later migration-created tables keep the runtime split.
        # Executed as migration for its own role, which a NOSUPERUSER
        # master could never set for another role.
        try:
            mcur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE %s IN SCHEMA %s "
                         "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %s"
                         % (qi_migration, qi_schema, qi_runtime))
            mcur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE %s IN SCHEMA %s "
                         "GRANT USAGE, SELECT ON SEQUENCES TO %s"
                         % (qi_migration, qi_schema, qi_runtime))
            done.append("default-privileges")
            _ok("default-privileges")
        except Exception:
            return _fail("default-privileges",
                         "completed: %s" % ",".join(done))
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


def do_verify():
    import psycopg

    bundle = _tls_guard()
    _reject_ambient_pg_overrides()
    runtime_url = _env("RUNTIME_DB_URL")
    runtime_user = _check_ident("RUNTIME_USER", _env("RUNTIME_USER"))
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
            conn.rollback()
        except Exception:
            pass
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
