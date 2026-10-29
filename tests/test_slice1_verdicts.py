"""Slice 1 safety and deterministic verdict regressions.

Socket-free and offline only. No model calls, no credentials.

Owner-mode verdicts derive only from explicitly confirmed owner facts, never
from demo template fields, memory suggestions, briefs, idea text, or founder
notes. Deterministic verdicts are supported/unsupported/conflicts with quoted
fact evidence, retaining legacy verified booleans. Keyword and value checks
are limited by design: unknown wording stays unsupported (blocked), never
silently supported.
"""
import unittest

from launchcrew.facts import check_claim, check_claims, check_sentence
from launchcrew.run import check_pack


OWNER_SOURCES = ['owner_confirmed_input']


def owner_facts(claims):
    return {'approved_claims': list(claims), 'sources': list(OWNER_SOURCES)}


class OwnerSafetyTests(unittest.TestCase):
    def test_demo_only_fact_blocked_against_owner_facts(self):
        # Owner confirmed Full-grain leather and $129. Bundled demo claim
        # 100% vegan PU leather must not verify, even though it lives in
        # demo_facts.json. Material wording differs, so conflicts.
        facts = owner_facts(['Full-grain leather', '$129'])
        for fn in (check_claim, check_sentence):
            with self.subTest(fn=fn.__name__):
                result = fn('100% vegan PU leather', facts)
                self.assertFalse(result['verified'])
                self.assertEqual(result['verdict'], 'conflicts')
                self.assertEqual(result['evidence'], 'Full-grain leather')
                self.assertIn('material', result['reason'].lower())

    def test_demo_fields_cannot_authorize_even_when_present(self):
        # Regression for the blob leak: even if a facts object still carries
        # demo template fields, only approved_claims authorize.
        facts = {'approved_claims': ['Full-grain leather', '$129'],
                 'sources': list(OWNER_SOURCES),
                 'material': '100% vegan PU leather',
                 'price': '$49',
                 'product': 'Vegan leather wallet',
                 'audience': 'Austin commuters',
                 'channel': 'Instagram',
                 'brand_voice': 'Warm, plain, no hype',
                 'memory_claims': ['Handmade wallet for commuters']}
        result = check_claim('100% vegan PU leather', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Full-grain leather')
        # Demo price $49 must not verify against owner $129.
        price = check_claim('$49', facts)
        self.assertFalse(price['verified'])
        self.assertEqual(price['verdict'], 'conflicts')
        self.assertEqual(price['evidence'], '$129')
        # Memory suggestion never authorizes.
        memory = check_claim('Handmade wallet for commuters', facts)
        self.assertFalse(memory['verified'])
        self.assertEqual(memory['verdict'], 'unsupported')
        self.assertIsNone(memory['evidence'])
        # Channel label is not an approved claim.
        channel = check_claim('Instagram', facts)
        self.assertFalse(channel['verified'])
        self.assertEqual(channel['verdict'], 'unsupported')

    def test_wrong_price_conflicts_with_quoted_evidence(self):
        facts = owner_facts(['Full-grain leather', '$129'])
        result = check_sentence('$49', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], '$129')
        self.assertIn('price', result['reason'].lower())
        claim = check_claim('Launch price $49 today', facts)
        self.assertFalse(claim['verified'])
        self.assertEqual(claim['verdict'], 'conflicts')
        self.assertEqual(claim['evidence'], '$129')

    def test_material_conflict_quotes_confirmed_fact(self):
        facts = owner_facts(['Full-grain leather'])
        result = check_sentence('Canvas tote', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Full-grain leather')
        self.assertIn('material', result['reason'].lower())


class VerdictTests(unittest.TestCase):
    def test_paraphrased_superlative_never_supported(self):
        # Finest is not in the fixed superlative list, but the paraphrase is
        # still not in the allowlist, so it stays unsupported (blocked).
        facts = owner_facts(['Vegan leather wallet'])
        for text in ('The finest wallet for commuters', 'The best wallet for commuters'):
            with self.subTest(text=text):
                result = check_sentence(text, facts)
                self.assertFalse(result['verified'])
                self.assertEqual(result['verdict'], 'unsupported')
                self.assertIsNone(result['evidence'])

    def test_false_absolute_blocked(self):
        facts = owner_facts(['Vegan leather wallet'])
        for text in ('Always waterproof', 'Never wears out'):
            with self.subTest(text=text):
                result = check_sentence(text, facts)
                self.assertFalse(result['verified'])
                self.assertEqual(result['verdict'], 'unsupported')
                self.assertIsNone(result['evidence'])
                self.assertIn(result['reason'],
                              ('Unapproved superlative or absolute',
                               'Unapproved negation',
                               'Sentence not in approved claims'))
                if text.startswith('Never'):
                    self.assertIn('negation', result['reason'].lower())

    def test_wrong_price_sentence_conflicts(self):
        facts = owner_facts(['$129'])
        result = check_sentence('$49', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], '$129')

    def test_product_type_swap_conflicts(self):
        facts = owner_facts(['Vegan leather wallet'])
        result = check_sentence('Vegan leather tote', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Vegan leather wallet')
        self.assertIn('product', result['reason'].lower())

    def test_supported_claim_quotes_exact_fact(self):
        facts = owner_facts(['Full-grain leather'])
        for text in ('Full-grain leather', 'Full-grain leather.'):
            with self.subTest(text=text):
                claim = check_claim(text, facts)
                self.assertTrue(claim['verified'])
                self.assertEqual(claim['verdict'], 'supported')
                self.assertEqual(claim['evidence'], 'Full-grain leather')
                sentence = check_sentence(text, facts)
                self.assertTrue(sentence['verified'])
                self.assertEqual(sentence['verdict'], 'supported')
                self.assertEqual(sentence['evidence'], 'Full-grain leather')

    def test_legacy_counts_preserved_with_new_verdict_counts(self):
        facts = owner_facts(['Full-grain leather', '$129'])
        packed = check_claims(['Full-grain leather', '$49', 'Bifold compact'], facts)
        self.assertEqual((packed['verified_count'], packed['blocked_count']), (1, 2))
        self.assertEqual(packed['supported_count'], 1)
        self.assertEqual(packed['conflicts_count'], 1)
        self.assertEqual(packed['unsupported_count'], 1)
        by_claim = {r['claim']: r for r in packed['results']}
        self.assertEqual(by_claim['Full-grain leather']['verdict'], 'supported')
        self.assertEqual(by_claim['$49']['verdict'], 'conflicts')
        self.assertEqual(by_claim['Bifold compact']['verdict'], 'unsupported')

    def test_check_pack_keeps_legacy_shape_and_adds_claim_results(self):
        facts = owner_facts(['Full-grain leather', '$129'])
        draft = {'claims': ['Full-grain leather', '$49'],
                 'post': 'Full-grain leather. $49.',
                 'email': 'Full-grain leather.'}
        packed = check_pack(draft, facts)
        # Legacy gate unchanged: one verified explicit claim, one blocked.
        self.assertEqual(packed['verified_count'], 1)
        self.assertEqual(packed['blocked_count'], 1)
        self.assertEqual(packed['blocked_claims'],
                         [{'claim': '$49', 'reason': packed['blocked_claims'][0]['reason']}])
        self.assertIn('Conflicting price', packed['blocked_claims'][0]['reason'])
        # New per-claim verdicts retain legacy booleans.
        by_claim = {r['claim']: r for r in packed['claim_results']}
        self.assertEqual(by_claim['Full-grain leather']['verdict'], 'supported')
        self.assertTrue(by_claim['Full-grain leather']['verified'])
        self.assertEqual(by_claim['Full-grain leather']['evidence'], 'Full-grain leather')
        self.assertEqual(by_claim['$49']['verdict'], 'conflicts')
        self.assertFalse(by_claim['$49']['verified'])
        self.assertEqual(by_claim['$49']['evidence'], '$129')
        self.assertGreaterEqual(packed['supported_count'], 1)
        self.assertGreaterEqual(packed['conflicts_count'], 1)

    def test_policy_block_keeps_factual_verdict_but_final_unverified(self):
        # A factually supported claim blocked by policy stays supported
        # factually, but verified False finally. Policy only adds blocks.
        facts = {'approved_claims': ['$49'], 'sources': ['demo']}
        draft = {'claims': ['$49'], 'post': '$49.', 'email': '$49.'}
        packed = check_pack(draft, facts, checker_policies=['price_claims'])
        self.assertEqual(packed['blocked_count'], 1)
        self.assertIn('price_claims', packed['blocked_claims'][0]['reason'])
        entry = next(r for r in packed['claim_results'] if r['claim'] == '$49')
        self.assertEqual(entry['verdict'], 'supported')
        self.assertFalse(entry['verified'])
        self.assertTrue(entry['blocked'])


if __name__ == '__main__':
    unittest.main()
