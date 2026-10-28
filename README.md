# LaunchCrew

LaunchCrew turns approved demo facts into a launch pack through Scout, Maker, and Checker. A human reviews each pack, approves it individually, then exports it. There is no posting, sending, paying, submitting, screening, ranking, scoring, shortlisting, batch approval, or automatic approval.

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

The run script uses Podman only, workspace-local VFS image storage, and a rootless slirp4netns pod. API, web, and database share the pod network namespace. Web reaches API on port 8000; API reaches Postgres on port 5432. Published localhost ports: web 3001, API 8001. No database port is published by this script. A named Podman volume retains database data. `scripts/podman-local.sh down` removes only this pod and keeps its volume and images. Do not run `up` twice without `down`.

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

Create an agent, choose it on the launch brief, and use the wallet idea: Vegan leather wallet, $49, for Austin commuters, launch on Instagram. Keep the unsupported claim demo checked to seed `best in Texas`. Run review shows Checker blocking the claim and a revised pack with final blocked count zero. The approval queue places pending packs first and refreshes every three seconds. Approve one pack, then use its separate Export pack action. Receipt inspection is available before approval and shows the full check and event record. Demo approval records `demo_placeholder`. No channel connection or publication occurs.

The API performs pipeline work synchronously. Status and queue use polling, without a worker queue or WebSockets. Optional model calls are forcibly disabled by the new adapter even if a provider environment variable exists. No run JSON files are created as a new system of record. See [Postgres migration](docs/postgres-migration.md) for transactions, indexes, historical mapping, and retained old JSON files.

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

pytest requires DATABASE_URL to a local Postgres database. It creates a unique temporary schema, applies the real Alembic baseline, and removes only that schema after tests. It covers endpoint behavior, no batch or automatic approval, pending ordering, export gates, concurrent approval, rollback, previews, auth session plumbing, and the committed OpenAPI document. Vitest regenerates types in memory to detect contract drift, checks driver imports, and checks shared controls and response handling. CI runs on every push and pull request, with tests, scans, Podman OCI builds and health checks, and headless Playwright. It is committed locally only; GitHub Actions has not been executed remotely.

Headless browser setup on this Ubuntu 26.04 host:

```bash
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.local/browsers"
export PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64
node web/node_modules/@playwright/test/cli.js install chromium
WEB_URL=http://127.0.0.1:3001 node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web test:e2e
```

Playwright uses real headless Chromium, not a signed-in or headful browser. The host platform override downloads the compatible Ubuntu 24.04 bundle. The tests verify agent builder, approval queue, receipt, and wallet flow at 375, 768, 1024, and 1440 pixels, including screenshots and overflow assertions. Local evidence lives under .local and test-results, not git. Exact results, demo run ids, environment failures and fixes, and visual inspection are in [verification](docs/verification.md).

The repository scan excludes dependency and build directories (.venv, node_modules, .next, .local, caches, browser reports) and scans authored source, docs, schema, workflows, and lockfiles. It distinguishes package-version strings from email addresses. check-repo-text.py runs explicit git grep over tracked source for prohibited punctuation and the legacy brand. It requires newly added files to be staged or committed. Both checks remain fail-closed on errors.

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

## Preserved CLI and future work

```bash
python3 -m launchcrew.run --idea 'Vegan leather wallet, $49, for Austin commuters' --facts facts/demo_facts.json --agents agents --out runs/local_demo.json --seed-unverified-claim
```

The CLI still writes historical-style JSON receipts and supports its explicit demo approval flag for legacy tests. The new API never supplies that flag. Existing Scout facts filtering, deterministic claim normalization, substring and allowlist checks, Maker revision, Checker vetoes, failed receipts, and approval/export semantics remain in their original modules. tests/ remains intact with added scanner regression tests.

AWS and DNS are preparation only, with no resources or records created. [AWS preparation](docs/aws-prep.md) isolates roles and resources, proposes us-east-1, requires HTTPS end to end, restricts the planned Cloudflare hostname to launchcrew.summitsingh.com, and leaves the cost cap explicitly blank for the owner. Teardown window: after Nov 4 through Nov 9, 2026. This run authorizes no provisioning, DNS, submission, or git push.

Live Spark, live SAM, v2, submission, deployment, and DNS are not complete or live. Existing V2-PLAN.md and CONNECTOR-PLAN.md remain future planning, not implemented features. Video and any public deployment require later review. Redis queue, S3 photo storage, Sentry, pgvector, Terraform, a second auth system, WebSockets for run progress, DynamoDB, Mongo, SQLite as primary, Svelte, Astro, Remix, Django, Node backend, and Go backend were not added. Next.js serves the frontend and proxies API calls only; Python owns business logic and database access.
