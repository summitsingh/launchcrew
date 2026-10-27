# LaunchCrew actual verification output

Demo data only. Commands executed from `/home/summit/launchcrew`. For both demos, `META_API_KEY` and `META_WONDER_MODEL` were explicitly empty. `key_present: false`. No live API access is claimed.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Exit code: 0. Actual output:

```text
test_create_load_edit_clone_list (test_agents.AgentTests.test_create_load_edit_clone_list) ... ok
test_dry_run_has_no_side_effects (test_agents.AgentTests.test_dry_run_has_no_side_effects) ... ok
test_every_required_field (test_agents.AgentTests.test_every_required_field) ... ok
test_v1_restrictions (test_agents.AgentTests.test_v1_restrictions) ... ok
test_approved_claim_containment (test_claim_check.ClaimTests.test_approved_claim_containment) ... ok
test_counts (test_claim_check.ClaimTests.test_counts) ... ok
test_draft_safety_net_without_explicit_claim (test_claim_check.ClaimTests.test_draft_safety_net_without_explicit_claim) ... ok
test_material_verified (test_claim_check.ClaimTests.test_material_verified) ... ok
test_normalize (test_claim_check.ClaimTests.test_normalize) ... ok
test_unverified_blocked (test_claim_check.ClaimTests.test_unverified_blocked) ... ok
test_model_facts_filtered (test_receipt.ReceiptTests.test_model_facts_filtered) ... ok
test_no_key_never_calls_network (test_receipt.ReceiptTests.test_no_key_never_calls_network) ... ok
test_pending_receipt_schema (test_receipt.ReceiptTests.test_pending_receipt_schema) ... ok
test_seed_revision_and_approval (test_receipt.ReceiptTests.test_seed_revision_and_approval) ... ok
test_transport_json_and_error_redaction (test_receipt.ReceiptTests.test_transport_json_and_error_redaction) ... ok

----------------------------------------------------------------------
Ran 15 tests in 0.016s

OK
```

## Demo 1

```bash
python3 -m launchcrew.run --idea 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram' --facts facts/demo_facts.json --agents agents --out runs/demo_001.json
```

Exit code: 0. Actual stdout excerpts from the JSON receipt:

```text
  "approval_state": "pending_approval",
  "approvals": [],
  "brand": "LaunchCrew",
  "checker_v1": {
    "blocked_claims": [],
    "blocked_count": 0,
    "revision_instructions": [],
    "verified_count": 5
  },
  "checker_v2": {
    "blocked_claims": [],
    "blocked_count": 0,
    "revision_instructions": [],
    "verified_count": 5
  },
  "maker_draft_v1": {
    "claims": [
      "100% vegan PU leather",
      "Designed in Texas",
      "$49",
      "Vegan leather wallet",
      "For Austin commuters"
    ],
    "email": "100% vegan PU leather. Designed in Texas. $49. Vegan leather wallet. For Austin commuters.",
    "post": "100% vegan PU leather. Designed in Texas. $49. Vegan leather wallet. For Austin commuters."
  },
  "maker_draft_v2": {
    "claims": [
      "100% vegan PU leather",
      "Designed in Texas",
      "$49",
      "Vegan leather wallet",
      "For Austin commuters"
    ],
    "email": "100% vegan PU leather. Designed in Texas. $49. Vegan leather wallet. For Austin commuters.",
    "post": "100% vegan PU leather. Designed in Texas. $49. Vegan leather wallet. For Austin commuters."
  },
  "model_usage": {
    "data_mode": "standard_no_train",
    "data_mode_note": "Stated intent for user data, not a verified API setting.",
    "spark_calls": 0,
    "spark_mode": "deterministic_fallback",
    "wonder_used": false
  },
  "run_id": "demo_001",
  "scout": {
    "facts_used": [
      {
        "claim": "100% vegan PU leather",
        "evidence": "100% vegan PU leather",
        "sources": [
          "demo_facts.json",
          "demo brand brief"
        ],
        "verified": true
      },
      {
        "claim": "Designed in Texas",
        "evidence": "Designed in Texas",
        "sources": [
          "demo_facts.json",
          "demo brand brief"
        ],
        "verified": true
      },
      {
        "claim": "$49",
        "evidence": "$49",
        "sources": [
          "demo_facts.json",
          "demo brand brief"
        ],
        "verified": true
      },
      {
        "claim": "Vegan leather wallet",
        "evidence": "Vegan leather wallet",
        "sources": [
          "demo_facts.json",
          "demo brand brief"
        ],
        "verified": true
      },
      {
        "claim": "For Austin commuters",
        "evidence": "For Austin commuters",
        "sources": [
          "demo_facts.json",
          "demo brand brief"
        ],
        "verified": true
      }
    ],
    "model_mode": "deterministic_fallback",
    "model_note": "Spark was not called because no key was present.",
    "risks": [
      "Demo risk: unsupported product claims require revision.",
      "Demo risk: channel suitability is unverified by this facts file."
    ],
    "sources": [
      "demo_facts.json",
      "demo brand brief"
    ]
  },
  "summary": {
    "blocked_count": 0,
    "revised": false,
    "submit_attempted": false,
    "submit_completed": false,
    "total_claims_checked": 10,
    "verified_count": 10
  },
  "visual_verification": {
    "checked": false,
    "method": "not_run",
    "notes": "SAM photo check is Nov 1 work, not in Oct 28-29 milestone"
  }
```

