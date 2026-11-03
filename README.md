# LaunchCrew

LaunchCrew is the trust layer for AI launch content for solo founders. Built new for the Meta Global AI Hackathon, Oct 26 to Nov 4, 2026. No code was reused, copied, or ported from any prior codebase.

How it works, in five steps:

1. One idea in: a sentence, a price, an audience.
2. The owner confirms facts with sources. Only confirmed facts enter the pack.
3. Scout, Maker, and Checker run in sequence. Scout gathers, Maker drafts, Checker audits.
4. The owner approves the exact reviewed version. Any edit clears the approval and forces a full recheck.
5. The approved pack is exported, or published through the Ready gate. Nothing publishes without passing the gate. The receipt is the product: every verdict, model call, and approval is recorded.

## Meta models in LaunchCrew

Muse Spark (muse-spark-1.3) through the Meta Model API powers Scout, Maker, and Checker candidates. Scout synthesizes through Wonder first and falls back to Spark only if Wonder is absent or fails, so a run where Scout used Wonder shows 2 Spark calls: Maker and Checker. Deterministic gates decide every verdict: confirmed-facts checks run before any model call, the Checker rechecks every candidate against the approved claims, and no model output can approve, unblock, or verify a claim.

SAM 3.1 photo segmentation: not yet proven live. This line will record exactly what was proven, with receipt evidence and date, once the bounded Phase S proof runs.

## Model boundary invariant

Model calls flow only through the pipeline adapter to the Meta Model API for Spark text candidates, and through the explicit photo-check route to SAM. Deterministic checks run before every model call. Every model output is a candidate that is rechecked against confirmed facts; only checked sentences survive. No model output approves, unblocks, or verifies anything. Approval binds a human approver to an exact version digest. Publishing requires the Ready gate plus the slot idempotency key. No model call is made to render progress, poll status, or run tests.

## Current live proof, Nov 3

Live site https://launchcrew.summitsingh.com serves the published main. All endpoints return 200 and the running image digests equal the publish manifest. Google sign-in is live on the demo site. Instagram is connected for the brand account, and one real post was published through the Ready gate on Nov 3: https://www.instagram.com/p/DfSbBrYDadb/. Only Instagram is a real connection; other platforms are unconnected. Google Drive import is built but not yet proven live. The demo post is a proof artifact and can be archived from the Instagram app at any time.

## Release evidence

The Verify workflow is disabled for the final stretch by owner decision. Release evidence is local suites plus live checks. Last full local run, Nov 1 at af97783: 717 pytest passed, 1777 unittest passed, 352 Vitest passed across 40 test files, tsc 0 errors, production web build 0 errors. Suites are suspended after that by owner decision. Live checks Nov 3 at 83fb497: health, auth status, plans, sitemap, icon, and demo facts all 200, both services 1/1, digests match the manifest.

## Setup

Use demo data only. Never add credentials, tokens, or personal data to the repo, logs, or receipts. Never commit .venv, node_modules, .next, or .local.

```bash
uv sync --frozen
pnpm --dir web install --frozen-lockfile   # pnpm 10.20.0
scripts/podman-local.sh build && scripts/podman-local.sh up
scripts/podman-local.sh check   # keyless runs, approval gate, export pass
scripts/podman-local.sh down    # removes the pod, keeps volume and images
```

Host dev: Postgres on 127.0.0.1:54329 with DATABASE_URL set, AUTH_ENABLED=false, PUBLIC_BASE_URL=http://127.0.0.1:3000, `alembic upgrade head`, then uvicorn on 8000 and `pnpm --dir web dev`. Keyed runs read META_API_KEY from private `.local/.env.local` (mode 600); adding the file alone makes no model call, and SAM stays off unless its own flag, budget, and allowlist are all set.

## Tests

```bash
uv run python -m unittest discover -s tests -v
uv run pytest -q   # needs DATABASE_URL to a local Postgres
pnpm --dir web test && pnpm --dir web typecheck && pnpm --dir web build
python3 scripts/scan_repo.py && python3 scripts/check-repo-text.py
```

Sole source author on this main line: Muse Code CLI. Third-party dependencies keep their own licenses; the shadcn/ui Button pattern is MIT, notice in web/SHADCN-LICENSE.txt. Superseded statuses, dated milestone walls, and long model API notes moved to docs/history.md.
