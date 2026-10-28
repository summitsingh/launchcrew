# Proposal acceptance matrix, Oct 28, 2026

Scope: the 8-page proposal (human-furnished source text, reviewed Oct 28; the private working copy is not cited as public proof) mapped against actual
implementation and tests on main at `a6cd81f`. Latest user direction
(Muse Code CLI sole author, main only, personal) overrides the proposal
line that named Codex primary on summit-amd. No tests were run to write
this matrix; evidence below is read from source, tests, and
prior rendered runs. Saved `../verification-*.log` files are local operator
notes only, never the sole public proof: each row names the public source or
test path that carries it, and CI proof is the public run
https://github.com/summitsingh/launchcrew/actions/runs/40695455958. No row is claimed VERIFIED beyond the evidence named
in its row. Optional Wonder, Image, Voice, Glimmer, support crews,
Designer, Analyst, new connectors, and roadmap crews stay roadmap unless
built and verified; they are not claimed.

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
| No auto-post, send, pay, submit | BUILT | No connector, publisher, scheduler, or payment code path; `scripts/scan_repo.py` plus `scripts/check-repo-text.py` clean |
| Memory edit and delete effects; Replay shows different Checker; 7 distinct Campaign days with individual approval | BUILT | `backend/tests/test_v2_acceptance.py` (brand-fact edit, blocked-rule delete, profile diff, 7 briefs); `CAMPAIGN_BRIEFS` day 1 Origin through day 7 Launch offer in `backend/app.py`; migration `002_v2_memory_campaign.py` |

## Model and tooling claims

| Proposal claim | Status | Evidence and limitation |
| --- | --- | --- |
| Spark per agent, strict JSON, deterministic first | HISTORICAL backend pass only | Oct 27 dated record, 3 calls, 5,401 tokens (see the matching dated historical entry in `docs/submission-draft.md` and `docs/verification.md`; no run ID is repeated here); NOT current, NOT container, NOT browser, NOT deployment |
| Wonder synthesis with Spark fallback | CODE only, no live proof | `launchcrew/wonder.py` present; no live Wonder call claimed |
| SAM 3.1 photo check | HELD, not passed | Product SAM OFF, global budget 0; bounded jacket test needs actual balance plus enforceable $1 preflight; exact approved asset is not public video authorization |
| Image crop variant, Voice input, Glimmer triage | ROADMAP, not demonstrated | No live calls claimed; crop preview volatile, never persisted |
| Stdlib-only core | CORE STDLIB, full web stack separate as proposed | `launchcrew/` pipeline modules import stdlib only (`argparse`, `copy`, `json`, `os`, `re`, `pathlib`, `urllib`, `http.server`, `datetime`; no third-party imports), covered by `tests/test_claim_check.py` and related core suites. The shipped product path is FastAPI plus Next.js plus Postgres, which the proposal itself describes as the Oct 30 to 31 milestone, so the core reads stdlib while the full web stack is a separate explicitly proposed layer |
| Support Crew, Designer, Analyst, Research, Drop, Finance, templates, seats | ROADMAP, not built | Not claimed in v1 scope |
| Drive, Instagram, Dropbox, Facebook connectors | PLANNED only, not live | Publish gated on business portfolio plus App Review plus Live mode; read-only first pattern only in docs |

## Required gaps (source untouched, next task)

1. Exact CI `40695455958` for `a6cd81f` is TERMINAL SUCCESS, confirmed from the saved run log `../verification-ci-a6cd81f-success.log` (24 browser passed in 2.3m at line 1130; bootstrap 6th image build tag at lines 1534-1536; container path PASS with no model calls at lines 1563-1578; job ends Complete): https://github.com/summitsingh/launchcrew/actions/runs/40695455958. No CI result is claimed for any later docs-only commit before it is pushed and its own run completes.
2. Live SAM end to end still open: available balance for the exact approved asset, billed unit, enforceable $1 bound with hard stop after 2 calls, derivative asset only, product Accept.
3. AWS deployment still planned: authorization tap per `docs/aws-approval-pack.md`, region confirmation, Cloudflare DNS record, origin and container HTTPS, database TLS verify-full, teardown after Nov 4 and no later than Nov 9.
4. Demo video still gated: live SAM pass or user-approved scope change, plus terminal CI, plus user tap to record and user approval of the final version.
5. Final submission still TODO: demo, repo, video, deployment ready plus final submit tap before Nov 4, 2026, 9:00 PM ET.

No product behavior was changed to write this matrix. Whole-goal completeness is NOT claimed.
