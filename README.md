# LaunchCrew

See [Machine fallback](AUTOMATION-PLAN.md#machine-fallback) for the primary machine, fallback order, Mac mini readiness, and repo state recovery rule.

LaunchCrew is built for the Meta Global AI Developer Hackathon. This is hackathon-only work for Oct 26 to Nov 4, 2026, with the Oct 30-31 Idea to Launch Pack v1 hardening milestone. Python 3 standard library only, no installation or external dependencies.

New in v1: agent creation and storage (create, load, edit, clone, test), a Spark strict-JSON pipeline with deterministic checks first, a receipt log, and approval plus export. The vegan leather wallet idea, `facts/demo_facts.json`, demo agents, and demo runs are demo data only. No real customer data or real PII belongs in this project.

V1 is approval plus export only. Nothing posts, sends, pays, or submits automatically. There is no Instagram or social connector in v1. The public repository exists; coordinator-managed updates contain only hackathon work and demo data. The project has not been submitted to the hackathon.

Run from `/home/summit/launchcrew`:

```bash
python3 -m unittest discover -s tests -v
python3 -m launchcrew.run --idea 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram' --facts facts/demo_facts.json --agents agents --out runs/demo_001.json
python3 -m launchcrew.run --idea 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram' --facts facts/demo_facts.json --agents agents --out runs/demo_002.json --approve --seed-unverified-claim
```

Without approval, the receipt records `pending_approval`. `--approve` simulates a human tap, records `demo_human`, and sets `approved_for_export`. Both commands store a local JSON receipt including drafts. Export is a local file action. Nothing posts, sends, pays, or submits. This stage prepares local files only; no remote, push, hackathon submission, or social posting is performed.

Scout, Maker, and Checker all use department Growth and approval level `approve_each`, with zero spend limit. Agent profiles live in `agents/`, one pretty printed, sorted JSON file per agent. `launchcrew.agents` provides `create_agent`, `load_agent`, `save_agent`, `list_agents`, `edit_agent`, `clone_agent`, and `test_agent`. Names use letters, digits, underscores, and hyphens. `test_agent` reads a profile and returns a preview without writes or model calls. Example:

```python
from launchcrew.agents import test_agent
preview = test_agent('Scout', 'Demo vegan leather wallet')
print(preview)
```

The pipeline checks facts deterministically before optional Scout synthesis, then runs Scout, Maker v1, Checker v1, Maker revision, Checker v2, and receipt storage. Every step appears in the event log. Scout attaches demo source labels to verified facts; unknown model facts are marked unverified and excluded from Maker. Model risks remain unverified hypotheses. Maker builds post and email drafts from approved claims. Checker checks the explicit claims list and scans draft sentences, including the exact phrase `best in Texas`. The `--seed-unverified-claim` flag is a demo test seed, not normal Maker behavior. It deliberately adds that phrase to v1, which Checker blocks with `Claim not found in facts file`. Revision rebuilds drafts from verified facts. A final blocked claim prevents successful receipt creation and export.

Claim-list matching preserves the existing normalized fact and approved-claim containment rule. Draft validation is stricter: every sentence must equal a normalized approved allowlist sentence, with no added assertions. A mixed approved plus unsupported sentence is blocked. Checker separately scans superlatives and absolutes (including best, number 1, only, guaranteed, perfect, unbeatable), and punctuation-sensitive numbers, prices, percentages, and numeric or month-name dates against the facts file. The exact phrase `best in Texas` remains blocked. Unmatched values report their type only. Maker emits separate allowlist sentences. This checker uses deterministic substring, sentence, superlative, and number checks, not general natural language verification. Unknown claims and unrecognized paraphrases are blocked, never guessed. Normalization strips punctuation, so this remains a conservative demo checker, not a semantic proof system.

Failures persist a `status: failed` partial receipt at the requested output path, with completed event steps, stopped step, error type only, pending approval, and submission flags false. They contain no failed input or exception messages. CLI failures exit non-zero. Failed and pending receipts cannot be exported. A final blocked draft prevents creation of a successful receipt.

## Local web approval UI

```bash
python3 -m launchcrew.web
```

Open `http://127.0.0.1:8765`. The default binds only to 127.0.0.1. Set `LAUNCHCREW_PORT` to change the port. Public exposure is a separate deployment decision. `LAUNCHCREW_HOST` explicitly changes the bind address; the prepared container sets it to 0.0.0.0 and uses `PORT`, default 8765. No credentials, authentication, or production data belong in the demo UI. See DEPLOY-CHECKLIST.md before any public deployment.

Enter the demo wallet idea, price $49, audience Austin commuters, then tap Run. Scout, Maker v1, Checker v1, Maker v2, Checker v2, summary, approval state, and visual verification appear on the run page. Tap Approve for export for a clean pending run. The human action records `web_human`, `approved_for_export`, and a timestamp. Export pack JSON downloads one receipt containing the post and email drafts; the run view also displays both drafts as plain text inside the JSON panels. Receipt JSON is a separate inspection link, available before approval, and does not constitute approved export. The CLI `demo_human` simulation stays available for tests.

Run storage is local `runs/`. Open `/run/demo_002` after the seeded CLI command to show the Checker block and revision case. Every route stops at approval plus export. There are no social connector or submission actions. Request logging is disabled; cross-origin form posts are refused.

## Agent tools

The UI displays profiles without editing. The CLI agent tools are the Python functions documented above, for example `python3 -c "from launchcrew.agents import list_agents; print(list_agents())"`. Use `create_agent`, `edit_agent`, `clone_agent`, and `test_agent` through Python for profile management.

## Optional model configuration

- `META_API_BASE_URL`: default `https://api.meta.ai/v1`.
- `META_API_KEY`: optional, supplied through the environment only. Never store it in this repository or print it.
- `META_MODEL`: default `muse-spark-1.3`. This is a placeholder to verify against current Meta Model API documentation. Neither this model identifier nor the endpoint compatibility was verified against live docs in this session.
- `META_WONDER_MODEL`: optional Scout synthesis model. When absent or unsuccessful, the caller uses Spark or deterministic fallback. Wonder is never required.

With no key, Spark explicitly returns `deterministic_fallback`, `model_used: none`, and a note explaining that no call occurred. With a key, the transport attempts an OpenAI-compatible chat completions POST requesting `json_object`, with a 30 second timeout. Parsed objects are still checked against facts. API or JSON errors return only their error type and fall back deterministically. Model access was tested using mocked transport only; live API access is not claimed. Deterministic Maker and Checker remain usable without any model. `spark_for_agent` composes agent instructions for optional synthesis. Spark attempt counts exclude optional Wonder requests; `wonder_used` records successful Wonder synthesis.

`model_usage.data_mode` states the intent `standard_no_train` for user data. It is not a verified API setting or training-policy guarantee. Input must remain demo data. No keys are looked up from local credential stores.

## Live verification preparation

```bash
python3 scripts/verify_meta.py
```

Without `--live`, this script makes no network call even if a key exists. Without a key it reports key missing, the placeholder model and endpoint unverified, and the approved route. Never look up a key in Bitwarden or any credential store.

Summit provides a Meta Model API key through the environment at runtime only, never in a file, repo, chat, or log, for a single live test run, or Summit approves a separate key creation in the Meta developer console for LaunchCrew testing.

The live Spark test is approved but not yet run. A later authorized operator may run `python3 scripts/verify_meta.py --live`. It attempts one strict JSON call with a 30 second timeout and checks returned claims against demo facts. Runtime `META_MODEL` controls any override; no new model is guessed. Standard placeholder is `muse-spark-1.3`; Contributor variant from the supplied secondary docs is `muse-spark-1.3-contributor`, not verified here. Existing `json_object` response_format is a live-test risk because secondary docs describe `json_schema` structured output. Live Spark is NOT verified until a Summit-approved live run succeeds. Demo runs stay in deterministic_fallback until then by leaving META_API_KEY unset. The existing CLI and UI still optionally call Spark if a runtime key is present, so do not provide one for deterministic demos.

The live SAM test is approved but not yet run. Run `python3 scripts/verify_sam.py` for preparation status only, with no network calls. Neither live test is run in Stage C. SAM preparation only: visual_verification remains `not_run`. Nov 1 will use direct `POST https://api.meta.ai/v1/files`, multipart file with purpose `user_data`, then `POST https://api.meta.ai/v1/responses`, model `sam-3.1`, user message with `input_text` and `input_image` containing `file_id`, `stream: true`, and metadata `mask_encoding: lossless`. Parse SSE output containing the box tag and lossless mask. This is a documented code plug point only, no photo checker is implemented. Use direct api.meta.ai, not Muse CLI: its --image flag sends a regular image part.

## Deployment and submission preparation

Dockerfile uses Python standard library only, non-root UID 10001, and explicitly binds the container interface. It copies only app, agents, and facts, then creates an empty writable runs directory. All local receipts, including demos, stay out of the image. No database or extra Python packages. No image was deployed by this stage. See AUTOMATION-PLAN.md and DEPLOY-CHECKLIST.md for pricing, Cloudflare DNS, TLS, persistence, isolation, teardown, video, and submission gates.

Public repo: https://github.com/summitsingh/launchcrew. Coordinator handles scan-verified micro-commits and push. Confirmed demo target in the deployment plan: launchcrew.summitsingh.com. The repository pattern scan exempts its own script path from personal-name detection and permits only those exact required public project URL and demo hostname references; copied names elsewhere remain blocked. No other personal name strings belong in repo files.

## V2 plan and sequence

Sequence, strict: v1 Launch Pack first, complete and lock the v1 demo, then build a v2 slice, then Nov 4 submission. V2 planning starts now, v2 build starts only after v1 is locked. If v2 slips, submit v1 at minimum, with v2 as additional demo only if ready and verified.

V2 slice priority, confirmed: Memory v1, Replay diff, Campaign Week FIRST, then Support Crew, Designer, Analyst, and Instagram connector plan, in that order.

Connector priority for photo sourcing in v2: Google Drive and Instagram first, instead of a local photo library, Dropbox second, Facebook Page photos last and deferred for now. Drive read-only first: list, metadata, download only shortlisted images selected explicitly by a human, never overwrite originals, record source file ID in receipts. No automated screener, ranking, scoring, or shortlisting. Instagram read-only first, via Instagram API with Unified Login, @summitleather.co only, professional account, instagram_basic for profile and media reads, draft queue, approval gate, receipt store, disconnect. Instagram publish code remains gated on business portfolio plus App Review and Live mode. Do not write publish, login, or OAuth publish code until that gate is confirmed. Tokens server-side only, supplied through the environment at runtime, never in code, repo, chat, logs, receipts, or client storage. No auto-post, auto-send, or auto-publish. This stage writes plan documents only, no connector code.

See V2-PLAN.md and CONNECTOR-PLAN.md. The final project is LaunchCrew, Indie track, Build for Your World, v1 plus v2 plan if ready. Submission execution remains gated until demo, repo, video, and deployment are ready, with a final submit check at that time. Do not submit in this stage.

## Strict new-work rule, Oct 27 evening

ALL work for this hackathon will be NEW for this hackathon. Do not reuse, copy, or port code from ai-instagram-organizer, ai-job-pilot, Koru Shield, or any other prior codebase into LaunchCrew submitted work, even if marked as pre-existing. All submitted code, connector layers, workflows, and demo features must be newly built Oct 26 to Nov 4, 2026, and clearly identified as such in README and submission. Demo data only (brand facts, demo idea, demo photos) may be used as input, but demo data is not code and must not be claimed as new code. Do not claim prior organiser dedupe or scoring logic as hackathon work in any form. No prior code will be reused, all connector layers will be newly built, demo data only as input.

The coordinator's read-only Oct 27 audit found no prior code copied into this repository. Evidence supplied by the coordinator: git log shows one root commit 37a358a on Oct 27, all repo files dated Oct 27, and grep for ai-job-pilot, jobpilot, instagram-organizer, Koru Shield code, TruckBux, daemon_call, bw-mcp, daemon.sock, and the LLM_ key pattern returned only context mentions in AUTOMATION-PLAN.md and DEPLOY-CHECKLIST.md about isolating from Koru Shield production, plus a ProofPilot application context mention, not code. scripts/verify_sam.py is status only, 407 bytes, with no network call, daemon socket, or mask parsing, and is not a copy of any prior SAM test script. This is a grep and git history check, not a full code similarity scan. These findings describe that coordinator snapshot; Stage C adds documentation references to this audit and rule.

## Current approvals and gates

- Public repo v1: done.
- Stage B push: pending coordinator verification.
- AWS provisioning: approved in principle when the web UI is ready, cost cap amount pending from Summit before actual provisioning.
- DNS for launchcrew.summitsingh.com: approved under the LaunchCrew-demo-only exception, Cloudflare only, no other DNS change to the parent domain of launchcrew.summitsingh.com.
- Live Spark test: approved but not yet run.
- Live SAM test: approved but not yet run.
- Final submission: gated until demo, repo, video, and deployment are ready, with a final submit check at that time. If deployment slips, record an explicit decision to submit v1 with a localhost demo video.
