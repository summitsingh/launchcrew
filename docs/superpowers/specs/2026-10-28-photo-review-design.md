# Photo Review (SAM Geometry Check): Design

**Date:** 2026-10-28 · **Status:** proposal, no implementation · **Source geometry:** https://dev.meta.ai/docs/sam/reading-segmentation and https://dev.meta.ai/docs/sam/segmenting (plain references; no live calls in design work).

## 1. Problem

`backend/sam.py:verify_demo_photo` only records segmentation `completed` (including zero matches) and never makes a visibility/crop decision. The proposal adds a real visual photo check to Run review without changing the original session rule (photo optional, Checker still blocks visual flaws) and without persisting raw photos or asserting full-object visibility from a box alone.

## 2. Goals / non-goals

Goals: optional per-run photo in existing Run review; explicit separate SAM check action; deterministic, reviewable geometry verdict; local crop suggestion/download preserving the original; receipt per decision/approval/export.

Non-goals: no full scene understanding; no verification of provider balance/credits in this design (balance is UNVERIFIED, see section 6); no new auth provider/scope; no generated/faked product pixels; no raw-image persistence or server preview endpoint; no reviewer freeform override of a non-detected verdict; no filename-class or general paid permission (only the single byte-identified approved file, see section 6); no public budget reset or epoch choice endpoint; no claim that a crop restores cut-off pixels.

## 3. UX lifecycle (bound to run + current revision)

States per run revision: `no_photo` → `photo_selected_local` → `check_requested` → `checked:{detected|not_detected|possible_clipping|unknown}`. Transitions: select/preview (client-only), explicit Check (server SAM call), Clear/Remove (explicit audit event), any saved photo change invalidates approval atomically exactly like human text edits (`DELETE FROM approvals` in the same transaction plus a `human_revised`-style audit entry). Admission and approval invalidation happen durably BEFORE any paid HTTP (see section 6).

Rules:

- Requested but `unknown` / unavailable / zero-match / `not_detected` / `possible_clipping` / `not_run` blocks approve AND export. There is no reviewer override that clears a non-`detected` photo state. The ONLY way a photo-bearing revision becomes exportable is a fresh `detected` geometry summary plus a fresh human pack approval on that same revision. A `possible_clipping` result is terminal for that revision: the operator either retries with a better photo (new revision, new check) or removes the photo (see next rule).
- Explicit Remove clears the attachment, writes an audit row, bumps the revision, resets approval, and returns the pack to the no-photo legacy path. Remove never exports the old photo and never acts as an override of an unsafe photo. A revision with `no_photo` state exports under the unchanged legacy text-only gate.
- Shared pack revision: photo attach/check/remove/clear bumps the same `current_revision` counter as `human_review.apply_revision` and goes through the same `expected_revision` plus row-lock plus current-approval-projection path. Text source truth is preserved: photo events carry a `photo_event` discriminator (`photo_attached | photo_checked | photo_removed`) that is DISTINCT from the text `source` projection (`Maker` vs `human`), and photo-only bumps never rewrite `human_draft` post/email/claims and never relabel existing `Revision N (Maker)` or `Revision N (human)` copy. The revision-history entry records both the text source and the photo event kind side by side.

## 4. Geometry interpretation (deterministic, versioned)

Normalized input record shape (matches the actual `backend/sam.py:parse_sse` output, no new fields):

```
SamRecord = {frame: int, object_id: int,
             box: (x1, y1, x2, y2, w, h),
             mask: {x: int, y: int, height: int, width: int,
                    encoding: "lossless", payload: str}}
```

Authoritative frame semantics (from the source docs above): static image is frame 0, so every record has `frame == 0`; box is `(x1,y1,x2,y2,w,h)` in source pixels with `x2,y2` INCLUSIVE; `w/h` are source-frame dimensions (EXIF-oriented); mask `height` precedes `width` in the payload header (`data=H,W,~payload`), stored as `mask.height` (mask rows) and `mask.width` (mask cols). Records with `frame != 0`, or whose `(w,h)` disagree with each other across records, or whose mask dims disagree with frame dims when a mask is present, fail closed to `unknown:fix_photo`.

