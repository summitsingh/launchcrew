# LaunchCrew: submission draft, review only, not submitted

Status: DRAFT ONLY. This document is a reviewable submission draft, prepared locally on Oct 27, 2026, updated Oct 28, 2026 for the user-authorized local Mac fallback. No submission has been made. No video has been recorded. No deployment has been made. No live demo URL is live. Every item marked TODO is a gate that must be closed with evidence before a final submission tap, and no TODO item may be presented as done in a final submission. Changes after f70d107 are pending independent verification and are not claimed as verified in this draft.

## Title and track

- Project title: LaunchCrew
- Track: Indie Developer
- Theme: Build for Your World
- Event: Meta Global AI Developer Hackathon, Cerebral Valley, Oct 26 to Nov 4, 2026
- Submission deadline, per Participant Guide checked Oct 27, 2026: Nov 4, 2026, 9:00 PM ET
- Submission representative: solo, one person. No name is printed in this repo draft, to keep the public repo free of personal information, and the representative name is entered on the submission form itself at final submission time. No other team member is listed here, and no teammate identity is invented. If a teammate is added later, that person must be added by name, with consent, before submission, and this draft must be updated first.

## Problem, audience, and what LaunchCrew does

Problem: a solo founder starting from an idea must research, write, check, and launch in separate tools, with no single verifiable pack to approve before anything is published, sent, or paid for.

Audience, demo: a solo founder launching a first product on Instagram, demo idea: Vegan leather wallet, $49, for Austin commuters, launch on Instagram. Demo data only, no real product, no real customer data, no real personal data.

What LaunchCrew v1 does, in one session under 10 minutes, demo only:
1. One idea in, one sentence plus price plus audience.
2. Three agents run in sequence, each with a distinct role and system prompt.
3. A Launch Pack is produced: sourced facts, risks, one post draft, one email draft, and a Checker verdict per item.
4. A human approves or blocks the pack, then exports it. Nothing posts, sends, or spends automatically. No auto-publish, no auto-send, no auto-pay, no auto-submit.

## Agents, v1 scope only

- Scout, Skeptical Analyst, cautious, source-first, no guesses. Output: 5 facts with sources plus 3 risks, unverified items marked as unverified.
- Maker, Brand Voice Writer, warm, plain, no hype. Output: 1 post draft plus 1 email draft, every claim tied to a brand fact.
- Checker, Strict Auditor, blocks on unverified claims, visual flaws, and off-brand tone. Output: pass, fix, or block per item, plus a visual check if a photo is supplied, plus a final approval receipt.
- User-created Checker, demo plan: the demo shows a user-created Checker profile, named by the user in the recording, with its own rules, applied to the same pack, so the viewer can see a Checker difference, not just a fixed Checker. The user-created Checker is a profile, not a new agent role, and it does not override deterministic claim safety.

## Architecture, as built in the public repo, main 4bb295d

- Backend: Python, FastAPI, Pydantic v2, OpenAPI with a generated TypeScript client, SQLAlchemy plus Alembic, Postgres as system of record for runs, agents, memory, approvals, audit, and auth sessions.
- Frontend: Next.js, TypeScript, Tailwind plus shadcn/ui, TanStack Query, Vitest plus Playwright for tests, pnpm.
- Tests and CI: pytest for FastAPI, Vitest plus Playwright for Next.js, GitHub Actions CI on every push, uv for Python, pnpm for Next.js. CI on main, run 40618077504, commit 4bb295d, success, 5m 5s, verified Oct 27, 2026. That CI result is a workflow result, not a live deployment result.
- Containers: Podman, OCI compatible, non-root UID 10001, local build, run, and test with Podman. Local containers serve HTTP only, see live demo and TLS gaps below.
- Auth, planned, not live: Google sign-in and Facebook Login, both, scopes profile and email only, Google openid, profile, email, Facebook public_profile, email, no Drive or publishing scopes bundled. Tokens server-side only, no passwords stored. Auth is disabled by default, AUTH_ENABLED defaults false, health reports auth disabled_demo, approval_by demo_placeholder. Real sign-in is PLANNED, NOT LIVE, and must not be claimed as live until a verified sign-in run proves it.
- Model plug-in, server-side only: only POST /api/runs can call the model API. Deterministic facts checks run first, optional Wonder Scout synthesis with Spark fallback, Spark Scout synthesis, and one strict-JSON Spark candidate call each for Maker and Checker. Candidates are re-checked deterministically, Checker verdicts stay deterministic, no model suggestion can approve, unblock, or verify a claim. All other routes never call the model API. Next.js has no model client, no key, and no endpoint secret. The model key, when used for a live test, is used via META_API_KEY environment variable only on summit-amd, in memory only, never in chat, code, repo, logs, receipts, screenshots, .env, script, or test file.

