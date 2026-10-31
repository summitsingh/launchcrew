"""Checker cliches policy: supported-policy wiring and claim blocking.

Socket-free and offline only. No model calls, no credentials.
Covers the official 'cliches' Checker policy in
launchcrew/checker_policies.py: supported-policy registration, exact
veto and rule matching, strict profile enforcement, per-claim
blocking through policy_blocks, reason text, and end-to-end blocking
through check_pack.
"""
import unittest

from launchcrew.checker_policies import (
    SUPPORTED_CHECKER_POLICIES,
    cliche_hits,
    describe_supported,
    effective_policies,
    parse_checker_agent,
    policy_blocks,
    policy_reason,
)
from launchcrew.cliche_scrubber import CLICHE_WORDS
from launchcrew.run import check_pack


def owner_facts(claims):
    return {'approved_claims': list(claims), 'sources': ['owner_confirmed_input']}


def cliches_checker():
    return {
        'name': 'ClicheGuard',
        'role': 'Checker',
        'department': 'Growth',
        'personality': 'Strict',
        'expertise': 'Policy',
        'decision_rules': ['Block marketing cliches'],
        'veto_scope': ['cliches'],
        'tools_allowed': ['facts_file', 'claim_check'],
        'spend_limit': 0,
        'approval_level': 'approve_each',
        'examples': [],
    }


class SupportedRegistrationTests(unittest.TestCase):
    def test_cliches_is_registered_with_exact_fields(self):
        entry = SUPPORTED_CHECKER_POLICIES['cliches']
        self.assertEqual(entry['policy'], 'cliches')
        self.assertEqual(entry['veto_token'], 'cliches')
        self.assertEqual(entry['rule_line'], 'Block marketing cliches')
        self.assertEqual(
            entry['description'],
            'Block claims containing generic AI filler buzzwords and marketing cliches.')

    def test_supported_set_lists_all_three_policies(self):
        self.assertEqual(
            sorted(item['policy'] for item in describe_supported()),
            ['cliches', 'price_claims', 'superlatives'])

    def test_every_cliche_word_is_a_blockable_claim(self):
        for word in sorted(CLICHE_WORDS):
            with self.subTest(word=word):
                text = 'This wallet is %s for commuters.' % word
                self.assertTrue(policy_blocks('cliches', text), text)


class ExactMatchingTests(unittest.TestCase):
    def test_veto_scope_cliches_is_enforced(self):
        parsed = parse_checker_agent(cliches_checker())
        self.assertEqual(parsed['enforced_policies'], ['cliches'])

    def test_rule_line_match_is_case_insensitive(self):
        agent = cliches_checker()
        agent['decision_rules'] = ['  BLOCK MARKETING CLICHES  ']
        agent['veto_scope'] = []
        parsed = parse_checker_agent(agent)
        self.assertEqual(parsed['enforced_policies'], ['cliches'])

    def test_near_miss_cliche_rules_stay_advisory(self):
        agent = cliches_checker()
        agent['decision_rules'] = ['Please block cliches when you can']
        agent['veto_scope'] = ['cliche']
        parsed = parse_checker_agent(agent)
        self.assertEqual(parsed['enforced_policies'], [])
        self.assertEqual(len(parsed['advisory_only']), 2)


class EffectivePolicyTests(unittest.TestCase):
    def test_strict_profile_enforces_cliches(self):
        self.assertIn('cliches', effective_policies('strict'))
        self.assertIn('superlatives', effective_policies('strict'))

    def test_standard_profile_does_not_enforce_cliches(self):
        self.assertNotIn('cliches', effective_policies('standard'))

    def test_checker_agent_adds_cliches_on_top(self):
        self.assertEqual(
            effective_policies('standard', cliches_checker()), ['cliches'])


class PolicyBlockTests(unittest.TestCase):
    def test_banned_words_block(self):
        for text in (
            'A miracle bottle for gym days.',
            'Cutting-edge steel frame.',
            'Seamlessly syncs with your phone.',
            'Unleash your potential with this bottle.',
            'Ready to take to the next level today.',
        ):
            with self.subTest(text=text):
                self.assertTrue(policy_blocks('cliches', text), text)

    def test_clean_copy_passes(self):
        for text in (
            'Full-grain leather wallet, 320 g, ships in two days.',
            'Steel frame, 1.2 kg, rated for 150 kg loads.',
            'The final level ships Friday.',
            'Elevation gain is 400 m on this trail.',
        ):
            with self.subTest(text=text):
                self.assertFalse(policy_blocks('cliches', text), text)

    def test_non_string_claim_never_blocks(self):
        for value in (None, 123, ['miracle'], {'claim': 'miracle'}):
            with self.subTest(value=value):
                self.assertFalse(policy_blocks('cliches', value))

    def test_unknown_policy_never_blocks(self):
        self.assertFalse(policy_blocks('unknown_policy', 'A miracle bottle.'))

    def test_reason_names_cliches_policy(self):
        reason = policy_reason('cliches')
        self.assertIn('cliches', reason)
        self.assertIn('cliche', reason.lower())

    def test_cliche_hits_match_lint_shape(self):
        hits = cliche_hits('A miracle game-changer for commuters.')
        self.assertTrue(hits)
        for hit in hits:
            with self.subTest(hit=hit):
                self.assertEqual(set(hit), {'cliche', 'reason'})
        self.assertEqual(cliche_hits('Full-grain leather wallet.'), [])
        self.assertEqual(cliche_hits(None), [])


class CheckPackIntegrationTests(unittest.TestCase):
    def test_cliches_policy_blocks_verified_claim_with_cliche(self):
        claim = 'Miracle vegan wallet for commuters'
        facts = owner_facts([claim])
        draft = {'claims': [claim], 'post': claim + '.', 'email': claim + '.'}
        packed = check_pack(draft, facts, checker_agent=cliches_checker())
        self.assertGreater(packed['blocked_count'], 0)
        reasons = ' '.join(
            item['reason'] for item in packed['blocked_claims'])
        self.assertIn('cliches', reasons)

    def test_standard_check_leaves_cliche_claim_unblocked_by_policy(self):
        claim = 'Miracle vegan wallet for commuters'
        facts = owner_facts([claim])
        draft = {'claims': [claim], 'post': claim + '.', 'email': claim + '.'}
        packed = check_pack(draft, facts, checker_profile='standard')
        for item in packed['blocked_claims']:
            self.assertNotIn('cliches', item['reason'])

    def test_strict_check_blocks_cliche_claim(self):
        claim = 'Miracle vegan wallet for commuters'
        facts = owner_facts([claim])
        draft = {'claims': [claim], 'post': claim + '.', 'email': claim + '.'}
        packed = check_pack(draft, facts, checker_profile='strict')
        reasons = ' '.join(
            item['reason'] for item in packed['blocked_claims'])
        self.assertIn('cliches', reasons)


if __name__ == '__main__':
    unittest.main()
