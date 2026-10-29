# Backend Meta Model API

Public documentation was fetched with curl on Oct 27, 2026. No signed-in browser, portal scraping, credential lookup, or key creation was used. Only boolean runtime key presence was checked.

## Documentation verification

The initial sandbox curl failed with `curl exit 6`. With network access enabled for public documentation, these pages returned HTTP 200:

- [Overview](https://dev.meta.ai/docs): documents base `https://api.meta.ai/v1`, Standard Spark identifiers `muse-spark-1.3`, `muse-spark-1.2`, `muse-spark-1.1`, Contributor identifiers `muse-spark-1.3-contributor`, `muse-spark-1.2-contributor`, and SAM `sam-3.1`. Existing base and model defaults are confirmed and unchanged. Wonder is documented as `muse-wonder-1.0`, but remains opt-in with no new default.
- [Authentication](https://dev.meta.ai/docs/authentication): documents Bearer authentication and the `LLM_` key prefix. Its examples use `MODEL_API_KEY`, which is an example variable name, not an SDK auto-discovery requirement. LaunchCrew exclusively reads `META_API_KEY` from its backend process environment.
- [Muse Code authentication](https://dev.meta.ai/docs/muse-code/auth): documents browser authentication or an API key, and environment `META_API_KEY` taking priority over stored credentials and browser sessions. Muse Code is a CLI using Model API, not a separate product API endpoint. LaunchCrew never invokes its CLI or reads its credential storage.
- [Structured output](https://dev.meta.ai/docs/structured-output): documents Chat Completions `response_format.type=json_schema`, `json_schema.schema`, and `json_schema.strict=true`. Strict schemas require every property and disallow extra properties. The transport now uses these settings rather than the previous `json_object` format, and validates returned string-array objects locally too.
- [File handling](https://dev.meta.ai/docs/file-handling): documents multipart `POST /v1/files`, purpose `user_data`, and referencing uploads using typed `input_image` with `file_id`. Uploaded files do not expire automatically. Only approved demo photos may be uploaded; no production photo storage or retention workflow is implemented.
- [SAM prompts](https://dev.meta.ai/docs/sam/segmenting): documents `sam-3.1`, `POST /v1/responses`, a user message with text and media, `stream=true`, and top-level `metadata.mask_encoding=lossless`. Concept prompts use lossless masks with a tilde marker. Box and point prompts can instead return one-bit masks. The product photo path (`upload_and_segment`) defaults to concept `product`; the fixed `jacket` prompt lives only in the diagnostic demo verification (`verify_demo_photo`), which is not the product path. No live SAM call is made in this state. The Spark demo remains unchanged: Vegan leather wallet, $49, for Austin commuters.
- [SAM output](https://dev.meta.ai/docs/sam/reading-segmentation): documents `response.output_text.delta`, frame markers, object IDs, paired box/mask tags, and `response.completed`. Empty output is a valid zero-match result. The new parser accumulates split deltas, parses boxes and lossless mask dimensions/payloads in memory, rejects malformed or incomplete streams, and discards geometry before returning receipt metadata. It does not decode or persist mask rasters.

`curl -L --max-time 30 https://api.meta.ai/docs` returned HTTP 404. That URL is not a usable documentation page. Verification above comes from fetched public dev.meta.ai pages, including their explicit api.meta.ai request examples. No authenticated endpoint or model compatibility is claimed from documentation alone. Local ignored evidence is `.local/meta-*.html`; no doc HTML is committed.

## Routes and deterministic boundaries

Three FastAPI creation paths can call Meta Model API text synthesis, each under explicit gates, all through `backend/adapter.py` `execute`:

- `POST /api/runs`: runs the pipeline synchronously and returns the completed receipt.
- `POST /api/runs/async`: stores a pending receipt, then runs the same pipeline in one background worker per run id, writing one stored step row per real stage. Polling the steps never starts model work.
- `POST /api/campaigns`: runs the same pipeline seven times, once per day brief, each with its own run id and receipt.

With a key present, each pipeline run does deterministic facts checks first, optional configured Wonder Scout synthesis with Spark fallback, and Spark Scout synthesis when Wonder is disabled. Maker and Checker each have one strict-JSON Spark candidate call. Scout candidates are independently checked against `facts/demo_facts.json`, with unverified entries explicitly marked and excluded from Maker. Maker accepts only independently checked allowlist sentences whose assembled draft also passes the deterministic Checker. Checker candidate claims are rechecked and discarded; they never determine the draft verdict. Final revision and both actual Checker verdicts remain deterministic. No model can approve, unblock, or verify a claim by suggestion. No invocation of SAM happens on any run, progress, or campaign path; SAM is reachable only from the explicit admitted photo check below.

`POST /api/runs/{run_id}/photo-check` runs paid SAM segmentation only after an explicit Check click passes every photo gate in the paid photo check section below. Run creation never segments; nothing is sent automatically.

These FastAPI business routes never call the model API:

- `GET /api/health`
- `GET /api/agents`
- `GET /api/agents/{name}`
- `POST /api/agents`
- `PUT /api/agents/{name}`
- `POST /api/agents/{name}/clone`
- `POST /api/agents/{name}/preview`
- `GET /api/queue`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/receipt`
- `GET /api/runs/{run_id}/steps`
- `GET /api/runs/{run_a}/diff/{run_b}`
- `POST /api/runs/{run_id}/revise`
- `POST /api/runs/{run_id}/approve`
- `POST /api/runs/{run_id}/export`
- `POST /api/runs/{run_id}/photo-check` without all gates passing (returns `not_run`, no provider or segmentation call; the Check POST body still reaches backend validation only)
- `DELETE /api/runs/{run_id}/photo`
- `GET /api/memory`, `POST /api/memory`, `GET /api/memory/{item_id}`, `PUT /api/memory/{item_id}`, `DELETE /api/memory/{item_id}`, `POST /api/memory/from-run/{run_id}`
- `GET /api/campaigns`, `GET /api/campaigns/{campaign_id}`, `POST /api/campaigns/{campaign_id}/days/{day}/approve`, `POST /api/campaigns/{campaign_id}/days/{day}/export`
- `GET /api/checker-policies`
- `GET /api/model-capabilities`
- `GET /api/auth/status`
- `GET /api/auth/{provider}/login`
- `GET /api/auth/{provider}/callback`
- `POST /api/auth/logout`

The provider routes support google and facebook. Framework endpoints `GET /openapi.json`, `GET /docs`, `GET /docs/oauth2-redirect`, and `GET /redoc` also never call models. Auth, connectors, database operations, individual approval and export gates remain deterministic. OAuth identity provider exchanges are unrelated to model transport. `DELETE /api/runs/{run_id}/photo` only detaches the photo at a new revision and never segments. Next.js has no provider client, endpoint secret, or key; the PhotoCheck UI sends photo bytes to the backend check route only on an explicit Check click, never on select, preview, crop, or remove. No new model call is made to render progress, to poll status, or to run tests; model calls happen only for an explicit user run under the existing configuration.

Without the key, no model network call occurs; drafts and Checker behavior retain deterministic fallback, with `model_used=none`. Runtime errors fall back with exception type only, never exception messages, response bodies or headers. Receipts record mode, models used, Spark attempt count, Wonder attempts and success flag, allowlisted numeric token counts and whether counts are known. Zero totals with unknown counts do not imply free provider usage. Failed pipeline receipts retain safe usage metadata too. Raw model candidate drafts and Checker suggestions are not persisted. Scout rejected claims remain explicitly unverified audit entries, never verified facts.

## Paid photo check

Concept reconciliation, Oct 28, 2026: the product photo path defaults to concept `product`. The `jacket` string from Oct 27 SAM diagnostics applies only to the diagnostic demo verification, never to an admitted photo check. A future bounded live SAM preflight will name its exact concept, file, budget, and operator approval before any call, and no call is made now. The Spark idea demo remains unchanged: Vegan leather wallet, $49, for Austin commuters.

The paid photo check is explicit, off by default, and single-owner. The enable flag is unset by default, the global one-shot budget starts at 0 images, and only exact operator-approved bytes are admitted (the photo sha256 must be allowlisted, with a runtime key present). Operator preflight checks key presence, pricing, and balance against the existing max-$1 envelope for the one approved file before any paid call. With the flag off or keyless, the check returns `method: not_run` over HTTP 200 and the UI states SAM is not configured. The explicit Check POST still sends the selected bytes to the LaunchCrew validation server, where `backend/photo_input.py` validates structure and bounds and computes the sha256; those bytes are never forwarded to any segmentation provider. No client path is accepted; only the bytes the operator explicitly approved can pass admission.

With all gates passing, admission commits revision N+1 with `photo_status` `check_requested` before transport, exactly one transport owner runs one Files upload plus one Responses segmentation with no retry inside a 30 second operation budget, and finalization attaches the verdict at the same revision without a second bump. A revision that moves first lands `failed_terminal` and the late reply is refused (409). The UI adds an optional PhotoCheck panel: PNG or JPEG up to 1 MiB and 8 megapixels, browser-local preview before Check (selected pixels stay in the browser until Check is clicked), explicit Check, a detected-only crop suggestion drawn from existing pixels with download after a real draw, and explicit Remove. Any photo state other than a current-revision `detected` check refuses approval and export (422) with the photo reason; removing the photo returns the pack to the text-only path and still needs fresh human approval.

Public receipts, logs, and server-backed rendered receipt fields keep only the sanitized summary (label, reason, policy version, actor, time) plus transport counts (attempts, uploads, segmentations, handling, note). Checked means segmentation completed, including zero matches; it does not verify product claims. No photo bytes, digests, provider file IDs, boxes, or masks persist in public receipts, logs, or server-backed rendered receipt fields. The browser necessarily holds selected pixels and transient crop geometry for local preview; explicit Check sends bytes to LaunchCrew backend validation, and keyed approved segmentation returns needed transient crop data. The sha256 digest alone is stored in the private `sam_calls` control ledger in Postgres (`backend/migrations/versions/003_photo_sam_calls.py`) as the approved-byte identity required for admission replay. The crop preview is volatile and never persisted. Provider uploads would remain until deleted at the provider. Run creation never segments; nothing is sent automatically.

## Key handling and live gates

Model calls use the existing portal key via environment only, server-side on this machine. No separate key was created. No credential store or portal was consulted. The backend reads the process environment at runtime. No key belongs in a file, repo, browser bundle, receipt, database, Containerfile or compose configuration. A rotated portal key replaces the same `META_API_KEY` environment variable with no code change; restart the backend process with the replacement environment.

Live Spark: **BLOCKED**, error type `EnvironmentVariableAbsent`; model used `none`, token counts zero, usage unknown. No live request was made.

Live SAM: attempted Oct 27, 2026, against commit `77f6730` plus the jacket concept change, with the reviewed demo file; model `sam-3.1`, method `sam-3.1`, checked `false`, error type `HTTPError`. No box or mask geometry and no key material appeared in any receipt. The backend returns only the error type, so provider file upload success or failure is unknown. Approval and export were verified separately on a keyless demo run. This stays history: a Files-only success plus an attempted SAM is not new live SAM and not current paid proof, and the keyless approval path above predates the paid photo gates (a photo-bearing pack now needs a current-revision `detected` check plus fresh approval).

Live Spark and live SAM remain separate unverified gates. Published proof on main is `a6cd81f` (host `5a186a5 --all` TERMINAL exit 0: 271 backend pytest, 234 core, 71 Vitest, 30 contracts plus typecheck plus build, 24 browser in 1.9min with 18 route-interception-free plus 6 labelled synthetic photo UI proofs; CI `40695455958` TERMINAL SUCCESS on the actual Linux container path; CFN plus test-only 119 PASS; PG 55507 binding harness PASS). Earlier `9809b4a` counts stay history. Still open: live SAM balance and operator cap (no automated balance verification exists; only the operator preflight gate is configured), deployment, demo video, and final submission gates. Mocked tests validate wiring, filtering, telemetry and SSE parsing, not live service compatibility. AWS, DNS, v2, submission and live sign-in were not performed. Historical Oct 27 Spark backend pass (muse-spark-1.3, 3 calls, 5,401 total tokens) stays history, separate from the current keyless and offline proof.

## Truth and transport pass, Oct 28, 2026

No live provider calls were made in this pass. Preflight balance and the enforceable cost gate are still unverified, and only an already-approved bounded test may later execute. No real upload, segmentation, Spark, or Wonder calls were performed here.

- Capability flags: `GET /api/model-capabilities` returns sanitized booleans (`spark_configured`, `wonder_configured`, `sam_configured`), allowlisted variants (`spark_variant` standard, contributor, unknown, or not_configured; `wonder_variant` standard, unknown, or not_configured), and a static note. Key presence means configuration present only. This readonly check does not verify availability or credits, and the endpoint makes no live call. Actual calls are in receipts. No keys, base URLs, paths, or secrets are exposed, and raw `META_MODEL` or `META_WONDER_MODEL` values are never returned. The footer reads this endpoint: Configuration unavailable on query error (error has priority over loading), Loading configuration while pending or when data is absent, "not configured" when keyless, and "Configuration present" otherwise with no claim that it was never tested. Stored run usage on each receipt stays labeled as stored usage.
- Receipt usage truth: `model_usage.data_mode` is derived from actual attempted requests on that run, not from current configuration, with versioned basis `data_basis=v2` and safe `request_provider` (meta, unknown, or none). The provider is classified at attempt time from the effective base URL by strict parsing: HTTPS with exact host api.meta.ai, default port 443, and no embedded credentials is meta; all other, malformed, spoof, HTTP, localhost, custom, or credential-bearing endpoints are unknown. No URL, key, path, or raw env value is persisted. `not_sent` means no attempt was made and renders as Nothing attempted with current basis. `standard_no_train` applies only when every attempt used a Standard variant to the documented Meta endpoint; its note describes the request variant, not an independent certification of provider privacy behavior. Contributor runs report `contributor` with explicit wording that content may be used as training data and sending it gives permission to train. Mixed runs report `mixed` with the same training permission warning for Contributor content. Anything with an unknown variant, unknown provider, or missing provenance reports `unknown` with no training guarantee claimed; historical stub attempts without provider also report unknown. Failed attempts count because the attempted model and provider are recorded, including failures; the raw configured string is sanitized to the allowlist or `unknown` before persistence. Historical receipts without the new basis keep their original stored JSON unchanged for audit and render as unverified unknown in the UI even when they contain the old hardcoded `standard_no_train` value. Coding inference used to build this product is not product use and is not counted.
- SAM transport: `/files` now sends `Accept: application/json` (HTTP 200 JSON per the file upload reference) and `/responses` sends `Accept: text/event-stream` (streaming Responses per the segmentation reference). Order is one upload then one Responses with no automatic retry. A files failure blocks the Responses call. Disabled, keyless, or photo-less runs make zero transport calls. Parser, geometry privacy, and receipt shape are unchanged.
- Build-context boundary: `.containerignore` and `.dockerignore` now exclude `facts/demo_photos/` and photo extensions (`jpg`, `jpeg`, `png`, `heic`, `webp`) while preserving `facts/demo_facts.json`. This repo currently has no photos, so the published image is clean; the exclusion keeps future private fixtures out of published images.

## Local verification evidence

Final commands and results:

- `DATABASE_URL=postgresql://postgres@127.0.0.1:54329/launchcrew .venv/bin/python -m pytest -q --disable-warnings --tb=short --basetemp=.local/pytest-models`: 39 passed, 111 dependency deprecation warnings. Uses isolated schema on the existing Postgres, mocked model transports, no provider key.
- `TMPDIR=$PWD/.local .venv/bin/python -m unittest discover -s tests -q`: 38 passed.
- `node .local/tools/node_modules/pnpm/bin/pnpm.cjs --dir web test`: Vitest 6 passed. No UI files changed, so Playwright was not rerun under the task's backend-only test rule. No browser was used in this run.
- `python3 scripts/scan_repo.py`: pass, every category zero, including secrets, punctuation and legacy brand.
- `python3 scripts/check-repo-text.py`: both counts zero. Explicit tracked-source grep excludes `__pycache__` and `.git`, including newly staged source.
- `git diff --check`: pass.
- `python3 scripts/verify_meta.py` and `python3 scripts/verify_sam.py`: no network, runtime key absent, SAM not_run.

Initial verification failures, all corrected or rerun successfully:

- `backend/tests/conftest.py`: `OperationalError` under sandbox localhost restrictions. The authorized rerun against the existing localhost database passed.
- `tests/test_receipt.py`: `AssertionError` in two old fixtures. The transport fixture now supplies its schema and checks strict json_schema rather than json_object. The filtering fixture now supplies an offline key and separate Scout/Maker/Checker results. Existing filtering and redaction assertions remain.
- Public docs curl: exit 6 under sandbox DNS restrictions; authorized public-doc fetch succeeded. The api.meta.ai docs URL remained HTTP 404 and is not cited as verification.

No final test or scan failure remains. No Podman image build or container run was performed; the existing pod was left running. Local commits require independent coordinator verification before any coordinator push. Remaining gates: live Spark; live SAM with reviewed demo photo; real identity-provider sign-in and HTTPS; deployment/TLS review and authorization; AWS provisioning; DNS; v2; remote CI; demo video; final submission authorization and execution. None is claimed complete here.

## Bounded live proof harness, source only

Source only, no live calls made here. Root owns review plus offline PG plus scans plus full relevant CI, then an explicit live run under already approved scope. Harness source plus test pass does not mark the whole product complete.

AWS build plus RDS plus Spark proof runs as a private ECS one-off using the exact deployed API image digest and the actual RDS runtime identity, via `backend/live_meta_proof.py` with task command Python plus module plus live plus spark mode. SAM host route proof runs host-local via the actual photo route plus private DB direct to Meta with the exact approved JPEG, via `scripts/verify_live_meta.py --live`. The public HTTPS browser flow is separate. Public video image is withheld. No AWS photo asset transfer occurs.

Spark bounds: one pipeline, three stages, at most three total HTTP attempts including failures, durable decrement before send, durable nonresettable one-shot latch before first HTTP, refuse reuse after any attempt or crash. Fixed Standard muse-spark-1.3, exact https origin plus chat path, max_completion_tokens 2048, n 1, serialized body at most 32 KiB, no Wonder, no tools, no redirects, no retries. Keys are never logged. Receipt needs spark_calls 3, wonder 0, empty errors, plus per call success with numeric usage and meta provenance. spark_mode alone means only at least one success. Uncertainty latches with no resend. Planning assumes 3.958272 USD for full model context, separate from SAM 1 USD. The byte bound is not a verified tokenizer count.

SAM bounds: one Files upload with Accept JSON plus at most one SSE segmentation only after valid upload success, existing credits, no retry, no new payment, no new key. Files body carries expires_after anchor created_at plus 3600 seconds before the final file part. Upload metadata needs integer created_at and expires_at with exact 3600 difference plus valid file id. Missing or invalid ends terminal with budget spent, no retry, no third DELETE. Original bytes are kept. Published SAM price seen as 0.0025 per image; a Files free statement was not found, so no all free claim is made and no hard provider cap is claimed. Root verifies current price and operation bound before live. Approval already covers exact asset plus one upload plus at most one segmentation. Finally budget is 0 and SAM is disabled regardless of success.

Secrets: the proof uses a dedicated fifth Meta product key secret outside the four stack secrets, via a reviewed env to SecretsManager loader with metadata only output. The narrow proof execution role reads only runtime DB plus Meta, with an empty task role. Public API stays keyless with no global spend guard. The fifth secret bills at 0.40 per secret month prorated, with 7 day recovery and no force, and no hard cap. Photo approval covers only a Meta upload, not a copy to AWS stores or logs.
