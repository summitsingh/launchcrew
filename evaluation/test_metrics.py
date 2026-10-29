"""Metric arithmetic tests with synthetic fake Checker responses.

Synthetic fakes prove runner mechanics only. They are labeled as tests,
not measured performance.
"""

import json
import tempfile
import unittest
from pathlib import Path

try:
    from evaluation.runner import (
        build_checker_facts,
        compute_binary_metrics,
        evaluate,
        get_source_sha,
        hash_dataset_bytes,
    )
except ImportError:
    from runner import (
        build_checker_facts,
        compute_binary_metrics,
        evaluate,
        get_source_sha,
        hash_dataset_bytes,
    )


class HashTests(unittest.TestCase):
    def test_hash_known_abc_value(self):
        self.assertEqual(
            hash_dataset_bytes(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_hash_empty_value(self):
        self.assertEqual(
            hash_dataset_bytes(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )


class BinaryMetricTests(unittest.TestCase):
    def test_hand_computed_rates_and_ids(self):
        # Synthetic fake Checker outcomes for testing only, not measured performance.
        cases = [
            {"id": "E-001", "expected_verdict": "Conflicts with confirmed facts"},
            {"id": "E-002", "expected_verdict": "Not in confirmed facts"},
            {"id": "E-003", "expected_verdict": "Conflicts with confirmed facts"},
            {"id": "S-001", "expected_verdict": "Supported"},
            {"id": "S-002", "expected_verdict": "Supported"},
        ]
        observed = {"E-001": False, "E-002": False, "E-003": True, "S-001": True, "S-002": False}
        metrics = compute_binary_metrics(cases, observed)
        self.assertEqual(metrics["total"], 5)
        self.assertEqual(metrics["error_total"], 3)
        self.assertEqual(metrics["supported_total"], 2)
        self.assertEqual(metrics["caught_total"], 2)
        self.assertEqual(metrics["miss_total"], 1)
        self.assertEqual(metrics["false_block_total"], 1)
        self.assertEqual(metrics["true_allow_total"], 1)
        self.assertAlmostEqual(metrics["binary_catch_rate"], 2 / 3)
        self.assertAlmostEqual(metrics["false_block_rate"], 1 / 2)
        self.assertEqual(metrics["miss_ids"], ["E-003"])
        self.assertEqual(metrics["false_block_ids"], ["S-002"])
        self.assertEqual(metrics["caught_ids"], ["E-001", "E-002"])
        self.assertEqual(metrics["true_allow_ids"], ["S-001"])

    def test_no_errors_gives_none_catch_rate(self):
        cases = [{"id": "S-001", "expected_verdict": "Supported"}]
        metrics = compute_binary_metrics(cases, {"S-001": True})
        self.assertIsNone(metrics["binary_catch_rate"])
        self.assertEqual(metrics["false_block_rate"], 0.0)
        self.assertEqual(metrics["miss_ids"], [])

    def test_no_supported_gives_none_false_block_rate(self):
        cases = [{"id": "E-001", "expected_verdict": "Conflicts with confirmed facts"}]
        metrics = compute_binary_metrics(cases, {"E-001": False})
        self.assertEqual(metrics["binary_catch_rate"], 1.0)
        self.assertIsNone(metrics["false_block_rate"])
        self.assertEqual(metrics["false_block_ids"], [])

    def test_miss_ids_sorted(self):
        cases = [
            {"id": "E-003", "expected_verdict": "Conflicts with confirmed facts"},
            {"id": "E-001", "expected_verdict": "Conflicts with confirmed facts"},
        ]
        metrics = compute_binary_metrics(cases, {"E-003": True, "E-001": True})
        self.assertEqual(metrics["miss_ids"], ["E-001", "E-003"])


class SourceShaTests(unittest.TestCase):
    def test_explicit_sha_returned_verbatim(self):
        result = get_source_sha("abc123def")
        self.assertEqual(result["sha"], "abc123def")
        self.assertEqual(result["method"], "explicit argument")

    def test_blank_explicit_does_not_return_blank(self):
        result = get_source_sha("")
        self.assertTrue(result["sha"])
        self.assertNotEqual(result["sha"], "")


class EvaluateWithFakeCheckerTests(unittest.TestCase):
    def test_evaluate_uses_binary_outcomes_and_reports_unmeasured(self):
        # Synthetic fake Checker for testing only, not measured performance.
        def fake_checker(claim, facts):
            if "fictional teal" in claim:
                return {"verified": True, "reason": "fake allow"}
            return {"verified": False, "reason": "fake block"}

        dataset = {
            "version": "9.9.9-test",
            "dataset_id": "fake-for-test-only",
            "cases": [
                {
                    "id": "E-001",
                    "product": "Fictional test item, synthetic evaluation only",
                    "confirmed_facts": ["Item color is fictional teal"],
                    "candidate_claim": "Item color is fictional crimson",
                    "expected_verdict": "Conflicts with confirmed facts",
                    "category": "color",
                },
                {
                    "id": "S-001",
                    "product": "Fictional test item, synthetic evaluation only",
                    "confirmed_facts": ["Item color is fictional teal"],
                    "candidate_claim": "Item color is fictional teal",
                    "expected_verdict": "Supported",
                    "category": "supported_exact",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fake_dataset.json"
            path.write_text(json.dumps(dataset), encoding="utf-8")
            report = evaluate(str(path), source_sha="test-sha-001", checker_fn=fake_checker)
        self.assertEqual(report["dataset_version"], "9.9.9-test")
        self.assertEqual(report["binary_catch_rate"], 1.0)
        self.assertEqual(report["false_block_rate"], 0.0)
        self.assertEqual(report["miss_ids"], [])
        self.assertEqual(report["false_block_ids"], [])
        self.assertEqual(report["category_accuracy"], "unmeasured")
        self.assertEqual(report["baseline"]["status"], "unmeasured")
        self.assertIn("verified", str(report["results"]))
        # Observed stays binary; generic block is never labeled as Conflicts.
        for row in report["results"]:
            self.assertIn("observed_verified", row)
            self.assertIn("observed_blocked", row)
            self.assertNotIn("observed_verdict", row)

    def test_build_checker_facts_uses_confirmed_list(self):
        case = {"confirmed_facts": ["Alpha one", "Beta two"]}
        facts = build_checker_facts(case)
        self.assertEqual(facts["approved_claims"], ["Alpha one", "Beta two"])
        self.assertTrue(facts["sources"])


if __name__ == "__main__":
    unittest.main()
