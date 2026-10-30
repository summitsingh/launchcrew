"""Focused Checker quality regressions, fictional only.

Socket-free and offline only. No model calls, no credentials.

Covers narrow fail-closed improvements: same subject and property value
swaps, included-item exclusivity, per-property quantities with unit forms,
negation and absolutes, and safe single-fact paraphrases. Uses fictional
products and values distinct from the frozen evaluation to prove generic
behavior. check_claim stays exact-only; only check_sentence allows the
narrow paraphrase path. Verified pairing stays strict and evidence stays
confirmed-facts-only.
"""
import unittest

from launchcrew.facts import check_claim, check_sentence


OWNER_SOURCES = ['owner_confirmed_input']


def owner_facts(claims):
    return {'approved_claims': list(claims), 'sources': list(OWNER_SOURCES)}


def assert_blocked(test, result):
    test.assertFalse(result['verified'])
    test.assertIn(result['verdict'], ('unsupported', 'conflicts'))
    if result['verdict'] == 'unsupported':
        test.assertIsNone(result['evidence'])
    else:
        test.assertIsInstance(result['evidence'], str)


def assert_supported(test, result, fact):
    test.assertTrue(result['verified'])
    test.assertEqual(result['verdict'], 'supported')
    test.assertEqual(result['evidence'], fact)


