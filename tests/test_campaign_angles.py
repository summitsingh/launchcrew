"""Focused checks for the five additional campaign angles.

Hand-built fixtures only. No model calls, no network, no live proof.
"""
import copy
import unittest

from launchcrew.campaign_angles import (
    ADDITIONAL_ANGLES,
    EXISTING_ANGLES,
    HOOK_MAX_CHARS,
    get_angle_detail,
    list_additional_angles,
    render_all_angles,
    render_angle,
    validate_hook,
)

FULL_FACTS = {
    "product": "Vegan leather wallet",
    "material": "100% vegan PU leather",
    "price": "$49",
    "design": "Designed in Texas",
    "gift_use": "Gift wrap available",
    "workday_use": "Fits a laptop",
    "weekend_use": "Fits weekend essentials",
    "repair_note": "Repair kit included",
    "founder_note": "Founder approved",
}


class CampaignAngleTests(unittest.TestCase):
    def test_five_angles_beyond_existing_seven(self):
        angles = list_additional_angles()
        self.assertEqual(tuple(angles), ADDITIONAL_ANGLES)
        self.assertEqual(len(angles), 5)
        self.assertEqual(len(set(angles)), 5)
        self.assertEqual(len(EXISTING_ANGLES), 7)
        for name in angles:
            self.assertNotIn(name, EXISTING_ANGLES)

    def test_brief_and_hook_templates_are_distinct(self):
        briefs = set()
        hooks = set()
        banned = ("best", "perfect", "amazing", "incredible", "revolutionary", "guaranteed")
        for name in list_additional_angles():
            detail = get_angle_detail(name)
            briefs.add(detail["brief_template"])
            hooks.add(detail["hook_template"])
            self.assertIn("{", detail["brief_template"])
            self.assertIn("{", detail["hook_template"])
            lowered = (detail["brief_template"] + detail["hook_template"]).lower()
            for word in banned:
                self.assertNotIn(word, lowered)
        self.assertEqual(len(briefs), 5)
        self.assertEqual(len(hooks), 5)

    def test_ready_hooks_fit_140_and_use_only_confirmed_facts(self):
        packed = render_all_angles(dict(FULL_FACTS))
        self.assertEqual(list(packed["angles"]), list(ADDITIONAL_ANGLES))
        seen_hooks = set()
        for name in ADDITIONAL_ANGLES:
            rendered = packed["angles"][name]
            self.assertEqual(rendered["status"], "ready")
            self.assertIsNotNone(rendered["hook"])
            self.assertIsNotNone(rendered["brief"])
            self.assertLessEqual(len(rendered["hook"]), 140)
            self.assertLessEqual(len(rendered["hook"]), HOOK_MAX_CHARS)
            self.assertLessEqual(len(rendered["brief"]), 280)
            self.assertNotIn("{", rendered["hook"])
            self.assertNotIn("{", rendered["brief"])
            self.assertTrue(validate_hook(rendered["hook"])["ok"])
            seen_hooks.add(rendered["hook"])
        self.assertEqual(len(seen_hooks), 5)

    def test_missing_fact_returns_suggestion_without_invention(self):
        rendered = render_angle("Gift ready", {"product": "Vegan leather wallet"})
        self.assertEqual(rendered["status"], "needs_owner_confirmation")
        self.assertEqual(rendered["state"], "suggestion")
        self.assertIsNone(rendered["brief"])
        self.assertIsNone(rendered["hook"])
        self.assertIn("price", rendered["missing_facts"])
        self.assertIn("price", rendered["suggestion"])
        self.assertIn("confirmation", rendered["suggestion"].lower())
        self.assertNotIn("$", str(rendered))

    def test_no_material_value_without_confirmation(self):
        facts = {"product": "Vegan leather wallet", "design": "Designed in Texas"}
        rendered = render_angle("Weekend carry", facts)
        self.assertEqual(rendered["status"], "needs_owner_confirmation")
        self.assertIsNone(rendered["brief"])
        self.assertIsNone(rendered["hook"])
        blob = str(rendered)
        self.assertNotIn("100%", blob)
        self.assertNotIn("vegan PU", blob)
        self.assertNotIn("$", blob)

    def test_extra_caller_keys_are_not_rendered(self):
        facts = dict(FULL_FACTS)
        facts["extra"] = "Mars base"
        rendered = render_angle("Gift ready", facts)
        self.assertEqual(rendered["status"], "ready")
        self.assertNotIn("Mars", rendered["brief"])
        self.assertNotIn("Mars", rendered["hook"])
        self.assertIn("$49", rendered["hook"])
        self.assertIn("Vegan leather wallet", rendered["hook"])

    def test_non_dict_facts_need_owner_confirmation(self):
        rendered = render_angle("Gift ready", ["Vegan leather wallet", "$49"])
        self.assertEqual(rendered["status"], "needs_owner_confirmation")
        self.assertEqual(rendered["state"], "suggestion")
        self.assertIsNone(rendered["brief"])
        self.assertIsNone(rendered["hook"])

    def test_unknown_angle_is_rejected(self):
        with self.assertRaises(ValueError):
            render_angle("Unknown angle", dict(FULL_FACTS))
        with self.assertRaises(ValueError):
            get_angle_detail("Unknown angle")

    def test_hook_validator_boundaries(self):
        exact = "H" * 139 + "."
        self.assertEqual(len(exact), 140)
        self.assertTrue(validate_hook(exact)["ok"])
        over = "H" * 140 + "."
        self.assertEqual(len(over), 141)
        failed = validate_hook(over)
        self.assertFalse(failed["ok"])
        self.assertTrue(any("140" in r for r in failed["reasons"]))
        self.assertFalse(validate_hook("Hello\nWorld")["ok"])
        self.assertFalse(validate_hook("Gift {product}")["ok"])
        self.assertFalse(validate_hook("   ")["ok"])

    def test_repeat_calls_are_deterministic(self):
        first = render_all_angles(dict(FULL_FACTS))
        second = render_all_angles(dict(FULL_FACTS))
        self.assertEqual(first, second)
        one = render_angle("Founder note", dict(FULL_FACTS))
        two = render_angle("Founder note", dict(FULL_FACTS))
        self.assertEqual(one, two)

    def test_caller_inputs_are_unchanged(self):
        facts = dict(FULL_FACTS)
        snapshot = copy.deepcopy(facts)
        render_angle("Gift ready", facts)
        render_all_angles(facts)
        self.assertEqual(facts, snapshot)

    def test_use_claims_require_explicit_confirmation(self):
        base = {
            "product": "Vegan leather wallet",
            "material": "100% vegan PU leather",
            "price": "$49",
            "design": "Designed in Texas",
        }
        expected_missing = {
            "Gift ready": "gift_use",
            "Workday carry": "workday_use",
            "Weekend carry": "weekend_use",
            "Repair and reuse": "repair_note",
            "Founder note": "founder_note",
        }
        for name in ADDITIONAL_ANGLES:
            rendered = render_angle(name, dict(base))
            self.assertEqual(rendered["status"], "needs_owner_confirmation")
            self.assertEqual(rendered["state"], "suggestion")
            self.assertIsNone(rendered["brief"])
            self.assertIsNone(rendered["hook"])
            self.assertIn(expected_missing[name], rendered["missing_facts"])

    def test_multiline_fact_is_rejected_before_ready(self):
        facts = dict(FULL_FACTS)
        facts["product"] = "Vegan wallet\nSecond line"
        rendered = render_angle("Gift ready", facts)
        self.assertEqual(rendered["status"], "needs_owner_confirmation")
        self.assertIsNone(rendered["brief"])
        self.assertIsNone(rendered["hook"])
        self.assertIn("confirmation", rendered["suggestion"].lower())
        direct = "Gift idea: Vegan wallet\nSecond line at $49."
        self.assertLessEqual(len(direct), 140)
        self.assertFalse(validate_hook(direct)["ok"])

    def test_multiline_explicit_use_fact_is_rejected(self):
        facts = dict(FULL_FACTS)
        facts["gift_use"] = "Wrap\nNow"
        rendered = render_angle("Gift ready", facts)
        self.assertEqual(rendered["status"], "needs_owner_confirmation")
        self.assertIsNone(rendered["brief"])
        self.assertIsNone(rendered["hook"])


if __name__ == "__main__":
    unittest.main()
