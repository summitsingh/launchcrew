FROM ghcr.io/astral-sh/uv:0.11.32 AS uv
FROM docker.io/library/python:3.14-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && useradd --uid 10001 --create-home crew && mkdir .local && chown crew:crew .local
# Public RDS CA bundle for verified database TLS. No private key material here.
# backend/store.py requires DATABASE_SSL_ROOTCERT to point at an existing CA
# bundle file when LAUNCHCREW_DB_TLS_MODE=verify-full, and the Fargate
# migration task definition sets that variable to /app/rds-ca-bundle.pem.
# The bundle is the official regional Amazon RDS us-east-1 trust bundle
# (self-issued Amazon RDS us-east-1 Root CA RSA2048 G1, RSA4096 G1, and
# ECC384 G1 roots), vendored from
# https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem
# and copied byte-for-byte below. It is NOT the Debian ca-certificates trust
# store and NOT the Amazon Trust Services web PKI roots: those do not sign
# RDS certificates. The Debian ca-certificates package is still installed so
# the OS trust store stays available for ordinary outbound HTTPS; it is never
# substituted for the RDS bundle. See docs/db-ca-bundle.md for provenance,
# checksum, rotation, and region scope. The file is world-readable on purpose:
# it holds only public roots, never a private key.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY backend/assets/rds-us-east-1-bundle.pem /app/rds-ca-bundle.pem
ARG RDS_CA_SHA256=b1711d12bae51838581281e23b6cb97b1074016873b4dafc80ed14002462dd77
RUN echo "$RDS_CA_SHA256  /app/rds-ca-bundle.pem" | sha256sum -c - \
 && chmod 644 /app/rds-ca-bundle.pem
COPY launchcrew ./launchcrew
COPY backend ./backend
COPY agents ./agents
COPY facts ./facts
COPY alembic.ini ./
USER 10001:10001
# Migration task only. No server is started here. This image is used
# by a separate Fargate one-off task, with its own IAM migration role.
# Runtime API tasks use containers/api.Containerfile, which must never
# run alembic. Migration and runtime database identities are separate,
# and runtime roles have no DDL. Database TLS is enforced in
# backend/store.py for non-local URLs, see that file.
CMD ["/opt/venv/bin/alembic", "upgrade", "head"]
