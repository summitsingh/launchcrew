"""Tests for structured per-field import suggestions.

Synthetic fixtures only. No personal information, no network, no files.
"""
import json
import unittest

from launchcrew.import_suggestions import (
    MAX_INPUT_CHARS,
    MAX_SUGGESTION_CHARS,
    MAX_SUGGESTIONS,
    REPLACE_WARNING,
    STRUCTURED_FIELDS,
    STRUCTURED_PARSER_VERSION,
    STATUS_UNCONFIRMED,
    SUPPORTED_SOURCES,
    is_replace_conflict,
    parse_structured_import,
    structured_proposal_digest,
)

LISTING_TEXT = "\n".join([
    "Full-grain leather tote",
    "Holds a 13in laptop in six card slots",
    "Compact bifold size",
    "$49 launch price",
    "Handmade for Austin commuters",
])

BIO_TEXT = "\n".join([
    "Sampleville bake stand",
    "We bake fresh each morning.",
    "Est. 2021",
])

CAPTION_TEXT = "\n".join([
    "Fresh batch Friday",
    "20% off bundles",
    "I pack every box myself.",
])


def _blob_without_unconfirmed(result):
    blob = json.dumps(result).lower().replace("unconfirmed", "")
    return blob


def _assert_all_unconfirmed(testcase, result, source):
    testcase.assertEqual(result["status"], STATUS_UNCONFIRMED)
    testcase.assertEqual(result["source"], source)
    testcase.assertEqual(result["parser_version"], STRUCTURED_PARSER_VERSION)
    testcase.assertIn("proposal_digest", result)
    testcase.assertRegex(result["proposal_digest"], r"^[0-9a-f]{64}$")
    testcase.assertIsInstance(result["field_suggestions"], list)
    for position, item in enumerate(result["field_suggestions"]):
        testcase.assertIn(item["field"], STRUCTURED_FIELDS)
        testcase.assertEqual(item["status"], STATUS_UNCONFIRMED)
        testcase.assertEqual(item["source"], source)
        testcase.assertEqual(item["index"], position)
        testcase.assertIsInstance(item["text"], str)
        testcase.assertTrue(item["text"])
    blob = _blob_without_unconfirmed(result)
    for banned in ("approv", "verif", "confirm", "trusted", "evidence",
                   "citation", "guaranteed"):
        testcase.assertNotIn(banned, blob)


