#!/usr/bin/env bash
# LaunchCrew demo db-roles verification on a disposable PostgreSQL cluster.
# This script creates its own temporary cluster, runs the actual
# deploy/aws/db-roles.sql with ON_ERROR_STOP in one transaction, then
# proves runtime CRUD plus sequence use and proves DDL split.
# Disposable only: temp PGDATA in mktemp dir, loopback 127.0.0.1 only,
# nondefault port, trust auth in the temp cluster only, trap cleanup,
# no persistent service, no existing database, no live secret.
# Demo identities only: lc_runtime_demo and lc_migration_demo.
# Usage:
#   scripts/verify-db-roles.sh
#   scripts/verify-db-roles.sh --static-only
# Env:
#   PG_BIN=/path/to/pg18/bin (dir with initdb, pg_ctl, psql)
#   PG_VERIFY_PORT=55432 (optional nondefault loopback port)
# Stage 2 also needs python3 with psycopg, alembic, sqlalchemy plus the
# backend store importable, and openssl for the disposable certificate.
# Every missing piece fails with its own message, never a silent pass.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SQL_FILE="$REPO_ROOT/deploy/aws/db-roles.sql"

RUNTIME_USER="lc_runtime_demo"
MIGRATION_USER="lc_migration_demo"
APP_SCHEMA="public"
DB_NAME="lc_verify_db"
SUPERUSER="postgres"

log() {
  echo "[verify-db-roles] $1"
}

fail() {
  echo "[verify-db-roles] FAIL: $1" >&2
  exit 1
}

usage() {
  echo "Usage: scripts/verify-db-roles.sh [--static-only] [--help]"
  echo "Env: PG_BIN=/opt/homebrew/opt/postgresql@18/bin PG_VERIFY_PORT=55432"
}

static_checks() {
  log "static checks on $SQL_FILE"
  [ -f "$SQL_FILE" ] || { echo "missing SQL file: $SQL_FILE" >&2; return 1; }
  [ -r "$SQL_FILE" ] || { echo "unreadable SQL file: $SQL_FILE" >&2; return 1; }

  # Repeatable syntax check for this script itself.
  bash -n "$SCRIPT_DIR/verify-db-roles.sh" || return 1
  log "static: bash -n pass"

  # No em dash in SQL (repo scan also enforces this).
  if grep -q "$(printf '\342\200\224')" "$SQL_FILE"; then
    echo "static: SQL contains em dash" >&2
    return 1
  fi

  # Work only on non-comment lines for privilege checks.
  # Forbid ALTER and DROP as table privileges. ALTER DEFAULT PRIVILEGES
  # lines are allowed, so exclude them before checking GRANT and REVOKE.
  tmp_grants="$(mktemp /tmp/lc-roles-grants-XXXXXX)"
  grep -v '^[[:space:]]*--' "$SQL_FILE" | grep -v 'ALTER DEFAULT PRIVILEGES' > "$tmp_grants" || true
  if grep -i -E '^[[:space:]]*(GRANT|REVOKE)[[:space:]].*\b(ALTER|DROP)\b.*ON[[:space:]]+TABLES' "$tmp_grants" >/dev/null; then
    echo "static: forbidden ALTER or DROP as table privilege" >&2
    rm -f "$tmp_grants"
    return 1
  fi
  log "static: no ALTER or DROP as table privilege"

  # Both roles must be created before ALTER DEFAULT PRIVILEGES references them.
  runtime_line="$(grep -n -m 1 -E 'CREATE[[:space:]]+ROLE[[:space:]]+:runtime_user' "$SQL_FILE" | cut -d: -f1 || true)"
  migration_line="$(grep -n -m 1 -E 'CREATE[[:space:]]+ROLE[[:space:]]+:migration_user' "$SQL_FILE" | cut -d: -f1 || true)"
  default_line="$(grep -n -m 1 -E 'ALTER[[:space:]]+DEFAULT[[:space:]]+PRIVILEGES[[:space:]]+FOR[[:space:]]+ROLE[[:space:]]+:migration_user' "$SQL_FILE" | cut -d: -f1 || true)"
  if [ -z "$runtime_line" ] || [ -z "$migration_line" ] || [ -z "$default_line" ]; then
    echo "static: missing CREATE ROLE or ALTER DEFAULT PRIVILEGES line" >&2
    rm -f "$tmp_grants"
    return 1
  fi
  if [ "$runtime_line" -gt "$default_line" ] || [ "$migration_line" -gt "$default_line" ]; then
    echo "static: CREATE ROLE must precede ALTER DEFAULT PRIVILEGES (runtime=$runtime_line migration=$migration_line default=$default_line)" >&2
    rm -f "$tmp_grants"
    return 1
  fi
  log "static: role order pass (runtime=$runtime_line migration=$migration_line default=$default_line)"

  # Runtime DML plus usage and sequence rights only.
  grep -q -E 'GRANT[[:space:]]+SELECT,[[:space:]]*INSERT,[[:space:]]*UPDATE,[[:space:]]*DELETE[[:space:]]+ON[[:space:]]+ALL[[:space:]]+TABLES' "$SQL_FILE" || { echo "static: missing runtime table DML grant" >&2; rm -f "$tmp_grants"; return 1; }
  grep -q -E 'GRANT[[:space:]]+USAGE,[[:space:]]*SELECT[[:space:]]+ON[[:space:]]+ALL[[:space:]]+SEQUENCES' "$SQL_FILE" || { echo "static: missing runtime sequence grant" >&2; rm -f "$tmp_grants"; return 1; }
  grep -q -E 'REVOKE[[:space:]]+CREATE[[:space:]]+ON[[:space:]]+SCHEMA[[:space:]]+:app_schema[[:space:]]+FROM[[:space:]]+:runtime_user' "$SQL_FILE" || { echo "static: missing runtime schema CREATE revoke" >&2; rm -f "$tmp_grants"; return 1; }
  if grep -i -E 'GRANT[[:space:]].*\b(CREATE|TRUNCATE|REFERENCES|TRIGGER)\b.*TO[[:space:]]+:runtime_user' "$tmp_grants" >/dev/null; then
    echo "static: runtime must not receive CREATE, TRUNCATE, REFERENCES, or TRIGGER" >&2
    rm -f "$tmp_grants"
    return 1
  fi
  log "static: runtime DML-only grants pass"

  # Migration schema DDL plus full rights.
  grep -q -E 'GRANT[[:space:]]+USAGE,[[:space:]]*CREATE[[:space:]]+ON[[:space:]]+SCHEMA' "$SQL_FILE" || { echo "static: missing migration schema grant" >&2; rm -f "$tmp_grants"; return 1; }
  grep -q -E 'GRANT[[:space:]]+ALL[[:space:]]+PRIVILEGES[[:space:]]+ON[[:space:]]+ALL[[:space:]]+TABLES[[:space:]]+IN[[:space:]]+SCHEMA[[:space:]]+:app_schema[[:space:]]+TO[[:space:]]+:migration_user' "$SQL_FILE" || { echo "static: missing migration table grant" >&2; rm -f "$tmp_grants"; return 1; }
  grep -q -E 'GRANT[[:space:]]+ALL[[:space:]]+PRIVILEGES[[:space:]]+ON[[:space:]]+ALL[[:space:]]+SEQUENCES[[:space:]]+IN[[:space:]]+SCHEMA[[:space:]]+:app_schema[[:space:]]+TO[[:space:]]+:migration_user' "$SQL_FILE" || { echo "static: missing migration sequence grant" >&2; rm -f "$tmp_grants"; return 1; }
  log "static: migration grants pass"

  # Default grants for later migration-created objects.
  grep -q -E 'ALTER[[:space:]]+DEFAULT[[:space:]]+PRIVILEGES[[:space:]]+FOR[[:space:]]+ROLE[[:space:]]+:migration_user.*GRANT[[:space:]]+SELECT,[[:space:]]*INSERT' "$SQL_FILE" || { echo "static: missing default table grant" >&2; rm -f "$tmp_grants"; return 1; }
  grep -q -E 'ALTER[[:space:]]+DEFAULT[[:space:]]+PRIVILEGES[[:space:]]+FOR[[:space:]]+ROLE[[:space:]]+:migration_user.*GRANT[[:space:]]+USAGE,[[:space:]]*SELECT[[:space:]]+ON[[:space:]]+SEQUENCES' "$SQL_FILE" || { echo "static: missing default sequence grant" >&2; rm -f "$tmp_grants"; return 1; }
  log "static: default privileges pass"

  # Model function defaults: global PUBLIC revoke only, no blanket runtime grant.
  grep -q -E 'ALTER[[:space:]]+DEFAULT[[:space:]]+PRIVILEGES[[:space:]]+FOR[[:space:]]+ROLE[[:space:]]+:migration_user[[:space:]]+REVOKE[[:space:]]+EXECUTE[[:space:]]+ON[[:space:]]+FUNCTIONS[[:space:]]+FROM[[:space:]]+PUBLIC' "$SQL_FILE" || { echo "static: missing global function PUBLIC revoke" >&2; rm -f "$tmp_grants"; return 1; }
  if grep -E 'ALTER[[:space:]]+DEFAULT[[:space:]]+PRIVILEGES[[:space:]]+FOR[[:space:]]+ROLE[[:space:]]+:migration_user[[:space:]]+REVOKE[[:space:]]+EXECUTE' "$SQL_FILE" | grep -q 'IN[[:space:]]\+SCHEMA'; then
    echo "static: per-schema PUBLIC function revoke cannot cancel global defaults" >&2
    rm -f "$tmp_grants"
    return 1
  fi
  if grep -E 'ALTER[[:space:]]+DEFAULT[[:space:]]+PRIVILEGES[[:space:]]+FOR[[:space:]]+ROLE[[:space:]]+:migration_user.*GRANT[[:space:]]+EXECUTE[[:space:]]+ON[[:space:]]+FUNCTIONS' "$SQL_FILE" >/dev/null; then
    echo "static: blanket future function runtime grant must be absent" >&2
    rm -f "$tmp_grants"
    return 1
  fi
  log "static: model function defaults pass"

  # No password assignment in non-comment SQL.
  if grep -i -E 'PASSWORD[[:space:]]*(=|USING|VALUES)' "$tmp_grants" >/dev/null; then
    echo "static: SQL must not assign a password" >&2
    rm -f "$tmp_grants"
    return 1
  fi
  rm -f "$tmp_grants"
  log "static: all static checks pass"
}

