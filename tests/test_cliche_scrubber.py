"""Spec-to-benefit cliche scrubber: positive and negative cases.

New-file-only coverage for launchcrew/cliche_scrubber.py. Stdlib
unittest, no I/O, no network, no model calls.
"""

import unittest

from launchcrew.cliche_scrubber import (
    CLEAN_REPLACEMENT,
    CLICHE_PHRASES,
    CLICHE_REASON,
    CLICHE_SCRUBBER_VERSION,
    CLICHE_WORDS,
    clean_cliches,
    has_cliche,
    lint_cliches,
)

EXPECTED_REASON = (
    "Generic marketing cliché; replace with a verified, "
    "concrete product specification."
)


def _cliches(text):
    return {hit["cliche"] for hit in lint_cliches(text)}


class VersionTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(CLICHE_SCRUBBER_VERSION, "cliche-scrubber/v1")

    def test_reason_constant(self):
        self.assertEqual(CLICHE_REASON, EXPECTED_REASON)
        self.assertNotIn("\u2014", CLICHE_REASON)


class WordInventoryTests(unittest.TestCase):
    def test_expected_words_present(self):
        for word in (
            "game-changer",
            "game-changing",
            "revolutionize",
            "revolutionary",
            "unleash",
            "next-level",
            "elevate",
            "supercharge",
            "seamlessly",
            "cutting-edge",
            "groundbreaking",
            "transformative",
            "redefine",
            "redefining",
            "miracle",
        ):
            with self.subTest(word=word):
                self.assertIn(word, CLICHE_WORDS)

    def test_expected_phrases_present(self):
        for phrase in (
            ("game", "changer"),
            ("game", "changing"),
            ("next", "level"),
            ("unleash", "your", "potential"),
            ("elevate", "your", "routine"),
            ("take", "to", "the", "next", "level"),
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, CLICHE_PHRASES)


class PositiveWordTests(unittest.TestCase):
    def test_every_banned_word_flags(self):
        for word in sorted(CLICHE_WORDS):
            with self.subTest(word=word):
                text = "This wallet is %s for commuters." % word
                self.assertTrue(has_cliche(text), text)
                self.assertTrue(lint_cliches(text), text)

    def test_hyphenated_word_matches_space_form(self):
        cases = (
            ("game-changer", "A true game changer for travel."),
            ("game-changing", "A truly game changing design."),
            ("next-level", "Next level comfort daily."),
            ("cutting-edge", "A cutting edge steel frame."),
        )
        for canonical, text in cases:
            with self.subTest(text=text):
                self.assertIn(canonical, _cliches(text), text)

    def test_single_words_match_space_form(self):
        for text in (
            "We revolutionize carry.",
            "A revolutionary clasp.",
            "Unleash extra room.",
            "Elevate your desk setup.",
        ):
            with self.subTest(text=text):
                self.assertTrue(has_cliche(text), text)


class PositivePhraseTests(unittest.TestCase):
    def test_every_banned_phrase_flags(self):
        for phrase in CLICHE_PHRASES:
            with self.subTest(phrase=phrase):
                text = "Our wallet will %s, buy it now." % " ".join(phrase)
                self.assertTrue(has_cliche(text), text)
                self.assertIn(" ".join(phrase), _cliches(text), text)

    def test_unleash_your_potential(self):
        self.assertIn(
            "unleash your potential",
            _cliches("Unleash your potential with this bottle."),
        )

    def test_elevate_your_routine(self):
        self.assertIn(
            "elevate your routine",
            _cliches("Elevate your routine every morning."),
        )

    def test_take_to_the_next_level(self):
        hits = _cliches("Ready to take to the next level today.")
        self.assertIn("take to the next level", hits)
        self.assertIn("next level", hits)


class CaseAndPunctuationTests(unittest.TestCase):
    def test_case_insensitive(self):
        for text in (
            "GAME-CHANGER",
            "Game-Changer",
            "REVOLUTIONARY",
            "Miracle",
            "UNLEASH YOUR POTENTIAL",
            "Take To The Next Level",
        ):
            with self.subTest(text=text):
                self.assertTrue(has_cliche(text), text)

    def test_punctuation_boundaries(self):
        for text in (
            "(miracle)",
            "miracle!",
            '"revolutionary," she said.',
            "[supercharge] your day.",
            "Cutting-edge: steel frame.",
            "Next-level; comfort.",
            "Unleash your potential...",
        ):
            with self.subTest(text=text):
                self.assertTrue(has_cliche(text), text)

    def test_extra_whitespace_still_matches(self):
        self.assertTrue(has_cliche("A game   changer for travel."))
        self.assertIn(
            "game changer", _cliches("A game   changer for travel.")
        )


