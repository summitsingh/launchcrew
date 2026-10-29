"""Slice 1 approval binding: versioned digest over the checked artifact.

Socket-free and offline only. No model calls, no DB, no credentials.
Approval binds owner-confirmed facts plus provenance (or the labelled
demo-template snapshot), current post/email/claims, the deterministic
Checker result, effective Checker profile/policies/blocked rules,
normalized photo state, and the shared revision. Export recomputes and
compares that digest every time, including revision zero.
"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import photo_review
from launchcrew import agents, human_review
from launchcrew.receipts import load_receipt, save_receipt

ROOT = Path(__file__).resolve().parents[1]
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


def offline_receipt(run_id='run_binding_probe', product_facts=None,
                    memory_claims=None, blocked_claims=None,
                    checker_profile='standard'):
    from backend import adapter
    profile = agents.load_agent('Maker', ROOT / 'agents')
    env = {'META_API_KEY': '', 'META_WONDER_MODEL': ''}
    with patch.dict(os.environ, env):
        with patch('launchcrew.run.spark_for_agent',
                   side_effect=AssertionError('no transport keyless')), \
             patch('launchcrew.run.wonder_synthesize_for_scout',
                   side_effect=AssertionError('no transport keyless')):
            return adapter.execute(run_id, IDEA, profile, False,
                                   memory_items=[],
                                   checker_profile=checker_profile,
                                   product_facts=product_facts)


def approved_no_photo():
    receipt = offline_receipt()
    assert receipt['status'] == 'completed'
    approved = human_review.approve_current(receipt, 'binding_human')
    assert human_review.exportable(approved)
    return approved


class BindingTests(unittest.TestCase):
    def test_clean_run_binds_and_exports(self):
        approved = approved_no_photo()
        binding = approved.get('approval_binding')
        self.assertIsInstance(binding, dict)
        self.assertEqual(binding['version'], human_review.APPROVAL_BINDING_VERSION)
        self.assertEqual(len(binding['digest']), 64)
        self.assertEqual(approved['approved_revision'], 0)
        self.assertEqual(approved['approvals'][-1]['binding_version'],
                         human_review.APPROVAL_BINDING_VERSION)
        self.assertEqual(approved['approvals'][-1]['binding_digest'],
                         binding['digest'])
        self.assertTrue(human_review.exportable(approved))
        bound, reason = human_review.binding_status(approved)
        self.assertTrue(bound, reason)
        exported = human_review.record_export(approved, 'binding_human')
        self.assertEqual(exported['exported_revision'], 0)
        self.assertEqual(exported['exported_draft']['post'],
                         approved['maker_draft_v2']['post'])
        self.assertEqual(exported['exported_draft']['email'],
                         approved['maker_draft_v2']['email'])
        # Export audit appends do not invalidate the binding.
        self.assertTrue(human_review.exportable(exported))

    def test_binding_deterministic_and_canonical(self):
        first = approved_no_photo()
        second = human_review.approve_current(offline_receipt(), 'other_human')
        # Same artifact shape from the same deterministic pipeline binds
        # deterministically apart from run-specific draft identity.
        # Recomputing the same receipt is stable.
        self.assertEqual(human_review.compute_approval_digest(first),
                         human_review.compute_approval_digest(copy.deepcopy(first)))
        self.assertEqual(first['approval_binding']['digest'],
                         human_review.compute_approval_digest(first))
        self.assertEqual(second['approval_binding']['version'],
                         human_review.APPROVAL_BINDING_VERSION)

    def test_binding_excludes_events_and_secrets(self):
        approved = approved_no_photo()
        payload = human_review.approval_binding_payload(approved)
        text = json.dumps(payload, sort_keys=True)
        for excluded in ('approved_by', 'approved_for_export', 'event_log',
                         'exported_by', 'last_exported', 'revised_at',
                         'checked_at', 'actor'):
            self.assertNotIn(excluded, text)
        for secret in ('base64', 'file-live', 'file_id', 'photo_sha256',
                       'sha256', 'DATABASE_URL', 'META_API_KEY', 'password'):
            self.assertNotIn(secret, text)
        # Timestamps and audit appends do not change the digest.
        mutated = copy.deepcopy(approved)
        mutated.setdefault('audit', {}).setdefault('event_log', []).append(
            {'step': 'note', 'timestamp': '2099-01-01T00:00:00+00:00'})
        mutated['last_exported_at'] = '2099-01-01T00:00:00+00:00'
        self.assertEqual(human_review.compute_approval_digest(mutated),
                         approved['approval_binding']['digest'])

    def test_tampering_invalidates_without_mutation_or_network(self):
        approved = approved_no_photo()
        before = copy.deepcopy(approved)

        def check_tamper(mutate):
            tampered = copy.deepcopy(approved)
            mutate(tampered)
            with patch('launchcrew.spark.urlopen',
                       side_effect=AssertionError('no network expected')):
                with patch('backend.sam.urlopen',
                           side_effect=AssertionError('no network expected')):
                    snapshot = copy.deepcopy(tampered)
                    self.assertFalse(human_review.exportable(tampered))
                    bound, reason = human_review.binding_status(tampered)
                    self.assertFalse(bound)
                    self.assertIn('binding', reason.lower())
                    # Exportability recomputes without mutating the receipt.
                    self.assertEqual(tampered, snapshot)
            # Original stays clean and exportable.
            self.assertTrue(human_review.exportable(approved))
            self.assertEqual(approved, before)

        # Confirmed fact value.
        check_tamper(lambda r: r['product_facts']['confirmed_claims'].__setitem__(0, 'Tampered claim'))
        # Confirmed field source (demo mode has no fields, so any added
        # field changes the bound snapshot).
        def tamper_source(r):
            fields = r['product_facts'].get('fields') or []
            if fields:
                fields[0]['source'] = 'listing'
            else:
                r['product_facts']['fields'] = [
                    {'field': 'material', 'value': 'Tampered',
                     'confirmed': True, 'source': 'listing'}]
        check_tamper(tamper_source)
        # Scout fact claim.
        def tamper_scout_claim(r):
            r['scout']['facts_used'][0]['claim'] = 'Tampered scout claim'
        check_tamper(tamper_scout_claim)
        # Scout fact provenance.
        def tamper_scout_sources(r):
            r['scout']['facts_used'][0]['sources'] = ['tampered_source']
        check_tamper(tamper_scout_sources)
        # Scout global sources.
        def tamper_global_sources(r):
            r['scout']['sources'] = ['tampered_source']
        check_tamper(tamper_global_sources)
        # Post and email copy.
        check_tamper(lambda r: r['maker_draft_v2'].__setitem__('post', 'Tampered post'))
        check_tamper(lambda r: r['maker_draft_v2'].__setitem__('email', 'Tampered email'))
        # Checker policy and profile.
        def tamper_policy(r):
            r['checker_policies'] = ['superlatives']
        check_tamper(tamper_policy)
        check_tamper(lambda r: r.__setitem__('checker_profile', 'strict'))
        # Blocked rule.
        def tamper_blocked(r):
            r['blocked_claims'] = ['Designed in Texas']
        check_tamper(tamper_blocked)
        # Checker result internals with a still-clean blocked_count.
        def tamper_verified(r):
            r['checker_v2']['verified_count'] = r['checker_v2']['verified_count'] + 1
        check_tamper(tamper_verified)
        def tamper_claim_results(r):
            r['checker_v2']['claim_results'][0]['reason'] = 'Tampered reason'
        check_tamper(tamper_claim_results)
        def tamper_supported(r):
            r['checker_v2']['supported_count'] = r['checker_v2']['supported_count'] + 1
        check_tamper(tamper_supported)
        # Photo state: a detected photo on the same revision still passes
        # the photo gate but must fail the binding.
        def tamper_photo(r):
            r['photo_status'] = {'state': 'checked', 'label': 'detected',
                                 'reason': 'clear_single',
                                 'policy_version': 'photo-geometry/v1',
                                 'revision': 0, 'actor': '', 'checked_at': ''}
        check_tamper(tamper_photo)
        # Shared revision with approved_revision kept matching and a clean
        # blocked_count must still fail the binding.
        def tamper_revision(r):
            r['revision'] = 1
            r['approved_revision'] = 1
            r['approvals'][-1]['revision'] = 1
        check_tamper(tamper_revision)

    def test_revision_clears_binding_and_reapproves_new_digest(self):
        approved = approved_no_photo()
        old_digest = approved['approval_binding']['digest']
        edit = {'post': 'Vegan leather wallet. Designed in Texas.',
                'email': 'For Austin commuters. $49.'}
        revised = human_review.apply_revision(approved, edit['post'], edit['email'],
                                              'binding_human', 0)
        self.assertEqual(revised['revision'], 1)
        self.assertEqual(revised['approval_state'], 'pending_approval')
        self.assertEqual(revised['approvals'], [])
        self.assertIsNone(revised['approved_revision'])
        self.assertIsNone(revised.get('approval_binding'))
        self.assertFalse(human_review.exportable(revised))
        # History preserves the superseded binding as audit evidence.
        self.assertEqual(revised['revision_history'][-1]['approval_binding']['digest'],
                         old_digest)
        reapproved = human_review.approve_current(revised, 'binding_human', 1)
        self.assertTrue(human_review.exportable(reapproved))
        self.assertNotEqual(reapproved['approval_binding']['digest'], old_digest)
        self.assertEqual(reapproved['approved_revision'], 1)
        exported = human_review.record_export(reapproved, 'binding_human')
        self.assertEqual(exported['exported_draft']['post'], edit['post'])
        self.assertEqual(exported['exported_draft']['email'], edit['email'])

    def test_photo_events_clear_binding(self):
        approved = approved_no_photo()
        old_digest = approved['approval_binding']['digest']
        inflight = {'state': 'check_requested', 'label': None,
                    'reason': 'check_requested: segmentation in flight',
                    'policy_version': 'photo-geometry/v1'}
        checked = photo_review.apply_photo_event(
            approved, event=photo_review.PHOTO_EVENT_CHECKED,
            actor='binding_human', status=dict(inflight))
        self.assertEqual(checked['revision'], 1)
        self.assertIsNone(checked.get('approval_binding'))
        self.assertEqual(checked['approval_state'], 'pending_approval')
        self.assertEqual(checked['revision_history'][-1]['approval_binding']['digest'],
                         old_digest)
        verdict = photo_review.attach_verdict(
            checked, label='detected', reason='clear_single',
            actor='binding_human', uploads=1, segmentations=1, segmented=True)
        self.assertIsNone(verdict.get('approval_binding'))
        self.assertEqual(verdict['approval_state'], 'pending_approval')
        reapproved = human_review.approve_current(verdict, 'binding_human', 1)
        self.assertTrue(human_review.exportable(reapproved))
        self.assertNotEqual(reapproved['approval_binding']['digest'], old_digest)
        removed = photo_review.apply_photo_event(
            reapproved, event=photo_review.PHOTO_EVENT_REMOVED,
            actor='binding_human', status=photo_review.blank_photo_status())
        self.assertEqual(removed['revision'], 2)
        self.assertIsNone(removed.get('approval_binding'))
        self.assertFalse(human_review.exportable(removed))
        final = human_review.approve_current(removed, 'binding_human', 2)
        self.assertTrue(human_review.exportable(final))

    def test_stale_revision_refused(self):
        receipt = offline_receipt()
        with self.assertRaisesRegex(ValueError, 'stale'):
            human_review.apply_revision(receipt, 'Vegan leather wallet.',
                                        'For Austin commuters.', 'h', 5)
        revised = human_review.apply_revision(
            receipt, 'Vegan leather wallet. Designed in Texas.',
            'For Austin commuters. $49.', 'h', 0)
        with self.assertRaisesRegex(ValueError, 'stale'):
            human_review.approve_current(revised, 'h', 0)
        with self.assertRaisesRegex(ValueError, 'stale|required'):
            human_review.approve_current(revised, 'h', None)

    def test_historical_unbound_approval_requires_new_approval(self):
        approved = approved_no_photo()
        historical = copy.deepcopy(approved)
        historical['approval_binding'] = None
        historical['approvals'][-1].pop('binding_version', None)
        historical['approvals'][-1].pop('binding_digest', None)
        self.assertFalse(human_review.exportable(historical))
        bound, reason = human_review.binding_status(historical)
        self.assertFalse(bound)
        self.assertIn('new approval', reason.lower())
        with self.assertRaisesRegex(ValueError, 'Export refused'):
            human_review.record_export(historical, 'binding_human')
        # Already-approved historical receipts stay refused until a saved
        # revision returns them to pending for a fresh bound approval.
        with self.assertRaisesRegex(ValueError, 'not pending approval'):
            human_review.approve_current(historical, 'binding_human', 0)

    def test_malformed_inputs_fail_closed(self):
        approved = approved_no_photo()
        for mutate in (lambda r: r['product_facts'].__setitem__('confirmed_claims', 'not-a-list'),
                       lambda r: r['checker_v2'].__setitem__('blocked_count', True),
                       lambda r: r['maker_draft_v2'].__setitem__('post', 123),
                       lambda r: r.__setitem__('revision', True)):
            tampered = copy.deepcopy(approved)
            mutate(tampered)
            with self.assertRaises(ValueError):
                human_review.compute_approval_digest(tampered)
            self.assertFalse(human_review.exportable(tampered))
        pending = offline_receipt()
        pending['product_facts'] = 'not-an-object'
        with self.assertRaisesRegex(ValueError, 'binding'):
            human_review.approve_current(pending, 'binding_human')

    def test_receipt_readback_carries_binding(self):
        approved = approved_no_photo()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            save_receipt(approved, path)
            reread = load_receipt(path)
        self.assertEqual(reread['approval_binding'], approved['approval_binding'])
        self.assertTrue(human_review.exportable(reread))
        exported = human_review.record_export(reread, 'binding_human')
        current = human_review.current_draft(reread)
        self.assertEqual(exported['exported_draft']['post'], current['post'])
        self.assertEqual(exported['exported_draft']['email'], current['email'])

    def test_wrapper_edit_passes_without_weakening_factuality(self):
        receipt = offline_receipt()
        good_post = 'Hello Designed in Texas, shop now!'
        good_email = 'Hi Designed in Texas, learn more.'
        check = human_review.recheck_text(good_post, good_email, receipt)
        self.assertEqual(check['blocked_count'], 0)
        revised = human_review.apply_revision(receipt, good_post, good_email,
                                              'binding_human', 0)
        # Stored explicit claims stay exact confirmed facts.
        for claim in revised['human_draft']['claims']:
            self.assertIn(claim, receipt['product_facts']['confirmed_claims'])
        approved = human_review.approve_current(revised, 'binding_human', 1)
        self.assertTrue(human_review.exportable(approved))
        # Extra factual wording outside confirmed spans still blocks.
        bad_post = 'Hello Designed in Texas canvas!'
        with self.assertRaises(human_review.NeedsRevision):
            human_review.apply_revision(receipt, bad_post, good_email,
                                        'binding_human', 0)
        # Unsupported seed still blocks.
        with self.assertRaises(human_review.NeedsRevision):
            human_review.apply_revision(receipt, 'best in Texas.', good_email,
                                        'binding_human', 0)

    def test_wrapper_policy_veto_preserved(self):
        from backend import adapter
        profile = agents.load_agent('Maker', ROOT / 'agents')
        checker = agents.load_agent('Checker', ROOT / 'agents')
        checker['decision_rules'] = ['Block price claims']
        checker['veto_scope'] = ['price_claims']
        env = {'META_API_KEY': '', 'META_WONDER_MODEL': ''}
        with patch.dict(os.environ, env):
            with patch('launchcrew.run.spark_for_agent',
                       side_effect=AssertionError('no transport keyless')), \
                 patch('launchcrew.run.wonder_synthesize_for_scout',
                       side_effect=AssertionError('no transport keyless')):
                receipt = adapter.execute('run_binding_policy', IDEA, profile,
                                          False, memory_items=[],
                                          checker_agent=checker)
        self.assertIn('price_claims', receipt['checker_policies'])
        # A grammar-clean wrapper carrying a policy-blocked price still fails.
        with self.assertRaises(human_review.NeedsRevision):
            human_review.apply_revision(receipt, 'Hello $49 shop now!',
                                        'Hi Designed in Texas, learn more.',
                                        'binding_human', 0)


if __name__ == '__main__':
    unittest.main()
