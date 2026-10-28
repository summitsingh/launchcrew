#!/usr/bin/env bash
# LaunchCrew release candidate verification, combined backend plus contract.
# Backend only is the default. All mode adds frontend and browser when
# pinned dependencies are present. No result is manufactured. Frontend
# and browser stay pending when dependencies are unavailable.
# Disposable PostgreSQL only: temp PGDATA, loopback 127.0.0.1 only,
# nondefault port, trap cleanup, no persistent service, no existing DB.
# Usage:
#   scripts/verify-release-candidate.sh --backend-only
#   scripts/verify-release-candidate.sh --all
# Env:
#   PG_BIN=/opt/homebrew/opt/postgresql@18/bin
#   PG_CANDIDATE_PORT=55433 (optional nondefault loopback port)
#   LC_API_PORT=8021 LC_WEB_PORT=3021 (all mode only, never 8001 or 3001)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DB="lc_candidate_backend"
PLAYWRIGHT_DB="lc_candidate_playwright"
SUPERUSER="postgres"

log() { echo "[verify-candidate] $1"; }
fail() { echo "[verify-candidate] FAIL: $1" >&2; exit 1; }
usage() {
  echo "Usage: scripts/verify-release-candidate.sh [--backend-only|--all|--help]"
  echo "Default is --backend-only."
}

MODE="backend-only"
for arg in ${1+"$@"}; do
  case "$arg" in
    --backend-only) MODE="backend-only" ;;
    --all) MODE="all" ;;
    --help|-h) usage; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

check_pins() {
  grep -q 'fastapi==0.135.4' "$REPO_ROOT/pyproject.toml" || fail "FastAPI pin 0.135.4 missing"
  grep -q 'starlette==1.3.1' "$REPO_ROOT/pyproject.toml" || fail "Starlette pin 1.3.1 missing"
  grep -q '"next": "15.5.28"' "$REPO_ROOT/web/package.json" || fail "Next pin 15.5.28 missing"
  log "pins pass: FastAPI 0.135.4, Starlette 1.3.1, Next 15.5.28"
}

find_pg_bin() {
  if [ -n "${PG_BIN:-}" ]; then
    [ -d "$PG_BIN" ] || fail "PG_BIN is not a directory: $PG_BIN"
    echo "$PG_BIN"
    return 0
  fi
  if command -v brew >/dev/null 2>&1; then
    brew_prefix="$(brew --prefix postgresql@18 2>/dev/null || true)"
    if [ -n "$brew_prefix" ] && [ -x "$brew_prefix/bin/initdb" ]; then
      echo "$brew_prefix/bin"
      return 0
    fi
  fi
  for dir in /opt/homebrew/opt/postgresql@18/bin /usr/local/opt/postgresql@18/bin; do
    if [ -x "$dir/initdb" ] && [ -x "$dir/pg_ctl" ] && [ -x "$dir/psql" ]; then
      echo "$dir"
      return 0
    fi
  done
  fail "PostgreSQL 18 binaries not found. Set PG_BIN to the postgresql@18 bin dir."
}

check_pg18() {
  version="$("$1/psql" --version 2>/dev/null || true)"
  log "psql version: $version"
  case "$version" in *" 18."*) ;; *) fail "PostgreSQL 18 is required, found: $version" ;; esac
}

pick_pg_port() {
  requested="${PG_CANDIDATE_PORT:-${PG_VERIFY_PORT:-}}"
  if [ -n "$requested" ]; then
    case "$requested" in ''|*[!0-9]*) fail "PG_CANDIDATE_PORT must be numeric" ;; esac
    [ "$requested" = "5432" ] && fail "PG_CANDIDATE_PORT must be nondefault, not 5432"
    echo "$requested"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    free_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])' 2>/dev/null || true)"
    if [ -n "$free_port" ] && [ "$free_port" != "5432" ]; then
      echo "$free_port"
      return 0
    fi
  fi
  echo "55433"
}

validate_candidate_ports() {
  api_port="$1"
  web_port="$2"
  pg_port="$3"
  for candidate in "$api_port" "$web_port"; do
    case "$candidate" in ''|*[!0-9]*) fail "candidate web/API port must be numeric, found: $candidate" ;; esac
  done
  [ "$api_port" = "$web_port" ] && fail "LC_API_PORT ($api_port) and LC_WEB_PORT ($web_port) must differ"
  for reserved in 3000 3001 8000 8001 5432; do
    [ "$api_port" = "$reserved" ] && fail "LC_API_PORT must avoid reserved port $reserved"
    [ "$web_port" = "$reserved" ] && fail "LC_WEB_PORT must avoid reserved port $reserved"
  done
  if [ -n "$pg_port" ]; then
    [ "$api_port" = "$pg_port" ] && fail "LC_API_PORT ($api_port) conflicts with disposable Postgres port $pg_port"
    [ "$web_port" = "$pg_port" ] && fail "LC_WEB_PORT ($web_port) conflicts with disposable Postgres port $pg_port"
  fi
  if command -v python3 >/dev/null 2>&1; then
    for candidate in "$api_port" "$web_port"; do
      if ! python3 -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1]))) != 0 else 1)" "$candidate" 2>/dev/null; then
        fail "port 127.0.0.1:$candidate is already in use, choose a free LC_API_PORT/LC_WEB_PORT"
      fi
    done
  fi
}

