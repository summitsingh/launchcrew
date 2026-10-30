"""Focused tests for launchcrew.context_claims.

Synthetic fixtures only. No real brand copy, no website text, no owner
data, no network, no database.
"""
import unittest

from launchcrew import context_claims

WS = "ws-summit-test"


def summit_scope(workspace=WS):
    return {"profile": "summit", "enabled": True, "workspace_id": workspace}


def summit_policy(extra=None, workspace=WS):
    policy = {"profile": "summit", "enabled": True, "workspace_id": workspace}
    if extra:
        policy.update(extra)
    return policy


class ScopeTests(unittest.TestCase):
    def test_inert_without_scope(self):
        self.assertEqual(context_claims.context_blocks_for_text("Genuine leather wallet."), [])
        self.assertEqual(
            context_claims.context_blocks_for_text("Genuine leather wallet.", scope={}), [])
        self.assertEqual(
            context_claims.context_blocks_for_text(
                "Genuine leather wallet.",
                scope={"profile": "other", "enabled": True, "workspace_id": WS}), [])

    def test_missing_workspace_refuses(self):
        scope = {"profile": "summit", "enabled": True}
        with self.assertRaises(context_claims.ScopeBindingError):
            context_claims.is_scope_enabled(scope, None)
        with self.assertRaises(context_claims.ScopeBindingError):
            context_claims.context_blocks_for_text("Genuine leather wallet.", scope=scope)

    def test_cross_workspace_mismatch_refuses(self):
        scope = summit_scope(workspace="ws-a")
        policy = summit_policy(workspace="ws-b")
        with self.assertRaises(context_claims.ScopeBindingError):
            context_claims.is_scope_enabled(scope, policy)
        with self.assertRaises(context_claims.ScopeBindingError):
            context_claims.context_blocks_for_text(
                "Genuine leather wallet.", policy=policy, scope=scope)

    def test_policy_profile_mismatch_refuses(self):
        scope = summit_scope(workspace="ws-a")
        policy = {"profile": "other", "enabled": True, "workspace_id": "ws-a"}
        with self.assertRaises(context_claims.ScopeBindingError):
            context_claims.context_blocks_for_text(
                "Genuine leather wallet.", policy=policy, scope=scope)

    def test_enabled_summit_scope_blocks(self):
        blocks = context_claims.context_blocks_for_text(
            "Genuine leather wallet.", scope=summit_scope())
        self.assertEqual(len(blocks), 1)
        self.assertIn("never allowed", blocks[0]["reason"])


