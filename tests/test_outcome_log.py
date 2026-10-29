"""Focused unittest suite for launchcrew.outcome_log (standard library only)."""

import json
import unittest

from launchcrew import outcome_log
from launchcrew.outcome_log import log_outcome

EXPECTED_ENTRY_KEYS = frozenset({
    "channel", "date", "count", "note", "provenance", "entered_by",
})

# Tokens an accepted owner-entered entry must never fabricate as proof.
FORBIDDEN_PROOF_TOKENS = (
    "measured",
    "verified",
    "provider",
    "auto-confirm",
    "auto_confirm",
    "auto confirmed",
)


class AcceptedBoundaryTests(unittest.TestCase):
    def test_accepted_minimal_boundaries(self):
        result = log_outcome("email", "2026-01-15", 0, "x")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["errors"], {})
        entry = result["entry"]
        self.assertEqual(entry["channel"], "email")
        self.assertEqual(entry["date"], "2026-01-15")
        self.assertEqual(entry["count"], 0)
        self.assertEqual(entry["note"], "x")

    def test_accepted_max_boundaries(self):
        note = "n" * 500
        result = log_outcome("web", "2026-12-31", 1000000, note)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["errors"], {})
        self.assertEqual(result["entry"]["count"], 1000000)
        self.assertEqual(result["entry"]["note"], note)

    def test_accepted_leap_day(self):
        result = log_outcome("sms", "2024-02-29", 3, "leap day count")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["entry"]["date"], "2024-02-29")

    def test_accepted_every_known_channel(self):
        self.assertGreaterEqual(len(outcome_log.KNOWN_CHANNELS), 1)
        for channel in sorted(outcome_log.KNOWN_CHANNELS):
            with self.subTest(channel=channel):
                result = log_outcome(channel, "2026-06-01", 1, "owner note")
                self.assertTrue(result["accepted"])
                self.assertEqual(result["entry"]["channel"], channel)

    def test_entry_keys_exact(self):
        result = log_outcome("phone", "2026-03-10", 7, "owner note")
        self.assertTrue(result["accepted"])
        self.assertEqual(frozenset(result["entry"].keys()), EXPECTED_ENTRY_KEYS)


class RejectedInputTests(unittest.TestCase):
    def assertRejected(self, channel, date, count, note, *fields):
        result = log_outcome(channel, date, count, note)
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["entry"])
        self.assertGreaterEqual(len(result["errors"]), 1)
        for field in fields:
            self.assertIn(field, result["errors"])
        return result

    def test_rejected_unknown_channel(self):
        self.assertRejected("billboard", "2026-01-15", 1, "owner note", "channel")

    def test_rejected_channel_case_padding_and_empty(self):
        for bad in ("Email", "EMAIL", " email", "email ", "", "   "):
            with self.subTest(channel=bad):
                self.assertRejected(bad, "2026-01-15", 1, "owner note", "channel")

    def test_rejected_channel_non_string(self):
        for bad in (None, 123, True, ["email"], {"channel": "email"}):
            with self.subTest(channel=bad):
                self.assertRejected(bad, "2026-01-15", 1, "owner note", "channel")

    def test_rejected_malformed_dates(self):
        bad_dates = [
            "",
            "2026-1-1",
            "26-01-01",
            "2026/01/01",
            "2026-01-01T00:00:00",
            "2026-01-01 ",
            " 2026-01-01",
            "2026-13-01",
            "2026-00-10",
            "2026-01-00",
            "2026-01-32",
            "2026-02-30",
            "2026-02-29",  # 2026 is not a leap year
            "abcd-ef-gh",
        ]
        for bad in bad_dates:
            with self.subTest(date=bad):
                self.assertRejected("email", bad, 1, "owner note", "date")

    def test_rejected_date_non_string(self):
        for bad in (None, 20260101, True, ["2026-01-15"]):
            with self.subTest(date=bad):
                self.assertRejected("email", bad, 1, "owner note", "date")

    def test_rejected_count_booleans(self):
        self.assertRejected("email", "2026-01-15", True, "owner note", "count")
        self.assertRejected("email", "2026-01-15", False, "owner note", "count")

    def test_rejected_count_bounds_and_types(self):
        for bad in (-1, -100, 1000001, 2000000, 1.0, 1.5, "5", None, [1]):
            with self.subTest(count=bad):
                self.assertRejected("email", "2026-01-15", bad, "owner note", "count")

    def test_rejected_note_empty_and_whitespace(self):
        for bad in ("", "   ", "\t  ", " \r\n "):
            with self.subTest(note=repr(bad)):
                self.assertRejected("email", "2026-01-15", 1, bad, "note")

    def test_rejected_note_overlong(self):
        self.assertRejected("email", "2026-01-15", 1, "x" * 501, "note")

    def test_rejected_note_unsafe_control_characters(self):
        for bad in ("line1\nline2", "tab\there", "ret\rhere", "nul\x00here",
                    "esc\x1bhere", "del\x7fhere", "bell\x07here"):
            with self.subTest(note=repr(bad)):
                self.assertRejected("email", "2026-01-15", 1, bad, "note")

    def test_rejected_note_non_string(self):
        for bad in (None, 123, True, ["note"]):
            with self.subTest(note=bad):
                self.assertRejected("email", "2026-01-15", 1, bad, "note")

    def test_fail_closed_reports_every_invalid_field(self):
        result = self.assertRejected("nope", "not-a-date", -5, "", "channel", "date", "count", "note")
        self.assertEqual(set(result["errors"].keys()), {"channel", "date", "count", "note"})

    def test_valid_fields_absent_from_errors(self):
        result = log_outcome("email", "not-a-date", 1, "owner note")
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["entry"])
        self.assertEqual(set(result["errors"].keys()), {"date"})


