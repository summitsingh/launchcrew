# Local verification

## Current state, Oct 28, 2026: published main `a6cd81f`, clean

Published main `a6cd81f` is clean (normal push plus readback only, verified). Exact CI `40695455958` is TERMINAL SUCCESS, confirmed from the saved run log `../verification-ci-a6cd81f-success.log` (24 browser passed in 2.3m at line 1130; bootstrap 6th image build tag at lines 1534-1536; actual Linux container path create, receipt, seeded block, pending export refusal 422, approve, export 200, queue PASS with no model calls at lines 1563-1578; job ends Complete): https://github.com/summitsingh/launchcrew/actions/runs/40695455958. Prior published `e425199` carries terminal CI `40681490583` SUCCESS on the actual Linux container path (saved log `../verification-ci-e425199-success.log`, lines 1382 to 1399: create, receipt, block, refuse, approve, export, queue).

Host run `5a186a5 --all` is TERMINAL exit 0 (saved log `../verification-5a186a5-all.log`): 271 backend pytest in 7.03s, 234 core unittest in 61.751s, 71 Vitest, 30 contracts plus typecheck plus build, 24 browser in 1.9min (18 route-interception-free: e2e across 375, 768, 1024, 1440 widths plus the async run-progress, stage-selection, real keyless photo check, memory, and integration acceptance flows; plus 6 labelled SYNTHETIC photo UI proofs in `web/tests/e2e/photo-synthetic.spec.ts` that deliberately intercept photo-check and receipt routes via `page.route`, never live SAM). Final CFN and test-only pass at `a6cd81f` is 119 PASS in 63.20s (saved log `../verification-a6cd81f-bootstrap-tests.log`), cfn-lint 1.58.0 ZERO diagnostics (saved log `../verification-bootstrap-final-cfnlint.log`, empty file), scan ALL zero, diff clean. Actual PG binding harness on disposable loopback Postgres 18.6 (port 55507, self-signed CA, password auth) is PASS (saved log `../verification-5a186a5-roles.log`): real client password auth good plus bad, migration Alembic 004, runtime CRUD with DDL 42501 refusal, unowned superuser and membership and old-head negatives. This is self-signed loopback TLS plus PG superuser, NOT RDS master, NOT live RDS TLS identity. Browser proof stands at 24: 18 route-interception-free (real keyless photo check in `web/tests/e2e/human-review.spec.ts`, keyless progress in `web/tests/e2e/run-progress.spec.ts`, integration acceptance, review widths, memory, stage selection) plus 6 clearly labelled SYNTHETIC photo UI proofs in `web/tests/e2e/photo-synthetic.spec.ts` (mocked photo-check fulfilled via `page.route`, never live SAM). No actual cloud resources, provider calls, or grants were used in checks.

Incremental stage receipts on this main line (`POST /api/runs/async`, `GET /api/runs/{run_id}/steps`, migration `004_run_steps`, `backend/run_jobs.py`): the keyless `not_run` receipt transport note honesty fix (bytes stayed on the LaunchCrew validation server, not forwarded to any segmentation provider) is covered by a backend assert plus a no-DB helper run through `record_unattempted_transport` with the receipt cleanliness gate. Keyless photo DOES send bytes to LaunchCrew validation, NOT to SAM; privacy wording says exactly that.

Restart limitation, by design: async workers are in-process threads with no supervisor, so a host restart loses in-flight pipeline work. What remains is the pending receipt plus the stored completed steps: evidence of accepted-but-unfinished work, never success. The Desk reports the result as unconfirmed, approval stays locked, and nothing is retried automatically; the founder creates a new pack instead. No database row lock is ever held across remote inference: every step write and the final receipt-plus-terminal-step commit are separate short transactions.

Dated history, earlier Oct 28, 2026: published main `9809b4a` carried the earlier host full pass (172 backend pytest, 109 core, 63 Vitest, scans plus typecheck plus build, 22 browser in 37.4s: 16 original plus 1 real keyless photo plus 5 clearly labelled synthetic interaction proofs; CI `40665386053` read at terminal by the orchestrator; prior CI `40659590053` was terminal success including containers). Offline CLI verification at that checkpoint (no live model calls): 115 unittest collected (112 pass; 3 pre-existing `test_stage_b` sandbox socket-bind errors, unrelated), 70 Vitest, `tsc --noEmit`, production `next build`, both repo scans clean, 234 pytest tests collected, exact OpenAPI plus TypeScript client regeneration with no diff beyond the new routes. The `test_stage_b` WebTests socket errors were sandbox loopback denials on the untouched stdlib UI server path, not product failures. Sections below dated Oct 27 are retained history, not current claims.

## Update, Oct 27 evening, history retained (see current state above)

Remote GitHub Actions execution is no longer unverified. Completed Verify LaunchCrew runs, with links:
- Main: run 40618077504, commit 4bb295d, Status Success, 5m 5s, https://github.com/summitsingh/launchcrew/actions/runs/40618077504
- Auth branch, context only, not main: run 40618273486, commit 8c49012, feature/auth-hardening, Status Success, 4m 44s, https://github.com/summitsingh/launchcrew/actions/runs/40618273486
- AWS branch, context only, not main: run 40617911319, commit 9b11d52, feature/aws-deployment-prep, Status Success, 4m 51s, https://github.com/summitsingh/launchcrew/actions/runs/40617911319
Test counts are not listed in the run page text, so no count is claimed here beyond workflow success. Main run annotations are warnings only: Node.js 20 deprecation, no artifacts for Playwright paths, and ubuntu-latest migration notice.

Historical live Spark backend pass, Oct 27 evening: model muse-spark-1.3, 3 Spark calls, 5,401 total tokens, Checker still blocked the seeded unverified claim deterministically, approval and export both HTTP 200, run run_40c88a9d14ea48e18cb85386a86545c6, commit ea6666e at that time, via FastAPI TestClient plus standalone Postgres, temporary schema dropped. This is a historical backend pass, not a container pass, not a deployment pass, not a current retest, and not a claim that Spark passes today in every path.