class MaterialTests(unittest.TestCase):
    def test_affirmative_variants_always_block(self):
        for text in ("Genuine leather wallet.", "Real leather trim.",
                     "Full grain leather.", "Top grain finish.",
                     "Full-grain leather.", "TOP GRAIN finish."):
            with self.subTest(text=text):
                blocks = context_claims.context_blocks_for_text(text, scope=summit_scope())
                self.assertTrue(blocks, text)
                self.assertIn("never allowed", blocks[0]["reason"].lower())

    def test_affirmative_blocked_even_when_confirmed(self):
        facts = {"approved_claims": ["Genuine leather wallet"]}
        blocks = context_claims.context_blocks_for_text(
            "Genuine leather wallet.", facts=facts, scope=summit_scope())
        self.assertTrue(blocks)
        self.assertIn("even when confirmed", blocks[0]["reason"].lower())

    def test_negated_needs_confirmation(self):
        blocks = context_claims.context_blocks_for_text(
            "Not genuine leather.", scope=summit_scope())
        self.assertTrue(blocks)
        self.assertIn("confirmed", blocks[0]["reason"].lower())

    def test_negated_passes_with_confirmed_sentence(self):
        facts = {"approved_claims": ["Not genuine leather"]}
        blocks = context_claims.context_blocks_for_text(
            "Not genuine leather.", facts=facts, scope=summit_scope())
        self.assertEqual(blocks, [])

    def test_bare_affirmative_does_not_authorize_negation(self):
        facts = {"approved_claims": ["Genuine leather"]}
        blocks = context_claims.context_blocks_for_text(
            "Not genuine leather.", facts=facts, scope=summit_scope())
        self.assertTrue(blocks)

    def test_blanket_flag_does_not_authorize(self):
        policy = summit_policy({"material_negation_allowed": True})
        blocks = context_claims.context_blocks_for_text(
            "Not real leather.", policy=policy, scope=summit_scope())
        self.assertTrue(blocks)

    def test_explicit_policy_sentence_authorizes_negation(self):
        policy = summit_policy({"confirmed_negations": ["Not real leather"]})
        blocks = context_claims.context_blocks_for_text(
            "Not real leather.", policy=policy, scope=summit_scope())
        self.assertEqual(blocks, [])

    def test_double_negation_reads_as_affirmative(self):
        blocks = context_claims.context_blocks_for_text(
            "Not not genuine leather.", scope=summit_scope())
        self.assertTrue(blocks)
        self.assertIn("double negation", blocks[0]["reason"].lower())

    def test_mixed_clause_affirmative_still_blocks(self):
        facts = {"approved_claims": ["Not genuine leather"]}
        blocks = context_claims.context_blocks_for_text(
            "Not genuine leather but full grain trim.", facts=facts,
            scope=summit_scope())
        phrases = [b["phrase"] for b in blocks]
        self.assertIn("full grain", phrases)

    def test_no_substring_false_positives(self):
        for text in ("Genuinely kind wallet.", "Realistic finish.",
                     "Full stop wallet.", "Topic list."):
            with self.subTest(text=text):
                self.assertEqual(
                    context_claims.context_blocks_for_text(text, scope=summit_scope()), [])


class AmbiguousExclusiveTests(unittest.TestCase):
    def test_not_only_material_always_blocks(self):
        for text in ("Not only genuine leather wallet.",
                     "Not just real leather trim.",
                     "Not merely full grain finish."):
            with self.subTest(text=text):
                blocks = context_claims.context_blocks_for_text(text, scope=summit_scope())
                self.assertTrue(blocks, text)
                self.assertIn("ambiguous", blocks[0]["reason"].lower())

    def test_not_only_material_blocked_even_when_confirmed(self):
        facts = {"approved_claims": ["Not only genuine leather wallet"]}
        blocks = context_claims.context_blocks_for_text(
            "Not only genuine leather wallet.", facts=facts, scope=summit_scope())
        self.assertTrue(blocks)
        self.assertIn("even when confirmed", blocks[0]["reason"].lower())

    def test_not_only_detected_as_ambiguous(self):
        detected = context_claims.detect_claims("Not only genuine leather wallet.")
        material = [d for d in detected if d["group"] == "material"]
        self.assertTrue(material)
        self.assertTrue(material[0]["affirmative"])
        self.assertTrue(material[0]["ambiguous"])
        self.assertFalse(material[0]["negated"])

    def test_linked_coordinated_not_only_blocks_both_clauses(self):
        facts = {"approved_claims": ["Not only genuine leather but full grain trim"]}
        blocks = context_claims.context_blocks_for_text(
            "Not only genuine leather but full grain trim.", facts=facts,
            scope=summit_scope())
        self.assertTrue(blocks)
        phrases = [b["phrase"] for b in blocks]
        self.assertIn("genuine leather", phrases)

    def test_ambiguous_gated_form_never_uses_negated_confirmation(self):
        facts = {"approved_claims": ["Not only waterproof wallet"]}
        blocks = context_claims.context_blocks_for_text(
            "Not only waterproof wallet.", facts=facts, scope=summit_scope())
        self.assertTrue(blocks)
        self.assertIn("ambiguous", blocks[0]["reason"].lower())


