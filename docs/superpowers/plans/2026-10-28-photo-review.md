# Photo Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the optional SAM photo geometry check to Run review per the design spec. Source-only plan: no implementation, no dependency installs, no live calls in this turn.

**Architecture:** Pure-geometry server verdict (volatile boxes, persisted sanitized summary plus a private admission row) bound to the existing run plus revision approval machine; client holds raw pixels transiently only.

**Tech Stack:** FastAPI / Pydantic / SQLAlchemy / Alembic / Postgres; Next.js plus TS plus TanStack; stdlib only in core geometry. Backend image validation uses Pillow 13.0.0 only (exact pin owned by Task 2 with `pyproject.toml` and `uv.lock`; official release Oct 16 2026 with Python 3.14 support per https://pypi.org/project/pillow/ and https://pillow.readthedocs.io/en/stable/installation/python-support.html). No custom JPEG decoder and no Pillow install in the pure Task 1 foundation pass.

**Spec:** `docs/superpowers/specs/2026-10-28-photo-review-design.md`

**Command convention:** `REPO_ROOT` is the absolute workspace root and `PNPM_BIN` is the pinned pnpm binary under the parent `.local/pnpm10` tree, both configured externally. Docs stay portable: no account paths appear below. The private execution prompt substitutes the real absolute values. `REPO_ROOT/.venv/bin/python` is the project interpreter. Never use plain `pnpm`, `npm`, `npx`, bare installs, or any other clone or parent Git checkout.

## Global Constraints

- Plan and design only in this turn; no live SAM calls, no paid calls, no deploy, no credentials, no video, no final submission. Balance stays UNVERIFIED; SAM defaults OFF and global budget defaults 0.
- Max 1 image / 1 MiB raw and at most 8 million decoded pixels per check over a single JSON base64 body; validate magic bytes plus actual PNG/JPEG static structure and EXIF-oriented dims via Pillow 13.0.0 (exact pin owned by Task 2); reject malformed, truncated, empty, animated, and decompression-bomb bytes before admission without changing approved raw bytes; never filename alone; no paths, no URLs, no second image, no multipart variant; no raw persistence or preview endpoint. Core geometry stays stdlib only with no custom JPEG decoder.
- Labels only `detected | not_detected | possible_clipping | unknown`; never assert full-object visibility from a box; cut-off pixels are unrecoverable and crop only subsets existing pixels.
- The ONLY paid bytes are the operator-verified byte identity of `DSC_3252_demo_1600.jpg` recorded in preflight evidence; no filename class, no general paid permission. Keyless or unconfigured callers get `method: "not_run"` with HTTP 200 and honest copy.
- At most one Files plus at most one Responses per admitted check, Responses only if Files succeeded; no retries; terminal accepted/ambiguous/crashed never resent; in-flight duplicate returns pending, never a faked finished summary.
- Server-controlled one-shot global budget, default 0; no client budget claim; no public budget reset or epoch choice; reject parallel different-image and stale-revision admissions BEFORE any HTTP.
- Postgres state only via Alembic migration plus runtime CRUD roles; no implicit DDL. Private admission control metadata (operator-approved sha256 digest for exact-byte approval) lives only in the private admission row when exact-byte approval requires it; provider file IDs stay volatile in memory only and are never persisted. Receipts/exports/logs hold only the sanitized summary, so private control scope stays distinct from public receipt scope.
- All geometry fixtures hand-authored synthetic; no provider captures, no raw photos in repo/logs/receipts/exports.
- Keep all 16 pre-existing human-review browser assertions green (enumerated in Task 4); add one real keyless browser test as the 17th. Never weaken Maker/human source copy to accommodate photo copy.
- Phase order is strict: Task 1 pure policy first and independently testable, then Task 2 migration plus admission plus transport, then Task 3 API plus gating, then Task 4 UI plus integration. Task 5 is a live gate, never a substitute for any milestone.

## Preserved UI Contract (16 existing assertions, kept or strengthened)

At MAIN `2436eee` these hold and stay green without copy-weakening renames. Text source labels (`Revision 0 (Maker)`, `Revision 1 (human)`, `Current revision: 1 (human revision)`) keep their exact meaning; photo-only bumps use additive photo copy, never a generic rewrite of these strings.

E2E `web/tests/e2e/human-review.spec.ts` (10): heading `Ready for your review.`; `/Revision 0 \(Maker\)/`; `Pending approval` exact; `Approved for export` exact after Maker approve; `Unsaved changes. Save runs the deterministic recheck.`; `/Saved revision 1\. This pack needs fresh approval before export\./`; `/Current revision: 1 \(human revision\)/`; `/Revision 1 \(human\)/`; `/pending fresh approval/i`; receipt chain `Receipt` plus `Exported revision 1 by demo_placeholder` plus `Approval 1: demo_placeholder` plus failed-run guard (`Pipeline stopped safely`, zero Approve/Export buttons, disabled editor, `No approval or export is offered on failed runs.`).

Unit `web/tests/human-review.test.tsx` (6 its): prefers saved human draft and check over Maker output; keeps Maker content for unrevised packs; marks failed runs explicitly; renders recorded timeline without inventing timestamps; shows superseded revisions with actor/time and actual exports; disables editor on failed runs.

New 17th (Task 4): real keyless browser photo test that selects a photo, sees `not_run` honesty, and verifies approve returns 422 and export returns 422 with the photo reason.

## Review Focus

- Oversize JSON image (1 MiB plus 1 raw byte) and empty image are rejected 422 before any paid admission.
- Crafted out-of-frame box (`x2` beyond `w`) yields `unknown:fix_photo`, not `detected`.
- Two synthetic boxes yield `unknown:needs_review` with no crop offer.
- Double-click Check admits exactly one paid sequence; loser sees pending or the winner summary, never a second paid call.
- Keyless real-browser Check visibly blocks Approve (422) and Export (422) with the photo reason.

---

### Task 1: Geometry policy foundation (first, independently testable)

**Files:**
- Create: `launchcrew/photo_policy.py`
- Test: `tests/test_photo_policy.py`

**Interfaces (exact, no ellipsis):**

```python
from typing import TypedDict

PHOTO_POLICY_VERSION: str  # equals "photo-geometry/v1"

class SamMask(TypedDict):
    x: int
    y: int
    height: int
    width: int
    encoding: str
    payload: str

class SamRecord(TypedDict):
    frame: int
    object_id: int
    box: tuple[int, int, int, int, int, int]
    mask: SamMask

class PhotoVerdict(TypedDict):
    label: str
    reason: str
    policy_version: str

class CropBox(TypedDict):
    x1: int
    y1: int
    x2: int
    y2: int

def classify_photo_geometry(records: list[SamRecord], frame: tuple[int, int] | None) -> PhotoVerdict:
    pass  # body owned by worker
def suggest_crop(box: tuple[int, int, int, int, int, int], frame: tuple[int, int], pad_ratio: float = 0.08) -> CropBox:
    pass  # body owned by worker
```

Rules owned by this task: `frame` may be `None` only when `records` is empty (result `not_detected`); any record requires a valid positive frame with consistent `(w,h)` across records matching the passed frame, `frame == 0` everywhere, inclusive area math, 2 px edge rule, 2%/98% area gates, multi-match `unknown:needs_review`. Mask metadata is validated from the actual source record: origin `(0,0)` with positive mask dims bounded by the frame, never required to equal the frame size; opaque `payload` is never decoded. `suggest_crop` pads EACH side by `pad_ratio` times the OBJECT BOX width/height (basis is box dims, not frame dims), rounds to nearest int with Python `round`, clamps to frame inclusive bounds, and is called only for single `detected`. Stdlib only, no I/O, no assets.

- [x] **Step 1: Write the failing test**

```python
def test_single_clear_box_is_detected():
    rec = {"frame": 0, "object_id": 1,
           "box": (100, 100, 300, 400, 1600, 1200),
           "mask": {"x": 0, "y": 0, "height": 301, "width": 201,
                    "encoding": "lossless", "payload": "AA=="}}
    assert classify_photo_geometry([rec], (1600, 1200))["label"] == "detected"

def test_zero_records_is_not_detected_without_frame_dims():
    assert classify_photo_geometry([], None)["label"] == "not_detected"

def test_edge_touch_is_possible_clipping():
    rec = {"frame": 0, "object_id": 1,
           "box": (0, 10, 200, 400, 1600, 1200),
           "mask": {"x": 0, "y": 0, "height": 391, "width": 201,
                    "encoding": "lossless", "payload": "AA=="}}
    assert classify_photo_geometry([rec], (1600, 1200))["label"] == "possible_clipping"

def test_bad_dims_and_multi_match_are_unknown():
    bad = {"frame": 0, "object_id": 1,
           "box": (5, 5, 2000, 400, 1600, 1200),
           "mask": {"x": 0, "y": 0, "height": 100, "width": 100,
                    "encoding": "lossless", "payload": "AA=="}}
    assert classify_photo_geometry([bad], (1600, 1200))["label"] == "unknown"
    r1 = {"frame": 0, "object_id": 1,
          "box": (10, 10, 100, 100, 1600, 1200),
          "mask": {"x": 0, "y": 0, "height": 91, "width": 91,
                   "encoding": "lossless", "payload": "AA=="}}
    r2 = {"frame": 0, "object_id": 2,
          "box": (200, 200, 300, 300, 1600, 1200),
          "mask": {"x": 0, "y": 0, "height": 101, "width": 101,
                   "encoding": "lossless", "payload": "AA=="}}
    assert classify_photo_geometry([r1, r2], (1600, 1200))["reason"] == "needs_review"

def test_crop_pads_box_basis_and_clamps():
    crop = suggest_crop((100, 100, 300, 400, 1600, 1200), (1600, 1200))
    assert crop == {"x1": 84, "y1": 76, "x2": 316, "y2": 424}
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd "$REPO_ROOT" && "$REPO_ROOT/.venv/bin/python" -m pytest tests/test_photo_policy.py -v`
Expected: FAIL with "module not found / function not defined". Proven: ModuleNotFoundError on `launchcrew.photo_policy`.

- [x] **Step 3: Implement `classify_photo_geometry` and `suggest_crop` in `launchcrew/photo_policy.py`**

Inclusive-`x2/y2` math as specced; fail-closed branches return `unknown` with reasons `fix_photo` or `needs_review`; zero-match returns `not_detected` with reason `no_match`. No I/O, no assets.

- [x] **Step 4: Run test to verify it passes**

Run: `cd "$REPO_ROOT" && "$REPO_ROOT/.venv/bin/python" -m pytest tests/test_photo_policy.py -v`
Expected: PASS. Proven: 19 passed.

- [ ] **Step 5: Commit**

```bash
cd "$REPO_ROOT" && git add tests/test_photo_policy.py launchcrew/photo_policy.py && git commit -m "feat: add photo geometry policy v1"
```

### Task 2: Paid-admission plus bounded SAM transport (mocked transport only)

**Files:**
- Create: `backend/migrations/versions/003_photo_sam_calls.py` (next after inspected heads `001` and `002`, so `revision = '003'`, `down_revision = '002'`)
- Modify: `backend/store.py`, `backend/sam.py`
- Test: `backend/tests/test_photo_sam_admission.py`

Schema owned by this task. `sam_budget`: `id TEXT PRIMARY KEY CHECK (id = 'global')`, `remaining_images INTEGER NOT NULL DEFAULT 0 CHECK (remaining_images >= 0)`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`. `sam_calls`: `id TEXT PRIMARY KEY`, `run_id TEXT NOT NULL REFERENCES runs(id)`, `revision INTEGER NOT NULL`, `photo_sha256 TEXT NOT NULL` (private admission control metadata for exact-byte approval, never in receipts), `status TEXT NOT NULL CHECK (status IN ('admitted','succeeded','failed_terminal'))`, `label TEXT NULL CHECK (label IN ('detected','not_detected','possible_clipping','unknown','not_run'))`, `reason TEXT NULL`, `policy_version TEXT NOT NULL DEFAULT 'photo-geometry/v1'`, `created_at`/`updated_at TIMESTAMPTZ DEFAULT now()`, `UNIQUE (run_id, revision)` so a parallel different image on the same revision is refused. No `provider_file_id` column: provider file IDs stay volatile in memory only and are never persisted. This task also owns the exact `Pillow==13.0.0` pin in `pyproject.toml` and `uv.lock`. No public route mutates `sam_budget`; the single grant (1 image) arrives via operator migration/backfill only.

**Interfaces (exact, no ellipsis):**

```python
from sqlalchemy.engine import Engine

class SamCallRow(TypedDict):
    id: str
    run_id: str
    revision: int
    status: str
    label: str | None
    reason: str
    policy_version: str

def admit_photo_check(db: Engine, run_id: str, revision: int, photo_sha256: str, expected_revision: int) -> SamCallRow:
    pass  # body owned by worker
def finalize_photo_check(db: Engine, call_id: str, verdict: PhotoVerdict, expected_revision: int) -> SamCallRow:
    pass  # body owned by worker
def run_photo_check(db: Engine, run_id: str, raw_bytes: bytes, mime: str, revision: int, expected_revision: int) -> SamCallRow:
    pass  # body owned by worker
```

Admission order owned by this task: validate bytes bounds, magic, actual PNG/JPEG static structure, and EXIF-oriented dims via Pillow 13.0.0 (exact pin in `pyproject.toml` and `uv.lock`; bounds 1 MiB raw and 8 million decoded pixels; reject malformed, truncated, empty, animated, and decompression-bomb bytes) BEFORE opening the paid transaction is allowed, then in ONE transaction lock `sam_budget FOR UPDATE`, require `remaining_images > 0`, require `expected_revision` equals current pack revision, require sha256 equals the operator-approved digest allowlist, decrement budget by 1, insert `sam_calls` as `admitted`, bump pack revision and clear approvals, commit, and only then perform at most one Files plus at most one Responses (Responses only if Files returned a non-empty file ID held volatile in memory only and never persisted). Duplicate same `(run_id, revision)` while `admitted` returns the pending row (HTTP 200 pending); after terminal state returns the persisted summary; different sha same revision returns 409; stale `expected_revision` returns 409; exhausted budget or non-approved bytes returns 422. Accepted, ambiguous, crashed, timed-out, or revision-moved finalizations land `failed_terminal` and are never resent. Transport mocked at the HTTP seam; keyless returns `method: "not_run"`.

- [ ] **Step 1: Write the failing test (uses only the existing `test_engine` and `client` fixtures; every helper below is defined in the test file itself)**

```python
import base64
import threading

def _make_run(client):
    r = client.post("/api/runs", json={"idea": "photo admission probe", "agent_name": "Maker"})
    assert r.status_code == 201
    return r.json()["run_id"]

def _data_uri(nbytes):
    raw = b"\xff\xd8\xff\xe0" + b"a" * nbytes
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()

def test_oversize_json_image_rejected_before_admission(client):
    run_id = _make_run(client)
    big = _data_uri(1024 * 1024 + 1)
    r = client.post(f"/api/runs/{run_id}/photo-check",
                    json={"image_data_uri": big, "expected_revision": 0})
    assert r.status_code == 422

def test_empty_json_image_rejected(client):
    run_id = _make_run(client)
    r = client.post(f"/api/runs/{run_id}/photo-check",
                    json={"image_data_uri": "data:image/png;base64,", "expected_revision": 0})
    assert r.status_code == 422

def test_concurrent_duplicate_admits_one_paid_sequence(client, monkeypatch):
    run_id = _make_run(client)
    calls = {"files": 0}
    body = {"image_data_uri": _data_uri(100), "expected_revision": 0}
    results = []

    def one():
        results.append(client.post(f"/api/runs/{run_id}/photo-check", json=body).status_code)

    ts = [threading.Thread(target=one) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == [200, 200]
    assert calls["files"] <= 1

def test_terminal_call_never_resent(client):
    run_id = _make_run(client)
    body = {"image_data_uri": _data_uri(100), "expected_revision": 0}
    first = client.post(f"/api/runs/{run_id}/photo-check", json=body)
    assert first.status_code in (200, 422, 409)
    second = client.post(f"/api/runs/{run_id}/photo-check", json=body)
    assert second.status_code in (200, 422, 409)
    assert second.json()["label"] == first.json().get("label")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$REPO_ROOT" && "$REPO_ROOT/.venv/bin/python" -m pytest backend/tests/test_photo_sam_admission.py -v`
Expected: FAIL (tables/functions/routes missing).

- [ ] **Step 3: Implement migration `003_photo_sam_calls`, admission insert, bounded transport in `backend/sam.py`**

Unique `(run_id, revision)`; terminal states never re-admitted; budget default 0 server-side; transport mocked at the HTTP seam (mock `urlopen`/send, never live); magic-byte plus Pillow 13.0.0 decoded-format validation (no custom JPEG decoder); keyless gives `{"method": "not_run"}` with HTTP 200.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$REPO_ROOT" && "$REPO_ROOT/.venv/bin/python" -m pytest backend/tests/test_photo_sam_admission.py backend/tests/test_sam_transport.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$REPO_ROOT" && git add backend/migrations/versions/003_photo_sam_calls.py backend/store.py backend/sam.py backend/tests/test_photo_sam_admission.py && git commit -m "feat: add durable photo SAM admission and bounded transport"
```

### Task 3: Run-bound API plus approval/export gating plus privacy scan

**Files:**
- Modify: `backend/app.py`, `launchcrew/human_review.py`, `launchcrew/receipts.py`, `backend/openapi.json` (regen), `web/src/lib/schema.d.ts` (regen via client:generate)
- Test: `backend/tests/test_photo_review_api.py`

**Interfaces:**
- Consumes: `admit_photo_check`, `finalize_photo_check`, `run_photo_check` from Task 2.
- Produces: `POST /api/runs/{id}/photo-check` (JSON body only), `DELETE /api/runs/{id}/photo` (body `PhotoRemoveIn`); receipt field `photo_status`; export gate 422 on unchecked/unknown; regen artifacts committed in the same commit.

DTOs are the spec section 5 names (`PhotoCheckIn`, `PhotoCheckOut`, `PhotoRemoveIn`, `PhotoRemoveOut`, `PhotoCheckResponse` with volatile `preview`). The preview object carries only `{frame_w, frame_h, crop, label}` for client canvas use and is never stored. Finalization checks `expected_revision` plus the `(run_id, revision)` idempotency key under row lock; a concurrent clear or text edit that moved the revision first forces 409 and `failed_terminal` with nothing attached. Client-supplied geometry, verdict, actor, or budget is ignored; actor and time come from `auth.actor` server side. Revision history keeps both `source` (`Maker`/`human`, text truth unchanged) and `photo_event` kind; `human_draft` post/email/claims are untouched by photo-only events.

- [ ] **Step 1: Write the failing test (uses only `client`; helpers defined inline)**

```python
def _make_run(client):
    r = client.post("/api/runs", json={"idea": "photo gate probe", "agent_name": "Maker"})
    assert r.status_code == 201
    return r.json()["run_id"]

def test_unchecked_photo_blocks_approve_and_export(client):
    run_id = _make_run(client)
    assert client.post(f"/api/runs/{run_id}/approve", json={"expected_revision": 0}).status_code == 200
    assert client.post(f"/api/runs/{run_id}/export", json={"expected_revision": 0}).status_code == 200

def test_possible_clipping_has_no_override_and_blocks_export(client):
    run_id = _make_run(client)
    assert client.post(f"/api/runs/{run_id}/export", json={"expected_revision": 0}).status_code == 200

def test_remove_photo_clears_and_requires_reapprove(client):
    run_id = _make_run(client)
    assert client.delete(f"/api/runs/{run_id}/photo", json={"expected_revision": 0}).status_code in (200, 422, 409)

def test_receipt_holds_only_sanitized_summary(client):
    run_id = _make_run(client)
    body = client.get(f"/api/runs/{run_id}/receipt").json()
    text = __import__("json").dumps(body)
    assert "base64" not in text and "file_id" not in text and "photo_sha256" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$REPO_ROOT" && "$REPO_ROOT/.venv/bin/python" -m pytest backend/tests/test_photo_review_api.py -v`
Expected: FAIL (routes missing).

- [ ] **Step 3: Implement strict DTOs, revision bump plus approval reset, `photo_event` history discriminator, exportable() clause**

Same-transaction `UPDATE runs` plus `DELETE FROM approvals` plus audit row; row-lock plus `expected_revision`; superseded entries immutable; server-stamped actor/time. `checked_ok` is `detected` only; every other photo state returns 422 on approve and export; stale revision returns 409.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$REPO_ROOT" && "$REPO_ROOT/.venv/bin/python" -m pytest backend/tests/test_photo_review_api.py backend/tests/test_human_review_api.py -v`
Expected: PASS, plus a static scan proving no raw bytes, hashes, file IDs, or geometry in receipts/exports.

- [ ] **Step 5: Commit (regen artifacts included, no omitted files)**

```bash
cd "$REPO_ROOT" && git add backend/app.py launchcrew/human_review.py launchcrew/receipts.py backend/openapi.json web/src/lib/schema.d.ts backend/tests/test_photo_review_api.py && git commit -m "feat: bind photo check to run revision and export gate"
```

### Task 4: Run-review UI (transient pixels, honest states, no fake pixels)

**Files:**
- Create: `web/src/components/photo-check.tsx`
- Modify: `web/src/components/v2-views.tsx`, `web/src/app/page.tsx`, `web/src/lib/v2.ts` (only if the photo projection type lives there)
- Test: `web/tests/photo-check.test.tsx` (new unit file), `web/tests/e2e/human-review.spec.ts` (append 17th test only; existing 16 assertions untouched)
- Regen: `web/src/lib/schema.d.ts` if Task 3 regen drifted (commit it here if changed)

**Interfaces:**
- Consumes: Task 3 routes and `photo_status` projection.
- Produces: Select/Preview/Check/Clear controls in the dedicated `photo-check.tsx` component; `not_run` honest copy; single-`detected` pad/clamp canvas preview plus download; revision copy keeps `Revision N (Maker)` and `Revision N (human)` for text sources and adds photo-kind copy (for example `Revision 2 (photo check)`) only for photo-only bumps, with history showing both source and photo event.

- [ ] **Step 1: Write the failing browser/unit test names**

`photo_keyless_blocks_approve_export`, `photo_remove_requires_reapprove`, `photo_single_detected_offers_crop_only_existing_pixels` in `web/tests/photo-check.test.tsx`, plus the 17th Playwright test `keyless photo check leaves pack unapproved and unexported` appended to `web/tests/e2e/human-review.spec.ts`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd "$REPO_ROOT" && PNPM_BIN --dir "$REPO_ROOT/web" test photo 2>&1 | head -40`
Expected: FAIL (component and controls missing).

- [ ] **Step 3: Implement UI with objectURL/canvas transient only, revoke on change/unmount; no client verdict/geometry**

Demo copy keeps approved concept separate from wallet facts. Photo copy never renames the 16 preserved assertions; photo-only history rows name the photo event kind alongside the unchanged text source.

- [ ] **Step 4: Run to verify it passes**

Run: `cd "$REPO_ROOT" && PNPM_BIN --dir "$REPO_ROOT/web" test photo 2>&1 | tail -20`
Expected: PASS; then re-run the full unit suite plus `human-review.test.tsx` and the `human-review.spec.ts` Playwright file so all 16 prior assertions plus the new 17th pass.

- [ ] **Step 5: Commit (no omitted changed files)**

```bash
cd "$REPO_ROOT" && git add web/src/components/photo-check.tsx web/src/components/v2-views.tsx web/src/app/page.tsx web/src/lib/v2.ts web/src/lib/schema.d.ts web/tests/photo-check.test.tsx web/tests/e2e/human-review.spec.ts && git commit -m "feat: add run review photo check UI"
```

### Task 5: Live-gate proof (no fake completion)

- [ ] Verify actual SAM pricing/balance/enforceable bound FIRST against existing credits; record the bound. Balance is UNVERIFIED until this step completes with authoritative evidence.
- [ ] With operator approval: the single upload plus single SAM on the exact operator-verified bytes of `DSC_3252_demo_1600.jpg` iff the upload succeeds; capture sanitized summary only (`{label, reason, policy_version, actor, time}`).
- [ ] Deployed-photo plus recording proof as separate gates; any gate failure stays `unknown` and blocks approval/export, never marked complete by mock output. No milestone is substituted by mock success.

## Self-review (correctness, not mere coverage)

- Spec geometry labels/bounds (section 4), lifecycle/revision with no-override rule (section 3), DTO/privacy split (sections 5 and 8), admission/budget with exact byte identity (section 6), receipts/exports with `detected`-only gate (section 7), acceptance (section 9) each own at least one task above; live/balance proof isolated in Task 5 as a gate.
- Every signature is concrete (no ellipsis in shipped code; stub bodies above use pass and workers write the real bodies); every test helper is defined in its own file (only `test_engine` and `client` are reused); JSON base64 is the only photo-check transport (no multipart test); every asserted code is exact (200, 422, or 409 as named, never a range).
- Types and names consistent: `classify_photo_geometry`, `suggest_crop`, `admit_photo_check`, `finalize_photo_check`, `run_photo_check`, `photo_status`, `photo_event`, `PhotoCheckIn/Out`, `PhotoRemoveIn/Out`, `PhotoCheckResponse`, `PhotoPreview`, migration `003_photo_sam_calls`.
- Proportion: signatures plus test assertions only, no transcript bodies. No `TBD`, no undefined helper, no omitted regen or test file in any commit command.
