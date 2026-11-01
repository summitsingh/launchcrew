# Proposal acceptance matrix, Oct 31, 2026

Scope: the 8-page proposal (human-furnished source text, reviewed Oct 28; the private working copy is not cited as public proof) mapped against actual
implementation, tests, and the live deployment on main at `482b652413e5cf2e8bd3a34412e3ca0ea5696e85`. Live site: https://launchcrew.summitsingh.com (stack launchcrew-demo in us-east-1 UPDATE_COMPLETE, Alembic 001 through 021 on RDS with exitCode 0). Latest user direction
(Muse Code CLI sole author, main only, personal) overrides the proposal
line that named Codex primary on summit-amd. No tests were run to write
this matrix; evidence below is read from source, tests, and
prior rendered and live runs. Saved `../verification-*.log` files are local operator
notes only, never the sole public proof: each row names the public source or
test path that carries it, live rows name the live endpoint receipt, and earlier CI proof is the public run
https://github.com/summitsingh/launchcrew/actions/runs/40695455958. No row is claimed VERIFIED beyond the evidence named
in its row. Phase A (M3 through M14) is 10 of 10 CLOSED_VERIFIED, Phase B (S1 through S5) is 5 of 5 CLOSED_VERIFIED, and Phase C (SC1 through SC6 in build order SC1, SC2, SC4, SC3, SC5, SC6) is 6 of 6 CLOSED_VERIFIED, all on the live site. M1 (Live Spark model budget), M2 (Live SAM photo check), and M6 (Google Drive OAuth) are BLOCKED_EXTERNAL with keys configured and honest fallback reporting. Optional Wonder, Image, Voice, Glimmer, and the remaining roadmap crews (Drop, Finance, Seller, templates) stay roadmap unless
built and verified; they are not claimed. History: the Oct 28 matrix covered main at `a6cd81f` with keyless deployment only; that keyless state is superseded by signed-in live auth.

## Core one-brief flow

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| One idea plus price plus audience in, one approved pack out | BUILT, verified keyless | Demo idea fixed in UI copy; `POST /api/runs`, `/api/runs/async`, `/api/campaigns` in `backend/app.py`; host `5a186a5 --all` TERMINAL exit 0, saved log `../verification-5a186a5-all.log` (local operator note; public proof is CI run 40695455958 plus the named source and test paths in this matrix) |
| Scout, then Maker, then Checker, then revision, then recheck, then receipt | BUILT | Pipeline order in `launchcrew/run.py`; async step rows in `backend/run_jobs.py` plus migration `004_run_steps`; browser run-progress flow `web/tests/e2e/run-progress.spec.ts` in the 24-browser host pass |
| Receipt per step: proposed, checked, blocked, approved, time | BUILT | Receipts in `launchcrew/receipts.py`; API receipt routes; no synthetic overwrite of unconfirmed terminals |

## User-defined agents, rules, veto

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| Agent fields: name, role, personality, expertise (paste or file), rules, veto | BUILT | Agent CRUD, clone, preview in `backend/app.py`; approval level fixed `approve_each`; spend limit 0; tools allowlisted |
| Personalities change outcomes within supported rules; free text stays advisory | BUILT for supported Checker policies only | `checker_profile` standard vs strict in `backend/app.py` plus `launchcrew/run.py` `check_pack`; Replay diff shows profile change in `backend/app.py` diff rows; `backend/tests/test_v2_acceptance.py` plus `web/tests/e2e/stage-selection.spec.ts`. Limits: name, role, personality, expertise, and non-matching decision_rules or veto_scope entries are prompt advisory text only and never override deterministic checks; only exact-match supported policies are enforced (`superlatives`, `price_claims` per `launchcrew/checker_policies.py`; all other free text is recorded advisory). Arbitrary custom personality effects are not guaranteed |

