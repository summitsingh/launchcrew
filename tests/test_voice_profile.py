"""Behavioral tests for launchcrew.voice_profile.

All fixtures are synthetic style references. No real names, emails,
account IDs, photos, secrets, or personal data appear here.
"""

import unittest

from launchcrew import voice_profile


def _examples(count=3):
    topics = ("garden layout", "trail map", "recipe card", "shelf plan", "park sign")
    out = []
    for i in range(count):
        topic = topics[i % len(topics)]
        out.append(
            {
                "input": f"Synthetic draft {i + 1} about {topic}",
                "output": f"Synthetic revision {i + 1} about {topic}",
            }
        )
    return out


def _profile(count=3, banned_terms=None):
    payload = {"examples": _examples(count)}
    if banned_terms is not None:
        payload["banned_terms"] = banned_terms
    return payload


class ExampleCountTests(unittest.TestCase):
    def test_three_examples_accepted(self):
        snap = voice_profile.validate_profile(_profile(3))
        self.assertEqual(len(snap["examples"]), 3)

    def test_five_examples_accepted(self):
        snap = voice_profile.validate_profile(_profile(5))
        self.assertEqual(len(snap["examples"]), 5)

    def test_two_examples_rejected(self):
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(_profile(2))

    def test_six_examples_rejected(self):
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(_profile(6))


class LengthBoundTests(unittest.TestCase):
    def test_overlong_input_rejected(self):
        payload = _profile(3)
        payload["examples"][0]["input"] = "q" * (voice_profile.MAX_INPUT_CHARS + 1)
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(payload)

    def test_overlong_output_rejected(self):
        payload = _profile(3)
        payload["examples"][1]["output"] = "z" * (voice_profile.MAX_OUTPUT_CHARS + 1)
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(payload)

    def test_overlong_total_rejected(self):
        # Five individually valid examples whose aggregate exceeds the cap.
        per_input = 800
        per_output = 801
        payload = {
            "examples": [
                {"input": "a" * per_input, "output": "b" * per_output}
                for _ in range(5)
            ]
        }
        total = 5 * (per_input + per_output)
        self.assertGreater(total, voice_profile.MAX_TOTAL_CHARS)
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(payload)

    def test_overlong_candidate_rejected(self):
        snap = voice_profile.validate_profile(_profile(3, banned_terms=["alder"]))
        with self.assertRaises(ValueError):
            voice_profile.check_text(
                snap, "w" * (voice_profile.MAX_CANDIDATE_CHARS + 1)
            )


class MalformedShapeTests(unittest.TestCase):
    def test_non_dict_profile_rejected(self):
        with self.assertRaises(TypeError):
            voice_profile.validate_profile([])

    def test_missing_examples_rejected(self):
        with self.assertRaises(ValueError):
            voice_profile.validate_profile({"banned_terms": []})

    def test_unknown_top_level_key_rejected(self):
        payload = _profile(3)
        payload["owner"] = "synthetic"
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(payload)

    def test_example_with_missing_key_rejected(self):
        payload = _profile(3)
        payload["examples"][0] = {"input": "Synthetic draft about pond"}
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(payload)

    def test_example_with_extra_key_rejected(self):
        payload = _profile(3)
        payload["examples"][0] = {
            "input": "Synthetic draft about pond",
            "output": "Synthetic revision about pond",
            "label": "extra",
        }
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(payload)

    def test_non_string_example_field_rejected(self):
        payload = _profile(3)
        payload["examples"][0]["output"] = 42
        with self.assertRaises(TypeError):
            voice_profile.validate_profile(payload)

    def test_empty_example_field_rejected(self):
        payload = _profile(3)
        payload["examples"][0]["input"] = "   "
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(payload)

    def test_non_list_banned_terms_rejected(self):
        with self.assertRaises(TypeError):
            voice_profile.validate_profile(_profile(3, banned_terms="alder"))

    def test_non_string_banned_term_rejected(self):
        with self.assertRaises(TypeError):
            voice_profile.validate_profile(_profile(3, banned_terms=[17]))

    def test_empty_and_punctuation_terms_rejected(self):
        for bad in ("", "   ", "!!!", "...", "--"):
            with self.subTest(term=bad), self.assertRaises(ValueError):
                voice_profile.validate_profile(_profile(3, banned_terms=[bad]))

    def test_too_many_banned_terms_rejected(self):
        many = [f"term{i}" for i in range(voice_profile.MAX_BANNED_TERMS + 1)]
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(_profile(3, banned_terms=many))

    def test_overlong_banned_term_rejected(self):
        long_term = "k" * (voice_profile.MAX_TERM_CHARS + 1)
        with self.assertRaises(ValueError):
            voice_profile.validate_profile(_profile(3, banned_terms=[long_term]))

    def test_malformed_snapshot_rejected_by_check(self):
        with self.assertRaises(TypeError):
            voice_profile.check_text([], "Synthetic candidate about garden")
        with self.assertRaises(ValueError):
            voice_profile.check_text({}, "Synthetic candidate about garden")
        with self.assertRaises(TypeError):
            voice_profile.check_text(
                {"banned_terms": ["alder"]}, b"bytes are not text"
            )


