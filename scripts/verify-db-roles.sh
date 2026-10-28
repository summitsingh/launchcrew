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
  head_expected="$(grep -E "^revision = " "$REPO_ROOT/backend/migrations/versions/004_run_steps.py" | cut -d"'" -f2)" || true
  head_script="$(grep -E "^EXPECTED_HEAD = " "$REPO_ROOT/scripts/bootstrap_db_roles.py" | cut -d'"' -f2)" || true
  [ -n "$head_expected" ] || fail "migration head unreadable, no invented pass"
  [ "$head_expected" = "$head_script" ] || fail "EXPECTED_HEAD $head_script does not match migration head $head_expected"

  BIND_DB="lc_bind_db"
  BIND_RT="lc_bind_runtime"
  BIND_MG="lc_bind_migration"
  log "create disposable bind database $BIND_DB"
  "$PG_BIN_DIR/createdb" -h 127.0.0.1 -p "$PORT" -U "$SUPERUSER" "$BIND_DB"

  # Fresh bind identities stay absent here on purpose. The actual
  # scripts/bootstrap_db_roles.py --bind below creates each role, stamps
  # the ownership marker, binds its password, and applies the privilege
  # split. Precreating the roles with db-roles.sql would leave them
  # without the ownership marker, and the hardened bind correctly
  # refuses such unowned roles, so no precreate or blind takeover
  # happens in this stage. Stage 1 above already proves db-roles.sql.

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

  HBA="$PGDATA/pg_hba.conf"
  {
    echo "host $BIND_DB $BIND_RT 127.0.0.1/32 scram-sha-256"
    echo "host $BIND_DB $BIND_MG 127.0.0.1/32 scram-sha-256"
    cat "$HBA"
  } >"$HBA.new" || fail "could not stage password-auth pg_hba"
  mv "$HBA.new" "$HBA" || fail "could not install password-auth pg_hba"
  "$PG_BIN_DIR/pg_ctl" -D "$PGDATA" -w reload
  log "bind roles use password auth, everything else keeps trust auth"

  BIND_RT_PW="$(python3 -c 'import secrets; print(secrets.token_hex(18))')"
  BIND_MG_PW="$(python3 -c 'import secrets; print(secrets.token_hex(18))')"
  MASTER_PW="$(python3 -c 'import secrets; print(secrets.token_hex(18))')"
  INTR_PW="$(python3 -c 'import secrets; print(secrets.token_hex(18))')"
  [ "${#BIND_RT_PW}" -ge 32 ] || fail "synthetic password generation failed"
  RT_URL="postgresql://${BIND_RT}:${BIND_RT_PW}@127.0.0.1:${PORT}/${BIND_DB}?sslmode=verify-full"
  MG_URL="postgresql://${BIND_MG}:${BIND_MG_PW}@127.0.0.1:${PORT}/${BIND_DB}?sslmode=verify-full"
  INTR_URL="postgresql://lc_intruder_demo:${INTR_PW}@127.0.0.1:${PORT}/${BIND_DB}?sslmode=verify-full"

  safe_emit() {
    # Bounded redacted error output for stage 2 failures. Secrets arrive
    # via env and text arrives via stdin, so no secret value ever appears
    # in argv. Output is truncated to 2000 bytes. Harness only, no values.
    REDACT_A="$BIND_RT_PW" REDACT_B="$BIND_MG_PW" REDACT_C="$MASTER_PW" REDACT_D="$INTR_PW" \
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
      DB_MASTER_USER="$SUPERUSER" MASTER_DB_PASSWORD="$MASTER_PW" \
      RUNTIME_DB_URL="$RT_URL" MIGRATION_DB_URL="$MG_URL" \
      RUNTIME_USER="$1" MIGRATION_USER="$BIND_MG" APP_SCHEMA="$APP_SCHEMA" \
      python3 "$REPO_ROOT/scripts/bootstrap_db_roles.py" --bind 2>&1
  }

  log "run actual scripts/bootstrap_db_roles.py --bind"
  set +e
  BIND_OUT="$(bind_job "$BIND_RT")"
  BIND_CODE=$?
  set -e
  [ "$BIND_CODE" -eq 0 ] || { printf '%s' "$BIND_OUT" | safe_emit >&2; fail "actual --bind failed"; }
  case "$BIND_OUT" in *"BIND COMPLETE"*) ;; *) printf '%s' "$BIND_OUT" | safe_emit >&2; fail "actual --bind missed BIND COMPLETE" ;; esac
  case "$BIND_OUT" in *"$BIND_RT_PW"*|*"$BIND_MG_PW"*|*"$MASTER_PW"*) fail "bind output leaked a synthetic password" ;; esac
  log "pass: actual --bind complete with no password in output"

  log "repeat actual --bind for idempotence proof"
  set +e
  REBIND_OUT="$(bind_job "$BIND_RT")"
  REBIND_CODE=$?
  set -e
  [ "$REBIND_CODE" -eq 0 ] || { printf '%s' "$REBIND_OUT" | safe_emit >&2; fail "actual --bind rerun failed"; }
  case "$REBIND_OUT" in *"BIND COMPLETE"*) ;; *) printf '%s' "$REBIND_OUT" | safe_emit >&2; fail "actual --bind rerun missed BIND COMPLETE" ;; esac
  case "$REBIND_OUT" in *"$BIND_RT_PW"*|*"$BIND_MG_PW"*|*"$MASTER_PW"*) fail "rebind output leaked a synthetic password" ;; esac
  log "pass: actual --bind is idempotent"

  pwset="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM pg_authid WHERE rolname IN ('$BIND_RT','$BIND_MG') AND rolpassword IS NOT NULL;" | tr -d '[:space:]')" || true
  [ "$pwset" = "2" ] || fail "bind did not set both role passwords"
  log "pass: both role passwords are set in the catalog"

  bind_as() {
    as_user="$1"
    as_pw="$2"
    as_sql="$3"
    PGPASSWORD="$as_pw" "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$as_user sslmode=verify-full sslrootcert=$CERTDIR/server.crt" -v ON_ERROR_STOP=1 -tAc "$as_sql"
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

  log "alembic upgrade head via the migration role"
  set +e
  MIG_OUT="$(cd "$REPO_ROOT" && DATABASE_URL="$MG_URL" LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" python3 -m alembic upgrade head 2>&1)"
  MIG_CODE=$?
  set -e
  [ "$MIG_CODE" -eq 0 ] || { printf '%s' "$MIG_OUT" | safe_emit >&2; fail "alembic upgrade head failed"; }
  ver="$(bind_as "$BIND_MG" "$BIND_MG_PW" "SELECT version_num FROM alembic_version;" | tr -d '[:space:]')" || true
  [ "$ver" = "004" ] || fail "alembic head is $ver, expected 004"
  log "pass: alembic head 004 applied via the migration role"

  verify_job() {
    LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" \
      DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_NAME="$BIND_DB" \
      RUNTIME_DB_URL="$RT_URL" RUNTIME_USER="$BIND_RT" APP_SCHEMA="$APP_SCHEMA" \
      python3 "$REPO_ROOT/scripts/bootstrap_db_roles.py" --verify 2>&1
  }

  log "run actual --verify with the runtime URL only"
  set +e
  VERIFY_OUT="$(verify_job)"
  VERIFY_CODE=$?
  set -e
  [ "$VERIFY_CODE" -eq 0 ] || { printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify failed at head 004"; }
  case "$VERIFY_OUT" in *"VERIFY COMPLETE"*|*"revision=004"*) ;; *) printf '%s' "$VERIFY_OUT" | safe_emit >&2; fail "actual --verify missed proof markers" ;; esac
  case "$VERIFY_OUT" in *"$BIND_RT_PW"*|*"$RT_URL"*) fail "verify output leaked a synthetic secret" ;; esac
  log "pass: actual --verify proves 004, identity, rolled-back write, DDL refusal"

  log "bind roles repeat the CRUD and DDL split directly"
  bind_as "$BIND_MG" "$BIND_MG_PW" "CREATE TABLE $APP_SCHEMA.bind_items (id SERIAL PRIMARY KEY, note TEXT);" >/dev/null || fail "migration role cannot create"
  bind_as "$BIND_RT" "$BIND_RT_PW" "INSERT INTO $APP_SCHEMA.bind_items(note) VALUES ('bind-row-1') RETURNING id;" >/dev/null || fail "runtime role cannot insert"
  bind_as "$BIND_RT" "$BIND_RT_PW" "SELECT count(*) FROM $APP_SCHEMA.bind_items;" >/dev/null || fail "runtime role cannot select"
  set +e
  bind_as "$BIND_RT" "$BIND_RT_PW" "CREATE TABLE $APP_SCHEMA.bind_nope (id integer);" >/dev/null 2>&1
  rt_ddl=$?
  set -e
  [ "$rt_ddl" -ne 0 ] || fail "runtime role created a table, split broken"
  log "pass: runtime CRUD works and runtime DDL is refused"

  log "negative: unowned superuser role is refused, never taken over"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "CREATE ROLE lc_intruder_demo SUPERUSER LOGIN;" >/dev/null
  set +e
  INTR_OUT="$(RUNTIME_DB_URL="$INTR_URL" RUNTIME_USER=lc_intruder_demo LAUNCHCREW_DB_TLS_MODE=verify-full DATABASE_SSL_ROOTCERT="$CERTDIR/server.crt" \
    DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_NAME="$BIND_DB" \
    DB_MASTER_USER="$SUPERUSER" MASTER_DB_PASSWORD="$MASTER_PW" \
    MIGRATION_DB_URL="$MG_URL" \
    MIGRATION_USER="$BIND_MG" APP_SCHEMA="$APP_SCHEMA" \
    python3 "$REPO_ROOT/scripts/bootstrap_db_roles.py" --bind 2>&1)"
  INTR_CODE=$?
  set -e
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "DROP ROLE lc_intruder_demo;" >/dev/null
  [ "$INTR_CODE" -ne 0 ] || fail "bind took over an unowned superuser role"
  case "$INTR_OUT" in *"role-safety"*) ;; *) printf '%s' "$INTR_OUT" | safe_emit >&2; fail "superuser refusal missed the role-safety marker" ;; esac
  log "pass: unowned superuser refused with role-safety"

  log "negative: membership takeover is refused"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "CREATE ROLE lc_group_demo NOLOGIN; GRANT lc_group_demo TO $BIND_RT;" >/dev/null
  set +e
  GRP_OUT="$(bind_job "$BIND_RT" 2>&1)"
  GRP_CODE=$?
  set -e
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "REVOKE lc_group_demo FROM $BIND_RT; DROP ROLE lc_group_demo;" >/dev/null
  [ "$GRP_CODE" -ne 0 ] || fail "bind took over a role with memberships"
  case "$GRP_OUT" in *"memberships"*) ;; *) printf '%s' "$GRP_OUT" | safe_emit >&2; fail "membership refusal missed the marker" ;; esac
  log "pass: membership takeover refused"

  log "negative: wrong head is refused by verify"
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "UPDATE alembic_version SET version_num='003';" >/dev/null
  set +e
  OLD_OUT="$(verify_job 2>&1)"
  OLD_CODE=$?
  set -e
  "$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=$BIND_DB user=$SUPERUSER" -v ON_ERROR_STOP=1 -qAc "UPDATE alembic_version SET version_num='004';" >/dev/null
  [ "$OLD_CODE" -ne 0 ] || fail "verify accepted the old head 003"
  case "$OLD_OUT" in *"FAIL"*) ;; *) printf '%s' "$OLD_OUT" | safe_emit >&2; fail "old head refusal left no FAIL marker" ;; esac
  set +e
  AGAIN_OUT="$(verify_job 2>&1)"
  AGAIN_CODE=$?
  set -e
  [ "$AGAIN_CODE" -eq 0 ] || { printf '%s' "$AGAIN_OUT" | safe_emit >&2; fail "verify failed after restoring head 004"; }
  log "pass: old head refused, restored head proves again"

  unset BIND_RT_PW BIND_MG_PW MASTER_PW INTR_PW RT_URL MG_URL INTR_URL
  unset BIND_OUT VERIFY_OUT MIG_OUT INTR_OUT GRP_OUT OLD_OUT AGAIN_OUT REBIND_OUT
  log "PASS: bind and verify job proof complete on disposable 127.0.0.1:$PORT"
  log "loopback self-signed CA only, NOT live RDS TLS proof"
}

bind_verify_live
