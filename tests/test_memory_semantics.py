"""Memory semantics: learned examples affect prompts, learned rules affect verdicts.

Socket-free and offline only. Provider paths stub the transport boundary
(launchcrew.spark.urlopen). No live model calls.
"""
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import adapter
from launchcrew import agents
from launchcrew.run import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


def completion(raw):
    return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(raw)}}],
                                  'usage': {}}).encode())


def base_profile(name):
    return {
        'name': name,
        'role': 'Custom role for ' + name,
        'department': 'Growth',
        'personality': 'Custom personality for ' + name,
        'expertise': 'Custom expertise for ' + name,
        'decision_rules': ['Use facts file first'],
        'veto_scope': [],
        'tools_allowed': ['facts_file', 'spark_strict_json', 'receipt_log', 'claim_check'],
        'spend_limit': 0,
        'approval_level': 'approve_each',
        'examples': [],
    }


def capture_stub(captured):
    def fake(request, timeout=30):
        payload = json.loads(request.data.decode())
        captured.append(payload)
        required = payload['response_format']['json_schema']['schema']['required']
        if 'facts_used' in required:
            return completion({'facts_used': [], 'risks': []})
        return completion({'claims': []})
    return fake


class MemoryEffectsTests(unittest.TestCase):
    def test_only_brand_fact_extends_allowlist(self):
        items = [
            {'id': 'mem_1', 'kind': 'brand_fact', 'title': 'Fact',
             'content': {'claim': 'Handmade vegan wallet for commuters'}},
            {'id': 'mem_2', 'kind': 'profile', 'title': 'Prof',
             'content': {'claim': 'Handmade vegan wallet for commuters', 'expertise': 'Austin voice'}},
            {'id': 'mem_3', 'kind': 'approval_example', 'title': 'Ex',
             'content': {'claim': 'Handmade vegan wallet for commuters', 'idea': 'i', 'post': 'p', 'email': 'e'}},
        ]
        claims, blocked, rules, expertise, examples, used = adapter._memory_effects(items)
        self.assertEqual(claims, ['Handmade vegan wallet for commuters'])
        self.assertEqual(blocked, [])
        self.assertEqual(expertise, 'Austin voice')
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]['id'], 'mem_3')
        self.assertEqual([u['id'] for u in used], ['mem_1', 'mem_2', 'mem_3'])

    def test_blocked_rule_string_and_learned_dict_formats(self):
        items = [
            {'id': 'a', 'kind': 'blocked_rule', 'title': 'Explicit',
             'content': {'claim': 'best in Texas'}},
            {'id': 'b', 'kind': 'blocked_rule', 'title': 'Learned',
             'content': {'blocked_claims': [{'claim': 'Amazing vegan wallet', 'reason': 'Seed reason'}]}},
            {'id': 'c', 'kind': 'blocked_rule', 'title': 'Mixed',
             'content': {'blocked_claims': ['extra claim', 123, {'nope': 1}, '', {'claim': ''}]}},
        ]
        claims, blocked, rules, _, _, _ = adapter._memory_effects(items)
        self.assertEqual(claims, [])
        self.assertIn('best in Texas', blocked)
        self.assertIn('Amazing vegan wallet', blocked)
        self.assertIn('extra claim', blocked)
        self.assertEqual(len(blocked), 3)
        reasons = {r['claim']: r['reason'] for r in rules}
        self.assertEqual(reasons['Amazing vegan wallet'], 'Seed reason')
        self.assertEqual(reasons['best in Texas'], 'Selected memory rule')

    def test_malformed_blocked_values_never_become_facts(self):
        items = [{'id': 'm', 'kind': 'blocked_rule', 'title': 'Bad',
                  'content': {'blocked_claims': [123, None, {'claim': 5}, {'reason': 'x'}], 'claim': 42}}]
        claims, blocked, _, _, _, _ = adapter._memory_effects(items)
        self.assertEqual(claims, [])
        self.assertEqual(blocked, [])

    def test_learned_blocked_rule_filters_real_candidate_claim(self):
        # The $49 price claim occurs naturally in the approved facts, so the
        # learned rule filters a real candidate instead of a manufactured one.
        profile = agents.load_agent('Maker', ROOT / 'agents')
        env = {'META_API_KEY': '', 'META_WONDER_MODEL': ''}
        with patch.dict(os.environ, env):
            with patch('launchcrew.run.spark_for_agent', side_effect=AssertionError('no transport keyless')), \
                 patch('launchcrew.run.wonder_synthesize_for_scout', side_effect=AssertionError('no transport keyless')):
                clean = adapter.execute('run_clean', IDEA, profile, False, memory_items=[])
                self.assertEqual(clean['checker_v1']['blocked_count'], 0)
                self.assertIn('$49', clean['maker_draft_v1']['post'])
                learned = {'id': 'mem_l', 'kind': 'blocked_rule', 'title': 'Learned',
                           'content': {'blocked_claims': [{'claim': '$49', 'reason': 'Price out of scope'}]}}
                blocked_receipt = adapter.execute('run_blocked', IDEA, profile, False, memory_items=[learned])
                self.assertEqual(blocked_receipt['checker_v1']['blocked_count'], 1)
                self.assertIn('$49', [c['claim'] for c in blocked_receipt['checker_v1']['blocked_claims']])
                self.assertEqual(blocked_receipt['checker_v2']['blocked_count'], 0)
                self.assertNotIn('$49', blocked_receipt['maker_draft_v2']['post'])
                self.assertEqual(blocked_receipt['memory_blocked_rules'][0]['claim'], '$49')
                self.assertEqual(blocked_receipt['memory_examples'], [])
                # Editing the rule to another real approved claim changes the verdict identity.
                edited = {'id': 'mem_l', 'kind': 'blocked_rule', 'title': 'Learned',
                          'content': {'blocked_claims': [{'claim': 'Designed in Texas', 'reason': 'Edited rule'}]}}
                edited_receipt = adapter.execute('run_edited', IDEA, profile, False, memory_items=[edited])
                self.assertEqual([c['claim'] for c in edited_receipt['checker_v1']['blocked_claims']], ['Designed in Texas'])
                self.assertNotIn('Designed in Texas', edited_receipt['maker_draft_v2']['post'])
                self.assertIn('$49', edited_receipt['maker_draft_v2']['post'])
                # The first draft still carries every real candidate; the
                # verdict identity and the final revision change instead.
                self.assertEqual(edited_receipt['maker_draft_v1']['post'], blocked_receipt['maker_draft_v1']['post'])
                self.assertNotEqual(edited_receipt['maker_draft_v2']['post'], blocked_receipt['maker_draft_v2']['post'])
                deleted = adapter.execute('run_deleted', IDEA, profile, False, memory_items=[])
                self.assertEqual(deleted['checker_v1']['blocked_count'], 0)
                self.assertIn('$49', deleted['maker_draft_v2']['post'])
                # Past receipts are snapshots: the blocked receipt still records its rule.
                self.assertEqual(blocked_receipt['memory_blocked_rules'][0]['claim'], '$49')

    def test_absent_blocked_claim_is_never_manufactured(self):
        # A memory rule for a claim in no candidate stays recorded but active
        # with zero blocks: it never enters the first draft or the counts.
        profile = agents.load_agent('Maker', ROOT / 'agents')
        env = {'META_API_KEY': '', 'META_WONDER_MODEL': ''}
        with patch.dict(os.environ, env):
            with patch('launchcrew.run.spark_for_agent', side_effect=AssertionError('no transport keyless')), \
                 patch('launchcrew.run.wonder_synthesize_for_scout', side_effect=AssertionError('no transport keyless')):
                learned = {'id': 'mem_absent', 'kind': 'blocked_rule', 'title': 'Learned',
                           'content': {'blocked_claims': [{'claim': 'best in Texas', 'reason': 'Not in this catalog'}]}}
                receipt = adapter.execute('run_absent', IDEA, profile, False, memory_items=[learned])
                self.assertEqual(receipt['memory_blocked_rules'][0]['claim'], 'best in Texas')
                self.assertEqual(receipt['checker_v1']['blocked_count'], 0)
                self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
                self.assertNotIn('best in Texas', receipt['maker_draft_v1']['post'])
                self.assertNotIn('best in Texas', receipt['maker_draft_v2']['post'])

    def test_unsupported_brand_fact_cannot_become_approved_fact(self):
        # An unsupported memory claim is refused by the deterministic floor,
        # never extended into the approved facts.
        import tempfile
        from launchcrew.run import run_pipeline
        with tempfile.TemporaryDirectory() as directory:
            out = str(Path(directory) / 'bad.json')
            with self.assertRaisesRegex(ValueError, 'Approved facts failed deterministic checks'):
                run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', ROOT / 'agents', out,
                             memory_claims=['best in Texas'], model_enabled=False)

    def test_approval_example_changes_provider_request_not_keyless_draft(self):
        profile = agents.load_agent('Maker', ROOT / 'agents')
        example = {'id': 'mem_e', 'kind': 'approval_example', 'title': 'Learned example',
                   'content': {'idea': IDEA, 'post': 'Designed in Texas wallet post UNIQUE-STYLE-1',
                               'email': 'Designed in Texas wallet email UNIQUE-STYLE-1'}}
        with patch.dict(os.environ, {'META_API_KEY': 'test-key', 'META_WONDER_MODEL': ''}):
            captured = []
            with patch('launchcrew.spark.urlopen', side_effect=capture_stub(captured)):
                adapter.execute('run_ex1', IDEA, profile, False, memory_items=[example])
            maker_calls = [p for p in captured if 'WordSmith' in p['messages'][0]['content'] or 'Maker' in p['messages'][0]['content']]
            self.assertTrue(captured)
            joined = json.dumps(captured)
            self.assertIn('UNIQUE-STYLE-1', joined)
            self.assertIn('Untrusted', joined)
            self.assertIn('never an approved fact', joined)
            edited = copy.deepcopy(example)
            edited['content']['post'] = 'Designed in Texas wallet post UNIQUE-STYLE-2'
            edited['content']['email'] = 'Designed in Texas wallet email UNIQUE-STYLE-2'
            captured2 = []
            with patch('launchcrew.spark.urlopen', side_effect=capture_stub(captured2)):
                adapter.execute('run_ex2', IDEA, profile, False, memory_items=[edited])
            self.assertIn('UNIQUE-STYLE-2', json.dumps(captured2))
            self.assertNotIn('UNIQUE-STYLE-1', json.dumps(captured2))
            captured3 = []
            with patch('launchcrew.spark.urlopen', side_effect=capture_stub(captured3)):
                adapter.execute('run_ex3', IDEA, profile, False, memory_items=[])
            self.assertNotIn('UNIQUE-STYLE', json.dumps(captured3))
        with patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''}):
            with patch('launchcrew.run.spark_for_agent', side_effect=AssertionError('no transport')), \
                 patch('launchcrew.run.wonder_synthesize_for_scout', side_effect=AssertionError('no transport')):
                with_examples = adapter.execute('run_k1', IDEA, profile, False, memory_items=[example])
                without = adapter.execute('run_k2', IDEA, profile, False, memory_items=[])
            self.assertEqual(with_examples['maker_draft_v1']['post'], without['maker_draft_v1']['post'])
            self.assertEqual(with_examples['maker_draft_v2']['post'], without['maker_draft_v2']['post'])
            self.assertEqual(with_examples['model_usage']['mode'], 'deterministic_fallback')
            self.assertEqual(with_examples['model_usage']['spark_calls'], 0)
            self.assertEqual(len(with_examples['memory_examples']), 1)
            self.assertEqual(with_examples['memory_examples'][0]['id'], 'mem_e')

    def test_unsupported_claims_stay_blocked_with_examples_selected(self):
        profile = agents.load_agent('Maker', ROOT / 'agents')
        example = {'id': 'mem_e', 'kind': 'approval_example', 'title': 'Ex',
                   'content': {'idea': IDEA, 'post': 'Vegan leather wallet post', 'email': 'Vegan leather wallet email'}}
        with patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''}):
            with patch('launchcrew.run.spark_for_agent', side_effect=AssertionError('no transport')), \
                 patch('launchcrew.run.wonder_synthesize_for_scout', side_effect=AssertionError('no transport')):
                receipt = adapter.execute('run_seed', IDEA, profile, True, memory_items=[example])
        self.assertIn('best in Texas', [c['claim'] for c in receipt['checker_v1']['blocked_claims']])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        self.assertNotIn('best in Texas', receipt['maker_draft_v2']['post'])

    def test_multiline_personality_expertise_persist_edit_clone_and_reach_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            maker = base_profile('WordSmith')
            maker['personality'] = 'Line one\nLine two\nLine three'
            maker['expertise'] = 'Austin voice\nSecond line'
            agents.create_agent(maker, directory)
            loaded = agents.load_agent('wordsmith', directory)
            self.assertIn('\n', loaded['personality'])
            edited = dict(loaded)
            edited['personality'] = 'Edited one\nEdited two'
            edited['expertise'] = 'Edited expertise\nMore'
            agents.edit_agent('wordsmith', edited, directory)
            self.assertIn('Edited two', agents.load_agent('wordsmith', directory)['personality'])
            agents.clone_agent('wordsmith', 'WordSmithCopy', directory)
            cloned = agents.load_agent('wordsmithcopy', directory)
            self.assertIn('Edited two', cloned['personality'])
            out = Path(directory) / 'm.json'
            with patch.dict(os.environ, {'META_API_KEY': 'test-key', 'META_WONDER_MODEL': ''}):
                captured = []
                with patch('launchcrew.spark.urlopen', side_effect=capture_stub(captured)):
                    run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', directory, out,
                                 maker_profile=cloned, scout_profile=base_profile('ScoutX'),
                                 checker_agent=base_profile('CheckX'))
            maker_payloads = [p for p in captured if 'Edited one' in json.dumps(p)]
            self.assertTrue(maker_payloads)
            self.assertIn('Edited two', json.dumps(maker_payloads[0]))
            self.assertIn('Edited expertise', json.dumps(maker_payloads[0]))

    def test_profile_examples_reach_maker_prompt_as_untrusted_context(self):
        maker = base_profile('WordSmith')
        maker['examples'] = [{'input': 'Wallet brief', 'approved_output': 'Designed in Texas wallet EXAMPLE-OUTPUT-9'}]
        out = Path(tempfile.mkdtemp()) / 'p.json'
        with tempfile.TemporaryDirectory() as directory:
            for name, profile in (('Scout', base_profile('Scout')), ('Maker', maker), ('Checker', base_profile('Checker'))):
                Path(directory).joinpath(name.lower() + '.json').write_text(json.dumps(profile))
            with patch.dict(os.environ, {'META_API_KEY': 'test-key', 'META_WONDER_MODEL': ''}):
                captured = []
                with patch('launchcrew.spark.urlopen', side_effect=capture_stub(captured)):
                    run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', directory, out)
        joined = json.dumps(captured)
        self.assertIn('EXAMPLE-OUTPUT-9', joined)
        self.assertIn('Untrusted example output', joined)


if __name__ == '__main__':
    unittest.main()
