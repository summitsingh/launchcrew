FROM docker.io/library/postgres:17-alpine
USER postgres
EXPOSE 5432
HEALTHCHECK --interval=5s --timeout=3s CMD pg_isready -U postgres -d launchcrew
