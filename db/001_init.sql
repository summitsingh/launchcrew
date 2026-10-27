-- Historical partial schema only. Superseded by Alembic revision 001.
-- Do not execute this file for new databases. See docs/postgres-migration.md.
CREATE TABLE IF NOT EXISTS agents (
 name text PRIMARY KEY, profile jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS runs (
 id text PRIMARY KEY, receipt jsonb NOT NULL,
 agent_name text NOT NULL REFERENCES agents(name),
 state text NOT NULL CHECK(state IN ('pending_approval','approved_for_export')),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS approvals (
 run_id text PRIMARY KEY REFERENCES runs(id), approved_by text NOT NULL,
 approved_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS memory (
 run_id text PRIMARY KEY REFERENCES runs(id), facts jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id text REFERENCES runs(id), action text NOT NULL,
 actor text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS runs_queue ON runs(state, created_at, id);
CREATE INDEX IF NOT EXISTS audit_run_time ON audit(run_id, created_at, id);
