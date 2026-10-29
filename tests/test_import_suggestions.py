"""Tests for launchcrew.import_suggestions.

Synthetic fixtures only. No personal information, no network, no files.
"""
import json
import unittest

from launchcrew.import_suggestions import (
    MAX_INPUT_CHARS,
    MAX_SUGGESTION_CHARS,
    MAX_SUGGESTIONS,
    PARSER_VERSION,
    STATUS_UNCONFIRMED,
    SUPPORTED_SOURCES,
    parse_import_text,
)


def _blob_without_unconfirmed(result):
    blob = json.dumps(result).lower().replace("unconfirmed", "")
    return blob


def _assert_all_unconfirmed(testcase, result, source):
    testcase.assertEqual(result["status"], STATUS_UNCONFIRMED)
    testcase.assertEqual(result["source"], source)
    testcase.assertIsInstance(result["suggestions"], list)
    for position, item in enumerate(result["suggestions"]):
        testcase.assertEqual(item["status"], STATUS_UNCONFIRMED)
        testcase.assertEqual(item["source"], source)
        testcase.assertEqual(item["index"], position)
        testcase.assertIsInstance(item["text"], str)
        testcase.assertTrue(item["text"])
    blob = _blob_without_unconfirmed(result)
    for banned in ("approv", "verif", "confirm", "trusted", "evidence",
                   "citation", "guaranteed"):
        testcase.assertNotIn(banned, blob)