class ChangedMagnitudeUnitTests(unittest.TestCase):
    def test_changed_magnitude_same_unit_conflicts(self):
        facts = owner_facts(['Carafe holds 900 ml'])
        result = check_sentence('Carafe holds 1200 ml', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Carafe holds 900 ml')

    def test_changed_unit_same_number_same_dimension_conflicts(self):
        facts = owner_facts(['Carafe holds 900 ml'])
        result = check_sentence('Carafe holds 900 liters', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Carafe holds 900 ml')

    def test_safe_unit_form_paraphrase_supported_sentence_only(self):
        facts = owner_facts(['Carafe holds 900 ml'])
        supported = check_sentence('Carafe holds 900 milliliters', facts)
        assert_supported(self, supported, 'Carafe holds 900 ml')
        exact_only = check_claim('Carafe holds 900 milliliters', facts)
        assert_blocked(self, exact_only)
        self.assertEqual(exact_only['verdict'], 'unsupported')


class UnrelatedQuantityTests(unittest.TestCase):
    def test_unrelated_number_does_not_mask_property_mismatch(self):
        facts = owner_facts([
            'Decanter aerates wine in about 30 minutes',
            'Decanter holds 1 liter',
        ])
        result = check_sentence('Decanter aerates wine in about 1 minute', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Decanter aerates wine in about 30 minutes')

    def test_same_number_different_property_stays_distinct(self):
        facts = owner_facts([
            'Stool seat height is 35 cm',
            'Stool weighs 8 kg',
        ])
        result = check_sentence('Stool seat height is 8 cm', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Stool seat height is 35 cm')


class WrongSubjectPropertyTests(unittest.TestCase):
    def test_wrong_subject_same_quantity_blocked(self):
        facts = owner_facts(['Carafe holds 900 ml', 'Crate includes carafe and stopper'])
        result = check_sentence('Crate holds 900 ml', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'unsupported')

    def test_wrong_property_same_entity_blocked(self):
        facts = owner_facts(['Stool seat height is 35 cm', 'Stool weighs 8 kg'])
        result = check_sentence('Stool weighs 35 cm', facts)
        assert_blocked(self, result)

    def test_same_subject_property_value_swap_conflicts(self):
        facts = owner_facts(['Carafe body is blown glass'])
        result = check_sentence('Carafe body is pressed tin', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Carafe body is blown glass')

    def test_same_head_different_modifier_conflicts(self):
        facts = owner_facts(['Product is a woven rush mat'])
        result = check_sentence('Product is a woven reed mat', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Product is a woven rush mat')


class CrossFactCompositionTests(unittest.TestCase):
    def test_mixed_entity_quantity_blocked(self):
        facts = owner_facts(['Carafe body is blown glass', 'Carafe holds 900 ml'])
        result = check_sentence('Carafe body is 900 ml', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'conflicts')

    def test_exact_two_fact_concatenation_still_supported(self):
        facts = owner_facts(['Carafe body is blown glass', 'Carafe holds 900 ml'])
        result = check_sentence(
            'Carafe body is blown glass and Carafe holds 900 ml', facts)
        self.assertTrue(result['verified'])
        self.assertEqual(result['verdict'], 'supported')


class ExtraQualifierItemTests(unittest.TestCase):
    def test_extra_qualifier_stays_unsupported(self):
        facts = owner_facts(['Carafe body is blown glass'])
        result = check_sentence('Carafe body is blown glass and dishwasher safe', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'unsupported')

    def test_extra_item_stays_unsupported_not_conflicts(self):
        facts = owner_facts(['Crate includes spoon and ladle'])
        result = check_sentence('Crate includes spoon, ladle, and whisk', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'unsupported')


class OmittedItemTests(unittest.TestCase):
    def test_omitted_item_with_only_conflicts(self):
        facts = owner_facts(['Crate includes spoon and ladle'])
        result = check_sentence('Crate includes only the spoon', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Crate includes spoon and ladle')

    def test_omitted_item_without_only_stays_unsupported(self):
        facts = owner_facts(['Crate includes spoon and ladle'])
        result = check_sentence('Crate includes spoon', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'unsupported')

    def test_only_without_omission_stays_unsupported(self):
        facts = owner_facts(['Crate includes spoon and ladle'])
        result = check_sentence('Crate includes only spoon and ladle', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'unsupported')


class NegationAbsoluteTests(unittest.TestCase):
    def test_negation_blocked_unsupported(self):
        facts = owner_facts(['Carafe body is blown glass'])
        result = check_sentence('Carafe body is not blown glass', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'unsupported')
        self.assertIn('negation', result['reason'].lower())

    def test_always_with_correct_quantity_blocked(self):
        facts = owner_facts(['Decanter aerates wine in about 30 minutes'])
        result = check_sentence('Decanter always aerates wine in about 30 minutes', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'unsupported')

    def test_always_with_wrong_quantity_conflicts(self):
        facts = owner_facts([
            'Decanter aerates wine in about 30 minutes',
            'Decanter holds 1 liter',
        ])
        result = check_sentence('Decanter always aerates wine in under 1 minute', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')

    def test_superlative_without_quantity_stays_unsupported(self):
        facts = owner_facts(['Decanter is tested for indoor table use'])
        result = check_sentence('Decanter is guaranteed to never fail anywhere', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'unsupported')


class AmbiguousFactsTests(unittest.TestCase):
    def test_omitted_distinguishing_qualifier_blocked(self):
        facts = owner_facts(['Vessel body is blown glass', 'Vessel body is molded glass'])
        result = check_sentence('Vessel body is glass', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'unsupported')

    def test_partial_item_list_across_facts_blocked(self):
        facts = owner_facts(['Crate includes spoon', 'Crate includes ladle'])
        result = check_sentence('Crate includes spoon and ladle', facts)
        assert_blocked(self, result)
        self.assertEqual(result['verdict'], 'unsupported')


class SafeParaphraseTests(unittest.TestCase):
    def test_material_uses_paraphrase_supported_sentence_only(self):
        facts = owner_facts(['Vessel shell is recycled copper mesh'])
        supported = check_sentence(
            'The shell of the vessel uses recycled copper mesh', facts)
        assert_supported(self, supported, 'Vessel shell is recycled copper mesh')
        exact_only = check_claim(
            'The shell of the vessel uses recycled copper mesh', facts)
        assert_blocked(self, exact_only)
        self.assertEqual(exact_only['verdict'], 'unsupported')

    def test_included_item_contains_with_paraphrase_supported_sentence_only(self):
        facts = owner_facts(['Crate includes spoon and ladle'])
        supported = check_sentence(
            'The crate contains a spoon with a ladle', facts)
        assert_supported(self, supported, 'Crate includes spoon and ladle')
        exact_only = check_claim(
            'The crate contains a spoon with a ladle', facts)
        assert_blocked(self, exact_only)
        self.assertEqual(exact_only['verdict'], 'unsupported')

    def test_property_reworded_quantity_left_blocked(self):
        # Same number and equivalent unit, but holds versus capacity and
        # height versus high/sits reword the property. Left blocked to
        # avoid enabling unsupported property claims.
        facts = owner_facts(['Carafe holds 900 ml'])
        blocked = check_sentence('The carafe capacity is 900 milliliters', facts)
        assert_blocked(self, blocked)
        self.assertEqual(blocked['verdict'], 'unsupported')
        facts = owner_facts(['Stool seat height is 35 cm'])
        blocked = check_sentence('The seat of the stool sits 35 centimeters high', facts)
        assert_blocked(self, blocked)
        self.assertEqual(blocked['verdict'], 'unsupported')


class ProvenancePairingTests(unittest.TestCase):
    def test_evidence_only_from_approved_claims(self):
        facts = {
            'approved_claims': ['Carafe holds 900 ml'],
            'sources': list(OWNER_SOURCES),
            'material': 'Carafe holds 1200 ml',
            'memory_claims': ['Carafe holds 1200 ml'],
        }
        result = check_sentence('Carafe holds 1200 ml', facts)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verdict'], 'conflicts')
        self.assertEqual(result['evidence'], 'Carafe holds 900 ml')

    def test_verified_pairing_strict(self):
        facts = owner_facts(['Crate includes spoon and ladle', 'Carafe holds 900 ml'])
        cases = [
            ('Crate includes spoon and ladle', True, 'supported'),
            ('The crate contains a spoon with a ladle', True, 'supported'),
            ('Crate includes only the spoon', False, 'conflicts'),
            ('Carafe holds 1200 ml', False, 'conflicts'),
            ('Crate includes spoon, ladle, and whisk', False, 'unsupported'),
            ('Carafe body is not blown glass', False, 'unsupported'),
        ]
        for text, verified, verdict in cases:
            with self.subTest(text=text):
                result = check_sentence(text, facts)
                self.assertIs(type(result['verified']), bool)
                self.assertEqual(result['verified'], verified)
                self.assertEqual(result['verdict'], verdict)
                if verified:
                    self.assertIn(result['evidence'], facts['approved_claims'])
                elif verdict == 'unsupported':
                    self.assertIsNone(result['evidence'])
                else:
                    self.assertIn(result['evidence'], facts['approved_claims'])


if __name__ == '__main__':
    unittest.main()
