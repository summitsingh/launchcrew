# Demo recording usage, source only

Status: SOURCE ONLY. No video has been created. No site or model claim is
verified by these docs. Root runs the harness after terminal checks plus live
proof, then verifies the actual output. This page covers only the recording
script plus narration. No app, API, infra, or model behavior was changed.

## What this is

- Harness: `web/scripts/record-demo.mjs` (Node, existing Playwright 1.56.1,
  ffmpeg and ffprobe, macOS say). No new deps, no install, no provider APIs.
- Narration: `docs/demo-narration.md` (2m50 target, 3 minute hard limit).
- Edit: ONE decision list cuts evidence holds to slots 12, 20, 26, 24, 18,
  15, 13, 17, 18, 7, plus optional 8s Spark. Total at most 180.
- Runtime: Node 24 with pnpm 10, as pinned at the repo root. The harness
  resolves the existing `web/node_modules` Playwright install.

Recording after required feature proof is already authorized. Final video
approval, upload, publication, and any Cerebral submission remain separate
gates with separate taps.

## Quick start for root

Dry run first (readonly, creates nothing):

```sh
node web/scripts/record-demo.mjs --dry-run --base-url https://launchcrew.summitsingh.com
```

Show all options:

```sh
node web/scripts/record-demo.mjs --help
```

Record after live proof (creates demo runs through the real UI):

```sh
node web/scripts/record-demo.mjs --record --base-url https://launchcrew.summitsingh.com
```

With a stored Spark proof readback on the same base URL (optional, explicit
silent 8s slot apart from the keyless wallet):

```sh
node web/scripts/record-demo.mjs --record \
  --base-url https://launchcrew.summitsingh.com \
  --spark-run-id <actual-stored-run-id>
```

With a private sanitized SAM summary for the pixel free card (optional, only
after actual confirmed correlation by root):

```sh
node web/scripts/record-demo.mjs --record \
  --base-url https://launchcrew.summitsingh.com \
  --sam-proof /private/path/sam-proof.json
```

## Gates

`--record` refuses unless all of these pass before any mutation:

- Base URL is verified HTTPS.
- `GET /api/health` is status ok with auth disabled_demo and approval_by
  demo_placeholder, using the actual schema from source.
- `GET /api/auth/status` is enabled false with empty user and live_verified
  false.
- `GET /api/model-capabilities` shows spark, wonder, and SAM all not
  configured, with spark and wonder variants not_configured. No new endpoints
  are used and no paid test calls are made.
- `GET /` returns 200.
- Narration doc exists and contains every segment id, with no em dash.
- Each offline say clip measures with ffprobe to fit its assigned EDL slot.
  Overrun refuses with a note to shorten the `SEGMENTS` say string plus the
  narration doc together. Doc only edits never change spoken audio.
- ffmpeg, ffprobe, and say are present. Voice defaults to the system voice
  with no download. A named `--voice` must already appear in `say -v`.
- Output dir is under `<repo>/.local` so IDs, evidence, and video stay
  private and gitignored.

Through capture the harness rechecks the keyless boundary and reads back each
new run plus each of the seven campaign day receipts. Every new wallet receipt
must show zero Spark calls, zero wonder attempts, deterministic fallback usage,
model_used none, and scout deterministic fallback, else refuse. The existing
AWS Spark receipt, if supplied, stays a read only separate proof and never
supports a claim that the new wallet used models.

Proof gates:

- Spark: `--spark-run-id` must read back a stored receipt on the same base
  URL with spark mode and nonzero stored Spark calls. Otherwise the run is
  refused or the flag is omitted and narration stays keyless only.
- SAM: `--sam-proof` must be a sanitized summary with method, scope,
  photo_state checked, nonzero segmentations, checked time, and revision. Any
  bytes, digest, provider ID, filename, geometry, crop, or image field refuses
  the SAM shot. Without this file the SAM segment is skipped and reported
  pending honestly. A private SAM run is never presented as living in the
  public AWS DB. The card labels a separate private host DB and a withheld
  jacket test photo.

