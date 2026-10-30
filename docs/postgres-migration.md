# Postgres ownership and migration

The new FastAPI stack uses SQLAlchemy with the psycopg driver. Alembic revisions 001 through 007 are the active chain with head 007_voice_profile. db/001_init.sql is retained as the recovered partial schema for provenance, explicitly superseded. Startup never runs that SQL file or creates tables implicitly. Run `uv run alembic upgrade head` before starting the API. The API container performs this migration before serving. Revision 007 widens the memory_items kind CHECK to exactly the four preexisting kinds plus voice_profile; its downgrade refuses while any voice_profile row exists.

New runs live in Postgres. The adapter imports launchcrew.run, launchcrew.agents, and launchcrew.receipts and passes a capture callback to the existing pipeline. It does not write new receipts under runs/. Temporary profile and export serialization files are short-lived, inside .local, and never authoritative. Preview validates the profile without files or model calls. Existing pipeline behavior, claim normalization, substring checks, allowlist, unverified fact exclusion, Checker revisions, and receipt export gates remain in the existing modules.

## Table mapping

| Existing demo material | New table and representation |
| --- | --- |
| agents/*.json | agents.profile JSONB, keyed by normalized name |
| runs/*.json receipt | runs.receipt JSONB, id from run_id, state from approval_state |
| receipt.scout.facts_used | memory.facts JSONB, keyed by run_id |
| receipt.approvals | approvals with run_id, approved_by, approved_at |
| receipt.audit.event_log | audit action rows for new mutations; historical events remain within receipt JSONB |
| New OAuth transient state and user identity | auth_sessions, hashed opaque id and expiry; no provider tokens |

Old JSON files remain untouched. No historical import was performed. To import them later, validate each receipt and agent, retain its original id and timestamps, insert runs and memory in one transaction, and insert approvals only for receipts that already passed an explicit human approval gate. Do not treat a legacy CLI demo_human simulation as authenticated approval. Tag imported audit events as historical rather than manufacturing new human actions. Back up the database and dry-run an import before any writes. On a database created by the partial SQL file, compare all columns and constraints with revision 001 first; do not stamp or migrate it blindly. The verified database in this run started empty.

## Transactions and queries

Run creation writes receipt, memory, and audit in one transaction. Profile edits include audit in the same transaction. Approval locks one run FOR UPDATE, applies the preserved receipt gate, writes one approval protected by its primary key, updates the receipt, and appends audit atomically. Duplicate and concurrent approvals cannot both succeed. Export locks the run, validates through the preserved export function, and appends audit before returning the pack. An export audit records preparation of the response, not proof the client saved the download.

The queue orders pending first, then created_at and id. runs_queue indexes state, created_at, id; audit_run_time indexes run_id, created_at, id. auth_sessions_expiry supports expiry cleanup. An operator may periodically delete expired sessions; no queue service was added. The JSON receipt retains the complete pipeline event log, while audit records API actions with an actor. Demo mode records demo_placeholder. Auth mode records the verified provider subject, not provider tokens or the full user profile.
