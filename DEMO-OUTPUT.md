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
