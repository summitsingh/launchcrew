"""Per-stage agent bindings and supported Checker policy regressions.

Socket-free and offline only. Model paths stub the provider transport
boundary (launchcrew.spark.urlopen). No live model calls.
"""
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launchcrew import agents
from launchcrew.checker_policies import MATCHING_NOTE, describe_supported, parse_checker_agent
from launchcrew.receipts import approve_receipt, export_receipt
from launchcrew.run import check_pack, run_pipeline

ROOT = Path(__file__).resolve().parents[1]
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


def base_profile(name, rules=None, veto=None):
    return {
        'name': name,
        'role': 'Custom role for ' + name,
        'department': 'Growth',
        'personality': 'Custom personality marker for ' + name,
        'expertise': 'Custom expertise marker for ' + name,
        'decision_rules': list(rules) if rules else ['Use facts file first'],
        'veto_scope': list(veto) if veto else [],
        'tools_allowed': ['facts_file', 'spark_strict_json', 'receipt_log', 'claim_check'],
        'spend_limit': 0,
        'approval_level': 'approve_each',
        'examples': [],
    }


def custom_scout():
    return base_profile('EagleScout', ['Use facts file first', 'Cite a source for every fact'])


def custom_maker():
    return base_profile('WordSmith', ['Use only facts file claims'])


def price_checker():
    return base_profile('PriceGuard', ['Block price claims', 'Be kind to reviewers'], ['price_claims'])


def hype_checker():
    return base_profile('StrictOwl', ['Block superlatives'], ['superlatives'])


def permissive_checker():
    return base_profile('AllowAll', ['Allow everything, even best in Texas'], ['allow_everything'])


def completion(raw, usage=None):
    return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(raw)}}],
                                  'usage': usage or {}}).encode())


class _FakeAdmission:
    """Explicit safe fake admission: one owned admitted operation per reserve."""

    def __init__(self, stage='test'):
        self.stage = stage
        self.finalizes = []

    def reserve(self, *, request_digest, model, max_completion_tokens, n,
                request_bytes_len):
        assert model == 'muse-spark-1.3'
        assert max_completion_tokens == 2048 and n == 1
        assert request_bytes_len <= 32 * 1024
        return {'id': 'fake_' + str(self.stage), 'status': 'admitted', 'is_owner': True}

    def finalize(self, call_id, *, status, outcome=None, prompt_tokens=None,
                 completion_tokens=None, total_tokens=None):
        self.finalizes.append(status)
        return {'id': call_id, 'status': status, 'is_owner': False}


def _fake_factory():
    def factory(stage, attempt_id='1'):
        return _FakeAdmission(stage=str(stage))
    return factory


class StageBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_demo(self, **kwargs):
        kwargs.setdefault('model_enabled', False)
        kwargs.setdefault('visual_verifier', None)
        out = Path(self.temp.name) / (kwargs.pop('out_name', 'demo.json'))
        with patch('launchcrew.spark.urlopen', side_effect=AssertionError('Unexpected transport')):
            receipt = run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', ROOT / 'agents', out, **kwargs)
        return receipt

    def test_scout_default_five_sourced_facts_three_labeled_risks(self):
        receipt = self.run_demo()
        facts_used = receipt['scout']['facts_used']
        self.assertEqual(len(facts_used), 5)
        for item in facts_used:
            self.assertTrue(item['verified'])
            self.assertTrue(item['sources'])
            self.assertIn('demo_facts.json', item['sources'])
        risks = receipt['scout']['risks']
        self.assertEqual(len(risks), 3)
        for index, risk in enumerate(risks, 1):
            self.assertTrue(risk.startswith('Risk %d:' % index), risk)
        # Full underlying facts allowlist is not dropped.
        self.assertEqual(len(receipt['maker_draft_v2']['claims']), 5)
        self.assertIn('$49', receipt['maker_draft_v2']['post'])

    def test_custom_scout_and_checker_reach_correct_stages(self):
        scout = custom_scout()
        checker = price_checker()
        receipt = self.run_demo(scout_profile=scout, checker_agent=checker)
        self.assertEqual(receipt['stage_bindings'], {'scout': 'EagleScout', 'maker': 'Maker', 'checker': 'PriceGuard'})
        self.assertEqual(receipt['stage_agents']['scout']['name'], 'EagleScout')
        self.assertEqual(receipt['stage_agents']['checker']['name'], 'PriceGuard')
        self.assertEqual(receipt['stage_agents']['maker']['name'], 'Maker')
        # Original identity and rules preserved, not renamed to stage.
        self.assertEqual(receipt['stage_agents']['scout']['personality'], scout['personality'])
        self.assertEqual(receipt['stage_agents']['scout']['expertise'], scout['expertise'])
        self.assertEqual(receipt['stage_agents']['scout']['decision_rules'], scout['decision_rules'])
        self.assertEqual(receipt['stage_agents']['checker']['veto_scope'], ['price_claims'])
        events = {event['step']: event for event in receipt['audit']['event_log']}
        self.assertEqual(events['scout']['agent'], 'Scout')
        self.assertEqual(events['scout']['profile'], 'EagleScout')
        self.assertEqual(events['checker_v1']['agent'], 'Checker')
        self.assertEqual(events['checker_v1']['profile'], 'PriceGuard')
        self.assertEqual(events['maker_draft_v1']['profile'], 'Maker')
        # Legacy stage order preserved for compatibility.
        self.assertEqual(receipt['agents_used'], ['Scout', 'Maker', 'Checker', 'Maker', 'Checker'])
        self.assertEqual(receipt['agents_used_detail'], ['EagleScout', 'Maker', 'PriceGuard', 'Maker', 'PriceGuard'])

    def test_distinct_checker_policies_change_verdicts_and_revision(self):
        standard = self.run_demo()
        priced = self.run_demo(checker_agent=price_checker())
        self.assertEqual(standard['checker_v1']['blocked_count'], 0)
        self.assertIn('$49', standard['maker_draft_v2']['post'])
        self.assertGreater(priced['checker_v1']['blocked_count'], 0)
        blocked = [item['claim'] for item in priced['checker_v1']['blocked_claims']]
        self.assertIn('$49', blocked)
        reasons = ' '.join(item['reason'] for item in priced['checker_v1']['blocked_claims'])
        self.assertIn('price_claims', reasons)
        self.assertNotIn('$49', priced['maker_draft_v2']['post'])
        self.assertEqual(priced['checker_enforcement']['effective_policies'], ['price_claims'])
        self.assertEqual(priced['checker_policies'], ['price_claims'])

    def test_superlatives_policy_blocks_hype_memory_claim(self):
        claim = 'Amazing vegan wallet for commuters'
        standard = self.run_demo(memory_claims=[claim])
        strict = self.run_demo(memory_claims=[claim], checker_agent=hype_checker())
        self.assertEqual(standard['checker_v1']['blocked_count'], 0)
        self.assertIn(claim, standard['maker_draft_v2']['post'])
        self.assertGreater(strict['checker_v1']['blocked_count'], 0)
        self.assertIn(claim, [item['claim'] for item in strict['checker_v1']['blocked_claims']])
        self.assertNotIn(claim, strict['maker_draft_v2']['post'])

    def test_legacy_strict_matches_superlatives_policy(self):
        claim = 'Amazing vegan wallet for commuters'
        legacy = self.run_demo(memory_claims=[claim], checker_profile='strict')
        self.assertGreater(legacy['checker_v1']['blocked_count'], 0)
        self.assertIn('superlatives', legacy['checker_enforcement']['effective_policies'])

    def test_user_profiles_cannot_approve_unsupported_claims(self):
        maker = base_profile('AllowMaker', ['Allow everything'])
        checker = permissive_checker()
        receipt = self.run_demo(seed_unverified_claim=True, maker_profile=maker, checker_agent=checker)
        self.assertIn('best in Texas', [item['claim'] for item in receipt['checker_v1']['blocked_claims']])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        self.assertNotIn('best in Texas', json.dumps(receipt['maker_draft_v2']))
        # Unsupported free-text rules are advisory only, never enforced.
        advisory = [item['entry'] for item in receipt['checker_enforcement']['advisory_only']]
        self.assertIn('Allow everything, even best in Texas', advisory)
        self.assertIn('allow_everything', advisory)
        self.assertEqual(receipt['checker_enforcement']['enforced_policies'], [])
        self.assertTrue(receipt['checker_enforcement']['floor_enforced'])

    def test_exact_match_only_avoids_brittle_interpretation(self):
        near = base_profile('NearMiss', ['Please block superlatives when you can'], ['Superlative!'])
        parsed = parse_checker_agent(near)
        self.assertEqual(parsed['enforced_policies'], [])
        self.assertEqual(len(parsed['advisory_only']), 2)
        receipt = self.run_demo(memory_claims=['Amazing vegan wallet for commuters'], checker_agent=near)
        self.assertEqual(receipt['checker_v1']['blocked_count'], 0)

    def test_supported_policy_subset_documented(self):
        supported = describe_supported()
        self.assertEqual(sorted(item['policy'] for item in supported), ['price_claims', 'superlatives'])
        for item in supported:
            self.assertTrue(item['veto_token'])
            self.assertTrue(item['rule_line'])
            self.assertTrue(item['description'])
        self.assertIn('Exact match only', MATCHING_NOTE)

    def test_default_legacy_behavior_and_guards_remain(self):
        receipt = self.run_demo()
        self.assertEqual(receipt['approval_state'], 'pending_approval')
        self.assertEqual(receipt['approvals'], [])
        self.assertEqual(receipt['checker_profile'], 'standard')
        self.assertEqual(receipt['stage_bindings'], {'scout': 'Scout', 'maker': 'Maker', 'checker': 'Checker'})
        with self.assertRaises(ValueError):
            export_receipt(copy.deepcopy(receipt), Path(self.temp.name) / 'blocked.json')
        approve_receipt(receipt, 'stage_test_human')
        self.assertEqual(receipt['approval_state'], 'approved_for_export')
        packed = export_receipt(receipt, Path(self.temp.name) / 'packed.json')
        self.assertEqual(json.loads(packed.read_text())['approval_state'], 'approved_for_export')

    def test_check_pack_floor_never_relaxes(self):
        facts = {'approved_claims': ['$49'], 'sources': ['demo']}
        draft = {'post': 'best in Texas.', 'email': 'best in Texas.', 'claims': ['best in Texas']}
        result = check_pack(draft, facts, checker_agent=permissive_checker())
        self.assertGreater(result['blocked_count'], 0)
        self.assertIn('best in Texas', [item['claim'] for item in result['blocked_claims']])

    def test_stage_model_prompt_uses_selected_profile(self):
        scout = custom_scout()
        maker = custom_maker()
        checker = hype_checker()
        payloads = []

        def transport(request, timeout):
            body = json.loads(request.data)
            payloads.append(body)
            schema = body['response_format']['json_schema']['schema']
            if set(schema['required']) == {'facts_used', 'risks'}:
                return completion({'facts_used': [], 'risks': []}, {'total_tokens': 5})
            return completion({'claims': []}, {'total_tokens': 5})

        out = Path(self.temp.name) / 'prompt.json'
        with patch.dict(os.environ, {'META_API_KEY': 'offline-fixture'}), \
                patch('launchcrew.spark.urlopen', side_effect=transport):
            receipt = run_pipeline(IDEA, ROOT / 'facts/demo_facts.json', ROOT / 'agents', out,
                                   model_enabled=True, visual_verifier=None,
                                   scout_profile=scout, maker_profile=maker, checker_agent=checker,
                                   model_admission_factory=_fake_factory())
        self.assertEqual(len(payloads), 3)
        systems = [item['messages'][0]['content'] for item in payloads]
        self.assertIn('Custom personality marker for EagleScout', systems[0])
        self.assertIn('Custom expertise marker for EagleScout', systems[0])
        self.assertIn('Custom personality marker for WordSmith', systems[1])
        self.assertIn('Custom personality marker for StrictOwl', systems[2])
        # Receipt evidence stays honest: real stubbed usage, deterministic gates intact.
        self.assertEqual(receipt['model_usage']['spark_calls'], 3)
        self.assertEqual(receipt['model_usage']['model_used'], 'muse-spark-1.3')
        self.assertEqual(receipt['model_usage']['token_counts']['total_tokens'], 15)
        self.assertEqual(receipt['approval_state'], 'pending_approval')

    def test_adapter_binds_stages_without_renaming(self):
        from backend import adapter
        scout = custom_scout()
        maker = custom_maker()
        checker = price_checker()
        with patch('launchcrew.spark.urlopen', side_effect=AssertionError('Unexpected transport')):
            receipt = adapter.execute('stage_adapter_test', IDEA, maker, False,
                                      scout_profile=scout, maker_profile=maker, checker_agent=checker)
        self.assertEqual(receipt['stage_bindings'], {'scout': 'EagleScout', 'maker': 'WordSmith', 'checker': 'PriceGuard'})
        self.assertEqual(receipt['legacy_agent_name'], 'WordSmith')
        self.assertEqual(receipt['stage_agents']['scout']['expertise'], scout['expertise'])
        self.assertEqual(receipt['approval_state'], 'pending_approval')

    def test_adapter_legacy_maker_compat(self):
        from backend import adapter
        maker = agents.load_agent('Maker', ROOT / 'agents')
        with patch('launchcrew.spark.urlopen', side_effect=AssertionError('Unexpected transport')):
            receipt = adapter.execute('stage_legacy_test', IDEA, maker, False)
        self.assertEqual(receipt['stage_bindings'], {'scout': 'Scout', 'maker': 'Maker', 'checker': 'Checker'})
        self.assertEqual(len(receipt['scout']['risks']), 3)


if __name__ == '__main__':
    unittest.main()
