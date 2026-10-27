# LaunchCrew

LaunchCrew is built for the Meta Global AI Developer Hackathon. This is hackathon-only work for Oct 26 to Nov 4, 2026, with an Idea to Launch Pack v1 milestone on Oct 28-29. Python 3 standard library only, no installation or external dependencies.

New in v1: agent creation and storage (create, load, edit, clone, test), a Spark strict-JSON pipeline with deterministic checks first, a receipt log, and approval plus export. The vegan leather wallet idea, `facts/demo_facts.json`, demo agents, and demo runs are demo data only. No real customer data or real PII belongs in this project.

V1 is approval plus export only. Nothing posts, sends, pays, or submits automatically. There is no Instagram or social connector in v1. Public repository preparation is in progress; the repository will contain only hackathon work and demo data. The project has not been submitted to the hackathon.

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

The pipeline checks facts deterministically before optional Scout synthesis, then runs Scout, Maker v1, Checker v1, Maker revision, Checker v2, and receipt storage. Every step appears in the event log. Scout attaches demo source labels to verified facts; unknown model facts are marked unverified and excluded from Maker. Model risks remain unverified hypotheses. Maker builds post and email drafts from approved claims. Checker checks the explicit claims list and scans draft sentences, including the exact phrase `best in Texas`. The `--seed-unverified-claim` flag is a demo test seed, not normal Maker behavior. It deliberately adds that phrase to v1, which Checker blocks with `Claim not found in facts file`. Revision rebuilds drafts from verified facts. A final blocked claim prevents receipt creation and export.

Claim matching follows the v1 rule: a normalized fact or a contained normalized approved claim verifies. This substring rule can miss unsupported additions to an otherwise approved sentence, so Maker emits only separate allowlist sentences and unknown Scout facts never feed Maker. Normalization lowercases, strips punctuation, and collapses whitespace. This v1 deterministic checker is not general natural language fact verification. Checker tone and visual instructions are stored in its profile; general tone auditing and visual inspection are not implemented. The seeded phrase is always blocked. Facts contain demo source labels, no external research or statistics.

## Optional model configuration

- `META_API_BASE_URL`: default `https://api.meta.ai/v1`.
- `META_API_KEY`: optional, supplied through the environment only. Never store it in this repository or print it.
- `META_MODEL`: default `muse-spark-1.3`. This is a placeholder to verify against current Meta Model API documentation. Neither this model identifier nor the endpoint compatibility was verified against live docs in this session.
- `META_WONDER_MODEL`: optional Scout synthesis model. When absent or unsuccessful, the caller uses Spark or deterministic fallback. Wonder is never required.

With no key, Spark explicitly returns `deterministic_fallback`, `model_used: none`, and a note explaining that no call occurred. With a key, the transport attempts an OpenAI-compatible chat completions POST requesting `json_object`, with a 30 second timeout. Parsed objects are still checked against facts. API or JSON errors return only their error type and fall back deterministically. Model access was tested using mocked transport only; live API access is not claimed. Deterministic Maker and Checker remain usable without any model. `spark_for_agent` composes agent instructions for optional synthesis. Spark attempt counts exclude optional Wonder requests; `wonder_used` records successful Wonder synthesis.

`model_usage.data_mode` states the intent `standard_no_train` for user data. It is not a verified API setting or training-policy guarantee. Input must remain demo data. No keys are looked up from local credential stores.

## Scope and remaining work

Built: agent creation and storage, deterministic checks with optional Muse Spark transport, Scout-only optional Wonder synthesis, and JSON receipts with simulated approval. See `DEMO-OUTPUT.md` for actual verification output and the full file inventory.

Open items for Oct 30-31: Scout, Maker, Checker sequence hardening, approval UI, live Meta endpoint and model verification, live API testing, broader tone auditing, and stronger natural language claim coverage. Current UI is CLI only. Current Maker and Checker are deterministic. Failed runs stop with an error type; persisted partial-failure receipts remain a hardening item.

SAM photo check is Nov 1 work, out of scope here. Receipts leave `visual_verification.checked` false and `method` `not_run`. SAM will plug in Nov 1 via direct api.meta.ai call, NOT via Muse CLI. No Muse Video is used.

Campaign Week, Support Crew, Finance Crew, other crews, marketplace, daily operations, CRM, HR, and all other workflows are not built. No screener, ranking, scoring, shortlisting, medical, education chatbot, nutrition, personality analysis, sports, or political features are built. Agent personality means work tone and rules only.
