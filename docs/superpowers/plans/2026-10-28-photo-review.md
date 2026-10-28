# Photo Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the optional SAM photo geometry check to Run review per the design spec.

**Architecture:** Pure-geometry server verdict (volatile boxes, persisted sanitized summary) bound to the existing run+revision approval machine; client holds raw pixels transiently only.

**Tech Stack:** FastAPI / Pydantic / SQLAlchemy / Alembic / Postgres; Next.js + TS + TanStack; stdlib only in core geometry.

**Spec:** `docs/superpowers/specs/2026-10-28-photo-review-design.md`

## Global Constraints

- Plan/design only in this turn; no live SAM calls, no paid calls, no deploy, no credentials, no video, no final submission.
- Max 1 image / 1 MiB raw per check; validate magic bytes, never filename alone; no paths/URLs; no raw persistence or preview endpoint.
- Labels only `detected | not_detected | possible_clipping | unknown`; never assert full-object visibility from a box.
- Default OFF; keyless returns `not_run` with HTTP 200 and honest UI.
- At most one Files + at most one Responses per admitted check, Responses only if Files succeeded; no retries; terminal accepted/ambiguous/crashed never resent.
- Server-controlled one-shot budget, default 0; no client budget claim.
- Postgres state only via Alembic migration + runtime CRUD roles; no implicit DDL.
- All geometry/file-ID fixtures hand-authored synthetic; no provider captures, no raw photos in repo/logs/receipts/exports.
- Absolute-path commands from the workspace root; frontend via the pinned absolute pnpm + Node 24 path; no installs, no plain pnpm/npm/npx.
- Keep all 16 prior strong browsers green.

## Review Focus

- Oversized/empty image (2 MiB, 0 bytes) is rejected 422 before any paid admission.
- Crafted out-of-frame box (`x2` beyond `w`) yields `unknown:fix_photo`, not `detected`.
- Two synthetic boxes yield `unknown:needs_review` with no crop offer.
- Double-click Check admits exactly one paid sequence under concurrency.
- Keyless real-browser Check visibly blocks Approve and Export with the photo reason.

---

### Task 1: Geometry policy foundation (first independently testable)

**Files:**
- Create: `launchcrew/photo_policy.py`
- Test: `tests/test_photo_policy.py`

**Interfaces:**
- Consumes: nothing new (stdlib only).
- Produces: `PHOTO_POLICY_VERSION: str` (= `"photo-geometry/v1"`); `classify_photo_geometry(records: list[dict], frame: tuple[int,int]) -> tuple[str,str]` returning `(label, reason)` with labels above.

- [ ] **Step 1: Write the failing test**

```python
def test_single_clear_box_is_detected():
    label, reason = classify_photo_geometry([{"box": (100, 100, 300, 400, 1600, 1200)}], (1600, 1200))
    assert label == "detected"

def test_zero_records_is_not_detected():
    assert classify_photo_geometry([], (1600, 1200))[0] == "not_detected"

def test_edge_touch_is_possible_clipping():
    assert classify_photo_geometry([{"box": (0, 10, 200, 400, 1600, 1200)}], (1600, 1200))[0] == "possible_clipping"

def test_bad_dims_and_multi_match_are_unknown():
    assert classify_photo_geometry([{"box": (5, 5, 2000, 400, 1600, 1200)}], (1600, 1200))[0] == "unknown"
    assert classify_photo_geometry([{"box": (10, 10, 100, 100, 1600, 1200)}, {"box": (200, 200, 300, 300, 1600, 1200)}], (1600, 1200))[0] == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && .venv/bin/python -m pytest tests/test_photo_policy.py -v`
Expected: FAIL with "module not found / function not defined".

- [ ] **Step 3: Implement `classify_photo_geometry` in `launchcrew/photo_policy.py`**

Inclusive-`x2/y2` edge rule (2 px), area gates 2%/98%, fail-closed invalid dims/coords, multi-match `unknown:needs_review`, zero-match `not_detected`. No I/O, no assets.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && .venv/bin/python -m pytest tests/test_photo_policy.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && git add tests/test_photo_policy.py launchcrew/photo_policy.py && git commit -m "feat: add photo geometry policy v1"
```

### Task 2: Paid-admission + bounded SAM transport (mocked transport only)

**Files:**
- Create: `backend/migrations/versions/xxxx_photo_sam_calls.py`
- Modify: `backend/store.py`, `backend/sam.py`
- Test: `backend/tests/test_photo_sam_admission.py`

**Interfaces:**
- Consumes: `classify_photo_geometry` from Task 1.
- Produces: `admit_photo_check(db, run_id, revision, photo_sha256) -> row | None`; `run_photo_check(...) -> {"method": ..., "label": ..., "reason": ...}` with at most one Files + one Responses, no retry.

- [ ] **Step 1: Write the failing test**

```python
def test_concurrent_duplicate_admits_one(pgdb):
    assert admitted_count(run_concurrent_checks(pgdb, same_key=True)) == 1

def test_crashed_call_never_resent(pgdb):
    assert second_attempt_after_crash(pgdb) == "refused:terminal"