class PlatformChannelTests(unittest.TestCase):
    PLATFORM_CHANNELS = ("x", "linkedin", "instagram", "facebook")

    def test_accepted_all_four_platform_channels(self):
        for channel in self.PLATFORM_CHANNELS:
            with self.subTest(channel=channel):
                result = log_outcome(channel, "2026-06-01", 1, "owner note")
                self.assertTrue(result["accepted"])
                self.assertEqual(result["errors"], {})
                self.assertEqual(result["entry"]["channel"], channel)

    def test_rejected_generic_social(self):
        result = log_outcome("social", "2026-06-01", 1, "owner note")
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["entry"])
        self.assertIn("channel", result["errors"])

    def test_rejected_unknown_platforms(self):
        for bad in ("tiktok", "youtube", "twitter", "threads",
                    "snapchat", "bluesky", "pinterest"):
            with self.subTest(channel=bad):
                result = log_outcome(bad, "2026-06-01", 1, "owner note")
                self.assertFalse(result["accepted"])
                self.assertIsNone(result["entry"])
                self.assertIn("channel", result["errors"])

    def test_rejected_platform_near_misses(self):
        for bad in ("X", "LinkedIn", "LINKEDIN", "Instagram", "INSTAGRAM",
                    "Facebook", "FACEBOOK", "fb", "FB", "ig", "IG",
                    "insta", "linked_in", "face_book", " x", "x ",
                    "linkedin ", " instagram", "x.com"):
            with self.subTest(channel=bad):
                result = log_outcome(bad, "2026-06-01", 1, "owner note")
                self.assertFalse(result["accepted"])
                self.assertIsNone(result["entry"])
                self.assertIn("channel", result["errors"])


class DeterminismAndProvenanceTests(unittest.TestCase):
    def test_deterministic_equal_inputs_equal_outputs(self):
        first = log_outcome("x", "2026-05-20", 42, "owner count for the day")
        second = log_outcome("x", "2026-05-20", 42, "owner count for the day")
        self.assertEqual(first, second)

    def test_provenance_explicit_owner_entered(self):
        result = log_outcome("in_person", "2026-07-04", 9, "owner count for the day")
        self.assertTrue(result["accepted"])
        entry = result["entry"]
        self.assertEqual(entry["provenance"], "self_reported")
        self.assertEqual(entry["entered_by"], "owner_entered")

    def test_no_fabricated_provider_proof(self):
        result = log_outcome("other", "2026-08-11", 2, "owner count for the day")
        self.assertTrue(result["accepted"])
        serialized = json.dumps(result["entry"], sort_keys=True).lower()
        for token in FORBIDDEN_PROOF_TOKENS:
            self.assertNotIn(token, serialized)

    def test_no_timestamp_or_id_keys(self):
        result = log_outcome("web", "2026-09-09", 4, "owner count for the day")
        self.assertTrue(result["accepted"])
        for key in ("generated_at", "timestamp", "created_at", "id", "run_id"):
            self.assertNotIn(key, result["entry"])

    def test_inputs_preserved_verbatim(self):
        note = "  padded owner note  "
        result = log_outcome("email", "2026-10-01", 5, note)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["entry"]["note"], note)
        self.assertEqual(result["inputs"],
                         {"channel": "email", "date": "2026-10-01", "count": 5, "note": note})

    def test_inputs_preserved_on_rejection(self):
        result = log_outcome("nope", "2026-01-15", 1, "owner note")
        self.assertFalse(result["accepted"])
        self.assertEqual(result["inputs"],
                         {"channel": "nope", "date": "2026-01-15", "count": 1, "note": "owner note"})

    def test_date_has_no_default(self):
        with self.assertRaises(TypeError):
            log_outcome("email", count=1, note="owner note")


if __name__ == "__main__":
    unittest.main()