## Scout facts, Maker claims, Checker verdict

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| Scout: 5 facts with sources plus 3 risks, unverified marked | BUILT | `launchcrew/facts.py` plus `launchcrew/run.py`; deterministic claim check; seeded `best in Texas` blocked with reason claim not in facts file |
| Maker: 1 post plus 1 email, every claim tied to a brand fact | BUILT | Maker revision excludes blocked claims; final blocked count 0 required before approval |
| Checker: pass, fix, or block per item; revision path | BUILT | Checker verdicts deterministic; model suggestions never approve, unblock, or verify; `tests/test_claim_check.py` |
| Photo visual check with upload | KEYLESS only, SAM unproven | Product route `POST /api/runs/{run_id}/photo-check` in `backend/app.py`: the explicit Check POST sends bytes to LaunchCrew validation (`backend/photo_input.py` parse, 1 MiB and 8 megapixel bounds, sha256 computed) and keyless returns `method: not_run` over HTTP 200 with bytes held server-side per the receipt transport note, never forwarded to SAM. Keyed path admits only exact allowlisted sha256 bytes via `backend/photo_admission.py` against the private `sam_calls` control ledger (`backend/migrations/versions/003_photo_sam_calls.py`; sha256 stored in Postgres for admission replay, never in receipts, logs, or UI), then one Files plus one Responses call, no retry, 30s budget (`backend/sam.py` transport only parses geometry in memory and discards it before receipts). Geometry in receipts is browser transient before Check. Tests: `backend/tests/test_photo_review_api.py` plus `backend/tests/test_photo_sam_admission.py`; browser: real keyless flow in `web/tests/e2e/human-review.spec.ts` (route-interception free) versus labelled synthetic mocks in `web/tests/e2e/photo-synthetic.spec.ts` (deliberate `page.route`, never live SAM). Transient photo SAM still REAL and UNPROVEN; responses never ran; no live SAM claim |

## Human gates, no auto actions

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| Human edit, approve, export; per-day Campaign approval | BUILT | Pending approval default; export refused before approval (422); per-day Campaign gates delegate to single-run gates, no batch approve or export, no auto-publish |
| No auto-post, send, pay, submit | BUILT, extended by authorized publishing | Default posture unchanged: pending approval, export refused before approval (422), no batch approve or export, no auto-publish outside authorization. Phase C adds the single authorized path: only S4 Ready slots execute, under the Approval Law, with binding re-check at execution, bounded retries (max 2), and a global kill switch (SC2). Viral generation is credit-capped and fails closed with HTTP 402 at 0 credits (SC5). `scripts/check-repo-text.py` clean (0 em dashes, 0 legacy brand strings) |
| Memory edit and delete effects; Replay shows different Checker; 7 distinct Campaign days with individual approval | BUILT | `backend/tests/test_v2_acceptance.py` (brand-fact edit, blocked-rule delete, profile diff, 7 briefs); `CAMPAIGN_BRIEFS` day 1 Origin through day 7 Launch offer in `backend/app.py`; migration `002_v2_memory_campaign.py` |

## Model and tooling claims

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| Spark per agent, strict JSON, deterministic first | BLOCKED_EXTERNAL (M1) | Keys configured in AWS (spark_configured=true on live GET /api/model-capabilities); live runs honestly report deterministic_fallback until provider credits are enabled. History: Oct 27 backend pass, 3 calls, 5,401 tokens (see the matching dated historical entry in `docs/submission-draft.md` and `docs/verification.md`; no run ID is repeated here); NOT current, NOT container, NOT browser, NOT deployment |
| Wonder synthesis with Spark fallback | CODE only, no live proof | `launchcrew/wonder.py` present; no live Wonder call claimed |
| SAM 3.1 photo check | BLOCKED_EXTERNAL (M2) | Keys configured in AWS (sam_configured=true on live GET /api/model-capabilities); live runs honestly report not_run until provider credits or allowlist are enabled. History: product SAM OFF, global budget 0; bounded jacket test needs actual balance plus enforceable $1 preflight; exact approved asset is not public video authorization |
| Image crop variant, Voice input, Glimmer triage | ROADMAP, not demonstrated | No live calls claimed; crop preview volatile, never persisted |
| Stdlib-only core | CORE STDLIB, full web stack separate as proposed | `launchcrew/` pipeline modules import stdlib only (`argparse`, `copy`, `json`, `os`, `re`, `pathlib`, `urllib`, `http.server`, `datetime`; no third-party imports), covered by `tests/test_claim_check.py` and related core suites. The shipped product path is FastAPI plus Next.js plus Postgres, which the proposal itself describes as the Oct 30 to 31 milestone, so the core reads stdlib while the full web stack is a separate explicitly proposed layer |
| Support Crew, Designer, Analyst, Research; Drop, Finance, templates, seats | Support, Designer, Analyst, Research BUILT and verified live; Drop, Finance, templates, seats ROADMAP, not built | Built presets ship alongside Checker, Maker, Scout on live GET /api/agents (Phase A M8, commits d4ea0c0 and 42f4a9c). Unbuilt crews are not claimed |
| Drive, Instagram, Dropbox connectors; Facebook connector and Facebook Login skipped | Facebook Login REMOVED from proposal scope per owner direction (Phase A M4); social connections BUILT and verified live (Phase C SC1) | SC1 `backend` social routes: priority platforms (instagram, facebook, threads, x, tiktok, pinterest, youtube, linkedin), flag-gated platforms (reddit, wordpress, discord, telegram), personal-account 422 block, encrypted tokens at rest, live capability sync into S2, one-tap disconnect. Google Drive OAuth (M6) is BLOCKED_EXTERNAL, not live. Publish path is Ready-slot autonomous execution under the Approval Law with binding re-check at execution, plus global kill switch (SC2). Remaining Dropbox-style connectors stay PLANNED only, not live |