## Demo 2

```bash
python3 -m launchcrew.run --idea 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram' --facts facts/demo_facts.json --agents agents --out runs/demo_002.json --approve --seed-unverified-claim
```

Exit code: 0. Actual stdout excerpts from the JSON receipt:

```text
  "approval_state": "approved_for_export",
  "approvals": [
    {
      "action": "approved_for_export",
      "approved_by": "demo_human",
      "timestamp": "2026-10-27T21:46:07.991671+00:00"
    }
  ],
  "brand": "LaunchCrew",
  "checker_v1": {
    "blocked_claims": [
      {
        "claim": "best in Texas",
        "reason": "Claim not found in facts file"
      }
    ],
    "blocked_count": 1,
    "revision_instructions": [
      "Remove best in Texas; replace with an approved facts file claim."
    ],
    "verified_count": 5
  },
  "checker_v2": {
    "blocked_claims": [],
    "blocked_count": 0,
    "revision_instructions": [],
    "verified_count": 5
  },
  "maker_draft_v1": {
    "claims": [
      "100% vegan PU leather",
      "Designed in Texas",
      "$49",
      "Vegan leather wallet",
      "For Austin commuters",
      "best in Texas"
    ],
    "email": "100% vegan PU leather. Designed in Texas. $49. Vegan leather wallet. For Austin commuters. best in Texas.",
    "post": "100% vegan PU leather. Designed in Texas. $49. Vegan leather wallet. For Austin commuters. best in Texas."
  },
  "maker_draft_v2": {
    "claims": [
      "100% vegan PU leather",
      "Designed in Texas",
      "$49",
      "Vegan leather wallet",
      "For Austin commuters"
    ],
    "email": "100% vegan PU leather. Designed in Texas. $49. Vegan leather wallet. For Austin commuters.",
    "post": "100% vegan PU leather. Designed in Texas. $49. Vegan leather wallet. For Austin commuters."
  },
  "model_usage": {
    "data_mode": "standard_no_train",
    "data_mode_note": "Stated intent for user data, not a verified API setting.",
    "spark_calls": 0,
    "spark_mode": "deterministic_fallback",
    "wonder_used": false
  },
  "run_id": "demo_002",
  "scout": {
    "facts_used": [
      {
        "claim": "100% vegan PU leather",
        "evidence": "100% vegan PU leather",
        "sources": [
          "demo_facts.json",
          "demo brand brief"
        ],
        "verified": true
      },
      {
        "claim": "Designed in Texas",
        "evidence": "Designed in Texas",
        "sources": [
          "demo_facts.json",
          "demo brand brief"
        ],
        "verified": true
      },
      {
        "claim": "$49",
        "evidence": "$49",
        "sources": [
          "demo_facts.json",
          "demo brand brief"
        ],
        "verified": true
      },
      {
        "claim": "Vegan leather wallet",
        "evidence": "Vegan leather wallet",
        "sources": [
          "demo_facts.json",
          "demo brand brief"
        ],
        "verified": true
      },
      {
        "claim": "For Austin commuters",
        "evidence": "For Austin commuters",
        "sources": [
          "demo_facts.json",
          "demo brand brief"
        ],
        "verified": true
      }
    ],
    "model_mode": "deterministic_fallback",
    "model_note": "Spark was not called because no key was present.",
    "risks": [
      "Demo risk: unsupported product claims require revision.",
      "Demo risk: channel suitability is unverified by this facts file."
    ],
    "sources": [
      "demo_facts.json",
      "demo brand brief"
    ]
  },
  "summary": {
    "blocked_count": 1,
    "revised": true,
    "submit_attempted": false,
    "submit_completed": false,
    "total_claims_checked": 11,
    "verified_count": 10
  },
  "visual_verification": {
    "checked": false,
    "method": "not_run",
    "notes": "SAM photo check is Nov 1 work, not in Oct 28-29 milestone"
  }
```

