"""Focused hook tests for launchcrew.campaign_angles.

Uses fictional synthetic facts only. No personal data.
Not run here while other writers are active; kept for the owner test pass.
"""
import unittest

from launchcrew import campaign_angles as ca


FACT_A = "The Blue Harbor demo notebook has 96 pages."
FACT_B = "The Blue Harbor demo notebook cover is blue."
FACT_C = "The Blue Harbor demo kit includes a pencil."

QUALIFIED_LONG = (
    "The Blue Harbor demo workshop lasts 60 minutes with extra padding words "
    "added only to exceed the hook budget, applying only in the fictional "
    "prototype, not the product."
)
NEGATED_LONG = (
    "The Blue Harbor demo kit includes a pencil plus a long fictional handling "
    "note that is not part of the product and never ships, added only to exceed "
    "the single hook line budget for testing purposes here."
)
SUBJECT_LONG = (
    "The Blue Harbor demo notebook has a blue cover and the demo kit includes "
    "a pencil, with extra fictional padding words added only so this sentence "
    "exceeds the hook budget and no partial hook may move the pencil to the "
    "notebook."
)
NUMERIC_LONG = (
    "The Blue Harbor demo notebook has 96 pages in the fictional prototype "
    "sample run, with extra padding words added only to exceed the hook budget, "
    "not a product quantity claim for sale."
)


class AngleHookTests(unittest.TestCase):
    def test_each_brief_has_bounded_single_line_hook(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B, FACT_C])
        self.assertEqual(len(briefs), 5)
        for brief in briefs:
            hook = brief["hook_line"]
            self.assertIsInstance(hook, str)
            self.assertTrue(hook.strip())
            self.assertLess(len(hook), 140)
            self.assertLessEqual(len(hook), ca.MAX_HOOK_CHARS)
            self.assertNotIn("\n", hook)
            self.assertNotIn("\r", hook)
            self.assertIn(hook, brief["brief_text"])
            self.assertIn("CAMPAIGN HOOK LINE", brief["brief_text"])

    def test_short_fact_hook_uses_whole_fact(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B, FACT_C])
        for brief in briefs:
            self.assertTrue(brief["hook_available"])
            self.assertIsNone(brief["hook_reason"])
            self.assertEqual(
                brief["hook_line"].split(": ", 1)[1],
                " ".join(brief["hook_source_fact"].split()),
            )

    def test_hooks_are_distinct_per_angle(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B, FACT_C])
        hooks = [b["hook_line"] for b in briefs]
        self.assertEqual(len(set(hooks)), 5)

    def test_single_fact_hooks_stay_distinct_without_new_claims(self):
        briefs = ca.generate_campaign_angles([FACT_A])
        hooks = [b["hook_line"] for b in briefs]
        self.assertEqual(len(set(hooks)), 5)
        for brief in briefs:
            self.assertEqual(brief["hook_source_fact"], FACT_A)
            self.assertEqual(brief["hook_fact_index"], 0)

    def test_hook_spotlights_rotating_source_fact(self):
        facts = [FACT_A, FACT_B, FACT_C]
        briefs = ca.generate_campaign_angles(facts)
        for position, brief in enumerate(briefs):
            expected = position % len(facts)
            self.assertEqual(brief["hook_fact_index"], expected)
            self.assertEqual(brief["hook_source_fact"], facts[expected])

    def test_long_qualification_is_unavailable_not_truncated(self):
        briefs = ca.generate_campaign_angles([QUALIFIED_LONG])
        self.assertEqual(len(briefs), 5)
        for brief in briefs:
            self.assertFalse(brief["hook_available"])
            self.assertIn("unavailable", brief["hook_line"])
            self.assertIn("owner input", brief["hook_line"])
            self.assertNotIn("not the product", brief["hook_line"])
            self.assertIn("not the product", brief["brief_text"])
            self.assertIn("shorter", brief["brief_text"])
            self.assertNotIn("...", brief["hook_line"])

    def test_negated_fact_is_unavailable_not_truncated(self):
        briefs = ca.generate_campaign_angles([NEGATED_LONG])
        for brief in briefs:
            self.assertFalse(brief["hook_available"])
            self.assertIn("unavailable", brief["hook_line"])
            self.assertNotIn("never ships", brief["hook_line"])
            self.assertIn("never ships", brief["brief_text"])
            self.assertIs(brief["approved"], False)
            self.assertEqual(brief["status"], "pending_owner_approval")

    def test_subject_fact_is_unavailable_not_truncated(self):
        briefs = ca.generate_campaign_angles([SUBJECT_LONG])
        for brief in briefs:
            self.assertFalse(brief["hook_available"])
            self.assertNotIn("pencil", brief["hook_line"])
            self.assertIn("pencil", brief["brief_text"])
            self.assertIn("owner input", brief["hook_line"])

    def test_numeric_fact_is_unavailable_not_truncated(self):
        briefs = ca.generate_campaign_angles([NUMERIC_LONG])
        for brief in briefs:
            self.assertFalse(brief["hook_available"])
            self.assertNotIn("96", brief["hook_line"])
            self.assertIn("96", brief["brief_text"])
            self.assertIn("shorter", brief["hook_reason"])

    def test_hooks_stay_pending_and_need_independent_check(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B])
        for brief in briefs:
            self.assertIs(brief["approved"], False)
            self.assertEqual(brief["status"], "pending_owner_approval")
            self.assertIn("PENDING", brief["brief_text"])
            self.assertIn("owner approval", brief["brief_text"].lower())
            self.assertIn("independent Checker", brief["brief_text"])
            self.assertIn("not independently exportable", brief["brief_text"].lower())

    def test_distinctness_note_states_reuse_honestly(self):
        single = ca.generate_campaign_angles([FACT_A])
        for brief in single:
            self.assertIn("DISTINCTNESS NOTE", brief["brief_text"])
            self.assertIn("Only one owner-confirmed", brief["brief_text"])
            self.assertIn("not five independent", brief["brief_text"])
        few = ca.generate_campaign_angles([FACT_A, FACT_B])
        for brief in few:
            self.assertIn("DISTINCTNESS NOTE", brief["brief_text"])
            self.assertIn("Only 2 owner-confirmed", brief["brief_text"])