## Phase A, Correction and Live Verification (10 of 10 CLOSED_VERIFIED)

Live site https://launchcrew.summitsingh.com on main at `482b652413e5cf2e8bd3a34412e3ca0ea5696e85`. Live Google OAuth sign-in succeeds in browser; GET /api/health returns `{"status":"ok","auth":"enabled_unverified","approval_by":"signed_in_user"}` and GET /api/auth/status returns `{"enabled":true,"providers":["google"]}`.

| Milestone | Claim | Evidence and limitation |
| --- | --- | --- |
| M3 (92f598a) | Campaign facts and 5 added angles | Custom facts draft all 7 days without wallet copy, verified live |
| M4 (051e63f, bffb324) | Facebook Login removed from proposal scope | Per owner direction; remaining auth is Google sign-in only |
| M5 (7866eee, 42f4a9c) | Facts library, variant confirmation, missing-facts waiver | /api/fact-products, /api/fact-variants/{id}/confirm, 422 waiver prompt, verified live |
| M7 (a49f211, 2f1489f, 42f4a9c) | Memory add/delete, Slice 3 voice panel | /api/memory plus voice-eval-summary panel, verified live |
| M8 (d4ea0c0, 42f4a9c) | Custom agents and 4 crew presets | Analyst, Checker, Designer, Maker, Research, Scout, Support on GET /api/agents, verified live |
| M9 (bf0b247, 42f4a9c) | Quickstart templates, persistent Replay diff | /api/quickstart-templates (fictional=true, confirmation_required=true), launchcrew.replayDiff, verified live |
| M10 (3441a5e) | Public plans page, waitlist | /plans page plus POST /api/waitlist, verified live |
| M11 (d745244, 41d847f) | Sitemap, favicon, demo facts | /sitemap.xml, /favicon.ico, /facts/demo_facts.json all HTTP 200 on the live site |
| M12 (cf1f101, 42f4a9c) | Server-bound approval integrity | Copy refused 422 before approval, 200 with approval-binding/v1 after, verified live |
| M13 (3823219) | Per-actor workspace isolation | Two distinct authenticated sessions; actor B gets 404 on actor A's run, verified live |
| M14 (c000101, 24cf7d6) | Honest status, banners, labels | /api/health, /api/auth/status, /api/model-capabilities, run receipts, verified live |

## Phase B, Social Pipeline S1 to S5 (5 of 5 CLOSED_VERIFIED)

| Slice | Claim | Evidence and limitation |
| --- | --- | --- |
| S1 (649a188) | Content calendar | Week and month views, empty-slot gap indicators, POST /api/calendar/campaigns/{id}/place creating 7 slots, run approval auto-advancing slot status, verified live |
| S2 (69177be) | Format library, brand kit, capability cards | POST /api/formats/check blocks 1-frame carousel with 422 and passes 6 frames at 4:5; brand-kit/v1 on receipts; channel capability cards; verified live |
| S3 (ce5b753) | Trend format picker | /api/trend-formats with mandatory source_label; deterministic superlative screening (guidance_only=true, fact_source=false); verified live |
| S4 (c080c2f) | Schedule slots, Validate Gate, schedule export | 3-condition gate (pack_approved, format_passed, variants_approved) with zero override button; unapproved slot refused 409; schedule-export/v1 JSON export; verified live |
| S5 (42ea1dc) | Cross-post verification board | /api/calendar/slots/{id}/deliveries/{channel}/verify and mark-posted; pending to posted to verified with exact text match versus mismatch detection; outcome capture (/outcomes); verified live |

