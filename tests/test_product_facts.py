"""Slice 1: explicitly confirmed owner product facts with provenance.

Socket-free and offline only. No live model calls, no credentials.

Pasted text, listings, and memory items can at most suggest a fact. A
value becomes evidence only when the owner explicitly confirms it. The
bundled fictional demo template stays available in demo mode only and
never silently becomes owner-confirmed facts.
"""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import adapter
from launchcrew import agents, human_review
from launchcrew.facts import (founder_variant, parse_product_facts,
                              product_section)

ROOT = Path(__file__).resolve().parents[1]
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
DEMO_CLAIMS = ['100% vegan PU leather', 'Designed in Texas', '$49',
               'Vegan leather wallet', 'For Austin commuters']


def field(value, confirmed, source='owner'):
    return {'value': value, 'confirmed': confirmed, 'source': source}


def offline_execute(run_id, product_facts, memory_items=None, seed=False):
    profile = agents.load_agent('Maker', ROOT / 'agents')
    env = {'META_API_KEY': '', 'META_WONDER_MODEL': ''}
    with patch.dict(os.environ, env):
        with patch('launchcrew.run.spark_for_agent', side_effect=AssertionError('no transport keyless')), \
             patch('launchcrew.run.wonder_synthesize_for_scout', side_effect=AssertionError('no transport keyless')):
            return adapter.execute(run_id, IDEA, profile, seed,
                                   memory_items=memory_items or [],
                                   product_facts=product_facts)


class ParseTests(unittest.TestCase):
    def test_none_means_demo_template_mode(self):
        self.assertIsNone(parse_product_facts(None))

    def test_confirmed_vs_suggested_split(self):
        parsed = parse_product_facts({
            'material': field('Full-grain leather', True),
            'size': field('Bifold compact', False, 'pasted_text'),
            'allowed_claims': [field('Stitched by hand', True),
                               field('Maybe waterproof', False, 'listing')],
        })
        self.assertEqual(parsed['confirmed_claims'], ['Full-grain leather', 'Stitched by hand'])
        self.assertEqual([s['value'] for s in parsed['suggested']],
                         ['Bifold compact', 'Maybe waterproof'])
        by_value = {entry['value']: entry for entry in parsed['fields']}
        self.assertEqual(by_value['Full-grain leather']['claim'], 'Full-grain leather')
        self.assertEqual(by_value['Full-grain leather']['label'], 'Material')
        self.assertIsNone(by_value['Bifold compact']['claim'])
        self.assertEqual(by_value['Bifold compact']['source'], 'pasted_text')
        self.assertEqual(by_value['Stitched by hand']['label'], 'Allowed claim')

    def test_unconfirmed_value_never_authorizes(self):
        parsed = parse_product_facts({
            'material': field('Full-grain leather', False),
            'price': field('$129', False, 'listing'),
        })
        self.assertEqual(parsed['confirmed_claims'], [])
        self.assertEqual(len(parsed['suggested']), 2)

    def test_confirmed_empty_rejected(self):
        for bad in ('', '   ', '!!!'):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(ValueError, 'confirmed but empty|Duplicate or empty'):
                    parse_product_facts({'material': field(bad, True)})

    def test_duplicate_confirmed_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate or empty'):
            parse_product_facts({
                'material': field('Full-grain leather', True),
                'allowed_claims': [field('full-grain LEATHER!', True)],
            })

    def test_invalid_types_rejected(self):
        cases = [
            (['not', 'a', 'dict'], 'must be an object'),
            ({'material': 'Full-grain leather'}, 'must be an object'),
            ({'material': {'value': 123, 'confirmed': True}}, 'must be a string'),
            ({'material': {'value': 'x', 'confirmed': 'yes'}}, 'must be true or false'),
            ({'material': {'value': 'x', 'confirmed': 1}}, 'must be true or false'),
            ({'material': {'value': 'x', 'confirmed': True, 'source': 'blog'}}, 'provenance'),
            ({'material': {'value': 'x'}}, 'explicit confirmation'),
            ({'material': {'value': 'x', 'confirmed': True, 'proof': 'y'}}, 'unsupported fields'),
            ({'color': field('brown', True)}, 'unsupported fields'),
            ({'allowed_claims': 'x'}, 'must be a list'),
        ]
        for raw, message in cases:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, message):
                    parse_product_facts(raw)

    def test_bounds_rejected(self):
        with self.assertRaisesRegex(ValueError, 'length limit'):
            parse_product_facts({'material': field('x' * 201, True)})
        with self.assertRaisesRegex(ValueError, 'claim limit'):
            parse_product_facts({'allowed_claims': [field('claim %d' % i, True) for i in range(13)]})
        with self.assertRaisesRegex(ValueError, 'length limit'):
            parse_product_facts({'founder_note': field('x' * 281, True)})

    def test_founder_note_is_one_sentence_and_never_a_claim(self):
        parsed = parse_product_facts({
            'material': field('Full-grain leather', True),
            'founder_note': field('I built this wallet for my commute.', True),
        })
        self.assertEqual(parsed['confirmed_claims'], ['Full-grain leather'])
        founder = parsed['founder_note']
        self.assertTrue(founder['confirmed'])
        self.assertTrue(founder['sentence_ok'])
        self.assertFalse(founder['authorized_as_fact'])
        self.assertEqual(founder['label'], 'Founder note')
        # Decimal prices do not split sentences.
        parsed = parse_product_facts(
            {'founder_note': field('It costs $49.99 today.', True)})
        self.assertTrue(parsed['founder_note']['sentence_ok'])
        for bad in ('First. Second.', 'No terminal punctuation', 'One. Two? Three!'):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(ValueError, 'one complete sentence'):
                    parse_product_facts({'founder_note': field(bad, True)})

    def test_founder_variant_requires_confirmation(self):
        founder = {'value': 'I built this wallet for my commute.', 'confirmed': True,
                   'sentence_ok': True}
        variant = founder_variant(founder, 'Full-grain leather.', 'Full-grain leather.')
        self.assertIn('I built this wallet for my commute.', variant['post'])
        self.assertFalse(variant['authorized'])
        self.assertFalse(variant['verified'])
        self.assertEqual(founder_variant({**founder, 'confirmed': False}, 'a.', 'b.'), None)
        self.assertIsNone(founder_variant(None, 'a.', 'b.'))
        # An empty base draft yields the note alone, never a stray dot lead.
        self.assertEqual(founder_variant(founder, '.', '.')['post'], founder['value'])

    def test_product_section_modes(self):
        demo = product_section(None, DEMO_CLAIMS)
        self.assertEqual(demo['mode'], 'demo_template')
        self.assertTrue(demo['template_used'])
        self.assertEqual(demo['confirmed_claims'], DEMO_CLAIMS)
        self.assertEqual(demo['labels']['price'], 'Price')
        parsed = parse_product_facts({'price': field('$129', True)})
        owner = product_section(parsed, ['$129'])
        self.assertEqual(owner['mode'], 'owner_input')
        self.assertFalse(owner['template_used'])
        self.assertEqual(owner['confirmed_claims'], ['$129'])
        self.assertEqual(owner['labels']['founder_note'], 'Founder note')


