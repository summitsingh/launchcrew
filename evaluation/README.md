# Synthetic Checker evaluation

Versioned privacy safe dataset and stdlib runner for the claim Checker.

## Dataset

- File: `dataset_v1.json`, version `1.0.0`, id `launchcrew-checker-synthetic-v1`.
- 30 cases: 22 deliberate error cases and 8 supported controls.
- Three-way mix: 8 Supported, 3 Not in confirmed facts, 19 Conflicts with confirmed facts.
- Error coverage: wrong material, missing included item, quantity, size, price mismatch, false absolute, product type swap, origin, warranty, plus color, capacity, and weight as distinct factual errors.
- Controls: 4 exact matches and 4 paraphrases with the same meaning in different words.
- Each case has stable ID, fictional product, exact confirmed fact strings, one candidate claim, expected verdict, and category label.
- Expected verdicts: `Supported`, `Not in confirmed facts`, `Conflicts with confirmed facts`.
- All products and facts are fictional and invented for testing. No real products, people, private data, credentials, or photos. No performance rates are stored in the dataset.

## Runner

- File: `runner.py`, stdlib only, no network, no model calls, no database.
- Uses production Checker through `launchcrew.facts.check_sentence` without modifying the Checker.
- For each case, confirmed facts become the allowlist and the candidate claim is checked once.
- Validates observed verdict enum (`supported`, `unsupported`, `conflicts`) and `verified` bool strictly. Malformed, unknown, or contradictory outputs fail closed to blocked and never count as category correct. Non-dict results exit with code 2.
- Maps expected labels to exact production enum: `Supported` to `supported`, `Not in confirmed facts` to `unsupported`, `Conflicts with confirmed facts` to `conflicts`.
- Computes from actual Checker outputs: binary catch rate, false block rate, miss IDs, and false block IDs, plus measured three-way category accuracy (`correct / total`), 3x3 confusion with expected rows and observed columns over production enum, category correct and mismatch counts and IDs, malformed counts and IDs, and per-class recall.
- Hashes exact dataset bytes with SHA256 and records source commit SHA from `--source-sha` or `git rev-parse HEAD`, or `unknown` when unavailable. No SHA is fabricated.
- Per-case results include observed verdict, expected production verdict, verified and blocked flags, malformed flag, category correct flag, and Checker reason.
- Model baseline is reported as `unmeasured` because a one call baseline requires a separately bounded real model run.

Usage:

```bash
python evaluation/runner.py --dataset evaluation/dataset_v1.json --out /tmp/checker_report.json --source-sha <sha>
```

If the Checker entrypoint is missing or a result is not a dict, the runner exits with code 2 and names the dependency. Field-level malformation fails closed per case to blocked and mismatch. The dataset and this note remain usable.

## Tests

- `test_dataset.py` validates structure, counts, category coverage, fictional markers, privacy patterns, and verdict labels.
- `test_metrics.py` checks metric arithmetic and hashing with synthetic fake Checker responses, plus hand-computed three-way and cross-class cases, malformed and unknown verdict and verified types, denominator edge cases, and a synthetic real-production-entrypoint smoke on fictional cases. Those fakes prove mechanics only and are labeled as tests, not measured performance. The smoke uses the deterministic production Checker only, with no model calls.

## Measured scope

- This evaluation measures sentence-level Checker verdicts on fictional single-claim cases only.
- It does not measure full run quality, multi-sentence drafts, policy or voice or style quality, human review, approval or export, backend or web behavior, or live model behavior.
- Category accuracy denominator is total cases (30 for v1). Malformed outputs count as blocked for binary catch but never as category correct; see malformed IDs.
- No baseline comparison until a separately bounded real model run is approved and logged.

## Limits

- Sentence-level fictional cases only. Not full run, policy, or voice quality.
- No baseline comparison until a separately bounded real model run is approved and logged.
- Paraphrased supported controls may be blocked by exact match logic. That outcome is recorded as false block and category mismatch, not relabeled.
