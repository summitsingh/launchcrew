"""Slice 1 specificity floor for vague quality wording.

Socket-free and offline only. No model calls, no credentials.
"""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launchcrew.checker_policies import specificity_blocks, specificity_hits, specificity_reason
from launchcrew.run import check_pack, run_pipeline

ROOT = Path(__file__).resolve().parents[1]
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


def owner_facts(claims):
    return {'approved_claims': list(claims), 'sources': ['owner_confirmed_input']}


class SpecificityUnitTests(unittest.TestCase):
    def test_hits_and_reason(self):
        self.assertEqual(specificity_hits('Premium finish'), ['premium'])
        self.assertTrue(specificity_blocks('High quality wallet'))
        self.assertEqual(specificity_hits('High-Quality!'), ['high quality'])
        reason = specificity_reason('Premium finish')
        self.assertIn('specificity', reason.lower())
        self.assertIn('vague', reason.lower())
        self.assertIn('premium', reason)

    def test_case_punctuation_boundaries(self):
        for text in ('PREMIUM', 'Premium!', '(premium)', 'world CLASS', 'TOP-QUALITY'):
            with self.subTest(text=text):
                self.assertTrue(specificity_blocks(text), text)

    def test_no_substring_false_positives(self):
        for text in ('premiumquality finish', 'superiority claim', 'superexcellent',
                     'Full-grain leather', 'Vegan leather wallet', 'Designed in Texas', '$129'):
            with self.subTest(text=text):
                self.assertFalse(specificity_blocks(text), text)

    def test_punctuation_without_spaces_separates_words(self):
        self.assertEqual(specificity_hits('premium,leather'), ['premium'])
        self.assertEqual(specificity_hits('high,quality'), ['high quality'])
        for text in ('premium,leather wallet', 'The premium,leather wallet',
                     'high,quality wallet', 'high:quality wallet', 'TOP/QUALITY wallet',
                     'world_class act', 'first_class seating', 'luxury,deluxe set'):
            with self.subTest(text=text):
                self.assertTrue(specificity_blocks(text), text)

    def test_no_cross_sentence_phrase_false_positives(self):
        for text in ('How high. Quality matters.', 'Top. Quality picks here.',
                     'World. Class act tonight.', 'First. Class seating available.',
                     'The rating was high. Quality was audited.',
                     'High\nQuality wallet', 'Top\nQuality picks'):
            with self.subTest(text=text):
                self.assertFalse(specificity_blocks(text), text)
        self.assertTrue(specificity_blocks('Premium. Leather wallet.'))

    def test_joined_substrings_still_safe(self):
        for text in ('highquality', 'topquality', 'worldclass', 'firstclass',
                     'The highquality finish', 'A topquality pick',
                     'An exquisitex item', 'Deluxed model'):
            with self.subTest(text=text):
                self.assertFalse(specificity_blocks(text), text)


