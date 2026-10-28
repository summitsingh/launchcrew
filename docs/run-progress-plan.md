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
Never raw provider payloads, prompts, or keys. The final stored receipt
`event_log` must agree with the step rows in order, timestamps, and
profile evidence; the completion transaction writes the finished step
row and the final receipt together, so success is never claimed before
the DB commit.

## Guards

- Approve/revise/export/photo-check on a running receipt return 409
  with an explicit "still running" reason.
- One worker per run id (registry dict); duplicate POSTs create separate
  run ids, never a second worker for the same id.
- Polls, reconnects, and navigation never call the provider and never
  restart work. Ambiguous transport failure leaves the run `running`
  with an `unconfirmed` note; the UI says the result is unknown and
  offers reload, never silent retry.
- Host restart loses in-flight workers by design (no supervisor). A
  `running` receipt older than its steps is evidence of
  accepted-but-unfinished work, never success; docs state this plainly.

## Frontend

- Desk `Create draft` uses `POST /api/runs/async`, opens a pending Run
  view immediately, polls steps + receipt, renders each completed stage
  from stored evidence as it lands, marks pending/failed/unconfirmed,
  and only shows approve/export on a completed receipt after the final
  poll agrees with the steps.
- Related Desk lifecycle fixes in the same edit: selected-photo
  caption/alt always reads Unchecked until a check passes; honest
  selected/checked/current/stale/unconfirmed states; crop copy drops
  server pad/clamp wording; acknowledged mutation receipts cancel
  in-flight GET polls and order by revision so a stale GET never
  overwrites a newer mutation receipt.

## Proofs

- `backend/tests/test_run_progress.py`: barrier test (scout completion
  observed before maker release), final receipt matches step order and
  timestamps and persists before completion is claimed, failure keeps
  completed steps and blocks approval/export, re-poll causes no
  duplicate provider work.
- Real keyless browser flow through the new pending/step view with the
  real API and Postgres (no route interception); offline barrier tests
  are labelled as timing proofs, not live Meta proof.
- All existing suites, scans, and photo interaction proofs stay green
  and unrenamed.
