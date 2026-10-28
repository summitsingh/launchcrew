# LaunchCrew

LaunchCrew turns approved demo facts into a launch pack through Scout, Maker, and Checker. A human reviews each pack, approves it individually, then exports it. There is no posting, sending, paying, submitting, screening, ranking, scoring, shortlisting, batch approval, or automatic approval.

Release candidate status, Oct 28, 2026: published main `9809b4a` carries the host full pass (172 backend pytest, 109 core, 63 Vitest, scans plus typecheck plus build, 22 browser: 16 original plus 1 real keyless photo plus 5 clearly labelled synthetic interaction proofs). On top of that base, this clone adds incremental stage receipts (`POST /api/runs/async` plus `GET /api/runs/{run_id}/steps`, see [the plan](docs/run-progress-plan.md)), now repaired after the host run showed a failed pipeline being stored without its failure row (failed receipt kept, zero failed step rows, `run_completed` audit). The repair branches on the actual pipeline outcome and persists the original failed receipt with its stopped stage, keeps the run row plus accepted step atomic, stops on journal loss instead of continuing blind, leaves unconfirmed terminal persistence without synthetic overwrite, shares one completion clock reading between step rows and receipt audit entries, serializes worker claim and start, and derives the photo selection caption from the actual current verdict, and the keyless receipt transport note now states the bytes stayed on the LaunchCrew validation server instead of claiming they were sent nowhere. CLI-verified offline so far: 115 unittest collected (112 pass; 3 pre-existing `test_stage_b` socket-bind errors denied by this sandbox, unrelated), 70 Vitest, typecheck, production build, contract regeneration with no diff, both repo scans clean, 234 pytest tests collected. Pending host verification after this checkpoint: the full backend pytest on real Postgres (including the previously failing failure-row test, the strengthened timestamp and profile agreement checks, the 4 new journal, unconfirmed, and registry tests, and the new keyless transport-note honesty assert), migration `004_run_steps`, and the updated real keyless browser flow. No push by this author; no live model calls, deployment, video, or submission are claimed.

The replacement stack is Python FastAPI, Pydantic v2 and OpenAPI, SQLAlchemy and Alembic over Postgres, and TypeScript Next.js with Tailwind, shadcn/ui patterns, and TanStack Query. The frontend uses a checked-in generated OpenAPI client through openapi-fetch. Only FastAPI accesses Postgres. The preserved Python modules in launchcrew/ remain the pipeline implementation. launchcrew/web.py is retained as the superseded stdlib UI; it is not the replacement demo interface.

All newly authored implementation in this migration was built locally Oct 27, 2026, within the Oct 26 to Nov 4 new-work window. Existing LaunchCrew pipeline code and the pre-existing individual approval and agent path change were preserved. No code was copied or ported from another project. Third-party dependencies and the attributed Button pattern retain their own provenance and are not claimed as hackathon-new work. Demo facts are input data, not new code.

## Local setup

Use only demo data. Do not add credentials, real personal data, passwords, or provider tokens to the repo, logs, or receipts. Local Postgres uses trust authentication inside an isolated development environment. It is not a deployment configuration.

`uv 0.11.32` was already installed. pnpm was absent and installed with `npm install --prefix .local/tools pnpm@10.20.0 --cache .local/npm-cache`. No global installation was needed. Use the local launcher below or an existing pnpm of that version. Dependencies are locked in uv.lock and web/pnpm-lock.yaml. Never commit .venv, node_modules, .next, or .local.

```bash
uv sync --frozen
node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web install --frozen-lockfile
scripts/podman-local.sh build
scripts/podman-local.sh up
scripts/podman-local.sh check
```

The run script uses Podman only, workspace-local VFS image storage, and a rootless slirp4netns pod. API, web, and database share the pod network namespace. Web reaches API on port 8000; API reaches Postgres on port 5432. Published localhost ports: web 3001, API 8001. No database port is published by this script. A named Podman volume retains database data. `scripts/podman-local.sh build` also builds the separate migration image, and `up` runs it once against the fresh volume before the runtime API starts, because the runtime API image intentionally never migrates. `scripts/podman-local.sh check` adds a keyless runs, approval gate, and export pass through the web proxy via scripts/verify-container-path.py, and `scripts/podman-local.sh diag` prints bounded sanitized logs for CI artifacts. `scripts/podman-local.sh down` removes only this pod and keeps its volume and images. Do not run `up` twice without `down`.