## New-work attribution, exact

- All submitted code in this project was newly built Oct 26 to Nov 4, 2026, for this hackathon, in the public repo https://github.com/summitsingh/launchcrew, branch main, commit 4bb295d at the time of this draft, plus feature branches listed in the evidence matrix below, which are not merged to main at the time of this draft.
- No code was reused, copied, or ported from ai-instagram-organizer, ai-job-pilot, Koru Shield, or any prior codebase into LaunchCrew submitted work, per Summit direction Oct 27, 2026. Demo data only may be used as input, demo data is not code and must not be claimed as new code.
- Pre-hackathon work that is not submitted as new work: the accepted ProofPilot application, Oct 13 to Oct 14, 2026, and the earlier ai-job-pilot work, are not the final Nov 4 project. Final Nov 4 direction is LaunchCrew, not ProofPilot, confirmed by Summit tap Oct 27, 2026. ProofPilot is not claimed as LaunchCrew new work, and LaunchCrew is not claimed as ProofPilot work.
- Demo photos: DSC_3252.JPG and its downscaled derivative DSC_3252_demo_1600.jpg, jacket photoshoot, demo data only, untracked in git, not committed or pushed, not claimed as new code, not claimed as a product photo for a real product.

## Public repo and live demo target, verified versus planned, clearly labeled

- Public repo, VERIFIED: https://github.com/summitsingh/launchcrew, branch main, commit 4bb295d at the time of this draft, verified by git ls-remote Oct 27, 2026. Feature branches, local or pushed, are not main, and must not be presented as main until merged with evidence.
- Live demo target, PLANNED, NOT VERIFIED, NOT LIVE: https://launchcrew.summitsingh.com, subdomain for LaunchCrew demo only, DNS via Cloudflare, not Route53, per Summit decision Oct 27, 2026. DNS record NOT created at the time of this draft. Deployment NOT made at the time of this draft. No live demo URL may be shown as live in a final submission until a verified live run proves WEB 200, API 200, and WEB API 200 at that URL, with HTTPS verified, including the container target hop, see TLS gaps below.
- Local demo, VERIFIED as local only: local API and web on localhost, with deterministic demo runs, no live key, no deployment, no public URL. Local success is not deployment success, and local success is not browser success unless a rendered browser run proves it.

## Meta tooling, used versus planned, accurately labeled

- Muse Spark, USED, historical backend pass only, see evidence matrix: muse-spark-1.3 via api.meta.ai/v1, 3 Spark calls, 5,401 total tokens, run run_40c88a9d14ea48e18cb85386a86545c6, commit ea6666e, via FastAPI TestClient POST /api/runs, deterministic Checker still blocked a seeded unverified claim, approval and export both HTTP 200. This is a historical backend pass only, not a container pass, not a deployment pass, not a current retest, and not a browser pass. It must not be presented as current browser success.
- Muse Wonder, PLANNED, NOT DEMONSTRATED LIVE: Scout synthesis only, with Spark fallback, in code, no live Wonder call is claimed in this draft.
- SAM 3.1, HELD, NOT PASSED: see evidence matrix, SAM held preflight. No SAM pass is claimed.
- Muse Image, PLANNED, NOT DEMONSTRATED: only for a corrected crop variant, never a fake product image, in plan only, no live Image call is claimed.
- Muse Voice Transcribe, PLANNED, NOT DEMONSTRATED: idea input option only, no live Transcribe call is claimed.
- Muse Glimmer, PLANNED, NOT DEMONSTRATED: local triage only, no live Glimmer call is claimed.
- Muse Code, tooling only: the Participant Guide does not require, ban, or require disclosure of any specific coding tool, including Codex, Claude Code, or Muse Code, per Guide check Oct 27, 2026. Coding tool use is not claimed as a product feature.