class MatchingBehaviorTests(unittest.TestCase):
    def test_casefold_matching(self):
        snap = voice_profile.validate_profile(
            _profile(3, banned_terms=["harbor"])
        )
        result = voice_profile.check_text(snap, "Visit the HARBOR at noon.")
        self.assertTrue(result["blocked"])
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["term"], "harbor")

    def test_unicode_casefold_matching(self):
        snap = voice_profile.validate_profile(
            _profile(3, banned_terms=["strasse"])
        )
        result = voice_profile.check_text(snap, "Walk along the Stra\u00dfe path.")
        self.assertTrue(result["blocked"])

    def test_substring_inside_larger_word_not_blocked(self):
        snap = voice_profile.validate_profile(_profile(3, banned_terms=["art"]))
        result = voice_profile.check_text(snap, "The earth and artist part ways.")
        self.assertFalse(result["blocked"])
        self.assertEqual(result["matches"], [])

    def test_whole_word_match_blocks(self):
        snap = voice_profile.validate_profile(_profile(3, banned_terms=["art"]))
        result = voice_profile.check_text(snap, "A short art note.")
        self.assertTrue(result["blocked"])
        self.assertEqual(result["matches"][0]["count"], 1)

    def test_multiword_phrase_match(self):
        snap = voice_profile.validate_profile(
            _profile(3, banned_terms=["quick brown"])
        )
        result = voice_profile.check_text(snap, "The quick brown fox rests.")
        self.assertTrue(result["blocked"])

    def test_multiword_with_extra_whitespace_matches(self):
        snap = voice_profile.validate_profile(
            _profile(3, banned_terms=["quick brown"])
        )
        for candidate in ("quick  brown fox", "quick\nbrown fox"):
            with self.subTest(candidate=candidate):
                result = voice_profile.check_text(snap, candidate)
                self.assertTrue(result["blocked"])

    def test_punctuation_boundaries_match(self):
        snap = voice_profile.validate_profile(
            _profile(3, banned_terms=["hello"])
        )
        result = voice_profile.check_text(snap, "Well, hello (hello).")
        self.assertTrue(result["blocked"])
        self.assertEqual(result["matches"][0]["count"], 2)

    def test_multiword_with_punctuation_separator_matches(self):
        snap = voice_profile.validate_profile(
            _profile(3, banned_terms=["foo bar"])
        )
        for candidate in ("foo, bar and more", "foo-bar and more"):
            with self.subTest(candidate=candidate):
                result = voice_profile.check_text(snap, candidate)
                self.assertTrue(result["blocked"])

    def test_no_banned_terms_never_blocks(self):
        snap = voice_profile.validate_profile(_profile(3))
        result = voice_profile.check_text(snap, "Any synthetic candidate passes.")
        self.assertFalse(result["blocked"])
        self.assertEqual(result["matches"], [])


class DeterminismTests(unittest.TestCase):
    def test_repeated_checks_are_equal(self):
        snap = voice_profile.validate_profile(
            _profile(3, banned_terms=["zebra", "apple"])
        )
        first = voice_profile.check_text(snap, "Apple and ZEBRA meet apple again.")
        second = voice_profile.check_text(snap, "Apple and ZEBRA meet apple again.")
        self.assertEqual(first, second)

    def test_banned_term_order_does_not_change_result(self):
        first = voice_profile.validate_profile(
            _profile(3, banned_terms=["zebra", "apple"])
        )
        second = voice_profile.validate_profile(
            _profile(3, banned_terms=["apple", "zebra"])
        )
        self.assertEqual(first["banned_terms"], second["banned_terms"])
        candidate = "Apple near zebra."
        self.assertEqual(
            voice_profile.check_text(first, candidate),
            voice_profile.check_text(second, candidate),
        )

    def test_matches_sorted_stably(self):
        snap = voice_profile.validate_profile(
            _profile(3, banned_terms=["zebra", "apple", "mango"])
        )
        result = voice_profile.check_text(snap, "zebra mango apple")
        terms = [m["term"] for m in result["matches"]]
        self.assertEqual(terms, sorted(terms, key=str.casefold))


class StyleOnlyMetadataTests(unittest.TestCase):
    def test_snapshot_carries_style_only_notice(self):
        snap = voice_profile.validate_profile(_profile(3))
        self.assertTrue(snap["meta"]["style_only"])
        notice = snap["meta"]["notice"]
        for phrase in (
            "style references only",
            "never factual",
            "never bypass Checker",
            "never become confirmed facts",
        ):
            self.assertIn(phrase, notice)

    def test_check_result_carries_notice_and_hides_private_data(self):
        snap = voice_profile.validate_profile(
            _profile(3, banned_terms=["alder"])
        )
        candidate = "Synthetic candidate about alder grove layout plan"
        result = voice_profile.check_text(snap, candidate)
        self.assertIn("style references only", result["notice"])
        self.assertNotIn("examples", result)
        self.assertNotIn(candidate, str(result))

    def test_snapshot_is_independent_copy(self):
        payload = _profile(3, banned_terms=["alder"])
        snap = voice_profile.validate_profile(payload)
        payload["examples"][0]["input"] = "Mutated after validation"
        payload["banned_terms"].append("birch")
        self.assertNotEqual(
            snap["examples"][0]["input"], "Mutated after validation"
        )
        self.assertEqual(snap["banned_terms"], ["alder"])


if __name__ == "__main__":
    unittest.main()
