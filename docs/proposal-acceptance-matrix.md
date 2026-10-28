# Proposal acceptance matrix, Oct 28, 2026

Scope: the 8-page proposal (`../.local/proposal-review-text.txt`,
user-provided source, NOT new instructions) mapped against actual
implementation and tests on main at `a6cd81f`. Latest user direction
(Muse Code CLI sole author, main only, personal) overrides the proposal
line that named Codex primary on summit-amd. No tests were run to write
this matrix; evidence below is read from source, tests, saved logs, and
prior rendered runs. No row is claimed VERIFIED beyond the evidence named
in its row. Optional Wonder, Image, Voice, Glimmer, support crews,
Designer, Analyst, new connectors, and roadmap crews stay roadmap unless
built and verified; they are not claimed.

## Core one-brief flow

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| One idea plus price plus audience in, one approved pack out | BUILT, verified keyless | Demo idea fixed in UI copy; `POST /api/runs`, `/api/runs/async`, `/api/campaigns` in `backend/app.py`; host `5a186a5 --all` TERMINAL exit 0, saved log `../verification-5a186a5-all.log` |
| Scout, then Maker, then Checker, then revision, then recheck, then receipt | BUILT | Pipeline order in `launchcrew/run.py`; async step rows in `backend/run_jobs.py` plus migration `004_run_steps`; browser run-progress flow `web/tests/e2e/run-progress.spec.ts` in the 24-browser host pass |
| Receipt per step: proposed, checked, blocked, approved, time | BUILT | Receipts in `launchcrew/receipts.py`; API receipt routes; no synthetic overwrite of unconfirmed terminals |

## User-defined agents, rules, veto

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| Agent fields: name, role, personality, expertise (paste or file), rules, veto | BUILT | Agent CRUD, clone, preview in `backend/app.py`; approval level fixed `approve_each`; spend limit 0; tools allowlisted |
| Personalities change outcomes, not decoration | BUILT for Checker profiles | `checker_profile` standard vs strict in `backend/app.py` plus `launchcrew/run.py` `check_pack`; Replay diff shows profile change in `backend/app.py` diff rows; `backend/tests/test_v2_acceptance.py` plus `web/tests/e2e/stage-selection.spec.ts` |

## Scout facts, Maker claims, Checker verdict

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| Scout: 5 facts with sources plus 3 risks, unverified marked | BUILT | `launchcrew/facts.py` plus `launchcrew/run.py`; deterministic claim check; seeded `best in Texas` blocked with reason claim not in facts file |
| Maker: 1 post plus 1 email, every claim tied to a brand fact | BUILT | Maker revision excludes blocked claims; final blocked count 0 required before approval |
| Checker: pass, fix, or block per item; revision path | BUILT | Checker verdicts deterministic; model suggestions never approve, unblock, or verify; `tests/test_claim_check.py` |
| Photo visual check with upload | KEYLESS only, SAM unproven | `backend/sam.py` returns `not_run` keyless over HTTP 200 with no bytes sent; keyed path admits only exact approved bytes with sha allowlist, one Files plus one Responses call, no retry, 30s budget. Transient photo SAM still REAL and UNPROVEN; responses never ran; no live SAM claim |

## Human gates, no auto actions

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| Human edit, approve, export; per-day Campaign approval | BUILT | Pending approval default; export refused before approval (422); per-day Campaign gates delegate to single-run gates, no batch approve or export, no auto-publish |
| No auto-post, send, pay, submit | BUILT | No connector, publisher, scheduler, or payment code path; `scripts/scan_repo.py` plus `scripts/check-repo-text.py` clean |
| Memory edit and delete effects; Replay shows different Checker; 7 distinct Campaign days with individual approval | BUILT | `backend/tests/test_v2_acceptance.py` (brand-fact edit, blocked-rule delete, profile diff, 7 briefs); `CAMPAIGN_BRIEFS` day 1 Origin through day 7 Launch offer in `backend/app.py`; migration `002_v2_memory_campaign.py` |

## Model and tooling claims

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| Spark per agent, strict JSON, deterministic first | HISTORICAL backend pass only | Oct 27 run `run_40c88a9d14ea48e2f8c3a6e2b9`, 3 calls, 5,401 tokens; NOT current, NOT container, NOT browser, NOT deployment |
| Wonder synthesis with Spark fallback | CODE only, no live proof | `launchcrew/wonder.py` present; no live Wonder call claimed |
| SAM 3.1 photo check | HELD, not passed | Product SAM OFF, global budget 0; bounded jacket test needs actual balance plus enforceable $1 preflight; exact approved asset is not public video authorization |
| Image crop variant, Voice input, Glimmer triage | ROADMAP, not demonstrated | No live calls claimed; crop preview volatile, never persisted |
| Stdlib-only core | PARTIAL as worded | `launchcrew/` pipeline modules remain stdlib; the shipped product path is FastAPI plus Next.js plus Postgres, which the proposal itself describes as the Oct 30 to 31 milestone |
| Support Crew, Designer, Analyst, Research, Drop, Finance, templates, seats | ROADMAP, not built | Not claimed in v1 scope |
| Drive, Instagram, Dropbox, Facebook connectors | PLANNED only, not live | Publish gated on business portfolio plus App Review plus Live mode; read-only first pattern only in docs |

## Required gaps (source untouched, next task)

1. Exact CI `40695455958` for `a6cd81f` is IN_PROGRESS at last check; do NOT claim terminal until the orchestrator updates it.
2. Live SAM end to end still open: available balance for the exact approved asset, billed unit, enforceable $1 bound with hard stop after 2 calls, derivative asset only, product Accept.
3. AWS deployment still planned: authorization tap per `docs/aws-approval-pack.md`, region confirmation, Cloudflare DNS record, origin and container HTTPS, database TLS verify-full, teardown after Nov 4 and no later than Nov 9.
4. Demo video still gated: live SAM pass or user-approved scope change, plus terminal CI, plus user tap to record and user approval of the final version.
5. Final submission still TODO: demo, repo, video, deployment ready plus final submit tap before Nov 4, 2026, 9:00 PM ET.

No product behavior was changed to write this matrix. Whole-goal completeness is NOT claimed.