podman-compose was not installed on this machine. compose.yaml is a compose-compatible alternative for machines with podman-compose and functional rootless bridge DNS. It uses service DNS instead of the shared pod, with a build-time API_URL override. That compose path was not executed here. The verified path is the Podman run script. The old Dockerfile and .dockerignore remain historical artifacts for the superseded stdlib UI; use containers/*.Containerfile and .containerignore for the replacement stack, always through Podman. No Docker daemon was used.

For host development, start local Postgres through Podman and set DATABASE_URL to its localhost port. Then:

```bash
export DATABASE_URL=postgresql://postgres@127.0.0.1:54329/launchcrew
export AUTH_ENABLED=false
export PUBLIC_BASE_URL=http://127.0.0.1:3000
uv run alembic upgrade head
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000 --no-access-log
# In another terminal:
node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web dev
```

The host-development database used in verification is container launchcrew-db, with its data in .local/pgdata and a localhost-only 54329 port. The separately verified full stack has its own database volume. No system Postgres installation was changed.

## Review workflow

Open the new UI at http://127.0.0.1:3001. Agent builder supports list, create, edit, clone, and preview of saved profiles. Preview performs no writes or model calls. Individual approval is fixed, spend limit is zero, and tools remain allowlisted.

Create an agent, choose it on the launch brief, and use the wallet idea: Vegan leather wallet, $49, for Austin commuters, launch on Instagram. Keep the unsupported claim demo checked to seed `best in Texas`. Creating a pack opens a pending Run view immediately: each stage (accepted, deterministic checks, Scout, Maker draft, Checker first check, Maker revision, Checker recheck, final receipt) lands as a stored row with its server time as the pipeline actually reaches it, and the final review unlocks only with the completed receipt. Run review shows Checker blocking the claim and a revised pack with final blocked count zero. The approval queue places pending packs first and refreshes every three seconds. Approve one pack, then use its separate Export pack action. Receipt inspection is available before approval and shows the full check and event record. Demo approval records `demo_placeholder`. No channel connection or publication occurs.

The Desk creates packs through `POST /api/runs/async`: one short transaction stores the pending receipt plus its accepted step row together (a journal failure rolls the whole accept back before any worker starts), one background worker per run id executes the real pipeline, and each real stage boundary is stored as a step row polled through `GET /api/runs/{run_id}/steps` alongside the receipt. A step row that cannot be persisted stops the pipeline with an honest failed receipt instead of continuing without its journal. Polling never starts model work. `POST /api/runs` stays synchronous for compatible clients and returns the completed receipt; `POST /api/campaigns` runs the same pipeline once per day brief. The three creation paths enable optional server-side Meta text synthesis when the runtime key is present, and the explicit photo check route enables paid SAM segmentation only when its own flag, key, budget, and approved-byte gates pass. No SAM call happens on any run, progress, or campaign path. Without keys, the preserved deterministic fallback makes no network call. No run JSON files are created as a new system of record. See [Postgres migration](docs/postgres-migration.md) for transactions, indexes, historical mapping, and retained old JSON files.

## Contract and tests

```bash
uv run python -m unittest discover -s tests -v
uv run pytest -q
uv run python -m scripts.generate_client
node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web client:generate
node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web test
node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web typecheck
node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web build
python3 scripts/scan_repo.py
python3 scripts/check-repo-text.py
```

pytest requires DATABASE_URL to a local Postgres database. It creates a unique temporary schema, applies the real Alembic baseline, and removes only that schema after tests. It covers endpoint behavior, no batch or automatic approval, pending ordering, export gates, concurrent approval, rollback, previews, auth session plumbing, and the committed OpenAPI document. Vitest regenerates types in memory to detect contract drift, checks driver imports, and checks shared controls and response handling. CI runs on every push and pull request, with tests, scans, Podman OCI builds and health checks, and headless Playwright. GitHub Actions has since executed remotely: main run 40665386053 at commit 9809b4a, read at terminal by the orchestrator (prior run 40659590053 was terminal success including containers). Test counts are not listed in the run page text, so no count is claimed here beyond workflow success; the host full-pass counts are recorded at the top of this file from orchestrator-supplied evidence.

Headless browser setup on this Ubuntu 26.04 host:

```bash
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.local/browsers"
export PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64
node web/node_modules/@playwright/test/cli.js install chromium
WEB_URL=http://127.0.0.1:3001 node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web test:e2e
```

Playwright uses real headless Chromium, not a signed-in or headful browser. The host platform override downloads the compatible Ubuntu 24.04 bundle. The tests verify agent builder, approval queue, receipt, and wallet flow at 375, 768, 1024, and 1440 pixels, including screenshots and overflow assertions. Local evidence lives under .local and test-results, not git. Exact results, demo run ids, environment failures and fixes, and visual inspection are in [verification](docs/verification.md).

The repository scan excludes dependency and build directories (.venv, node_modules, .next, .local, caches, browser reports) and scans authored source, docs, schema, workflows, and lockfiles. It distinguishes package-version strings from email addresses. check-repo-text.py runs explicit git grep over tracked source for prohibited punctuation and the legacy brand. It requires newly added files to be staged or committed. Both checks remain fail-closed on errors.

## Backend model API

[Model API verification and exact route boundaries](docs/model-api.md) records the public pages fetched with curl on Oct 27, 2026. The [overview](https://dev.meta.ai/docs) confirms `https://api.meta.ai/v1`, `muse-spark-1.3` and `sam-3.1`, so defaults are unchanged. [Structured output](https://dev.meta.ai/docs/structured-output) confirms strict `json_schema`; the transport now uses it. [Muse Code authentication](https://dev.meta.ai/docs/muse-code/auth) confirms its environment authentication uses the same Model API. `https://api.meta.ai/docs` returned HTTP 404; verification uses the fetched dev.meta.ai pages, not that unavailable page.

Model calls use the existing portal key via environment only, read by FastAPI from `META_API_KEY` at runtime. No separate key is created, and no credential store or portal is searched. A rotated portal key replaces the same environment variable with no code change. No key is placed in a repo file, frontend, database, receipt, build or container configuration.

Three creation paths can call models, each under explicit gates, all through `backend/adapter.py` `execute`: `POST /api/runs` (synchronous, returns the completed receipt), `POST /api/runs/async` (pending receipt plus one background worker per run id with stored step rows), and `POST /api/campaigns` (seven runs, one per day brief). Each run does Spark text synthesis (optional configured Wonder synthesis with Spark fallback) for Scout, Maker, and Checker candidates. `POST /api/runs/{run_id}/photo-check` runs paid SAM segmentation, and only after an explicit Check click passes every photo gate below. No SAM call happens on any run, progress, or campaign path. Every candidate passes deterministic checks against demo facts. Unverified Scout facts are excluded from Maker. Maker accepts checked allowlist sentences only. Checker suggestions never decide verdicts, approve, unblock or verify claims. Final drafts, auth, connectors, database operations, approval and export gates remain deterministic.

Exact non-model business routes: `GET /api/health`; `GET /api/agents`; `GET /api/agents/{name}`; `POST /api/agents`; `PUT /api/agents/{name}`; `POST /api/agents/{name}/clone`; `POST /api/agents/{name}/preview`; `GET /api/queue`; `GET /api/runs/{run_id}`; `GET /api/runs/{run_id}/receipt`; `GET /api/runs/{run_id}/steps`; `GET /api/runs/{run_a}/diff/{run_b}`; `POST /api/runs/{run_id}/revise`; `POST /api/runs/{run_id}/approve`; `POST /api/runs/{run_id}/export`; `DELETE /api/runs/{run_id}/photo`; memory item routes; campaign read and per-day approve/export routes; `GET /api/checker-policies`; `GET /api/model-capabilities`; `GET /api/auth/status`; `GET /api/auth/{provider}/login`; `GET /api/auth/{provider}/callback`; `POST /api/auth/logout`. Provider is google or facebook. `DELETE /api/runs/{run_id}/photo` only detaches the photo at a new revision and never segments. Framework `GET /openapi.json`, `GET /docs`, `GET /docs/oauth2-redirect`, and `GET /redoc` also make no model calls. No new model call is made to render progress, poll status, or run tests.

Paid photo check is explicit, off by default, and single-owner. Defaults keep it off: the enable flag is unset, the global one-shot budget starts at 0 images, and only exact operator-approved bytes are admitted (the photo sha256 must be allowlisted, with a runtime key present). With the flag off or keyless, the check returns `method: not_run` over HTTP 200, sends no bytes, and the UI states SAM is not configured. With all gates passing, admission commits revision N+1 with `photo_status` `check_requested` before transport, exactly one transport owner runs one Files upload plus one Responses segmentation with no retry inside a 30 second operation budget, and finalization attaches the verdict at the same revision without a second bump; a revision that moves first lands `failed_terminal` and the late reply is refused (409). The UI adds an optional PhotoCheck panel: PNG or JPEG up to 1 MiB and 8 megapixels, local-only preview, explicit Check, a detected-only crop suggestion drawn from existing pixels with download after a real draw, and explicit Remove. Any photo state other than a current-revision `detected` check refuses approval and export (422) with the photo reason; removing the photo returns the pack to the text-only path and still needs fresh human approval. Receipts keep only the sanitized summary (label, reason, policy version, actor, time) plus transport counts; no photo bytes, digests, provider file IDs, or geometry are stored, and the crop preview is volatile and never persisted. Run creation never segments; nothing is sent automatically. The preflight note for operators: key presence, pricing and balance checked against the existing max-$1 envelope for the one approved file below, before any paid call.

History, not a current claim: the Oct 27 Files-only upload success plus the historical Spark backend pass (muse-spark-1.3, 3 calls, 5,401 tokens) stay history, not new live SAM and not current paid proof. Current published proof is main `9809b4a` with the host full pass described at the top of this file, including the real keyless photo proof as its 17th browser check. Still open: live SAM balance and operator cap (no automated balance verification exists; only the operator preflight gate is configured), deployment, demo video, and final submission gates. This change adds incremental stage receipts as a product feature: pending receipts, stored step rows, and honest pending/failed/unconfirmed states, with no new model calls for progress rendering, polling, or tests.

Update, Oct 27 evening, superseding the earlier blocked statement for Spark only. Historical live Spark backend pass: model muse-spark-1.3, 3 Spark calls, 5,401 total tokens, Checker still blocked the seeded unverified claim deterministically, approval and export both HTTP 200, run run_40c88a9d14ea48e18cb85386a86545c6, commit ea6666e at that time, via FastAPI TestClient plus standalone Postgres, temporary schema dropped. This is a historical backend pass, not a container pass, not a deployment pass, not a current retest, and not a claim that Spark passes today in every path. Live SAM end to end: OPEN, not passed. Files step failed 400 with original DSC_3252.JPG, 5504 by 8256, 25,956,803 bytes; files step succeeded 200 with derivative DSC_3252_demo_1600.jpg, 1067 by 1600, 496,593 bytes, Accept application/json in diagnostic code; responses never run; product retry never run in the fixed configuration; checked true never recorded; provider file from the successful derivative upload is left until deleted, delete endpoint unconfirmed. A files-only success is not a SAM pass. Demo photo supplied for SAM diagnostics: DSC_3252.JPG and its derivative, in facts/demo_photos/, untracked, not committed. Container-path model tests, for Spark and SAM through the Podman container API with a key at container start, remain OPEN. Tests in the earlier migration run used mocked transport, existing localhost Postgres, and frontend unit tests. No signed-in browser was used and no container was rebuilt in that earlier run.

## Auth status

Auth is planned, not live. Authlib in FastAPI is the sole source of truth when enabled. No real Google or Facebook sign-in was performed. There were no provider credentials available, and no live browser sign-in was used. Auth stays disabled by default. Disabled mode uses `demo_placeholder`; it does not impersonate a signed-in person.

Opt-in configuration uses AUTH_ENABLED=true, HTTPS PUBLIC_BASE_URL, and GOOGLE_CLIENT_ID plus GOOGLE_CLIENT_SECRET and/or FACEBOOK_CLIENT_ID plus FACEBOOK_CLIENT_SECRET, supplied at runtime outside files and logs. Missing provider configuration or HTTPS prevents startup when enabled. Google requests openid, profile, email. Facebook requests public_profile, email. There are no Drive, Instagram, publishing, or unrelated scopes. Configure exact HTTPS callback routes `/api/auth/google/callback` and `/api/auth/facebook/callback` at each provider. The routes use Authlib state and nonce handling, persist state and identity only in Postgres sessions, rotate an opaque random session cookie, and never retain provider tokens. Cookies are Secure, HttpOnly, SameSite=Lax, with an eight hour expiry. Only hashed cookie identifiers are stored server-side. Mutation origins are checked. When enabled, protected APIs require a session and approval_by records the verified provider subject. Mocked session and scope tests validate plumbing, not live provider compatibility. The UI links to FastAPI login routes; no second auth system is included. Review and verify provider setup, logout, expiry cleanup, and end-to-end HTTPS before enabling publicly.

## Design references and third-party attribution

[DESIGN.md](DESIGN.md) is written for LaunchCrew in original words. Repository licenses were fetched from GitHub's license API before any pattern use. These were license-reviewed as candidate references. No source or design-system prose was copied from them:

- [UI/UX Pro Max Skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), MIT.
- [Awesome DESIGN.md](https://github.com/VoltAgent/awesome-design-md), MIT.
- [Taste Skill](https://github.com/Leonxlnx/taste-skill), MIT.
- [Impeccable](https://github.com/pbakaus/impeccable), Apache 2.0.
- [Magic UI](https://github.com/magicuidesign/magicui), MIT, considered but no code used.
- [React Bits](https://github.com/DavidHDev/react-bits), MIT plus Commons Clause in the fetched license, no code used.

[shadcn/ui](https://github.com/shadcn-ui/ui) provides the Button composition pattern using Radix Slot and class-variance-authority; local styling is original. MIT copyright and permission notice are in web/SHADCN-LICENSE.txt. The design avoids decorative animation and component effects in the approval flow. Runtime dependencies include Next.js, React, Tailwind, TanStack Query, openapi-fetch, Radix Slot, class-variance-authority, clsx, tailwind-merge, and Lucide icons under their respective licenses. Test and code-generation packages retain their own licenses. They are third-party dependencies, not new LaunchCrew code.

## V2 Item A, local first slice

Memory CRUD and explicit learning from individually approved runs use the new Postgres memory_items table. The v1 memory table stays intact. Replay compares stored receipts, including differing ideas, without taking actions. Campaign Week creates seven pending Launch Packs in one transaction, each with its own approval and export gates. The review desk has Replay and Campaign views and uses three second TanStack Query polling.

Alembic 002 adds memory_items, campaigns, and campaign_days. Apply migrations before starting this worktree's API. The generated OpenAPI and frontend client include the new routes. No connectors or scheduling were implemented. See [campaign export notes](docs/campaign-export-notes.md) and the Item A section of [verification](docs/verification.md) for offline API evidence and local check results. The broader V2 plan remains future work beyond this slice.

## Preserved CLI and future work

```bash
python3 -m launchcrew.run --idea 'Vegan leather wallet, $49, for Austin commuters' --facts facts/demo_facts.json --agents agents --out runs/local_demo.json --seed-unverified-claim
```

The CLI still writes historical-style JSON receipts and supports its explicit demo approval flag for legacy tests. The new API never supplies that flag. Existing Scout facts filtering, deterministic claim normalization, substring and allowlist checks, Maker revision, Checker vetoes, failed receipts, and approval/export semantics remain in their original modules. tests/ remains intact with added scanner regression tests.

AWS and DNS are preparation only, with no resources or records created. [AWS preparation](docs/aws-prep.md) isolates roles and resources, proposes us-east-1, requires HTTPS end to end, restricts the planned Cloudflare hostname to launchcrew.summitsingh.com, and leaves the cost cap explicitly blank for the owner. Teardown window: after Nov 4 through Nov 9, 2026. This run authorizes no provisioning, DNS, submission, or git push.

Live SAM end to end, v2, submission, deployment, and DNS are not complete or live. Live Spark has a historical backend pass, described above, but is not complete or live as a container or deployment feature. Existing V2-PLAN.md and CONNECTOR-PLAN.md remain future planning, not implemented features. Video and any public deployment require later review. Redis queue, S3 photo storage, Sentry, pgvector, Terraform, a second auth system, WebSockets for run progress, DynamoDB, Mongo, SQLite as primary, Svelte, Astro, Remix, Django, Node backend, and Go backend were not added. Next.js serves the frontend and proxies API calls only; Python owns business logic and database access.