## Open items

Oct 30-31: Scout, Maker, Checker sequence hardening, approval UI, broader tone checks, substring claim-check hardening, persisted partial-failure receipts, live Meta API endpoint and placeholder model verification, and live API testing. SAM photo check is Nov 1 work. No test or demo failed. Spark live access and Wonder live synthesis were not exercised; deterministic fallback and mocked Spark transport were tested.

## Delivered file inventory

Paths relative to `/home/summit/launchcrew`, including completed pre-existing scaffold modules:

```text
.gitignore
DEMO-OUTPUT.md
README.md
agents/checker.json
agents/maker.json
agents/scout.json
facts/demo_facts.json
launchcrew/__init__.py
launchcrew/agents.py
launchcrew/facts.py
launchcrew/receipts.py
launchcrew/run.py
launchcrew/spark.py
launchcrew/wonder.py
runs/.gitkeep
runs/demo_001.json
runs/demo_002.json
tests/test_agents.py
tests/test_claim_check.py
tests/test_receipt.py
```

## Final scans

Executed `grep -rIl` with Unicode U+2014 across `.` and `grep -rIlE` with common API token, access key, private-key header, and literal META_API_KEY assignment patterns across `.`. Matching values are never printed. This is a pattern check, not a general secret-detection guarantee.

```text
Em dash scan, whole directory: exit_code=1, matched_files=0, no hits.
Common secret-pattern scan, whole directory (file names only): exit_code=1, matched_files=0, no hits.
```

## Public repo preparation, Oct 27

Stage A, Oct 27, 2026. Files changed:

```text
README.md
scripts/scan_repo.py
tests/test_scan.py
DEMO-OUTPUT.md
runs/demo_001.json
runs/demo_002.json
```

README now describes the hackathon dates, v1 features, demo-only data, and public repository preparation. Existing run instructions, model configuration, and live-verification caveats are retained. The new standard-library scanner checks punctuation, the legacy brand, contact patterns, secret patterns, and personal identifiers. Its only personal-name exception is the documented, exact allowlist comment in the scanner itself. Findings print paths and check types only, with line numbers for punctuation and legacy-brand findings. Counts represent matching lines per check. Read errors also fail the scan.