Live SAM end to end remains OPEN, not passed. Files step failed 400 with original DSC_3252.JPG, 5504 by 8256, 25,956,803 bytes; files step succeeded 200 with derivative DSC_3252_demo_1600.jpg, 1067 by 1600, 496,593 bytes, Accept application/json in diagnostic code; responses never run; product retry never run in the fixed configuration; checked true never recorded; provider file from the successful derivative upload is left until deleted, delete endpoint unconfirmed. A files-only success is not a SAM pass.

Explicitly retained as OPEN: container-path model tests for Spark and SAM through the Podman container API with a key at container start, real Google and Facebook sign-in, deployment at launchcrew.summitsingh.com, demo video, and final submission. Video gate is BOTH a live SAM pass AND a CI pass; CI pass is now met, SAM pass is not, so video stays gated. Submission gate is Summit's final tap after demo, repo, video, and deployment are ready, due Nov 4, 2026, 9:00 PM ET, and is not done.

Machine: summit-amd. Checkout: /home/summit/launchcrew. Work stayed local. No Docker daemon, AWS provisioning, DNS creation, submission, signed-in browser, or origin push was used. Git commits are local for independent coordinator verification.

## Recovered work and changes

The starting commit 6fc6ae8 was preserved, including its agents.py changes. The recovered partial .gitignore, run.py seams, backend/, and db/001_init.sql were reviewed and committed as 1cd41ee after 36 existing unittest cases and two new adapter cases passed. No recovered source file was silently discarded.

The directory parameter and injectable receipt writer were kept. Model disabling was retained for the new adapter. SQLAlchemy replaced direct psycopg calls in store.py and app.py because the added brief requires one Postgres layer. Alembic 001 supersedes the retained SQL file. Typed receipt responses and a generated client replaced generic endpoint typing. Authlib server-side sessions were added disabled by default. Temporary adapter profiles and export serialization moved inside .local to stay in the checkout. One pipeline audit sentence changed from claiming a local run JSON file was stored to describing preparation for receipt storage. No claim-check or approval logic was duplicated or rewritten.

An empty web/app directory left by the aborted session was removed after inspection showed it had no files. It masked Next.js discovery of web/src/app. The old launchcrew/web.py and old run JSON files remain unchanged. README names the stdlib UI as superseded.

## Final test results

| Suite | Total | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Backend pytest | 21 | 21 | 0 | 0 |
| Existing unittest directory, including two added scanner regressions | 38 | 38 | 0 | 0 |
| Frontend Vitest | 6 | 6 | 0 | 0 |
| Playwright, real headless Chromium | 12 | 12 | 0 | 0 |

The original 36 unittest cases all remain. Backend pytest includes the two adapter cases. Final pytest emitted 105 dependency deprecation warnings, with no failed tests. TypeScript typecheck and production Next.js builds passed. OpenAPI regeneration and TypeScript regeneration produced no diff. The generated-client equality test uses the generator library in memory and still compares the complete output byte for byte. The frontend boundary test parses source imports and checks dependencies for Postgres drivers and backend store imports.

Commands actually used, with environment variables scoped to the local demo database:

```bash
DATABASE_URL=postgresql://postgres@127.0.0.1:54329/launchcrew UV_CACHE_DIR=$PWD/.local/cache uv sync --frozen
DATABASE_URL=postgresql://postgres@127.0.0.1:54329/launchcrew UV_CACHE_DIR=$PWD/.local/cache uv run pytest -q --disable-warnings
UV_CACHE_DIR=$PWD/.local/cache uv run python -m unittest discover -s tests -q
node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web test
node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web typecheck
.venv/bin/python -m scripts.generate_client
node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web client:generate
git diff --exit-code backend/openapi.json web/src/lib/schema.d.ts
scripts/podman-local.sh build
scripts/podman-local.sh up
scripts/podman-local.sh check
PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 PLAYWRIGHT_BROWSERS_PATH=$PWD/.local/browsers WEB_URL=http://127.0.0.1:3001 node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web test:e2e
```

Local sockets, headless browser processes, network downloads, Podman, and writes to the sandbox's read-only git metadata required managed execution outside the restricted sandbox. All dependencies, image storage, runtime directories, screenshots, and persistent application files were placed inside the checkout. No live browser session or sign-in was used. Headful Chrome was not attempted.

## Browser and visual checks

| Width | Agent builder | Approval queue | Receipt | Brief and run reflow |
| --- | --- | --- | --- | --- |
| 375 | PASS | PASS | PASS | PASS |
| 768 | PASS | PASS | PASS | PASS |
| 1024 | PASS | PASS | PASS | PASS |
| 1440 | PASS | PASS | PASS | PASS |

The tests create, edit, clone, and preview agents; create wallet runs from the new UI; inspect the unsupported claim and revision; approve one pack; save a real browser download; and open its receipt. Document overflow is asserted at each width. Screenshots are .local/idea-WIDTH.png, builder-WIDTH.png, run-WIDTH.png, queue-WIDTH.png, and receipt-WIDTH.png. Browser results are .local/playwright-results.json and .local/playwright.log. These are local ignored evidence, not source artifacts.

Visual defects and fixes: long synthetic agent names initially widened the 375 pixel builder. The first browser matrix reported nine passing and three failing tests, including two dependent evidence-file failures after the builder failed. The fix gives the profile text a shrinkable width and wraps long words. The complete matrix then passed. Empty root app discovery was fixed before browser verification. Visual inspection of saved screenshots confirmed mobile brief and run stacking, readable draft panels, wrapped identifiers, and receipt disclosure. No decorative hero image, gradient, animated counter, or publishing affordance was added. Full JSON is intentionally behind a disclosure and may make expanded receipt screenshots long.

## Scans and grep

```bash
python3 scripts/scan_repo.py
python3 scripts/check-repo-text.py
git grep -I -n -i -F "$(printf '\342\200\224')" -- . ':!**/__pycache__/**' ':!.git/**' | wc -l
git grep -I -n -i -F 'Company'' OS' -- . ':!**/__pycache__/**' ':!.git/**' | wc -l
```

