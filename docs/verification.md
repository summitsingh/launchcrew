# Local verification, Oct 27, 2026

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

Three images were built with `podman build --format oci`, via scripts/podman-local.sh. All three services ran through rootless Podman. Image manifests use application/vnd.oci.image.manifest.v1+json. Runtime user checks: API uid 10001, web uid 1000, database uid 70. The API runs Alembic before serving.

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
| A2 CI | Implemented for every push and pull request; constituent commands verified locally. Remote Actions execution remains unverified because no push is authorized. |
| A3 package managers | uv preinstalled, pnpm locally installed; frozen Python and pnpm installs verified, both lockfiles committed. |
| A4 database | SQLAlchemy and Alembic verified on real local Postgres. Raw psycopg persistence removed; retained SQL file explicitly superseded. |
| A5 frontend | Tailwind, locally styled attributed shadcn/ui Button pattern, and TanStack Query queue/run polling and export mutation state implemented and browser verified. |
| A6 API contract | Pydantic v2 OpenAPI, committed generated TypeScript definitions, typed openapi-fetch calls, regeneration scripts, and drift tests verified. |
| A7 auth | Authlib routes, identity-only scopes, secure opaque cookies, Postgres sessions, subject attribution, rotation, expiry, and mocked callback tests implemented. Disabled by default. Auth is planned, not live; real Google/Facebook sign-in and deployment HTTPS remain unverified without provider credentials. |

## Remaining gates and exclusions

Open gates are independent coordinator verification and any later coordinator push; remote GitHub Actions execution; optional compose-path execution; real Google and Facebook sign-in with provider credentials and HTTPS; deployment TLS including API-to-database TLS; the blank AWS cost cap, later provisioning approval, resource and region review, DNS creation and later teardown verification; live Spark; live SAM; v2 build and lock; demo video; and final submission authorization and execution. AWS, DNS, auth sign-in, v2, Spark, SAM, and submission are not claimed as live or done.

Not added: Redis queue, S3 photo storage, Sentry, pgvector, Terraform, a second auth system, WebSockets for run progress, DynamoDB, Mongo, SQLite as primary, Svelte, Astro, Remix, Django, Node backend, or Go backend. The Next server provides frontend rendering and the API proxy only. No AWS or DNS command was executed, nothing was submitted, and nothing was pushed.

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
