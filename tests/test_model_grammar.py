"""Model grammar regression: verbatim safe copy, strict explicit claims, fallback truth.

Socket-free and offline only. Model paths stub spark_for_agent directly;
no transport, no credentials, no live calls. Every model string is
untrusted and independently validated; unsafe candidates fall back to
labelled deterministic drafts.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launchcrew import human_review
from launchcrew.facts import check_claim, check_sentence
from launchcrew.run import make_distinct_draft, run_pipeline

ROOT = Path(__file__).resolve().parents[1]
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
SEED = 'best in Texas'


def spark_result(raw, model='muse-spark-1.3', usage=None):
    return {'mode': 'spark', 'model_used': model, 'attempted': True,
            'attempted_model': model, 'raw_json': raw,
            'usage': dict(usage or {}), 'request_provider': 'meta'}


def fallback_result():
    return {'mode': 'deterministic_fallback', 'model_used': 'none', 'attempted': False}


def owner_facts(claims):
    return {'approved_claims': list(claims), 'sources': ['owner_confirmed_input']}


class GrammarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_demo(self, maker_raw, seed=False, product_facts=None,
                 memory_claims=None, brief=None, approve=False):
        out = Path(self.temp.name) / 'demo.json'
        scout = spark_result({'facts_used': [], 'risks': []})
        maker = spark_result(maker_raw) if maker_raw is not None else fallback_result()
        checker = spark_result({'claims': []})
        with patch.dict(os.environ, {'META_API_KEY': 'offline-fixture', 'META_WONDER_MODEL': ''}):
            with patch('launchcrew.run.spark_for_agent', side_effect=[scout, maker, checker]):
                receipt = run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', ROOT / 'agents',
                                       out, seed_unverified_claim=seed,
                                       model_enabled=True, product_facts=product_facts,
                                       memory_claims=memory_claims, brief=brief,
                                       approve=approve)
        return receipt

    def test_safe_literal_survives_export(self):
        good = 'Designed in Texas'
        post_line = 'Hello Designed in Texas, shop now!'
        email_line = 'Hi Designed in Texas, learn more.'
        receipt = self.run_demo({'claims': [good],
                                 'post_lines': [post_line],
                                 'email_lines': [email_line]},
                                approve=False)
        receipt = human_review.approve_current(receipt, 'demo_human')
        for key in ('maker_draft_v1', 'maker_draft_v2'):
            draft = receipt[key]
            self.assertEqual(draft['draft_origin'], 'model_safe')
            self.assertTrue(draft['model_written'])
            self.assertEqual(draft['post'], post_line)
            self.assertEqual(draft['email'], email_line)
            self.assertNotEqual(draft['post'], draft['email'])
            self.assertTrue(draft['line_evidence'])
            for item in draft['line_evidence']:
                self.assertIn(good, item['evidence'])
        self.assertEqual(receipt['checker_v1']['blocked_count'], 0)
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        current = human_review.current_draft(receipt)
        self.assertEqual(current['post'], post_line)
        self.assertEqual(current['email'], email_line)
        view = human_review.export_view(receipt)
        self.assertEqual(view['exported_draft']['post'], post_line)
        self.assertEqual(view['exported_draft']['email'], email_line)
        texts = [r['claim'] for r in receipt['checker_v2']['claim_results']]
        self.assertTrue(any(post_line.split(',')[0] in t or good in t for t in texts))

    def test_seeded_removal_preserves_safe(self):
        good = 'Designed in Texas'
        post_line = 'Hello Designed in Texas, shop now!'
        email_line = 'Hi Designed in Texas, learn more.'
        receipt = self.run_demo({'claims': [good],
                                 'post_lines': [post_line],
                                 'email_lines': [email_line]},
                                seed=True)
        marker = receipt['seed_unverified_claim']
        self.assertTrue(marker['enabled'])
        self.assertTrue(marker['v1_included'])
        self.assertFalse(marker['v2_included'])
        self.assertTrue(marker['v2_removed'])
        v1 = receipt['maker_draft_v1']
        self.assertEqual(v1['draft_origin'], 'model_safe')
        self.assertTrue(v1['model_written'])
        self.assertIn(post_line, v1['post'])
        self.assertIn(email_line, v1['email'])
        self.assertIn(SEED, v1['post'])
        self.assertIn(SEED, v1['email'])
        self.assertIn(SEED, [c['claim'] for c in receipt['checker_v1']['blocked_claims']])
        v2 = receipt['maker_draft_v2']
        self.assertEqual(v2['draft_origin'], 'model_safe')
        self.assertTrue(v2['model_written'])
        self.assertEqual(v2['post'], post_line)
        self.assertEqual(v2['email'], email_line)
        self.assertNotIn(SEED, v2['post'])
        self.assertNotIn(SEED, v2['email'])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)

    def test_composite_explicit_blocked(self):
        facts = owner_facts(['Full-grain leather'])
        for claim in ('Full-grain leather with extra words',
                      'Full-grain leather and canvas',
                      'Hello Full-grain leather'):
            with self.subTest(claim=claim):
                result = check_claim(claim, facts)
                self.assertFalse(result['verified'])
                self.assertEqual(result['verdict'], 'unsupported')
                self.assertIsNone(result['evidence'])
        exact = check_claim('Full-grain leather', facts)
        self.assertTrue(exact['verified'])
        self.assertEqual(exact['verdict'], 'supported')
        self.assertEqual(exact['evidence'], 'Full-grain leather')

    def test_negation_rejected(self):
        facts = owner_facts(['Full-grain leather'])
        direct = check_sentence('Hello Full-grain leather not canvas!', facts)
        self.assertFalse(direct['verified'])
        self.assertEqual(direct['verdict'], 'unsupported')
        self.assertEqual(direct['reason'], 'Unapproved negation')
        receipt = self.run_demo({'claims': ['Designed in Texas'],
                                 'post_lines': ['Hello Designed in Texas not canvas!'],
                                 'email_lines': ['Hi Designed in Texas never fails.']})
        v1 = receipt['maker_draft_v1']
        self.assertEqual(v1['draft_origin'], 'deterministic_fallback')
        self.assertFalse(v1['model_written'])
        self.assertEqual(v1['post'], v1['email'])
        self.assertNotIn('not canvas', v1['post'])
        self.assertNotIn('never fails', v1['email'])

    def test_new_material_rejected(self):
        facts = owner_facts(['Full-grain leather'])
        direct = check_sentence('Hello Full-grain leather canvas!', facts)
        self.assertFalse(direct['verified'])
        self.assertEqual(direct['verdict'], 'unsupported')
        receipt = self.run_demo({'claims': ['Designed in Texas'],
                                 'post_lines': ['Hello Designed in Texas canvas!'],
                                 'email_lines': ['Hi Designed in Texas suede.']})
        v1 = receipt['maker_draft_v1']
        self.assertEqual(v1['draft_origin'], 'deterministic_fallback')
        self.assertFalse(v1['model_written'])
        self.assertNotIn('canvas', v1['post'])
        self.assertNotIn('suede', v1['email'])

    def test_new_price_rejected(self):
        facts = owner_facts(['$129'])
        conflict = check_sentence('Hello $129 $49!', facts)
        self.assertFalse(conflict['verified'])
        self.assertEqual(conflict['verdict'], 'conflicts')
        facts = owner_facts(['Full-grain leather'])
        unmatched = check_sentence('Hello Full-grain leather $49!', facts)
        self.assertFalse(unmatched['verified'])
        self.assertEqual(unmatched['verdict'], 'unsupported')
        self.assertIn('price', unmatched['reason'].lower())
        receipt = self.run_demo({'claims': ['Designed in Texas'],
                                 'post_lines': ['Hello Designed in Texas $99!'],
                                 'email_lines': ['Hi Designed in Texas $99.']})
        v1 = receipt['maker_draft_v1']
        self.assertEqual(v1['draft_origin'], 'deterministic_fallback')
        self.assertFalse(v1['model_written'])
        self.assertNotIn('$99', v1['post'])

    def test_absolute_rejected(self):
        facts = owner_facts(['Vegan leather wallet'])
        direct = check_sentence('Hello Vegan leather wallet always!', facts)
        self.assertFalse(direct['verified'])
        self.assertEqual(direct['verdict'], 'unsupported')
        receipt = self.run_demo({'claims': ['Designed in Texas'],
                                 'post_lines': ['Hello Designed in Texas always!'],
                                 'email_lines': ['Hi Designed in Texas perfect.']})
        v1 = receipt['maker_draft_v1']
        self.assertEqual(v1['draft_origin'], 'deterministic_fallback')
        self.assertFalse(v1['model_written'])
        self.assertNotIn('always', v1['post'])
        self.assertNotIn('perfect', v1['email'].lower())

    def test_fallback_truth_labels(self):
        # Claims-only safe subset is identical fallback, never model-written.
        receipt = self.run_demo({'claims': ['$49']})
        v1 = receipt['maker_draft_v1']
        self.assertEqual(v1['draft_origin'], 'deterministic_fallback')
        self.assertFalse(v1['model_written'])
        self.assertEqual(v1['model_used'], 'none')
        self.assertEqual(v1['post'], v1['email'])
        # Identical model channels are rejected: distinctness must come from
        # the model, not from code formatting.
        same = self.run_demo({'claims': ['Designed in Texas'],
                              'post_lines': ['Hello Designed in Texas!'],
                              'email_lines': ['Hello Designed in Texas!']})
        self.assertEqual(same['maker_draft_v1']['draft_origin'], 'deterministic_fallback')
        self.assertFalse(same['maker_draft_v1']['model_written'])
        # Deterministic distinct formatter never claims model authorship.
        distinct = make_distinct_draft(['Designed in Texas'])
        self.assertEqual(distinct['draft_origin'], 'deterministic_fallback')
        self.assertFalse(distinct['model_written'])
        self.assertEqual(distinct['model_used'], 'none')

    def test_owner_no_demo_memory_brief(self):
        product = {'material': {'value': 'Full-grain leather', 'confirmed': True, 'source': 'owner'},
                   'contents': {'value': 'Six card slots', 'confirmed': True, 'source': 'owner'},
                   'size': {'value': 'Bifold compact', 'confirmed': True, 'source': 'owner'},
                   'price': {'value': '$129', 'confirmed': True, 'source': 'owner'}}
        demo_claim = '100% vegan PU leather'
        receipt = self.run_demo({'claims': [demo_claim],
                                 'post_lines': ['Hello ' + demo_claim + '!'],
                                 'email_lines': ['Hi ' + demo_claim + '.']},
                                product_facts=product,
                                memory_claims=[demo_claim],
                                brief='Vegan leather wallet launch')
        for key in ('maker_draft_v1', 'maker_draft_v2'):
            draft = receipt[key]
            self.assertIn('Full-grain leather', draft['post'])
            self.assertIn('$129', draft['post'])
            self.assertNotIn(demo_claim, draft['post'])
            self.assertNotIn(demo_claim, draft['email'])
            self.assertNotIn('Vegan leather wallet launch', draft['post'])
        section = receipt['product_facts']
        self.assertEqual(section['mode'], 'owner_input')
        self.assertFalse(section['template_used'])
        self.assertEqual(section['confirmed_claims'],
                         ['Full-grain leather', 'Six card slots', 'Bifold compact', '$129'])
        self.assertEqual(section['allowlist'],
                         ['Full-grain leather', 'Six card slots', 'Bifold compact', '$129'])
        for entry in receipt['scout']['facts_used']:
            self.assertTrue(entry['verified'])
            self.assertEqual(entry['sources'], ['owner_confirmed_input'])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)


if __name__ == '__main__':
    unittest.main()
