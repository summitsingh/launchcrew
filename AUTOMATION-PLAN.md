# Historical automation plan

The FastAPI and Postgres replacement uses README.md as its local runbook. File receipt storage below describes only the retained legacy CLI.

# LaunchCrew automation plan

## Machine fallback

Machine fallback rule, Summit Oct 27 evening:

- Primary: summit-amd, directory /home/summit/launchcrew, Codex gpt-6.1-sol, medium.
- If summit-amd becomes unavailable, fails, or Codex there stops working, continue on summits-mac-mini as usual.
- On Mac mini: Codex first, then Muse Code CLI with Muse Spark 1.3 contributor model as fallback if Codex on Mac mini also fails.
- Never controller VM, never Oracle enterprise account, personal account only, on any machine.
- If a switch happens, report the switch, the new directory, and any work that needs syncing from summit-amd, do not silently restart from scratch, and do not lose receipts, repo state, or deployment plan.
- Mac mini readiness, verified by coordinator Oct 27: hostname Summits-Mac-mini, arm64, via macmini-ssh, user summit, Codex at /opt/homebrew/bin/codex version 0.164.0, config model gpt-6.1-sol, model_reasoning_effort medium. Codex is NOT on the default PATH on Mac mini, so non-interactive runs must prepend /opt/homebrew/bin to PATH and close stdin.
- Mac mini currently has no ~/launchcrew directory. A switch requires cloning https://github.com/summitsingh/launchcrew and recovering any unpushed changes from summit-amd first, which is why pushing Stage B plus Stage C promptly matters.

## V1 completion

- Oct 30-31: deterministic Scout, Maker, Checker hardening, persisted partial-failure receipts, real human approval UI, and live Spark verification gate.
- Nov 1: SAM photo verification, direct Meta Model API only. Keep visual_verification not_run until implemented and verified.
- Nov 2: v1 failure cases; Replay diff belongs to v2 and starts only after v1 lock.
- Nov 3: 3-minute video and README polish.
- Nov 4: submit early before 9:00 PM ET. Summit performs the final submit tap.

V1 remains approval plus export only. Never auto-post, auto-send, auto-pay, or auto-submit. No real PII. Live Spark remains unverified; use deterministic_fallback until a Summit-approved live verification succeeds.

## V2 track, plan only

Sequence, strict: v1 Launch Pack first, complete and lock the v1 demo, then build a v2 slice, then Nov 4 submission. V2 planning starts now, v2 build starts only after v1 is locked. If v2 slips, submit v1 at minimum, with v2 as additional demo only if ready and verified.

V2 slice priority, confirmed: Memory v1, Replay diff, Campaign Week FIRST, then Support Crew, Designer, Analyst, and Instagram connector plan, in that order.

Connector priority for photo sourcing in v2: Google Drive and Instagram first, instead of a local photo library, Dropbox second, Facebook Page photos last and deferred for now. Drive read-only first: list, metadata, download only shortlisted images selected explicitly by a human, never overwrite originals, record source file ID in receipts. No automated screener, ranking, scoring, or shortlisting. Instagram read-only first, via Instagram API with Unified Login, @summitleather.co only, professional account, instagram_basic for profile and media reads, draft queue, approval gate, receipt store, disconnect. Instagram publish code remains gated on business portfolio plus App Review and Live mode. Do not write publish, login, or OAuth publish code until that gate is confirmed. Tokens server-side only, supplied through the environment at runtime, never in code, repo, chat, logs, receipts, or client storage. No auto-post, auto-send, or auto-publish. This stage writes plan documents only, no connector code.

See V2-PLAN.md and CONNECTOR-PLAN.md for the integrated plans. V1 remains approval plus export only. No auto-post, auto-send, auto-pay, or auto-submit. No screener, ranking, scoring, or shortlisting.

## Strict new-work rule, Oct 27 evening

ALL work for this hackathon will be NEW for this hackathon. Do not reuse, copy, or port code from ai-instagram-organizer, ai-job-pilot, Koru Shield, or any other prior codebase into LaunchCrew submitted work, even if marked as pre-existing. All submitted code, connector layers, workflows, and demo features must be newly built Oct 26 to Nov 4, 2026, and clearly identified as such in README and submission. Demo data only (brand facts, demo idea, demo photos) may be used as input, but demo data is not code and must not be claimed as new code. Do not claim prior organiser dedupe or scoring logic as hackathon work in any form. No prior code will be reused, all connector layers will be newly built, demo data only as input.

