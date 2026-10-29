"""Unit tests for launchcrew.campaign_angles.

Uses fictional synthetic facts only. No personal data.
"""
import copy
import unittest

from launchcrew import campaign_angles as ca


FACT_A = "The Blue Harbor demo notebook has 96 pages."
FACT_B = "The Blue Harbor demo notebook cover is blue."
FACT_C = "The Blue Harbor demo kit includes a pencil."
FACT_D = "The Blue Harbor demo workshop lasts 60 minutes."


class CampaignAnglesTests(unittest.TestCase):
    def test_generates_exactly_five_briefs(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B, FACT_C])
        self.assertIsInstance(briefs, list)
        self.assertEqual(len(briefs), 5)
        self.assertEqual(len(briefs), ca.NUM_ANGLES)

    def test_labels_are_distinct_and_nonblank(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B])
        labels = [b["label"] for b in briefs]
        self.assertEqual(len(labels), 5)
        self.assertEqual(len(set(labels)), 5)
        for label in labels:
            self.assertIsInstance(label, str)
            self.assertTrue(label.strip())
        self.assertEqual(len(set(ca.ANGLE_LABELS)), 5)

    def test_brief_texts_are_distinct(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B, FACT_C])
        texts = [b["brief_text"] for b in briefs]
        self.assertEqual(len(set(texts)), 5)
        rendered = [str(b) for b in briefs]
        self.assertEqual(len(set(rendered)), 5)

    def test_single_fact_shared_without_fabrication(self):
        briefs = ca.generate_campaign_angles([FACT_A])
        self.assertEqual(len(briefs), 5)
        labels = [b["label"] for b in briefs]
        self.assertEqual(len(set(labels)), 5)
        for brief in briefs:
            self.assertEqual(brief["facts_used"], [FACT_A])
            self.assertIn(FACT_A, brief["brief_text"])
            for index in brief["fact_indexes"]:
                self.assertEqual(index, 0)

    def test_several_facts_exact_and_identified(self):
        facts = [FACT_A, FACT_B, FACT_C]
        briefs = ca.generate_campaign_angles(facts)
        for brief in briefs:
            self.assertTrue(brief["facts_used"])
            self.assertEqual(len(brief["facts_used"]), len(brief["fact_indexes"]))
            for fact, index in zip(brief["facts_used"], brief["fact_indexes"]):
                self.assertIn(index, (0, 1, 2))
                self.assertEqual(fact, facts[index])
                self.assertIn(fact, brief["brief_text"])

    def test_no_invented_facts(self):
        facts = [FACT_A, FACT_B, FACT_C]
        briefs = ca.generate_campaign_angles(facts)
        for brief in briefs:
            for fact in brief["facts_used"]:
                self.assertIn(fact, facts)

    def test_determinism(self):
        facts = [FACT_A, FACT_B, FACT_C]
        first = ca.generate_campaign_angles(facts)
        second = ca.generate_campaign_angles(list(facts))
        self.assertEqual(first, second)
        as_tuple = ca.generate_campaign_angles(tuple(facts))
        self.assertEqual(first, as_tuple)

    def test_count_bounds(self):
        ok = ["Fact %d from Harbor demo." % i for i in range(ca.MAX_FACTS)]
        self.assertEqual(len(ca.generate_campaign_angles(ok)), 5)
        too_many = ["Fact %d from Harbor demo." % i for i in range(ca.MAX_FACTS + 1)]
        with self.assertRaises(ValueError):
            ca.generate_campaign_angles(too_many)
        with self.assertRaises(ValueError):
            ca.generate_campaign_angles([])

    def test_fact_length_bounds(self):
        ok_fact = "x" * ca.MAX_FACT_CHARS
        briefs = ca.generate_campaign_angles([ok_fact])
        self.assertEqual(len(briefs), 5)
        too_long = "x" * (ca.MAX_FACT_CHARS + 1)
        with self.assertRaises(ValueError):
            ca.generate_campaign_angles([too_long])

    def test_output_length_bounded(self):
        facts = [FACT_A, FACT_B, FACT_C, FACT_D]
        for brief in ca.generate_campaign_angles(facts):
            self.assertLessEqual(len(brief["brief_text"]), ca.MAX_BRIEF_CHARS)

    def test_malformed_inputs_rejected(self):
        bad_inputs = (None, 123, "a string", {"fact": FACT_A}, {FACT_A, FACT_B}, b"bytes")
        for bad in bad_inputs:
            with self.subTest(bad=bad), self.assertRaises((TypeError, ValueError)):
                ca.generate_campaign_angles(bad)
        for bad_list in ([None], [123], [FACT_A, None], [{"text": FACT_A}]):
            with self.subTest(bad_list=bad_list), self.assertRaises((TypeError, ValueError)):
                ca.generate_campaign_angles(bad_list)

    def test_blank_strings_rejected(self):
        for blank in ("", "   ", "\t\n  "):
            with self.subTest(blank=repr(blank)), self.assertRaises(ValueError):
                ca.generate_campaign_angles([blank])
        with self.assertRaises(ValueError):
            ca.generate_campaign_angles([FACT_A, "   "])

    def test_duplicates_rejected(self):
        with self.assertRaises(ValueError):
            ca.generate_campaign_angles([FACT_A, FACT_A])
        with self.assertRaises(ValueError):
            ca.generate_campaign_angles([FACT_A, FACT_B, FACT_A])

    def test_no_auto_approval(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B])
        for brief in briefs:
            self.assertIs(brief["approved"], False)
            self.assertEqual(brief["status"], "pending_owner_approval")
            text = brief["brief_text"]
            self.assertIn("PENDING", text)
            self.assertIn("APPROVAL", text)
            self.assertIn("NOT APPROVED", text)
            lowered = text.lower()
            self.assertIn("pending", lowered)
            self.assertIn("owner approval", lowered)

    def test_editorial_instruction_separated_from_facts(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B])
        for brief in briefs:
            self.assertTrue(brief["editorial_instruction"].strip())
            self.assertTrue(brief["editorial_approach"].strip())
            self.assertIn("EDITORIAL INSTRUCTION", brief["brief_text"])
            self.assertIn("OWNER-CONFIRMED FACTS", brief["brief_text"])
            self.assertNotIn(brief["editorial_instruction"], brief["facts_used"])

    def test_no_input_mutation(self):
        facts = [FACT_A, FACT_B, FACT_C]
        snapshot = copy.deepcopy(facts)
        ca.generate_campaign_angles(facts)
        self.assertEqual(facts, snapshot)

    def test_output_independent_and_pure(self):
        facts = [FACT_A, FACT_B]
        first = ca.generate_campaign_angles(facts)
        first[0]["facts_used"].append("mutated")
        first[0]["brief_text"] = "mutated"
        second = ca.generate_campaign_angles(facts)
        self.assertNotIn("mutated", second[0]["facts_used"])
        self.assertNotEqual(second[0]["brief_text"], "mutated")
        for brief in second:
            self.assertIsNot(brief["facts_used"], facts)
        third = ca.generate_campaign_angles(facts)
        self.assertEqual(second, third)

    def test_stable_documented_interface(self):
        self.assertTrue(callable(ca.generate_campaign_angles))
        self.assertTrue(ca.__doc__ and ca.__doc__.strip())
        self.assertTrue(
            ca.generate_campaign_angles.__doc__
            and ca.generate_campaign_angles.__doc__.strip()
        )
        for name in ("NUM_ANGLES", "MIN_FACTS", "MAX_FACTS", "MAX_FACT_CHARS", "MAX_BRIEF_CHARS"):
            self.assertIsInstance(getattr(ca, name), int)


if __name__ == "__main__":
    unittest.main()