find_pg_bin() {
  if [ -n "${PG_BIN:-}" ]; then
    if [ ! -d "$PG_BIN" ]; then
      fail "PG_BIN is not a directory: $PG_BIN"
    fi
    echo "$PG_BIN"
    return 0
  fi
  candidates=""
  if command -v brew >/dev/null 2>&1; then
    brew_prefix="$(brew --prefix postgresql@18 2>/dev/null || true)"
    if [ -n "$brew_prefix" ] && [ -d "$brew_prefix/bin" ]; then
      candidates="$candidates $brew_prefix/bin"
    fi
  fi
  candidates="$candidates /opt/homebrew/opt/postgresql@18/bin /usr/local/opt/postgresql@18/bin"
  for dir in $candidates; do
    if [ -x "$dir/initdb" ] && [ -x "$dir/pg_ctl" ] && [ -x "$dir/psql" ]; then
      echo "$dir"
      return 0
    fi
  done
  fail "PostgreSQL 18 binaries not found. Set PG_BIN to the postgresql@18 bin dir, for example PG_BIN=/opt/homebrew/opt/postgresql@18/bin"
}

check_pg18() {
  pg_bin="$1"
  version="$("$pg_bin/psql" --version 2>/dev/null || true)"
  log "psql version: $version"
  case "$version" in
    *" 18."*) ;;
    *) fail "PostgreSQL 18 is required, found: $version" ;;
  esac
}

pick_port() {
  if [ -n "${PG_VERIFY_PORT:-}" ]; then
    case "$PG_VERIFY_PORT" in
      ''|*[!0-9]*) fail "PG_VERIFY_PORT must be numeric" ;;
    esac
    if [ "$PG_VERIFY_PORT" = "5432" ]; then
      fail "PG_VERIFY_PORT must be nondefault, not 5432"
    fi
    if [ "$PG_VERIFY_PORT" -lt 1024 ] || [ "$PG_VERIFY_PORT" -gt 65535 ]; then
      fail "PG_VERIFY_PORT out of range 1024-65535"
    fi
    echo "$PG_VERIFY_PORT"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    free_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])' 2>/dev/null || true)"
    if [ -n "$free_port" ] && [ "$free_port" != "5432" ]; then
      echo "$free_port"
      return 0
    fi
  fi
  echo "55432"
}

MODE="full"
for arg in ${1+"$@"}; do
  case "$arg" in
    --static-only) MODE="static" ;;
    --help|-h) usage; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

static_checks || fail "static checks failed"
if [ "$MODE" = "static" ]; then
  log "STATIC ONLY PASS"
  exit 0
fi

PG_BIN_DIR="$(find_pg_bin)"
check_pg18 "$PG_BIN_DIR"
PORT="$(pick_port)"
if [ "$PORT" = "5432" ]; then
  fail "refusing default port 5432"
fi
log "using PG_BIN=$PG_BIN_DIR port=$PORT loopback 127.0.0.1 only"

PG_ROOT="$(mktemp -d /tmp/launchcrew-pg-verify-XXXXXX)"
PGDATA="$PG_ROOT/data"
SOCKDIR="$PG_ROOT/sock"
LOGFILE="$PG_ROOT/postgres.log"
mkdir -p "$SOCKDIR"
chmod 700 "$PG_ROOT" "$SOCKDIR"

cleanup() {
  if [ -n "${PGDATA:-}" ] && [ -d "$PGDATA" ] && [ -x "$PG_BIN_DIR/pg_ctl" ]; then
    "$PG_BIN_DIR/pg_ctl" -D "$PGDATA" -m fast stop >/dev/null 2>&1 || true
  fi
  if [ -n "${PG_ROOT:-}" ] && [ -d "$PG_ROOT" ]; then
    rm -rf "$PG_ROOT"
  fi
}
trap cleanup EXIT INT TERM

log "initdb disposable cluster in $PGDATA"
"$PG_BIN_DIR/initdb" -D "$PGDATA" -U "$SUPERUSER" --auth=trust -E UTF8 >/dev/null

log "start postgres on 127.0.0.1:$PORT with socket dir $SOCKDIR"
"$PG_BIN_DIR/pg_ctl" -D "$PGDATA" -l "$LOGFILE" -o "-h 127.0.0.1 -p $PORT -k $SOCKDIR -c listen_addresses='127.0.0.1'" -w start

ready=0
for _ in $(seq 1 30); do
  if "$PG_BIN_DIR/pg_isready" -h 127.0.0.1 -p "$PORT" -U "$SUPERUSER" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" != "1" ]; then
  fail "postgres did not become ready; see $LOGFILE"
fi

listen="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=postgres user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SHOW listen_addresses;" | tr -d '[:space:]')"
shown_port="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=postgres user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SHOW port;" | tr -d '[:space:]')"
if [ "$listen" != "127.0.0.1" ] && [ "$listen" != "localhost" ]; then
  fail "refusing non-loopback listen_addresses: $listen"
fi
if [ "$shown_port" = "5432" ] || [ "$shown_port" != "$PORT" ]; then
  fail "refusing unexpected port: $shown_port"
fi
log "listening on $listen:$shown_port (loopback, nondefault)"

log "create disposable database $DB_NAME"
"$PG_BIN_DIR/createdb" -h 127.0.0.1 -p "$PORT" -U "$SUPERUSER" "$DB_NAME"

log "run actual db-roles.sql with ON_ERROR_STOP in one transaction"
"$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$DB_NAME user=$SUPERUSER" \
  -v ON_ERROR_STOP=1 --single-transaction \
  -v runtime_user="$RUNTIME_USER" \
  -v migration_user="$MIGRATION_USER" \
  -v app_schema="$APP_SCHEMA" \
  -f "$SQL_FILE"

psql_super() {
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$DB_NAME user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "$1"
}

psql_as() {
  as_user="$1"
  sql="$2"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$DB_NAME user=$as_user" -v ON_ERROR_STOP=1 -tAc "$sql"
}

expect_success() {
  label="$1"
  as_user="$2"
  sql="$3"
  set +e
  out="$(psql_as "$as_user" "$sql" 2>&1)"
  status=$?
  set -e
  if [ $status -ne 0 ]; then
    echo "$out" >&2
    fail "$label as $as_user must succeed but failed"
  fi
  log "pass: $label as $as_user succeeds"
}

expect_failure() {
  label="$1"
  as_user="$2"
  sql="$3"
  set +e
  out="$(psql_as "$as_user" "$sql" 2>&1)"
  status=$?
  set -e
  if [ $status -eq 0 ]; then
    echo "$out" >&2
    fail "$label as $as_user must fail but succeeded"
  fi
  case "$out" in
    *"permission denied"*|*"must be owner"*|*"insufficient privilege"*|*"not permitted"*) ;;
    *) echo "$out" >&2; fail "$label as $as_user failed without an insufficient-privilege error" ;;
  esac
  log "pass: $label as $as_user is rejected"
}

log "verify demo roles exist"
runtime_exists="$(psql_super "SELECT 1 FROM pg_roles WHERE rolname='$RUNTIME_USER';" | tr -d '[:space:]')"
migration_exists="$(psql_super "SELECT 1 FROM pg_roles WHERE rolname='$MIGRATION_USER';" | tr -d '[:space:]')"
[ "$runtime_exists" = "1" ] || fail "runtime role missing: $RUNTIME_USER"
[ "$migration_exists" = "1" ] || fail "migration role missing: $MIGRATION_USER"

log "migration creates the CRUD table; no extra GRANT follows, default privileges must apply"
expect_success "migration CREATE TABLE verify_items" "$MIGRATION_USER" "CREATE TABLE $APP_SCHEMA.verify_items (id SERIAL PRIMARY KEY, note TEXT);"

log "runtime CRUD on the migration-created table"
expect_success "runtime INSERT" "$RUNTIME_USER" "INSERT INTO $APP_SCHEMA.verify_items(note) VALUES ('demo-row-1') RETURNING id;"
expect_success "runtime SELECT" "$RUNTIME_USER" "SELECT id, note FROM $APP_SCHEMA.verify_items;"
expect_success "runtime UPDATE" "$RUNTIME_USER" "UPDATE $APP_SCHEMA.verify_items SET note='demo-row-2' WHERE note='demo-row-1';"
expect_success "runtime sequence nextval" "$RUNTIME_USER" "SELECT nextval('$APP_SCHEMA.verify_items_id_seq');"
expect_success "runtime sequence SELECT" "$RUNTIME_USER" "SELECT last_value FROM $APP_SCHEMA.verify_items_id_seq;"
expect_success "runtime DELETE" "$RUNTIME_USER" "DELETE FROM $APP_SCHEMA.verify_items WHERE note='demo-row-2';"

log "runtime DDL must be rejected"
expect_failure "runtime CREATE TABLE" "$RUNTIME_USER" "CREATE TABLE $APP_SCHEMA.runtime_no_create (id integer);"
expect_failure "runtime ALTER TABLE" "$RUNTIME_USER" "ALTER TABLE $APP_SCHEMA.verify_items ADD COLUMN extra_col integer;"
expect_failure "runtime DROP TABLE" "$RUNTIME_USER" "DROP TABLE $APP_SCHEMA.verify_items;"

log "migration DDL must succeed on a disposable proof table"
expect_success "migration CREATE TABLE proof" "$MIGRATION_USER" "CREATE TABLE $APP_SCHEMA.mig_ddl_proof (id integer PRIMARY KEY, note text);"
expect_success "migration ALTER TABLE proof" "$MIGRATION_USER" "ALTER TABLE $APP_SCHEMA.mig_ddl_proof ADD COLUMN extra_col integer;"
expect_success "migration DROP TABLE proof" "$MIGRATION_USER" "DROP TABLE $APP_SCHEMA.mig_ddl_proof;"

log "verify_items still present after rejected runtime DROP"
expect_success "migration SELECT verify_items" "$MIGRATION_USER" "SELECT count(*) FROM $APP_SCHEMA.verify_items;"

log "PASS: db-roles file proof complete on disposable 127.0.0.1:$PORT"

