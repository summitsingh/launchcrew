#!/bin/sh
# LaunchCrew API container entrypoint, deployment separation only.
# Runtime tasks must never run migrations. Migration is a separate task
# using containers/migrate.Containerfile, with its own IAM role.
# TLS, fail-closed when required:
# - If LAUNCHCREW_REQUIRE_CONTAINER_TLS=1, TLS_CERT_FILE and TLS_KEY_FILE
#   must both exist, otherwise this script exits 1 and the task fails.
# - If both files exist, uvicorn serves TLS on port 8443, for an ALB
#   HTTPS target group. Certificates are mounted at task start from
#   Secrets Manager, they are never baked into the image, and no
#   certificate path or value is logged here.
# - If neither file exists and TLS is not required, uvicorn serves
#   plain HTTP on port 8000, for local development only. That mode
#   must never be used for a public deployment.
# - If only one file exists, exit 1, do not start with a half TLS config.
# Dry run, for local validation only:
# - If LAUNCHCREW_ENTRYPOINT_DRY_RUN=1, print the uvicorn command
#   instead of execing it, so the TLS selection logic can be tested
#   without starting a server or touching a database.
set -eu
CERT_FILE="${TLS_CERT_FILE:-}"
KEY_FILE="${TLS_KEY_FILE:-}"
REQUIRE_TLS="${LAUNCHCREW_REQUIRE_CONTAINER_TLS:-0}"
if [ -n "$CERT_FILE" ] && [ -n "$KEY_FILE" ]; then
  if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "api-entrypoint: TLS cert or key file missing" >&2
    exit 1
  fi
  if [ "${LAUNCHCREW_ENTRYPOINT_DRY_RUN:-0}" = "1" ]; then
    echo "/opt/venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8443 --no-access-log --ssl-certfile $CERT_FILE --ssl-keyfile $KEY_FILE"
    exit 0
  fi
  exec /opt/venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8443 --no-access-log --ssl-certfile "$CERT_FILE" --ssl-keyfile "$KEY_FILE"
fi
if [ -n "$CERT_FILE" ] || [ -n "$KEY_FILE" ]; then
  echo "api-entrypoint: only one of TLS_CERT_FILE and TLS_KEY_FILE is set" >&2
  exit 1
fi
if [ "$REQUIRE_TLS" = "1" ]; then
  echo "api-entrypoint: container TLS is required but no cert or key file is present" >&2
  exit 1
fi
if [ "${LAUNCHCREW_ENTRYPOINT_DRY_RUN:-0}" = "1" ]; then
  echo "/opt/venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --no-access-log"
  exit 0
fi
exec /opt/venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --no-access-log