Policy `photo-geometry/v1` (reviewable, checked-in constant):

- Zero records after a completed stream is `not_detected`. This classification needs NO invented frame dims: when the record list is empty the frame argument may be `None` and the result is still `not_detected`. Invalid frame dims only matter when records exist.
- Fail closed on invalid dimensions/coordinates when records exist (non-positive `w/h`, `x2<x1`, `y2<y1`, out-of-frame box, mask dims mismatch, `frame != 0`, inconsistent `(w,h)` across records) → `unknown:fix_photo`.
- `possible_clipping`: box touches frame edge within 2 px (inclusive coordinates) OR box area < 2% of frame area OR box area > 98% of frame area. Area uses inclusive extent: `area = (x2-x1+1) * (y2-y1+1)`, `frame_area = w * h`.
- `detected`: exactly one record passing all gates above.
- Multi-object ambiguity (2 or more records): `unknown:needs_review`, no auto-select of a "best" box.
- Labels are only `detected | not_detected | possible_clipping | unknown`. Copy never claims "fully visible" or "whole object visible"; `detected` means only "one in-frame candidate passed the size/edge gates". Cut-off pixels cannot be recovered by any later step.

Crop (client-side only, volatile, never persisted): for a single `detected` record the server may return a volatile preview hint computed by `suggest_crop` (pad 8% EACH side with the basis being the OBJECT BOX width and height, then clamp to frame, inclusive coordinates). Multi-match and all non-`detected` states offer no crop. The suggested crop only subsets existing pixels; the original file is always preserved and download stays a local blob anchor. The preview hint is carried in the volatile `PhotoPreview` response object only (see section 5), never written to the DB row or the receipt.

## 5. API boundary (strict DTOs, no raw persistence)

Transport: `POST /api/runs/{id}/photo-check` accepts exactly one image as a single JSON body field `image_data_uri` of the form `data:image/{png|jpeg};base64,<payload>` with a strict bound (decoded raw max 1 MiB; rejects empty, oversize, non-image magic, animated/multi-frame bytes). Server validates magic bytes and decoded image format/dims via stdlib only, never filename alone. No paths, no URLs, no second image, no multipart variant of this contract.

Pydantic DTOs (exact names; status codes are exact, never ranges):

```
PhotoCheckIn: {image_data_uri: str, expected_revision: StrictInt}
PhotoCheckOut: {method: "sam-3.1" | "not_run", label: PhotoLabel | None,
  reason: str, policy_version: "photo-geometry/v1",
  revision: int, photo_state: PhotoState}
PhotoRemoveIn: {expected_revision: StrictInt}
PhotoRemoveOut: {revision: int, photo_state: "no_photo",
  approval_state: "pending_approval"}
PhotoPreview: {frame_w: int, frame_h: int,
  crop: {x1: int, y1: int, x2: int, y2: int} | None,
  label: "detected"}
PhotoCheckResponse: {receipt: Receipt, preview: PhotoPreview | None}
```

Status codes: invalid body/empty/oversize/bad magic returns 422; stale or missing `expected_revision` returns 409; exhausted budget or non-approved bytes returns 422 with a `reason` naming the cause; keyless/unconfigured SAM returns 200 with `method: "not_run"` and honest copy; duplicate concurrent same-key check returns 200 with the winner's persisted summary (pending while in flight, never a faked finished summary); parallel different-image same-revision check returns 409; stale-revision finalization returns 409 and never attaches.

Server holds the image in memory only for the duration of the Files-to-Responses sequence, then drops it. No disk write, no DB bytea, no log of bytes, no receipt/export inclusion, no preview endpoint.

Client keeps the file in an `objectURL`/canvas only, revokes on change/unmount. Client never sends geometry, verdict, source, actor, or budget; the server recomputes verdict from its own parse plus policy and stamps actor/time from existing auth (`auth.actor`).

History: superseded photo decisions are immutable (`revision_history` entries plus `audit` rows append-only); a new photo event never mutates a prior entry.

## 6. Paid-call safety (durable admission, one-shot budget)