Verification commands:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/scan_repo.py /home/summit/launchcrew
```

Test result: 23 total, 23 passed, 0 failed. Exit code: 0.

Scan result: pass. Exit code: 0. Counts:

```text
em_dash: 0
legacy_brand: 0
email: 0
phone: 0
street_address: 0
secret: 0
personal_name: 0
read_error: 0
```

Independent recursive grep checks used `grep -r -o` for U+2014 and `grep -r -i -o` for the legacy brand, excluding `__pycache__` and `.git`. Both returned exit code 1, meaning no matches: em dash count 0, legacy brand count 0. Pattern strings were constructed at runtime so the verification documentation and tests remain clean under the same scan.

Both existing demo CLI commands from README were rerun with `META_API_KEY` and `META_WONDER_MODEL` explicitly empty. Both exited 0 and regenerated their local receipts:

```text
Run 1: pending_approval, submit_attempted=false
Run 2: approved_for_export, submit_attempted=false
Both: deterministic_fallback, spark_calls=0, visual method=not_run
```

No failures occurred. No git initialization, git push, remote creation, GitHub repository creation, AWS, DNS, or submission was done in this stage. V1 remains approval plus export only. Nothing posts, sends, pays, or submits automatically. No live Spark verification is claimed; transport testing remains mocked only, the model identifier remains a placeholder, and SAM photo checking remains Nov 1 work marked `not_run`.


## Oct 30-31 milestone

Stage B implementation completed locally on Oct 27 for the Oct 30-31 milestone. No push, remote change, AWS provisioning, DNS creation, portal submission, live Spark call, or live SAM call occurred. Stage A scanner and tests were present. Baseline: 23 total, 23 passed, 0 failed.

Files changed:

- `.dockerignore`
- `AUTOMATION-PLAN.md`
- `DEMO-OUTPUT.md`
- `DEPLOY-CHECKLIST.md`
- `Dockerfile`
- `README.md`
- `launchcrew/facts.py`
- `launchcrew/receipts.py`
- `launchcrew/run.py`
- `launchcrew/spark.py`
- `launchcrew/web.py`
- `runs/demo_001.json`
- `runs/demo_002.json`
- `runs/web_91f899fec3b1439ea33a6142289d19f9.json`
- `scripts/scan_repo.py`
- `scripts/verify_meta.py`
- `scripts/verify_sam.py`
- `tests/test_scan.py`
- `tests/test_stage_b.py`

Verification:

- `python3 -m unittest discover -s tests -v`: 36 total, 33 passed, 3 errors, 0 assertion failures. Counted as 3 failed checks. All three localhost ephemeral-port HTTP tests encounter PermissionError at socket creation in this execution environment. They remain real integration tests, without skips or mocked success. Failure files: tests/test_stage_b.py and launchcrew/web.py, PermissionError. Rerun these tests in a socket-enabled environment before calling this milestone fully verified.
- Three additional in-memory HTTP parser and response tests pass: clean approval and export, pending export refusal, blocked and failed approval refusal, repeat approval refusal, cross-origin refusal, and invalid-path refusal. They supplement real HTTP tests and do not establish localhost operation.
- `python3 scripts/scan_repo.py /home/summit/launchcrew`: pass, all finding categories 0. Scanner no longer has a literal personal name in its source. Only its own script path is exempt from personal-name checking, plus the required exact public project URL and confirmed deployment hostname are treated as project references. Copies of names elsewhere still fail.
- Recursive `grep -r` punctuation check and `grep -ri` legacy-brand check, excluding __pycache__ and .git: 0 matching files each, therefore 0 matching lines each.
- `git diff --check`: clean after whitespace correction.
- CLI wallet run `demo_001`: pending_approval, Checker v1 blocked 0, Checker v2 blocked 0, submit_attempted false, submit_completed false, deterministic_fallback.
- CLI wallet run `demo_002`: approved_for_export by demo_human, Checker v1 blocked 1 (seeded unsupported claim), Checker v2 blocked 0, submit_attempted false, submit_completed false, deterministic_fallback.
- Live localhost web UI demo: launchcrew/web.py, PermissionError, no run id created, approval and export through a real socket not verified.
- Supplementary in-memory HTTP demo only: run `web_91f899fec3b1439ea33a6142289d19f9`, approval_state `approved_for_export`, pending export HTTP response 403, approval response 200, export response 200 with JSON attachment, submit_attempted false. Receipt persisted under runs/ for review. These response codes were produced by the real HTTP parser and handler over in-memory streams, without an OS socket.

Live Spark: still NOT verified. `scripts/verify_meta.py` ran without a key, reported key missing, no network call made, model identifier placeholder muse-spark-1.3 not verified, endpoint default https://api.meta.ai/v1 not verified, and json_object as a live-test risk relative to secondary json_schema docs. Default execution refuses network even with a runtime key. Mocked live transport validates strict claims and token reporting only. Exact approved key route:

Summit provides a Meta Model API key through the environment at runtime only, never in a file, repo, chat, or log, for a single live test run, or Summit approves a separate key creation in the Meta developer console for LaunchCrew testing.

No credential store was consulted. Demo commands explicitly removed META_API_KEY and META_WONDER_MODEL from their child process environments. No key was read, printed, or stored.

SAM: not_run, Nov 1 work. `scripts/verify_sam.py` reports key missing and no network call. Only a direct api.meta.ai upload plus responses input_image plug point is documented, no photo check implemented.

V2: plan only, no connector code. V1 Launch Pack must be complete and locked before v2 build, then Nov 4 submission. If v2 slips, submit v1 at minimum, with v2 as additional demo only if ready and verified. Submission package is a preparation checklist; video link, team list, deployment decision, and final human tap remain open. Dockerfile and deployment checklist prepared only, no image build or deployment performed. The public demo UI requires a separate access decision before exposure; default startup binds 127.0.0.1.

Current approvals and gates, updated Oct 27:

- Public repo v1: done.
- Stage B push: pending coordinator verification.
- AWS provisioning: approved in principle when the web UI is ready, cost cap amount pending from Summit before actual provisioning.
- DNS for launchcrew.summitsingh.com: approved under the LaunchCrew-demo-only exception, Cloudflare only, no other DNS change to the parent domain of launchcrew.summitsingh.com.
- Live Spark test: approved but not yet run.
- Live SAM test: approved but not yet run.
- Final submission: gated until demo, repo, video, and deployment are ready, with a final submit check at that time. If deployment slips, record an explicit decision to submit v1 with a localhost demo video.

## New-work audit, Oct 27

All repo code was built Oct 26 to Nov 4, 2026, by Codex on summit-amd, within the hackathon work window. No code copied from ai-instagram-organizer, ai-job-pilot, Koru Shield, or any prior codebase. Demo data only as input, not claimed as code. This statement identifies the hackathon work window, not future work already completed.

The coordinator's read-only Oct 27 audit found no prior code copied into this repository. Evidence supplied by the coordinator: git log shows one root commit 37a358a on Oct 27, all repo files dated Oct 27, and grep for ai-job-pilot, jobpilot, instagram-organizer, Koru Shield code, TruckBux, daemon_call, bw-mcp, daemon.sock, and the LLM_ key pattern returned only context mentions in AUTOMATION-PLAN.md and DEPLOY-CHECKLIST.md about isolating from Koru Shield production, plus a ProofPilot application context mention, not code. scripts/verify_sam.py is status only, 407 bytes, with no network call, daemon socket, or mask parsing, and is not a copy of any prior SAM test script. This is a grep and git history check, not a full code similarity scan. These findings describe that coordinator snapshot; Stage C adds documentation references to this audit and rule.

## Independent web UI verification, Oct 27

Coordinator-supplied verified results, recorded here without rerunning the HTTP check in Stage C:

- Form loads.
- POST /run gave 303 to run web_df0bdbea57a4402ab2bc2a44314efd02.
- Export before approve gave 403.
- Run view showed pending_approval.
- Approve POST gave 200 with approved_by web_human.
- Export after approve gave 200.
- approval_state approved_for_export.
- summary total_claims_checked 10, verified_count 10, blocked_count 0.
- submit_attempted false, submit_completed false.

The earlier Codex Stage B test failures were sandbox socket blocks, not app failures, because the same tests pass outside the sandbox and this real HTTP verification succeeded. The Stage B failures remain visible above alongside this independent verification. This is supplied coordinator evidence, not a claim that Stage C reran tests outside the sandbox.

## Stage C verification, Oct 27

Documentation changes only: AUTOMATION-PLAN.md, README.md, V2-PLAN.md, CONNECTOR-PLAN.md, DEMO-OUTPUT.md, and DEPLOY-CHECKLIST.md. Existing Stage B code, tests, and receipts were preserved. Cost cap and budget period remain blank pending Summit.

- `python3 -m unittest discover -s tests -v`, with META_API_KEY and META_WONDER_MODEL removed from the child environment: 36 total, 33 passed, 3 failed checks (3 errors, 0 assertion failures). The three real-socket web tests remain blocked by sandbox socket permissions. In-memory HTTP tests passed. No live Spark or SAM call occurred.
- Failure files and error types only: tests/test_stage_b.py, PermissionError; launchcrew/web.py, PermissionError.
- `python3 scripts/scan_repo.py /home/summit/launchcrew`: final pass, all finding categories 0. An initial documentation scan flagged 7 personal-name matches in parent-domain wording; that wording was corrected without changing the scanner.
- Recursive punctuation and legacy-brand grep checks, excluding __pycache__ and .git: 0 matching lines each.
- Prior-code recursive grep for ai-job-pilot, instagram-organizer, and Koru Shield: only documentation context, strict-rule, audit-evidence, and deployment-isolation mentions; no code references found outside Markdown documents. This is a grep check, not a code similarity scan.
- `git diff --check`: clean.
- No git initialization, push, remote change, AWS provisioning, DNS creation, submission, live service calls, or connector code. No keys read, printed, logged, or stored.
