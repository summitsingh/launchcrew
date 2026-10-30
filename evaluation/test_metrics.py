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
        EXPECTED_TO_PRODUCTION,
        MALFORMED_OBSERVED,
        OBSERVED_VERDICTS,
        PRODUCTION_VERDICTS,
        build_checker_facts,
        compute_binary_metrics,
        compute_category_metrics,
        evaluate,
        get_checker_entrypoint,
        get_source_sha,
        hash_dataset_bytes,
        map_expected_to_production,
        validate_checker_result,
        validate_dataset_cases,
    )
except ImportError:
    from runner import (
        EXPECTED_TO_PRODUCTION,
        MALFORMED_OBSERVED,
        OBSERVED_VERDICTS,
        PRODUCTION_VERDICTS,
        build_checker_facts,
        compute_binary_metrics,
        compute_category_metrics,
        evaluate,
        get_checker_entrypoint,
        get_source_sha,
        hash_dataset_bytes,
        map_expected_to_production,
        validate_checker_result,
        validate_dataset_cases,
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


class MappingTests(unittest.TestCase):
    def test_expected_labels_map_to_exact_production_enum(self):
        self.assertEqual(map_expected_to_production("Supported", "X"), "supported")
        self.assertEqual(
            map_expected_to_production("Not in confirmed facts", "X"), "unsupported"
        )
        self.assertEqual(
            map_expected_to_production("Conflicts with confirmed facts", "X"), "conflicts"
        )
        self.assertEqual(
            EXPECTED_TO_PRODUCTION,
            {
                "Supported": "supported",
                "Not in confirmed facts": "unsupported",
                "Conflicts with confirmed facts": "conflicts",
            },
        )
        self.assertEqual(tuple(PRODUCTION_VERDICTS), ("supported", "unsupported", "conflicts"))

    def test_unknown_expected_label_raises(self):
        with self.assertRaises(ValueError):
            map_expected_to_production("Supported?", "E-999")


class ValidationTests(unittest.TestCase):
    def test_valid_supported_pairing(self):
        verified, verdict, malformed, reason = validate_checker_result(
            {"verified": True, "verdict": "supported", "reason": "ok"}
        )
        self.assertIs(verified, True)
        self.assertEqual(verdict, "supported")
        self.assertIs(malformed, False)
        self.assertEqual(reason, "ok")

    def test_valid_blocked_pairings(self):
        for verdict in ("unsupported", "conflicts"):
            verified, observed, malformed, _ = validate_checker_result(
                {"verified": False, "verdict": verdict, "reason": "blocked"}
            )
            self.assertIs(verified, False)
            self.assertEqual(observed, verdict)
            self.assertIs(malformed, False)

    def test_unknown_verdict_fails_closed(self):
        verified, verdict, malformed, _ = validate_checker_result(
            {"verified": False, "verdict": "unknown", "reason": "fake"}
        )
        self.assertIs(verified, False)
        self.assertEqual(verdict, "malformed")
        self.assertIs(malformed, True)

    def test_capitalized_verdict_fails_closed(self):
        # Exact production enum is lowercase; capitalized is malformed.
        verified, verdict, malformed, _ = validate_checker_result(
            {"verified": True, "verdict": "Supported", "reason": "fake"}
        )
        self.assertIs(verified, False)
        self.assertEqual(verdict, "malformed")
        self.assertIs(malformed, True)

    def test_verified_int_fails_closed(self):
        verified, verdict, malformed, _ = validate_checker_result(
            {"verified": 1, "verdict": "supported", "reason": "fake"}
        )
        self.assertIs(verified, False)
        self.assertEqual(verdict, "malformed")
        self.assertIs(malformed, True)

    def test_verified_string_fails_closed(self):
        verified, verdict, malformed, _ = validate_checker_result(
            {"verified": "true", "verdict": "unsupported", "reason": "fake"}
        )
        self.assertIs(verified, False)
        self.assertEqual(verdict, "malformed")
        self.assertIs(malformed, True)

    def test_missing_keys_fail_closed(self):
        for result in ({}, {"verified": True}, {"verdict": "supported"}):
            verified, verdict, malformed, _ = validate_checker_result(result)
            self.assertIs(verified, False)
            self.assertEqual(verdict, "malformed")
            self.assertIs(malformed, True)

    def test_contradictory_true_with_blocked_verdict_fails_closed(self):
        verified, verdict, malformed, _ = validate_checker_result(
            {"verified": True, "verdict": "unsupported", "reason": "fake"}
        )
        self.assertIs(verified, False)
        self.assertEqual(verdict, "malformed")
        self.assertIs(malformed, True)
        verified, verdict, malformed, _ = validate_checker_result(
            {"verified": True, "verdict": "conflicts", "reason": "fake"}
        )
        self.assertIs(verified, False)
        self.assertEqual(verdict, "malformed")
        self.assertIs(malformed, True)

    def test_contradictory_false_with_supported_fails_closed(self):
        verified, verdict, malformed, _ = validate_checker_result(
            {"verified": False, "verdict": "supported", "reason": "fake"}
        )
        self.assertIs(verified, False)
        self.assertEqual(verdict, "malformed")
        self.assertIs(malformed, True)

    def test_non_dict_raises(self):
        for bad in (None, [], "supported", True):
            with self.assertRaises(RuntimeError):
                validate_checker_result(bad)


class CategoryMetricTests(unittest.TestCase):
    def test_all_three_classes_correct(self):
        # Hand computed: 3 cases, one per class, all correct.
        cases = [
            {"id": "S-001", "expected_verdict": "Supported"},
            {"id": "U-001", "expected_verdict": "Not in confirmed facts"},
            {"id": "C-001", "expected_verdict": "Conflicts with confirmed facts"},
        ]
        observed = {"S-001": "supported", "U-001": "unsupported", "C-001": "conflicts"}
        cat = compute_category_metrics(cases, observed, {})
        self.assertEqual(cat["total"], 3)
        self.assertEqual(cat["correct_total"], 3)
        self.assertEqual(cat["mismatch_total"], 0)
        self.assertEqual(cat["malformed_total"], 0)
        self.assertEqual(cat["correct_ids"], ["C-001", "S-001", "U-001"])
        self.assertEqual(cat["mismatch_ids"], [])
        self.assertEqual(cat["malformed_ids"], [])
        self.assertAlmostEqual(cat["category_accuracy"], 1.0)
        self.assertEqual(cat["category_accuracy_denominator"], 3)
        self.assertEqual(
            cat["confusion"],
            {
                "supported": {
                    "supported": 1,
                    "unsupported": 0,
                    "conflicts": 0,
                    "malformed": 0,
                },
                "unsupported": {
                    "supported": 0,
                    "unsupported": 1,
                    "conflicts": 0,
                    "malformed": 0,
                },
                "conflicts": {
                    "supported": 0,
                    "unsupported": 0,
                    "conflicts": 1,
                    "malformed": 0,
                },
            },
        )
        self.assertEqual(
            cat["per_class_recall"], {"supported": 1.0, "unsupported": 1.0, "conflicts": 1.0}
        )
        self.assertEqual(
            cat["expected_totals"], {"supported": 1, "unsupported": 1, "conflicts": 1}
        )

    def test_cross_class_confusion_hand_computed(self):
        # Hand computed: 6 cases, 3 correct, 3 cross-class mismatches.
        # S-002 is a false block with wrong category (supported seen as unsupported).
        # U-002 is blocked but wrong category (unsupported seen as conflicts).
        # C-002 is a miss with wrong category (conflicts seen as supported).
        cases = [
            {"id": "S-001", "expected_verdict": "Supported"},
            {"id": "S-002", "expected_verdict": "Supported"},
            {"id": "U-001", "expected_verdict": "Not in confirmed facts"},
            {"id": "U-002", "expected_verdict": "Not in confirmed facts"},
            {"id": "C-001", "expected_verdict": "Conflicts with confirmed facts"},
            {"id": "C-002", "expected_verdict": "Conflicts with confirmed facts"},
        ]
        observed = {
            "S-001": "supported",
            "S-002": "unsupported",
            "U-001": "unsupported",
            "U-002": "conflicts",
            "C-001": "conflicts",
            "C-002": "supported",
        }
        cat = compute_category_metrics(cases, observed, {})
        self.assertEqual(cat["total"], 6)
        self.assertEqual(cat["correct_total"], 3)
        self.assertEqual(cat["mismatch_total"], 3)
        self.assertEqual(cat["malformed_total"], 0)
        self.assertEqual(cat["correct_ids"], ["C-001", "S-001", "U-001"])
        self.assertEqual(cat["mismatch_ids"], ["C-002", "S-002", "U-002"])
        self.assertAlmostEqual(cat["category_accuracy"], 3 / 6)
        self.assertEqual(cat["category_accuracy_denominator"], 6)
        self.assertEqual(
            cat["confusion"],
            {
                "supported": {
                    "supported": 1,
                    "unsupported": 1,
                    "conflicts": 0,
                    "malformed": 0,
                },
                "unsupported": {
                    "supported": 0,
                    "unsupported": 1,
                    "conflicts": 1,
                    "malformed": 0,
                },
                "conflicts": {
                    "supported": 1,
                    "unsupported": 0,
                    "conflicts": 1,
                    "malformed": 0,
                },
            },
        )
        self.assertAlmostEqual(cat["per_class_recall"]["supported"], 1 / 2)
        self.assertAlmostEqual(cat["per_class_recall"]["unsupported"], 1 / 2)
        self.assertAlmostEqual(cat["per_class_recall"]["conflicts"], 1 / 2)

    def test_malformed_never_counts_as_correct(self):
        # Hand computed: both observed enums match expected, but both flagged
        # malformed, so correct stays 0 and both are mismatches in the
        # separate malformed column, never on the valid diagonal.
        cases = [
            {"id": "S-001", "expected_verdict": "Supported"},
            {"id": "U-001", "expected_verdict": "Not in confirmed facts"},
        ]
        observed = {"S-001": "supported", "U-001": "unsupported"}
        malformed = {"S-001": True, "U-001": True}
        cat = compute_category_metrics(cases, observed, malformed)
        self.assertEqual(cat["correct_total"], 0)
        self.assertEqual(cat["mismatch_total"], 2)
        self.assertEqual(cat["malformed_total"], 2)
        self.assertEqual(cat["correct_ids"], [])
        self.assertEqual(cat["mismatch_ids"], ["S-001", "U-001"])
        self.assertEqual(cat["malformed_ids"], ["S-001", "U-001"])
        self.assertAlmostEqual(cat["category_accuracy"], 0.0)
        self.assertEqual(cat["category_accuracy_denominator"], 2)
        self.assertAlmostEqual(cat["per_class_recall"]["supported"], 0.0)
        self.assertAlmostEqual(cat["per_class_recall"]["unsupported"], 0.0)
        self.assertIsNone(cat["per_class_recall"]["conflicts"])
        self.assertEqual(cat["confusion"]["supported"]["malformed"], 1)
        self.assertEqual(cat["confusion"]["unsupported"]["malformed"], 1)
        self.assertEqual(cat["confusion"]["supported"]["supported"], 0)
        self.assertEqual(cat["confusion"]["unsupported"]["unsupported"], 0)

    def test_unknown_observed_fails_closed_to_mismatch(self):
        cases = [{"id": "S-001", "expected_verdict": "Supported"}]
        cat = compute_category_metrics(cases, {"S-001": "Supported"}, {})
        self.assertEqual(cat["correct_total"], 0)
        self.assertEqual(cat["mismatch_total"], 1)
        self.assertEqual(cat["malformed_total"], 1)
        self.assertEqual(cat["malformed_ids"], ["S-001"])
        self.assertEqual(cat["confusion"]["supported"]["malformed"], 1)
        self.assertEqual(cat["confusion"]["supported"]["unsupported"], 0)
        self.assertAlmostEqual(cat["category_accuracy"], 0.0)

    def test_missing_observed_fails_closed_to_mismatch(self):
        cases = [{"id": "C-001", "expected_verdict": "Conflicts with confirmed facts"}]
        cat = compute_category_metrics(cases, {}, {})
        self.assertEqual(cat["correct_total"], 0)
        self.assertEqual(cat["mismatch_total"], 1)
        self.assertEqual(cat["malformed_total"], 1)
        self.assertEqual(cat["confusion"]["conflicts"]["malformed"], 1)
        self.assertEqual(cat["confusion"]["conflicts"]["unsupported"], 0)

    def test_empty_denominator_gives_none_accuracy(self):
        cat = compute_category_metrics([], {}, {})
        self.assertEqual(cat["total"], 0)
        self.assertIsNone(cat["category_accuracy"])
        self.assertEqual(cat["category_accuracy_denominator"], 0)
        self.assertEqual(cat["correct_total"], 0)
        self.assertEqual(cat["mismatch_total"], 0)
        self.assertEqual(
            cat["confusion"],
            {
                "supported": {
                    "supported": 0,
                    "unsupported": 0,
                    "conflicts": 0,
                    "malformed": 0,
                },
                "unsupported": {
                    "supported": 0,
                    "unsupported": 0,
                    "conflicts": 0,
                    "malformed": 0,
                },
                "conflicts": {
                    "supported": 0,
                    "unsupported": 0,
                    "conflicts": 0,
                    "malformed": 0,
                },
            },
        )
        self.assertIsNone(cat["per_class_recall"]["supported"])
        self.assertIsNone(cat["per_class_recall"]["unsupported"])
        self.assertIsNone(cat["per_class_recall"]["conflicts"])

    def test_single_class_leaves_other_recalls_none(self):
        cases = [
            {"id": "S-001", "expected_verdict": "Supported"},
            {"id": "S-002", "expected_verdict": "Supported"},
        ]
        observed = {"S-001": "supported", "S-002": "unsupported"}
        cat = compute_category_metrics(cases, observed, {})
        self.assertAlmostEqual(cat["category_accuracy"], 1 / 2)
        self.assertAlmostEqual(cat["per_class_recall"]["supported"], 1 / 2)
        self.assertIsNone(cat["per_class_recall"]["unsupported"])
        self.assertIsNone(cat["per_class_recall"]["conflicts"])
        self.assertEqual(
            cat["expected_totals"], {"supported": 2, "unsupported": 0, "conflicts": 0}
        )

    def test_unknown_expected_label_raises(self):
        cases = [{"id": "X-001", "expected_verdict": "Almost supported"}]
        with self.assertRaises(ValueError):
            compute_category_metrics(cases, {"X-001": "supported"}, {})

    def test_expected_unsupported_malformed_stays_off_diagonal(self):
        # Regression: expected unsupported with malformed output must not
        # increment the valid diagonal even when the raw enum matches.
        cases = [
            {"id": "U-001", "expected_verdict": "Not in confirmed facts"},
            {"id": "U-002", "expected_verdict": "Not in confirmed facts"},
        ]
        observed = {"U-001": "unsupported", "U-002": "bogus-enum"}
        malformed = {"U-001": True}
        cat = compute_category_metrics(cases, observed, malformed)
        self.assertEqual(cat["correct_total"], 0)
        self.assertEqual(cat["mismatch_total"], 2)
        self.assertEqual(cat["malformed_total"], 2)
        self.assertEqual(cat["malformed_ids"], ["U-001", "U-002"])
        self.assertAlmostEqual(cat["category_accuracy"], 0.0)
        self.assertEqual(cat["confusion"]["unsupported"]["unsupported"], 0)
        self.assertEqual(cat["confusion"]["unsupported"]["malformed"], 2)
        diagonal = sum(
            cat["confusion"][v][v] for v in ("supported", "unsupported", "conflicts")
        )
        self.assertEqual(diagonal, cat["correct_total"])
        self.assertEqual(diagonal, 0)

    def test_confusion_arithmetic_invariants_with_malformed(self):
        # Hand computed mixed valid and malformed: diagonal equals correct,
        # malformed column equals malformed_total, matrix sum equals total.
        cases = [
            {"id": "S-001", "expected_verdict": "Supported"},
            {"id": "S-002", "expected_verdict": "Supported"},
            {"id": "U-001", "expected_verdict": "Not in confirmed facts"},
            {"id": "C-001", "expected_verdict": "Conflicts with confirmed facts"},
        ]
        observed = {
            "S-001": "supported",
            "S-002": "unsupported",
            "U-001": "unsupported",
            "C-001": "conflicts",
        }
        malformed = {"U-001": True}
        cat = compute_category_metrics(cases, observed, malformed)
        self.assertEqual(cat["total"], 4)
        self.assertEqual(cat["correct_total"], 2)
        self.assertEqual(cat["mismatch_total"], 2)
        self.assertEqual(cat["malformed_total"], 1)
        self.assertEqual(cat["malformed_ids"], ["U-001"])
        self.assertAlmostEqual(cat["category_accuracy"], 2 / 4)
        self.assertEqual(
            cat["confusion"],
            {
                "supported": {
                    "supported": 1,
                    "unsupported": 1,
                    "conflicts": 0,
                    "malformed": 0,
                },
                "unsupported": {
                    "supported": 0,
                    "unsupported": 0,
                    "conflicts": 0,
                    "malformed": 1,
                },
                "conflicts": {
                    "supported": 0,
                    "unsupported": 0,
                    "conflicts": 1,
                    "malformed": 0,
                },
            },
        )
        self.assertEqual(tuple(OBSERVED_VERDICTS), ("supported", "unsupported", "conflicts", "malformed"))
        self.assertEqual(MALFORMED_OBSERVED, "malformed")
        total_cells = sum(
            cat["confusion"][exp][obs]
            for exp in ("supported", "unsupported", "conflicts")
            for obs in ("supported", "unsupported", "conflicts", "malformed")
        )
        self.assertEqual(total_cells, cat["total"])
        diagonal = sum(
            cat["confusion"][v][v] for v in ("supported", "unsupported", "conflicts")
        )
        self.assertEqual(diagonal, cat["correct_total"])
        malformed_column = sum(
            cat["confusion"][exp]["malformed"]
            for exp in ("supported", "unsupported", "conflicts")
        )
        self.assertEqual(malformed_column, cat["malformed_total"])


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
    def test_evaluate_reports_measured_three_way(self):
        # Synthetic fake Checker for testing only, not measured performance.
        def fake_checker(claim, facts):
            if "fictional teal" in claim:
                return {"verified": True, "verdict": "supported", "reason": "fake allow"}
            if "fictional crimson" in claim:
                return {"verified": False, "verdict": "conflicts", "reason": "fake conflict"}
            return {"verified": False, "verdict": "unsupported", "reason": "fake block"}

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
                    "id": "E-002",
                    "product": "Fictional test item, synthetic evaluation only",
                    "confirmed_facts": ["Item color is fictional teal"],
                    "candidate_claim": "Item includes fictional brush",
                    "expected_verdict": "Not in confirmed facts",
                    "category": "missing_included_item",
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
        # Binary rates preserved: 2 errors blocked, 1 supported allowed.
        self.assertEqual(report["binary_catch_rate"], 1.0)
        self.assertEqual(report["false_block_rate"], 0.0)
        self.assertEqual(report["miss_ids"], [])
        self.assertEqual(report["false_block_ids"], [])
        # Three-way is measured, not unmeasured.
        self.assertAlmostEqual(report["category_accuracy"], 1.0)
        self.assertEqual(report["category_accuracy_denominator"], 3)
        self.assertEqual(report["category_correct_total"], 3)
        self.assertEqual(report["category_mismatch_total"], 0)
        self.assertEqual(report["category_correct_ids"], ["E-001", "E-002", "S-001"])
        self.assertEqual(report["category_mismatch_ids"], [])
        self.assertEqual(report["malformed_total"], 0)
        self.assertEqual(report["malformed_ids"], [])
        self.assertEqual(
            report["confusion"],
            {
                "supported": {
                    "supported": 1,
                    "unsupported": 0,
                    "conflicts": 0,
                    "malformed": 0,
                },
                "unsupported": {
                    "supported": 0,
                    "unsupported": 1,
                    "conflicts": 0,
                    "malformed": 0,
                },
                "conflicts": {
                    "supported": 0,
                    "unsupported": 0,
                    "conflicts": 1,
                    "malformed": 0,
                },
            },
        )
        self.assertEqual(
            report["per_class_recall"],
            {"supported": 1.0, "unsupported": 1.0, "conflicts": 1.0},
        )
        self.assertEqual(report["baseline"]["status"], "unmeasured")
        for row in report["results"]:
            self.assertIn("observed_verified", row)
            self.assertIn("observed_blocked", row)
            self.assertIn("observed_verdict", row)
            self.assertIn(
                row["observed_verdict"],
                ("supported", "unsupported", "conflicts", "malformed"),
            )
            self.assertIn("expected_production_verdict", row)
            self.assertIn("malformed", row)
            self.assertIn("category_correct", row)
            self.assertIs(row["malformed"], False)
            self.assertIs(row["category_correct"], True)

    def test_evaluate_malformed_fails_closed_per_case(self):
        # Synthetic fake Checker for testing only, not measured performance.
        # E-001 returns an unknown verdict, S-001 returns a non-bool verified.
        # Both fail closed to blocked and mismatch, never to correct.
        def fake_checker(claim, facts):
            if "crimson" in claim:
                return {"verified": False, "verdict": "unknown", "reason": "fake bad enum"}
            return {"verified": 1, "verdict": "supported", "reason": "fake bad bool"}

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
            report = evaluate(str(path), source_sha="test-sha-002", checker_fn=fake_checker)
        # Fail closed to blocked: error case counts as caught, supported as false block.
        self.assertEqual(report["binary_catch_rate"], 1.0)
        self.assertEqual(report["false_block_rate"], 1.0)
        self.assertEqual(report["miss_ids"], [])
        self.assertEqual(report["false_block_ids"], ["S-001"])
        # Category never counts malformed as correct and never uses a
        # fallback production enum as the observed verdict.
        self.assertAlmostEqual(report["category_accuracy"], 0.0)
        self.assertEqual(report["category_accuracy_denominator"], 2)
        self.assertEqual(report["category_correct_total"], 0)
        self.assertEqual(report["category_mismatch_total"], 2)
        self.assertEqual(report["category_mismatch_ids"], ["E-001", "S-001"])
        self.assertEqual(report["malformed_total"], 2)
        self.assertEqual(report["malformed_ids"], ["E-001", "S-001"])
        self.assertEqual(report["confusion"]["conflicts"]["malformed"], 1)
        self.assertEqual(report["confusion"]["supported"]["malformed"], 1)
        self.assertEqual(report["confusion"]["conflicts"]["conflicts"], 0)
        self.assertEqual(report["confusion"]["supported"]["supported"], 0)
        for row in report["results"]:
            self.assertIs(row["observed_verified"], False)
            self.assertIs(row["observed_blocked"], True)
            self.assertEqual(row["observed_verdict"], "malformed")
            self.assertIs(row["malformed"], True)
            self.assertIs(row["category_correct"], False)

    def test_build_checker_facts_uses_confirmed_list(self):
        case = {"confirmed_facts": ["Alpha one", "Beta two"]}
        facts = build_checker_facts(case)
        self.assertEqual(facts["approved_claims"], ["Alpha one", "Beta two"])
        self.assertTrue(facts["sources"])


class EvaluateDatasetValidationTests(unittest.TestCase):
    def _evaluate_with_counting_checker(self, cases):
        calls = []

        def fake_checker(claim, facts):
            calls.append((claim, facts))
            return {"verified": True, "verdict": "supported", "reason": "fake"}

        dataset = {
            "version": "9.9.9-test",
            "dataset_id": "fake-validation-only",
            "cases": cases,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid_dataset.json"
            path.write_text(json.dumps(dataset), encoding="utf-8")
            with self.assertRaises(ValueError):
                evaluate(str(path), source_sha="test-sha-invalid", checker_fn=fake_checker)
        return calls

    def _valid_case(self, case_id, expected="Supported"):
        return {
            "id": case_id,
            "product": "Fictional test item, synthetic evaluation only",
            "confirmed_facts": ["Item color is fictional teal"],
            "candidate_claim": "Item color is fictional teal",
            "expected_verdict": expected,
            "category": "supported_exact",
        }

    def test_duplicate_ids_rejected_without_checker_calls(self):
        cases = [self._valid_case("DUP-001"), self._valid_case("DUP-001")]
        calls = self._evaluate_with_counting_checker(cases)
        self.assertEqual(calls, [])

    def test_missing_and_empty_ids_rejected_without_checker_calls(self):
        base = self._valid_case("OK-001")
        invalid_ids = [
            ("missing", {k: v for k, v in base.items() if k != "id"}),
            ("empty", dict(base, id="")),
            ("whitespace", dict(base, id="   ")),
            ("none", dict(base, id=None)),
            ("int", dict(base, id=123)),
        ]
        for label, bad_case in invalid_ids:
            with self.subTest(label=label):
                calls = self._evaluate_with_counting_checker([bad_case])
                self.assertEqual(calls, [])

    def test_unknown_expected_label_rejected_without_checker_calls(self):
        cases = [self._valid_case("X-001", expected="Almost supported")]
        calls = self._evaluate_with_counting_checker(cases)
        self.assertEqual(calls, [])

    def test_validate_dataset_cases_accepts_unique_nonempty_ids(self):
        validate_dataset_cases([self._valid_case("A-001"), self._valid_case("A-002")])


class ProductionEntrypointSmokeTests(unittest.TestCase):
    def test_real_checker_entrypoint_is_callable(self):
        checker_fn = get_checker_entrypoint()
        self.assertTrue(callable(checker_fn))
        result = checker_fn(
            "Fictional widget color is teal",
            {
                "approved_claims": ["Fictional widget color is teal"],
                "sources": ["synthetic test only"],
            },
        )
        self.assertIs(result["verified"], True)
        self.assertEqual(result["verdict"], "supported")

    def test_evaluate_with_real_checker_on_synthetic_fictional_cases(self):
        # Synthetic fictional cases for smoke only, not measured performance.
        # Uses the real deterministic production Checker, no model calls.
        try:
            from launchcrew.facts import check_sentence as real_checker
        except Exception as exc:
            self.skipTest("production Checker unavailable: " + str(exc))
        dataset = {
            "version": "9.9.9-test",
            "dataset_id": "fake-smoke-only",
            "cases": [
                {
                    "id": "T-001",
                    "product": "Fictional smoke widget, synthetic evaluation only",
                    "confirmed_facts": ["Fictional widget color is teal"],
                    "candidate_claim": "Fictional widget color is teal",
                    "expected_verdict": "Supported",
                    "category": "supported_exact",
                },
                {
                    "id": "T-002",
                    "product": "Fictional smoke widget, synthetic evaluation only",
                    "confirmed_facts": ["Price is $29"],
                    "candidate_claim": "Price is $19",
                    "expected_verdict": "Conflicts with confirmed facts",
                    "category": "price_mismatch",
                },
                {
                    "id": "T-003",
                    "product": "Fictional smoke bottle, synthetic evaluation only",
                    "confirmed_facts": ["Box includes bottle and cap"],
                    "candidate_claim": "Box includes bottle, cap, and brush",
                    "expected_verdict": "Not in confirmed facts",
                    "category": "missing_included_item",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smoke_dataset.json"
            path.write_text(json.dumps(dataset), encoding="utf-8")
            report = evaluate(str(path), source_sha="smoke-sha", checker_fn=real_checker)
        # Smoke proves wiring and measured three-way shape, not full performance.
        self.assertIsInstance(report["category_accuracy"], float)
        self.assertEqual(report["category_accuracy_denominator"], 3)
        self.assertEqual(report["malformed_total"], 0)
        self.assertEqual(report["baseline"]["status"], "unmeasured")
        for row in report["results"]:
            self.assertIs(type(row["observed_verified"]), bool)
            self.assertIn(
                row["observed_verdict"],
                ("supported", "unsupported", "conflicts", "malformed"),
            )
        total_confusion = sum(
            report["confusion"][exp][obs]
            for exp in ("supported", "unsupported", "conflicts")
            for obs in ("supported", "unsupported", "conflicts", "malformed")
        )
        self.assertEqual(total_confusion, 3)
        diagonal = sum(
            report["confusion"][v][v] for v in ("supported", "unsupported", "conflicts")
        )
        self.assertEqual(diagonal, report["category_correct_total"])
        malformed_column = sum(
            report["confusion"][exp]["malformed"]
            for exp in ("supported", "unsupported", "conflicts")
        )
        self.assertEqual(malformed_column, report["malformed_total"])
        # Hand checked deterministic expectations for these synthetic inputs.
        by_id = {row["id"]: row for row in report["results"]}
        self.assertEqual(by_id["T-001"]["observed_verdict"], "supported")
        self.assertEqual(by_id["T-002"]["observed_verdict"], "conflicts")
        self.assertEqual(by_id["T-003"]["observed_verdict"], "unsupported")
        self.assertAlmostEqual(report["category_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
