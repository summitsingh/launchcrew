# Photo Review (SAM Geometry Check) — Design

**Date:** 2026-10-28 · **Status:** proposal, no implementation · **Source geometry:** https://dev.meta.ai/docs/sam/reading-segmentation and https://dev.meta.ai/docs/sam/segmenting (plain references; do not fetch with product key).

## 1. Problem

`backend/sam.py:verify_demo_photo` only records segmentation `completed` (including zero matches) and never makes a visibility/crop decision. The proposal adds a real visual photo check to Run review without changing the original session rule (photo optional, Checker still blocks visual flaws) and without persisting raw photos or asserting full-object visibility from a box alone.

## 2. Goals / non-goals

Goals: optional per-run photo in existing Run review; explicit separate SAM check action; deterministic, reviewable geometry verdict; local crop suggestion/download preserving the original; receipt per decision/approval/export.
Non-goals: no full scene understanding, no verification of provider balance/credits, no new auth provider/scope, no generated/faked product pixels, no raw-image persistence or server preview endpoint.

## 3. UX lifecycle (bound to run + current revision)

States per run revision: `no_photo` → `photo_selected_local` → `check_requested` → `checked:{detected|not_detected|possible_clipping|unknown}`. Transitions: select/preview (client-only), explicit Check (server SAM call), Clear/Remove (explicit audit event), any saved photo change invalidates approval atomically exactly like human text edits (`DELETE FROM approvals` in the same transaction + `human_revised`-style audit entry).

Rules:

- Requested but `unknown` / unavailable / zero-match / `fix_photo` blocks approve and export. No-photo legacy text flow is unchanged.
- Explicit Remove clears the attachment, writes an audit row, resets approval, and never exports the old photo.
- Shared pack revision: photo attach/check/remove/clear bumps the same `current_revision` counter as `human_review.apply_revision` and goes through the same `expected_revision` + row-lock + current-approval-projection path. Because the current UI treats `revision > 0` as "human rewrote text," the UI copy must change to "revision N (text and/or photo)" and the revision-history entry must carry a `photo_event` discriminator (`text_revised | photo_attached | photo_checked | photo_removed`) so a photo-only bump never reads as rewritten text.

## 4. Geometry interpretation (deterministic, versioned)

Provider records stay volatile (boxes, masks, file IDs never persisted). The only persisted artifact is a sanitized summary: `{label, reason, policy_version, actor, time}`.

Authoritative frame semantics (from the source docs above): static image is frame 0; box is `(x1,y1,x2,y2,w,h)` in source pixels with `x2,y2` INCLUSIVE; `w/h` are source-frame dimensions (EXIF-oriented); mask `H` precedes `W`; zero-match `completed` is normal `not_detected`, never `visible`.

Policy `photo-geometry/v1` (reviewable, checked-in constant):

- Fail closed on invalid dimensions/coordinates (non-positive `w/h`, `x2<x1`, out-of-frame box, mask dims mismatch) → `unknown:fix_photo`.
- `not_detected`: zero records after a completed stream.
- `possible_clipping`: box touches frame edge within 2 px OR box area < 2% of frame OR box area > 98% of frame.
- `detected`: exactly one record passing the above gates.
- Multi-object ambiguity (≥2 records): `unknown:needs_review`, no auto-select of "best" box.
- Labels are only `detected | not_detected | possible_clipping | unknown`. Copy never claims "fully visible"; `detected` means "one in-frame candidate passed the size/edge gates."

Crop: client-side only. Single `detected` may offer a volatile pad-and-clamp preview (pad 8% each side, clamp to frame, canvas transient). Multi-match offers no crop. A crop never restores missing pixels; the original file is always preserved and the suggested crop only subsets existing pixels. Download is a local blob anchor.

## 5. API boundary (strict DTOs, no raw persistence)

- Transport: `POST /api/runs/{id}/photo-check` accepts exactly one image, max 1 MiB raw. JSON base64 (`data:image/{png|jpeg};base64,…`, bound ≈ 1.4 MB string) is preferred to avoid multipart deps; server validates magic bytes, never filename alone. No paths, no URLs, no second image.
- Server holds the image in memory only for the duration of the Files→Responses sequence, then drops it. No disk write, no DB bytea, no log of bytes, no receipt/export inclusion, no preview endpoint.
- Client keeps the file in an `objectURL`/canvas only, revokes on change/unmount. Never sends geometry, verdict, source, or actor from the client; the server recomputes and stamps actor from existing auth (`auth.actor`).
- History: superseded photo decisions are immutable (`revision_history` entries + `audit` rows append-only); a new photo event never mutates a prior entry.

## 6. Paid-call safety (durable admission, one-shot budget)

- Gate: operator `SAM enable` flag + verified preflight (key present, pricing/balance checked against the existing max-$1 envelope for the one approved `DSC_3252_demo_1600.jpg`-class test) default OFF. Keyless callers get `method:not_run`, HTTP 200, honest UI ("SAM not configured — photo unchecked").
- Bounded sequence per check: at most one Files upload + at most one Responses call, and the Responses call happens only if Files returned a valid file ID. No retries.
- Durable admission: a Postgres `sam_calls` row (migration via Alembic, runtime CRUD roles, no implicit DDL) is inserted as `admitted` under a unique idempotency key `(run_id, revision, photo_sha256)` before any HTTP. Accepted/ambiguous/crashed calls are terminal — never auto-resent. Concurrent duplicate checks admit at most one (unique constraint wins; loser returns the winner's persisted summary). Budget is server-controlled (`sam_budget remaining`, default 0); no client budget claim or epoch choice. This bounds spend; it does not verify provider balance.
- Pre-existing constraint restated: the already-approved human test is exactly one upload + one SAM iff the upload succeeds, max $1 existing credits, pricing/balance/enforceable bound verified FIRST. Balance is currently UNVERIFIED and no real calls happen in this design work.

## 7. Receipts, approvals, exports

- Every photo decision writes a receipt event (`photo_checked` with the sanitized summary) and every approval/export writes its own receipt; a photo event bumps revision so stale `expected_revision` approvals 409 exactly like text edits.
- `exportable()` gains a photo clause: `photo_status in (none, checked_ok)` where `checked_ok` is `detected` or reviewer-overridden `possible_clipping`; `unknown/not_detected/requested-unchecked` refuses export with 422.

## 8. Privacy

No source/data/raw photo in repo, images, logs, receipts, or exports. PII path of the private raw PDF is never copied into public docs. All geometry/file-ID examples in code and tests are hand-authored by us (synthetic boxes), never captured provider output.

## 9. Acceptance (must all hold)

1. Keyless browser: select photo → Check shows `not_run`; approve/export refused with the photo reason.
2. Remove photo clears attachment, resets approval, and export never contains the old photo.
3. Invalid dimensions/coordinates and multi-match both fail closed to `unknown`.
4. Concurrent duplicate checks issue one paid sequence; history entries immutable.
5. All 16 prior strong browsers still pass; no raw bytes in any persisted artifact (scan test).
