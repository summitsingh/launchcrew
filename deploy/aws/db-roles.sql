-- LaunchCrew demo database roles, separated privileges, not just IAM names.
-- Run this once, with the master database user, before runtime or
-- migration tasks start, in a separately authorized provisioning run.
-- No password is in this file. Passwords are supplied via Secrets
-- Manager, one secret per database identity, and are never committed.
-- Variables, supplied by the provisioning run, not by this file:
--   :runtime_user, :migration_user, :app_schema
-- Example, psql only in a provisioning run, not here:
--   psql "host=... dbname=launchcrew user=master sslmode=verify-full" \
--     -v runtime_user=launchcrew_runtime \
--     -v migration_user=launchcrew_migration \
--     -v app_schema=public -f deploy/aws/db-roles.sql
-- PostgreSQL table privileges are only SELECT, INSERT, UPDATE, DELETE,
-- TRUNCATE, REFERENCES, and TRIGGER. ALTER and DROP are not table
-- privileges and must never appear in a GRANT or REVOKE ON TABLES line.
-- DDL control comes from schema CREATE rights, table ownership, and
-- default privileges, not from table privilege keywords.
-- The migration identity is the identity that creates the tables,
-- because only the separate migration task runs alembic. Default
-- privileges below are therefore FOR ROLE :migration_user, so tables
-- and sequences created later by migration runs carry the same grants.
-- Runtime identity: required DML plus usage and sequence rights only.
-- No DDL, no CREATE, no ownership, no TRUNCATE, no REFERENCES, no
-- TRIGGER. It can read and write demo rows and use sequences for
-- generated ids, it cannot change the schema, and it cannot create
-- objects in the schema.
REVOKE CREATE ON SCHEMA :app_schema FROM PUBLIC;
-- Both roles exist before any ALTER DEFAULT PRIVILEGES line references them.
CREATE ROLE :runtime_user LOGIN;
CREATE ROLE :migration_user LOGIN;
GRANT USAGE ON SCHEMA :app_schema TO :runtime_user;
REVOKE CREATE ON SCHEMA :app_schema FROM :runtime_user;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA :app_schema FROM :runtime_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA :app_schema TO :runtime_user;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA :app_schema FROM :runtime_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA :app_schema TO :runtime_user;
ALTER DEFAULT PRIVILEGES FOR ROLE :migration_user IN SCHEMA :app_schema GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :runtime_user;
ALTER DEFAULT PRIVILEGES FOR ROLE :migration_user IN SCHEMA :app_schema GRANT USAGE, SELECT ON SEQUENCES TO :runtime_user;
-- Migration identity: schema DDL plus full row and sequence rights,
-- for schema changes only. It owns the tables it creates through
-- alembic, which is the only schema change path. It is used only by
-- the separate migration task, never by runtime tasks, and runtime
-- tasks must not use this identity or its secret.
GRANT USAGE, CREATE ON SCHEMA :app_schema TO :migration_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA :app_schema TO :migration_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA :app_schema TO :migration_user;
-- Verify, in the provisioning run, against a disposable PostgreSQL
-- instance, with \du and \dp, plus a runtime-user attempt to CREATE
-- TABLE, ALTER TABLE, and DROP TABLE, each of which must fail, and a
-- migration-user attempt to CREATE TABLE, ALTER TABLE, and DROP TABLE,
-- each of which must succeed in a disposable test schema only.
-- Do not run the verification CREATE TABLE in the production demo
-- schema, use a disposable test schema, and drop it after verification.
-- Verification status: PENDING independent verification. No disposable
-- database run has been performed for this revision in this CLI, and no
-- result is claimed here. Codex runs it independently.
