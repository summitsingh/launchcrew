"""Meaningful tests for launchcrew.extra_crews (stdlib only)."""

import copy
import json
import unittest

from launchcrew import agents
from launchcrew import extra_crews

FACTS = {
    "approved_claims": [
        "100% vegan PU leather",
        "Designed in Texas",
        "Vegan leather wallet",
    ],
    "sources": ["owner brief", "workspace facts"],
}


def outcome_record(**overrides):
    record = {
        "channel": "email",
        "posted_date": "2026-01-15",
        "likes": 3,
        "comments": 2,
        "clicks": 1,
        "sales": 0,
        "note": "owner note",
        "provenance": "self_reported",
    }
    record.update(overrides)
    return record


def detected_photo(**overrides):
    photo = {
        "frame": (200, 200),
        "records": [
            {
                "frame": 0,
                "object_id": 1,
                "box": (50, 50, 120, 120, 200, 200),
                "mask": {
                    "x": 0,
                    "y": 0,
                    "height": 50,
                    "width": 50,
                    "encoding": "lossless",
                    "payload": "x",
                },
            }
        ],
        "photo_ref": "IMG_001",
    }
    photo.update(overrides)
    return photo


class ProfileSpineTests(unittest.TestCase):
    def test_four_profiles_validate(self):
        profiles = extra_crews.list_extra_crew_profiles()
        self.assertEqual(len(profiles), 4)
        names = sorted(p["name"].lower() for p in profiles)
        self.assertEqual(names, ["analyst", "designer", "research", "support"])

    def test_get_profile_returns_copy(self):
        first = extra_crews.get_extra_crew_profile("Support")
        first["role"] = "changed"
        second = extra_crews.get_extra_crew_profile("support")
        self.assertNotEqual(second["role"], "changed")

    def test_unknown_crew_rejected(self):
        with self.assertRaises(ValueError):
            extra_crews.get_extra_crew_profile("maker")
        with self.assertRaises(TypeError):
            extra_crews.get_extra_crew_profile(None)

    def test_zero_spend_and_approve_each(self):
        for profile in extra_crews.list_extra_crew_profiles():
            with self.subTest(crew=profile["name"]):
                agents.validate(profile)
                self.assertEqual(profile["spend_limit"], 0)
                self.assertNotIsInstance(profile["spend_limit"], bool)
                self.assertEqual(profile["approval_level"], "approve_each")

    def test_distinct_enforced_checker_policies(self):
        from launchcrew.checker_policies import parse_checker_agent

        expected = {
            "support": ["price_claims"],
            "designer": ["superlatives"],
            "analyst": ["cliches"],
            "research": ["custom:moonshot"],
        }
        seen = set()
        for crew, policies in expected.items():
            with self.subTest(crew=crew):
                profile = extra_crews.get_extra_crew_profile(crew)
                enforced = parse_checker_agent(profile)["enforced_policies"]
                self.assertEqual(enforced, policies)
                seen.add(tuple(enforced))
        self.assertEqual(len(seen), 4)

    def test_tools_limited_to_spine(self):
        for profile in extra_crews.list_extra_crew_profiles():
            with self.subTest(crew=profile["name"]):
                self.assertTrue(profile["tools_allowed"])
                self.assertTrue(set(profile["tools_allowed"]) <= agents.ALLOWED_TOOLS)

    def test_no_network_or_auto_approval_language(self):
        network_tokens = ("network", "http", "api", "web", "photo", "signup", "team")
        for profile in extra_crews.list_extra_crew_profiles():
            with self.subTest(crew=profile["name"]):
                tools = [t.lower() for t in profile["tools_allowed"]]
                for token in network_tokens:
                    for tool in tools:
                        self.assertNotIn(token, tool)
                blob = json.dumps(profile).lower()
                compact = "".join(c for c in blob if c.isalnum())
                self.assertNotIn("autoapprov", compact)
                combined = " ".join(
                    [
                        profile.get("role", ""),
                        profile.get("personality", ""),
                        profile.get("expertise", ""),
                        " ".join(profile.get("decision_rules", [])),
                    ]
                ).lower()
                self.assertIn("owner", combined)
                self.assertIn("checker", combined)
                self.assertIn("approval", combined)

    def test_no_demo_paths_in_live_guidance(self):
        for profile in extra_crews.list_extra_crew_profiles():
            with self.subTest(crew=profile["name"]):
                raw = json.dumps(profile).lower()
                self.assertNotIn("demo_facts", raw)
                self.assertNotIn("demo brand", raw)
                self.assertNotIn("demo_", raw)

    def test_no_personal_data(self):
        for profile in extra_crews.list_extra_crew_profiles():
            with self.subTest(crew=profile["name"]):
                raw = json.dumps(profile).lower()
                for token in ("@", "password", "credential", "secret"):
                    self.assertNotIn(token, raw)