class PipelineTests(unittest.TestCase):
    def test_demo_fixture_mode_unchanged(self):
        receipt = offline_execute('run_demo_fixture', None)
        self.assertEqual(receipt['status'], 'completed')
        self.assertIn('$49', receipt['maker_draft_v2']['post'])
        section = receipt['product_facts']
        self.assertEqual(section['mode'], 'demo_template')
        self.assertTrue(section['template_used'])
        self.assertEqual(section['confirmed_claims'], DEMO_CLAIMS)
        self.assertIsNone(section['founder_note'])
        self.assertIsNone(section['draft_variant'])

    def test_owner_confirmed_claims_authorize_drafts(self):
        receipt = offline_execute('run_owner_ok', {
            'material': field('Full-grain leather', True),
            'price': field('$129', True),
        })
        self.assertEqual(receipt['status'], 'completed')
        self.assertIn('Full-grain leather', receipt['maker_draft_v2']['post'])
        self.assertIn('$129', receipt['maker_draft_v2']['post'])
        for demo in DEMO_CLAIMS:
            self.assertNotIn(demo, receipt['maker_draft_v2']['post'])
        section = receipt['product_facts']
        self.assertEqual(section['mode'], 'owner_input')
        self.assertFalse(section['template_used'])
        self.assertEqual(section['confirmed_claims'], ['Full-grain leather', '$129'])
        self.assertEqual(section['fields'][0]['label'], 'Material')
        for entry in receipt['scout']['facts_used']:
            self.assertTrue(entry['verified'])
            self.assertEqual(entry['sources'], ['owner_confirmed_input'])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)

    def test_owner_suggested_values_never_enter_drafts(self):
        receipt = offline_execute('run_owner_suggest', {
            'material': field('Full-grain leather', True),
            'size': field('Bifold compact', False, 'pasted_text'),
        })
        for key in ('post', 'email'):
            self.assertNotIn('Bifold compact', receipt['maker_draft_v1'][key])
            self.assertNotIn('Bifold compact', receipt['maker_draft_v2'][key])
        self.assertNotIn('Bifold compact', receipt['product_facts']['confirmed_claims'])
        self.assertNotIn('Bifold compact', receipt['product_facts']['allowlist'])
        self.assertEqual([s['value'] for s in receipt['product_facts']['suggested']],
                         ['Bifold compact'])

    def test_unconfirmed_memory_cannot_authorize(self):
        memory = [{'id': 'mem_1', 'kind': 'brand_fact', 'title': 'Fact',
                   'content': {'claim': 'Handmade vegan wallet for commuters'}}]
        receipt = offline_execute('run_owner_mem', {
            'material': field('Full-grain leather', True),
        }, memory_items=memory)
        self.assertEqual(receipt['status'], 'completed')
        self.assertNotIn('Handmade vegan wallet for commuters',
                         receipt['maker_draft_v2']['post'])
        self.assertNotIn('Handmade vegan wallet for commuters',
                         receipt['product_facts']['confirmed_claims'])
        self.assertNotIn('Handmade vegan wallet for commuters',
                         receipt['product_facts']['allowlist'])
        suggested = [s for s in receipt['product_facts']['suggested']
                     if s['value'] == 'Handmade vegan wallet for commuters']
        self.assertEqual(len(suggested), 1)
        self.assertEqual(suggested[0]['source'], 'memory')
        self.assertEqual(receipt['memory_claims'], [])
        self.assertEqual(receipt['memory_used'][0]['id'], 'mem_1')

    def test_memory_sourced_confirmation_authorizes_with_provenance(self):
        receipt = offline_execute('run_owner_memsrc', {
            'material': field('Handmade vegan wallet for commuters', True, 'memory'),
        })
        self.assertIn('Handmade vegan wallet for commuters',
                      receipt['maker_draft_v2']['post'])
        self.assertIn('Handmade vegan wallet for commuters',
                      receipt['product_facts']['confirmed_claims'])
        self.assertEqual(receipt['product_facts']['fields'][0]['source'], 'memory')

    def test_demo_template_never_confirmed_in_owner_mode(self):
        receipt = offline_execute('run_owner_nodemo', {'price': field('$129', True)})
        section = receipt['product_facts']
        self.assertFalse(section['template_used'])
        for demo in DEMO_CLAIMS:
            self.assertNotIn(demo, section['confirmed_claims'])
            self.assertNotIn(demo, section['allowlist'])
            self.assertNotIn(demo, receipt['maker_draft_v2']['post'])

    def test_blocked_rule_veto_preserved_in_owner_mode(self):
        memory = [{'id': 'mem_v', 'kind': 'blocked_rule', 'title': 'Veto',
                   'content': {'claim': 'Full-grain leather'}}]
        receipt = offline_execute('run_owner_veto', {
            'material': field('Full-grain leather', True),
        }, memory_items=memory)
        self.assertEqual(receipt['checker_v1']['blocked_count'], 1)
        self.assertEqual(receipt['checker_v1']['blocked_claims'][0]['claim'],
                         'Full-grain leather')
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        self.assertNotIn('Full-grain leather', receipt['maker_draft_v2']['post'])

    def test_empty_owner_input_completes_honestly_without_approval_context(self):
        receipt = offline_execute('run_owner_empty', {})
        self.assertEqual(receipt['status'], 'completed')
        self.assertEqual(receipt['product_facts']['mode'], 'owner_input')
        self.assertEqual(receipt['product_facts']['confirmed_claims'], [])
        ok, _ = human_review.valid_revision_context(receipt)
        self.assertFalse(ok)

    def test_invalid_product_facts_raise_before_pipeline(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate or empty'):
            offline_execute('run_owner_bad', {
                'material': field('Full-grain leather', True),
                'price': field('Full-grain leather', True),
            })

    def test_founder_note_variant_end_to_end(self):
        receipt = offline_execute('run_owner_note', {
            'material': field('Full-grain leather', True),
            'founder_note': field('I built this wallet for my commute.', True),
        })
        self.assertEqual(receipt['status'], 'completed')
        variant = receipt['product_facts']['draft_variant']
        self.assertIn('I built this wallet for my commute.', variant['post'])
        self.assertIn('I built this wallet for my commute.', variant['email'])
        self.assertFalse(variant['authorized'])
        self.assertFalse(variant['verified'])
        self.assertFalse(receipt['product_facts']['founder_note']['authorized_as_fact'])
        self.assertNotIn('I built this wallet for my commute.',
                         receipt['maker_draft_v2']['post'])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)

    def test_unconfirmed_founder_feeds_no_variant(self):
        receipt = offline_execute('run_owner_note_sug', {
            'founder_note': field('I built this wallet for my commute.', False),
        })
        self.assertIsNone(receipt['product_facts']['draft_variant'])
        self.assertEqual([s['value'] for s in receipt['product_facts']['suggested']],
                         ['I built this wallet for my commute.'])

    def test_owner_seed_still_blocked_by_deterministic_checker(self):
        receipt = offline_execute('run_owner_seed', {
            'material': field('Full-grain leather', True),
        }, seed=True)
        self.assertIn('best in Texas', [c['claim'] for c in receipt['checker_v1']['blocked_claims']])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        self.assertNotIn('best in Texas', receipt['maker_draft_v2']['post'])


if __name__ == '__main__':
    unittest.main()
