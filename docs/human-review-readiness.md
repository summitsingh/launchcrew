# Human review readiness (safe editing on main)

Scope: narrow post plus email pack review only. No new crews, connectors,
Meta or paid model calls, photo UI, cloud, DNS, or publishing.

What was built:
- `launchcrew/human_review.py` is the single pure helper for revision
  math. It rechecks edited post and email against the SAME run snapshot
  (verified Scout facts, blocked rules, Checker policies) with the
  existing `run.check_pack` path. No model or API call runs from edit or
  recheck. Client verdicts, approvals, actors, and policy fields are never
  trusted.
- Invalid edits are rejected with HTTP 422 and are not stored. The
  response carries per-claim reasons and revision instructions. Only
  clean text is saved as a new human revision.
- Any saved change resets export approval to pending. Fresh approval must
  bind the latest revision with an explicit strict-integer
  `expected_revision`. Missing or stale versions on edited packs are
  refused with 409. Legacy unedited revision-zero clients sending `{}`
  stay compatible. Every saved revision preserves the complete prior
  draft, check, approval state, and context plus actual actor/time
  history, including across multiple pending edits. Original Maker
  output is never mutated.
- Approval and export use row locks (`FOR UPDATE`) plus revision checks.
  Stale edit, approval, and export requests are refused with 409.
  `approve_receipt` and `export_receipt` read the latest checked human
  content, never stale Maker text. Learning approval examples uses the
  latest approved human content. Failed runs refuse revise, approve, and
  export. Strict DTOs forbid unknown fields and reject bools, floats,
  and strings for version integers, so forged `approved_by`, verdict,
  and policy fields return 422 and the actual actor always comes from
  the server session.
- Export payloads carry `exported_draft` and `exported_revision` while
  keeping original Maker drafts as evidence. Exports persist the actual
  export revision, actor, and time into `audit.event_log`,
  `export_history`, and `last_exported_*`, so GET receipt and the UI
  timeline show the real export.
- Source evidence is never invented: the `demo_facts.json` fallback is
  gone as authority. Review requires an actual trusted snapshot with
  `verified is True` plus sourced entries and real scout sources, plus
  a completed run. Missing or malformed review context fails closed.
  Stage profiles and applied memory context stay snapshotted for
  deterministic rechecks after later profile or memory edits.
- Frontend Run review has an accessible editor with unsaved, saved,
  needs-revision, and pending-fresh-approval states, plus a plain
  explanation of what rechecking does. Receipts show the recorded event
  timeline, revision history, current versus original drafts, and failed
  status with sanitized stage and type. Queue cards show revision and
  current final-blocked state with controls disabled when appropriate.
  Raw receipt JSON remains as an advanced view only.

Observed results in this sandbox on 2026-10-28 (this session only):
- `web`: Vitest 6 files, 32 tests passed.
- `web`: `tsc --noEmit` passed.
- `web`: `next build` passed.
- `scripts/check-repo-text.py` passed (all counts 0).
- `scripts/scan_repo.py` passed (`Scan result: pass`).
- `tests` unittest: 87 passed plus 38 subtests passed; 3 failed in
  `tests/test_stage_b.py` `WebTests` from sandbox bind denial
  (`socketserver` bind raises `PermissionError: [Errno 1] Operation not
  permitted`). Environmental only; the tests were not weakened.
- Pure helper probe without binds (`launchcrew/human_review.py` direct):
  bool `base_revision` rejected, clean edit saved as revision 1 with
  actual actor and timestamp, full prior-context history entry recorded,
  stale base rejected, approval without `expected_revision` on an edited
  pack rejected, wrong `expected_revision` rejected, legacy revision-0
  approve with omitted `expected_revision` accepted, export persisted
  revision/actor/time into `export_history` and `audit.event_log`,
  unapproved export rejected, bool revision reads as 0. All behaved as
  designed.
- NOT run here: Postgres-backed `backend/tests` (no `DATABASE_URL`, no
  Postgres in sandbox; collection errors on `KeyError: 'DATABASE_URL'`)
  and Playwright browser tests (sandbox denies loopback binds). No PG or
  browser pass is claimed from this shell. The host verifier must run the
  full gates on commit.

Not run here (needs host):
- `scripts/verify-release-candidate.sh --backend-only`
- `scripts/verify-release-candidate.sh --all`
- New tests: `backend/tests/test_human_review_api.py`,
  `web/tests/human-review.test.tsx`, `web/tests/e2e/human-review.spec.ts`

Hand to host verifier: run the backend-only gate, then the all gate with
disposable Postgres and real Next plus API, and confirm the new revision
tests plus all prior suites before any push.