Final scan counts: em_dash 0, legacy_brand 0, email 0, phone 0, street_address 0, secret 0, personal_name 0, read_error 0. Both explicit git grep matching-line counts: 0. Git grep covers tracked source, including committed additions. Dependency caches, build output, browser evidence, .git, and bytecode are outside the authored repository scan. The scan is a pattern check, not a claim of comprehensive secret detection.

The first expanded scan reported 499 email matches from package-version strings and a generated build cache, with punctuation and legacy-brand counts already zero. The email pattern now requires an alphabetic top-level domain, and generated caches are excluded. Added tests prove real synthetic email addresses still match and authored files are still scanned. No source finding was hidden by excluding its path.

## Container verification

Three images were built with `podman build --format oci`, via scripts/podman-local.sh. All three services ran through rootless Podman. Image manifests use application/vnd.oci.image.manifest.v1+json. Runtime user checks: API uid 10001, web uid 1000, database uid 70. Superseded: the runtime API image intentionally never migrates now (see the container migration fix below). A separate migration image runs once before API startup.

- `curl -fsS http://127.0.0.1:8001/api/health`: HTTP 200, status ok, auth disabled_demo, approval_by demo_placeholder.
- `curl -fsS http://127.0.0.1:3001/`: HTTP 200.
- `curl -fsS http://127.0.0.1:3001/api/health`: HTTP 200.
- `pg_isready -U postgres -d launchcrew` inside launchcrew-stack-db: accepting connections, exit 0.

The host's default rootless bridge path failed first through pasta, then through the user-bus DNS helper. The verified run script uses a shared rootless slirp4netns pod, without bridge DNS. Compose is provided but unexecuted because podman-compose is absent. PostgreSQL is not an HTTP service; pg_isready is its health check. No database port is published by the full-stack script. Health polling tolerates transient connection resets during API startup, then requires a successful final health request. Logs are local under .local/podman-build.log and .local/podman-run.log.

## Resolved verification failures

This table records file and error type only. All have been corrected or rerun successfully with the required local execution environment.

| File or tool entry point | Error type |
| --- | --- |
| tests/test_stage_b.py | PermissionError |
| backend/tests/test_api.py | AssertionError |
| backend/tests/conftest.py | ModuleNotFoundError |
| web/src/app/page.tsx | TS2554, TS2741, TS2345 |
| web/tests/unit.test.tsx | Error, EPERM |
| web/tests/e2e/review.spec.ts | Error, ENOENT |
| web/node_modules/@playwright/test/cli.js | Error |
| scripts/podman-local.sh | Podman exit 125, 126, 127 |
| scripts/scan_repo.py | scan exit 1 |
| .git/index.lock | git exit 128 |

The Request annotation, pytest pythonpath, in-memory client generation, workspace runtime environment, Chromium platform override, and mobile reflow fix address the corresponding failures. No tests were deleted, skipped, or weakened to conceal failures. No final verification failure remains.

## Additions A1 through A7

| Addition | Result |
| --- | --- |
| A1 testing | Implemented and locally verified: pytest 21, unittest 38, Vitest 6, Playwright 12 passing. |
| A2 CI | Implemented for every push and pull request; constituent commands verified locally. Remote Actions execution has since been verified: main run 40618077504, commit 4bb295d, Status Success, 5m 5s, https://github.com/summitsingh/launchcrew/actions/runs/40618077504 . Auth branch run 40618273486, commit 8c49012, Success, 4m 44s, and AWS branch run 40617911319, commit 9b11d52, Success, 4m 51s, are branch context only, not main. |
| A3 package managers | uv preinstalled, pnpm locally installed; frozen Python and pnpm installs verified, both lockfiles committed. |
| A4 database | SQLAlchemy and Alembic verified on real local Postgres. Raw psycopg persistence removed; retained SQL file explicitly superseded. |
| A5 frontend | Tailwind, locally styled attributed shadcn/ui Button pattern, and TanStack Query queue/run polling and export mutation state implemented and browser verified. |
| A6 API contract | Pydantic v2 OpenAPI, committed generated TypeScript definitions, typed openapi-fetch calls, regeneration scripts, and drift tests verified. |
| A7 auth | Authlib routes, identity-only scopes, secure opaque cookies, Postgres sessions, subject attribution, rotation, expiry, and mocked callback tests implemented. Disabled by default. Auth is planned, not live; real Google/Facebook sign-in and deployment HTTPS remain unverified without provider credentials. |

## Remaining gates and exclusions

Open gates are independent coordinator verification and any later coordinator push; optional compose-path execution; real Google and Facebook sign-in with provider credentials and HTTPS; deployment TLS including API-to-database TLS; the blank AWS cost cap, later provisioning approval, resource and region review, DNS creation and later teardown verification; live Spark container-path and deployment tests; live SAM end to end; v2 build and lock; demo video; and final submission authorization and execution. AWS, DNS, auth sign-in, v2, SAM end to end, and submission are not claimed as live or done. Live Spark is claimed only as the historical backend pass described in the Oct 27 evening update above, not as a container, deployment, or current pass.

Not added: Redis queue, S3 photo storage, Sentry, pgvector, Terraform, a second auth system, WebSockets for run progress, DynamoDB, Mongo, SQLite as primary, Svelte, Astro, Remix, Django, Node backend, or Go backend. The Next server provides frontend rendering and the API proxy only. No AWS or DNS command was executed in that run, nothing was submitted in that run, and nothing was pushed in that run; later pushes and remote CI runs are recorded in the Oct 27 evening update above.

## Final wallet demo runs

Each run used the new UI and a newly created agent with the wallet idea. Each began pending_approval, blocked one seeded claim in v1, revised to zero blocked claims in v2, received one demo_placeholder approval, and downloaded JSON through a separate export action.