class SpecificityCheckPackTests(unittest.TestCase):
    def test_explicit_supported_vague_veto_keeps_verdict(self):
        facts = owner_facts(['Premium leather wallet', 'Full-grain leather'])
        draft = {'claims': ['Premium leather wallet'], 'post': 'Premium leather wallet.',
                 'email': 'Full-grain leather.'}
        packed = check_pack(draft, facts)
        self.assertEqual(packed['blocked_count'], 1)
        self.assertIn('specificity', packed['blocked_claims'][0]['reason'].lower())
        entry = next(r for r in packed['claim_results'] if r['claim'] == 'Premium leather wallet')
        self.assertEqual(entry['verdict'], 'supported')
        self.assertFalse(entry['verified'])
        self.assertTrue(entry['blocked'])
        self.assertIn('Remove Premium leather wallet', packed['revision_instructions'][0])

    def test_omitted_claims_unsupported_vague_still_blocked(self):
        facts = owner_facts(['Full-grain leather'])
        draft = {'claims': [], 'post': 'Premium finish for commuters.', 'email': ''}
        packed = check_pack(draft, facts)
        self.assertEqual(packed['blocked_count'], 1)
        self.assertIn('specificity', packed['blocked_claims'][0]['reason'].lower())

    def test_omitted_claims_supported_vague_still_blocked(self):
        facts = owner_facts(['Premium leather wallet'])
        draft = {'claims': [], 'post': 'Premium leather wallet.', 'email': ''}
        packed = check_pack(draft, facts)
        self.assertEqual(packed['blocked_count'], 1)
        entry = next(r for r in packed['claim_results'] if r['claim'] == 'Premium leather wallet')
        self.assertEqual(entry['verdict'], 'supported')
        self.assertFalse(entry['verified'])

    def test_standard_and_strict_both_enforce(self):
        facts = owner_facts(['Premium leather wallet'])
        draft = {'claims': ['Premium leather wallet'], 'post': 'Premium leather wallet.',
                 'email': 'Premium leather wallet.'}
        for profile in ('standard', 'strict'):
            with self.subTest(profile=profile):
                packed = check_pack(draft, facts, checker_profile=profile)
                self.assertGreaterEqual(packed['blocked_count'], 1)
                self.assertIn('specificity', packed['blocked_claims'][0]['reason'].lower())

    def test_existing_policy_precedence_preserved(self):
        facts = owner_facts(['Amazing premium wallet'])
        draft = {'claims': ['Amazing premium wallet'], 'post': 'Amazing premium wallet.',
                 'email': 'Amazing premium wallet.'}
        strict = check_pack(draft, facts, checker_profile='strict')
        self.assertIn('superlatives', strict['blocked_claims'][0]['reason'])
        standard = check_pack(draft, facts, checker_profile='standard')
        self.assertIn('specificity', standard['blocked_claims'][0]['reason'].lower())

    def test_concrete_facts_retain_behavior(self):
        facts = owner_facts(['Full-grain leather', '$129'])
        draft = {'claims': ['Full-grain leather'], 'post': 'Full-grain leather.', 'email': '$129.'}
        packed = check_pack(draft, facts)
        self.assertEqual(packed['blocked_count'], 0)
        self.assertEqual(packed['verified_count'], 1)


class SpecificityPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_v1_blocks_vague_memory_v2_cleans(self):
        out = Path(self.temp.name) / 'spec.json'
        with patch('launchcrew.spark.urlopen', side_effect=AssertionError('no transport')):
            receipt = run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', ROOT / 'agents', out,
                                   model_enabled=False, memory_claims=['Premium leather wallet'])
        blocked = receipt['checker_v1']['blocked_claims']
        self.assertTrue(any('specificity' in b['reason'].lower() for b in blocked))
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        self.assertNotIn('Premium leather wallet', receipt['maker_draft_v2']['post'])

    def test_recheck_rejects_vague_accepts_clean(self):
        from launchcrew import human_review
        out = Path(self.temp.name) / 'clean.json'
        with patch('launchcrew.spark.urlopen', side_effect=AssertionError('no transport')):
            receipt = run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', ROOT / 'agents', out,
                                   model_enabled=False)
        vague = human_review.recheck_text('Premium wallet for commuters.', 'Designed in Texas.', receipt)
        self.assertGreater(vague['blocked_count'], 0)
        self.assertTrue(any('specificity' in b['reason'].lower() for b in vague['blocked_claims']))
        clean = human_review.recheck_text('Designed in Texas.', 'Designed in Texas.', receipt)
        self.assertEqual(clean['blocked_count'], 0)


