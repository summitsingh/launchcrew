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
  bind the latest revision. Old approvals move to `revision_history` as
  superseded audit, never as current approval.
- Approval and export use row locks (`FOR UPDATE`) plus revision checks.
  Stale edit, approval, and export requests are refused with 409.
  `approve_receipt` and `export_receipt` read the latest checked human
  content, never stale Maker text. Learning approval examples uses the
  latest approved human content. Failed runs refuse revise, approve, and
  export. Legacy unrevised packs stay compatible (revision 0).
- Export payloads carry `exported_draft` and `exported_revision` while
  keeping original Maker drafts as evidence.
- Frontend Run review has an accessible editor with unsaved, saved,
  needs-revision, and pending-fresh-approval states, plus a plain
  explanation of what rechecking does. Receipts show the recorded event
  timeline, revision history, current versus original drafts, and failed
  status with sanitized stage and type. Queue cards show revision and
  current final-blocked state with controls disabled when appropriate.
  Raw receipt JSON remains as an advanced view only.

Observed CLI-safe results in this sandbox:
- `web`: Vitest 6 files, 31 tests passed (was 5 files, 26 tests).
- `web`: `tsc --noEmit` passed.
- `web`: `next build` passed.
- `scripts/check-repo-text.py` passed (em dash 0).
- `scripts/scan_repo.py` passed.
- `tests` unittest: 87 passed, 3 errors in `test_stage_b.py` from sandbox
  bind denial (`HTTPServer` bind `Operation not permitted`). Same shape as
  the known CLI bind limit, not a code failure.
- Pure helper probe without binds: clean recheck 0 blocked, unsupported
  `best in Texas` 1 blocked with claim reason, revision increment,
  approval binding, export view, stale refusal, and failed refusal all
  behaved as designed.
- Postgres backend tests (83), original unittest full suite behavior
  beyond binds, Vitest contract regeneration, and Playwright browser
  (15 existing plus 1 new human-review spec) were NOT run here because
  this sandbox denies loopback binds (`socket.bind 127.0.0.1` raises
  `PermissionError`). No PG or browser pass is claimed from this shell.
  The host and GitHub verifier must run the full gates on commit.

Not run here (needs host):
- `scripts/verify-release-candidate.sh --backend-only`
- `scripts/verify-release-candidate.sh --all`
- New tests: `backend/tests/test_human_review_api.py`,
  `web/tests/human-review.test.tsx`, `web/tests/e2e/human-review.spec.ts`

Hand to host verifier: run the backend-only gate, then the all gate with
disposable Postgres and real Next plus API, and confirm the new revision
tests plus all prior suites before any push.