| Width | Run id | Approval | Export |
| --- | --- | --- | --- |
| 375 | run_0eca7df8ed914a1ca3e7ee8ee081c522 | pending_approval to approved_for_export; demo_placeholder | downloaded_json |
| 768 | run_5f3c2b36f62c427db0e85ad2028a69e7 | pending_approval to approved_for_export; demo_placeholder | downloaded_json |
| 1024 | run_07217cec7ea04172b60cdb3bd04d2ff6 | pending_approval to approved_for_export; demo_placeholder | downloaded_json |
| 1440 | run_45327a31886a4d7396598045ea957cb3 | pending_approval to approved_for_export; demo_placeholder | downloaded_json |

Detailed local evidence: .local/demo-WIDTH.json, .local/export-WIDTH.json, .local/playwright-results.json. Demo runs remain in the full-stack Postgres volume for coordinator inspection. Earlier browser passes also left demo records; no run history was erased.

## Final image identifiers and durability

| Image | OCI id |
| --- | --- |
| localhost/launchcrew-api:demo | cbc92f01affd6ecc8a66aa8d58b5fe000020562d8b4772e31c4b3f679fbee45e |
| localhost/launchcrew-web:demo | 77141435c76f08647353d1e8441736ea79a02427738c47104246ec8ca3a8b188 |
| localhost/launchcrew-db:demo | e51b3312f84ec57dfb9ac8796432666727f9bf513054c18d9b652e505bfa2511 |

All three manifests were inspected as OCI. After the final startup-script change, the entire pod was restarted, all health checks passed again, and each of the four demo receipts was fetched through the new UI API proxy. Each matched its downloaded JSON and retained approved_for_export with demo_placeholder. No database data was removed. The stack remains available locally on web port 3001 and API port 8001.

## Changed-file manifest

Relative to preserved starting commit 6fc6ae8, one file per line:

```text
.containerignore
.github/workflows/verify.yml
.gitignore
AUTOMATION-PLAN.md
DEPLOY-CHECKLIST.md
DESIGN.md
README.md
alembic.ini
backend/__init__.py
backend/adapter.py
backend/app.py
backend/auth.py
backend/migrations/env.py
backend/migrations/versions/001_baseline.py
backend/openapi.json
backend/requirements-test.txt
backend/requirements.txt
backend/store.py
backend/tests/conftest.py
backend/tests/test_adapter.py
backend/tests/test_api.py
compose.yaml
containers/api.Containerfile
containers/db.Containerfile
containers/podman.conf
containers/web.Containerfile
db/001_init.sql
docs/aws-prep.md
docs/postgres-migration.md
docs/verification.md
launchcrew/run.py
pyproject.toml
scripts/check-repo-text.py
scripts/generate_client.py
scripts/podman-local.sh
scripts/scan_repo.py
tests/test_scan.py
uv.lock
web/SHADCN-LICENSE.txt
web/components.json
web/next-env.d.ts
web/next.config.ts
web/package.json
web/playwright.config.ts
web/pnpm-lock.yaml
web/postcss.config.mjs
web/src/app/globals.css
web/src/app/layout.tsx
web/src/app/page.tsx
web/src/components/ui/button.tsx
web/src/lib/api.ts
web/src/lib/schema.d.ts
web/src/lib/utils.ts
web/tests/e2e/review.spec.ts
web/tests/unit.test.tsx
web/tsconfig.json
web/vitest.config.ts
```


## V2 Item A verification, separate worktree, Oct 27, 2026

Worktree: /home/summit/launchcrew-v2, branch feature/v2-memory-replay-campaign, starting commit 966de60. Only this worktree was edited. No branch switch, commit, push, rebase, or revert occurred. All new implementation was authored in this repo during this task. Existing pipeline and receipt gates remain the execution and approval paths.

Backend: `DATABASE_URL=postgresql://postgres@127.0.0.1:54329/launchcrew UV_CACHE_DIR="$PWD/.local/uv-cache" uv run pytest -q` passed 50 tests with two dependency deprecation warnings. The first run found a JSON literal parsed as a SQL bind in a new test; it was corrected to a bound JSON parameter and the complete suite passed. This includes strict memory inputs, lifecycle and audit, explicit approved-run learning, replay changes and idea mismatch, seven campaign runs and legacy memory rows, individual gates, transaction rollback, auth coverage, v1 approval/export, and exact committed OpenAPI equality.

Frontend: local pnpm 10.20.0 ran `client:generate`, `test`, `typecheck`, and `build`. Vitest passed 10 tests across two files. New component tests cover both views, replay sections and mismatch, and day approval/export controls for pending, blocked, failed, missing final check, approved, and busy states. Typecheck and production build passed. Generated types match the canonical OpenAPI exactly.

Database handling: checked scripts/podman-local.sh and container status. No running pod appeared in the default Podman inventory; API port 8001 and web port 3001 did not respond. Existing localhost Postgres 17.11 on port 54329 responded successfully. Used it with unique temporary schemas for tests and API demo, then dropped only those schemas. No container was started, stopped, rebuilt, or removed. No Podman volume or repo pod was changed. No full stack was started. Playwright smoke was not run because the full stack was not up.

The deterministic API demo used FastAPI TestClient with the real Postgres migration and adapter, overriding only pipeline options to model_enabled=False and visual_verifier=None. No model or visual transport was invoked. Demo rows were removed with the isolated schema after verification. Detailed local evidence is in .local/v2-demo-evidence.json, which is ignored by git.

- Memory created: mem_72299b7aff9749219961051afd61d80e. Edited title to Wallet demo price, content to the $49 demo price plus demo_only true.
- Campaign created: camp_3ca8f5dc10134bdca3f66d89fd350911. Seven days, all initially completed and pending_approval, final blocked count zero.
- Day 1: run_8b788fbf7b9a4d4c8d465ae819b8a4e2, explicitly changed to approved_for_export, then exported with HTTP 200 and attachment filename launchcrew-pack.json. Export receipt state approved_for_export, submit_attempted false.
- Day 2: run_542807e07d0d452088aacc1994b8ba13, pending_approval.
- Day 3: run_d33cb8fdf6d2408cafbfcaff1bd6b4d4, pending_approval.
- Day 4: run_aee9c748e3be4304b950eed457312394, pending_approval.
- Day 5: run_0c533cd2c18e407cbae15d2c7726ec86, pending_approval.
- Day 6: run_bdcfe553022c48b8ad2edc7e09517937, pending_approval.
- Day 7: run_d2441f1e1dbf4725a2544f7c9e14da2c, pending_approval.
- Replay compared day 1 with day 2, HTTP 200, same_idea true, approval_state_changed true. Both had first blocked count one and final blocked count zero. Identical deterministic drafts yielded false draft-change flags. Regression tests separately verify differing drafts and Checker verdicts.