preserve_server_logs() {
  artifact_dir="$REPO_ROOT/.local/verify-candidate-logs"
  mkdir -p "$artifact_dir" 2>/dev/null || return 0
  if [ -n "${PG_ROOT:-}" ] && [ -d "$PG_ROOT" ]; then
    for name in api.log web.log postgres.log; do
      if [ -f "$PG_ROOT/$name" ]; then
        cp "$PG_ROOT/$name" "$artifact_dir/verify-candidate-$name" 2>/dev/null || true
      fi
    done
    log "server logs preserved in $artifact_dir before temp cleanup"
  fi
}

check_pins
bash -n "$SCRIPT_DIR/verify-release-candidate.sh"
log "static: bash -n pass"

API_PORT="${LC_API_PORT:-8021}"
WEB_PORT="${LC_WEB_PORT:-3021}"
[ "$API_PORT" = "8001" ] && fail "LC_API_PORT must not be 8001"
[ "$WEB_PORT" = "3001" ] && fail "LC_WEB_PORT must not be 3001"
EXPECTED_API_URL="http://127.0.0.1:$API_PORT"
log "candidate web/API ports: API 127.0.0.1:$API_PORT web 127.0.0.1:$WEB_PORT (rewrites bake API_URL at build)"

validate_candidate_ports "$API_PORT" "$WEB_PORT" ""
PG_BIN_DIR="$(find_pg_bin)"
check_pg18 "$PG_BIN_DIR"
PORT="$(pick_pg_port)"
[ "$PORT" = "5432" ] && fail "refusing default port 5432"
validate_candidate_ports "$API_PORT" "$WEB_PORT" "$PORT"
log "using PG_BIN=$PG_BIN_DIR port=$PORT loopback 127.0.0.1 only"

PG_ROOT="$(mktemp -d /tmp/launchcrew-candidate-pg-XXXXXX)"
PGDATA="$PG_ROOT/data"
SOCKDIR="$PG_ROOT/sock"
LOGFILE="$PG_ROOT/postgres.log"
mkdir -p "$SOCKDIR"
chmod 700 "$PG_ROOT" "$SOCKDIR"
API_PID=""
WEB_PID=""

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then preserve_server_logs; fi
  if [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then kill "$API_PID" 2>/dev/null || true; fi
  if [ -n "$WEB_PID" ] && kill -0 "$WEB_PID" 2>/dev/null; then kill "$WEB_PID" 2>/dev/null || true; fi
  if [ -n "${PGDATA:-}" ] && [ -d "$PGDATA" ] && [ -x "${PG_BIN_DIR:-}/pg_ctl" ]; then
    "$PG_BIN_DIR/pg_ctl" -D "$PGDATA" -m fast stop >/dev/null 2>&1 || true
  fi
  if [ -n "${PG_ROOT:-}" ] && [ -d "$PG_ROOT" ]; then rm -rf "$PG_ROOT"; fi
}
trap cleanup EXIT INT TERM

log "initdb disposable cluster in $PGDATA"
"$PG_BIN_DIR/initdb" -D "$PGDATA" -U "$SUPERUSER" --auth=trust -E UTF8 >/dev/null
log "start postgres on 127.0.0.1:$PORT"
"$PG_BIN_DIR/pg_ctl" -D "$PGDATA" -l "$LOGFILE" -o "-h 127.0.0.1 -p $PORT -k $SOCKDIR -c listen_addresses='127.0.0.1'" -w start

ready=0
for _ in $(seq 1 30); do
  if "$PG_BIN_DIR/pg_isready" -h 127.0.0.1 -p "$PORT" -U "$SUPERUSER" >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = "1" ] || fail "postgres did not become ready; see $LOGFILE"