The harness never clicks Check photo and never makes paid calls. Dry run
performs readonly navigation plus GET checks only.

## What gets recorded

All state comes from actual natural UI actions in a fresh Chromium context at
1600x900 with matching record video size. Scrolls and holds run inside actual
shot intervals and end on asserted evidence. DOM presence alone is never proof:

- Fictional wallet brief ($49, Austin commuters, Instagram).
- Custom PriceGuard checker with supported price_claims policy, shown against
  advisory only free text, enforced preview held readable.
- Actual Scout facts, sources, and risks, labelled demo or source provided,
  never web research, scrolled readable in the hold.
- Seeded unsupported claim through the explicit UI checkbox, labelled seeded
  demo, with genuine veto and revision.
- Replay of two actual run IDs from the session.
- Memory edit before and after from two actual UI runs, shown as a labelled
  prepared comparison with receipt derived block labels after exact receipt
  checks and no supersede. Save waits true UI close plus persisted readback.
- Seven distinct campaign day packs with per day approval, each card scrolled
  into the viewport and asserted readable in the hold. No batch approval.
- Optional pixel free SAM card only from validated proof, photo withheld,
  separate private host DB labelled, wallet not SAM checked.
- Human approve plus actual export download, stored timeline, submission not
  attempted, timeline scrolled readable.
- Closing card with public repo https://github.com/summitsingh/launchcrew and
  the recorded HTTPS site address on screen in the viewport for 7s. No
  localhost shown as public and no verified word printed in source.

No route interception, mocks, fabricated responses, fake LLM activity, direct
SQL seed, or API created state presented as UI. Responses may be observed to
collect run IDs, never replaced. Read only GET readbacks validate receipts,
memory, and campaigns. Any missing selector or failed check exits nonzero with
the failing step. No placeholder pass exists.

## Edit and outputs

One take is recorded, then ONE edit decision list keeps evidence holds in real
order and trims only identified setup, navigation, and run waits between
holds. No speedup, no reordered evidence, no fake pauses, no shortest truncate
of evidence. Audio clips are padded with silence to their slots, Spark gets a
silent slot, and captions use the same contiguous slot times, so video, audio,
captions, and manifest stay aligned.

All outputs are private under `.local/demo` (gitignored). Nothing with IDs,
evidence, video, or manifests is written to committed paths:

- `demo-ui.mp4`: remuxed full UI take.
- `trimmed-ui.mp4`: EDL cut evidence holds joined in order.
- `narration/*.m4a`: offline say clips, padded clips, plus the joined track.
- `launchcrew-demo.mp4`: final muxed video.
- `launchcrew-demo.srt`: captions from EDL slot times.
- `edl.json`: source in and out per hold, slot starts, trimmed spans.
- `shot-manifest.json`: EDL, segment holds, full private run IDs, proof
  provenance, ffprobe result.
- `shots/*`: actual screenshots plus labelled comparison, SAM, and closing
  cards.
- `clips/take.webm`: raw Playwright take, plus per EDL cuts.

Browser context is fresh with fictional data only. No desktop, key files,
cloud console, or existing screenshots are captured. Personal photos never
enter AWS, S3, ECR, CloudWatch, or the video. Contributor name and Cerebral
email are unknown and are never invented.

## Verification

The harness runs ffprobe on the final MP4 and refuses unless:

- Dimensions are exactly 1600x900.
- Duration matches the EDL total within 3s and is at most 180 seconds (target
  about 170).
- Audio track is present when narration is enabled.
- File size is nontrivial (readability sanity, not a content proof).

Root still checks the actual duration, sound, frame privacy, and receipt
claims by watching the private video, then opens it for user review. User
approval of the video, upload, publication, and any submission are separate.

## Files changed by this deliverable

- `web/scripts/record-demo.mjs` (EDL, keyless, closing card, memory, scroll)
- `docs/demo-narration.md` (matching say strings, slots, honesty labels)
- `docs/demo-recording-usage.md` (this file, gates and edit)

No tests were run in Muse for this source only task. Checks are UNRUN here by
design. Root reviews source and runs a meaningful dry run after exit.
