"""Maker distinct post/email, fallback labelling, and seed marker.

Socket-free and offline only. Model paths stub spark_for_agent directly;
no transport, no credentials, no live calls. Every model string is
untrusted and independently validated; unsafe candidates fall back to
labelled deterministic drafts. The demo seed stays deterministic in v1
with an explicit receipt marker and is removed in v2.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launchcrew.run import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
SEED = 'best in Texas'
NOTE = 'I built this wallet for my commute.'


def spark_result(raw, model='muse-spark-1.3', usage=None):
    return {'mode': 'spark', 'model_used': model, 'attempted': True,
            'attempted_model': model, 'raw_json': raw,
            'usage': dict(usage or {}), 'request_provider': 'meta'}


def fallback_result():
    return {'mode': 'deterministic_fallback', 'model_used': 'none', 'attempted': False}


class DistinctCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_demo(self, maker_raw, seed=False, scout_raw=None, checker_raw=None,
                 model_enabled=True, product_facts=None):
        out = Path(self.temp.name) / 'demo.json'
        scout = spark_result(scout_raw or {'facts_used': [], 'risks': []})
        maker = spark_result(maker_raw) if maker_raw is not None else fallback_result()
        # Checker suggestion shape stays claims-only; empty keeps gates clean.
        checker = spark_result(checker_raw if checker_raw is not None else {'claims': []})
        key = 'offline-fixture' if model_enabled else ''
        with patch.dict(os.environ, {'META_API_KEY': key, 'META_WONDER_MODEL': ''}):
            with patch('launchcrew.run.spark_for_agent', side_effect=[scout, maker, checker]):
                receipt = run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', ROOT / 'agents',
                                       out, seed_unverified_claim=seed,
                                       model_enabled=model_enabled,
                                       product_facts=product_facts)
        return receipt

    def test_structured_model_copy_is_distinct_with_metadata(self):
        good = 'Designed in Texas'
        post_line = 'Hello Designed in Texas, shop now!'
        email_line = 'Hi Designed in Texas, learn more.'
        receipt = self.run_demo({'claims': [good],
                                 'post_lines': [post_line],
                                 'email_lines': [email_line]})
        v1 = receipt['maker_draft_v1']
        self.assertEqual(v1['draft_origin'], 'model_safe')
        self.assertTrue(v1['model_written'])
        self.assertEqual(v1['maker_schema'], 'structured_post_email')
        self.assertEqual(v1['model_used'], 'muse-spark-1.3')
        self.assertNotEqual(v1['post'], v1['email'])
        self.assertEqual(v1['post'], post_line)
        self.assertEqual(v1['email'], email_line)
        v2 = receipt['maker_draft_v2']
        self.assertEqual(v2['draft_origin'], 'model_safe')
        self.assertTrue(v2['model_written'])
        self.assertEqual(v2['post'], post_line)
        self.assertEqual(v2['email'], email_line)
        self.assertNotEqual(v2['post'], v2['email'])
        self.assertEqual(receipt['checker_v1']['blocked_count'], 0)
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        marker = receipt['seed_unverified_claim']
        self.assertFalse(marker['enabled'])
        self.assertIsNone(marker['claim'])
        self.assertFalse(marker['v1_included'])
        self.assertFalse(marker['v2_included'])

    def test_legacy_claims_only_model_builds_distinct_draft(self):
        # Claims-only safe subset without verbatim channels is deterministic
        # identical fallback, never labelled model-written.
        good = '$49'
        receipt = self.run_demo({'claims': [good]})
        v1 = receipt['maker_draft_v1']
        self.assertEqual(v1['draft_origin'], 'deterministic_fallback')
        self.assertFalse(v1['model_written'])
        self.assertEqual(v1['maker_schema'], 'legacy_claims_only')
        self.assertEqual(v1['model_used'], 'none')
        self.assertEqual(v1['post'], v1['email'])
        self.assertIn(good, v1['post'])
        self.assertIn(good, v1['email'])
        self.assertEqual(v1['claims'], [good])
        self.assertEqual(receipt['checker_v1']['blocked_count'], 0)

    def test_unsafe_model_rejected_to_labelled_fallback(self):
        # Model proposes only the blocked seed claim; safe filtering empties
        # it, so the pipeline falls back to original allowlist claims.
        receipt = self.run_demo({'claims': [SEED],
                                 'post_lines': [SEED],
                                 'email_lines': [SEED]})
        v1 = receipt['maker_draft_v1']
        self.assertEqual(v1['draft_origin'], 'deterministic_fallback')
        self.assertFalse(v1['model_written'])
        self.assertEqual(v1['maker_schema'], 'none_fallback')
        self.assertEqual(v1['model_used'], 'none')
        # Fallback stays identical and safe.
        self.assertEqual(v1['post'], v1['email'])
        self.assertNotIn(SEED, v1['post'])
        self.assertEqual(receipt['checker_v1']['blocked_count'], 0)

    def test_keyless_fallback_labelled_and_safe(self):
        out = Path(self.temp.name) / 'fallback.json'
        with patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''}):
            with patch('launchcrew.run.spark_for_agent',
                       side_effect=AssertionError('no transport keyless')):
                receipt = run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', ROOT / 'agents',
                                       out, model_enabled=True)
        for key in ('maker_draft_v1', 'maker_draft_v2'):
            draft = receipt[key]
            self.assertEqual(draft['draft_origin'], 'deterministic_fallback')
            self.assertFalse(draft['model_written'])
        self.assertEqual(receipt['maker_draft_v1']['post'],
                         receipt['maker_draft_v1']['email'])
        self.assertEqual(receipt['model_usage']['spark_calls'], 0)
        self.assertEqual(receipt['model_usage']['model_used'], 'none')

    def test_seed_marker_fallback_path(self):
        out = Path(self.temp.name) / 'seed.json'
        with patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''}):
            with patch('launchcrew.run.spark_for_agent',
                       side_effect=AssertionError('no transport keyless')):
                receipt = run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', ROOT / 'agents',
                                       out, seed_unverified_claim=True,
                                       model_enabled=True)
        marker = receipt['seed_unverified_claim']
        self.assertTrue(marker['enabled'])
        self.assertEqual(marker['claim'], SEED)
        self.assertTrue(marker['v1_included'])
        self.assertFalse(marker['v2_included'])
        self.assertTrue(marker['v2_removed'])
        self.assertIn(SEED, receipt['maker_draft_v1']['post'])
        self.assertIn(SEED, [c['claim'] for c in receipt['checker_v1']['blocked_claims']])
        self.assertNotIn(SEED, receipt['maker_draft_v2']['post'])
        self.assertNotIn(SEED, receipt['maker_draft_v2']['email'])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        self.assertEqual(receipt['maker_draft_v1']['draft_origin'], 'deterministic_fallback')

    def test_seed_marker_model_path(self):
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
        self.assertNotEqual(v1['post'], v1['email'])
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
        self.assertNotEqual(v2['post'], v2['email'])
        self.assertNotIn(SEED, v2['post'])
        self.assertNotIn(SEED, v2['email'])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)

    def test_model_founder_note_never_becomes_approved(self):
        product = {'material': {'value': 'Full-grain leather', 'confirmed': True, 'source': 'owner'},
                   'founder_note': {'value': NOTE, 'confirmed': True, 'source': 'owner'}}
        receipt = self.run_demo({'claims': [NOTE],
                                 'post_lines': [NOTE],
                                 'email_lines': [NOTE]},
                                product_facts=product)
        # Raw founder note is unverified and rejected; drafts use confirmed
        # owner facts only.
        self.assertNotIn(NOTE, receipt['maker_draft_v1']['post'])
        self.assertNotIn(NOTE, receipt['maker_draft_v2']['post'])
        self.assertNotIn(NOTE, receipt['product_facts']['confirmed_claims'])
        self.assertNotIn(NOTE, receipt['product_facts']['allowlist'])
        variant = receipt['product_facts']['draft_variant']
        self.assertIn(NOTE, variant['post'])
        self.assertFalse(variant['authorized'])
        self.assertFalse(variant['verified'])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        self.assertIn('Full-grain leather', receipt['maker_draft_v2']['post'])


if __name__ == '__main__':
    unittest.main()
