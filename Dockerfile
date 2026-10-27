FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8765 LAUNCHCREW_HOST=0.0.0.0
WORKDIR /app
RUN groupadd --gid 10001 launchcrew && useradd --uid 10001 --gid 10001 --no-create-home launchcrew
COPY --chown=10001:10001 launchcrew/ ./launchcrew/
COPY --chown=10001:10001 agents/ ./agents/
COPY --chown=10001:10001 facts/ ./facts/
RUN mkdir runs && chown 10001:10001 runs
USER 10001:10001
EXPOSE 8765
CMD ["python3", "-m", "launchcrew.web"]
