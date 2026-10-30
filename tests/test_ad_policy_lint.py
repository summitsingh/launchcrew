"""Slice 4 ad policy lint: positive and negative cases.

New-file-only coverage for launchcrew/ad_policy_lint.py. Stdlib
unittest, no I/O, no model calls.
"""

import unittest

from launchcrew.ad_policy_lint import (
    AD_POLICY_LINT_VERSION,
    ad_policy_blocks,
    lint_ad_policy,
)


def _matches(text):
    return {(hit["category"], hit["match"]) for hit in lint_ad_policy(text)}


class AdPolicyLintVersionTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(AD_POLICY_LINT_VERSION, "ad-policy/v1")


class AbsoluteClaimTests(unittest.TestCase):
    def test_guaranteed_family(self):
        for text in (
            "Guaranteed results!",
            "We guarantee it works.",
            "Our guarantees cover shipping.",
        ):
            with self.subTest(text=text):
                hits = lint_ad_policy(text)
                self.assertTrue(hits, text)
                self.assertTrue(
                    all(h["category"] == "absolute_claim" for h in hits)
                )

    def test_always_never(self):
        self.assertIn(
            ("absolute_claim", "always"), _matches("It always works.")
        )
        self.assertIn(
            ("absolute_claim", "never"), _matches("You will never wait.")
        )

    def test_risk_phrases(self):
        self.assertIn(
            ("absolute_claim", "risk free"), _matches("Risk free trial.")
        )
        self.assertIn(
            ("absolute_claim", "no risk"), _matches("No-risk purchase.")
        )
        self.assertIn(
            ("absolute_claim", "zero risk"), _matches("Zero risk offer.")
        )

    def test_percent_form(self):
        self.assertIn(
            ("absolute_claim", "100%"), _matches("100% effective.")
        )
        self.assertIn(
            ("absolute_claim", "100 percent"),
            _matches("100 percent effective."),
        )

    def test_case_and_punctuation_boundaries(self):
        for text in ("GUARANTEED", "(guaranteed)", "overnight!", "MIRACLE?"):
            with self.subTest(text=text):
                self.assertTrue(ad_policy_blocks(text), text)

    def test_no_substring_false_positives(self):
        for text in (
            "Whenever possible we ship fast.",
            "A guaranteedx return policy.",
            "Disguaranteed items only.",
            "The $100 price is final.",
            "Save 100 dollars today.",
        ):
            with self.subTest(text=text):
                self.assertFalse(ad_policy_blocks(text), text)

    def test_no_cross_sentence_phrase_false_positives(self):
        for text in (
            "No. Risk is low with this wallet.",
            "Zero. Risk was audited last year.",
            "Risk. Free samples while they last.",
        ):
            with self.subTest(text=text):
                self.assertFalse(ad_policy_blocks(text), text)


class PersonalAttributeTests(unittest.TestCase):
    def test_second_person_phrasing(self):
        self.assertIn(
            ("personal_attribute", "you are"),
            _matches("You are tired every morning."),
        )
        self.assertIn(
            ("personal_attribute", "you re"),
            _matches("You're a busy commuter."),
        )
        self.assertIn(
            ("personal_attribute", "are you"),
            _matches("Are you struggling with bills?"),
        )
        self.assertIn(
            ("personal_attribute", "do you"),
            _matches("Do you suffer from back pain?"),
        )

    def test_your_noun(self):
        self.assertIn(
            ("personal_attribute", "your age"),
            _matches("At your age, comfort matters."),
        )
        self.assertIn(
            ("personal_attribute", "your weight"),
            _matches("Track your weight daily."),
        )

    def test_lone_you_is_clean(self):
        for text in (
            "Made for you.",
            "Designed for young professionals.",
            "Your wallet, your rules.",
        ):
            with self.subTest(text=text):
                self.assertFalse(ad_policy_blocks(text), text)

    def test_no_substring_false_positives(self):
        for text in (
            "Do your best work here.",
            "Yourself included in the offer.",
            "Young commuters love this.",
        ):
            with self.subTest(text=text):
                self.assertFalse(ad_policy_blocks(text), text)


class ShamingComparisonTests(unittest.TestCase):
    def test_shaming_words(self):
        self.assertIn(
            ("shaming_comparison", "ugly"),
            _matches("That old wallet is ugly."),
        )
        self.assertIn(
            ("shaming_comparison", "loser"),
            _matches("Don't be a loser."),
        )

    def test_comparison_phrases(self):
        self.assertIn(
            ("shaming_comparison", "better than"),
            _matches("Better than the rest."),
        )
        self.assertIn(
            ("shaming_comparison", "worse than"),
            _matches("Worse than carrying cash loose."),
        )

    def test_dont_be_trigram(self):
        self.assertIn(
            ("shaming_comparison", "don't be"),
            _matches("Don't be late again."),
        )
        self.assertIn(
            ("shaming_comparison", "don't be"),
            _matches("Do not be late again."),
        )

    def test_bare_comparative_is_clean(self):
        for text in (
            "Better luck next time.",
            "A better wallet for commuters.",
            "Tasteful design for daily use.",
        ):
            with self.subTest(text=text):
                self.assertFalse(ad_policy_blocks(text), text)

    def test_no_cross_sentence_phrase_false_positives(self):
        self.assertFalse(
            ad_policy_blocks("Better. Than ever before."))

    def test_no_substring_false_positives(self):
        for text in (
            "Ugliness is in the eye of the beholder.",
            "The closers sealed the deal.",
        ):
            with self.subTest(text=text):
                self.assertFalse(ad_policy_blocks(text), text)


class HitShapeTests(unittest.TestCase):
    def test_hit_dict_has_per_hit_reason(self):
        hits = lint_ad_policy("Guaranteed results for you.")
        self.assertTrue(hits)
        for hit in hits:
            with self.subTest(hit=hit):
                self.assertIn(hit["category"], {
                    "absolute_claim",
                    "personal_attribute",
                    "shaming_comparison",
                })
                self.assertTrue(hit["match"])
                self.assertIn(hit["match"], hit["reason"])
                self.assertIn(hit["category"], hit["reason"])

    def test_deterministic_sorted_unique(self):
        text = "Guaranteed! Better than the rest. GUARANTEED, better than ever."
        first = lint_ad_policy(text)
        second = lint_ad_policy(text)
        self.assertEqual(first, second)
        keys = [(h["category"], h["match"]) for h in first]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))

    def test_clean_copy_is_empty(self):
        for text in (
            "Leather wallet, $49, designed in Texas.",
            "Full-grain leather. Ships in two days.",
            "",
            "   ",
        ):
            with self.subTest(text=text):
                self.assertEqual(lint_ad_policy(text), [])
                self.assertFalse(ad_policy_blocks(text))

    def test_non_string_input_is_empty(self):
        for value in (None, 123, ["guaranteed"], {"text": "guaranteed"}):
            with self.subTest(value=value):
                self.assertEqual(lint_ad_policy(value), [])
                self.assertFalse(ad_policy_blocks(value))

    def test_all_three_categories_together(self):
        hits = lint_ad_policy(
            "Guaranteed comfort. You are tired. Better than the rest."
        )
        categories = {hit["category"] for hit in hits}
        self.assertEqual(
            categories,
            {"absolute_claim", "personal_attribute", "shaming_comparison"},
        )


if __name__ == "__main__":
    unittest.main()
