#!/usr/bin/env bash
# Podman only. Keep image storage in the checkout, but runroot under 50 chars:
# .local/run/containers is 45 chars locally and 61 on the GitHub runner.
# A stable per-user /tmp path stays short across build/up/check/down calls.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .local/run
chmod 700 .local/run
export XDG_RUNTIME_DIR="$PWD/.local/run"
export CONTAINERS_CONF="$PWD/containers/podman.conf"
runroot="/tmp/launchcrew-run-$(id -u)"
if [[ -L "$runroot" || ( -e "$runroot" && ! -O "$runroot" ) ]]; then
  echo 'Podman runroot must be owned by the current user and not a symlink' >&2
  exit 1
fi
mkdir -p -m 700 "$runroot"
chmod 700 "$runroot"
podman_args=(--root "$PWD/.local/podman" --runroot "$runroot" --storage-driver vfs)
p() { podman "${podman_args[@]}" "$@"; }
case "${1:-up}" in
  build)
    p build --format oci -f containers/db.Containerfile -t localhost/launchcrew-db:demo .
    p build --format oci -f containers/api.Containerfile -t localhost/launchcrew-api:demo .
    p build --format oci -f containers/web.Containerfile -t localhost/launchcrew-web:demo .
    ;;
  up)
    p pod create --name launchcrew-stack --network slirp4netns -p 127.0.0.1:8001:8000 -p 127.0.0.1:3001:3000
    p volume exists launchcrew-stack-data || p volume create launchcrew-stack-data
    p run -d --name launchcrew-stack-db --pod launchcrew-stack -e POSTGRES_DB=launchcrew -e POSTGRES_HOST_AUTH_METHOD=trust -v launchcrew-stack-data:/var/lib/postgresql/data:U localhost/launchcrew-db:demo
    for attempt in {1..60}; do
      if p exec launchcrew-stack-db pg_isready -U postgres -d launchcrew; then break; fi
      sleep 1
    done
    p exec launchcrew-stack-db pg_isready -U postgres -d launchcrew
    p run -d --name launchcrew-api --pod launchcrew-stack -e DATABASE_URL=postgresql://postgres@127.0.0.1:5432/launchcrew -e AUTH_ENABLED=false -e PUBLIC_BASE_URL=http://127.0.0.1:3001 localhost/launchcrew-api:demo
    for attempt in {1..60}; do
      if curl -fsS http://127.0.0.1:8001/api/health; then break; fi
      sleep 1
    done
    curl -fsS http://127.0.0.1:8001/api/health
    p run -d --name launchcrew-web --pod launchcrew-stack localhost/launchcrew-web:demo
    for attempt in {1..60}; do
      if curl -fsS http://127.0.0.1:3001/api/health; then break; fi
      sleep 1
    done
    curl -fsS http://127.0.0.1:3001/api/health
    ;;
  check)
    p exec launchcrew-stack-db pg_isready -U postgres -d launchcrew
    curl -fsS -o /dev/null -w 'API HTTP %{http_code}\n' http://127.0.0.1:8001/api/health
    curl -fsS -o /dev/null -w 'WEB HTTP %{http_code}\n' http://127.0.0.1:3001/
    curl -fsS -o /dev/null -w 'WEB API HTTP %{http_code}\n' http://127.0.0.1:3001/api/health
    ;;
  down)
    p pod rm -f launchcrew-stack
    # Keep named volume and local images for coordinator verification.
    ;;
  *) echo 'Usage: scripts/podman-local.sh build|up|check|down' >&2; exit 2 ;;
esac