## V2, crews, and connectors, planned unless demonstrated

- V2 first slice, INTEGRATED AND BROWSER VERIFIED at candidate f70d107, NOT MERGED to main: Memory, Replay, Campaign Week, in feature branch feature/v2-memory-replay-campaign, plus follow-up commits, with integrated verification in integration candidate branch feature/integration-candidate, head f70d107. Closeout evidence: backend pytest 67 passed, original unittest 38 passed, Vitest 14 passed, typecheck and build passed, contract paths 23 with clean regeneration, Playwright acceptance 1 passed in 9.1s. Audit confirmed every required V1 and V2 flow is exercised through rendered UI with no route interception, and all 11 acceptance artifacts exist with matching contents. V2 must not be claimed as merged until it is merged with evidence.
- Later crews, PLANNED ONLY, NOT BUILT AS SUBMITTED V1: Support Crew, Designer, Analyst, Research Crew, Drop Crew, Finance Crew with approve or hold, never auto-pay, Seller, templates. None of these are claimed as live in v1.
- Connectors, PLANNED ONLY, NOT LIVE: Drive and Instagram first, read-only, Dropbox second, Facebook Page photos last and deferred. Instagram connector gates are unconfirmed beyond pages read Oct 27, 2026, including business portfolio owner or admin, portfolio placement for the brand account, App Review and Live mode status, endpoint-by-endpoint permissions, rate limits, token lifetime, and separate business verification requirement. No connector is claimed as live, connected, or publishing in this draft. V1 export is export only, no auto-post, send, reply, scheduled auto-publish, no ads, no multi-account in Phase 1, no webhooks until checked and approved, no other social networks in this connector plan.

## Local fallback status, Oct 28, 2026, pending independent verification

- Build host: the user-authorized local Mac fallback, with three local worktrees (deploy-code, integration, submission-docs). The earlier summit-amd state is preserved, not deleted, and no remote writer is active.
- Last verified evidence: integration candidate f70d107 closeout only: backend pytest 67 passed, original unittest discover 38 passed, frontend Vitest 14 passed, typecheck and build passed, 23 contract paths with clean regeneration, Playwright integration acceptance 1 passed in 9.1s. Those counts stand as reported in closeout; nothing newer has been verified.
- New unmerged changes, NOT VERIFIED, pending an independent Codex run: deploy-code database role correction (valid PostgreSQL privileges, runtime DML plus usage and sequence rights with no DDL, default privileges for the migration identity that creates the tables, separate master password secret) and integration spec additions (seven distinct rendered campaign brief texts with API cross-check, campaign day export refusal before approval through both the run and campaign routes). Socket-dependent checks (Playwright browser run, disposable Postgres role verification) were explicitly not run in this restricted CLI and stay unverified.
- Gaps unchanged and still explicit: current live Spark retest, live SAM (held, no live calls), real identity sign-in, AWS deployment with DNS and TLS, container model test, demo recording (gated on SAM pass plus CI pass), merge, push, and submission. None of these is claimed as done.

## Evidence and gaps matrix

Status values: VERIFIED means a command, run, or rendered check produced the result named, with a receipt. PLANNED means in code, docs, or plan only, with no live or rendered proof yet. TODO means a gate that must be closed with evidence before final submission, and the evidence must be added to this matrix first.

