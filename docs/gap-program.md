# LaunchCrew gap program

Goal: close every repo-roadmap gap with code-only slices that run green
without provider credentials. Live-gated paths stay fail-closed with
named owner actions. One micro-commit per slice, pushed to main.

## Done

- Slice A (09d5eec): AI media creative packs for owner-shot media.
  POST /api/runs/{run_id}/media-creative, metered by the global model
  budget, 402 at zero, 503 keyless, draft provenance on the receipt.
- Slice B (6afbdaa): owner focal-point crop variants. Migration 022,
  POST /api/media/assets/{asset_id}/focal-point, focal-consistent
  plain generation, original facts asserted intact.
- Slice C (d2ffc31): owner-saved post templates with gated apply.
  Migration 023, /api/owner-templates CRUD plus apply through the
  normal pipeline with the missing-core gate and no template waiver.
- Slice D (8945a07): seat roles on workspace keys. Migration 024,
  owner/editor/viewer, viewer keys read-only (403 otherwise), role
  selector in the agent surfaces panel.
- Slice E (135e3e7): Drop and Finance crew presets, each with one
  distinct enforced Checker policy, seeded through the existing spine.

## Next, in order

- Slice F (17f9be1): engagement triage intake. Pure deterministic
  classifier (question, complaint, praise, spam risk, neutral) over
  owner-logged comments and DMs, suggested reply drafts, approve then
  mark handled. No auto-send. Live comment pull stays gated on
  platform tokens.
- Slice G (dcac907): voice memo intake. Transcript-text draft source
  attached to a run with voice_transcript provenance, revision bump,
  and reset approval. Real transcription stays gated on a speech
  provider.
- Slice H (this commit): cloud storage connector mirroring the Drive
  intake shape, unconfigured by default: config detection, status
  reporting, and authorize plus callback routes that refuse closed.
  No provider HTTP exists, so every path runs green keyless. OAuth
  app and tokens stay owner-gated.

## Out (owner-gated, not buildable here)

- Rendered image, video, and audio bytes (no generative media provider).
- Live Spark and SAM proofs (credits and budget).
- Google Drive values and redirect URI, second account for two-user
  proof, demo video, final submission, teardown verification.
