# Synthetic Checker evaluation

Versioned privacy safe dataset and stdlib runner for the claim Checker.

## Dataset

- File: `dataset_v1.json`, version `1.0.0`, id `launchcrew-checker-synthetic-v1`.
- 30 cases: 22 deliberate error cases and 8 supported controls.
- Error coverage: wrong material, missing included item, quantity, size, price mismatch, false absolute, product type swap, origin, warranty, plus color, capacity, and weight as distinct factual errors.
- Controls: 4 exact matches and 4 paraphrases with the same meaning in different words.
- Each case has stable ID, fictional product, exact confirmed fact strings, one candidate claim, expected verdict, and category label.
- Expected verdicts: `Supported`, `Not in confirmed facts`, `Conflicts with confirmed facts`.
- All products and facts are fictional and invented for testing. No real products, people, private data, credentials, or photos. No performance rates are stored in the dataset.

## Runner

- File: `runner.py`, stdlib only, no network, no model calls, no database.
- Uses production Checker through `launchcrew.facts.check_sentence` without modifying the Checker.
- For each case, confirmed facts become the allowlist and the candidate claim is checked once.
- Computes from actual Checker outputs: binary catch rate, false block rate, miss IDs, and false block IDs.
- Hashes exact dataset bytes with SHA256 and records source commit SHA from `--source-sha` or `git rev-parse HEAD`, or `unknown` when unavailable. No SHA is fabricated.
- Observed verdict is binary only: verified (allowed) or blocked. A generic block is never read as Conflicts.
- Category accuracy is reported as `unmeasured` because the current Checker exposes only verified or blocked.
- Model baseline is reported as `unmeasured` because a one call baseline requires a separately bounded real model run.

Usage:

```bash
python evaluation/runner.py --dataset evaluation/dataset_v1.json --out /tmp/checker_report.json --source-sha <sha>
```

If the Checker entrypoint is missing or its result shape changed, the runner exits with code 2 and names the dependency. The dataset and this note remain usable.

## Tests

- `test_dataset.py` validates structure, counts, category coverage, fictional markers, privacy patterns, and verdict labels.
- `test_metrics.py` checks metric arithmetic and hashing with synthetic fake Checker responses. Those fakes prove mechanics only and are labeled as tests, not measured performance.

## Limits

- Binary measurement only until the Checker offers a trustworthy three way observed verdict.
- No baseline comparison until a separately bounded real model run is approved and logged.
- Paraphrased supported controls may be blocked by exact match logic. That outcome is recorded as false block, not relabeled.