| Item | Status | Receipt or gate |
| --- | --- | --- |
| Core V1, Scout, Maker, Checker, receipt, approval, export, deterministic claim check | VERIFIED, backend plus keyless browser acceptance at integration candidate f70d107, not merged to main | CI run 40618077504, commit 4bb295d, success, 5m 5s. Integration candidate f70d107 closeout: backend pytest 67 passed, original unittest 38 passed, Vitest 14 passed, typecheck and build passed, contract paths 23 with clean regeneration, Playwright acceptance 1 passed in 9.1s. Audit confirmed every required V1 flow is exercised through rendered UI with no route interception, and all 11 acceptance artifacts exist with matching contents. |
| User-created Checker, sourced facts, seeded unsupported claim blocked and revised, human approval and export receipt | PARTIAL: seeded claim blocked and revised, human approval, export receipt browser verified at f70d107; user-created Checker profile still pending | f70d107 acceptance renders a seeded unsupported claim blocked then revised, human approval, and an export receipt with submit_attempted false, and no attempted publication. A user-created Checker profile with its own rules is still not shown in the acceptance spec, so it stays PLANNED. Demo recording plan, docs/demo-recording-plan.md, gives the timed script. |
| Live Spark, muse-spark-1.3 | VERIFIED, historical backend pass only, NOT current, NOT container, NOT deployment, NOT browser | Run run_40c88a9d14ea48e18cb85386a86545c6, commit ea6666e, 3 Spark calls, 5,401 tokens, Checker blocked seeded unverified claim, approval 200, export 200, via TestClient plus standalone Postgres. TODO: current retest, container-path test with key at container start, and deployment test, each separately, before any current live claim. |
| Live SAM 3.1, end to end, checked true | HELD, NOT PASSED, NO LIVE CALLS until preflight evidence is available | Files 400 on original photo, files 200 on downscaled derivative DSC_3252_demo_1600.jpg, responses never run, checked true never recorded, provider file from derivative upload left until deleted, delete endpoint unconfirmed, files-only success is not a SAM pass. TODO: available credits for Summit specific account from an authoritative source, billed unit for /files plus a sam-3.1 /responses call, enforceable $1 bound or Summit direct Muse acceptance of the estimated $0.0025 per image with a hard stop after 2 calls as the bound, plus Summit direct Muse confirmation for the exact bounded scope, derivative only, product Accept text/event-stream, then responses only if files succeeds, model sam-3.1, jacket concept. No SAM options message until that preflight evidence is available, per Summit instruction Oct 27, 2026. |
| Memory consumption, edit and delete effects on later runs | VERIFIED at integration candidate f70d107, not merged to main | V2 branch implements Memory selection, edit changes next run, delete removes effect. f70d107 closeout: backend pytest 67 passed, Playwright acceptance 1 passed in 9.1s. Audit confirmed rendered Memory edit and delete browser steps with matching effects on later runs, and no route interception. |
| Replay, standard versus strict Checker difference | VERIFIED at integration candidate f70d107, not merged to main | V2 branch implements standard versus strict Checker profiles, Replay diff includes checker profile, blocked count, and draft change, deterministic claim safety enforced in both. f70d107 closeout: backend pytest 67 passed, Playwright acceptance 1 passed in 9.1s. Audit confirmed rendered Replay standard versus strict browser steps, and no route interception. |
| Campaign Week, 7 distinct briefs, per-day approval and export guards | VERIFIED at integration candidate f70d107, not merged to main | V2 branch implements 7 day-specific briefs, day 1 Origin story, day 2 Material and craft, day 3 Commuter use, day 4 Styling, day 5 Care and durability, day 6 Social proof, day 7 Launch offer, per-day approve and export delegating to single-run gates, no batch approve, no batch export, no auto-publish, blocked day refuses approval and export while another day proceeds. f70d107 closeout: backend pytest 67 passed, Playwright acceptance 1 passed in 9.1s. Audit confirmed rendered 7 day cards and per-day guard browser steps, and no route interception. |
| Auth, Google and Facebook sign-in, live | PLANNED, NOT LIVE | Auth hardening branch 8c49012, logout cookie expiry, rotation, expiry, mocked approval_by, provider checklist, scopes profile and email only. AUTH_ENABLED defaults false, health auth disabled_demo, approval_by demo_placeholder. TODO: provider credentials setup, HTTPS deployment, real sign-in run, with no passwords stored, tokens server-side only, approval_by provider subject, not demo_placeholder. |
| Deployment, AWS, Cloudflare DNS, TLS | PLANNED, NOT LIVE | AWS deployment proposal, workspace file launchcrew-aws-deployment-proposal.md, recommended Fargate plus ALB, $17.10 for 7 days, $28.57 for 12 days, App Runner revised with NAT egress, $19.51 for 7 days, $32.69 for 12 days, see proposal for corrections. TODO: cost cap choice by Summit after seeing estimate, deployment authorization tap, region confirmation us-east-1, explicit Cloudflare record authorization, origin and container HTTPS verified, database TLS verify-full verified, separate migration execution, teardown verification after Nov 4 and no later than Nov 9, 2026. Local containers serve HTTP only, so origin and container TLS must be added and verified before deployment, and ALB target HTTPS must be distinguished as hop encryption, not certificate identity validation, per AWS ALB docs. |
| Demo video, 3 minutes | PLANNED, NOT RECORDED, GATED | Outline at workspace file launchcrew-demo-video-outline.md, 3 minutes, target 2m50s, 7 sections, local UI only until deployment is verified live, final video approval by Summit before submission. TODO: record only after BOTH live SAM pass AND CI pass, CI now passes, SAM does not, so video stays gated, plus final video approval tap. |
| Final submission, Nov 4, 9:00 PM ET | TODO, NOT SUBMITTED | TODO: demo, repo, video, and deployment ready, plus Summit final submit tap, with this draft updated from the integration owner result, with all TODO items above closed with receipts, or explicitly removed from the final submission claims. Do not submit until those gates are closed. |