## Phase C, SocialClaw SC1 to SC6 (6 of 6 CLOSED_VERIFIED, build order SC1, SC2, SC4, SC3, SC5, SC6)

Approval Law (Autonomy Revision, Owner Decision Oct 31, 2026): authorization is the S4 Ready gate (pack approved, format check passed, all selected channel variants approved). Once a slot is Ready, the SC2 executor can post autonomously at the scheduled time without a per-post tap, while re-checking the approval binding at execution time (any post-approval edit drops the slot to needs_approval and skips execution).

| Slice | Claim | Evidence and limitation |
| --- | --- | --- |
| SC1 (bdef0ed) | Social account connections | /api/social/platforms, connect, callback, disconnect; priority platforms plus flag-gated platforms; personal-account 422 block; encrypted tokens at rest; live S2 capability sync; one-tap disconnect preserving receipts; verified live |
| SC2 (d7a8014) | Autonomous Ready-slot publish executor | /api/publish/execute-due, per-slot execute, kill-switch; SHA-256 idempotency key; bounded retries (max 2); binding re-check at execution; verified live |
| SC4 (6c662c9) | Media library | /api/media/assets upload-once with SHA-256 digests; non-destructive 4:5 (1080x1350), 1:1, 16:9, 9:16 derivatives; multi-channel attachment without re-upload; Checker aspect-ratio validation; verified live |
| SC3 (86b4761) | Provider analytics pull | Per-delivery and scheduled refresh restricted to verified S5 posts (409 on unverified); source_label plus fetched_at; calendar outcome badges; unreported metrics shown as not reported, never fake zeros; verified live |
| SC5 (7511fba) | Viral format generator | /api/viral-generator/generate and /credits; 3 to 10 screenshots or 1 recording plus confirmed facts; Checker pass as normal pending_approval run; per-workspace credit cap failing closed with HTTP 402 at 0 credits before any provider call; verified live |
| SC6 (482b652) | Agent surfaces | Workspace-key REST API (/api/agent/* with hashed X-LaunchCrew-Workspace-Key), hosted MCP server (/api/mcp/tools, /api/mcp/call), CLI schedule apply, installable skill (/api/agent-surfaces/skill, skills/launchcrew-socialclaw/SKILL.md); identical S4 validation logic; verified live |

## Required gaps (source untouched, next task)

1. Exact CI `40695455958` for `a6cd81f` was TERMINAL SUCCESS, confirmed from the saved run log `../verification-ci-a6cd81f-success.log` (24 browser passed in 2.3m; container path PASS with no model calls; job ends Complete): https://github.com/summitsingh/launchcrew/actions/runs/40695455958. History only. Current main `482b652` carries ECR images published in GitHub Actions Run 41258578330 with stack UPDATE_COMPLETE (operation 5c9d7a60-d58f-11f1-9d85-0affffcc81a7), plus the local suite (673 pytest, 352 Vitest across 40 files, tsc and build 0 errors). No CI result is claimed for any later docs-only commit before it is pushed and its own run completes.
2. Live SAM end to end (M2) BLOCKED_EXTERNAL: keys configured in AWS (sam_configured=true), live runs honestly report not_run. Gate: provider credits or allowlist, then the bounded test (available balance for the exact approved asset, billed unit, enforceable $1 bound with hard stop after 2 calls, derivative asset only, product Accept).
3. AWS deployment CLOSED: stack launchcrew-demo in us-east-1 is UPDATE_COMPLETE serving https://launchcrew.summitsingh.com with Alembic 001 through 021 on RDS. Remaining: teardown verification after Nov 4 and no later than Nov 9.
4. Demo video still gated: BLOCKED_EXTERNAL items resolved or user-approved scope change, plus user tap to record and user approval of the final version. No video is claimed.
5. Final submission still TODO: demo, repo, video, deployment ready plus final submit tap before Nov 4, 2026, 9:00 PM ET. No submission is claimed.

No product behavior was changed to write this matrix. Whole-goal completeness is NOT claimed.