SAM, live model calls, remote CI, video, submission, connectors, provisioning, and live sign-in were not done. Support Crew, Designer, and Analyst were not built. Nothing publishes automatically. Nothing was committed or pushed.

Preserved v1 unittest suite: 38 passed. The initial restricted-sandbox attempt could not bind three temporary test HTTP servers; rerunning with localhost socket permission passed all 38 without source changes. Dependency downloads initially required network permission, then installed from the locked manifests in this worktree.

After staging only the six new source, test, migration, and connector-notes files, scripts/scan_repo.py passed with zero findings for every check. scripts/check-repo-text.py reported em_dash 0 and legacy_brand 0. Both staged and unstaged git diff whitespace checks passed. The branch remained feature/v2-memory-replay-campaign at 966de60; no commit or push occurred.

## Release candidate independent verification, Oct 28, 2026, at c1038ef

Branch ceplat-launchcrew-release-candidate, clean HEAD c1038ef. Independent Codex run, disposable clusters only, removed after use. No push, no merge to main, no cloud provisioning, no credentials in repo.

- Backend pytest: 67 passed, exit 0, on disposable loopback Postgres 18.6, nondefault port, via scripts/verify-release-candidate.sh --backend-only.
- Original unittest suite: 38 passed, exit 0, same run.
- Contract regeneration: 23 paths, backend/openapi.json clean with no diff, exit 0.
- Database roles: scripts/verify-db-roles.sh PASS on disposable loopback Postgres 18.6, nondefault port, with tightened privilege-only refusals. Runtime CRUD and sequence use passed. Runtime CREATE, ALTER, DROP refused. Migration CREATE, ALTER, DROP passed on a disposable proof table. Static role order 29/30/37 passed.
- cfn-lint 1.58.0 on deploy/aws/fargate.yaml: passed.
- Frontend and browser: pending, not passed, due npm registry certificate validation. No Vitest, typecheck, build, or Playwright result is claimed for the candidate.
- Clusters: disposable test clusters removed after use.

Unresolved and not claimed: frontend and browser rerun, live auth sign-in, live model retest and container-path test, live SAM end to end (held, no live calls), AWS SAM validation and deployment, demo recording, merge, push, and submission. An AWS Budget is an alert and estimate mechanism, not an enforced hard spend cap. Cost and deployment approvals stay open user decisions.

## Campaign selector fix plus Scout facts section, Oct 28, local only, pending host browser rerun

Extends main at dbad964. Sole writer personal MuseCLI, repo-local identity only. No push. No dependency or browser reinstall. No cloud, DNS, deploy, spend, credentials, photos, SAM, product model, recording, or submission action.

- Campaign strict violation fixed: CampaignView Maker control was labeled `Agent`, so `getByLabel('Agent')` matched Scout agent, Agent, and Checker agent. The control is now labeled `Maker profile` with id `campaign-maker`, matching the brief form wording. web/tests/e2e/integration-acceptance.spec.ts Campaign Week now uses `getByLabel('Maker profile', { exact: true })`. Other brief-form Maker selectors were made exact without changing assertions. No route mocks, no deleted proof steps.
- Typed Scout receipt contract, backward compatible: backend/app.py adds optional `ScoutFact`, `ScoutSection`, and `ModelUsage` models plus optional `scout`, `stage_bindings`, `stage_agents`, `checker_enforcement`, `checker_policies`, and `model_usage` on Receipt. Historical and failed receipts without Scout data still validate. backend/openapi.json and web/src/lib/schema.d.ts regenerated normally. Contract paths stay 24.
- Run review now renders Scout facts and risks from stored receipt data: new `ScoutFactsSection` in web/src/components/v2-views.tsx, shown between the stage strip and the first-check panel. It lists each stored fact with its claim, evidence, source labels, and Verified or Unverified status; each stored risk tagged as a demo risk or an unverified model hypothesis; the selected Scout identity from stage bindings; and stored model synthesis and usage truthfully, with a fallback line when usage is absent on older receipts. Legacy or failed receipts render a short unavailable note and invent no facts. Raw receipt JSON remains inspectable in the record view. Approval, export, autopost safety, profile, Memory, Replay, and Campaign flows are unchanged. Existing panel, badge, tag, and hint styles reused plus small list rules that wrap at narrow widths.
- Playwright assertions added, not yet run on a host: stage-selection guarded run asserts the rendered section shows the custom Scout identity, 5 fact rows, 3 risk rows, 5 exact Verified badges, all 5 default claims, demo-risk labeling, the no-external-research note, and deterministic fallback, with API cross-checks on `scout.facts_used`, `scout.risks`, and `scout.sources`; default run asserts 5 facts and 3 risks in UI and API; integration-acceptance v1 run asserts 5 facts, 3 risks, and 5 Verified badges in UI plus API lengths on the exported receipt. Viewport overflow at 375, 768, 1024, and 1440 is covered by the existing review spec run path, which checks no horizontal overflow after the draft renders with the new section.

