"""Synthetic Checker evaluation runner, stdlib only.

Uses the production Checker through its current public Python entrypoint
without modifying the Checker. Computes binary catch rate, false block rate,
miss IDs, three-way category accuracy, confusion, per-class recall, and IDs
from Checker outputs. Reports model baseline as unmeasured.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

CHECKER_ENTRYPOINT = "launchcrew.facts.check_sentence"
EXPECTED_VERDICTS = ("Supported", "Not in confirmed facts", "Conflicts with confirmed facts")
SUPPORTED_LABEL = "Supported"

PRODUCTION_VERDICTS = ("supported", "unsupported", "conflicts")
PRODUCTION_SUPPORTED = "supported"
PRODUCTION_UNSUPPORTED = "unsupported"
PRODUCTION_CONFLICTS = "conflicts"

EXPECTED_TO_PRODUCTION = {
    "Supported": "supported",
    "Not in confirmed facts": "unsupported",
    "Conflicts with confirmed facts": "conflicts",
}

CATEGORY_NOTE = (
    "Category accuracy is measured as correct / total over all cases. "
    "Expected labels map to production enum: Supported to supported, "
    "Not in confirmed facts to unsupported, "
    "Conflicts with confirmed facts to conflicts. "
    "Observed verdict is the exact production enum from "
    "launchcrew.facts.check_sentence with strict verified pairing "
    "(verified True only with supported, verified False only with "
    "unsupported or conflicts). Malformed, unknown, or contradictory "
    "outputs fail closed to blocked and never count as correct. "
    "Confusion rows are expected production enum, columns observed."
)

BASELINE_NOTE = (
    "Baseline status is unmeasured. "
    "A one call model baseline requires a separately bounded real model run "
    "with its own approval, budget, and logging, not a synthetic value."
)


def load_dataset_bytes(path):
    return Path(path).read_bytes()


def hash_dataset_bytes(data):
    return hashlib.sha256(data).hexdigest()


def parse_dataset(data):
    return json.loads(data.decode("utf-8"))


def build_checker_facts(case):
    """Build Checker facts dict from one evaluation case."""
    return {
        "approved_claims": list(case.get("confirmed_facts", [])),
        "sources": ["synthetic evaluation v1"],
    }


def get_checker_entrypoint():
    """Import production Checker without changing it."""
    try:
        from launchcrew.facts import check_sentence
    except Exception as exc:
        raise RuntimeError(
            "Checker entrypoint unavailable: launchcrew.facts.check_sentence "
            "could not be imported. Dataset and methodology remain usable. "
            "A core change may have moved the entrypoint."
        ) from exc
    if not callable(check_sentence):
        raise RuntimeError(
            "Checker entrypoint unavailable: launchcrew.facts.check_sentence "
            "is not callable. Dataset and methodology remain usable."
        )
    return check_sentence


def map_expected_to_production(expected_label, case_id=None):
    """Map dataset expected label to exact production enum."""
    try:
        return EXPECTED_TO_PRODUCTION[expected_label]
    except KeyError:
        raise ValueError(
            "Unknown expected_verdict %r for case %r. Expected one of %s."
            % (expected_label, case_id, ", ".join(EXPECTED_VERDICTS))
        ) from None


def validate_checker_result(result):
    """Validate one production Checker result, fail closed per case.

    Returns (verified, verdict, malformed, reason). verified is bool,
    verdict is exact production enum. malformed is True when verdict enum
    is unknown, verified is not bool, or the pairing contradicts production
    (verified True only with supported). Malformed outputs fail closed to
    verified False and a blocked verdict, never to supported. Non-dict
    results raise RuntimeError.
    """
    if not isinstance(result, dict):
        raise RuntimeError(
            "Checker result shape unexpected: not a dict. "
            "Dataset and methodology remain usable."
        )
    verified_raw = result.get("verified")
    verdict_raw = result.get("verdict")
    reason = result.get("reason", "")
    if not isinstance(reason, str):
        reason = str(reason)
    verified_valid = type(verified_raw) is bool
    verdict_valid = isinstance(verdict_raw, str) and verdict_raw in PRODUCTION_VERDICTS
    consistent = False
    if verified_valid and verdict_valid:
        if verified_raw is True and verdict_raw == PRODUCTION_SUPPORTED:
            consistent = True
        elif verified_raw is False and verdict_raw in (
            PRODUCTION_UNSUPPORTED,
            PRODUCTION_CONFLICTS,
        ):
            consistent = True
    if verified_valid and verdict_valid and consistent:
        return (verified_raw, verdict_raw, False, reason)
    if verdict_valid and verdict_raw in (PRODUCTION_UNSUPPORTED, PRODUCTION_CONFLICTS):
        fail_verdict = verdict_raw
    else:
        fail_verdict = PRODUCTION_UNSUPPORTED
    return (False, fail_verdict, True, reason)


def observe_with_checker(case, checker_fn):
    """Run one candidate claim through the Checker. Returns three-way outcome."""
    facts = build_checker_facts(case)
    result = checker_fn(case["candidate_claim"], facts)
    verified, verdict, malformed, reason = validate_checker_result(result)
    return {
        "verified": verified,
        "blocked": not verified,
        "verdict": verdict,
        "reason": reason,
        "malformed": malformed,
    }


def compute_binary_metrics(cases, observed_by_id):
    """Compute binary catch rate, false block rate, and miss IDs.

    observed_by_id maps case id to True when the Checker allowed the claim
    (verified) and False when the Checker blocked it.
    """
    supported_ids = []
    error_ids = []
    for case in cases:
        if case.get("expected_verdict") == SUPPORTED_LABEL:
            supported_ids.append(case.get("id"))
        else:
            error_ids.append(case.get("id"))
    miss_ids = []
    caught_ids = []
    for case_id in error_ids:
        if observed_by_id.get(case_id):
            miss_ids.append(case_id)
        else:
            caught_ids.append(case_id)
    false_block_ids = []
    true_allow_ids = []
    for case_id in supported_ids:
        if observed_by_id.get(case_id):
            true_allow_ids.append(case_id)
        else:
            false_block_ids.append(case_id)
    if error_ids:
        binary_catch_rate = len(caught_ids) / len(error_ids)
    else:
        binary_catch_rate = None
    if supported_ids:
        false_block_rate = len(false_block_ids) / len(supported_ids)
    else:
        false_block_rate = None
    return {
        "total": len(cases),
        "supported_total": len(supported_ids),
        "error_total": len(error_ids),
        "caught_total": len(caught_ids),
        "miss_total": len(miss_ids),
        "false_block_total": len(false_block_ids),
        "true_allow_total": len(true_allow_ids),
        "binary_catch_rate": binary_catch_rate,
        "false_block_rate": false_block_rate,
        "miss_ids": sorted(miss_ids),
        "false_block_ids": sorted(false_block_ids),
        "caught_ids": sorted(caught_ids),
        "true_allow_ids": sorted(true_allow_ids),
    }


def compute_category_metrics(cases, observed_verdict_by_id, malformed_by_id=None):
    """Compute three-way category accuracy, confusion, IDs, and per-class recall.

    cases is a list of dataset cases with id and expected_verdict.
    observed_verdict_by_id maps case id to production enum (supported,
    unsupported, conflicts). Unknown or missing observed values fail closed
    to unsupported and mismatch, never to correct.
    malformed_by_id optionally maps case id to True when Checker output was
    malformed or contradictory; those cases never count as correct, even
    when the fail-closed verdict matches expected.
    Confusion is expected-row by observed-column over production enum.
    """
    if malformed_by_id is None:
        malformed_by_id = {}
    confusion = {exp: {obs: 0 for obs in PRODUCTION_VERDICTS} for exp in PRODUCTION_VERDICTS}
    correct_ids = []
    mismatch_ids = []
    malformed_ids = []
    expected_totals = {v: 0 for v in PRODUCTION_VERDICTS}
    expected_correct = {v: 0 for v in PRODUCTION_VERDICTS}
    for case in cases:
        case_id = case.get("id")
        expected_label = case.get("expected_verdict")
        expected_enum = map_expected_to_production(expected_label, case_id)
        expected_totals[expected_enum] += 1
        raw_observed = observed_verdict_by_id.get(case_id)
        flagged = bool(malformed_by_id.get(case_id))
        if raw_observed not in PRODUCTION_VERDICTS:
            flagged = True
            observed_enum = PRODUCTION_UNSUPPORTED
        else:
            observed_enum = raw_observed
        confusion[expected_enum][observed_enum] += 1
        if flagged:
            malformed_ids.append(case_id)
            mismatch_ids.append(case_id)
        elif observed_enum == expected_enum:
            correct_ids.append(case_id)
            expected_correct[expected_enum] += 1
        else:
            mismatch_ids.append(case_id)
    total = len(cases)
    correct_total = len(correct_ids)
    mismatch_total = len(mismatch_ids)
    if total:
        category_accuracy = correct_total / total
    else:
        category_accuracy = None
    per_class_recall = {}
    for verdict in PRODUCTION_VERDICTS:
        denom = expected_totals[verdict]
        if denom:
            per_class_recall[verdict] = expected_correct[verdict] / denom
        else:
            per_class_recall[verdict] = None
    return {
        "total": total,
        "correct_total": correct_total,
        "mismatch_total": mismatch_total,
        "malformed_total": len(malformed_ids),
        "correct_ids": sorted(correct_ids),
        "mismatch_ids": sorted(mismatch_ids),
        "malformed_ids": sorted(malformed_ids),
        "confusion": confusion,
        "category_accuracy": category_accuracy,
        "category_accuracy_denominator": total,
        "per_class_recall": per_class_recall,
        "expected_totals": dict(expected_totals),
    }


def get_source_sha(explicit=None):
    """Accept explicit SHA or record git HEAD without fabricating one."""
    if explicit:
        text = str(explicit).strip()
        if text:
            return {"sha": text, "method": "explicit argument"}
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        sha = (proc.stdout or "").strip()
        if proc.returncode == 0 and sha:
            return {"sha": sha, "method": "git rev-parse HEAD"}
    except Exception:
        pass
    return {"sha": "unknown", "method": "unavailable; not fabricated"}


def evaluate(dataset_path, source_sha=None, checker_fn=None):
    """Evaluate the versioned dataset with the production Checker."""
    dataset_path = Path(dataset_path)
    data = load_dataset_bytes(dataset_path)
    digest = hash_dataset_bytes(data)
    dataset = parse_dataset(data)
    cases = dataset.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset has no cases list")
    if checker_fn is None:
        checker_fn = get_checker_entrypoint()
    observed_by_id = {}
    observed_verdict_by_id = {}
    malformed_by_id = {}
    results = []
    for case in cases:
        outcome = observe_with_checker(case, checker_fn)
        case_id = case.get("id")
        observed_by_id[case_id] = outcome["verified"]
        observed_verdict_by_id[case_id] = outcome["verdict"]
        malformed_by_id[case_id] = outcome["malformed"]
        expected_enum = map_expected_to_production(case.get("expected_verdict"), case_id)
        category_correct = (not outcome["malformed"]) and (outcome["verdict"] == expected_enum)
        results.append(
            {
                "id": case_id,
                "category": case.get("category"),
                "expected_verdict": case.get("expected_verdict"),
                "expected_production_verdict": expected_enum,
                "observed_verified": outcome["verified"],
                "observed_blocked": outcome["blocked"],
                "observed_verdict": outcome["verdict"],
                "malformed": outcome["malformed"],
                "category_correct": category_correct,
                "checker_reason": outcome["reason"],
            }
        )
    metrics = compute_binary_metrics(cases, observed_by_id)
    cat = compute_category_metrics(cases, observed_verdict_by_id, malformed_by_id)
    return {
        "dataset_id": dataset.get("dataset_id"),
        "dataset_version": dataset.get("version"),
        "dataset_path": str(dataset_path),
        "dataset_sha256": digest,
        "source_commit": get_source_sha(source_sha),
        "checker_entrypoint": CHECKER_ENTRYPOINT,
        "counts": {
            "total": metrics["total"],
            "supported_total": metrics["supported_total"],
            "error_total": metrics["error_total"],
            "caught_total": metrics["caught_total"],
            "miss_total": metrics["miss_total"],
            "false_block_total": metrics["false_block_total"],
            "true_allow_total": metrics["true_allow_total"],
        },
        "binary_catch_rate": metrics["binary_catch_rate"],
        "false_block_rate": metrics["false_block_rate"],
        "miss_ids": metrics["miss_ids"],
        "false_block_ids": metrics["false_block_ids"],
        "category_accuracy": cat["category_accuracy"],
        "category_accuracy_denominator": cat["category_accuracy_denominator"],
        "category_accuracy_note": CATEGORY_NOTE,
        "confusion": cat["confusion"],
        "category_correct_total": cat["correct_total"],
        "category_mismatch_total": cat["mismatch_total"],
        "category_correct_ids": cat["correct_ids"],
        "category_mismatch_ids": cat["mismatch_ids"],
        "malformed_total": cat["malformed_total"],
        "malformed_ids": cat["malformed_ids"],
        "per_class_recall": cat["per_class_recall"],
        "category_expected_totals": cat["expected_totals"],
        "baseline": {"status": "unmeasured", "note": BASELINE_NOTE},
        "results": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run synthetic Checker evaluation with stdlib only."
    )
    parser.add_argument("--dataset", default="evaluation/dataset_v1.json")
    parser.add_argument("--out", default="")
    parser.add_argument("--source-sha", default="")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        report = evaluate(args.dataset, source_sha=args.source_sha or None)
    except RuntimeError as error:
        parser.exit(2, "Evaluation dependency: " + str(error) + "\n")
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
