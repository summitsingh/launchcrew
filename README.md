# LaunchCrew

LaunchCrew is the trust layer for AI launch content for solo founders. Built new for the Meta Global AI Hackathon, Oct 26 to Nov 4, 2026. No code was reused, copied, or ported from any prior codebase. Solo project. Indie track, theme: Build for Your World.

Demo video: https://www.youtube.com/watch?v=17A0uiV-adQ

How it works, in five steps:

1. One idea in: a sentence, a price, an audience.
2. The owner confirms facts with sources. Only confirmed facts enter the pack.
3. Scout, Maker, and Checker run in sequence. Scout gathers, Maker drafts, Checker audits.
4. The owner approves the exact reviewed version. Any edit clears the approval and forces a full recheck.
5. The approved pack is exported, or published through the Ready gate. Nothing publishes without passing the gate. The receipt is the product: every verdict, model call, and approval is recorded.

## Meta models in LaunchCrew

Muse Spark (model ID `muse-spark-1.3`), called through the Meta Model API, powers the Scout, Maker, and Checker agents' candidates and the owner-gated Spark generation features. Scout has an optional Wonder synthesis path, but the current spend guard permits only `muse-spark-1.3`, so Wonder cannot make a live call and Scout falls back to Spark. Checker verdicts on factual claims are deterministic code, not model output: confirmed-facts checks run before any model call, the Checker rechecks every candidate against the approved claims, and no model output can approve, unblock, or verify a claim.

SAM 3.1, called through the Meta Model API, runs photo checks on product images through segmentation via the explicit POST /api/runs/{run_id}/photo-check route when its configuration, budget, and allowlist permit. SAM 3.1 live segmentation was proven on Nov 4, 2026 in a one-shot proof run (1 upload, 1 segmentation, label detected, method sam-3.1, exactly 1 ledger row, within its spend ceiling).

Spark and SAM are the only AI models the launch pipeline and the photo-check route call, and both are Meta models reached through the Meta Model API. The codebase also contains an optional image-generation route for media experiments (OpenAI gpt-image-1, xAI grok-2-image, Google imagen-4.0-generate-001). That route is outside the launch pipeline: it runs only when an operator supplies that provider's own key, it is not used by the demo, by any proof run, or by the hosted site, and no output from it can enter a launch pack.

The demo video narration uses Muse text-to-speech (Warm Pebble voice) for voice output only; it is not part of the app runtime. No speech-to-text is used anywhere in the app or the demo; voice-memo intake accepts owner-supplied transcript text only.

## Model boundary invariant

Launch-pipeline model calls flow through the pipeline adapter to the Meta Model API for Spark text candidates, and photo checks flow through the explicit photo-check route to SAM. Owner-gated Spark generation and the separately keyed image-generation route are additional explicit model-call paths. Deterministic checks run before every launch-pipeline model call. Every launch-pipeline text output is a candidate that is rechecked against confirmed facts; only checked sentences survive. No model output approves, unblocks, or verifies anything. Approval binds a human approver to an exact version digest. Publishing requires the Ready gate plus the slot idempotency key. No model call is made to render progress, poll status, or run tests.

## Current live proof, Nov 4

Live site: https://launchcrew.summitsingh.com, served from a single EC2 instance since Nov 4, 2026, in public demo mode with no login. Instagram is connected for the brand account. Real posts published through the Ready gate: Nov 3, https://www.instagram.com/p/DfSbBrYDadb/, and on Nov 4 the two demo-product launches, the Men's Classic Bomber at https://www.instagram.com/p/DfV0ItDDEQC/ and the Women's Classic Regular moto at https://www.instagram.com/p/DfV0lR3DMEs/, each published with its own demo product image. The live deploy is main commit 3f6c57f. The public queue was trimmed on Nov 4 to the Nov 3 proof run plus the runs created for the final demo filming. Spark live proof passed on Nov 4, 2026 (3 live calls, receipt verified, seeded veto blocked, SPARK PROOF PASS). SAM live proof is recorded in the Meta models section above. Only Instagram is a real connection; other platforms are unconnected. Google Drive import is built but not yet proven live. The demo posts are proof artifacts and can be archived from the Instagram app at any time.

## Demo product images

The demo uses 10 product images served by the web app from `web/public/demo-products/`, at the URL path `/demo-products/<file name>`.

