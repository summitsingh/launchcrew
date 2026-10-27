# LaunchCrew V2 Plan, Oct 27 evening

Status: plan only. No v2 code is built in Stage C.

Sequence, strict: v1 Launch Pack first, complete and lock the v1 demo, then build a v2 slice, then Nov 4 submission. V2 planning starts now, v2 build starts only after v1 is locked. If v2 slips, submit v1 at minimum, with v2 as additional demo only if ready and verified.

## V1 lock criteria, all must be true before v2 build starts
- Oct 30-31 milestone complete and verified: hardening, partial-failure receipts, web approval UI, tests pass, scan pass, grep counts 0.
- Public repo at https://github.com/summitsingh/launchcrew updated with v1 plus Oct 30-31 changes, public, scan verified.
- Live Spark test complete, one call, demo data only, key via environment on summit-amd only, model, token counts, and success or error type recorded, no key material.
- Live SAM test complete, demo photo only, direct api.meta.ai only, method, model, box or mask summary, and success or error type recorded, no key material.
- Web approval UI demo verified through HTTP: create run, approve, export, with a clean final check.
- AWS deployment at launchcrew.summitsingh.com verified live, or, if deployment slips, a clear decision recorded to submit v1 without a live deployment, with the demo video showing the localhost web UI.
- If any lock criterion fails, v2 build does NOT start, and the submission package stays v1 only.

## V2 slice, plan order, CONFIRMED by Summit Oct 27 evening
V2 slice priority, confirmed: Memory v1, Replay diff, Campaign Week FIRST, then Support Crew, Designer, Analyst, and Instagram connector plan, in that order.
1. Memory v1 and Replay diff.
   - Memory: brand facts, agent profiles, past approvals as examples, blocked claims as rules, editable and deletable, exportable, no auto-learning without approval.
   - Replay: same idea, two Checkers, diff outputs, proving personalities change outcomes. Replay is a demo artifact, not a background job.
   - Demo: run the wallet idea with Checker A and Checker B, show the diff, show memory updated from the approved run only.
2. Campaign Week.
   - One campaign idea in, a week of drafts out, each day as a separate pack, each pack approved separately, nothing posts automatically.
   - Uses the newly built LaunchCrew Launch Pack, Memory, and Checker, with a campaign facts file per week.
3. Support Crew.
   - Support Triager plus Drafter, draft replies only, approval per reply, no auto-send, no inbox connection in the hackathon slice unless Summit approves a read-only connection separately.
   - Uses the newly built LaunchCrew claim check against brand facts and support rules.
4. Designer and Analyst agents.
   - Designer: visual brief and crop variant only, using SAM visual check, no fake product images, no auto-post.
   - Analyst: reads approved packs and receipts, produces a summary report, no auto-action, insights only.
5. Instagram Unified Login connector plan.
   - Planning now; read-only draft-queue and approval implementation only after v1 lock in a later stage. Publish, login, and OAuth remain gated.
   - Gate, still open: Summit must confirm business portfolio plus App Review and Live mode before any Instagram publish, login, or OAuth code is written.
   - Connector plan: CONNECTOR-PLAN.md. Read-only first with instagram_basic as the supplied planning permission; verify scopes and API details against official docs at build time. Future publish or additional scopes require separate gate confirmation.
   - V2 read-only connector demo, only after v1 lock in a later stage: @summitleather.co only, profile and media reads, draft queue, approve a specific pack for export, receipt recorded, disconnect test. Publishing remains a separately gated future action; no publishing is authorized in Stage C.

## V2 scope, what is NOT in the hackathon v2 slice
- No marketplace, no multi-company, no daily ops loop, no CRM, no HR, no Finance Crew in the hackathon slice, unless Summit reorders the slice explicitly.
- No auto-post, auto-send, auto-pay, auto-submit, no screener, ranking, or scoring, in any v2 slice.
- No Instagram publish, login, or OAuth code until the gate above is confirmed. Read-only work is planned for after v1 lock in a later stage; no connector code in Stage C.

## V2 build order, after v1 lock
- Step 1: Memory v1 storage and Replay diff, with tests, receipt fields for memory and replay, and a demo run.
- Step 2: Campaign Week, using the newly built LaunchCrew Memory and Launch Pack, with per-day approval.
- Step 3: Support Crew, draft only, with approval per reply.
- Step 4: Designer and Analyst agents, with SAM visual check for Designer and receipt summary for Analyst.
- Step 5: Instagram connector plan. Read-only implementation is possible only after v1 lock in a later stage; publish, login, and OAuth code remain gated. Unbuilt connectors stay clearly marked as planned in README and submission.
- In a later authorized stage, each step gets its own coordinator-managed micro-commit push to the public repo, after scan verification, and its own demo check. A step that fails verification is dropped from the submission demo, not shipped broken.