## What this draft does not claim

- No teammate identity is invented, no optional Meta tool is claimed as integrated unless the matrix above says VERIFIED, no connector is claimed as live, no deployment is claimed as live, no live demo URL is claimed as live, no video is claimed as recorded, no submission is claimed as made.
- Historical backend Spark smoke is not current browser success, local success is not deployment success, files-only SAM success is not a SAM pass, CI success is not deployment success, and a running Postgres process is not a test result.
- No banned project claim is made: LaunchCrew is applicant-side for a solo founder, with no employer use, no submit by default, demo on mock or consenting test forms only, never live employer portals, and no claim of mass auto-apply. Words for a banned project type are not used as feature claims in this draft.

## TODO gates, before final submission tap

1. CLOSED with f70d107 closeout evidence: backend pytest 67 passed, original unittest discover 38 passed, Vitest 14 passed, typecheck and build passed, contract paths 23 with clean regeneration, from integration candidate feature/integration-candidate at f70d107, counts as reported in closeout.
2. CLOSED with f70d107 closeout evidence plus audit: keyless Playwright acceptance 1 passed in 9.1s on isolated ports (API 8021, web 3021), rendered across V1 and V2, including Memory edit and delete effects, Replay standard versus strict difference, 7 distinct campaign briefs with 7 day cards, and per-day approval and export guards, with 8 screenshots, 2 export receipts, and summary.json, and no attempted publication. Audit confirmed all required flows are rendered UI with no route interception, and all 11 artifacts exist with matching contents.
3. TODO: SAM preflight evidence and, if approved in Muse chat directly, bounded SAM end-to-end test, or explicit removal of SAM pass from final claims, with SAM held status updated in this matrix.
4. TODO: current Spark retest, container-path test, and deployment test, each separately, or explicit scoping of the Spark claim to the historical backend pass only.
5. TODO: live auth, deployment, DNS, and TLS verification, or explicit scoping of the demo to local UI only, with no live demo URL claimed.
6. TODO: demo video recorded per docs/demo-recording-plan.md, after SAM and CI gates, with final video approval tap.
7. TODO: this draft updated from the integration owner result, with all matrix rows updated to VERIFIED or PLANNED, with receipts, and with no TODO item left presented as done.
8. TODO: Summit final submit tap, separate from all prior taps, with the final submission copy and video approved in full.
9. TODO: independent Codex verification of all post-f70d107 changes (deploy-code database roles and template, integration spec assertions), with actual counts and exit codes, or explicit scoping of claims back to the f70d107 closeout above.

End of draft. No submission, no upload, no deployment, no publication, no credential, no paid call was made to prepare this draft.