bind_verify_live() {
  log "stage 2: actual bind and verify job on the disposable cluster"
  log "loopback only with a disposable self-signed CA; this exercises the"
  log "real verify-full code path but is NOT live RDS TLS proof"
  command -v python3 >/dev/null 2>&1 || fail "python3 is required for stage 2"
  command -v openssl >/dev/null 2>&1 || fail "openssl is required for stage 2 certificates, no bundle can be made without it"
  python3 -c "import psycopg" 2>/dev/null || fail "python3 psycopg is required for stage 2, no database driver means no invented pass"
  python3 -c "import alembic, sqlalchemy" 2>/dev/null || fail "python3 alembic and sqlalchemy are required for stage 2, no migration run without them means no invented pass"
  (cd "$REPO_ROOT" && python3 -c "import backend.store" 2>/dev/null) || fail "backend.store must import for the alembic run in stage 2"
  head_expected="$(grep -E "^revision = " "$REPO_ROOT/backend/migrations/versions/008_run_outcomes.py" | cut -d"'" -f2)" || true
  head_script="$(grep -E "^EXPECTED_HEAD = " "$REPO_ROOT/scripts/bootstrap_db_roles.py" | cut -d'"' -f2)" || true
  [ -n "$head_expected" ] || fail "migration head unreadable, no invented pass"
  [ "$head_expected" = "$head_script" ] || fail "EXPECTED_HEAD $head_script does not match migration head $head_expected"
  [ "$head_expected" = "008" ] || fail "migration head is $head_expected, expected 008"

  BIND_DB="lc_bind_db"
  BIND_ADMIN="lc_bind_admin"
  BIND_RT="lc_bind_runtime"
  BIND_MG="lc_bind_migration"
  log "create RDS-like fixture admin NOSUPERUSER CREATEDB CREATEROLE, leave $BIND_DB absent"
  log "local admin logic proof only, NOT RDS identity proof"
  log "fresh-path proof: actual --bind must create the exact DB via maintenance postgres"

  # Fresh bind identities and the bind database stay absent here on purpose.
  # The actual scripts/bootstrap_db_roles.py --bind below connects strict
  # verify-full TLS to the built-in postgres maintenance database as the
  # fixture admin, creates exactly BIND_DB if absent, then creates each
  # role, stamps the ownership marker, binds its password, and applies the
  # privilege split. Precreating the database with createdb would skip the
  # fresh db-ensure path, and precreating the roles with db-roles.sql would
  # leave them without the ownership marker, and the hardened bind correctly
  # refuses such unowned roles, so no precreate or blind takeover happens
  # in this stage. Stage 1 above already proves db-roles.sql.

  ADMIN_PW="$(python3 -c 'import secrets; print(secrets.token_hex(18))')"
  [ "${#ADMIN_PW}" -ge 32 ] || fail "synthetic admin password failed"
  BIND_ADMIN_NAME="$BIND_ADMIN" BIND_ADMIN_PW="$ADMIN_PW" \
  BIND_PORT="$PORT" python3 -c '
import os
import psycopg
admin = os.environ["BIND_ADMIN_NAME"]
pw = os.environ["BIND_ADMIN_PW"]
port = int(os.environ["BIND_PORT"])
if admin != "lc_bind_admin":
    raise SystemExit("unexpected admin name")
conn = psycopg.connect(host="127.0.0.1", port=port, dbname="postgres",
                       user="postgres", autocommit=True)
cur = conn.cursor()
cur.execute("CREATE ROLE lc_bind_admin WITH LOGIN NOSUPERUSER "
            "CREATEROLE CREATEDB NOREPLICATION NOBYPASSRLS")
cc = psycopg.ClientCursor(conn)
cc.execute("ALTER ROLE lc_bind_admin WITH PASSWORD %s", (pw,))
conn.close()
' || fail "fixture admin creation failed"
  log "fixture admin is LOGIN NOSUPERUSER CREATEROLE CREATEDB"
  admin_flags="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=postgres user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolsuper::text || ',' || rolcreaterole::text || ',' || rolcreatedb::text || ',' || rolcanlogin::text FROM pg_roles WHERE rolname='"$BIND_ADMIN"';" | tr -d '[:space:]')" || true
  [ "$admin_flags" = "false,true,true,true" ] || fail "fixture admin flags are $admin_flags, expected false,true,true,true"
  db_absent="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=postgres user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM pg_database WHERE datname='"$BIND_DB"';" | tr -d '[:space:]')" || true
  [ "$db_absent" = "0" ] || fail "bind DB $BIND_DB must be absent before fresh bind"
  log "pass: admin is NOSUPERUSER CREATEDB CREATEROLE and $BIND_DB is absent"

  CERTDIR="$PGDATA/certs"
  mkdir -p "$CERTDIR"
  chmod 700 "$CERTDIR"
  openssl req -x509 -newkey rsa:2048 -keyout "$CERTDIR/server.key" \
    -out "$CERTDIR/server.crt" -days 2 -nodes \
    -subj "/CN=127.0.0.1" \
    -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" >/dev/null 2>&1 \
    || fail "openssl could not create the disposable certificate"
  chmod 600 "$CERTDIR/server.key"
  {
    echo "ssl = on"
    echo "ssl_cert_file = '$CERTDIR/server.crt'"
    echo "ssl_key_file = '$CERTDIR/server.key'"
  } >>"$PGDATA/postgresql.conf"
  "$PG_BIN_DIR/pg_ctl" -D "$PGDATA" -l "$LOGFILE" \
    -o "-h 127.0.0.1 -p $PORT -k $SOCKDIR -c listen_addresses='127.0.0.1'" -w restart
  ssl_on="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=postgres user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SHOW ssl;" | tr -d '[:space:]')" || true
  [ "$ssl_on" = "on" ] || fail "disposable server has no SSL support, cannot exercise verify-full, no invented pass"
  log "disposable server SSL is on with a fresh self-signed CA"

  # Maintenance postgres requires the admin password so the fresh db-ensure
  # path proves password-auth plus verify-full TLS. BIND_DB lines cover the
  # fresh DB once actual --bind creates it. Loopback disposable only.
  HBA="$PGDATA/pg_hba.conf"
  {
    echo "host postgres $BIND_ADMIN 127.0.0.1/32 scram-sha-256"
    echo "host $BIND_DB $BIND_ADMIN 127.0.0.1/32 scram-sha-256"
    echo "host $BIND_DB $BIND_RT 127.0.0.1/32 scram-sha-256"
    echo "host $BIND_DB $BIND_MG 127.0.0.1/32 scram-sha-256"
    cat "$HBA"
  } >"$HBA.new" || fail "could not stage password-auth pg_hba"
  mv "$HBA.new" "$HBA" || fail "could not install password-auth pg_hba"
  "$PG_BIN_DIR/pg_ctl" -D "$PGDATA" -w reload
  log "admin plus bind roles use password auth, superuser keeps trust"

  BIND_RT_PW="$(python3 -c 'import secrets; print(secrets.token_hex(18))')"
  BIND_MG_PW="$(python3 -c 'import secrets; print(secrets.token_hex(18))')"
  INTR_PW="$(python3 -c 'import secrets; print(secrets.token_hex(18))')"
  [ "${#BIND_RT_PW}" -ge 32 ] || fail "synthetic password generation failed"
  RT_URL="postgresql://${BIND_RT}:${BIND_RT_PW}@127.0.0.1:${PORT}/${BIND_DB}?sslmode=verify-full"
  MG_URL="postgresql://${BIND_MG}:${BIND_MG_PW}@127.0.0.1:${PORT}/${BIND_DB}?sslmode=verify-full"
  INTR_URL="postgresql://lc_intruder_demo:${INTR_PW}@127.0.0.1:${PORT}/${BIND_DB}?sslmode=verify-full"

  safe_emit() {
    # Bounded redacted error output for stage 2 failures. Secrets arrive
    # via env and text arrives via stdin, so no secret value ever appears
    # in argv. Output is truncated to 2000 bytes. Harness only, no values.
    REDACT_A="$BIND_RT_PW" REDACT_B="$BIND_MG_PW" REDACT_C="$ADMIN_PW" REDACT_D="$INTR_PW" \
    REDACT_E="$RT_URL" REDACT_F="$MG_URL" python3 -c '
import os, sys
text = sys.stdin.read()
for key in ("REDACT_A", "REDACT_B", "REDACT_C", "REDACT_D", "REDACT_E", "REDACT_F"):
    secret = os.environ.get(key, "")
    if secret:
        text = text.replace(secret, "***")
sys.stdout.write(text[:2000])
' 2>/dev/null
  }

  bind_job() {
    LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" \
      DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_NAME="$BIND_DB" \
      DB_MASTER_USER="$BIND_ADMIN" MASTER_DB_PASSWORD="$ADMIN_PW" \
      RUNTIME_DB_URL="$RT_URL" MIGRATION_DB_URL="$MG_URL" \
      RUNTIME_USER="$1" MIGRATION_USER="$BIND_MG" APP_SCHEMA="$APP_SCHEMA" \
      python3 "$REPO_ROOT/scripts/bootstrap_db_roles.py" --bind 2>&1
  }

  db_pre="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=postgres user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM pg_database WHERE datname='"$BIND_DB"';" | tr -d '[:space:]')" || true
  [ "$db_pre" = "0" ] || fail "bind DB $BIND_DB must still be absent before fresh bind"
  log "run actual scripts/bootstrap_db_roles.py --bind as the admin to create $BIND_DB"
  set +e
  BIND_OUT="$(bind_job "$BIND_RT")"
  BIND_CODE=$?
  set -e
  [ "$BIND_CODE" -eq 0 ] || { printf '%s' "$BIND_OUT" | safe_emit >&2; fail "actual --bind failed"; }
  case "$BIND_OUT" in *"BIND COMPLETE"*) ;; *) printf '%s' "$BIND_OUT" | safe_emit >&2; fail "actual --bind missed BIND COMPLETE" ;; esac
  case "$BIND_OUT" in *"db-ensure"*) ;; *) printf '%s' "$BIND_OUT" | safe_emit >&2; fail "actual --bind missed db-ensure" ;; esac
  case "$BIND_OUT" in *"password-binding"*|*"schema-acls"*|*"runtime-grants"*|*"default-privileges"*) ;; *) printf '%s' "$BIND_OUT" | safe_emit >&2; fail "actual --bind missed phase markers" ;; esac
  case "$BIND_OUT" in *"$BIND_RT_PW"*|*"$BIND_MG_PW"*|*"$ADMIN_PW"*) fail "bind output leaked a synthetic password" ;; esac
  log "pass: actual --bind complete with no password in output"
  fresh_db_owner="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=postgres user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='"$BIND_DB"';" | tr -d '[:space:]')" || true
  [ "$fresh_db_owner" = "$BIND_ADMIN" ] || fail "fresh bind DB owner is $fresh_db_owner, expected $BIND_ADMIN"
  fresh_schema_owner="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='public';" | tr -d '[:space:]')" || true
  case "$fresh_schema_owner" in
    "$BIND_ADMIN"|"pg_database_owner") ;;
    *) fail "fresh bind schema owner is $fresh_schema_owner, expected $BIND_ADMIN or pg_database_owner" ;;
  esac
  log "pass: actual --bind created exact $BIND_DB owned by $BIND_ADMIN with schema owner $fresh_schema_owner"
  unset db_pre fresh_db_owner fresh_schema_owner

  log "repeat actual --bind for idempotence proof (existing-DB path after fresh create)"
  set +e
  REBIND_OUT="$(bind_job "$BIND_RT")"
  REBIND_CODE=$?
  set -e
  [ "$REBIND_CODE" -eq 0 ] || { printf '%s' "$REBIND_OUT" | safe_emit >&2; fail "actual --bind rerun failed"; }
  case "$REBIND_OUT" in *"BIND COMPLETE"*) ;; *) printf '%s' "$REBIND_OUT" | safe_emit >&2; fail "actual --bind rerun missed BIND COMPLETE" ;; esac
  case "$REBIND_OUT" in *"$BIND_RT_PW"*|*"$BIND_MG_PW"*|*"$ADMIN_PW"*) fail "rebind output leaked a synthetic password" ;; esac
  log "pass: actual --bind is idempotent"

  log "inspect the automatic native admin membership rows"
  for managed in "$BIND_RT" "$BIND_MG"; do
    native_row="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT target.rolname || ',' || member.rolname || ',' || grantor.rolname || ',' || m.grantor::text || ',' || grantor.rolsuper::text || ',' || m.admin_option::text || ',' || m.inherit_option::text || ',' || m.set_option::text FROM pg_auth_members m JOIN pg_roles target ON target.oid = m.roleid JOIN pg_roles member ON member.oid = m.member JOIN pg_roles grantor ON grantor.oid = m.grantor WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = '$managed') OR m.member = (SELECT oid FROM pg_roles WHERE rolname = '$managed');" | tr -d '[:space:]')" || true
    expected_row="$managed,$BIND_ADMIN,$SUPERUSER,10,true,true,false,false"
    [ "$native_row" = "$expected_row" ] || fail "native membership for $managed is [$native_row], expected [$expected_row]"
  done
  log "pass: native rows are roleid managed, member admin, grantor OID 10 ($SUPERUSER), ADMIN true SET false INHERIT false"

  pwset="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM pg_authid WHERE rolname IN ('$BIND_RT','$BIND_MG') AND rolpassword IS NOT NULL;" | tr -d '[:space:]')" || true
  [ "$pwset" = "2" ] || fail "bind did not set both role passwords"
  log "pass: both role passwords are set in the catalog"

  bind_as() {
    as_user="$1"
    as_pw="$2"
    as_sql="$3"
    PGPASSWORD="$as_pw" "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$as_user sslmode=verify-full sslrootcert=$CERTDIR/server.crt" -v ON_ERROR_STOP=1 -tAc "$as_sql"
  }

  model_checks() {
    m_label="$1"
    m_prefix="$2"
    log "model 008 $m_label: tables owned, functions secdef pinned, no PUBLIC"
    for m_tbl in model_budget model_calls; do
      m_own="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = '$APP_SCHEMA' AND c.relname = '$m_tbl';" | tr -d '[:space:]')" || true
      [ "$m_own" = "$BIND_MG" ] || fail "model $m_tbl owner is $m_own, expected $BIND_MG ($m_label)"
    done
    set +e
    MODEL_OUT="$(BIND_PORT="$PORT" BIND_DB="$BIND_DB" BIND_RT="$BIND_RT" BIND_MG="$BIND_MG" APP_SCHEMA="$APP_SCHEMA" RT_URL="$RT_URL" MG_URL="$MG_URL" CERT_FILE="$CERTDIR/server.crt" M_PREFIX="$m_prefix" python3 -c '
