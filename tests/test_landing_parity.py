"""Tests for the landing page offer parity sentinel.

Socket-free and offline only. No model calls, no credentials, no PII.
"""
import unittest

from launchcrew.landing_parity import (
    LANDING_PARITY_VERSION,
    audit_landing_page_parity,
    extract_prices,
    verify_legal_footer,
    verify_price_parity,
)

FULL_FOOTER_HTML = """<html><body>
<p>Widget for $49. Buy now.</p>
<footer>
<a href="/privacy">Privacy Policy</a>
<a href="/terms">Terms of Service</a>
<a href="/refund-policy">Refund Policy</a>
</footer>
</body></html>"""

MISSING_REFUND_HTML = """<html><body>
<p>Widget for $49. Buy now.</p>
<footer>
<a href="/privacy">Privacy Policy</a>
<a href="/terms">Terms of Service</a>
</footer>
</body></html>"""


class ExtractPricesTests(unittest.TestCase):
    def test_extracts_dollar_amounts(self):
        self.assertEqual(extract_prices("Only $49 today"), ["$49"])

    def test_extracts_decimal_amount(self):
        self.assertEqual(extract_prices("Only $49.99 today"), ["$49.99"])

    def test_extracts_pound_and_euro(self):
        self.assertEqual(
            extract_prices("£20 in the UK, €35 in the EU"),
            ["£20", "€35"],
        )

    def test_sorted_unique(self):
        self.assertEqual(
            extract_prices("$69 then $49 then $69"),
            ["$49", "$69"],
        )

    def test_no_prices_returns_empty(self):
        self.assertEqual(extract_prices("free shipping today"), [])

    def test_non_string_returns_empty(self):
        self.assertEqual(extract_prices(None), [])
        self.assertEqual(extract_prices(49), [])

    def test_version_constant(self):
        self.assertEqual(LANDING_PARITY_VERSION, "landing-parity/v1")


class PriceParityTests(unittest.TestCase):
    def test_matching_price_passes(self):
        result = verify_price_parity(
            "Get the widget for only $49",
            "<html><body><p>Widget for $49. Buy now.</p></body></html>",
        )
        self.assertTrue(result["parity_passed"])
        self.assertEqual(result["ad_prices"], ["$49"])
        self.assertEqual(result["landing_prices"], ["$49"])
        self.assertEqual(result["unmatched_ad_prices"], [])

    def test_mismatch_fails_with_unmatched(self):
        result = verify_price_parity(
            "Get the widget for only $49",
            "<html><body><p>Widget for $69. Buy now.</p></body></html>",
        )
        self.assertFalse(result["parity_passed"])
        self.assertEqual(result["ad_prices"], ["$49"])
        self.assertEqual(result["landing_prices"], ["$69"])
        self.assertEqual(result["unmatched_ad_prices"], ["$49"])

    def test_partial_match_reports_only_missing(self):
        result = verify_price_parity(
            "Was $69 now $49",
            "<html><body><p>Now $49.</p></body></html>",
        )
        self.assertFalse(result["parity_passed"])
        self.assertEqual(result["unmatched_ad_prices"], ["$69"])

    def test_no_prices_in_ad_passes(self):
        result = verify_price_parity(
            "Free shipping on every order",
            "<html><body><p>Widget for $69.</p></body></html>",
        )
        self.assertTrue(result["parity_passed"])
        self.assertEqual(result["ad_prices"], [])
        self.assertEqual(result["unmatched_ad_prices"], [])

    def test_non_string_inputs_do_not_raise(self):
        result = verify_price_parity(None, None)
        self.assertTrue(result["parity_passed"])
        self.assertEqual(result["ad_prices"], [])
        self.assertEqual(result["landing_prices"], [])


class LegalFooterTests(unittest.TestCase):
    def test_full_footer_passes(self):
        result = verify_legal_footer(FULL_FOOTER_HTML)
        self.assertTrue(result["legal_compliance_passed"])
        self.assertEqual(
            result["detected_policies"],
            ["privacy_policy", "terms_of_service", "refund_policy"],
        )
        self.assertEqual(result["missing_policies"], [])

    def test_missing_refund_fails(self):
        result = verify_legal_footer(MISSING_REFUND_HTML)
        self.assertFalse(result["legal_compliance_passed"])
        self.assertIn("privacy_policy", result["detected_policies"])
        self.assertIn("terms_of_service", result["detected_policies"])
        self.assertEqual(result["missing_policies"], ["refund_policy"])

    def test_empty_footer_misses_everything(self):
        result = verify_legal_footer("<html><body><p>No footer.</p></body></html>")
        self.assertFalse(result["legal_compliance_passed"])
        self.assertEqual(result["detected_policies"], [])
        self.assertEqual(
            result["missing_policies"],
            ["privacy_policy", "terms_of_service", "refund_policy"],
        )

    def test_href_only_links_detected_case_insensitive(self):
        html = (
            "<footer>"
            '<a href="/PRIVACY">Link</a>'
            '<a href="/TOS">Link</a>'
            '<a href="/Refund">Link</a>'
            "</footer>"
        )
        result = verify_legal_footer(html)
        self.assertTrue(result["legal_compliance_passed"])
        self.assertEqual(result["missing_policies"], [])

    def test_malformed_html_handled_gracefully(self):
        result = verify_legal_footer("<footer><a href=/privacy>Privacy")
        self.assertIsInstance(result["legal_compliance_passed"], bool)
        self.assertIn("detected_policies", result)
        self.assertIn("missing_policies", result)

    def test_non_string_input_handled_gracefully(self):
        result = verify_legal_footer(None)
        self.assertFalse(result["legal_compliance_passed"])
        self.assertEqual(result["detected_policies"], [])
        self.assertEqual(len(result["missing_policies"]), 3)


class AuditTests(unittest.TestCase):
    def test_full_audit_passes(self):
        result = audit_landing_page_parity(
            "Get the widget for only $49", FULL_FOOTER_HTML
        )
        self.assertTrue(result["overall_passed"])
        self.assertTrue(result["parity_passed"])
        self.assertTrue(result["legal_compliance_passed"])
        self.assertEqual(result["version"], "landing-parity/v1")
        self.assertEqual(result["unmatched_ad_prices"], [])
        self.assertEqual(result["missing_policies"], [])

    def test_audit_fails_on_price_mismatch(self):
        result = audit_landing_page_parity(
            "Get the widget for only $49",
            FULL_FOOTER_HTML.replace("$49", "$69"),
        )
        self.assertFalse(result["overall_passed"])
        self.assertFalse(result["parity_passed"])
        self.assertTrue(result["legal_compliance_passed"])
        self.assertEqual(result["unmatched_ad_prices"], ["$49"])

    def test_audit_fails_on_missing_policy(self):
        result = audit_landing_page_parity(
            "Get the widget for only $49", MISSING_REFUND_HTML
        )
        self.assertFalse(result["overall_passed"])
        self.assertTrue(result["parity_passed"])
        self.assertFalse(result["legal_compliance_passed"])
        self.assertEqual(result["missing_policies"], ["refund_policy"])


if __name__ == "__main__":
    unittest.main()