class CampaignDayHookTests(unittest.TestCase):
    def test_default_week_has_seven_bounded_hooks(self):
        hooks = ca.generate_campaign_day_hooks([FACT_A, FACT_B])
        self.assertEqual(len(hooks), 7)
        seen = set()
        for hook in hooks:
            self.assertLess(len(hook["hook_line"]), 140)
            self.assertNotIn("\n", hook["hook_line"])
            self.assertIn(hook["source_fact"], [FACT_A, FACT_B])
            self.assertIs(hook["approved"], False)
            self.assertEqual(hook["status"], "pending_owner_approval")
            seen.add(hook["hook_line"])
        self.assertEqual(len(seen), 7)

    def test_short_fact_days_are_available(self):
        hooks = ca.generate_campaign_day_hooks([FACT_A, FACT_B], num_days=2)
        for hook in hooks:
            self.assertTrue(hook["hook_available"])
            self.assertIsNone(hook["hook_reason"])

    def test_long_fact_days_are_unavailable_without_fake_hook(self):
        hooks = ca.generate_campaign_day_hooks([QUALIFIED_LONG], num_days=3)
        self.assertEqual(len(hooks), 3)
        for hook in hooks:
            self.assertFalse(hook["hook_available"])
            self.assertIn("unavailable", hook["hook_line"])
            self.assertIn("owner input", hook["hook_line"])
            self.assertNotIn("not the product", hook["hook_line"])
            self.assertEqual(hook["source_fact"], QUALIFIED_LONG)
            self.assertIs(hook["approved"], False)
            self.assertEqual(hook["status"], "pending_owner_approval")

    def test_custom_day_count_and_rotation(self):
        hooks = ca.generate_campaign_day_hooks([FACT_A, FACT_B, FACT_C], num_days=3)
        self.assertEqual([h["day"] for h in hooks], [1, 2, 3])
        self.assertEqual([h["fact_index"] for h in hooks], [0, 1, 2])
        self.assertEqual([h["source_fact"] for h in hooks], [FACT_A, FACT_B, FACT_C])

    def test_bad_day_counts_rejected(self):
        with self.assertRaises((TypeError, ValueError)):
            ca.generate_campaign_day_hooks([FACT_A], num_days=0)
        with self.assertRaises((TypeError, ValueError)):
            ca.generate_campaign_day_hooks([FACT_A], num_days=8)
        with self.assertRaises((TypeError, ValueError)):
            ca.generate_campaign_day_hooks([FACT_A], num_days=True)

    def test_daily_alias_matches(self):
        first = ca.generate_campaign_day_hooks([FACT_A, FACT_B], num_days=2)
        second = ca.generate_daily_hooks([FACT_A, FACT_B], num_days=2)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
