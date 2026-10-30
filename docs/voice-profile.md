# Voice profile (Slice 3)

Slice 3 adds an explicit voice style layer without changing factual
authority. Voice samples shape phrasing only. They never become
confirmed facts, never bypass Checker, and never authorize export.

All samples in code, tests, and docs are synthetic. No owner-approved
past posts exist in this repo and none are claimed. No Summit passages
are copied. Public Summit Leather site and social presence informed
tone direction only, not confirmed product facts and not post
ownership. No durability, shipping, or catalog facts are taken from
those sources.

## Shape and validation

Memory kind `voice_profile` holds:

- `examples`: 3 to 5 pairs of `{"input": str, "output": str}`
- `banned_terms`: optional list of up to 50 short terms

Validation rejects unknown keys, wrong counts, overlong text, empty
fields, and punctuation-only terms with HTTP 422. Memory kind is
immutable. Malformed selected voice content fails closed with HTTP
422 in selection, never facts and never silent clean. A later valid
voice in the same selection still applies; only the all-invalid case
raises.

Use synthetic samples only. Do not place real names, emails, account
IDs, photos, secrets, or other personal data in profiles.

## Selection and style-only boundary

The first valid `voice_profile` in `memory_ids` order wins. Its
examples feed Maker profile examples as untrusted style context. Its
banned terms become Checker vetoes.

- Keyless drafts are identical with and without a voice that carries
  no banned terms. Style alone does not change deterministic output.
- A voice example containing an unsupported claim does not authorize
  that claim. Checker still blocks it.
- `content.claim` on a voice profile never enters the factual
  allowlist. Only `brand_fact` claims and explicitly confirmed owner
  facts do.

## Checker veto

`check_pack` accepts an optional voice snapshot and ref. Banned terms
only add blocks with concrete reasons naming profile title, version,
and term. They never verify an unverified claim.

Whole-word matching is Unicode case-insensitive. Multiword terms
match across whitespace and punctuation separators. No regular
expressions are used. Checker and human recheck scan full post and
full email alongside claims and sentences, so a term such as blue
moon still blocks when written across sentence punctuation or
newlines as Blue. Moon. Factual and policy blocks are preserved,
and a concrete voice reason is added even when another rule already
blocks the same candidate.

## Pipeline and receipt

`run_pipeline` accepts a versioned voice snapshot and ref. It filters
v2 claims containing banned terms so v1 records the block and v2
stays clean. The receipt stores:

- `voice_profile`: id, title, version, digest, example count, banned
  term count, banned terms list, style-only notice
- `voice_stale`: true only after the selected voice is edited or
  deleted

Failure receipts carry `voice_profile` null when no voice applied.
Style samples stay in Memory and never enter the approval binding
payload as text.

## Human review and approval binding

Recheck uses the receipt voice snapshot, so later Memory edits cannot
rewrite past proof. Approval binding covers voice source, version,
digest, counts, and banned terms plus facts, copy, policy, photo, and
check. Tampering with voice terms invalidates the binding.

Editing or deleting a selected voice marks dependent pending,
running, and completed runs in the same workspace `voice_stale`,
clears approvals and binding, appends a `voice_invalidated` audit
event, and requires a new human revision check before export.
Pending receipts carry the selected voice id plus stable version
and digest binding at accept time under row lock, sync saves
recheck the binding under row lock without holding a transaction
over model calls, and async finalization preserves a concurrent
stale marker under row lock and never silently reapproves. History
preserves the prior voice context for audit. Failed runs stay
untouched because they are already not approvable.

## Channel variants (tested helper only)

`channel_variants.build_channel_variants` is a tested helper with no
backend or web production callsite. Channel candidates containing
banned terms refuse with `needs_revision` status, a concrete voice
reason, and no exported text. Provenance records voice title,
version, and banned term count when enforced. Clean candidates
record `voice_blocked` false. Candidates are presentation only and
still require downstream current approved Checker and receipt
binding. Still missing product integration: no run product flow,
receipt field, API route, or UI calls the helper, so no live channel
UI capability is claimed from helper tests.

## Receipt, Replay, and UI

- `Receipt.voice_profile` and `Receipt.voice_stale` expose the
  selected source and staleness.
- `RunDiff` carries `voice_id`, `voice_title`, and `voice_version`
  for each side plus `voice_changed`.
- Memory view supports `voice_profile` with a synthetic-only hint
  and explicit JSON shape guidance.
- Receipt record shows a Voice row plus a Voice block with source,
  version, counts, notice, and stale state.
- Replay shows a Voice source changes section with a style-only note.

## Actor isolation

Voice samples stay in the actor workspace. Memory reads, run reads,
and invalidation filter by `workspace_id`. Cross-actor fetch returns
404. Invalidation touches only pending, running, and completed runs
in the same workspace whose receipt voice id matches. Other
workspaces, failed runs, and other voice ids are untouched.

Existing SAM and actor boundaries are unchanged. Photo checks,
Google auth gating, and workspace seeding keep their current
behavior.

## Contracts

- `backend/openapi.json` includes `voice_profile` Memory kinds,
  `Receipt.voice_profile` and `Receipt.voice_stale`,
  `RunDiff` voice fields, and the `VoiceProfileSection` schema.
- `web/src/lib/schema.d.ts` matches those contracts, including the
  `voice_profile` Memory kinds and voice section types.

## Limitations

- No controlled with-voice or without-voice edit runs have been
  measured. See `docs/voice-edit-measurement.md` for the bounded
  protocol and unmeasured placeholders.
- No owner-approved past posts are available or claimed.
- Public site and social links are tone input only, not evidence.