import hashlib
import os
import psycopg
port = int(os.environ["BIND_PORT"])
db = os.environ["BIND_DB"]
rt_name = os.environ["BIND_RT"]
mg_name = os.environ["BIND_MG"]
schema = os.environ["APP_SCHEMA"]
prefix = os.environ["M_PREFIX"]
rt_url = os.environ["RT_URL"]
mg_url = os.environ["MG_URL"]
cert = os.environ["CERT_FILE"]
admin = psycopg.connect(host="127.0.0.1", port=port, dbname=db, user="postgres", autocommit=True)
cur = admin.cursor()
cur.execute("SELECT p.proname, pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig, p.proargnames, p.proargmodes FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = %s AND p.proname LIKE %s ORDER BY p.proname", (schema, "model_%"))
rows = cur.fetchall()
names = sorted(r[0] for r in rows)
if names != ["model_finalize_call", "model_no_direct", "model_reserve_call"]:
    raise SystemExit("unexpected model functions")
cur.execute("SELECT oid FROM pg_roles WHERE rolname = %s", (rt_name,))
rt_row = cur.fetchone()
if rt_row is None:
    raise SystemExit("runtime role missing")
rt_oid = rt_row[0]
for proname, owner, secdef, proconfig, argnames, argmodes in rows:
    if owner != mg_name:
        raise SystemExit("function owner mismatch")
    cfg = list(proconfig or [])
    if proname == "model_no_direct":
        want_path = ["pg_catalog", "pg_temp"]
    elif proname in ("model_reserve_call", "model_finalize_call"):
        want_path = [schema, "pg_temp"]
    else:
        raise SystemExit("unexpected model functions")
    got_paths = []
    for v in cfg:
        s = str(v)
        if s.startswith("search_path="):
            raw = s.split("=", 1)[1]
            parts = [p.strip().strip(chr(34)).strip() for p in raw.split(",")]
            got_paths.append(parts)
    if len(got_paths) != 1 or got_paths[0] != want_path:
        raise SystemExit("search_path not pinned with pg_temp last")
    cur.execute("SELECT e.grantee, e.privilege_type FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace, LATERAL aclexplode(coalesce(p.proacl, acldefault(%s, p.proowner))) AS e WHERE n.nspname = %s AND p.proname = %s", ("f", schema, proname))
    fprivs = cur.fetchall()
    if any(int(g) == 0 and str(pt).upper() == "EXECUTE" for g, pt in fprivs):
        raise SystemExit("PUBLIC execute present")
    all_names = list(argnames or [])
    if argmodes is None:
        in_names = all_names
    else:
        modes = list(argmodes or [])
        in_names = [nm for nm, md in zip(all_names, modes) if str(md).lower() in ("i", "b", "v")]
    args = " ".join(str(v) for v in in_names).lower()
    if "amount" in args or "micros" in args or "debit" in args or "refill" in args or "grant" in args:
        raise SystemExit("function accepts a debit amount")
    if proname in ("model_reserve_call", "model_finalize_call"):
        if not secdef:
            raise SystemExit("reserve and finalize must be SECURITY DEFINER")
        if not any(int(g) == int(rt_oid) and str(pt).upper() == "EXECUTE" for g, pt in fprivs):
            raise SystemExit("runtime EXECUTE missing")
    else:
        if secdef:
            raise SystemExit("trigger guard must not be SECURITY DEFINER")
        if any(int(g) == int(rt_oid) for g, pt in fprivs):
            raise SystemExit("trigger guard must not grant runtime")
cur.execute("SELECT COUNT(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = %s AND (p.proname LIKE %s OR p.proname LIKE %s)", (schema, "%grant%", "%refill%"))
if cur.fetchone()[0] != 0:
    raise SystemExit("refill function present")
cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relname IN (%s, %s)", (schema, "model_budget", "model_calls"))
found = {}
for (relname,) in cur.fetchall():
    cur.execute("SELECT e.grantee, e.privilege_type FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, LATERAL aclexplode(coalesce(c.relacl, acldefault(%s, c.relowner))) AS e WHERE n.nspname = %s AND c.relname = %s", ("r", schema, relname))
    tprivs = cur.fetchall()
    if any(int(g) == 0 and str(pt).upper() in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER") for g, pt in tprivs):
        raise SystemExit("PUBLIC table access present")
    rt_privs = set(str(pt).upper() for g, pt in tprivs if int(g) == int(rt_oid))
    if "SELECT" not in rt_privs:
        raise SystemExit("runtime SELECT missing")
    if rt_privs.intersection(("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")):
        raise SystemExit("runtime write present")
    found[relname] = True
if set(found) != {"model_budget", "model_calls"}:
    raise SystemExit("model tables missing")
admin.close()
rt = psycopg.connect(rt_url, sslrootcert=cert, autocommit=True)
mg = psycopg.connect(mg_url, sslrootcert=cert, autocommit=True)
rc = rt.cursor()
mc = mg.cursor()
def expect_42501(fn):
    try:
        fn()
    except Exception as exc:
        if getattr(exc, "sqlstate", None) != "42501":
            raise SystemExit("expected 42501")
    else:
        raise SystemExit("direct write unexpectedly succeeded")
expect_42501(lambda: rc.execute("INSERT INTO public.model_budget(id, remaining_micros) VALUES (%s, %s)", ("other", 1)))
expect_42501(lambda: rc.execute("UPDATE public.model_budget SET remaining_micros = %s WHERE id = %s", (1, "global")))
expect_42501(lambda: rc.execute("DELETE FROM public.model_budget WHERE id = %s", ("global",)))
zero64 = "0" * 64
expect_42501(lambda: rc.execute("INSERT INTO public.model_calls(id, run_id, stage, attempt_id, request_digest, model, status, reservation_micros) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", ("mc_probe_" + prefix, prefix + "_r", "Scout", "a1", zero64, "muse-spark-1.3", "admitted", 4000000)))
expect_42501(lambda: rc.execute("UPDATE public.model_calls SET status = %s WHERE id = %s", ("succeeded", "mc_nope")))
expect_42501(lambda: rc.execute("DELETE FROM public.model_calls WHERE id = %s", ("mc_nope",)))
rc.execute("SELECT remaining_micros FROM public.model_budget WHERE id = %s", ("global",))
rc.fetchone()
rc.execute("SELECT COUNT(*) FROM public.model_calls")
rc.fetchone()
mc.execute("UPDATE public.model_budget SET remaining_micros = %s WHERE id = %s", (0, "global"))
rc.execute("SELECT remaining_micros FROM public.model_budget WHERE id = %s", ("global",))
if rc.fetchone()[0] != 0:
    raise SystemExit("zero default not preserved")
def digest(tag):
    return hashlib.sha256(tag.encode()).hexdigest()
try:
    rc.execute("SELECT * FROM public.model_reserve_call(%s, %s, %s, %s, %s, %s, %s)", (prefix + "_run0", "Scout", "a0", digest(prefix + "req0"), 2048, 1, 1024))
    rc.fetchone()
except Exception as exc:
    if getattr(exc, "sqlstate", None) == "42501":
        raise SystemExit("reserve function not executable")
    if getattr(exc, "sqlstate", None) != "P0001":
        raise SystemExit("exhausted reserve must fail closed")
else:
    raise SystemExit("exhausted reserve unexpectedly succeeded")
mc.execute("UPDATE public.model_budget SET remaining_micros = %s WHERE id = %s", (4000000, "global"))
rc.execute("SELECT * FROM public.model_reserve_call(%s, %s, %s, %s, %s, %s, %s)", (prefix + "_run1", "Scout", "a1", digest(prefix + "req1"), 2048, 1, 1024))
row1 = rc.fetchone()
if row1 is None or row1[12] is not True:
    raise SystemExit("first reserve must own")
call1 = row1[0]
if row1[5] != "muse-spark-1.3" or row1[11] != 4000000 or row1[6] != "admitted":
    raise SystemExit("fixed reservation mismatch")
rc.execute("SELECT remaining_micros FROM public.model_budget WHERE id = %s", ("global",))
if rc.fetchone()[0] != 0:
    raise SystemExit("budget not debited")
try:
    rc.execute("SELECT * FROM public.model_reserve_call(%s, %s, %s, %s, %s, %s, %s)", (prefix + "_run2", "Scout", "a1", digest(prefix + "req2"), 2048, 1, 1024))
    rc.fetchone()
except Exception as exc:
    if getattr(exc, "sqlstate", None) == "42501":
        raise SystemExit("reserve function not executable")
    if getattr(exc, "sqlstate", None) != "P0001":
        raise SystemExit("one-slot second must fail closed")
else:
    raise SystemExit("one-slot second unexpectedly succeeded")
rc.execute("SELECT * FROM public.model_reserve_call(%s, %s, %s, %s, %s, %s, %s)", (prefix + "_run1", "Scout", "a1", digest(prefix + "req1"), 2048, 1, 1024))
row_dup = rc.fetchone()
if row_dup is None or row_dup[0] != call1 or row_dup[12] is not False:
    raise SystemExit("duplicate must replay without resend")
if row_dup[6] != "admitted":
    raise SystemExit("restart must stay admitted")
try:
    rc.execute("SELECT * FROM public.model_reserve_call(%s, %s, %s, %s, %s, %s, %s)", (prefix + "_run1", "Scout", "a1", digest(prefix + "other"), 2048, 1, 1024))
    rc.fetchone()
except Exception as exc:
    if getattr(exc, "sqlstate", None) == "42501":
        raise SystemExit("reserve function not executable")
    if getattr(exc, "sqlstate", None) != "23505":
        raise SystemExit("digest mismatch must conflict")
else:
    raise SystemExit("digest mismatch unexpectedly succeeded")
rc.execute("SELECT * FROM public.model_finalize_call(%s, %s, %s, %s, %s, %s)", (call1, "ambiguous_terminal", "ambiguous:read_failed", None, None, None))
frow = rc.fetchone()
if frow is None or frow[6] != "ambiguous_terminal" or frow[12] is not False:
    raise SystemExit("ambiguous finalize failed")
rc.execute("SELECT remaining_micros FROM public.model_budget WHERE id = %s", ("global",))
if rc.fetchone()[0] != 0:
    raise SystemExit("ambiguous must not refund")
rc.execute("SELECT * FROM public.model_reserve_call(%s, %s, %s, %s, %s, %s, %s)", (prefix + "_run1", "Scout", "a1", digest(prefix + "req1"), 2048, 1, 1024))
row_amb = rc.fetchone()
if row_amb is None or row_amb[6] != "ambiguous_terminal" or row_amb[12] is not False:
    raise SystemExit("ambiguous must not resend")
mc.execute("UPDATE public.model_budget SET remaining_micros = %s WHERE id = %s", (4000000, "global"))
rc.execute("SELECT * FROM public.model_reserve_call(%s, %s, %s, %s, %s, %s, %s)", (prefix + "_run2", "Scout", "a1", digest(prefix + "req2"), 2048, 1, 1024))
row2 = rc.fetchone()
if row2 is None or row2[12] is not True:
    raise SystemExit("second slot must own after grant")
fname = "test_future_" + prefix
mc.execute("CREATE OR REPLACE FUNCTION public.%s() RETURNS INTEGER LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS %s SELECT 1 %s" % (fname, "$$", "$$"))
mc.execute("SELECT e.grantee, e.privilege_type FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace, LATERAL aclexplode(coalesce(p.proacl, acldefault(%s, p.proowner))) AS e WHERE n.nspname = %s AND p.proname = %s", ("f", "public", fname))
ffprivs = mc.fetchall()
ff_public = any(int(g) == 0 and str(pt).upper() == "EXECUTE" for g, pt in ffprivs)
ff_runtime = any(int(g) == int(rt_oid) and str(pt).upper() == "EXECUTE" for g, pt in ffprivs)
if ff_public or ff_runtime:
    mc.execute("DROP FUNCTION public.%s()" % fname)
    raise SystemExit("future function scope wrong")
mc.execute("DROP FUNCTION public.%s()" % fname)
rt.close()
mg.close()
print("model ok")
' 2>&1)"
    MODEL_CODE=$?
    set -e
    [ "$MODEL_CODE" -eq 0 ] || { printf '%s' "$MODEL_OUT" | safe_emit >&2; fail "model 008 $m_label proof failed"; }
    unset MODEL_OUT MODEL_CODE
    log "pass: model 008 $m_label direct fails 42501, functions allowed, no resend, scope ok"
  }

  log "password auth with the bound password works, a wrong one fails"
  set +e
  bind_as "$BIND_RT" "$BIND_RT_PW" "SELECT 1;" >/dev/null 2>&1
  auth_ok=$?
  bind_as "$BIND_RT" "wrong-password-for-negative-check" "SELECT 1;" >/dev/null 2>&1
  auth_bad=$?
  set -e
  [ "$auth_ok" -eq 0 ] || fail "password auth with the bound password failed"
  [ "$auth_bad" -ne 0 ] || fail "password auth accepted a wrong password"
  log "pass: bound password authenticates, wrong password is refused"

  log "alembic upgrade head via the migration role on the admin-owned DB"
  set +e
  MIG_OUT="$(cd "$REPO_ROOT" && DATABASE_URL="$MG_URL" LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" python3 -m alembic upgrade head 2>&1)"
  MIG_CODE=$?
  set -e
  [ "$MIG_CODE" -eq 0 ] || { printf '%s' "$MIG_OUT" | safe_emit >&2; fail "alembic upgrade head failed"; }
  ver="$(bind_as "$BIND_MG" "$BIND_MG_PW" "SELECT version_num FROM alembic_version;" | tr -d '[:space:]')" || true
  [ "$ver" = "008" ] || fail "alembic head is $ver, expected 008"
  alembic_owner="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = '$APP_SCHEMA' AND c.relname = 'alembic_version';" | tr -d '[:space:]')" || true
  [ "$alembic_owner" = "$BIND_MG" ] || fail "alembic owner is $alembic_owner, expected $BIND_MG"
  log "pass: alembic head 008 applied via the migration role and owned by it"

  model_checks "pre-rebind" "mpre"

  log "bind again after migration for post-object idempotence proof"
  set +e
  POSTMIG_OUT="$(bind_job "$BIND_RT")"
  POSTMIG_CODE=$?
  set -e
  [ "$POSTMIG_CODE" -eq 0 ] || { printf '%s' "$POSTMIG_OUT" | safe_emit >&2; fail "actual --bind after migration failed"; }
  case "$POSTMIG_OUT" in *"BIND COMPLETE"*) ;; *) printf '%s' "$POSTMIG_OUT" | safe_emit >&2; fail "post-migration --bind missed BIND COMPLETE" ;; esac
  case "$POSTMIG_OUT" in *"$BIND_RT_PW"*|*"$BIND_MG_PW"*|*"$ADMIN_PW"*) fail "post-migration output leaked a synthetic password" ;; esac
  log "pass: post-migration rebind succeeds with migration-owned objects present"

  model_checks "post-rebind" "mpost"

  log "outcome 008: run_outcomes owned, constrained, no workspace DEFAULT, runtime DML only"
  outcome_owner="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = '$APP_SCHEMA' AND c.relname = 'run_outcomes';" | tr -d '[:space:]')" || true
  [ "$outcome_owner" = "$BIND_MG" ] || fail "outcome run_outcomes owner is $outcome_owner, expected $BIND_MG"
  outcome_default="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT COALESCE(column_default,'') FROM information_schema.columns WHERE table_schema = '$APP_SCHEMA' AND table_name = 'run_outcomes' AND column_name = 'workspace_id';" | tr -d '[:space:]')" || true
  [ -z "$outcome_default" ] || fail "outcome workspace_id has DEFAULT $outcome_default, expected none"
  for want_constraint in run_outcomes_workspace_fkey run_outcomes_run_workspace_fkey run_outcomes_revision_non_negative run_outcomes_channel run_outcomes_likes_bounds run_outcomes_comments_bounds run_outcomes_clicks_bounds run_outcomes_sales_bounds run_outcomes_note_length run_outcomes_note_no_control run_outcomes_provenance run_outcomes_actor_signed_in; do
    found="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = '$APP_SCHEMA' AND t.relname = 'run_outcomes' AND c.conname = '$want_constraint';" | tr -d '[:space:]')" || true
    [ "$found" = "1" ] || fail "outcome constraint missing: $want_constraint"
  done
  actor_def="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = '$APP_SCHEMA' AND t.relname = 'run_outcomes' AND c.conname = 'run_outcomes_actor_signed_in';" || true)"
  case "$actor_def" in *"demo_placeholder"*) ;; *) fail "outcome actor constraint does not refuse demo_placeholder" ;; esac
  prov_def="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = '$APP_SCHEMA' AND t.relname = 'run_outcomes' AND c.conname = 'run_outcomes_provenance';" || true)"
  case "$prov_def" in *"self_reported"*) ;; *) fail "outcome provenance constraint does not require self_reported" ;; esac
  bind_as "$BIND_RT" "$BIND_RT_PW" "SELECT count(*) FROM $APP_SCHEMA.run_outcomes;" >/dev/null || fail "runtime role cannot SELECT run_outcomes"
  RT_URL="$RT_URL" CERT_FILE="$CERTDIR/server.crt" APP_SCHEMA="$APP_SCHEMA" python3 -c '
import os
import psycopg
url = os.environ["RT_URL"]
cert = os.environ["CERT_FILE"]
schema = os.environ["APP_SCHEMA"]
conn = psycopg.connect(url, sslrootcert=cert, autocommit=True)
cur = conn.cursor()
table = schema + ".run_outcomes"
for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
    cur.execute("SELECT has_table_privilege(%s, %s)", (table, priv))
    if not cur.fetchone()[0]:
        raise SystemExit("runtime %s missing on run_outcomes" % priv)
for priv in ("TRUNCATE", "REFERENCES", "TRIGGER"):
    cur.execute("SELECT has_table_privilege(%s, %s)", (table, priv))
    if cur.fetchone()[0]:
        raise SystemExit("runtime %s present on run_outcomes" % priv)
