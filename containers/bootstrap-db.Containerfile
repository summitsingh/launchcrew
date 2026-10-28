FROM ghcr.io/astral-sh/uv:0.11.32 AS uv
FROM docker.io/library/python:3.14-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && useradd --uid 10001 --create-home crew && mkdir .local && chown crew:crew .local
# Deploy-only SDK for prereq provisioning (Phase B). Pinned boto3 plus
# cryptography with hashes, installed with pip --require-hashes in this
# image only. Core app UV deps unchanged. This reuses the existing
# bootstrap image with no new ECR repo; Phase C adds task definitions
# that override the command to run populate_prereqs.py --populate or
# --verify-material on this same image.
COPY containers/bootstrap-deploy-requirements.lock /tmp/bootstrap-deploy-requirements.lock
RUN /opt/venv/bin/pip install --require-hashes -r /tmp/bootstrap-deploy-requirements.lock \
 && rm /tmp/bootstrap-deploy-requirements.lock
# Public RDS CA bundle for verified database TLS. No private key material here.
# scripts/bootstrap_db_roles.py requires DATABASE_SSL_ROOTCERT to point at an
# existing CA bundle file with LAUNCHCREW_DB_TLS_MODE=verify-full, and the
# Fargate bootstrap task definition sets that variable to
# /app/rds-ca-bundle.pem. The bundle is the official regional Amazon RDS
# us-east-1 trust bundle (self-issued Amazon RDS us-east-1 Root CA RSA2048 G1,
# RSA4096 G1, and ECC384 G1 roots), vendored from
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
COPY scripts/bootstrap_db_roles.py /app/scripts/bootstrap_db_roles.py
COPY scripts/populate_prereqs.py /app/scripts/populate_prereqs.py
USER 10001:10001
# Bootstrap database-role task only by default. No server is started here,
# alembic is never run here, and this image never receives runtime traffic.
# This image is used by the isolated one-off bootstrap task, with its own
# least privilege IAM role, to bind database role passwords from injected
# Secrets Manager values held in process memory only. Phase B adds the
# memory-only prereq provisioner on this same image with no new repo;
# Phase C task definitions override the command to run populate_prereqs.py
# --populate or --verify-material. Migration stays the only schema change
# path in containers/migrate.Containerfile, and runtime tasks use
# containers/api.Containerfile, which must never run alembic or role binds.
ENTRYPOINT ["/opt/venv/bin/python", "/app/scripts/bootstrap_db_roles.py"]
CMD ["--bind"]
