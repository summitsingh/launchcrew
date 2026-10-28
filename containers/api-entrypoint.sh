#!/bin/sh
# LaunchCrew API container entrypoint, deployment separation only.
# Runtime tasks must never run migrations. Migration is a separate task
# using containers/migrate.Containerfile, with its own IAM role.
# Certificate injection, actually implemented, not assumed:
# - If TLS_CERT_B64 and TLS_KEY_B64 are set, from Secrets Manager via
#   ECS task secrets, decode them to /tmp/tls/cert.pem and
#   /tmp/tls/key.pem, mode 600, without logging any certificate, key,
#   or secret value, and without logging the base64 values themselves,
#   then use those files. The decoded files live only in the task
#   container, they are never baked into the image.
# - Else, if TLS_CERT_FILE and TLS_KEY_FILE are set to existing files,
#   use those files directly, for local TLS tests.
# - Else, if LAUNCHCREW_REQUIRE_CONTAINER_TLS=1, exit 1, fail closed.
# - Else, plain HTTP on port 8000, local development only, never for
#   a public deployment.
# - If only one file, or only one base64 variable, is set, exit 1.
# Dry run, for local validation only:
# - If LAUNCHCREW_ENTRYPOINT_DRY_RUN=1, print the uvicorn command
#   instead of execing it, then delete any files decoded in dry-run
#   mode, so no certificate material is left behind by a test.
set -eu
DRY_RUN="${LAUNCHCREW_ENTRYPOINT_DRY_RUN:-0}"
DECODED_IN_DRY_RUN=0
if [ -n "${TLS_CERT_B64:-}" ] && [ -n "${TLS_KEY_B64:-}" ]; then
  mkdir -p /tmp/tls
  chmod 700 /tmp/tls
  printf '%s' "$TLS_CERT_B64" | base64 -d > /tmp/tls/cert.pem
  printf '%s' "$TLS_KEY_B64" | base64 -d > /tmp/tls/key.pem
  chmod 600 /tmp/tls/cert.pem /tmp/tls/key.pem
  TLS_CERT_FILE=/tmp/tls/cert.pem
  TLS_KEY_FILE=/tmp/tls/key.pem
  unset TLS_CERT_B64 TLS_KEY_B64
  if [ "$DRY_RUN" = "1" ]; then
    DECODED_IN_DRY_RUN=1
  fi
fi
CERT_FILE="${TLS_CERT_FILE:-}"
KEY_FILE="${TLS_KEY_FILE:-}"
REQUIRE_TLS="${LAUNCHCREW_REQUIRE_CONTAINER_TLS:-0}"
cleanup_dry_run() {
  if [ "$DECODED_IN_DRY_RUN" = "1" ]; then
    rm -f /tmp/tls/cert.pem /tmp/tls/key.pem
  fi
}
if [ -n "${TLS_CERT_B64:-}" ] || [ -n "${TLS_KEY_B64:-}" ]; then
  cleanup_dry_run
  echo "api-entrypoint: only one of TLS_CERT_B64 and TLS_KEY_B64 is set" >&2
  exit 1
fi
if [ -n "$CERT_FILE" ] && [ -n "$KEY_FILE" ]; then
  if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    cleanup_dry_run
    echo "api-entrypoint: TLS cert or key file missing" >&2
    exit 1
  fi
  if [ "$DRY_RUN" = "1" ]; then
    echo "/opt/venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8443 --no-access-log --ssl-certfile $CERT_FILE --ssl-keyfile $KEY_FILE"
    cleanup_dry_run
    exit 0
  fi
  exec /opt/venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8443 --no-access-log --ssl-certfile "$CERT_FILE" --ssl-keyfile "$KEY_FILE"
fi
if [ -n "$CERT_FILE" ] || [ -n "$KEY_FILE" ]; then
  cleanup_dry_run
  echo "api-entrypoint: only one of TLS_CERT_FILE and TLS_KEY_FILE is set" >&2
  exit 1
fi
if [ "$REQUIRE_TLS" = "1" ]; then
  cleanup_dry_run
  echo "api-entrypoint: container TLS is required but no cert or key file is present" >&2
  exit 1
fi
if [ "$DRY_RUN" = "1" ]; then
  echo "/opt/venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --no-access-log"
  exit 0
fi
exec /opt/venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --no-access-log