Socket-free evidence from this sandbox (binds denied, so no servers started):
- Frontend Vitest: 5 files, 26 tests passed (20 before, 6 new scout-facts tests).
- Frontend typecheck: `tsc --noEmit` exit 0.
- Frontend production build with `API_URL=http://127.0.0.1:8021`: exit 0.
- Contract: openapi regeneration idempotent, 24 paths, web schema matches canonical OpenAPI per the committed drift test inside the Vitest run.
- Core unittest: 63 passed, 3 errors, all three in tests/test_stage_b.py WebTests setUp where HTTPServer bind is denied by this sandbox (PermissionError on bind). Unrelated files untouched; rerun on a bind-capable host required.
- Backend pytest: not run here, needs disposable Postgres loopback bind. Pending host run.
- scripts/scan_repo.py: pass, zero findings. scripts/check-repo-text.py: em_dash 0, legacy_brand 0. `git diff --check`: clean.
- Browser acceptance including Campaign Week and the new Scout facts UI: pending host run via scripts/verify-release-candidate.sh --all. Not claimed.

Unresolved and not claimed: full verifier rerun on a bind-capable host, live auth sign-in, live model calls, SAM end to end, deployment, demo recording, push, and submission.

## Teardown implementation, Oct 28, local only, pending independent rerun

- deploy/aws/teardown.sh: dry-run default with no AWS call. Confirm path requires exact stack ARN plus expected 12-digit account and region, verifies caller identity and Project LaunchCrew with Environment demo tags before any destructive call, deletes only that stack via CloudFormation, waits for stack-delete-complete, verifies terminal absence by authoritative ValidationError not-found, distinguishes auth and API errors from not-found, never deletes by prefix, never deletes shared or outside-stack resources, and reports Secrets Manager values, ACM certificate, Cloudflare DNS, and manual snapshots as remaining work with a separate approval gate.
- deploy/aws/fargate.yaml: explicit DeletionPolicy Delete and UpdateReplacePolicy Delete on Database, ECR repos, log groups, and DemoBudget. ECR repos set EmptyOnDelete true so a nonempty repo does not block stack deletion or silently retain images. Database keeps DeleteAutomatedBackups true and DeletionProtection false so approved teardown does not silently retain a billable final snapshot.
- Offline tests: tests/test_teardown.py, 8 tests passed with a fake AWS command fixture, no AWS contact. Covers dry-run zero calls, refused ARN and caller and tag mismatch with no delete, success verified by authoritative not-found, and auth failure never treated as absence.
- Local static checks in this commit: sh -n teardown.sh passed, teardown unittest passed, scan and text checks passed. Full backend, db-roles, and cfn-lint rerun for this teardown revision is pending independent verification and is not claimed here.

## Container migration fix plus full e2e glob, Oct 28, local only, new CI pending

Sole writer personal MuseCode CLI on main, atop 1d1a7c0. No push in this pass. No cloud, DNS, deploy, spend, credentials, photos, SAM, product model, recording, or submission action. No backend Memory semantics change; 1d1a7c0 behavior preserved.

- Published failure: the CI Podman step at e56d51e failed with `curl: (56) Recv failure: Connection reset by peer` 60 times against http://127.0.0.1:8001/api/health, after host, backend, frontend, and 14 browser checks passed and all images built (local log verification-ci-e56d51e-failed.log held outside the repo; task cites run 40638273145). The CI log carried no API container output, only curl resets, so the cause below is grounded in repo code, not in captured container logs.
- Diagnosis: `scripts/podman-local.sh up` created a fresh named volume, waited for Postgres, then started the runtime API with no migration step. The runtime entrypoint intentionally never migrates (deployment separation, own migration role), and `backend/app.py` lifespan calls `store.initialize()`, which INSERTs seed agents immediately. Against a fresh volume with no tables that INSERT fails, so the API container exits and the health probe resets. The existing `containers/migrate.Containerfile` was built by nothing and run by nothing.
- Fix, separations preserved: `build` now also builds `localhost/launchcrew-migrate:demo`; `up` runs that image once with `DATABASE_URL=postgresql://postgres@127.0.0.1:5432/launchcrew` and `LAUNCHCREW_DB_TLS_MODE=local` before starting the runtime API, and fails with diagnostics if migration fails. Alembic stays out of `containers/api-entrypoint.sh`, the runtime API keeps no DDL, cloud TLS enforcement in `backend/store.py` is untouched, and the migration and runtime database roles stay separate. `down` still removes only the owned pod and keeps the named volume and images.
- Failure evidence: new `diag` subcommand prints pod status plus bounded 100 line tails of app logs only, never environment, inspect output, config, or secret values, and saves `.local/container-diag.log`. `up` calls it when migration, API, or web readiness fails. CI traps it before cleaning the owned pod and uploads `.local/container-diag.log` plus `.local/container-path-evidence.json` as verification evidence.
- Functional container proof: new `scripts/verify-container-path.py` (stdlib only, authored in this pass) runs keyless through the real API and the Next rewrite proxy with no model calls: direct and proxied health with `disabled_demo` and `demo_placeholder`, agent list, plain run creation, receipt reread, seeded run blocked in v1, export refused 422 before approval, approval, export 200 with `submit_attempted` false, and queue listing. `scripts/podman-local.sh check` runs it after the existing health probes.
- Full browser glob: `scripts/verify-release-candidate.sh` now runs one `pnpm --dir web test:e2e` with no named spec files, so `web/tests/e2e/memory-learned.spec.ts` plus integration, stage, and viewport specs all run in a single invocation with one complete JSON report. Named spec lists cannot omit a future spec again.
- Static separation tests: new `tests/test_container_migration.py`, 13 tests, socket-free, covering migration image build, migration before API ordering with explicit local DB mode, runtime no DDL, migrate only migrates, full e2e glob with all four specs present, sanitized diagnostics with owned pod only cleanup, and harness coverage through the proxy with the 422 gate.

Socket-free evidence from this sandbox (binds denied, so no servers, databases, or containers started):

- `bash -n` on `scripts/podman-local.sh`, `scripts/verify-release-candidate.sh`, and `scripts/verify-db-roles.sh`: all pass.
- New tests plus related suites: 47 passed (`test_container_migration`, `test_verifier_origin`, `test_scan`, `test_teardown`, `test_memory_semantics`).
- Full `tests` discover: 87 run, 3 errors, all three the known `tests/test_stage_b.py` WebTests binds denied by this sandbox, same as the prior pass. No new failure.
- `python3 scripts/scan_repo.py`: pass, zero findings. `scripts/check-repo-text.py`: em_dash 0, legacy_brand 0. `git diff --check`: clean.
- Harness CLI parses (`--api-base`, `--web-base`); its live run needs the container stack and is pending CI.