conn.close()
print("outcome grants ok")
' >/dev/null || fail "runtime DML split on run_outcomes is wrong"
  set +e
  bind_as "$BIND_RT" "$BIND_RT_PW" "ALTER TABLE $APP_SCHEMA.run_outcomes ADD COLUMN outcome_nope integer;" >/dev/null 2>&1
  outcome_ddl=$?
  set -e
  [ "$outcome_ddl" -ne 0 ] || fail "runtime role altered run_outcomes, split broken"
  log "pass: outcome 008 table owned, constrained, no DEFAULT, runtime DML only with DDL refused"
  unset outcome_owner outcome_default found want_constraint actor_def prov_def outcome_ddl

  verify_job() {
    LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" \
      DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_NAME="$BIND_DB" \
      RUNTIME_DB_URL="$RT_URL" RUNTIME_USER="$BIND_RT" MIGRATION_USER="$BIND_MG" \
      APP_SCHEMA="$APP_SCHEMA" \
      python3 "$REPO_ROOT/scripts/bootstrap_db_roles.py" --verify 2>&1
  }

  log "run actual --verify with the runtime URL only"
  set +e
  VERIFY_OUT="$(verify_job)"
  VERIFY_CODE=$?
  set -e
  [ "$VERIFY_CODE" -eq 0 ] || { printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify failed at head 008"; }
  case "$VERIFY_OUT" in *"VERIFY COMPLETE"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed VERIFY COMPLETE" ;; esac
  case "$VERIFY_OUT" in *"revision=008"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed revision=008" ;; esac
  case "$VERIFY_OUT" in *"verify-model-budget-zero ok"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed model budget proof" ;; esac
  case "$VERIFY_OUT" in *"verify-model-no-direct ok"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed model direct DML proof" ;; esac
  case "$VERIFY_OUT" in *"verify-model-functions ok"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed model function proof" ;; esac
  case "$VERIFY_OUT" in *"verify-model-owners ok"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed model owner proof" ;; esac
  case "$VERIFY_OUT" in *"verify-model-defaults ok"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed model defaults proof" ;; esac
  case "$VERIFY_OUT" in *"verify-outcome-owner ok"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed outcome owner proof" ;; esac
  case "$VERIFY_OUT" in *"verify-outcome-constraints ok"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed outcome constraints proof" ;; esac
  case "$VERIFY_OUT" in *"verify-outcome-grants ok"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed outcome grants proof" ;; esac
  case "$VERIFY_OUT" in *"$BIND_RT_PW"*|*"$RT_URL"*) fail "verify output leaked a synthetic secret" ;; esac
  log "pass: actual --verify proves 008, identity, rolled-back write, DDL refusal, model and outcome guards"

  log "bind roles repeat the CRUD and sequence split directly"
  bind_as "$BIND_MG" "$BIND_MG_PW" "CREATE TABLE $APP_SCHEMA.bind_items (id SERIAL PRIMARY KEY, note TEXT);" >/dev/null || fail "migration role cannot create"
  bind_as "$BIND_RT" "$BIND_RT_PW" "INSERT INTO $APP_SCHEMA.bind_items(note) VALUES ('bind-row-1') RETURNING id;" >/dev/null || fail "runtime role cannot insert"
  bind_as "$BIND_RT" "$BIND_RT_PW" "SELECT count(*) FROM $APP_SCHEMA.bind_items;" >/dev/null || fail "runtime role cannot select"
  bind_as "$BIND_RT" "$BIND_RT_PW" "UPDATE $APP_SCHEMA.bind_items SET note='bind-row-2' WHERE note='bind-row-1';" >/dev/null || fail "runtime role cannot update"
  bind_as "$BIND_RT" "$BIND_RT_PW" "SELECT nextval('$APP_SCHEMA.bind_items_id_seq');" >/dev/null || fail "runtime role cannot use sequences"
  bind_as "$BIND_RT" "$BIND_RT_PW" "DELETE FROM $APP_SCHEMA.bind_items WHERE note='bind-row-2';" >/dev/null || fail "runtime role cannot delete"
  set +e
  bind_as "$BIND_RT" "$BIND_RT_PW" "CREATE TABLE $APP_SCHEMA.bind_nope (id integer);" >/dev/null 2>&1
  rt_ddl=$?
  set -e
  [ "$rt_ddl" -ne 0 ] || fail "runtime role created a table, split broken"
  log "pass: runtime CRUD plus sequence use works and runtime DDL is refused"

  log "default privilege proof: late migration objects need no rebind"
  bind_as "$BIND_MG" "$BIND_MG_PW" "CREATE TABLE $APP_SCHEMA.late_items (id SERIAL PRIMARY KEY, note TEXT);" >/dev/null || fail "migration role cannot create late table"
  bind_as "$BIND_RT" "$BIND_RT_PW" "INSERT INTO $APP_SCHEMA.late_items(note) VALUES ('late-1') RETURNING id;" >/dev/null || fail "runtime role cannot use late table without rebind"
  bind_as "$BIND_RT" "$BIND_RT_PW" "SELECT nextval('$APP_SCHEMA.late_items_id_seq');" >/dev/null || fail "runtime role cannot use late sequence without rebind"
  bind_as "$BIND_MG" "$BIND_MG_PW" "DROP TABLE $APP_SCHEMA.late_items;" >/dev/null || fail "owned late table cleanup failed"
  log "pass: late objects work without rebind, then owned cleanup drops them"

  log "runtime CREATE, ALTER, and DROP each fail with exact SQLSTATE 42501"
  RT_URL="$RT_URL" CERT_FILE="$CERTDIR/server.crt" python3 -c '
import os
import psycopg
url = os.environ["RT_URL"]
cert = os.environ["CERT_FILE"]
conn = psycopg.connect(url, sslrootcert=cert, autocommit=True)
cur = conn.cursor()
checks = [
    "CREATE TABLE public.rt_42501_nope (id integer)",
    "ALTER TABLE public.bind_items ADD COLUMN rt_42501_nope integer",
    "DROP TABLE public.bind_items",
]
for stmt in checks:
    try:
        cur.execute(stmt)
    except Exception as exc:
        if getattr(exc, "sqlstate", None) != "42501":
            raise SystemExit("expected 42501, got %r" % (getattr(exc, "sqlstate", None),))
    else:
        raise SystemExit("DDL unexpectedly succeeded: %s" % stmt.split()[0])