class StructuredImportTests(unittest.TestCase):
    def test_structured_fields_cover_fact_slots(self):
        self.assertEqual(
            tuple(STRUCTURED_FIELDS),
            ("material", "contents", "size", "price", "allowed_claim", "founder_note"),
        )

    def test_listing_splits_into_distinct_fields(self):
        result = parse_structured_import(LISTING_TEXT, "listing")
        by_text = {item["text"]: item["field"] for item in result["field_suggestions"]}
        self.assertEqual(by_text, {
            "Full-grain leather tote": "material",
            "Holds a 13in laptop in six card slots": "contents",
            "Compact bifold size": "size",
            "$49 launch price": "price",
            "Handmade for Austin commuters": "allowed_claim",
        })
        _assert_all_unconfirmed(self, result, "listing")

    def test_bio_routes_first_person_sentence_to_founder_note(self):
        result = parse_structured_import(BIO_TEXT, "instagram_bio")
        by_text = {item["text"]: item["field"] for item in result["field_suggestions"]}
        self.assertEqual(by_text, {
            "Sampleville bake stand": "allowed_claim",
            "We bake fresh each morning.": "founder_note",
            "Est. 2021": "allowed_claim",
        })
        _assert_all_unconfirmed(self, result, "instagram_bio")

    def test_caption_routes_first_person_sentence_to_founder_note(self):
        result = parse_structured_import(CAPTION_TEXT, "instagram_caption")
        by_text = {item["text"]: item["field"] for item in result["field_suggestions"]}
        self.assertEqual(by_text, {
            "Fresh batch Friday": "allowed_claim",
            "20% off bundles": "allowed_claim",
            "I pack every box myself.": "founder_note",
        })
        _assert_all_unconfirmed(self, result, "instagram_caption")

    def test_explicit_labels_route_to_named_fields(self):
        text = "\n".join([
            "Material: full-grain leather",
            "Contents: six card slots",
            "Size: compact bifold",
            "Price: $49",
            "Note: I stitch every seam.",
            "Claim: weekend pickup only",
        ])
        result = parse_structured_import(text, "listing")
        by_text = {item["text"]: item["field"] for item in result["field_suggestions"]}
        self.assertEqual(by_text, {
            "Material: full-grain leather": "material",
            "Contents: six card slots": "contents",
            "Size: compact bifold": "size",
            "Price: $49": "price",
            "Note: I stitch every seam.": "founder_note",
            "Claim: weekend pickup only": "allowed_claim",
        })
        _assert_all_unconfirmed(self, result, "listing")

    def test_drive_file_source_uses_same_schema(self):
        result = parse_structured_import(LISTING_TEXT, "drive_file")
        self.assertEqual(result["source"], "drive_file")
        fields = [item["field"] for item in result["field_suggestions"]]
        self.assertEqual(fields, ["material", "contents", "size", "price", "allowed_claim"])
        _assert_all_unconfirmed(self, result, "drive_file")

    def test_digest_stable_and_content_sensitive(self):
        first = parse_structured_import(LISTING_TEXT, "listing")
        second = parse_structured_import(LISTING_TEXT, "listing")
        self.assertEqual(first["proposal_digest"], second["proposal_digest"])
        changed = parse_structured_import(LISTING_TEXT + "\nExtra strap", "listing")
        self.assertNotEqual(first["proposal_digest"], changed["proposal_digest"])
        self.assertEqual(
            first["proposal_digest"],
            structured_proposal_digest(first["field_suggestions"]),
        )
        empty = parse_structured_import("   \n  ", "listing")
        self.assertEqual(empty["field_suggestions"], [])
        self.assertRegex(empty["proposal_digest"], r"^[0-9a-f]{64}$")
        _assert_all_unconfirmed(self, empty, "listing")

    def test_replace_guard_matrix(self):
        digest = parse_structured_import(LISTING_TEXT, "listing")["proposal_digest"]
        other = parse_structured_import(BIO_TEXT, "listing")["proposal_digest"]
        self.assertFalse(is_replace_conflict(None, digest))
        self.assertFalse(is_replace_conflict("", digest))
        self.assertFalse(is_replace_conflict(digest, digest))
        self.assertFalse(is_replace_conflict(other, digest, True))
        self.assertTrue(is_replace_conflict(other, digest))
        self.assertTrue(is_replace_conflict(other, digest, False))
        self.assertIn("pending", REPLACE_WARNING.lower())
        self.assertIn("did not replace", REPLACE_WARNING.lower())

    def test_replace_guard_rejects_malformed_digests(self):
        digest = parse_structured_import(LISTING_TEXT, "listing")["proposal_digest"]
        for bad in ("not-a-digest", "x" * 63, "z" * 64, "https://evil.invalid/d"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    is_replace_conflict(bad, digest)
        with self.assertRaises(ValueError):
            is_replace_conflict("x" * 64, "short")
        with self.assertRaises(ValueError):
            is_replace_conflict(None, digest, confirm_replace="yes")  # type: ignore[arg-type]

    def test_bounds_match_line_parser(self):
        long_text = "x" * (MAX_INPUT_CHARS + 1)
        for source in SUPPORTED_SOURCES:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    parse_structured_import(long_text, source)
        lines = [f"Sample item {i:02d}" for i in range(MAX_SUGGESTIONS + 5)]
        result = parse_structured_import("\n".join(lines), "listing")
        self.assertEqual(len(result["field_suggestions"]), MAX_SUGGESTIONS)
        self.assertTrue(result["truncated"])
        overlong = "z" * (MAX_SUGGESTION_CHARS + 1)
        result = parse_structured_import("Alpha\n" + overlong + "\nBeta", "listing")
        texts = [s["text"] for s in result["field_suggestions"]]
        self.assertEqual(texts, ["Alpha", "Beta"])
        self.assertEqual(result["dropped_overlong"], 1)
        result = parse_structured_import("Alpha\nAlpha\nBeta\n  \n", "listing")
        self.assertEqual(result["dropped_duplicates"], 1)
        self.assertGreaterEqual(result["dropped_empty"], 1)
        _assert_all_unconfirmed(self, result, "listing")

    def test_input_validation_matches_line_parser(self):
        for bad in (None, b"bytes", 123, ["line"]):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(TypeError):
                    parse_structured_import(bad, "listing")  # type: ignore[arg-type]
        for bad in ("", "tiktok", "LISTING", "drive"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_structured_import("Sample bake stand", bad)
        with self.assertRaises(ValueError):
            parse_structured_import("hello\x00world", "listing")

    def test_fidelity_preserved_per_field(self):
        text = "Mini loaf $4, family loaf $12.50\n- Fresh SOURDOUGH, baked daily!"
        result = parse_structured_import(text, "listing")
        by_text = {item["text"]: item["field"] for item in result["field_suggestions"]}
        self.assertEqual(by_text, {
            "Mini loaf $4, family loaf $12.50": "price",
            "- Fresh SOURDOUGH, baked daily!": "allowed_claim",
        })
        hostile = "<script>alert(1)</script>"
        result = parse_structured_import(hostile, "listing")
        self.assertEqual(result["field_suggestions"][0]["text"], hostile)
        self.assertNotIn("html", _blob_without_unconfirmed(result))

    def test_stable_shape(self):
        result = parse_structured_import("Alpha\nBeta", "instagram_caption")
        self.assertEqual(
            set(result.keys()),
            {"status", "source", "field_suggestions", "proposal_digest",
             "truncated", "dropped_duplicates", "dropped_overlong",
             "dropped_empty", "parser_version"},
        )
        self.assertEqual(
            set(result["field_suggestions"][0].keys()),
            {"field", "text", "source", "status", "index"},
        )

    def test_pure_deterministic(self):
        first = parse_structured_import(LISTING_TEXT, "listing")
        second = parse_structured_import(LISTING_TEXT, "listing")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