listen="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=postgres user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SHOW listen_addresses;" | tr -d '[:space:]')"
shown_port="$("$PG_BIN_DIR/psql" "host=127.0.0.1 port=$PORT dbname=postgres user=$SUPERUSER" -v ON_ERROR_STOP=1 -tAc "SHOW port;" | tr -d '[:space:]')"
[ "$listen" = "127.0.0.1" ] || [ "$listen" = "localhost" ] || fail "refusing non-loopback listen_addresses: $listen"
[ "$shown_port" != "5432" ] && [ "$shown_port" = "$PORT" ] || fail "refusing unexpected port: $shown_port"
log "listening on $listen:$shown_port (loopback, nondefault)"

"$PG_BIN_DIR/createdb" -h 127.0.0.1 -p "$PORT" -U "$SUPERUSER" "$BACKEND_DB"
log "created disposable database $BACKEND_DB"

cd "$REPO_ROOT"
mkdir -p .local/uv-cache
export UV_CACHE_DIR="$REPO_ROOT/.local/uv-cache"

USE_UV=0
if command -v uv >/dev/null 2>&1 && [ -f "$REPO_ROOT/uv.lock" ]; then USE_UV=1; fi
if [ "$USE_UV" = "1" ]; then
  log "uv sync --frozen"
  uv sync --frozen || fail "uv sync failed"
  PY_RUN=(uv run --frozen python)
  PYTEST_RUN=(uv run --frozen pytest)
  ALEMBIC_RUN=(uv run --frozen alembic)
else
  if [ -x "$REPO_ROOT/.venv/bin/python" ]; then PY_BIN="$REPO_ROOT/.venv/bin/python"
  else PY_BIN="python3"; fi
  PY_RUN=("$PY_BIN")
  PYTEST_RUN=("$PY_BIN" -m pytest)
  ALEMBIC_RUN=("$PY_BIN" -m alembic)
fi
log "python runner: ${PY_RUN[*]}"

export DATABASE_URL="postgresql://$SUPERUSER@127.0.0.1:$PORT/$BACKEND_DB"
export AUTH_ENABLED="false"
unset LAUNCHCREW_DB_TLS_MODE 2>/dev/null || true

log "run combined backend pytest"
set +e
"${PYTEST_RUN[@]}" -q --disable-warnings 2>&1 | tail -n 20
PYTEST_STATUS=${PIPESTATUS[0]}
set -e
[ "$PYTEST_STATUS" -eq 0 ] || fail "backend pytest failed with exit $PYTEST_STATUS"
log "backend pytest exit 0"

log "run original unittest suite"
set +e
"${PY_RUN[@]}" -m unittest discover -s tests 2>&1 | tail -n 10
UNITTEST_STATUS=${PIPESTATUS[0]}
set -e
[ "$UNITTEST_STATUS" -eq 0 ] || fail "unittest suite failed with exit $UNITTEST_STATUS"
log "unittest exit 0"

log "contract regeneration check"
set +e
"${PY_RUN[@]}" -m scripts.generate_client >/dev/null 2>&1
GEN_STATUS=$?
set -e
[ "$GEN_STATUS" -eq 0 ] || fail "contract regeneration failed with exit $GEN_STATUS"
PATH_COUNT="$("${PY_RUN[@]}" -c 'import json; print(len(json.load(open("backend/openapi.json")).get("paths", {})))')"
log "contract paths: $PATH_COUNT"
git diff --exit-code -- backend/openapi.json >/dev/null 2>&1 || fail "backend/openapi.json differs after regeneration"
log "contract clean: backend/openapi.json has no diff"

if [ "$MODE" = "backend-only" ]; then
  log "PASS: backend-only verification complete on disposable 127.0.0.1:$PORT"
  log "frontend: pending (not requested in backend-only mode)"
  log "browser: pending (not requested in backend-only mode)"
  exit 0
fi

log "all mode: frontend gates, pending when pinned dependencies are unavailable"
if ! command -v node >/dev/null 2>&1; then
  log "frontend: pending (node unavailable)"
  log "browser: pending (node unavailable)"
  log "PASS: backend complete on disposable 127.0.0.1:$PORT; frontend and browser pending"
  exit 0
fi
if ! command -v pnpm >/dev/null 2>&1; then
  log "frontend: pending (pnpm unavailable)"
  log "browser: pending (pnpm unavailable)"
  log "PASS: backend complete on disposable 127.0.0.1:$PORT; frontend and browser pending"
  exit 0
fi
if [ ! -d "$REPO_ROOT/web/node_modules" ]; then
  log "pnpm install --frozen-lockfile"
  set +e
  pnpm --dir web install --frozen-lockfile 2>&1 | tail -n 5
  INSTALL_STATUS=${PIPESTATUS[0]}
  set -e
  if [ "$INSTALL_STATUS" -ne 0 ]; then
    log "frontend: pending (pnpm install exit $INSTALL_STATUS, dependencies unavailable)"
    log "browser: pending (pnpm install exit $INSTALL_STATUS, dependencies unavailable)"
    log "PASS: backend complete on disposable 127.0.0.1:$PORT; frontend and browser pending"
    exit 0
  fi
