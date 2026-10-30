"""Listing title check: supported, unsupported, and conflicting cases.

Socket-free and offline only. No model calls, no credentials. Uses only
caller-supplied confirmed claims, no invented facts.
"""
import unittest

from launchcrew.facts import CONFLICTS, SUPPORTED, UNSUPPORTED
from launchcrew.listing_check import check_listing_title, lint_shopping_title


class ListingCheckTests(unittest.TestCase):
    def test_supported_title_matches_confirmed_claim(self):
        result = check_listing_title(
            "Full-grain leather", ["Full-grain leather", "$129"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["verdict"], SUPPORTED)
        self.assertEqual(result["verdict"], "supported")
        self.assertEqual(result["evidence"], "Full-grain leather")

    def test_unsupported_title_not_in_confirmed_facts(self):
        result = check_listing_title(
            "Bifold compact", ["Full-grain leather", "$129"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["verdict"], UNSUPPORTED)
        self.assertEqual(result["verdict"], "unsupported")
        self.assertIsNone(result["evidence"])

    def test_conflicting_title_contradicts_confirmed_claim(self):
        result = check_listing_title("$49", ["Full-grain leather", "$129"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["verdict"], CONFLICTS)
        self.assertEqual(result["verdict"], "conflicts")
        self.assertEqual(result["evidence"], "$129")


class ShoppingTitleLintTests(unittest.TestCase):
    def test_flags_promotional_text(self):
        issues = lint_shopping_title("Full-grain leather wallet, FREE SHIPPING")
        rules = [i["rule"] for i in issues]
        self.assertIn("promotional_text", rules)
        match = next(i["match"] for i in issues if i["rule"] == "promotional_text")
        self.assertEqual(match, "free shipping")

    def test_flags_all_caps_word(self):
        issues = lint_shopping_title("Full-grain leather WALLET")
        rules = [i["rule"] for i in issues]
        self.assertIn("all_caps", rules)
        match = next(i["match"] for i in issues if i["rule"] == "all_caps")
        self.assertEqual(match, "WALLET")

    def test_flags_repeated_punctuation(self):
        issues = lint_shopping_title("Full-grain leather wallet!!!")
        rules = [i["rule"] for i in issues]
        self.assertIn("repeated_punctuation", rules)
        match = next(i["match"] for i in issues
                     if i["rule"] == "repeated_punctuation")
        self.assertEqual(match, "!!!")

    def test_flags_combined_violations(self):
        issues = lint_shopping_title("WALLET on sale!!!")
        rules = [i["rule"] for i in issues]
        self.assertIn("promotional_text", rules)
        self.assertIn("all_caps", rules)
        self.assertIn("repeated_punctuation", rules)

    def test_clean_title_passes(self):
        self.assertEqual(lint_shopping_title("Full-grain leather wallet"), [])

    def test_price_decimal_never_flags(self):
        self.assertEqual(lint_shopping_title("$49.99 leather wallet"), [])


if __name__ == "__main__":
    unittest.main()