class ImportSuggestionsTests(unittest.TestCase):
    def test_supported_sources(self):
        self.assertIn("listing", SUPPORTED_SOURCES)
        self.assertIn("instagram_bio", SUPPORTED_SOURCES)
        self.assertIn("instagram_caption", SUPPORTED_SOURCES)

    def test_empty_string_returns_unconfirmed_empty(self):
        result = parse_import_text("", "listing")
        self.assertEqual(result["suggestions"], [])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["parser_version"], PARSER_VERSION)
        _assert_all_unconfirmed(self, result, "listing")

    def test_whitespace_only_returns_empty(self):
        result = parse_import_text("  \n\t\n   ", "instagram_bio")
        self.assertEqual(result["suggestions"], [])
        self.assertGreaterEqual(result["dropped_empty"], 1)
        _assert_all_unconfirmed(self, result, "instagram_bio")

    def test_long_input_rejected(self):
        long_text = "x" * (MAX_INPUT_CHARS + 1)
        for source in SUPPORTED_SOURCES:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    parse_import_text(long_text, source)

    def test_input_at_max_length_accepted(self):
        text = "a" * MAX_SUGGESTION_CHARS
        padding_lines = ["ok"] * 5
        _ = padding_lines
        result = parse_import_text(text, "listing")
        self.assertEqual(len(result["suggestions"]), 1)
        _assert_all_unconfirmed(self, result, "listing")

    def test_malformed_text_type_rejected(self):
        for bad in (None, b"bytes", 123, ["line"], {"text": "x"}):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(TypeError):
                    parse_import_text(bad, "listing")

    def test_malformed_source_type_rejected(self):
        for bad in (None, b"listing", 123, ["listing"]):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(TypeError):
                    parse_import_text("Maple Street Bakery", bad)

    def test_unsupported_source_rejected(self):
        for bad in ("", "tiktok", "website", "LISTING", " listing",
                    "instagram", "instagram-bio", "caption"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_import_text("Sample bake stand", bad)

    def test_control_heavy_rejected(self):
        for bad in ("hello\x00world", "a\x01b", "x\x1by",
                    "tab\tok\x7f", "snowman\x9fhere"):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(ValueError):
                    parse_import_text(bad, "listing")

    def test_allowed_controls_accepted(self):
        result = parse_import_text("line one\r\nline two\ttabbed", "listing")
        texts = [s["text"] for s in result["suggestions"]]
        self.assertEqual(texts, ["line one", "line two tabbed"])
        _assert_all_unconfirmed(self, result, "listing")

    def test_duplicate_exact_collapses_preserving_order(self):
        text = "\n".join([
            "Baked fresh each morning",
            "Sampleville bake stand",
            "Baked fresh each morning",
            "Weekend pickup only",
            "Sampleville bake stand",
        ])
        result = parse_import_text(text, "listing")
        texts = [s["text"] for s in result["suggestions"]]
        self.assertEqual(texts, [
            "Baked fresh each morning",
            "Sampleville bake stand",
            "Weekend pickup only",
        ])
        self.assertEqual(result["dropped_duplicates"], 2)
        self.assertEqual([s["index"] for s in result["suggestions"]],
                         [0, 1, 2])
        _assert_all_unconfirmed(self, result, "listing")

    def test_duplicate_whitespace_variants_collapse(self):
        text = "  Baked   fresh\tmorning  \nBaked fresh morning"
        result = parse_import_text(text, "instagram_caption")
        texts = [s["text"] for s in result["suggestions"]]
        self.assertEqual(texts, ["Baked fresh morning"])
        self.assertEqual(result["dropped_duplicates"], 1)
        _assert_all_unconfirmed(self, result, "instagram_caption")

    def test_duplicate_matching_is_exact_case_sensitive(self):
        text = "Baked fresh\nbaked fresh\nBAKED FRESH"
        result = parse_import_text(text, "listing")
        texts = [s["text"] for s in result["suggestions"]]
        self.assertEqual(texts, ["Baked fresh", "baked fresh", "BAKED FRESH"])
        self.assertEqual(result["dropped_duplicates"], 0)

    def test_source_labels_echoed(self):
        for source in SUPPORTED_SOURCES:
            with self.subTest(source=source):
                result = parse_import_text("Sunny corner book cart", source)
                self.assertEqual(result["source"], source)
                self.assertEqual(result["suggestions"][0]["source"], source)
                _assert_all_unconfirmed(self, result, source)

    def test_text_fidelity_prices_percentages_dates(self):
        text = "\n".join([
            "Mini loaf $4, family loaf $12.50",
            "Opening week 20% off bundles",
            "Pickup window 2026-02-14",
            "Call time 3.50 means half past three",
        ])
        result = parse_import_text(text, "listing")
        texts = [s["text"] for s in result["suggestions"]]
        self.assertEqual(texts, [
            "Mini loaf $4, family loaf $12.50",
            "Opening week 20% off bundles",
            "Pickup window 2026-02-14",
            "Call time 3.50 means half past three",
        ])
        _assert_all_unconfirmed(self, result, "listing")

    def test_text_fidelity_case_punctuation_markers(self):
        text = "\n".join([
            "- Fresh SOURDOUGH, baked daily!",
            "Maple Street Bakery | Sampleville | Est. 2021",
        ])
        result = parse_import_text(text, "instagram_bio")
        texts = [s["text"] for s in result["suggestions"]]
        self.assertEqual(texts, [
            "- Fresh SOURDOUGH, baked daily!",
            "Maple Street Bakery | Sampleville | Est. 2021",
        ])

    def test_whitespace_normalized_conservatively(self):
        result = parse_import_text(
            "  Sunny   corner\t\tbook   cart  ", "listing")
        self.assertEqual(result["suggestions"][0]["text"],
                         "Sunny corner book cart")

    def test_newlines_split_and_empty_lines_skipped(self):
        result = parse_import_text("Alpha\n\n\nBeta\n   \nGamma", "listing")
        texts = [s["text"] for s in result["suggestions"]]
        self.assertEqual(texts, ["Alpha", "Beta", "Gamma"])
        self.assertGreaterEqual(result["dropped_empty"], 2)

    def test_suggestion_count_bounded(self):
        lines = [f"Sample item {i:02d}" for i in range(MAX_SUGGESTIONS + 5)]
        result = parse_import_text("\n".join(lines), "listing")
        self.assertEqual(len(result["suggestions"]), MAX_SUGGESTIONS)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["suggestions"][0]["text"], "Sample item 00")
        self.assertEqual(
            result["suggestions"][-1]["text"],
            f"Sample item {MAX_SUGGESTIONS - 1:02d}",
        )
        _assert_all_unconfirmed(self, result, "listing")

    def test_each_suggestion_length_bounded(self):
        overlong = "z" * (MAX_SUGGESTION_CHARS + 1)
        text = "\n".join(["Sunny corner book cart", overlong, "Beta shelf"])
        result = parse_import_text(text, "listing")
        texts = [s["text"] for s in result["suggestions"]]
        self.assertEqual(texts, ["Sunny corner book cart", "Beta shelf"])
        self.assertEqual(result["dropped_overlong"], 1)
        self.assertFalse(result["truncated"])

    def test_html_returned_as_plain_text_without_execution(self):
        text = "<script>alert(1)</script>"
        result = parse_import_text(text, "listing")
        self.assertEqual(result["suggestions"][0]["text"], text)
        self.assertNotIn("html", _blob_without_unconfirmed(result))
        _assert_all_unconfirmed(self, result, "listing")

    def test_stable_metadata_shape(self):
        result = parse_import_text("Alpha\nBeta", "instagram_caption")
        self.assertEqual(
            set(result.keys()),
            {"status", "source", "suggestions", "truncated",
             "dropped_duplicates", "dropped_overlong", "dropped_empty",
             "parser_version"},
        )
        self.assertEqual(
            set(result["suggestions"][0].keys()),
            {"text", "source", "status", "index"},
        )
        self.assertIsInstance(result["truncated"], bool)
        self.assertIsInstance(result["dropped_duplicates"], int)
        self.assertIsInstance(result["dropped_overlong"], int)
        self.assertIsInstance(result["dropped_empty"], int)

    def test_pure_deterministic(self):
        text = "Sunny corner book cart\nWeekend pickup only"
        first = parse_import_text(text, "listing")
        second = parse_import_text(text, "listing")
        self.assertEqual(first, second)
        self.assertEqual(text, "Sunny corner book cart\nWeekend pickup only")

    def test_unconfirmed_invariant_across_sources(self):
        samples = {
            "listing": "Mini loaf $4\nWeekend pickup only",
            "instagram_bio": "Sampleville bake stand\nEst. 2021",
            "instagram_caption": "Fresh batch Friday\n20% off bundles",
        }
        for source, text in samples.items():
            with self.subTest(source=source):
                _assert_all_unconfirmed(
                    self, parse_import_text(text, source), source)


if __name__ == "__main__":
    unittest.main()