conn.close()
print("42501 ok")
' >/dev/null || fail "runtime DDL did not fail with exact 42501"
  log "pass: runtime DDL fails with exact 42501"

  log "negative: unowned superuser role is refused, never taken over"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "CREATE ROLE lc_intruder_demo SUPERUSER LOGIN;" >/dev/null
  set +e
  INTR_OUT="$(RUNTIME_DB_URL="$INTR_URL" RUNTIME_USER=lc_intruder_demo LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" \
    DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_NAME="$BIND_DB" \
    DB_MASTER_USER="$BIND_ADMIN" MASTER_DB_PASSWORD="$ADMIN_PW" \
    MIGRATION_DB_URL="$MG_URL" \
    MIGRATION_USER="$BIND_MG" APP_SCHEMA="$APP_SCHEMA" \
    python3 "$REPO_ROOT/scripts/bootstrap_db_roles.py" --bind 2>&1)"
  INTR_CODE=$?
  set -e
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "DROP ROLE lc_intruder_demo;" >/dev/null
  [ "$INTR_CODE" -ne 0 ] || fail "bind took over an unowned superuser role"
  case "$INTR_OUT" in *"role-safety"*) ;; *) printf '%s' "$INTR_OUT" | safe_emit >&2; fail "superuser refusal missed the role-safety marker" ;; esac
  log "pass: unowned superuser refused with role-safety"

  log "negative: BYPASSRLS role is refused"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "CREATE ROLE lc_bypass_demo LOGIN BYPASSRLS;" >/dev/null
  BYPASS_URL="postgresql://lc_bypass_demo:${INTR_PW}@127.0.0.1:${PORT}/${BIND_DB}?sslmode=verify-full"
  set +e
  BYPASS_OUT="$(RUNTIME_DB_URL="$BYPASS_URL" RUNTIME_USER=lc_bypass_demo LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" \
    DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_NAME="$BIND_DB" \
    DB_MASTER_USER="$BIND_ADMIN" MASTER_DB_PASSWORD="$ADMIN_PW" \
    MIGRATION_DB_URL="$MG_URL" \
    MIGRATION_USER="$BIND_MG" APP_SCHEMA="$APP_SCHEMA" \
    python3 "$REPO_ROOT/scripts/bootstrap_db_roles.py" --bind 2>&1)"
  BYPASS_CODE=$?
  set -e
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "DROP ROLE lc_bypass_demo;" >/dev/null
  unset BYPASS_URL
  [ "$BYPASS_CODE" -ne 0 ] || fail "bind took over a BYPASSRLS role"
  case "$BYPASS_OUT" in *"BYPASSRLS"*) ;; *) printf '%s' "$BYPASS_OUT" | safe_emit >&2; fail "BYPASSRLS refusal missed the marker" ;; esac
  log "pass: BYPASSRLS refused"

  log "negative: foreign member is refused before password mutation"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "CREATE ROLE lc_intruder_member NOLOGIN; GRANT $BIND_RT TO lc_intruder_member;" >/dev/null
  pw_before_rt="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_RT';" | tr -d '[:space:]')" || true
  pw_before_mg="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_MG';" | tr -d '[:space:]')" || true
  set +e
  FOREIGN_OUT="$(bind_job "$BIND_RT" 2>&1)"
  FOREIGN_CODE=$?
  set -e
  pw_after_rt="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_RT';" | tr -d '[:space:]')" || true
  pw_after_mg="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_MG';" | tr -d '[:space:]')" || true
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "REVOKE $BIND_RT FROM lc_intruder_member; DROP ROLE lc_intruder_member;" >/dev/null
  [ "$FOREIGN_CODE" -ne 0 ] || fail "bind took over a role with a foreign member"
  case "$FOREIGN_OUT" in *"memberships"*) ;; *) printf '%s' "$FOREIGN_OUT" | safe_emit >&2; fail "foreign membership refusal missed the marker" ;; esac
  [ "$pw_before_rt" = "$pw_after_rt" ] || fail "refused bind mutated the runtime password"
  [ "$pw_before_mg" = "$pw_after_mg" ] || fail "refused bind mutated the migration password"
  unset pw_before_rt pw_before_mg pw_after_rt pw_after_mg
  set +e
  FOREIGN_FIX_OUT="$(bind_job "$BIND_RT" 2>&1)"
  FOREIGN_FIX_CODE=$?
  set -e
  [ "$FOREIGN_FIX_CODE" -eq 0 ] || { printf '%s' "$FOREIGN_FIX_OUT" | safe_emit >&2; fail "rebind failed after foreign cleanup"; }
  log "pass: foreign member refused with passwords unchanged, recovery rebind ok"

  log "negative: reverse and group memberships are refused"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "CREATE ROLE lc_group_demo NOLOGIN; GRANT lc_group_demo TO $BIND_RT;" >/dev/null
  set +e
  GRP_OUT="$(bind_job "$BIND_RT" 2>&1)"
  GRP_CODE=$?
  set -e
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "REVOKE lc_group_demo FROM $BIND_RT; DROP ROLE lc_group_demo;" >/dev/null
  [ "$GRP_CODE" -ne 0 ] || fail "bind took over a role with memberships"
  case "$GRP_OUT" in *"memberships"*) ;; *) printf '%s' "$GRP_OUT" | safe_emit >&2; fail "membership refusal missed the marker" ;; esac
  set +e
  GRP_FIX_OUT="$(bind_job "$BIND_RT" 2>&1)"
  GRP_FIX_CODE=$?
  set -e
  [ "$GRP_FIX_CODE" -eq 0 ] || { printf '%s' "$GRP_FIX_OUT" | safe_emit >&2; fail "rebind failed after group cleanup"; }
  log "pass: reverse and group memberships refused, recovery rebind ok"

  log "negative: changed membership options are refused"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "REVOKE $BIND_RT FROM $BIND_ADMIN; GRANT $BIND_RT TO $BIND_ADMIN;" >/dev/null
  set +e
  OPTS_OUT="$(bind_job "$BIND_RT" 2>&1)"
  OPTS_CODE=$?
  set -e
  [ "$OPTS_CODE" -ne 0 ] || fail "bind accepted changed membership options"
  case "$OPTS_OUT" in *"memberships"*) ;; *) printf '%s' "$OPTS_OUT" | safe_emit >&2; fail "options refusal missed the marker" ;; esac
  # Recovery must restore the exact native row. A bare REVOKE leaves zero
  # rows and the limited admin then lacks ADMIN for ALTER PASSWORD, so the
  # next bind would correctly fail at password-binding. Restore via the
  # superuser fixture with native options only, no SET or INHERIT grant.
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "REVOKE $BIND_RT FROM $BIND_ADMIN; GRANT $BIND_RT TO $BIND_ADMIN WITH ADMIN TRUE, INHERIT FALSE, SET FALSE;" >/dev/null
  opts_restored="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT target.rolname || ',' || member.rolname || ',' || grantor.rolname || ',' || m.grantor::text || ',' || grantor.rolsuper::text || ',' || m.admin_option::text || ',' || m.inherit_option::text || ',' || m.set_option::text FROM pg_auth_members m JOIN pg_roles target ON target.oid = m.roleid JOIN pg_roles member ON member.oid = m.member JOIN pg_roles grantor ON grantor.oid = m.grantor WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = '$BIND_RT') OR m.member = (SELECT oid FROM pg_roles WHERE rolname = '$BIND_RT');" | tr -d '[:space:]')" || true
  [ "$opts_restored" = "$BIND_RT,$BIND_ADMIN,$SUPERUSER,10,true,true,false,false" ] || fail "options restore is [$opts_restored], expected native row"
  unset opts_restored
  set +e
  OPTS_FIX_OUT="$(bind_job "$BIND_RT" 2>&1)"
  OPTS_FIX_CODE=$?
  set -e
  [ "$OPTS_FIX_CODE" -eq 0 ] || { printf '%s' "$OPTS_FIX_OUT" | safe_emit >&2; fail "rebind failed after options restore"; }
  log "pass: changed options refused, native row restored, recovery rebind ok"

  log "negative: foreign-owned object is refused and never transferred"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "CREATE TABLE $APP_SCHEMA.foreign_owned_demo (id integer);" >/dev/null
  own_pw_before_rt="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_RT';" | tr -d '[:space:]')" || true
  own_pw_before_mg="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_MG';" | tr -d '[:space:]')" || true
  own_acl_before="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT COALESCE(nspacl::text,'') FROM pg_namespace WHERE nspname='$APP_SCHEMA';" | tr -d '[:space:]')" || true
  set +e
  OWN_OUT="$(bind_job "$BIND_RT" 2>&1)"
  OWN_CODE=$?
  set -e
  own_pw_after_rt="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_RT';" | tr -d '[:space:]')" || true
  own_pw_after_mg="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_MG';" | tr -d '[:space:]')" || true
  own_acl_after="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT COALESCE(nspacl::text,'') FROM pg_namespace WHERE nspname='$APP_SCHEMA';" | tr -d '[:space:]')" || true
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "DROP TABLE $APP_SCHEMA.foreign_owned_demo;" >/dev/null
  [ "$OWN_CODE" -ne 0 ] || fail "bind granted over a foreign-owned object"
  case "$OWN_OUT" in *"unexpected owner"*) ;; *) printf '%s' "$OWN_OUT" | safe_emit >&2; fail "foreign owner refusal missed the marker" ;; esac
  [ "$own_pw_before_rt" = "$own_pw_after_rt" ] || fail "refused bind mutated the runtime password"
  [ "$own_pw_before_mg" = "$own_pw_after_mg" ] || fail "refused bind mutated the migration password"
  [ "$own_acl_before" = "$own_acl_after" ] || fail "refused bind mutated the schema ACL"
  unset own_pw_before_rt own_pw_before_mg own_pw_after_rt own_pw_after_mg own_acl_before own_acl_after
  set +e
  OWN_FIX_OUT="$(bind_job "$BIND_RT" 2>&1)"
  OWN_FIX_CODE=$?
  set -e
  [ "$OWN_FIX_CODE" -eq 0 ] || { printf '%s' "$OWN_FIX_OUT" | safe_emit >&2; fail "rebind failed after foreign object cleanup"; }
  log "pass: foreign-owned object refused with passwords and schema ACL unchanged, recovery rebind ok"

  log "negative: foreign-owned view is refused before password and ACL mutation"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "CREATE VIEW $APP_SCHEMA.foreign_owned_view AS SELECT 1;" >/dev/null
  view_pw_before_rt="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_RT';" | tr -d '[:space:]')" || true
  view_pw_before_mg="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_MG';" | tr -d '[:space:]')" || true
  view_acl_before="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT COALESCE(nspacl::text,'') FROM pg_namespace WHERE nspname='$APP_SCHEMA';" | tr -d '[:space:]')" || true
  set +e
  VIEW_OUT="$(bind_job "$BIND_RT" 2>&1)"
  VIEW_CODE=$?
  set -e
  view_pw_after_rt="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_RT';" | tr -d '[:space:]')" || true
  view_pw_after_mg="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='$BIND_MG';" | tr -d '[:space:]')" || true
  view_acl_after="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT COALESCE(nspacl::text,'') FROM pg_namespace WHERE nspname='$APP_SCHEMA';" | tr -d '[:space:]')" || true
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "DROP VIEW $APP_SCHEMA.foreign_owned_view;" >/dev/null
  [ "$VIEW_CODE" -ne 0 ] || fail "bind granted over a foreign-owned view"
  case "$VIEW_OUT" in *"unexpected owner"*) ;; *) printf '%s' "$VIEW_OUT" | safe_emit >&2; fail "foreign view refusal missed the marker" ;; esac
  [ "$view_pw_before_rt" = "$view_pw_after_rt" ] || fail "refused bind mutated the runtime password"
  [ "$view_pw_before_mg" = "$view_pw_after_mg" ] || fail "refused bind mutated the migration password"
  [ "$view_acl_before" = "$view_acl_after" ] || fail "refused bind mutated the schema ACL"
  unset view_pw_before_rt view_pw_before_mg view_pw_after_rt view_pw_after_mg view_acl_before view_acl_after
  set +e
  VIEW_FIX_OUT="$(bind_job "$BIND_RT" 2>&1)"
  VIEW_FIX_CODE=$?
  set -e
  [ "$VIEW_FIX_CODE" -eq 0 ] || { printf '%s' "$VIEW_FIX_OUT" | safe_emit >&2; fail "rebind failed after foreign view cleanup"; }
  log "pass: foreign-owned view refused with passwords and schema ACL unchanged, recovery rebind ok"

  # Live foreign-superuser grantor setup is impossible under PG18. Ordinary
  # superuser grants are recorded as the bootstrap superuser (OID 10), even
  # with SET ROLE to another superuser, and GRANTED BY needs ADMIN unless
  # bootstrap. See sql-grant docs and role-attributes native GRANT. The
  # isolated unit test_foreign_superuser_grantor_is_refused proves the
  # OID-only superuser tuple refusal. This live proof uses normal SQL with
  # a foreign NONsuperuser grantor chain instead. The prerequisite ADMIN
  # row may itself trigger the refusal, so this is a foreign grant chain
  # rejection, not an OID-only superuser proof.
  log "negative: foreign grant chain is refused, only OID 10 is native"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "CREATE ROLE lc_foreign_grantor NOLOGIN;" >/dev/null
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "REVOKE $BIND_RT FROM $BIND_ADMIN;" >/dev/null
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "GRANT $BIND_RT TO lc_foreign_grantor WITH ADMIN TRUE;" >/dev/null
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "SET ROLE lc_foreign_grantor; GRANT $BIND_RT TO $BIND_ADMIN WITH ADMIN TRUE, INHERIT FALSE, SET FALSE GRANTED BY lc_foreign_grantor; RESET ROLE;" >/dev/null
  chain_main="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT grantor.rolname || ',' || m.grantor::text || ',' || grantor.rolsuper::text || ',' || m.admin_option::text || ',' || m.inherit_option::text || ',' || m.set_option::text FROM pg_auth_members m JOIN pg_roles grantor ON grantor.oid = m.grantor WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = '$BIND_RT') AND m.member = (SELECT oid FROM pg_roles WHERE rolname = '$BIND_ADMIN');" | tr -d '[:space:]')" || true
  case "$chain_main" in lc_foreign_grantor,*) ;; *) fail "foreign chain fixture missed the foreign grantor: [$chain_main]" ;; esac
  case "$chain_main" in *,false,true,false,false) ;; *) fail "foreign chain fixture has wrong options: [$chain_main]" ;; esac
  case "$chain_main" in lc_foreign_grantor,10,*) fail "foreign chain fixture unexpectedly used OID 10" ;; esac
  chain_pre="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT m.admin_option::text FROM pg_auth_members m WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = '$BIND_RT') AND m.member = (SELECT oid FROM pg_roles WHERE rolname = 'lc_foreign_grantor');" | tr -d '[:space:]')" || true
  [ "$chain_pre" = "true" ] || fail "foreign chain prerequisite lacks ADMIN: [$chain_pre]"
  chain_count="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM pg_auth_members m WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = '$BIND_RT') OR m.member = (SELECT oid FROM pg_roles WHERE rolname = '$BIND_RT');" | tr -d '[:space:]')" || true
  [ "$chain_count" = "2" ] || fail "foreign chain fixture has $chain_count rows, expected 2"
  unset chain_pre chain_count
  set +e
  EVIL_OUT="$(bind_job "$BIND_RT" 2>&1)"
  EVIL_CODE=$?
  set -e
  # Grantor-aware cleanup in valid dependency order: dependent first, then
  # prerequisite, then drop, then restore the exact native row. No SET/INHERIT.
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "REVOKE $BIND_RT FROM $BIND_ADMIN GRANTED BY lc_foreign_grantor; REVOKE $BIND_RT FROM lc_foreign_grantor; DROP ROLE lc_foreign_grantor; GRANT $BIND_RT TO $BIND_ADMIN WITH ADMIN TRUE, INHERIT FALSE, SET FALSE;" >/dev/null
  unset chain_main
  [ "$EVIL_CODE" -ne 0 ] || fail "bind accepted a foreign grant chain"
  case "$EVIL_OUT" in *"memberships"*) ;; *) printf '%s' "$EVIL_OUT" | safe_emit >&2; fail "foreign chain refusal missed the marker" ;; esac
  evil_restored="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT target.rolname || ',' || member.rolname || ',' || grantor.rolname || ',' || m.grantor::text || ',' || grantor.rolsuper::text || ',' || m.admin_option::text || ',' || m.inherit_option::text || ',' || m.set_option::text FROM pg_auth_members m JOIN pg_roles target ON target.oid = m.roleid JOIN pg_roles member ON member.oid = m.member JOIN pg_roles grantor ON grantor.oid = m.grantor WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = '$BIND_RT') OR m.member = (SELECT oid FROM pg_roles WHERE rolname = '$BIND_RT');" | tr -d '[:space:]')" || true
  [ "$evil_restored" = "$BIND_RT,$BIND_ADMIN,$SUPERUSER,10,true,true,false,false" ] || fail "foreign chain restore is [$evil_restored], expected native row"
  unset evil_restored
  set +e
  EVIL_FIX_OUT="$(bind_job "$BIND_RT" 2>&1)"
  EVIL_FIX_CODE=$?
  set -e
  [ "$EVIL_FIX_CODE" -eq 0 ] || { printf '%s' "$EVIL_FIX_OUT" | safe_emit >&2; fail "rebind failed after foreign chain cleanup"; }
  log "pass: foreign grant chain refused, native row restored, recovery rebind ok"

  log "negative: historical predecessor 007 is refused by verify at 008"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "UPDATE alembic_version SET version_num='007';" >/dev/null
  set +e
  OLD_OUT="$(verify_job 2>&1)"
  OLD_CODE=$?
  set -e
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "UPDATE alembic_version SET version_num='008';" >/dev/null
  [ "$OLD_CODE" -ne 0 ] || fail "verify accepted the historical head 007"
  case "$OLD_OUT" in *"FAIL"*) ;; *) printf '%s' "$OLD_OUT" | safe_emit >&2; fail "old head refusal left no FAIL marker" ;; esac
  set +e
  AGAIN_OUT="$(verify_job 2>&1)"
  AGAIN_CODE=$?
  set -e
  [ "$AGAIN_CODE" -eq 0 ] || { printf '%s' "$AGAIN_OUT" | safe_emit >&2; fail "verify failed after restoring head 008"; }
  log "pass: historical 007 refused, restored 008 proves again"

  log "run actual --verify-role-state with both URLs, no master, under NOSUPERUSER admin"
  role_state_job() {
    LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" \
      DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_NAME="$BIND_DB" \
      DB_MASTER_USER="$BIND_ADMIN" \
      RUNTIME_DB_URL="$RT_URL" MIGRATION_DB_URL="$MG_URL" \
      RUNTIME_USER="$BIND_RT" MIGRATION_USER="$BIND_MG" \
      APP_SCHEMA="$APP_SCHEMA" \
      python3 "$REPO_ROOT/scripts/bootstrap_db_roles.py" --verify-role-state 2>&1
  }
  set +e
  RS_OUT="$(role_state_job)"
  RS_CODE=$?
  set -e
  [ "$RS_CODE" -eq 0 ] || { printf '%s' "$RS_OUT" | safe_emit >&2; fail "actual --verify-role-state failed at head 008"; }
  case "$RS_OUT" in *"ROLE-STATE COMPLETE"*) ;; *) printf '%s' "$RS_OUT" | safe_emit >&2; fail "role-state missed ROLE-STATE COMPLETE" ;; esac
  case "$RS_OUT" in *"head=008"*) ;; *) printf '%s' "$RS_OUT" | safe_emit >&2; fail "role-state missed head=008" ;; esac
  case "$RS_OUT" in *"role-state-runtime-connect ok"*) ;; *) printf '%s' "$RS_OUT" | safe_emit >&2; fail "role-state missed runtime connect proof" ;; esac
  case "$RS_OUT" in *"role-state-migration-connect ok"*) ;; *) printf '%s' "$RS_OUT" | safe_emit >&2; fail "role-state missed migration connect proof" ;; esac
  case "$RS_OUT" in *"role-state-ownership ok"*) ;; *) printf '%s' "$RS_OUT" | safe_emit >&2; fail "role-state missed ownership proof" ;; esac
  case "$RS_OUT" in *"role-state-grants ok"*) ;; *) printf '%s' "$RS_OUT" | safe_emit >&2; fail "role-state missed grants proof" ;; esac
  case "$RS_OUT" in *"role-state-schema-props ok"*) ;; *) printf '%s' "$RS_OUT" | safe_emit >&2; fail "role-state missed schema-props proof" ;; esac
  case "$RS_OUT" in *"$BIND_RT_PW"*|*"$BIND_MG_PW"*|*"$RT_URL"*|*"$MG_URL"*) fail "role-state output leaked a synthetic secret" ;; esac
  log "pass: actual --verify-role-state proves both auths, flags, ownership, grants at 008 with no master"

  log "negative: partial grants are refused by role-state, then restored"
  bind_as "$BIND_MG" "$BIND_MG_PW" "REVOKE INSERT ON $APP_SCHEMA.bind_items FROM \"$BIND_RT\";" >/dev/null || fail "partial revoke setup failed"
  set +e
  RS_PART_OUT="$(role_state_job 2>&1)"
  RS_PART_CODE=$?
  set -e
  bind_as "$BIND_MG" "$BIND_MG_PW" "GRANT INSERT ON $APP_SCHEMA.bind_items TO \"$BIND_RT\";" >/dev/null || fail "partial grant restore failed"
  [ "$RS_PART_CODE" -ne 0 ] || fail "role-state accepted partial grants"
  case "$RS_PART_OUT" in *"FAIL"*) ;; *) printf '%s' "$RS_PART_OUT" | safe_emit >&2; fail "partial refusal left no FAIL marker" ;; esac
  case "$RS_PART_OUT" in *"role-state-table-grant"*) ;; *) printf '%s' "$RS_PART_OUT" | safe_emit >&2; fail "partial refusal missed table-grant marker" ;; esac
  set +e
  RS_RESTORE_OUT="$(role_state_job 2>&1)"
  RS_RESTORE_CODE=$?
  set -e
  [ "$RS_RESTORE_CODE" -eq 0 ] || { printf '%s' "$RS_RESTORE_OUT" | safe_emit >&2; fail "role-state failed after grant restore"; }
  log "pass: partial grants refused with FAIL, restored grants prove again"

  log "head007 ready path: downgrade to 007 returns 10, upgrade restores 008"
  set +e
  DOWN_OUT="$(cd "$REPO_ROOT" && DATABASE_URL="$MG_URL" LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" python3 -m alembic downgrade -1 2>&1)"
  DOWN_CODE=$?
  set -e
  [ "$DOWN_CODE" -eq 0 ] || { printf '%s' "$DOWN_OUT" | safe_emit >&2; fail "alembic downgrade to 007 failed"; }
  ver007="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT version_num FROM alembic_version;" | tr -d '[:space:]')" || true
  [ "$ver007" = "007" ] || fail "downgrade head is $ver007, expected 007"
  outcome_gone="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = '$APP_SCHEMA' AND c.relname = 'run_outcomes';" | tr -d '[:space:]')" || true
  [ "$outcome_gone" = "0" ] || fail "run_outcomes still present at head 007, expected exactly one 008 migration"
  set +e
  RS007_OUT="$(role_state_job 2>&1)"
  RS007_CODE=$?
  set -e
  [ "$RS007_CODE" -eq 10 ] || { printf '%s' "$RS007_OUT" | safe_emit >&2; fail "role-state at head 007 returned $RS007_CODE, expected 10"; }
  case "$RS007_OUT" in *"head=007"*) ;; *) printf '%s' "$RS007_OUT" | safe_emit >&2; fail "role-state 007 missed head=007" ;; esac
  set +e
  UP_OUT="$(cd "$REPO_ROOT" && DATABASE_URL="$MG_URL" LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" python3 -m alembic upgrade head 2>&1)"
  UP_CODE=$?
  set -e
  [ "$UP_CODE" -eq 0 ] || { printf '%s' "$UP_OUT" | safe_emit >&2; fail "alembic upgrade back to 008 failed"; }
  set +e
  RS008_OUT="$(role_state_job 2>&1)"
  RS008_CODE=$?
  set -e
  [ "$RS008_CODE" -eq 0 ] || { printf '%s' "$RS008_OUT" | safe_emit >&2; fail "role-state failed after restoring head 008"; }
  log "pass: head007 returns 10 ready, restored 008 returns 0"

  bind_as "$BIND_MG" "$BIND_MG_PW" "DROP TABLE $APP_SCHEMA.bind_items;" >/dev/null || fail "owned bind table cleanup failed"
  unset ADMIN_PW BIND_RT_PW BIND_MG_PW INTR_PW RT_URL MG_URL INTR_URL
  unset BIND_OUT VERIFY_OUT MIG_OUT INTR_OUT BYPASS_OUT FOREIGN_OUT FOREIGN_FIX_OUT GRP_OUT GRP_FIX_OUT OPTS_OUT OPTS_FIX_OUT OWN_OUT OWN_FIX_OUT VIEW_OUT VIEW_FIX_OUT EVIL_OUT EVIL_FIX_OUT OLD_OUT AGAIN_OUT REBIND_OUT POSTMIG_OUT RS_OUT RS_PART_OUT RS_RESTORE_OUT RS007_OUT RS008_OUT DOWN_OUT UP_OUT
  log "PASS: bind and verify job proof complete on disposable 127.0.0.1:$PORT"
  log "loopback self-signed CA only, NOT live RDS TLS proof"
  log "admin fixture proves binder logic only, NOT RDS identity proof"
}

bind_verify_live
