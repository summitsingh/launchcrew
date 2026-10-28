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

log "PASS: db-roles verification complete on disposable 127.0.0.1:$PORT"
