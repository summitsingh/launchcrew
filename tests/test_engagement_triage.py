"""Engagement triage coverage: classification priority and drafts.

Pure stdlib unittest with synthetic fixtures only. No DB, no network.
"""

import unittest

from launchcrew import engagement_triage as tri


class NormalizeTests(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(tri.MODULE_VERSION, "engagement-triage/v1")
        self.assertEqual(tri.KINDS, ("comment", "dm"))

    def test_kind_ok(self):
        self.assertEqual(tri.normalize_kind("comment"), "comment")
        self.assertEqual(tri.normalize_kind("  dm  "), "dm")

    def test_kind_bad(self):
        for bad in ("email", "", None, 5, ["comment"]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    tri.normalize_kind(bad)

    def test_text_and_handle_and_ref(self):
        self.assertEqual(tri.normalize_text("  hello  "), "hello")
        self.assertEqual(tri.normalize_handle("@owner"), "owner")
        self.assertEqual(tri.normalize_ref(" post_1 "), "post_1")
        for bad in ("", "   ", None, 9, "x" * 2001):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(ValueError):
                    tri.normalize_text(bad)
        with self.assertRaises(ValueError):
            tri.normalize_handle("")
        with self.assertRaises(ValueError):
            tri.normalize_ref("")


class ClassifyTests(unittest.TestCase):
    def test_complaint_first(self):
        self.assertEqual(tri.classify_text("This arrived broken, I want a refund?"), "complaint")

    def test_spam_risk(self):
        self.assertEqual(
            tri.classify_text("Free money crypto, click here http://example.invalid"), "spam_risk")

    def test_question(self):
        self.assertEqual(tri.classify_text("When does this restock?"), "question")

    def test_praise(self):
        self.assertEqual(tri.classify_text("Love this, amazing quality"), "praise")

    def test_neutral(self):
        self.assertEqual(tri.classify_text("Saw this on my feed"), "neutral")

    def test_bad_input_raises(self):
        with self.assertRaises(ValueError):
            tri.classify_text("  ")


class SuggestTests(unittest.TestCase):
    def test_drafts_name_handle_and_snippet(self):
        draft = tri.suggest_reply("question", "owner", "When does this restock?")
        self.assertIn("owner", draft)
        self.assertIn("When does this restock?", draft)
        self.assertNotIn("refund", draft.lower())

    def test_complaint_apologizes_without_promising(self):
        draft = tri.suggest_reply("complaint", "owner", "Arrived broken")
        self.assertIn("sorry", draft.lower())
        self.assertNotIn("refund", draft.lower())
        self.assertNotIn("guarantee", draft.lower())

    def test_spam_risk_refuses_draft(self):
        with self.assertRaises(ValueError):
            tri.suggest_reply("spam_risk", "owner", "Free money, click here")

    def test_neutral_gets_generic_draft(self):
        draft = tri.suggest_reply("neutral", "owner", "Saw this on my feed")
        self.assertIn("owner", draft)


if __name__ == "__main__":
    unittest.main()