class SupportTests(unittest.TestCase):
    def test_confirmed_claim_cited_and_unconfirmed_flagged(self):
        draft = extra_crews.draft_support_reply(
            "What is it made of?",
            ["100% vegan PU leather", "Free shipping worldwide"],
            FACTS,
        )
        self.assertEqual(draft["crew"], "support")
        self.assertEqual(draft["status"], "draft")
        self.assertFalse(draft["approved"])
        self.assertTrue(draft["requires_owner_confirmation"])
        self.assertTrue(draft["requires_checker_approval"])
        self.assertTrue(draft["needs_owner_input"])
        by_claim = {c["claim"]: c for c in draft["claims"]}
        self.assertTrue(by_claim["100% vegan PU leather"]["verified"])
        self.assertEqual(by_claim["100% vegan PU leather"]["source"], "facts_file")
        self.assertFalse(by_claim["Free shipping worldwide"]["verified"])
        self.assertEqual(by_claim["Free shipping worldwide"]["source"], "unverified")

    def test_empty_claims_ask_owner(self):
        draft = extra_crews.draft_support_reply("Question?", [], FACTS)
        self.assertTrue(draft["needs_owner_input"])
        self.assertEqual(draft["claims"], [])

    def test_bad_inputs_rejected(self):
        with self.assertRaises(ValueError):
            extra_crews.draft_support_reply("  ", ["x"], FACTS)
        with self.assertRaises(TypeError):
            extra_crews.draft_support_reply("q", "notalist", FACTS)
        with self.assertRaises(TypeError):
            extra_crews.draft_support_reply("q", ["x"], "notfacts")


class DesignerTests(unittest.TestCase):
    def test_grounded_advice_from_validated_geometry(self):
        result = extra_crews.suggest_designer_layout(
            detected_photo(), "center the wallet", "warm and plain"
        )
        self.assertEqual(result["crew"], "designer")
        self.assertTrue(result["words_only"])
        self.assertTrue(result["original_only"])
        self.assertTrue(result["geometry_grounded"])
        self.assertFalse(result["inspected_pixels"])
        self.assertFalse(result["generated_pixels"])
        self.assertFalse(result["processed_pixels"])
        self.assertFalse(result["approved"])
        self.assertTrue(result["requires_owner_confirmation"])
        self.assertTrue(result["requires_checker_approval"])
        self.assertFalse(result["needs_owner_input"])
        self.assertEqual(result["verdict"]["label"], "detected")
        self.assertIsNotNone(result["crop"])
        self.assertIn("supplied geometry data only", result["suggestion_text"])
        self.assertIn("no pixels were viewed", result["suggestion_text"].lower())
        self.assertIn(str(result["crop"]["x1"]), result["suggestion_text"])

    def test_missing_geometry_asks_owner(self):
        for photo in (
            detected_photo(records=[]),
            {"frame": (200, 200), "records": []},
            detected_photo(frame=None),
        ):
            with self.subTest(photo=photo):
                result = extra_crews.suggest_designer_layout(photo, "crop tight")
                self.assertTrue(result["needs_owner_input"])
                self.assertEqual(result["suggestion_text"], "")
                self.assertFalse(result["geometry_grounded"])
                self.assertFalse(result["generated_pixels"])

    def test_non_detected_verdict_asks_owner(self):
        touching = detected_photo()
        touching["records"] = [
            {
                "frame": 0,
                "object_id": 1,
                "box": (0, 0, 10, 10, 200, 200),
                "mask": {
                    "x": 0,
                    "y": 0,
                    "height": 10,
                    "width": 10,
                    "encoding": "lossless",
                    "payload": "x",
                },
            }
        ]
        result = extra_crews.suggest_designer_layout(touching, "crop tight")
        self.assertTrue(result["needs_owner_input"])
        self.assertEqual(result["suggestion_text"], "")
        self.assertIsNotNone(result["verdict"])

    def test_missing_request_note_asks_owner(self):
        result = extra_crews.suggest_designer_layout(detected_photo(), "   ")
        self.assertTrue(result["needs_owner_input"])
        self.assertEqual(result["suggestion_text"], "")

    def test_bare_label_never_establishes_geometry(self):
        with self.assertRaises(TypeError):
            extra_crews.suggest_designer_layout("IMG_001.jpg", "center the wallet")
        with self.assertRaises(TypeError):
            extra_crews.suggest_designer_layout(None, "center the wallet")
        with self.assertRaises(TypeError):
            extra_crews.suggest_designer_layout(detected_photo(), None)


