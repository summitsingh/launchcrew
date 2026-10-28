FROM ghcr.io/astral-sh/uv:0.11.32 AS uv
FROM docker.io/library/python:3.14-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && useradd --uid 10001 --create-home crew && mkdir .local && chown crew:crew .local
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
