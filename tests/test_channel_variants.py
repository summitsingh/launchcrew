"""Focused checks for channel presentation variants.

Hand-built fixtures only. No model calls, no network, no live proof.
"""
import copy
import unittest

from launchcrew.channel_variants import (
    X_MAX_CHARS,
    build_channel_variants,
    build_x_variant,
    split_sentences,
    validate_x_variant,
)


class ChannelVariantTests(unittest.TestCase):
    def test_x_limit_is_280(self):
        self.assertEqual(X_MAX_CHARS, 280)

    def test_x_exact_280_boundary_is_exportable(self):
        sentence = "A" * 279 + "."
        self.assertEqual(len(sentence), 280)
        variant = build_x_variant(sentence, [])
        self.assertEqual(len(variant["text"]), 280)
        self.assertTrue(variant["exportable"])
        self.assertEqual(variant["status"], "ready")
        self.assertIsNone(variant["trim_note"])
        check = validate_x_variant(variant["text"], [], sentence)
        self.assertTrue(check["ok"])
        self.assertTrue(check["exportable"])
        self.assertEqual(check["char_count"], 280)

    def test_x_overlong_first_sentence_refuses_without_fragment(self):
        sentence = "B" * 280 + "."
        self.assertEqual(len(sentence), 281)
        variant = build_x_variant(sentence, [])
        self.assertFalse(variant["exportable"])
        self.assertEqual(variant["status"], "needs_revision")
        self.assertEqual(variant["text"], "")
        self.assertIn("revision", variant["reason"].lower())
        self.assertIn("280", variant["reason"])
        check = validate_x_variant(sentence, [], sentence)
        self.assertFalse(check["ok"])
        self.assertTrue(any("280" in r for r in check["reasons"]))

    def test_decimal_price_does_not_split_sentence(self):
        draft = "Price is $49.99 today. It ships soon."
        parts = split_sentences(draft)
        self.assertEqual(len(parts), 2)
        self.assertIn("$49.99", parts[0])
        self.assertEqual(parts[1], "It ships soon.")
        sized = "Size is 3.5 inches. Good."
        sized_parts = split_sentences(sized)
        self.assertEqual(len(sized_parts), 2)
        self.assertIn("3.5", sized_parts[0])

    def test_price_decimal_exact_match_boundaries(self):
        draft = "Vegan leather wallet at $49.99. Designed in Texas."
        confirmed = ["Vegan leather wallet", "$49.99", "Designed in Texas"]
        variant = build_x_variant(draft, confirmed)
        self.assertTrue(variant["exportable"])
        self.assertIn("$49.99", variant["text"])
        self.assertTrue(validate_x_variant(variant["text"], confirmed, draft)["ok"])
        wrong_price = ["Vegan leather wallet", "$49", "Designed in Texas"]
        check = validate_x_variant(variant["text"], wrong_price, draft)
        self.assertFalse(check["ok"])
        self.assertTrue(any("$49.99" in r or "confirmed" in r for r in check["reasons"]))

    def test_x_trim_keeps_whole_sentences_with_receipt_note(self):
        first = "A" * 100 + "."
        second = "B" * 100 + "."
        third = "C" * 100 + "."
        draft = " ".join([first, second, third])
        variant = build_x_variant(draft, [])
        self.assertTrue(variant["exportable"])
        self.assertEqual(variant["text"], first + " " + second)
        self.assertLessEqual(len(variant["text"]), 280)
        note = variant["trim_note"]
        self.assertIsNotNone(note)
        self.assertIn("2 of 3", note)
        self.assertIn("280", note)
        self.assertIn("omitted", note)
        self.assertIn("no sentence shortened", note.lower())
        for kept in split_sentences(variant["text"]):
            self.assertIn(kept, draft)
        meta = variant["metadata"]
        self.assertEqual((meta["kept_sentences"], meta["total_sentences"]), (2, 3))
        self.assertEqual(meta["omitted_sentences"], 1)

    def test_audience_and_angle_are_never_rendered_as_facts(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        packed = build_channel_variants(
            draft, confirmed, audience="Mars explorers", campaign_angle="Mars launch"
        )
        for key in ("x", "linkedin", "instagram", "email"):
            self.assertNotIn("Mars", packed[key]["text"])
        self.assertIn("Mars explorers", str(packed["provenance"]["audience_context"]))
        self.assertIn("Mars launch", str(packed["provenance"]["angle_context"]))
        note = packed["provenance"]["note"].lower()
        self.assertIn("suggestion", note)
        self.assertIn("not verified", note)

    def test_channel_formats_are_distinct_but_verbatim(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        packed = build_channel_variants(draft, confirmed)
        texts = [packed[k]["text"] for k in ("x", "linkedin", "instagram", "email")]
        self.assertEqual(len(set(texts)), 4)
        self.assertEqual(packed["x"]["text"], draft)
        self.assertTrue(packed["linkedin"]["text"].startswith("Update:"))
        self.assertTrue(packed["instagram"]["text"].endswith("More soon."))
        self.assertEqual(packed["email"]["subject"], "Quick update")
        self.assertIn("Hello,", packed["email"]["body"])
        self.assertIn("Thanks,", packed["email"]["body"])
        for key in ("x", "linkedin", "instagram", "email"):
            body = packed[key]["body"] if key == "email" else packed[key]["text"]
            for sentence in split_sentences(body):
                if sentence in ("Update:", "More soon.", "Hello,", "Thanks,"):
                    continue
                self.assertIn(sentence, draft)

    def test_validator_rejects_cut_sentence_and_invented_price(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        cut = validate_x_variant("Vegan leather wall", confirmed, draft)
        self.assertFalse(cut["ok"])
        self.assertTrue(any("verbatim" in r for r in cut["reasons"]))
        invented = validate_x_variant("Vegan leather wallet at $99.", confirmed, draft)
        self.assertFalse(invented["ok"])
        self.assertTrue(
            any("$99" in r or "verbatim" in r or "confirmed" in r for r in invented["reasons"])
        )

    def test_empty_draft_needs_revision(self):
        variant = build_x_variant("   ", [])
        self.assertFalse(variant["exportable"])
        self.assertEqual(variant["status"], "needs_revision")
        self.assertEqual(variant["text"], "")
        self.assertIn("revision", variant["reason"].lower())

    def test_repeat_calls_are_deterministic(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        first = build_channel_variants(draft, confirmed, audience="Austin commuters")
        second = build_channel_variants(draft, confirmed, audience="Austin commuters")
        self.assertEqual(first, second)
        check_first = validate_x_variant(first["x"]["text"], confirmed, draft)
        check_second = validate_x_variant(second["x"]["text"], confirmed, draft)
        self.assertEqual(check_first, check_second)

    def test_caller_inputs_are_unchanged(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        audience = {"segment": "Austin commuters"}
        angle = "Origin story"
        draft_copy = copy.deepcopy(draft)
        confirmed_copy = copy.deepcopy(confirmed)
        audience_copy = copy.deepcopy(audience)
        angle_copy = copy.deepcopy(angle)
        packed = build_channel_variants(draft, confirmed, audience, angle)
        validate_x_variant(packed["x"]["text"], confirmed, draft)
        self.assertEqual(draft, draft_copy)
        self.assertEqual(confirmed, confirmed_copy)
        self.assertEqual(audience, audience_copy)
        self.assertEqual(angle, angle_copy)


if __name__ == "__main__":
    unittest.main()