fi

set +e
pnpm --dir web test 2>&1 | tail -n 10
VITEST_STATUS=${PIPESTATUS[0]}
set -e
[ "$VITEST_STATUS" -eq 0 ] || fail "frontend Vitest failed with exit $VITEST_STATUS"
log "frontend Vitest exit 0"

set +e
pnpm --dir web typecheck 2>&1 | tail -n 5
TSC_STATUS=${PIPESTATUS[0]}
set -e
[ "$TSC_STATUS" -eq 0 ] || fail "frontend typecheck failed with exit $TSC_STATUS"
log "frontend typecheck exit 0"

validate_candidate_ports "$API_PORT" "$WEB_PORT" "$PORT"
set +e
API_URL="$EXPECTED_API_URL" pnpm --dir web build 2>&1 | tail -n 10
BUILD_STATUS=${PIPESTATUS[0]}
set -e
[ "$BUILD_STATUS" -eq 0 ] || fail "frontend build failed with exit $BUILD_STATUS"
log "frontend build exit 0 with API_URL=$EXPECTED_API_URL (rewrites baked)"

if ! pnpm --dir web exec playwright --version >/dev/null 2>&1; then
  log "browser: pending (playwright unavailable)"
  log "PASS: backend and frontend complete; browser pending"
  exit 0
fi

validate_candidate_ports "$API_PORT" "$WEB_PORT" "$PORT"
"$PG_BIN_DIR/createdb" -h 127.0.0.1 -p "$PORT" -U "$SUPERUSER" "$PLAYWRIGHT_DB"
PW_URL="postgresql://$SUPERUSER@127.0.0.1:$PORT/$PLAYWRIGHT_DB"
log "created disposable playwright database $PLAYWRIGHT_DB"
set +e
DATABASE_URL="$PW_URL" "${ALEMBIC_RUN[@]}" upgrade head >/dev/null 2>&1
MIG_STATUS=$?
set -e
[ "$MIG_STATUS" -eq 0 ] || fail "playwright alembic upgrade failed with exit $MIG_STATUS"

log "no live model calls: META_API_KEY empty, AUTH_ENABLED false, deterministic gates only"
DATABASE_URL="$PW_URL" AUTH_ENABLED=false META_API_KEY="" nohup "${PY_RUN[@]}" -m uvicorn backend.app:app --host 127.0.0.1 --port "$API_PORT" >"$PG_ROOT/api.log" 2>&1 &
API_PID=$!
API_URL="$EXPECTED_API_URL" PORT="$WEB_PORT" nohup pnpm --dir web exec next start --hostname 127.0.0.1 --port "$WEB_PORT" >"$PG_ROOT/web.log" 2>&1 &
WEB_PID=$!
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1 && curl -fsS "http://127.0.0.1:$WEB_PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null || { preserve_server_logs; fail "API did not become ready on 127.0.0.1:$API_PORT"; }
curl -fsS "http://127.0.0.1:$WEB_PORT/api/health" >/dev/null || { preserve_server_logs; fail "web did not become ready on 127.0.0.1:$WEB_PORT (expected API_URL=$EXPECTED_API_URL baked at build)"; }
log "servers ready: API 127.0.0.1:$API_PORT web 127.0.0.1:$WEB_PORT with API_URL=$EXPECTED_API_URL"

set +e
WEB_URL="http://127.0.0.1:$WEB_PORT" DATABASE_URL="$PW_URL" pnpm --dir web test:e2e -- tests/e2e/integration-acceptance.spec.ts tests/e2e/stage-selection.spec.ts 2>&1 | tail -n 15
ACCEPT_STATUS=${PIPESTATUS[0]}
set -e
[ "$ACCEPT_STATUS" -eq 0 ] || { preserve_server_logs; fail "integration acceptance Playwright failed with exit $ACCEPT_STATUS"; }
log "integration acceptance plus stage-selection Playwright exit 0"

set +e
WEB_URL="http://127.0.0.1:$WEB_PORT" DATABASE_URL="$PW_URL" pnpm --dir web test:e2e -- tests/e2e/review.spec.ts 2>&1 | tail -n 15
VIEWPORT_STATUS=${PIPESTATUS[0]}
set -e
[ "$VIEWPORT_STATUS" -eq 0 ] || fail "viewport Playwright failed with exit $VIEWPORT_STATUS"
log "viewport Playwright exit 0"

log "PASS: all verification complete on disposable 127.0.0.1:$PORT"