## Connector priority, Oct 27 evening, for photo sourcing in v2
- Build Drive and Instagram connectors FIRST, instead of a local photo library. Order: Google Drive and Instagram first, Dropbox second, Facebook Page photos last and deferred for now.
- Drive: read-only first, list folders and files, read metadata, download only shortlisted images, never overwrite originals, record source file ID in receipts.
- Instagram: read-only first, via Instagram API with Unified Login, @summitleather.co only, professional account, instagram_basic for profile and media reads, draft queue, approval gate, receipt store, disconnect. Instagram publish code remains gated on portfolio plus App Review and Live mode, do NOT write publish, login, or OAuth publish code until that gate is confirmed.
- Tokens server-side only, never in code, repo, chat, or client storage. No auto-post, auto-send, or auto-publish from any connector.
- No prior code will be reused, all connector layers will be newly built, demo data only as input. No prior organiser dedupe or scoring logic may be claimed as hackathon work.
- Full integrated connector plan: CONNECTOR-PLAN.md, planning only, no connector code built yet, connector build starts only after v1 is locked in a later stage.

## Stage C execution boundary

Stage C runs on summit-amd only, in /home/summit/launchcrew, with Codex primary. Do not switch to Muse Code, push, or change the remote. Machine fallback notes in the supplied draft are future planning context and do not authorize a switch in this stage.

## Submission package, with v2
- Minimum submission, always ready: v1 Launch Pack, public repo, 3-minute video, AWS deployment if ready, Indie track, Build for Your World, hackathon-only work Oct 26 to Nov 4 clearly identified.
- Additional demo, only if ready and verified: v2 slice steps that passed verification, shown as a separate section in the video and README, clearly marked as v2, with the same approval plus export rule.
- Final submission execution remains gated until demo, repo, video, and deployment are ready, with a final submit check at that time. Do not submit now.
- AWS target, confirmed: launchcrew.summitsingh.com, isolated from Koru Shield production, teardown after Nov 4 to Nov 9.
- Public repo: https://github.com/summitsingh/launchcrew, v1 commit 37a358a, Stage B updates to follow as micro-commits.

## Strict new-work rule, Oct 27 evening

ALL work for this hackathon will be NEW for this hackathon. Do not reuse, copy, or port code from ai-instagram-organizer, ai-job-pilot, Koru Shield, or any other prior codebase into LaunchCrew submitted work, even if marked as pre-existing. All submitted code, connector layers, workflows, and demo features must be newly built Oct 26 to Nov 4, 2026, and clearly identified as such in README and submission. Demo data only (brand facts, demo idea, demo photos) may be used as input, but demo data is not code and must not be claimed as new code. Do not claim prior organiser dedupe or scoring logic as hackathon work in any form. No prior code will be reused, all connector layers will be newly built, demo data only as input.

The coordinator's read-only Oct 27 audit found no prior code copied into this repository. Evidence supplied by the coordinator: git log shows one root commit 37a358a on Oct 27, all repo files dated Oct 27, and grep for ai-job-pilot, jobpilot, instagram-organizer, Koru Shield code, TruckBux, daemon_call, bw-mcp, daemon.sock, and the LLM_ key pattern returned only context mentions in AUTOMATION-PLAN.md and DEPLOY-CHECKLIST.md about isolating from Koru Shield production, plus a ProofPilot application context mention, not code. scripts/verify_sam.py is status only, 407 bytes, with no network call, daemon socket, or mask parsing, and is not a copy of any prior SAM test script. This is a grep and git history check, not a full code similarity scan. These findings describe that coordinator snapshot; Stage C adds documentation references to this audit and rule.

## Integrated connector plan

Connector priority for photo sourcing in v2: Google Drive and Instagram first, instead of a local photo library, Dropbox second, Facebook Page photos last and deferred for now. Drive read-only first: list, metadata, download only shortlisted images selected explicitly by a human, never overwrite originals, record source file ID in receipts. No automated screener, ranking, scoring, or shortlisting. Instagram read-only first, via Instagram API with Unified Login, @summitleather.co only, professional account, instagram_basic for profile and media reads, draft queue, approval gate, receipt store, disconnect. Instagram publish code remains gated on business portfolio plus App Review and Live mode. Do not write publish, login, or OAuth publish code until that gate is confirmed. Tokens server-side only, supplied through the environment at runtime, never in code, repo, chat, logs, receipts, or client storage. No auto-post, auto-send, or auto-publish. This stage writes plan documents only, no connector code.

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


## Current approvals and gates

- Public repo v1: done.
- Stage B push: pending coordinator verification.
- AWS provisioning: approved in principle when the web UI is ready, cost cap amount pending from Summit before actual provisioning.
- DNS for launchcrew.summitsingh.com: approved under the LaunchCrew-demo-only exception, Cloudflare only, no other DNS change to the parent domain of launchcrew.summitsingh.com.
- Live Spark test: approved but not yet run.
- Live SAM test: approved but not yet run.
- Final submission: gated until demo, repo, video, and deployment are ready, with a final submit check at that time. If deployment slips, record an explicit decision to submit v1 with a localhost demo video.

AWS provisioning is approved in principle in the isolated Koru Shield AWS account when the web UI is ready. The cost cap amount remains blank in DEPLOY-CHECKLIST.md until Summit fills it. Cloudflare DNS only, because the supplied snapshot found empty Route53 hosted zones and Cloudflare nameservers for the parent domain of launchcrew.summitsingh.com. No provisioning or DNS creation in Stage C. Teardown after Nov 4 to Nov 9.

Human selection is the only meaning of shortlisted here. No automated screener, ranking, scoring, or shortlisting. Stage C creates no connector code.