Only the Men's Classic Bomber and the Women's Classic Regular moto are real Summit Leather Co. products; the other items are fictional demo products created for the LaunchCrew demo catalog, and the flat lay mixes the two real jackets with fictional accessories. Never present the fictional items as real products.

| Product | File | Served at | Real or fictional | Demo use |
| --- | --- | --- | --- | --- |
| Men's Classic Bomber jacket, black, male model, Austin downtown street | product-01-bomber.jpg | /demo-products/product-01-bomber.jpg | Real Summit Leather Co. product | Instagram post image; media library attach |
| Women's Classic Regular moto jacket, black, belted, female model, Austin backdrop | product-02-moto.jpg | /demo-products/product-02-moto.jpg | Real Summit Leather Co. product | SAM photo check (jacket photo); media library attach |
| Bifold wallet, black, studio shot on warm stone | product-03-wallet.jpg | /demo-products/product-03-wallet.jpg | Fictional demo product (the demo's existing $49 wallet hero) | Demo hero product shot; media library attach |
| Slim card holder, cognac tan, studio shot | product-04-card-holder.jpg | /demo-products/product-04-card-holder.jpg | Fictional demo product | Media library attach |
| Structured tote bag, black, model in Austin storefront | product-05-tote.jpg | /demo-products/product-05-tote.jpg | Fictional demo product | Instagram post image; media library attach |
| Weekender duffel bag, black with tan handles, studio shot | product-06-duffel.jpg | /demo-products/product-06-duffel.jpg | Fictional demo product | Media library attach |
| Belt, black, brushed metal buckle, coiled | product-07-belt.jpg | /demo-products/product-07-belt.jpg | Fictional demo product | Media library attach |
| Pair of gloves, black, flat lay with jacket sleeve edge | product-08-gloves.jpg | /demo-products/product-08-gloves.jpg | Fictional demo product | SAM photo check (secondary detail shot); media library attach |
| Chelsea boots, black leather, concrete with soft shadows | product-09-boots.jpg | /demo-products/product-09-boots.jpg | Fictional demo product | Media library attach |
| Catalog flat lay: both jackets folded with wallet, belt, and gloves, top-down | product-10-catalog-flatlay.jpg | /demo-products/product-10-catalog-flatlay.jpg | Mixed: real jackets (rows 1 and 2) with fictional accessories (rows 3, 7, 8) | Catalog closing shot |

## Outside services

The Instagram Graph API is a non-AI service used for publishing approved posts and for verifying published posts afterward. It is not an AI model and is listed separately from the Meta models.

## Release evidence

Release evidence is local suites plus live checks; the Verify workflow is disabled for the final stretch by owner decision. Nov 4, 2026, at the Step 2 deploy (commit d66c449): web build passed, scripts/check-repo-text.py passed, scripts/scan_repo.py passed with zero findings, and the live site verified through its public name (health, queue, connections, publish board). The last full test-suite run remains the Nov 1 run recorded in docs/history.md.

## Setup

LaunchCrew runs locally with no sign-up. The hosted site (`launchcrew.summitsingh.com`) works in public demo mode with no login. A Meta Model API key is optional: the code reads `META_API_KEY` from the backend process environment. Without a key, launch runs use the deterministic fallback path. `.env.example` contains variable names, empty credential placeholders, and a non-secret `false` default for the SAM flag; it contains no credential values.

Use demo data only. Never add credentials, tokens, or personal data to the repo, logs, or receipts. Never commit .venv, node_modules, .next, or .local.

Prerequisites: uv, pnpm 10.20.0, and podman for the container path; host dev also needs a local Postgres.

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

Muse Code CLI authored the original product implementation. Codex contributed the UI overhaul, beginning with the Step 2 design system and app shell, Nov 4, 2026. Third-party dependencies keep their own licenses; shadcn/ui components are MIT, notice in web/SHADCN-LICENSE.txt. Superseded statuses, dated milestone walls, and long model API notes moved to docs/history.md.

The new shell is enabled by default. Set the server environment variable `LAUNCHCREW_NEW_UI=false` to use Classic throughout the workspace. Settings > Advanced > Classic workspace also opens `/classic` while the flag is enabled. Step 2 adds shell navigation and route adapters to existing screens; the Review, Launches, New launch, Schedule, and full Settings redesigns remain later work. See [the Step 2 report](docs/ui-step-2-2026-11-04.md) for scope and verification limits.