def test_invalid_image_rejected_before_admission(client):
    assert client.post(url, files={"image": two_mib()}).status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && .venv/bin/python -m pytest backend/tests/test_photo_sam_admission.py -v`
Expected: FAIL (tables/functions missing).

- [ ] **Step 3: Implement Alembic migration `sam_calls` + `sam_budget`, admission insert, bounded transport in `backend/sam.py`**

Unique `(run_id, revision, photo_sha256)`; terminal states never re-admitted; budget default 0 server-side; transport mocked at the HTTP seam (mock `urlopen`/send, never live); magic-byte validation; keyless → `{"method": "not_run"}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && .venv/bin/python -m pytest backend/tests/test_photo_sam_admission.py backend/tests/test_sam_transport.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && git add backend/migrations/versions/xxxx_photo_sam_calls.py backend/store.py backend/sam.py backend/tests/test_photo_sam_admission.py && git commit -m "feat: add durable photo SAM admission and bounded transport"
```

### Task 3: Run-bound API + approval/export gating + privacy scan

**Files:**
- Modify: `backend/app.py`, `launchcrew/human_review.py`, `launchcrew/receipts.py`
- Test: `backend/tests/test_photo_review_api.py`

**Interfaces:**
- Consumes: `admit_photo_check`, `run_photo_check` from Task 2.
- Produces: `POST /api/runs/{id}/photo-check`, `DELETE /api/runs/{id}/photo`; receipt `photo_status`; export gate 422 on unchecked/unknown.

- [ ] **Step 1: Write the failing test**

```python
def test_unchecked_photo_blocks_approve_and_export(client):
    assert approve_after_requested_unchecked(client).status_code in (409, 422)
    assert export_after_requested_unchecked(client).status_code == 422

def test_remove_photo_clears_and_requires_reapprove(client):
    assert removed_export_never_contains_old_photo(client)

def test_receipt_holds_only_sanitized_summary(client):
    assert receipt_has_no_bytes_or_file_ids(client)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && .venv/bin/python -m pytest backend/tests/test_photo_review_api.py -v`
Expected: FAIL (routes missing).

- [ ] **Step 3: Implement strict DTOs, revision bump + approval reset, `photo_event` history discriminator, exportable() clause**

Same-transaction `UPDATE runs` + `DELETE FROM approvals` + audit row; row-lock + `expected_revision`; superseded entries immutable; server-stamped actor/time.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && .venv/bin/python -m pytest backend/tests/test_photo_review_api.py backend/tests/test_human_review_api.py -v`
Expected: PASS, plus a static scan proving no raw bytes/file IDs in receipts/exports.

- [ ] **Step 5: Commit**

```bash
cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && git add backend/app.py launchcrew/human_review.py launchcrew/receipts.py backend/tests/test_photo_review_api.py && git commit -m "feat: bind photo check to run revision and export gate"
```

### Task 4: Run-review UI (transient pixels, honest states, no fake pixels)

**Files:**
- Modify: `web/src/components/v2-views.tsx`, `web/src/app/page.tsx`
- Test: `web/tests/human-review.test.tsx`, `web/tests/e2e/human-review.spec.ts`
- Test: real-browser keyless flow + unit canvas test with synthetic box

**Interfaces:**
- Consumes: Task 3 routes and `photo_status` projection.
- Produces: Select/Preview/Check/Clear controls; `not_run` honest copy; single-`detected` pad/clamp canvas preview + download; revision copy "revision N (text and/or photo)".

- [ ] **Step 1: Write the failing browser/unit test names**

`photo_keyless_blocks_approve_export`, `photo_remove_requires_reapprove`, `photo_single_detected_offers_crop_only_existing_pixels`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/.local/pnpm10/node_modules/.bin/pnpm --dir web test photo 2>&1 | head -40`
Expected: FAIL (controls missing).

- [ ] **Step 3: Implement UI with objectURL/canvas transient only, revoke on change/unmount; no client verdict/geometry**

Demo copy keeps approved concept separate from wallet facts.

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/.local/pnpm10/node_modules/.bin/pnpm --dir web test photo 2>&1 | tail -20`
Expected: PASS; then re-run all 16 prior strong browsers green.

- [ ] **Step 5: Commit**

```bash
cd /Users/summthak/Documents/ChatGPT/Playground/LaunchCrew-local-fallback/release-candidate && git add web/src/components/v2-views.tsx web/src/app/page.tsx web/tests/human-review.test.tsx && git commit -m "feat: add run review photo check UI"
```

### Task 5: Live-gate proof (no fake completion)

- [ ] Verify actual SAM pricing/balance/enforceable bound FIRST against existing credits; record the bound.
- [ ] With operator approval: the single approved upload + single SAM iff upload succeeds; capture sanitized summary only.
- [ ] Deployed-photo + recording proof as separate gates; any gate failure stays `unknown` and blocks approval/export — never marked complete by mock output.

## Self-review

- Spec coverage: geometry labels/bounds (§4), lifecycle/revision (§3), DTO/privacy (§5,§8), admission/budget (§6), receipts/exports (§7), acceptance (§9) — each has an owning task above; live/balance proof isolated in Task 5 as a gate.
- Steps are one-action with exact test names, commands, and expected outputs; no bodies beyond the inclusive-edge/pad rules the signatures need.
- Types/names consistent: `classify_photo_geometry`, `admit_photo_check`, `run_photo_check`, `photo_status`, `photo_event`.
- Proportion: signatures + test assertions only, no transcript bodies.