Not claimed: container stack pass (needs a bind-capable host or CI; new CI run for this commit is pending, not passed), memory-learned browser pass (pending independent host run via the full verifier, then CI), backend pytest and db-roles rerun on a host. The container diagnosis above is code-grounded and awaits CI proof.

## Live-receipts repair, Oct 28, local only, host backend plus browser pending

Sole writer personal Muse Code CLI on release-candidate main, atop b346338 (published 9809b4a was the last published checkpoint at that time; superseded, now `a6cd81f`). No push. No real provider HTTP, Meta product calls, credentials, spend, cloud, DNS, recording, or submission. No DB binds by this author; Postgres and browser runs belong to the host terminal.

- Host evidence that motivated this repair: `../verification-b346338-all.log` and `.local/verify-candidate-logs/verify-candidate-pytest.log` showed 175 passed, 1 failed in 6.47s. The failure was `backend/tests/test_run_progress.py::test_failure_retains_completed_steps_and_blocks_approval_export` line 124: zero failed step rows after a real checker_v1 gate failure. Root cause in final source: `backend/adapter.py execute` captured the pipeline's failed receipt from `run_pipeline` and returned it after suppressing the exception, and `backend/run_jobs.py _work` then called `_finalize_success` unconditionally, so the failure kept its receipt but gained a `run_completed` audit and no failure row. No later full stage ran; no host frontend or browser pass is claimed from that log.
- Fix in owned backend, core, tests, web, and docs (this repair, not new features):
  - `_work` branches on the actual outcome. A returned failed receipt persists the pipeline's original failed receipt (error type, completed history, profiles, model usage, stopped stage) with exactly one failed step row and a `run_failed` audit; no `receipt` completed row and no `run_completed` for failed outcomes. The stopped stage comes from the captured failure's own audit, not from `last_started` (which still names the prior Maker stage when a gate fails before the failing stage emits its own started note).
  - The run row and its `accepted` step row now commit in one `create_async` transaction; an accept journal failure rolls everything back before any worker starts. A mid-run step row that cannot persist raises bounded `StepJournalError` (type name only), which stops the pipeline with an honest failed receipt instead of continuing inference without its journal. No provider work is retried; no queue, cloud, or broker added.
  - Terminal persistence failure is separated from pipeline failure: `_leave_unconfirmed` reads back the stored receipt, never overwrites a possibly committed terminal receipt with a synthetic failure, adds one best-effort bounded-type audit marker, and lets the running receipt with no live worker read as unconfirmed. No raw thread tracebacks, no params or receipt contents in error surfaces.
  - `launchcrew/run.py` completed stages now share one clock reading and profile between the stored step event and the receipt audit entry for the same observed completion (`reached` helper); started notes keep their own readings, and the prepared receipt audit entry stays distinct from the stored terminal row. Core stays stdlib with optional hooks defaulting None; CLI and sync API unchanged.
  - Worker registry claims and starts under one lock; at most one live worker per run id. Public creation mints a fresh UUID per POST and never restarts; GET polling never starts or restarts work.
  - `web/tests/e2e/run-progress.spec.ts` now asserts the actual contract: completed order, started history, distinct server timestamps, non-empty profiles, stored terminal evidence, and step versus receipt audit agreement per completed stage. `selectionPhotoCopy` derives the new-pixels caption and alt from the actual current verdict (no verdict, current detected check, superseded, in flight, other stored state) instead of always reading Unchecked; the keyless text-only flow keeps its existing copy and the photo22 browser proof semantics are unchanged. A real deferred-GET test proves a late older poll cannot regress an acknowledged newer receipt; the N+1 admission and N+2 invalidation behavior is unchanged.
- Socket-free evidence from this sandbox (binds denied, so no servers, databases, or containers started):
  - `tests` discover: 115 run, 3 errors, all three the known `tests/test_stage_b.py` WebTests binds denied by this sandbox, same as the prior pass. Includes the 2 new shared clock and profile proofs.
  - Full Vitest: 9 files, 69 passed. `tsc --noEmit` passed. Production `next build` passed.
  - Contract regeneration: `python -m scripts.generate_client` exit 0, 30 paths, no diff in `backend/openapi.json`.
  - `python scripts/scan_repo.py`: pass. `scripts/check-repo-text.py`: em_dash 0, legacy_brand 0, no secret or personal data counts. `pytest --collect-only` on backend plus tests: 295 collected.
- Not claimed: backend pytest on real Postgres (includes the previously failing failure-row test, the strengthened timestamp and profile agreement, and the 4 new accept rollback, journal loss, unconfirmed, and registry tests), migration `004_run_steps` on real Postgres, the updated real keyless browser flow, and any full-stack or container pass. Those belong to the host terminal after this checkpoint, then CI. The earlier 175 plus 1 is a failure record, not a pass, and is not presented as one.

## Timestamp invariant plus selection proof fix, Oct 28, local only, host backend plus browser pending

Sole writer personal Muse Code CLI on release-candidate main, atop bdf06c0 (published 9809b4a was the last published checkpoint at that time; superseded, now `a6cd81f`). No push. No real provider HTTP, Meta product calls, credentials, spend, cloud, DNS, recording, or submission. No DB binds by this author; Postgres and browser runs belong to the host terminal.

