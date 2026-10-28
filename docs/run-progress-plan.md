# Incremental stage receipts: architecture plan

Date: 2026-10-28. Sole author: Muse Code CLI on release-candidate main.
Constraint: no Redis, no cloud, no new paid APIs, no new model calls.
Compat: keep `POST /api/runs` synchronous and every existing test green.

## Decision

Polling over short transactions, no SSE, no worker process.

- `POST /api/runs` stays synchronous and completed-only (legacy clients,
  Campaign weeks, all existing tests). It keeps calling
  `adapter.execute` directly.
- New `POST /api/runs/async` creates a pending run fast (one short
  transaction: pending receipt plus an `accepted` step row), returns
  `202` with the pending receipt, and starts one daemon worker thread
  in the API process that runs the real pipeline.
- New `GET /api/runs/{id}/steps` returns stored step rows in sequence
  order. The Desk polls steps every 2 seconds and the receipt every
  3 seconds. Polling is read-only and never starts work.
- Core stays stdlib-only: `run_pipeline` accepts two optional callables,
  `progress(stage, state, profile, evidence)` and `stage_gate(stage)`,
  both defaulting to None. The backend supplies a progress sink that
  writes one `run_steps` row per real stage boundary in its own short
  transaction. `stage_gate` exists only for the barrier test.
- New migration `004_run_steps.py` creates table `run_steps`
  (run_id FK, seq, stage, state, observed_at, profile, evidence JSONB).
  No change to `runs`: the pending row stores an honest pending receipt
  (`status: running`, empty drafts, `approval_state: pending_approval`)
  that no approval/export gate accepts.

## Stage vocabulary (fixed, matches pipeline order)

`accepted`, `scout`, `maker_draft_v1`, `checker_v1`, `maker_draft_v2`,
`checker_v2`, `receipt`, plus terminal `failed`. Each row carries the
server-observed timestamp, the bound run id, the stage profile name, and
sanitized evidence only (counts, blocked counts, fact/risk/draft sizes).
Never raw provider payloads, prompts, or keys. Each completed pipeline
stage shares one clock reading and profile between its stored step row
and the receipt `event_log` entry for the same observed completion;
started notes keep their own earlier readings, and the prepared receipt
audit entry stays distinct from the stored terminal row (prepared vs
committed). The terminal transaction writes the finished step row and
the final receipt together, so success is never claimed before the DB
commit. A failed outcome persists the pipeline's original failed receipt
with its actual stopped stage, exactly one failed step row, and a
`run_failed` audit; no `receipt` completed row and no `run_completed`
audit are written for failures.

## Guards

- Approve/revise/export/photo-check on a running receipt return 409
  with an explicit "still running" reason; failed receipts refuse with
  409/422 and offer no approval or export.
- At most one live worker per run id: claim and thread start happen
  under one lock, so concurrent starters serialize and only the first
  starts. Public creation mints a fresh id per POST and never restarts;
  GET polling never starts or restarts work. A sequential private start
  after a finished worker is explicit, never automatic recovery.
- The run row and its `accepted` step row commit in one transaction: a
  journal failure rolls the whole accept back before any worker starts.
  A step row that cannot be persisted mid-run raises a bounded journal
  error that stops the pipeline with an honest failed receipt; later
  inference never runs blind after required journal loss, and the
  failed receipt keeps the known completed stage audit. No provider
  work is retried and no new queue is introduced.
- Polls, reconnects, and navigation never call the provider and never
  restart work. Ambiguous terminal persistence (the finalize transaction
  cannot be confirmed) leaves the stored receipt as it is: a still
  running receipt with no live worker is reported as unconfirmed, with
  a best-effort bounded-type audit marker and no params or receipt
  contents. A possibly committed success is never overwritten with a
  synthetic failure; the UI says the result is unknown and offers
  reload, never silent retry. No raw thread tracebacks escape: errors
  are reduced to bounded type names.
- Host restart loses in-flight workers by design (no supervisor). A
  `running` receipt older than its steps is evidence of
  accepted-but-unfinished work, never success; docs state this plainly.

## Frontend

- Desk `Create draft` uses `POST /api/runs/async`, opens a pending Run
  view immediately, polls steps + receipt, renders each stage from
  stored evidence as it lands (started, completed, pending, failed),
  marks unconfirmed when the worker is gone but the receipt is still
  running, and only shows approve/export on a completed receipt after
  the final poll agrees with the steps.
- Related Desk lifecycle fixes in the same edit: the selected-photo
  caption/alt derives from the actual current verdict (no verdict,
  current detected check, superseded, in flight, or other stored state),
  so the same unchanged local bytes are not called forever unchecked
  once the current revision has a detected check; new local pixels are
  still never implied checked. Crop copy drops server pad/clamp
  wording; acknowledged mutation receipts cancel in-flight GET polls
  and order by revision so a stale GET never overwrites a newer
  mutation receipt.

## Proofs

- `backend/tests/test_run_progress.py`: barrier test (scout completion
  observed before maker release), final receipt matches completed
  order with started history, shared timestamps and profiles per
  completed stage, and persists before completion is claimed; failure
  keeps the original failed receipt, exactly one failed row at the
  actual stopped stage, and blocks approval/export; accept journal
  failure rolls back with no worker; mid-run journal loss fails
  honestly with no further model work; terminal persist failure leaves
  stored state unconfirmed without synthetic overwrite; concurrent
  starters claim at most one live worker; re-poll causes no duplicate
  provider work.
- Real keyless browser flow through the new pending/step view with the
  real API and Postgres (no route interception); offline barrier tests
  are labelled as timing proofs, not live Meta proof.
- All existing suites, scans, and photo interaction proofs stay green
  and unrenamed.