class TrailingNegationTests(unittest.TestCase):
    def test_trailing_not_does_not_negate(self):
        blocks = context_claims.context_blocks_for_text(
            "Genuine leather wallet not.", scope=summit_scope())
        self.assertTrue(blocks)
        self.assertIn("never allowed", blocks[0]["reason"].lower())

    def test_trailing_clause_does_not_negate_first_clause(self):
        blocks = context_claims.context_blocks_for_text(
            "Genuine leather wallet, not canvas.", scope=summit_scope())
        phrases = [b["phrase"] for b in blocks]
        self.assertIn("genuine leather", phrases)

    def test_preceding_negation_within_window_negates(self):
        detected = context_claims.detect_claims("Not genuine leather wallet.")
        material = [d for d in detected if d["group"] == "material"]
        self.assertTrue(material)
        self.assertTrue(material[0]["negated"])
        self.assertFalse(material[0]["affirmative"])

    def test_coordinated_mixed_clauses(self):
        blocks = context_claims.context_blocks_for_text(
            "Not canvas tote but genuine leather wallet.", scope=summit_scope())
        phrases = [b["phrase"] for b in blocks]
        self.assertIn("genuine leather", phrases)

    def test_unrelated_negation_across_and_does_not_govern(self):
        for text in ("Not blue and genuine leather.",
                     "No zipper and real leather.",
                     "Not canvas or top grain trim."):
            with self.subTest(text=text):
                detected = context_claims.detect_claims(text)
                material = [d for d in detected if d["group"] == "material"]
                self.assertTrue(material, text)
                self.assertTrue(all(m["affirmative"] for m in material), text)
                self.assertTrue(all(not m["negated"] for m in material), text)

    def test_coordinated_affirmative_blocked_even_when_confirmed(self):
        for text in ("Not blue and genuine leather.",
                     "No zipper and real leather."):
            with self.subTest(text=text):
                facts = {"approved_claims": [text.rstrip(".")]}
                blocks = context_claims.context_blocks_for_text(
                    text, facts=facts, scope=summit_scope())
                self.assertTrue(blocks, text)
                self.assertIn("never allowed", blocks[0]["reason"].lower())

    def test_legitimate_negated_material_still_passes(self):
        facts = {"approved_claims": ["Not genuine leather"]}
        blocks = context_claims.context_blocks_for_text(
            "Not genuine leather.", facts=facts, scope=summit_scope())
        self.assertEqual(blocks, [])

    def test_negated_first_conjunct_passes_while_second_affirmative_blocks(self):
        facts = {"approved_claims": ["Not genuine leather and canvas"]}
        blocks = context_claims.context_blocks_for_text(
            "Genuine leather and not canvas.", facts=facts, scope=summit_scope())
        phrases = [b["phrase"] for b in blocks]
        self.assertIn("genuine leather", phrases)


class ContractionTests(unittest.TestCase):
    def test_dont_tokenizes_as_negation(self):
        tokens = context_claims._word_tokens("Don't buy this.")
        self.assertIn("dont", tokens)
        self.assertNotIn("don", tokens)

    def test_contraction_negated_care_needs_confirmation(self):
        blocks = context_claims.context_blocks_for_text(
            "Don't machine wash.", scope=summit_scope())
        self.assertTrue(blocks)
        facts = {"approved_claims": ["Don't machine wash"]}
        confirmed = context_claims.context_blocks_for_text(
            "Don't machine wash.", facts=facts, scope=summit_scope())
        self.assertEqual(confirmed, [])

    def test_curly_apostrophe_contraction(self):
        blocks = context_claims.context_blocks_for_text(
            "Doesn\u2019t need a break-in.", scope=summit_scope())
        self.assertTrue(blocks)


