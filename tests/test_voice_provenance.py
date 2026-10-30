"""Behavioral tests for launchcrew.voice_provenance.

All fixtures are synthetic style-context references about gardens, trails,
and recipe cards. No real names, emails, account IDs, photos, secrets, or
personal data appear here. No Summit copy is used.
"""

import copy
import unittest

from launchcrew import voice_provenance
from launchcrew.voice_provenance import (
    UNKNOWN_VERSION,
    VOICE_STYLE_NOTICE,
    build_voice_provenance,
    format_voice_provenance_note,
    normalize_samples,
    normalize_version,
)


def _samples():
    return [
        {"id": "mem_garden", "title": "Synthetic garden voice"},
        {"id": "mem_trail", "title": "Synthetic trail voice"},
    ]


class NormalizeTests(unittest.TestCase):
    def test_normalize_keeps_id_and_title_only(self):
        entries = normalize_samples(
            [{"id": "mem_a", "title": "Synthetic garden voice",
              "content": "body text must not leak",
              "examples": [{"input": "x", "output": "y"}]}]
        )
        self.assertEqual(entries, [{"id": "mem_a", "title": "Synthetic garden voice"}])

    def test_normalize_skips_unusable_entries(self):
        entries = normalize_samples(
            ["not-a-dict", None, 42, {}, {"id": "  ", "title": ""},
             {"id": "mem_b", "title": None}]
        )
        self.assertEqual(entries, [{"id": "mem_b", "title": None}])

    def test_normalize_non_list_is_empty(self):
        self.assertEqual(normalize_samples(None), [])
        self.assertEqual(normalize_samples("mem_a"), [])
        self.assertEqual(normalize_samples({"id": "mem_a"}), [])

    def test_normalize_does_not_mutate_input(self):
        raw = _samples()
        snapshot = copy.deepcopy(raw)
        normalize_samples(raw)
        self.assertEqual(raw, snapshot)

    def test_version_passthrough_and_unknown(self):
        self.assertEqual(normalize_version("voice/v1:abc123"), "voice/v1:abc123")
        self.assertEqual(normalize_version("  voice/v1:abc123  "), "voice/v1:abc123")
        for missing in (None, "", "   ", 42, ["voice/v1:x"]):
            with self.subTest(missing=missing):
                self.assertEqual(normalize_version(missing), UNKNOWN_VERSION)


class BuildProvenanceTests(unittest.TestCase):
    def test_normal_case_reports_samples_and_version(self):
        record = build_voice_provenance(_samples(), "voice/v1:abc123")
        self.assertEqual(record["sample_count"], 2)
        self.assertTrue(record["has_voice"])
        self.assertEqual(record["snapshot_version"], "voice/v1:abc123")
        self.assertEqual(
            record["samples"],
            [{"id": "mem_garden", "title": "Synthetic garden voice"},
             {"id": "mem_trail", "title": "Synthetic trail voice"}],
        )
        self.assertIn("mem_garden", record["note"])
        self.assertIn("Synthetic trail voice", record["note"])
        self.assertIn("voice/v1:abc123", record["note"])

    def test_empty_samples_means_no_voice(self):
        for empty in ([], (), None):
            with self.subTest(empty=empty):
                record = build_voice_provenance(empty, "voice/v1:abc123")
                self.assertEqual(record["sample_count"], 0)
                self.assertEqual(record["samples"], [])
                self.assertFalse(record["has_voice"])
                self.assertIn("no voice samples were present", record["note"])
                self.assertIn("voice/v1:abc123", record["note"])

    def test_missing_version_is_unknown_never_invented(self):
        for missing in (None, "", "   ", 42):
            with self.subTest(missing=missing):
                record = build_voice_provenance(_samples(), missing)
                self.assertEqual(record["snapshot_version"], UNKNOWN_VERSION)
                self.assertIn(UNKNOWN_VERSION, record["note"])
                self.assertNotIn("None", record["note"])

    def test_empty_samples_and_missing_version(self):
        record = build_voice_provenance([], None)
        self.assertEqual(record["sample_count"], 0)
        self.assertFalse(record["has_voice"])
        self.assertEqual(record["snapshot_version"], UNKNOWN_VERSION)
        self.assertIn("no voice samples were present", record["note"])
        self.assertIn(UNKNOWN_VERSION, record["note"])

    def test_sample_body_text_never_leaks(self):
        record = build_voice_provenance(
            [{"id": "mem_a", "title": "Synthetic garden voice",
              "content": {"claim": "best in Texas"},
              "text": "secret body line"}],
            "voice/v1:abc123",
        )
        rendered = str(record)
        self.assertNotIn("best in Texas", rendered)
        self.assertNotIn("secret body line", rendered)

    def test_result_is_independent_copy(self):
        raw = _samples()
        record = build_voice_provenance(raw, "voice/v1:abc123")
        raw[0]["id"] = "mutated"
        record["samples"][0]["id"] = "edited"
        fresh = build_voice_provenance(
            [{"id": "mem_garden", "title": "Synthetic garden voice"}],
            "voice/v1:abc123",
        )
        self.assertEqual(fresh["samples"][0]["id"], "mem_garden")

    def test_deterministic_for_same_inputs(self):
        first = build_voice_provenance(_samples(), "voice/v1:abc123")
        second = build_voice_provenance(_samples(), "voice/v1:abc123")
        self.assertEqual(first, second)


class NoticeBoundaryTests(unittest.TestCase):
    def test_notice_states_style_context_never_fact_sources(self):
        for phrase in ("style context", "never fact sources"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, VOICE_STYLE_NOTICE)

    def test_every_note_carries_boundary(self):
        cases = [
            build_voice_provenance(_samples(), "voice/v1:abc123"),
            build_voice_provenance([], "voice/v1:abc123"),
            build_voice_provenance(_samples(), None),
            build_voice_provenance([], None),
        ]
        for record in cases:
            with self.subTest(record=record["note"]):
                self.assertEqual(record["notice"], VOICE_STYLE_NOTICE)
                for phrase in ("style context", "never fact sources"):
                    self.assertIn(phrase, record["note"])

    def test_format_helper_matches_build_note(self):
        self.assertEqual(
            format_voice_provenance_note(_samples(), "voice/v1:abc123"),
            build_voice_provenance(_samples(), "voice/v1:abc123")["note"],
        )
        self.assertIn(
            "no voice samples were present",
            format_voice_provenance_note([], None),
        )


if __name__ == "__main__":
    unittest.main()
