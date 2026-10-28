# Backend Meta Model API

Public documentation was fetched with curl on Oct 27, 2026. No signed-in browser, portal scraping, credential lookup, or key creation was used. Only boolean runtime key presence was checked.

## Documentation verification

The initial sandbox curl failed with `curl exit 6`. With network access enabled for public documentation, these pages returned HTTP 200:

- [Overview](https://dev.meta.ai/docs): documents base `https://api.meta.ai/v1`, Standard Spark identifiers `muse-spark-1.3`, `muse-spark-1.2`, `muse-spark-1.1`, Contributor identifiers `muse-spark-1.3-contributor`, `muse-spark-1.2-contributor`, and SAM `sam-3.1`. Existing base and model defaults are confirmed and unchanged. Wonder is documented as `muse-wonder-1.0`, but remains opt-in with no new default.
- [Authentication](https://dev.meta.ai/docs/authentication): documents Bearer authentication and the `LLM_` key prefix. Its examples use `MODEL_API_KEY`, which is an example variable name, not an SDK auto-discovery requirement. LaunchCrew exclusively reads `META_API_KEY` from its backend process environment.
- [Muse Code authentication](https://dev.meta.ai/docs/muse-code/auth): documents browser authentication or an API key, and environment `META_API_KEY` taking priority over stored credentials and browser sessions. Muse Code is a CLI using Model API, not a separate product API endpoint. LaunchCrew never invokes its CLI or reads its credential storage.
- [Structured output](https://dev.meta.ai/docs/structured-output): documents Chat Completions `response_format.type=json_schema`, `json_schema.schema`, and `json_schema.strict=true`. Strict schemas require every property and disallow extra properties. The transport now uses these settings rather than the previous `json_object` format, and validates returned string-array objects locally too.
- [File handling](https://dev.meta.ai/docs/file-handling): documents multipart `POST /v1/files`, purpose `user_data`, and referencing uploads using typed `input_image` with `file_id`. Uploaded files do not expire automatically. Only approved demo photos may be uploaded; no production photo storage or retention workflow is implemented.
- [SAM prompts](https://dev.meta.ai/docs/sam/segmenting): documents `sam-3.1`, `POST /v1/responses`, a user message with text and media, `stream=true`, and top-level `metadata.mask_encoding=lossless`. Concept prompts use lossless masks with a tilde marker. Box and point prompts can instead return one-bit masks; this implementation sends only the fixed demo concept prompt `jacket`. Summit approved changing `wallet` to `jacket` on Oct 27, 2026, for the SAM demo only. The Spark demo remains unchanged: Vegan leather wallet, $49, for Austin commuters.
- [SAM output](https://dev.meta.ai/docs/sam/reading-segmentation): documents `response.output_text.delta`, frame markers, object IDs, paired box/mask tags, and `response.completed`. Empty output is a valid zero-match result. The new parser accumulates split deltas, parses boxes and lossless mask dimensions/payloads in memory, rejects malformed or incomplete streams, and discards geometry before returning receipt metadata. It does not decode or persist mask rasters.

`curl -L --max-time 30 https://api.meta.ai/docs` returned HTTP 404. That URL is not a usable documentation page. Verification above comes from fetched public dev.meta.ai pages, including their explicit api.meta.ai request examples. No authenticated endpoint or model compatibility is claimed from documentation alone. Local ignored evidence is `.local/meta-*.html`; no doc HTML is committed.

## Routes and deterministic boundaries

The only FastAPI route that can call Meta Model API is:

- `POST /api/runs`

With a key present, it runs deterministic facts checks first, optional configured Wonder Scout synthesis with Spark fallback, and Spark Scout synthesis when Wonder is disabled. Maker and Checker each have one strict-JSON Spark candidate call. Scout candidates are independently checked against `facts/demo_facts.json`, with unverified entries explicitly marked and excluded from Maker. Maker accepts only independently checked allowlist sentences whose assembled draft also passes the deterministic Checker. Checker candidate claims are rechecked and discarded; they never determine the draft verdict. Final revision and both actual Checker verdicts remain deterministic. No model can approve, unblock, or verify a claim by suggestion.

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
- `POST /api/runs/{run_id}/approve`
- `POST /api/runs/{run_id}/export`
- `GET /api/auth/status`
- `GET /api/auth/{provider}/login`
- `GET /api/auth/{provider}/callback`
- `POST /api/auth/logout`

The provider routes support google and facebook. Framework endpoints `GET /openapi.json`, `GET /docs`, `GET /docs/oauth2-redirect`, and `GET /redoc` also never call models. Auth, connectors, database operations, individual approval and export gates remain deterministic. OAuth identity provider exchanges are unrelated to model transport. Next.js has no model client, endpoint secret or key, and no UI changes were needed.

Without the key, no model network call occurs; drafts and Checker behavior retain deterministic fallback, with `model_used=none`. Runtime errors fall back with exception type only, never exception messages, response bodies or headers. Receipts record mode, models used, Spark attempt count, Wonder attempts and success flag, allowlisted numeric token counts and whether counts are known. Zero totals with unknown counts do not imply free provider usage. Failed pipeline receipts retain safe usage metadata too. Raw model candidate drafts and Checker suggestions are not persisted. Scout rejected claims remain explicitly unverified audit entries, never verified facts.

## SAM opt-in

On Oct 27, 2026, with Summit approval, the fixed SAM demo concept changed from `wallet` to `jacket`. This change applies to the SAM demo only. The Spark idea demo remains unchanged: Vegan leather wallet, $49, for Austin commuters.

SAM defaults to `method=not_run`, `checked=false`. Only a server operator setting `LAUNCHCREW_SAM_DEMO_PHOTO` to a demo image beneath `facts/demo_photos/`, plus runtime key presence, enables it during `POST /api/runs`. No client upload or arbitrary client path is accepted. The demo directory must contain only reviewed demo images. The new server module posts multipart files with purpose `user_data`, then Responses with `input_text`, `input_image.file_id`, streaming and lossless mask metadata. Network timeouts are bounded by a 30 second operation budget. No demo photo was supplied or uploaded in this run.

Visual receipts contain only `method`, `checked`, and optional `error_type`. Checked means segmentation completed, including zero matches; it does not verify product claims. Neither SAM failure nor absence blocks approval or export. Photos, file IDs, boxes and masks never enter receipts or Postgres. Provider uploads would remain until deleted at the provider; no live upload was performed here.

## Key handling and live gates

Model calls use the existing portal key via environment only, server-side on this machine. No separate key was created. No credential store or portal was consulted. The backend reads the process environment at runtime. No key belongs in a file, repo, browser bundle, receipt, database, Containerfile or compose configuration. A rotated portal key replaces the same `META_API_KEY` environment variable with no code change; restart the backend process with the replacement environment.

Live Spark: **BLOCKED**, error type `EnvironmentVariableAbsent`; model used `none`, token counts zero, usage unknown. No live request was made.

Live SAM: attempted Oct 27, 2026, against commit `77f6730` plus the jacket concept change, with approved demo photo `DSC_3252.JPG`; model `sam-3.1`, method `sam-3.1`, checked `false`, error type `HTTPError`. No box or mask geometry and no key material appeared in any receipt. The backend returns only the error type, so provider file upload success or failure is unknown. Approval and export were verified separately on a keyless demo run and were not blocked by SAM.

Live Spark and live SAM remain separate unverified gates. Mocked tests validate wiring, filtering, telemetry and SSE parsing, not live service compatibility. AWS, DNS, v2, submission and live sign-in were not performed. The existing Podman stack and standalone test Postgres were reused without stopping or rebuilding containers.

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