- Host evidence that motivated this fix: `../verification-bdf06c0-all.log` showed 181 backend PASS, 115 core PASS, 69 Vitest PASS, and 30 clean contracts/typecheck/build/scans PASS, with browser 22 pass and 1 fail. The failure was `web/tests/e2e/run-progress.spec.ts` line 64: 15 raw timestamp strings distinct but only 14 distinct `Date.getTime` instants. Raw strings differ at full microsecond precision while two legitimate quick events share one millisecond; `Date` truncates microseconds to milliseconds, so the uniqueness invariant was invalid, not the clock data. No sleep, fake clock, or forced timestamp spacing was added.
- Fix in owned tests and web (working pipeline untouched):
  - `backend/tests/test_run_progress.py` keeps the full microsecond and aware instant equality proof for the shared completion reading, and replaces the raw plus instant global uniqueness claim with unique ordered sequence ids, valid timezone-aware UTC observed times, and nondecreasing instants with ties allowed. New `test_same_millisecond_events_keep_sequence_order` fixture proves two ordered legitimate events in one millisecond stay ordered by seq without unique millisecond instants.
  - `web/tests/e2e/run-progress.spec.ts` asserts the actual contract: unique ordered seq, completed order, started history, timezone-aware observed times, nondecreasing `Date.getTime` order with ties allowed, profiles, stored terminal evidence, and the shared completion reading compared at full precision (canonical second plus fractional part, millisecond `Date` equality alongside) instead of truncating to milliseconds.
  - `web/src/components/photo-check.tsx` tracks the local selection generation plus an ephemeral acknowledged check proof set only when the response for the current selection confirms the current photo check, cleared on new file, external revision, new run, unmount, remove, and error or ambiguous results. The acknowledged current selection reads checked with fresh human approval still required, never not-sent; a new file stays unchecked with no inherited verdict and no automatic HTTP. The keyless post-check copy admits the validation-server send while SAM did not run, never local-only. Raw bytes, geometry, provider ids, and digests stay out of DB, log, and public receipt; the proof is local state only.
  - `web/tests/e2e/photo-synthetic.spec.ts` gains a sixth synthetic mounted UI proof (mocked photo-check, never live SAM): detected response for file A draws the real crop with checked caption and alt, then file B reads unchecked with the old crop gone, no inherited verdict, and no automatic request. The existing five synthetic proofs stay truthfully labelled mocks, and the real keyless flow stays route-interception free.
  - `web/tests/photo-check.test.tsx` gains helper coverage for the checked-current, new-file, stale-proof, and keyless branches.
- Socket-free evidence from this sandbox (binds denied, so no servers or databases started):
  - `tests` discover: 115 run, 3 errors, all three the known `tests/test_stage_b.py` WebTests binds denied by this sandbox (`PermissionError` on socket bind, files untouched by this change), same as the prior pass.
  - Full Vitest: 9 files, 70 passed. `tsc --noEmit` passed. Production `next build` passed.
  - Contract regeneration: `python -m scripts.generate_client` exit 0, 30 paths, no diff in `backend/openapi.json`.
  - `python scripts/scan_repo.py`: pass. `scripts/check-repo-text.py`: em_dash 0, legacy_brand 0, no secret or personal data counts. `pytest --collect-only`: 182 collected (181 plus the new same-millisecond fixture). The two DB-free timestamp tests pass standalone.
- Not claimed: backend pytest on real Postgres (182, includes migration 004, barrier, failure, journal, rollback, unconfirmed, registry, UTC, and safe acceptance), the rerun of `run-progress.spec.ts` with the corrected invariant, the new sixth synthetic proof, the real keyless browser flow with no-SAM refusal and remove-to-fresh-approval, and any full-stack or container pass. Those belong to the host terminal after this checkpoint, then CI.

## Bootstrap admission and role proof correction, Oct 28, source only, host tests pending

Sole writer personal Muse Code CLI on release-candidate main, atop 5ae82ec. No push. No tests, collection, build, network, DB, AWS, env, credentials, or install actions in this pass; CLI read, edit, and commit only. No cloud calls, spend, DNS, recording, or submission.

- deploy/aws/bootstrap.sh: absent-stack check now requires the exact requested stack name in the not-exist message; any other ValidationError refuses without creating. Parameters file parsing fails closed on duplicates, missing values, UsePreviousValue, malformed entries, and unrecognized secret references, and a missing file value never counts as a match. CloudFormation overrides travel as one python-built argv item each with shape guards and bounded failures. Image proof refuses latest by name, honors tag at sha256 pins, and states the point-in-time scope (template repos carry no immutable tag lock). One-off proof uses the owned task definition document for the expected essential set with default-true semantics, exact task and cluster ARNs, and bounded codes only. Phases dbroles, migrate, and enable check exact secret bindings and execution roles (including TLS material for API and web) before any task starts; enable re-proves images, bindings, and the runtime-only verify proof before any deploy and never reruns migration or provider work. New --tls-secret-arn input with the same ARN ownership checks.
- tests/test_bootstrap.py: fake now serves Api and Web logical resources, keeps fresh stacks absent until the fake deploy creates them, returns real-shaped container status without the essential flag with per-definition containers and matching task ARNs, and returns full task definition documents with images, secrets, and execution roles. New behavior tests cover standalone enable re-proof, verify failure, image and binding drift, other-error absence, latest refusal, and strict parameters cases. Secret-auth test asserts no read-value call and no mutation with bounded error text.
- scripts/bootstrap_db_roles.py: existing roles are rebound only with the ownership stamp and no superuser, create, replication, or membership risk. Binding comment states the memory-only literal accurately, and stdout redaction is labeled as process-only with server-side logging outside the job.
- scripts/verify-db-roles.sh: stage 2 exercises the actual bind and verify job after alembic head through the migration role on the same disposable loopback cluster, with synthetic passwords in memory only, password-auth proof, wrong-password refusal, CRUD and DDL split on the bound roles, and unowned-role, membership, and old-head negatives. Loopback self-signed CA only, not live RDS TLS proof.
- Text hygiene: the 13 secret-pattern findings were the s-k hyphen sequence inside hyphenated source words (the ECS describe name, generated temp names, and per-minute cost words); those constructions are now split or reworded with no scanner change and no whitelist. No em dash, no personal data.
- Not claimed: the full bootstrap offline suite green (94 plus new tests), the backend pytest, the db-roles live stage, scans, and any cloud or serving proof. Those belong to the host terminal after this checkpoint, then CI. No cloud-ready claim is made from offline edits.