class AnalystTests(unittest.TestCase):
    def test_restates_actual_multi_metric_records(self):
        entries = [
            outcome_record(),
            outcome_record(
                channel="x",
                posted_date="2026-01-16",
                likes=5,
                comments=4,
                clicks=3,
                sales=2,
                note="owner note two",
            ),
        ]
        summary = extra_crews.summarize_outcomes(entries)
        self.assertEqual(summary["crew"], "analyst")
        self.assertEqual(summary["entry_count"], 2)
        self.assertFalse(summary["approved"])
        self.assertFalse(summary["invented_metrics"])
        self.assertFalse(summary["computed_totals"])
        self.assertFalse(summary["needs_owner_input"])
        self.assertEqual(len(summary["points"]), 2)
        for point in summary["points"]:
            self.assertEqual(point["provenance"], "self_reported")
            self.assertEqual(point["entered_by"], "owner_entered")
            self.assertEqual(point["status"], "draft")
        self.assertIn("likes 3", summary["points"][0]["point"])
        self.assertIn("sales 2", summary["points"][1]["point"])
        self.assertIn("2026-01-16", summary["points"][1]["point"])

    def test_workspace_scoping_accepts_match(self):
        entries = [outcome_record(workspace_id="ws-one", run_id="run-one")]
        summary = extra_crews.summarize_outcomes(
            entries, workspace_id="ws-one", run_id="run-one"
        )
        self.assertFalse(summary["needs_owner_input"])
        self.assertEqual(summary["entry_count"], 1)

    def test_foreign_workspace_fails_closed(self):
        entries = [outcome_record(workspace_id="ws-one")]
        with self.assertRaises(ValueError):
            extra_crews.summarize_outcomes(entries, workspace_id="ws-two")
        with self.assertRaises(ValueError):
            extra_crews.summarize_outcomes(entries)

    def test_run_mismatch_fails_closed(self):
        entries = [outcome_record(run_id="run-one")]
        with self.assertRaises(ValueError):
            extra_crews.summarize_outcomes(entries, run_id="run-two")

    def test_invalid_metrics_fail_closed(self):
        for field in ("likes", "comments", "clicks", "sales"):
            for bad in (True, False, -1, 1000001, 1.5, "5", None):
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(ValueError):
                        extra_crews.summarize_outcomes([outcome_record(**{field: bad})])

    def test_invalid_dates_channels_notes_provenance_rejected(self):
        with self.assertRaises(ValueError):
            extra_crews.summarize_outcomes([outcome_record(posted_date="2026-02-30")])
        with self.assertRaises(ValueError):
            extra_crews.summarize_outcomes([outcome_record(channel="social")])
        with self.assertRaises(ValueError):
            extra_crews.summarize_outcomes([outcome_record(note="   ")])
        with self.assertRaises(ValueError):
            extra_crews.summarize_outcomes([outcome_record(provenance="measured")])
        with self.assertRaises(ValueError):
            extra_crews.summarize_outcomes([outcome_record(actor="demo_placeholder")])
        with self.assertRaises(ValueError):
            extra_crews.summarize_outcomes([outcome_record(entered_by="provider")])

    def test_legacy_count_shape_rejected_without_inventing_measures(self):
        legacy = {
            "channel": "email",
            "date": "2026-01-15",
            "count": 3,
            "note": "owner note",
            "provenance": "self_reported",
            "entered_by": "owner_entered",
        }
        with self.assertRaises(ValueError):
            extra_crews.summarize_outcomes([legacy])

    def test_empty_entries_ask_owner(self):
        summary = extra_crews.summarize_outcomes([])
        self.assertTrue(summary["needs_owner_input"])
        self.assertEqual(summary["points"], [])

    def test_non_dict_entry_rejected(self):
        with self.assertRaises(TypeError):
            extra_crews.summarize_outcomes("notalist")


class ResearchTests(unittest.TestCase):
    def test_source_kinds_stay_unconfirmed(self):
        result = extra_crews.suggest_research_facts(
            [
                {"text": "Designed in Texas", "source": "workspace facts"},
                {"text": "Ships to Mars", "source": "owner notebook"},
                "A plain string with no source",
            ],
            FACTS,
        )
        self.assertEqual(result["status"], "unconfirmed")
        self.assertFalse(result["approved"])
        self.assertTrue(result["requires_owner_confirmation"])
        self.assertTrue(result["requires_checker_approval"])
        self.assertEqual(len(result["suggestions"]), 3)
        for suggestion in result["suggestions"]:
            self.assertEqual(suggestion["status"], "unconfirmed")
            self.assertFalse(suggestion["verified"])
            self.assertFalse(suggestion["confirmed"])
            self.assertIn("no lookup", suggestion["note"].lower())
        by_text = {s["text"]: s for s in result["suggestions"]}
        self.assertEqual(
            by_text["Designed in Texas"]["source_kind"], "workspace_verified_reference"
        )
        self.assertEqual(
            by_text["Ships to Mars"]["source_kind"], "owner_supplied_reference"
        )
        self.assertEqual(
            by_text["A plain string with no source"]["source_kind"], "unsourced"
        )
        self.assertTrue(by_text["Designed in Texas"]["matched_confirmed_fact"])

    def test_empty_candidates_ask_owner(self):
        result = extra_crews.suggest_research_facts([], FACTS)
        self.assertTrue(result["needs_owner_input"])

    def test_bad_inputs_rejected(self):
        with self.assertRaises(TypeError):
            extra_crews.suggest_research_facts("notalist", FACTS)
        with self.assertRaises(TypeError):
            extra_crews.suggest_research_facts([123], FACTS)


if __name__ == "__main__":
    unittest.main()
