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

    def test_labels_are_five_editorial_purposes(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B])
        labels = [b["label"] for b in briefs]
        self.assertEqual(labels, list(ca.ANGLE_LABELS))
        self.assertEqual(
            set(labels),
            {
                "Discovery Hook",
                "Concrete Detail",
                "Buyer Question",
                "Claim Boundary",
                "Concise Recap",
            },
        )
        for label in labels:
            lowered = label.lower()
            for old in ("spotlight", "sequential", "reverse", "paired", "closing"):
                self.assertNotIn(old, lowered)

    def test_editorial_approaches_are_distinct_purposes(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B, FACT_C])
        approaches = [b["editorial_approach"] for b in briefs]
        self.assertEqual(len(set(approaches)), 5)
        for approach in approaches:
            self.assertIsInstance(approach, str)
            self.assertTrue(approach.strip())
        joined = " ".join(a.lower() for a in approaches)
        for keyword in ("hook", "exact", "buyer", "boundary", "recap"):
            self.assertIn(keyword, joined)
        for old in ("spotlight", "sequential", "reverse", "paired"):
            self.assertNotIn(old, joined)

    def test_editorial_instructions_distinct_and_not_mere_orderings(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B, FACT_C])
        instructions = [b["editorial_instruction"] for b in briefs]
        self.assertEqual(len(set(instructions)), 5)
        for instruction in instructions:
            self.assertIsInstance(instruction, str)
            self.assertTrue(instruction.strip())
            self.assertIn("Do not", instruction)
        joined = " ".join(i.lower() for i in instructions)
        self.assertNotIn("reverse", joined)
        self.assertNotIn("supplied order", joined)
        self.assertNotIn("spotlight", joined)

    def test_brief_texts_are_distinct(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B, FACT_C])
        texts = [b["brief_text"] for b in briefs]
        self.assertEqual(len(set(texts)), 5)
        rendered = [str(b) for b in briefs]
        self.assertEqual(len(set(rendered)), 5)

    def test_brief_texts_differ_beyond_labels_and_facts(self):
        facts = [FACT_A, FACT_B, FACT_C]
        briefs = ca.generate_campaign_angles(facts)
        stripped = []
        for brief in briefs:
            text = brief["brief_text"]
            text = text.replace(brief["label"], "")
            for fact in facts:
                text = text.replace(fact, "")
            text = text.replace("1.", "").replace("2.", "").replace("3.", "")
            text = text.replace("- ", "")
            stripped.append(text)
        self.assertEqual(len(set(stripped)), 5)
        for i in range(5):
            for j in range(i + 1, 5):
                self.assertNotEqual(stripped[i], stripped[j])
                diff = set(stripped[i].split()) ^ set(stripped[j].split())
                self.assertGreater(len(diff), 5)

    def test_each_frame_renders_distinct_useful_section(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B])
        by_label = {b["label"]: b["brief_text"] for b in briefs}
        self.assertIn("EDITORIAL HOOK QUESTION", by_label["Discovery Hook"])
        self.assertIn(
            "What is one confirmed detail worth a closer look?",
            by_label["Discovery Hook"],
        )
        self.assertIn("hook support", by_label["Discovery Hook"].lower())
        self.assertIn("PRESENTATION NOTE", by_label["Concrete Detail"])
        self.assertIn("exact wording", by_label["Concrete Detail"].lower())
        self.assertIn("EDITORIAL BUYER QUESTION", by_label["Buyer Question"])
        self.assertIn(
            "What does the quoted material confirm", by_label["Buyer Question"]
        )
        self.assertIn("answer material only", by_label["Buyer Question"].lower())
        self.assertIn("EVIDENCE / CLAIM BOUNDARY", by_label["Claim Boundary"])
        self.assertIn(
            "Only the quoted facts above are asserted", by_label["Claim Boundary"]
        )
        self.assertIn("RECAP NOTE", by_label["Concise Recap"])
        self.assertIn("recap set", by_label["Concise Recap"].lower())
        markers = {
            "EDITORIAL HOOK QUESTION": "Discovery Hook",
            "EDITORIAL BUYER QUESTION": "Buyer Question",
            "EVIDENCE / CLAIM BOUNDARY": "Claim Boundary",
            "PRESENTATION NOTE": "Concrete Detail",
            "RECAP NOTE": "Concise Recap",
        }
        for marker, expected_label in markers.items():
            holders = [label for label, text in by_label.items() if marker in text]
            self.assertEqual(holders, [expected_label])

    def test_shared_source_not_reorderings(self):
        facts = [FACT_A, FACT_B, FACT_C]
        briefs = ca.generate_campaign_angles(facts)
        for brief in briefs:
            self.assertEqual(brief["facts_used"], facts)
            self.assertEqual(brief["fact_indexes"], [0, 1, 2])
        texts = [b["brief_text"] for b in briefs]
        self.assertEqual(len(set(texts)), 5)

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

    def test_one_fact_honesty_note(self):
        briefs = ca.generate_campaign_angles([FACT_A])
        for brief in briefs:
            text = brief["brief_text"]
            self.assertIn("SOURCE SCOPE (not a fact)", text)
            self.assertIn("Only one owner-confirmed fact was supplied", text)
            self.assertIn("same single fact", text)
            self.assertIn("five editorial frames", text)
            self.assertIn("not as five independent", text)
            self.assertEqual(brief["facts_used"], [FACT_A])

    def test_multi_fact_shared_scope_honesty(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B])
        for brief in briefs:
            text = brief["brief_text"]
            self.assertIn("SOURCE SCOPE (not a fact)", text)
            self.assertIn("same 2 supplied facts", text)
            self.assertIn("five editorial frames", text)
            self.assertIn("not as five independent", text)

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

    def test_exact_fact_preservation_byte_for_byte(self):
        tricky = ["  Spaced Fact! With, punctuation?  ", "MiXeD CASE 123 & symbols #@!"]
        briefs = ca.generate_campaign_angles(tricky)
        for brief in briefs:
            self.assertEqual(brief["facts_used"], tricky)
            for fact, index in zip(brief["facts_used"], brief["fact_indexes"]):
                self.assertEqual(fact, tricky[index])
                self.assertIn(fact, brief["brief_text"])
        single = ca.generate_campaign_angles([tricky[0]])
        for brief in single:
            self.assertEqual(brief["facts_used"], [tricky[0]])
            self.assertIn(tricky[0], brief["brief_text"])

    def test_no_invented_facts(self):
        facts = [FACT_A, FACT_B, FACT_C]
        briefs = ca.generate_campaign_angles(facts)
        for brief in briefs:
            for fact in brief["facts_used"]:
                self.assertIn(fact, facts)

    def test_no_factual_additions_or_forbidden_claims(self):
        facts = [FACT_A, FACT_B]
        briefs = ca.generate_campaign_angles(facts)
        forbidden_positive = (
            "$",
            "discount",
            "cheap",
            "affordable",
            "made in",
            "manufactured",
            "guaranteed",
            "in stock",
            "limited stock",
            "available now",
            "better than",
            "best in class",
            "customers love",
            "perfect for",
            "ideal for",
            "study shows",
            "experts say",
        )
        for brief in briefs:
            for fact in brief["facts_used"]:
                self.assertIn(fact, facts)
            text_without_facts = brief["brief_text"]
            for fact in facts:
                text_without_facts = text_without_facts.replace(fact, "")
            lowered = text_without_facts.lower()
            for phrase in forbidden_positive:
                self.assertNotIn(phrase, lowered)
            self.assertIn("No additional facts are asserted here", brief["brief_text"])
        boundary = [b for b in briefs if b["label"] == "Claim Boundary"][0]
        self.assertIn("Only the quoted facts above are asserted", boundary["brief_text"])
        self.assertIn("No additional benefit, audience", boundary["brief_text"])
        self.assertIn("beyond those quoted facts", boundary["brief_text"])

    def test_confirmed_price_fact_not_denied(self):
        price_fact = "The Blue Harbor demo kit costs $49."
        briefs = ca.generate_campaign_angles([FACT_A, price_fact])
        for brief in briefs:
            self.assertIn(price_fact, brief["facts_used"])
            self.assertIn(price_fact, brief["brief_text"])
        boundary = [b for b in briefs if b["label"] == "Claim Boundary"][0]
        text = boundary["brief_text"]
        self.assertIn("Only the quoted facts above are asserted", text)
        self.assertIn("No additional benefit, audience", text)
        self.assertIn("beyond those quoted facts", text)

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

    def test_pending_approval_without_automation_or_live_claims(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B])
        banned = (
            "automated",
            "automatic",
            "auto-generated",
            "live campaign",
            "live ui",
            "integrated",
            "published",
            "ready to publish",
            "approved for use",
        )
        for brief in briefs:
            self.assertIs(brief["approved"], False)
            self.assertEqual(brief["status"], "pending_owner_approval")
            text = brief["brief_text"]
            self.assertIn("PENDING", text)
            self.assertIn("NOT APPROVED", text)
            self.assertIn("individual owner approval", text.lower())
            self.assertIn("DRAFT FOR REVIEW", text)
            lowered = text.lower()
            for phrase in banned:
                self.assertNotIn(phrase, lowered)

    def test_editorial_instruction_separated_from_facts(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B])
        for brief in briefs:
            self.assertTrue(brief["editorial_instruction"].strip())
            self.assertTrue(brief["editorial_approach"].strip())
            self.assertIn("EDITORIAL INSTRUCTION", brief["brief_text"])
            self.assertIn("OWNER-CONFIRMED FACTS", brief["brief_text"])
            self.assertNotIn(brief["editorial_instruction"], brief["facts_used"])

    def test_editorial_questions_separated_from_facts(self):
        briefs = ca.generate_campaign_angles([FACT_A, FACT_B])
        by_label = {b["label"]: b for b in briefs}
        for brief in briefs:
            self.assertIn("EDITORIAL INSTRUCTION (not a fact)", brief["brief_text"])
            self.assertIn("OWNER-CONFIRMED FACTS", brief["brief_text"])
            self.assertNotIn(brief["editorial_instruction"], brief["facts_used"])
        hook_text = by_label["Discovery Hook"]["brief_text"]
        self.assertIn("EDITORIAL HOOK QUESTION (not a fact", hook_text)
        buyer_text = by_label["Buyer Question"]["brief_text"]
        self.assertIn("EDITORIAL BUYER QUESTION (not a fact", buyer_text)
        boundary_text = by_label["Claim Boundary"]["brief_text"]
        self.assertIn("EVIDENCE / CLAIM BOUNDARY (not a fact", boundary_text)

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