def make_prelint_vague_receipt(base_receipt, vague_claim='Premium leather wallet'):
    receipt = copy.deepcopy(base_receipt)
    receipt['approval_state'] = 'pending_approval'
    receipt['approvals'] = []
    receipt['approved_revision'] = None
    receipt['approval_binding'] = None
    scout_sources = list((receipt.get('scout') or {}).get('sources') or ['owner_confirmed_input'])
    if not scout_sources:
        scout_sources = ['owner_confirmed_input']
    facts_used = list((receipt.get('scout') or {}).get('facts_used') or [])
    if vague_claim not in [e.get('claim') for e in facts_used if isinstance(e, dict)]:
        facts_used.append({'claim': vague_claim, 'verified': True, 'verdict': 'supported',
                           'evidence': vague_claim, 'sources': list(scout_sources)})
    receipt['scout']['facts_used'] = facts_used
    pf = dict(receipt.get('product_facts') or {})
    confirmed = list(pf.get('confirmed_claims') or [])
    if vague_claim not in confirmed:
        confirmed.append(vague_claim)
    pf['confirmed_claims'] = confirmed
    allowlist = list(pf.get('allowlist') or [])
    if vague_claim not in allowlist:
        allowlist.append(vague_claim)
    pf['allowlist'] = allowlist
    receipt['product_facts'] = pf
    v2 = dict(receipt.get('maker_draft_v2') or {})
    v2['post'] = vague_claim + '.'
    v2['email'] = vague_claim + '.'
    v2['claims'] = [vague_claim]
    receipt['maker_draft_v2'] = v2
    receipt['checker_v2'] = {
        'verified_count': 1,
        'blocked_count': 0,
        'blocked_claims': [],
        'revision_instructions': [],
        'claim_results': [
            {'claim': vague_claim, 'verified': True, 'verdict': 'supported',
             'evidence': vague_claim, 'reason': 'Matched approved claim',
             'blocked': False, 'source': 'explicit_claim'}
        ],
        'supported_count': 1,
        'unsupported_count': 0,
        'conflicts_count': 0,
    }
    return receipt


class SpecificityApprovalGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _base_receipt(self, name):
        out = Path(self.temp.name) / name
        with patch('launchcrew.spark.urlopen', side_effect=AssertionError('no transport')):
            return run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', ROOT / 'agents', out,
                                model_enabled=False)

    def test_new_approval_refused_for_prelint_clean_vague(self):
        from launchcrew import human_review
        base = self._base_receipt('base1.json')
        vague = make_prelint_vague_receipt(base)
        self.assertEqual(human_review.current_check(vague)['blocked_count'], 0)
        with self.assertRaises(ValueError) as ctx:
            human_review.approve_current(vague, 'tester')
        self.assertIn('specificity', str(ctx.exception).lower())

    def test_prior_bound_approved_vague_cannot_export(self):
        from launchcrew import human_review
        base = self._base_receipt('base2.json')
        vague = make_prelint_vague_receipt(base)
        binding = human_review.approval_binding(vague)
        vague['approvals'] = [{'approved_by': 'tester', 'action': 'approved_for_export',
                               'timestamp': '2026-01-01T00:00:00+00:00', 'revision': 0,
                               'binding_version': binding['version'],
                               'binding_digest': binding['digest']}]
        vague['approval_state'] = 'approved_for_export'
        vague['approved_revision'] = 0
        vague['approval_binding'] = dict(binding)
        bound, _ = human_review.binding_status(vague)
        self.assertTrue(bound)
        self.assertFalse(human_review.exportable(vague))
        with self.assertRaises(ValueError) as ctx_export:
            human_review.record_export(vague, 'tester')
        self.assertIn('specificity', str(ctx_export.exception).lower())
        with self.assertRaises(ValueError) as ctx_view:
            human_review.export_view(vague)
        self.assertIn('specificity', str(ctx_view.exception).lower())

    def test_clean_approval_export_controls_unchanged(self):
        from launchcrew import human_review
        base = self._base_receipt('base3.json')
        self.assertFalse(specificity_blocks(base['maker_draft_v2']['post']))
        self.assertFalse(specificity_blocks(base['maker_draft_v2']['email']))
        approved = human_review.approve_current(base, 'tester')
        self.assertEqual(approved['approval_state'], 'approved_for_export')
        self.assertTrue(human_review.exportable(approved))
        exported = human_review.record_export(approved, 'tester')
        self.assertEqual(exported['exported_revision'], 0)
        view = human_review.export_view(approved)
        self.assertIn('exported_draft', view)


if __name__ == '__main__':
    unittest.main()
