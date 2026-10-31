"""Checked launch matrix: receipt-bound seven-channel candidates.

Offline and deterministic only. No model calls, no network, no DB.
Covers launchcrew.channel_variants.checked_launch_matrix: the bundle
derives verbatim from the current approved post draft and the
receipt-bound confirmed claims, refuses without current human
approval plus a matching approval binding, re-verifies every
rendered candidate, and never auto-publishes.
"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from launchcrew import channel_variants, human_review

ROOT = Path(__file__).resolve().parents[1]
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
MATRIX_CHANNELS = ('x', 'linkedin', 'instagram', 'email', 'facebook', 'tiktok', 'shopify')


def offline_receipt(run_id='run_matrix_probe', product_facts=None):
    from backend import adapter
    from launchcrew import agents
    profile = agents.load_agent('Maker', ROOT / 'agents')
    env = {'META_API_KEY': '', 'META_WONDER_MODEL': ''}
    with patch.dict(os.environ, env):
        with patch('launchcrew.run.spark_for_agent',
                   side_effect=AssertionError('no transport keyless')), \
             patch('launchcrew.run.wonder_synthesize_for_scout',
                   side_effect=AssertionError('no transport keyless')):
            return adapter.execute(run_id, IDEA, profile, False,
                                   memory_items=[],
                                   checker_profile='standard',
                                   product_facts=product_facts)


def approved_receipt(run_id='run_matrix_probe', product_facts=None):
    receipt = offline_receipt(run_id, product_facts)
    assert receipt['status'] == 'completed'
    approved = human_review.approve_current(receipt, 'matrix_human')
    assert human_review.exportable(approved)
    return approved


class CheckedLaunchMatrixTests(unittest.TestCase):
    def test_pending_receipt_refuses_without_approval(self):
        receipt = offline_receipt()
        self.assertEqual(receipt['approval_state'], 'pending_approval')
        with self.assertRaises(ValueError) as ctx:
            channel_variants.checked_launch_matrix(receipt)
        self.assertIn('approval', str(ctx.exception).lower())

    def test_approved_receipt_returns_all_seven_channels(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_launch_matrix(approved)
        for channel in MATRIX_CHANNELS:
            with self.subTest(channel=channel):
                self.assertIn(channel, bundle)
                entry = bundle[channel]
                self.assertEqual(entry['channel'], channel)
                self.assertFalse(entry['exportable'])
                self.assertFalse(entry['independently_exportable'])
                self.assertTrue(entry['requires_checker_binding'])
        self.assertEqual(bundle['bundle_version'],
                         channel_variants.CHECKED_LAUNCH_MATRIX_VERSION)
        self.assertEqual(bundle['receipt_id'], approved['run_id'])
        self.assertEqual(bundle['revision'],
                         human_review.current_revision(approved))
        self.assertEqual(bundle['approval_state'], 'approved_for_export')
        self.assertEqual(bundle['binding_version'],
                         approved['approval_binding']['version'])
        self.assertEqual(bundle['binding_digest'],
                         approved['approval_binding']['digest'])
        self.assertEqual(bundle['draft_source'],
                         channel_variants.CHECKED_DRAFT_SOURCE)
        self.assertTrue(bundle['no_auto_publish'])
        self.assertIn('campaign angle', bundle['note'].lower())
        provenance = bundle['provenance']
        self.assertTrue(provenance['matrix'])
        self.assertEqual(provenance['channels'], list(MATRIX_CHANNELS))
        self.assertEqual(provenance['matrix_channels'], list(MATRIX_CHANNELS))

    def test_content_valid_entries_reverify_exactly(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_launch_matrix(approved)
        post = channel_variants.bundle_post_text(approved)
        confirmed = approved['product_facts']['confirmed_claims']
        for channel in MATRIX_CHANNELS:
            entry = bundle[channel]
            if not entry['content_valid']:
                continue
            with self.subTest(channel=channel):
                ok, reason = channel_variants.verify_exact_variant_text(
                    channel, entry['text'], entry.get('subject', ''),
                    post, confirmed)
                self.assertTrue(ok, reason)

    def test_repeat_calls_are_deterministic(self):
        approved = approved_receipt()
        first = channel_variants.checked_launch_matrix(approved)
        second = channel_variants.checked_launch_matrix(approved)
        self.assertEqual(first, second)

    def test_caller_receipt_is_unchanged(self):
        approved = approved_receipt()
        before = copy.deepcopy(approved)
        channel_variants.checked_launch_matrix(approved)
        self.assertEqual(approved, before)

    def test_matrix_matches_single_builders_source(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_launch_matrix(approved)
        post = channel_variants.bundle_post_text(approved)
        confirmed = approved['product_facts']['confirmed_claims']
        matrix = channel_variants.build_launch_matrix(post, confirmed)
        for channel in MATRIX_CHANNELS:
            with self.subTest(channel=channel):
                if bundle[channel]['content_valid']:
                    self.assertEqual(bundle[channel]['text'],
                                     matrix[channel]['text'])

    def test_tiktok_and_shopify_framing_preserved(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_launch_matrix(approved)
        if bundle['tiktok']['content_valid']:
            self.assertTrue(bundle['tiktok']['text'].startswith(
                channel_variants.TIKTOK_HEADER))
            self.assertTrue(bundle['tiktok']['text'].endswith(
                channel_variants.TIKTOK_CLOSER))
        if bundle['shopify']['content_valid']:
            for line in bundle['shopify']['text'].splitlines():
                if line.strip():
                    self.assertTrue(line.startswith('- '))


if __name__ == '__main__':
    unittest.main()