Gate: operator `SAM enable` flag plus verified preflight (key present, pricing/balance checked against the existing max-$1 envelope for the ONE approved file below), default OFF. Keyless callers get `method: "not_run"`, HTTP 200, honest UI ("SAM not configured, photo unchecked").

The single already-approved paid test is EXACTLY the byte identity of `DSC_3252_demo_1600.jpg` (the 1067 by 1600 derivative, operator-verified sha256 recorded in preflight evidence), not a filename class and not any other photo sharing that name. Admission binds to that operator-verified digest: until a new explicit approval exists, the paid path admits only those exact bytes; budget alone never authorizes a different image. Current provider balance is UNVERIFIED and no real calls happen in this design work. Config defaults keep SAM OFF and the global budget at 0.

Bounded sequence per admitted check: at most one Files upload plus at most one Responses call, and the Responses call happens only if Files returned a valid file ID. No retries.

Durable admission (Postgres, migration plus runtime CRUD roles, no implicit DDL): a `sam_budget` single-row table (`id = 'global'`, `remaining_images INT DEFAULT 0 CHECK >= 0`) and a `sam_calls` ledger. Admission runs in ONE transaction BEFORE ANY HTTP: lock the budget row `FOR UPDATE`, require `remaining_images > 0`, decrement by exactly 1, insert the `sam_calls` row as `admitted` under unique key `(run_id, revision)`, bump the pack revision and clear approvals in the same transaction. Any stale `expected_revision`, any parallel different-image admission for the same `(run_id, revision)`, and any second paid image while the global grant is spent are refused BEFORE any HTTP (409 for stale/parallel-image, 422 for exhausted budget or non-approved bytes). There is no public budget reset and no epoch choice; budget changes happen only through operator-controlled migration/backfill outside the public API.

Terminal semantics: `succeeded` (with a stored label), `failed_terminal` (accepted-but-unparseable, ambiguous, crashed, timed out, or invalidated by a concurrent clear/text change before finalization), and in-flight `admitted` are never auto-resent. A duplicate same-key arrival while `admitted` returns 200 `pending`, never a faked finished summary. A duplicate after terminal state returns the persisted summary. Finalization rechecks `expected_revision` plus the idempotency key under row lock; if the revision moved (concurrent clear or text edit landed first), finalization aborts to `failed_terminal` and attaches nothing to the receipt. This spend bound limits calls; it does not verify provider balance.

## 7. Receipts, approvals, exports

Every photo decision writes a receipt event (`photo_checked` with the sanitized summary) and every approval/export writes its own receipt; a photo event bumps revision so stale `expected_revision` approvals fail 409 exactly like text edits.

`exportable()` gains a photo clause: `photo_status in (none, checked_ok)` where `checked_ok` is ONLY `detected` on the current revision plus a fresh human pack approval on that same revision. `not_run`, `requested-unchecked`, `unknown`, `not_detected`, and `possible_clipping` all refuse export with 422 naming the photo reason. There is no override path around this clause.

## 8. Privacy

Private control metadata lives ONLY in the `sam_calls` row (the sha256 digest and the provider file ID needed for idempotency and debug) and in server logs at most as an opaque call ID. The sanitized receipt/export/log payload holds ONLY `{label, reason, policy_version, actor, time}`. No image bytes, no image hash, no filename, no provider file ID, no box/mask geometry, and no raw SAM text appear in any receipt, export, log line, or scan-visible artifact. PII path of any private raw PDF is never copied into public docs. All geometry/file-ID examples in code and tests are hand-authored by us (synthetic boxes), never captured provider output.

## 9. Acceptance (all hold)

1. Keyless browser: select photo, Check returns `not_run` 200 honesty; approve refused 422 with the photo reason and export refused 422 with the photo reason.
2. Remove photo clears the attachment, bumps revision, resets approval, and export never contains the old photo.
3. Invalid dimensions/coordinates and multi-match both fail closed to `unknown`.
4. Concurrent duplicate checks issue one paid sequence; in-flight duplicate returns pending; history entries immutable.
5. All 16 pre-existing human-review browser assertions still pass unchanged; no raw bytes, hashes, file IDs, or geometry in any persisted artifact (scan test).
