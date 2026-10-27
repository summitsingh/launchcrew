# LaunchCrew Connector Plan, Oct 27 evening, planning and read-only layer only

Status: plan only. Stage C integrates documentation only, no connector code is built or authorized in this stage.
Priority, Summit Oct 27 evening: Build Drive and Instagram connectors FIRST, instead of a local photo library.
Order: Google Drive and Instagram first, Dropbox second, Facebook Page photos last and deferred for now.
Sequence rule, unchanged: v1 locks first, v2 build starts only after v1 is locked. Connector building is part of the v2 photo and Designer work, after v1 lock, not a reason to delay or break v1. If connector work slips, submit v1 at minimum, with connectors as additional demo only if ready and verified.

## Google Drive connector, read-only first
- Purpose: source product and brand photos for LaunchCrew packs and SAM visual checks, without a local photo library.
- Read-only layer first:
  - List folders and files, read metadata, search by name or folder, in that order.
  - Download only shortlisted images, after a human explicitly selects them in the LaunchCrew UI, never bulk download, never sync a whole Drive.
  - Never overwrite originals, never rename, move, or delete a Drive file. All writes are local LaunchCrew receipts and local copies of shortlisted images only, with the source file ID recorded.
  - Record in every receipt that uses a Drive photo: source file ID, file name, folder path if available, download time, and the LaunchCrew run id. No file content in receipts, only metadata and IDs.
- Auth and tokens: server-side only, never in code, repo, chat, or client storage. Token passed via environment at runtime only, never stored in the repo. No token in logs, receipts, or demo video.
- Scopes, to be confirmed at build time from the official Drive API docs, read-only scopes only in this slice. No write, delete, or share scopes in the read-only layer.
- Failure handling: a Drive failure leaves the pack in pending_approval with a reason, no silent retry, no duplicate download without a new shortlist.
- No prior code will be reused, all connector layers will be newly built, demo data only as input.

## Instagram connector, read-only first, via Instagram API with Unified Login
- Account: @summitleather.co only, professional account. No other account in any connector step.
- Read-only layer first:
  - Profile and media reads, using instagram_basic for profile and media reads, as confirmed from the Permissions page Oct 27.
  - List media, read media metadata, download only shortlisted media, after a human explicitly selects it, never bulk download.
  - Draft queue: any pack, caption, or media selected for a possible post goes into a draft queue, with approval gate per specific pack, receipt store, and disconnect.
  - Receipt store: record account ID, media ID, caption draft, approval state, and verification result, never a token, never a password.
  - Disconnect: one tap, removes the stored token, marks packs disconnected, exports receipts if requested.
- Publish gate, STILL OPEN, strict: Instagram publish code remains GATED on business portfolio plus App Review and Live mode confirmation. Do NOT write publish, login, or OAuth publish code until that gate is confirmed, while planning is authorized now and read-only building can start only after v1 lock in a later stage.
  - What read-only building means, exactly: an API client that calls graph.facebook.com with a token supplied via environment at runtime, plus draft queue, approval gate, receipt store, and disconnect. It does NOT include a login URL, code exchange, OAuth flow, or publish endpoint call.
  - What is NOT authorized yet: any code that creates a login URL, exchanges a code for a token, requests instagram_content_publish in a live login flow, or calls a publish endpoint.
  - Open gates to report at build time: business portfolio confirmation for @summitleather.co, App Review status for instagram_basic and, later, instagram_content_publish, Live mode status, and whether the app is owned by the portfolio that owns the Instagram assets.
- Tokens: server-side only, never in code, repo, chat, or client storage. Token passed via environment at runtime only, never logged.
- No auto-post, auto-send, or auto-publish from any connector step, in any slice.

## Dropbox, second
- Read-only layer, same pattern as Drive: list, metadata, download only shortlisted files, never overwrite originals, record source file ID in receipts, tokens server-side only.
- Build only after Drive and Instagram read-only layers are verified, unless Summit reorders explicitly.

## Facebook Page photos, last and deferred for now
- Deferred, do not build in the hackathon slice unless Summit reorders explicitly.
- If built later: read-only, Facebook Page photos only, same draft queue, approval gate, and receipt rules, no auto-post.

## Connection verification and read-only test results, to be reported at build time
- For each connector, report: connection method used, account or folder verified, read-only call made, number of items listed, number downloaded, receipt IDs created, and any failure with error type only.
- Report the open portfolio and App Review gates for Instagram, with the exact gate status, not a guess.
- Report that no prior code was reused. All connector layers must be newly built during the hackathon window.
- No token, password, file content, or personal data in any test report or public repo.

## Implementation limits
- No Instagram publish, login, or OAuth publish code, until the portfolio plus App Review and Live mode gate is confirmed.
- No Drive write, delete, share, or overwrite code, in the read-only slice.
- No auto-post, auto-send, or auto-publish, from any connector.
- No connector build in the LaunchCrew repo until v1 is locked, to avoid conflicting with the Stage B v1 run currently in progress.

## Strict new-work rule, Oct 27 evening

ALL work for this hackathon will be NEW for this hackathon. Do not reuse, copy, or port code from ai-instagram-organizer, ai-job-pilot, Koru Shield, or any other prior codebase into LaunchCrew submitted work, even if marked as pre-existing. All submitted code, connector layers, workflows, and demo features must be newly built Oct 26 to Nov 4, 2026, and clearly identified as such in README and submission. Demo data only (brand facts, demo idea, demo photos) may be used as input, but demo data is not code and must not be claimed as new code. Do not claim prior organiser dedupe or scoring logic as hackathon work in any form. No prior code will be reused, all connector layers will be newly built, demo data only as input.

The coordinator's read-only Oct 27 audit found no prior code copied into this repository. Evidence supplied by the coordinator: git log shows one root commit 37a358a on Oct 27, all repo files dated Oct 27, and grep for ai-job-pilot, jobpilot, instagram-organizer, Koru Shield code, TruckBux, daemon_call, bw-mcp, daemon.sock, and the LLM_ key pattern returned only context mentions in AUTOMATION-PLAN.md and DEPLOY-CHECKLIST.md about isolating from Koru Shield production, plus a ProofPilot application context mention, not code. scripts/verify_sam.py is status only, 407 bytes, with no network call, daemon socket, or mask parsing, and is not a copy of any prior SAM test script. This is a grep and git history check, not a full code similarity scan. These findings describe that coordinator snapshot; Stage C adds documentation references to this audit and rule.

## Selection and action limits

Shortlisted means explicitly selected by a human only. No automated screener, ranking, scoring, or shortlisting. V1 remains approval plus export only. No auto-post, auto-send, auto-pay, auto-submit, or auto-publish. No connector implementation, Drive code, Instagram code, Dropbox code, or Facebook code in Stage C. Read-only API details and scopes are supplied planning inputs and must be checked against official docs at build time.