class EvidenceGateTests(unittest.TestCase):
    def test_gated_claims_block_without_confirmation(self):
        cases = ("Waterproof wallet.", "Lifetime warranty.",
                 "Guaranteed for life.", "Unbreakable frame.",
                 "Sustainable wallet.", "Biodegradable wallet.",
                 "Carbon neutral shipping.", "Rich patina finish.")
        for text in cases:
            with self.subTest(text=text):
                blocks = context_claims.context_blocks_for_text(text, scope=summit_scope())
                self.assertTrue(blocks, text)
                self.assertIn("confirmed sentence",
                              blocks[0]["reason"].lower())

    def test_gated_claim_passes_with_exact_sentence(self):
        facts = {"approved_claims": ["Waterproof wallet"]}
        blocks = context_claims.context_blocks_for_text(
            "Waterproof wallet.", facts=facts, scope=summit_scope())
        self.assertEqual(blocks, [])

    def test_bare_phrase_does_not_authorize_different_subject(self):
        facts = {"approved_claims": ["Waterproof wallet"]}
        blocks = context_claims.context_blocks_for_text(
            "Waterproof tote.", facts=facts, scope=summit_scope())
        self.assertTrue(blocks)

    def test_subject_reversal_stays_blocked(self):
        facts = {"approved_claims": ["Leather wallet includes case"]}
        blocks = context_claims.context_blocks_for_text(
            "Leather case includes wallet.", facts=facts, scope=summit_scope())
        # No gated phrase here, but the reversal must not read as
        # confirmed if a gated phrase is present in a variant form.
        facts_gated = {"approved_claims": ["Waterproof wallet includes case"]}
        reversed_blocks = context_claims.context_blocks_for_text(
            "Waterproof case includes wallet.", facts=facts_gated,
            scope=summit_scope())
        self.assertTrue(reversed_blocks)
        self.assertEqual(blocks, [])

    def test_conditioning_needs_confirmation(self):
        blocks = context_claims.context_blocks_for_text(
            "Apply conditioner monthly.", scope=summit_scope())
        self.assertTrue(blocks)

    def test_machine_wash_assertion_needs_confirmation(self):
        blocks = context_claims.context_blocks_for_text(
            "Machine washable wallet.", scope=summit_scope())
        self.assertTrue(blocks)

    def test_unsupported_negated_care_blocks(self):
        for text in ("Do not machine wash.", "Do not condition the leather."):
            with self.subTest(text=text):
                blocks = context_claims.context_blocks_for_text(text, scope=summit_scope())
                self.assertTrue(blocks, text)

    def test_supported_negated_care_passes(self):
        facts = {"approved_claims": ["Do not machine wash"]}
        blocks = context_claims.context_blocks_for_text(
            "Do not machine wash.", facts=facts, scope=summit_scope())
        self.assertEqual(blocks, [])

    def test_break_in_supported_negation_passes(self):
        facts = {"approved_claims": ["No stiff break-in"]}
        blocks = context_claims.context_blocks_for_text(
            "No stiff break-in.", facts=facts, scope=summit_scope())
        self.assertEqual(blocks, [])

    def test_break_in_unsupported_blocks(self):
        blocks = context_claims.context_blocks_for_text(
            "Requires a break-in period.", scope=summit_scope())
        self.assertTrue(blocks)


class StyleGuidanceTests(unittest.TestCase):
    def test_positioning_terms_never_block(self):
        for text in ("Luxury wallet.", "High-end wallet.",
                     "Designer wallet.", "Cheap wallet.",
                     "Cheapest wallet."):
            with self.subTest(text=text):
                self.assertEqual(
                    context_claims.context_blocks_for_text(text, scope=summit_scope()), [])


class CandidateSummaryTests(unittest.TestCase):
    def test_check_candidate_shape(self):
        result = context_claims.check_candidate("Luxury wallet.", scope=summit_scope())
        self.assertFalse(result["blocked"])
        self.assertEqual(result["blocked_count"], 0)
        self.assertTrue(result["scope_enabled"])
        blocked = context_claims.check_candidate(
            "Genuine leather wallet.", scope=summit_scope())
        self.assertTrue(blocked["blocked"])
        self.assertEqual(blocked["blocked_count"], 1)
        self.assertEqual(blocked["module"], context_claims.MODULE_VERSION)


if __name__ == "__main__":
    unittest.main()
