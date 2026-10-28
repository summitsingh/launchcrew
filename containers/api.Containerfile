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
COPY containers/api-entrypoint.sh /usr/local/bin/api-entrypoint.sh
USER 10001:10001
EXPOSE 8000 8443
CMD ["/usr/local/bin/api-entrypoint.sh"]
