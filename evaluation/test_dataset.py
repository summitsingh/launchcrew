"""Dataset validation tests for synthetic Checker evaluation."""

import json
import re
import unittest
from pathlib import Path

DATASET_PATH = Path(__file__).with_name("dataset_v1.json")
ALLOWED_VERDICTS = {"Supported", "Not in confirmed facts", "Conflicts with confirmed facts"}
REQUIRED_ERROR_CATEGORIES = {
    "wrong_material",
    "missing_included_item",
    "quantity",
    "size",
    "price_mismatch",
    "false_absolute",
    "product_type_swap",
    "origin",
    "warranty",
}
ALLOWED_CATEGORIES = REQUIRED_ERROR_CATEGORIES | {
    "color",
    "capacity",
    "weight",
    "supported_exact",
    "supported_paraphrase",
}
REQUIRED_KEYS = {"id", "product", "confirmed_facts", "candidate_claim", "expected_verdict", "category"}
ID_PATTERN = re.compile(r"^EVAL-\d{3}$")
BANNED_RATE_KEYS = {"accuracy", "catch_rate", "false_block_rate", "binary_catch_rate", "category_accuracy"}


def load_dataset():
    data = DATASET_PATH.read_bytes()
    return data, json.loads(data.decode("utf-8"))


class DatasetStructureTests(unittest.TestCase):
    def test_version_and_id_present(self):
        _, dataset = load_dataset()
        self.assertEqual(dataset.get("version"), "1.0.0")
        self.assertEqual(dataset.get("dataset_id"), "launchcrew-checker-synthetic-v1")
        self.assertIn("cases", dataset)
        self.assertIsInstance(dataset["cases"], list)

    def test_counts_meet_minimums(self):
        _, dataset = load_dataset()
        cases = dataset["cases"]
        errors = [c for c in cases if c.get("expected_verdict") != "Supported"]
        supported = [c for c in cases if c.get("expected_verdict") == "Supported"]
        self.assertGreaterEqual(len(errors), 20)
        self.assertGreaterEqual(len(supported), 6)
        self.assertGreaterEqual(len(cases), 26)

    def test_ids_unique_and_stable_format(self):
        _, dataset = load_dataset()
        ids = [c.get("id") for c in dataset["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        for case_id in ids:
            self.assertIsInstance(case_id, str)
            self.assertTrue(ID_PATTERN.match(case_id), "bad id " + str(case_id))

    def test_required_keys_present(self):
        _, dataset = load_dataset()
        for case in dataset["cases"]:
            self.assertTrue(REQUIRED_KEYS.issubset(case.keys()), "missing keys in " + str(case.get("id")))

    def test_verdicts_allowed(self):
        _, dataset = load_dataset()
        for case in dataset["cases"]:
            self.assertIn(case.get("expected_verdict"), ALLOWED_VERDICTS)

    def test_categories_allowed_and_required_covered(self):
        _, dataset = load_dataset()
        seen_errors = set()
        for case in dataset["cases"]:
            self.assertIn(case.get("category"), ALLOWED_CATEGORIES)
            if case.get("expected_verdict") != "Supported":
                seen_errors.add(case.get("category"))
        missing = REQUIRED_ERROR_CATEGORIES - seen_errors
        self.assertEqual(missing, set(), "missing error categories " + str(sorted(missing)))

    def test_supported_controls_include_paraphrases(self):
        _, dataset = load_dataset()
        paraphrases = [c for c in dataset["cases"] if c.get("category") == "supported_paraphrase"]
        exact = [c for c in dataset["cases"] if c.get("category") == "supported_exact"]
        self.assertGreaterEqual(len(paraphrases), 2)
        self.assertGreaterEqual(len(exact), 1)
        for case in paraphrases:
            self.assertEqual(case.get("expected_verdict"), "Supported")

    def test_confirmed_facts_and_claim_nonempty(self):
        _, dataset = load_dataset()
        for case in dataset["cases"]:
            facts = case.get("confirmed_facts")
            claim = case.get("candidate_claim")
            self.assertIsInstance(facts, list)
            self.assertGreaterEqual(len(facts), 1)
            for fact in facts:
                self.assertIsInstance(fact, str)
                self.assertTrue(fact.strip(), "empty fact in " + str(case.get("id")))
            self.assertIsInstance(claim, str)
            self.assertTrue(claim.strip(), "empty claim in " + str(case.get("id")))

    def test_fictional_markers_present(self):
        _, dataset = load_dataset()
        for case in dataset["cases"]:
            product = case.get("product", "")
            self.assertIn("Fictional", product)
            self.assertIn("synthetic evaluation only", product)

    def test_no_hardcoded_rates_in_dataset(self):
        _, dataset = load_dataset()
        for key in BANNED_RATE_KEYS:
            self.assertNotIn(key, dataset)
        for case in dataset["cases"]:
            for key in BANNED_RATE_KEYS:
                self.assertNotIn(key, case)


class DatasetPrivacyTests(unittest.TestCase):
    def test_no_at_sign_in_bytes(self):
        data, _ = load_dataset()
        self.assertNotIn(chr(64), data.decode("utf-8"))

    def test_no_email_pattern(self):
        _, dataset = load_dataset()
        text = json.dumps(dataset)
        pat = re.compile(r"[\w.+-]+" + chr(64) + r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,63}")
        self.assertIsNone(pat.search(text))

    def test_no_long_digit_runs(self):
        _, dataset = load_dataset()
        text = json.dumps(dataset)
        self.assertIsNone(re.search(r"\d{7,}", text))

    def test_no_street_like_entries(self):
        _, dataset = load_dataset()
        suffixes = ["street", "avenue", "road", "lane", "drive", "court", "boulevard", "way", "place", "parkway", "circle", "terrace", "trail", "highway"]
        for case in dataset["cases"]:
            for fact in case.get("confirmed_facts", []) + [case.get("candidate_claim", "")]:
                lowered = fact.lower()
                has_digit = any(ch.isdigit() for ch in lowered)
                if not has_digit:
                    continue
                for suffix in suffixes:
                    self.assertNotIn(" " + suffix, lowered, "possible street in " + str(case.get("id")))

    def test_no_secret_markers(self):
        _, dataset = load_dataset()
        text = json.dumps(dataset)
        marker_a = "AK" + "IA"
        marker_b = "gh" + "p_"
        marker_c = "gh" + "o_"
        marker_d = "s" + "k-"
        for marker in (marker_a, marker_b, marker_c, marker_d):
            self.assertNotIn(marker, text)

    def test_no_owner_name(self):
        _, dataset = load_dataset()
        text = json.dumps(dataset)
        full = "Summit" + " Singh"
        joined = "summit" + "singh"
        self.assertNotIn(full, text)
        self.assertNotIn(joined, text.lower())

    def test_no_em_dash(self):
        data, _ = load_dataset()
        self.assertNotIn(chr(0x2014), data.decode("utf-8"))

    def test_no_legacy_brand(self):
        _, dataset = load_dataset()
        text = json.dumps(dataset)
        brand = "Company" + " OS"
        self.assertNotIn(brand, text)
        self.assertNotIn(brand.lower(), text.lower())

    def test_no_photo_or_credential_terms(self):
        _, dataset = load_dataset()
        text = json.dumps(dataset).lower()
        for term in ("photo", "password", "account id", "credential"):
            self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