The coordinator's read-only Oct 27 audit found no prior code copied into this repository. Evidence supplied by the coordinator: git log shows one root commit 37a358a on Oct 27, all repo files dated Oct 27, and grep for ai-job-pilot, jobpilot, instagram-organizer, Koru Shield code, TruckBux, daemon_call, bw-mcp, daemon.sock, and the LLM_ key pattern returned only context mentions in AUTOMATION-PLAN.md and DEPLOY-CHECKLIST.md about isolating from Koru Shield production, plus a ProofPilot application context mention, not code. scripts/verify_sam.py is status only, 407 bytes, with no network call, daemon socket, or mask parsing, and is not a copy of any prior SAM test script. This is a grep and git history check, not a full code similarity scan. These findings describe that coordinator snapshot; Stage C adds documentation references to this audit and rule.

## AWS isolated deployment preparation

Target: launchcrew.summitsingh.com, the confirmed demo-only exception. Keep it isolated from Koru Shield production: separate IAM role and resources, no production data, no production credentials, no shared secrets. Provisioning is approved in principle when the web UI is ready, in the Koru Shield AWS account, under the LaunchCrew-demo-only exception. DNS creation for this subdomain is included; no other DNS change to the parent domain of launchcrew.summitsingh.com is authorized. The cost cap amount is still pending from Summit before actual provisioning; the DEPLOY-CHECKLIST.md cost cap field stays blank until Summit fills it. Do not provision in this stage. Report resource inventory and estimated cost before deployment and actual resources and cost afterward. Teardown window: after Nov 4 through Nov 9.

Concrete resources for coordinator pricing and confirmation:

- One smallest suitable container host or serverless container for the Python standard library web UI, preferably App Runner or a public container endpoint reachable through Cloudflare.
- Cloudflare DNS record for launchcrew.summitsingh.com, mapped to the selected service endpoint according to its custom-domain instructions.
- TLS certificate and custom-domain validation, with HTTPS end to end.
- Bounded logs with retention and cost controls, without request bodies, headers, keys, or PII.
- Separate IAM runtime and deployment roles, minimal permissions, isolated storage only if needed for receipts.
- No database in v1 unless the coordinator explicitly approves one. No load balancer unless required.

Recommend us-east-1 for coordinator confirmation. File receipts require a single instance and writable runs directory. Serverless ephemeral storage may lose receipts on restart; coordinator must choose an appropriate demo storage lifecycle and verify this limitation before deploying. The old Dockerfile is superseded by the Podman Containerfiles. See README.md and docs/aws-prep.md for the replacement stack. Do not provision AWS or create DNS in this run.

## AWS and DNS findings

Coordinator verified Oct 27, supplied evidence, not re-queried in this run: AWS account 492767006483, user koru-admin, aws-cli 2.37.5 on summit-amd. Route53 hosted zones are empty in that account. Both the parent domain of launchcrew.summitsingh.com and korushield.com use Cloudflare nameservers walt.ns.cloudflare.com and fish.ns.cloudflare.com. The target launchcrew.summitsingh.com currently resolves to nothing according to that snapshot. Use Cloudflare, not Route53, for the deployment DNS record. The selected AWS endpoint must be reachable from that record with TLS. No other subdomain is authorized.

## Public repository

Public repo: https://github.com/summitsingh/launchcrew. Coordinator handles creation history, scan-verified micro-commits, and push. This run does not initialize git, change origin, or push. Before each coordinator micro-commit, run the tests and repository scan and inspect the diff. README must identify hackathon-only work, demo data, and approval plus export only. No credential stores or existing keys may be consulted.

## Video

Record a 3-minute demo using a live web UI run only: wallet idea, seeded Checker block case, revised draft, human approval, and export. Show no auto-post, no live employer portal, no real PII, and only hackathon-built work. The UI creates normal clean runs; generate the seeded demo receipt locally with the documented CLI command, then open that receipt in the UI to show the block and revision alongside a fresh live UI run.

## Submission gate

Do not submit in this run. Final project is LaunchCrew, Indie track, Build for Your World, v1 plus v2 plan if ready. Submission execution remains gated until demo, repo, video, and deployment are ready, with a final submit check at that time. ProofPilot was only the Oct 13 event application idea, not the final submission project.

Package checklist:

- Public repository URL.
- Demo URL if deployed.
- 3-minute video link.
- Team list confirmed by Summit.
- Hackathon-only work clearly identified.
- Indie track, Build for Your World.
- Submission before Nov 4 9:00 PM ET.
- Final submit tap required from Summit at that time, after the demo is ready.

## Current approvals and gates

- Public repo v1: done.
- Stage B push: pending coordinator verification.
- AWS provisioning: approved in principle when the web UI is ready, cost cap amount pending from Summit before actual provisioning.
- DNS for launchcrew.summitsingh.com: approved under the LaunchCrew-demo-only exception, Cloudflare only, no other DNS change to the parent domain of launchcrew.summitsingh.com.
- Live Spark test: approved but not yet run.
- Live SAM test: approved but not yet run.
- Final submission: gated until demo, repo, video, and deployment are ready, with a final submit check at that time. If deployment slips, record an explicit decision to submit v1 with a localhost demo video.
