from pathlib import Path
import unittest

from launchcrew.facts import check_claim, check_claims, check_draft, load_facts, normalize
from launchcrew.run import check_pack

ROOT = Path(__file__).resolve().parents[1]


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self.facts, self.blob = load_facts(ROOT / 'facts/demo_facts.json')

    def test_material_verified(self):
        result = check_claim('100% vegan PU leather', self.facts)
        self.assertTrue(result['verified'])
        self.assertEqual(result['evidence'], '100% vegan PU leather')

    def test_unverified_blocked(self):
        result = check_claim('best in Texas', self.facts)
        self.assertFalse(result['verified'])
        self.assertIsNone(result['evidence'])
        self.assertEqual(result['reason'], 'Claim not found in facts file')

    def test_counts(self):
        result = check_claims(['$49', 'Designed in Texas', 'best in Texas'], self.facts)
        self.assertEqual((result['verified_count'], result['blocked_count']), (2, 1))

    def test_normalize(self):
        self.assertEqual(normalize('  HELLO,  World!  '), 'hello world')
        self.assertIn(normalize('100% vegan PU leather'), self.blob)

    def test_draft_safety_net_without_explicit_claim(self):
        pack = {'claims': ['$49'], 'post': '$49. best in Texas.', 'email': '$49.'}
        self.assertEqual(check_pack(pack, self.facts)['blocked_count'], 1)
        self.assertTrue(check_draft('Designed in Texas, best in Texas.', self.facts))

    def test_approved_claim_containment(self):
        self.assertTrue(check_claim('This wallet is Designed in Texas', self.facts)['verified'])
        self.assertFalse(check_claim('Designed in Texas, best in Texas', self.facts)['verified'])
