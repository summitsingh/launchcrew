# Demo recording usage, source only

Status: SOURCE ONLY. No video has been created. No site or model claim is
verified by these docs. Root runs the harness after terminal checks plus live
proof, then verifies the actual output. This page covers only the recording
script plus narration. No app, API, infra, or model behavior was changed.

## What this is

- Harness: `web/scripts/record-demo.mjs` (Node, existing Playwright 1.56.1,
  ffmpeg and ffprobe, macOS say). No new deps, no install, no provider APIs.
- Narration: `docs/demo-narration.md` (2m50 target, 3 minute hard limit).
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

With a stored Spark proof readback on the same base URL (optional, shown
separately from the keyless wallet):

```sh
node web/scripts/record-demo.mjs --record \
  --base-url https://launchcrew.summitsingh.com \
  --spark-run-id <actual-stored-run-id>
```

With a private sanitized SAM summary for the pixel free card (optional, only
after actual confirmed correlation):

```sh
node web/scripts/record-demo.mjs --record \
  --base-url https://launchcrew.summitsingh.com \
  --sam-proof /private/path/sam-proof.json
```

## Gates

`--record` refuses unless all of these pass:

- Base URL is verified HTTPS.
- `GET /api/health`, `GET /api/auth/status`, and `GET /` all return 200.
- Narration doc exists and contains every segment id.
- ffmpeg, ffprobe, and say are present. Voice defaults to the system voice
  with no download. A named `--voice` must already appear in `say -v`.
- Output dir is under `<repo>/.local` so IDs, evidence, and video stay
  private and gitignored.

Proof gates:

- Spark: `--spark-run-id` must read back a stored receipt on the same base
  URL with spark mode and nonzero stored Spark calls. Otherwise the run is
  refused or the flag is omitted and narration stays keyless only.
- SAM: `--sam-proof` must be a sanitized summary with method, scope,
  photo_state checked, nonzero segmentations, checked time, and revision. Any
  bytes, digest, provider ID, filename, geometry, crop, or image field refuses
  the SAM shot. Without this file the SAM segment is skipped and reported
  pending honestly. A private SAM run is never presented as living in the
  public AWS DB.

The harness never clicks Check photo and never makes paid calls. Dry run
performs readonly navigation plus GET checks only.

## What gets recorded

All state comes from actual natural UI actions in a fresh Chromium context at
1600x900 with matching record video size:

- Fictional wallet brief ($49, Austin commuters, Instagram).
- Custom PriceGuard checker with supported price_claims policy, shown against
  advisory only free text.
- Actual Scout facts, sources, and risks, labelled demo or source provided,
  never web research.
- Seeded unsupported claim through the explicit UI checkbox, labelled seeded
  demo, with genuine veto and revision.
- Replay of two actual run IDs from the session.
- Memory edit before and after from two actual UI runs, shown as a labelled
  prepared comparison.
- Seven distinct campaign day packs with per day approval.
- Optional pixel free SAM card only from validated proof, photo withheld.
- Human approve plus actual export download, stored timeline, submission not
  attempted.
- Close on the public repo plus the verified HTTPS site address only.

No route interception, mocks, fabricated responses, fake LLM activity, direct
SQL seed, or API created state presented as UI. Responses may be observed to
collect run IDs, never replaced. Any missing selector or failed check exits
nonzero with the failing step. No placeholder pass exists.

## Outputs and privacy

All outputs are private under `.local/demo` (gitignored). Nothing with IDs,
evidence, video, or manifests is written to committed paths:

- `demo-ui.mp4`: remuxed UI take.
- `narration/*.m4a`: offline say clips plus the joined track.
- `launchcrew-demo.mp4`: final muxed video.
- `launchcrew-demo.srt`: captions from actual clip durations.
- `shot-manifest.json`: segment times, run prefixes, proof provenance.
- `shots/*`: actual screenshots plus labelled comparison and SAM cards.
- `clips/take.webm`: raw Playwright take.

Browser context is fresh with fictional data only. No desktop, key files,
cloud console, or existing screenshots are captured. Personal photos never
enter AWS, S3, ECR, CloudWatch, or the video. Contributor name and Cerebral
email are unknown and are never invented.

## Verification

The harness runs ffprobe on the final MP4 and refuses unless:

- Dimensions are exactly 1600x900.
- Duration is at most 180 seconds (target about 170).
- Audio track is present when narration is enabled.
- File size is nontrivial (readability sanity, not a content proof).

Root still checks the actual duration, sound, frame privacy, and receipt
claims by watching the private video, then opens it for user review. User
approval of the video, upload, publication, and any submission are separate.

## Files changed by this deliverable

- `web/scripts/record-demo.mjs` (new)
- `docs/demo-narration.md` (new)
- `docs/demo-recording-usage.md` (this file, new)

No tests were run in Muse for this source only task. Checks are UNRUN here by
design. Root reviews source and runs a meaningful dry run after exit.