class NegativeTests(unittest.TestCase):
    def test_clean_copy_is_empty(self):
        for text in (
            "Full-grain leather wallet, 320 g, ships in two days.",
            "Steel frame, 1.2 kg, rated for 150 kg loads.",
            "Cotton canvas tote with brass zipper.",
            "",
            "   ",
        ):
            with self.subTest(text=text):
                self.assertEqual(lint_cliches(text), [])
                self.assertFalse(has_cliche(text))

    def test_non_string_input_is_empty(self):
        for value in (None, 123, ["miracle"], {"text": "miracle"}):
            with self.subTest(value=value):
                self.assertEqual(lint_cliches(value), [])
                self.assertFalse(has_cliche(value))

    def test_lone_words_are_clean(self):
        for text in (
            "The final level ships Friday.",
            "We stock board games downtown.",
            "Take the bus to the store.",
            "Your potential buyers love specs.",
            "Morning routine starts at six.",
        ):
            with self.subTest(text=text):
                self.assertFalse(has_cliche(text), text)

    def test_no_substring_false_positives(self):
        for text in (
            "Elevation gain is 400 m on this trail.",
            "Gameplay lasts about two hours.",
            "The elevator fits four people.",
            "Seamless stitching holds the strap.",
            "A miraculous detail in the liner.",
            "She redefined the schedule herself.",
            "Supercharged mornings start early.",
            "The unleashed dog ran ahead.",
        ):
            with self.subTest(text=text):
                self.assertFalse(has_cliche(text), text)

    def test_no_cross_sentence_phrase_false_positives(self):
        for text in (
            "Our favorite game. Changer cables cost $12.",
            "What comes next. Level the surface before gluing.",
            "Please take shirts to the next. Level the load evenly.",
        ):
            with self.subTest(text=text):
                self.assertFalse(has_cliche(text), text)


class HitShapeTests(unittest.TestCase):
    def test_hit_dict_keys_and_reason(self):
        hits = lint_cliches("A miracle game-changer for commuters.")
        self.assertTrue(hits)
        for hit in hits:
            with self.subTest(hit=hit):
                self.assertEqual(set(hit), {"cliche", "reason"})
                self.assertTrue(hit["cliche"])
                self.assertEqual(hit["reason"], EXPECTED_REASON)

    def test_deterministic_sorted_unique(self):
        text = "Miracle! A game-changer. MIRACLE, game changer again."
        first = lint_cliches(text)
        second = lint_cliches(text)
        self.assertEqual(first, second)
        matches = [hit["cliche"] for hit in first]
        self.assertEqual(matches, sorted(matches))
        self.assertEqual(len(matches), len(set(matches)))

    def test_repeated_word_deduped(self):
        hits = lint_cliches("Miracle upon miracle, we promise.")
        self.assertEqual([hit["cliche"] for hit in hits], ["miracle"])

    def test_has_cliche_matches_lint(self):
        for text in (
            "A miracle bottle.",
            "Leather wallet, ships Friday.",
            "",
            None,
        ):
            with self.subTest(text=text):
                self.assertEqual(has_cliche(text), bool(lint_cliches(text)))


class CleanTests(unittest.TestCase):
    def test_clean_copy_unchanged(self):
        for text in (
            "Full-grain leather wallet, ships in two days.",
            "Steel frame, 1.2 kg, rated for 150 kg loads.",
            "",
            "   ",
        ):
            with self.subTest(text=text):
                self.assertEqual(clean_cliches(text), text)

    def test_non_string_yields_empty_string(self):
        for value in (None, 123, ["miracle"]):
            with self.subTest(value=value):
                self.assertEqual(clean_cliches(value), "")

    def test_single_word_removed(self):
        result = clean_cliches("A miracle bottle for gym days.")
        self.assertIsInstance(result, str)
        self.assertNotIn("miracle", result.lower())
        self.assertIn(CLEAN_REPLACEMENT, result)
        self.assertFalse(has_cliche(result))

    def test_phrase_removed_as_one_span(self):
        result = clean_cliches("Unleash your potential with this bottle.")
        self.assertEqual(result.count(CLEAN_REPLACEMENT), 1)
        self.assertFalse(has_cliche(result))

    def test_overlapping_word_and_phrase_merge(self):
        result = clean_cliches("A true game-changer for travel.")
        self.assertEqual(result.count(CLEAN_REPLACEMENT), 1)
        self.assertFalse(has_cliche(result))

    def test_multiple_cliches_all_removed(self):
        text = "A revolutionary miracle. Supercharge daily carry."
        result = clean_cliches(text)
        self.assertEqual(result.count(CLEAN_REPLACEMENT), 3)
        self.assertFalse(has_cliche(result))

    def test_hyphen_and_space_forms_cleaned(self):
        for text in (
            "Next-level comfort daily.",
            "Next level comfort daily.",
            "Cutting-edge steel frame.",
            "Cutting edge steel frame.",
        ):
            with self.subTest(text=text):
                result = clean_cliches(text)
                self.assertFalse(has_cliche(result), text)
                self.assertIn(CLEAN_REPLACEMENT, result)


if __name__ == "__main__":
    unittest.main()
