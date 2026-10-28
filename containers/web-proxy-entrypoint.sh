#!/bin/sh
# LaunchCrew web TLS proxy entrypoint, sidecar container only.
# Decodes Secrets Manager certificate material, supplied as base64
# environment variables TLS_CERT_B64 and TLS_KEY_B64, to files in
# /tmp/tls, with mode 600, without logging any certificate, key, or
# secret value, and without logging the base64 values themselves.
# If TLS_CERT_FILE and TLS_KEY_FILE are already set to existing files,
# those files are used directly, and the base64 variables are ignored.
# If neither a file pair nor a base64 pair is present, exit 1, fail
# closed, do not start a plain HTTP proxy. The proxy then serves TLS
# on port 8443, proxying only to http://127.0.0.1:3000, see tls-proxy.mjs.
set -eu
if [ -n "${TLS_CERT_FILE:-}" ] && [ -n "${TLS_KEY_FILE:-}" ]; then
  if [ ! -f "$TLS_CERT_FILE" ] || [ ! -f "$TLS_KEY_FILE" ]; then
    echo "web-proxy-entrypoint: TLS cert or key file missing" >&2
    exit 1
  fi
elif [ -n "${TLS_CERT_B64:-}" ] && [ -n "${TLS_KEY_B64:-}" ]; then
  mkdir -p /tmp/tls
  chmod 700 /tmp/tls
  printf '%s' "$TLS_CERT_B64" | base64 -d > /tmp/tls/cert.pem
  printf '%s' "$TLS_KEY_B64" | base64 -d > /tmp/tls/key.pem
  chmod 600 /tmp/tls/cert.pem /tmp/tls/key.pem
  export TLS_CERT_FILE=/tmp/tls/cert.pem
  export TLS_KEY_FILE=/tmp/tls/key.pem
  unset TLS_CERT_B64 TLS_KEY_B64
else
  echo "web-proxy-entrypoint: no TLS cert/key file pair and no base64 pair present" >&2
  exit 1
fi
exec node /app/tls-proxy.mjs
