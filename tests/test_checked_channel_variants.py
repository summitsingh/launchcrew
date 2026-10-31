"""Slice 4 checked channel variants: receipt-bound export candidates.

Offline and deterministic only. No model calls, no network, no DB.
Covers the product integration (not the base builders, which have
their own suite): the bundle derives verbatim from the current
approved post draft and the receipt-bound confirmed claims, refuses
without current human approval plus a matching approval binding,
records X sentence-boundary trims, honors the receipt voice profile,
claims no campaign angles, and never auto-publishes.
"""
import copy
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from launchcrew import channel_variants, human_review

ROOT = Path(__file__).resolve().parents[1]
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


def offline_receipt(run_id='run_checked_probe', product_facts=None):
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


def approved_receipt(run_id='run_checked_probe', product_facts=None):
    receipt = offline_receipt(run_id, product_facts)
    assert receipt['status'] == 'completed'
    approved = human_review.approve_current(receipt, 'checked_human')
    assert human_review.exportable(approved)
    return approved


def with_voice(receipt, banned_terms):
    voiced = copy.deepcopy(receipt)
    voiced['voice_profile'] = {
        'id': 'mem_voice_probe',
        'title': 'Probe voice',
        'version': 'v1',
        'digest': '0' * 64,
        'example_count': 3,
        'banned_term_count': len(banned_terms),
        'banned_terms': list(banned_terms),
        'notice': 'Style samples only.',
    }
    return voiced


def first_sentence_term(post):
    from launchcrew.channel_variants import split_sentences
    sentences = split_sentences(post)
    assert sentences
    for token in re.findall(r'[A-Za-z]+', sentences[0]):
        if len(token) >= 4:
            return token
    raise AssertionError('first sentence has no usable word')


class CheckedChannelVariantsTests(unittest.TestCase):
    def test_pending_receipt_refuses_without_approval(self):
        receipt = offline_receipt()
        self.assertEqual(receipt['approval_state'], 'pending_approval')
        with self.assertRaises(ValueError) as ctx:
            channel_variants.checked_channel_variants(receipt)
        self.assertIn('approval', str(ctx.exception).lower())

    def test_failed_and_running_receipts_refuse(self):
        failed = copy.deepcopy(offline_receipt())
        failed['status'] = 'failed'
        with self.assertRaises(ValueError) as ctx_failed:
            channel_variants.checked_channel_variants(failed)
        self.assertIn('failed', str(ctx_failed.exception).lower())
        running = copy.deepcopy(offline_receipt())
        running['status'] = 'running'
        with self.assertRaises(ValueError) as ctx_running:
            channel_variants.checked_channel_variants(running)
        self.assertIn('running', str(ctx_running.exception).lower())

    def test_non_dict_receipt_refuses(self):
        for bad in (None, [], 'receipt'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    channel_variants.checked_channel_variants(bad)

    def test_bundle_shape_echoes_binding(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_channel_variants(approved)
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            self.assertIn(channel, bundle)
        self.assertIn('provenance', bundle)
        self.assertEqual(bundle['bundle_version'],
                         channel_variants.CHECKED_BUNDLE_VERSION)
        self.assertEqual(bundle['receipt_id'], approved['run_id'])
        self.assertEqual(bundle['revision'],
                         human_review.current_revision(approved))
        self.assertEqual(bundle['approval_state'], 'approved_for_export')
        self.assertEqual(bundle['binding_version'],
                         approved['approval_binding']['version'])
        self.assertEqual(bundle['binding_digest'],
                         approved['approval_binding']['digest'])
        self.assertEqual(bundle['confirmed_claims_count'],
                         len(approved['product_facts']['confirmed_claims']))
        self.assertEqual(bundle['draft_source'],
                         channel_variants.CHECKED_DRAFT_SOURCE)
        self.assertEqual(bundle['channel_approvals'], {})
        self.assertTrue(bundle['no_auto_publish'])
        self.assertIn('no campaign angles', bundle['note'].lower())
        self.assertIn('no auto-publish', bundle['note'].lower())

    def test_variants_not_independently_exportable(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_channel_variants(approved)
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            with self.subTest(channel=channel):
                variant = bundle[channel]
                self.assertFalse(variant['exportable'])
                self.assertFalse(variant['independently_exportable'])
                self.assertTrue(variant['requires_checker_binding'])
                self.assertIsNone(variant.get('checker_approval'))
                self.assertIsNone(variant.get('receipt_id'))
                self.assertIn('not independently exportable',
                              variant['approval_note'].lower())
                self.assertIn('current approved checker',
                              variant['approval_note'].lower())
        self.assertFalse(bundle['provenance']['exportable'])
        self.assertFalse(bundle['provenance']['independently_exportable'])
        self.assertIsNone(bundle['provenance']['checker_approval'])
        self.assertIsNone(bundle['provenance']['receipt_id'])

    def test_x_within_280_and_verbatim(self):
        approved = approved_receipt()
        post = human_review.current_draft(approved)['post']
        bundle = channel_variants.checked_channel_variants(approved)
        x_text = bundle['x']['text']
        if bundle['x']['content_valid']:
            self.assertLessEqual(len(x_text), 280)
            for sentence in channel_variants.split_sentences(x_text):
                self.assertIn(sentence, post)
            if bundle['x']['trim_note']:
                note = bundle['x']['trim_note'].lower()
                self.assertIn('sentence boundary', note)
                self.assertIn('no sentence shortened', note)
                self.assertIn('280', bundle['x']['trim_note'])
            check = channel_variants.validate_x_variant(
                x_text, approved['product_facts']['confirmed_claims'], post)
            self.assertTrue(check['ok'])
            self.assertFalse(check['exportable'])
        else:
            self.assertEqual(x_text, '')
            self.assertIn('revision', bundle['x']['reason'].lower())

    def test_measured_claims_stay_confirmed(self):
        approved = approved_receipt()
        confirmed = approved['product_facts']['confirmed_claims']
        bundle = channel_variants.checked_channel_variants(approved)
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            variant = bundle[channel]
            if not variant['content_valid']:
                self.assertEqual(variant['text'], '')
                continue
            body = variant['text']
            if channel == 'email':
                body += ' ' + variant.get('subject', '')
            tokens = channel_variants._measured_tokens(body)
            joined = ' '.join(confirmed)
            for token in tokens:
                self.assertIn(token, joined)

    def test_tampered_post_refuses_on_binding(self):
        approved = approved_receipt()
        tampered = copy.deepcopy(approved)
        tampered['maker_draft_v2']['post'] += ' Tampered.'
        with self.assertRaises(ValueError) as ctx:
            channel_variants.checked_channel_variants(tampered)
        self.assertIn('binding', str(ctx.exception).lower())

    def test_superseded_revision_refuses(self):
        approved = approved_receipt()
        stale = copy.deepcopy(approved)
        stale['revision'] = 99
        with self.assertRaises(ValueError):
            channel_variants.checked_channel_variants(stale)

    def test_no_audience_or_angle_context_used(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_channel_variants(approved)
        self.assertIsNone(bundle['provenance']['audience_context'])
        self.assertIsNone(bundle['provenance']['angle_context'])
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            with self.subTest(channel=channel):
                self.assertEqual(bundle[channel]['channel'], channel)

    def test_no_publish_surface(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_channel_variants(approved)
        text = str(bundle).lower()
        for marker in ('publish_url', 'post_to', 'schedule_at',
                       'access_token', 'oauth', 'http://', 'https://'):
            self.assertNotIn(marker, text)
        self.assertIn('no auto-publish', bundle['note'].lower())

    def test_receipt_voice_veto_applies_without_new_bans(self):
        pending = offline_receipt()
        post = human_review.current_draft(pending)['post']
        term = first_sentence_term(post)
        voiced = with_voice(pending, [term])
        bound = human_review.approve_current(voiced, 'checked_human')
        self.assertTrue(human_review.exportable(bound))
        bundle = channel_variants.checked_channel_variants(bound)
        for channel in ('linkedin', 'instagram', 'email', 'facebook'):
            with self.subTest(channel=channel):
                variant = bundle[channel]
                self.assertEqual(variant['status'], 'needs_revision')
                self.assertFalse(variant['content_valid'])
                self.assertEqual(variant['text'], '')
                self.assertIn('voice', variant['reason'].lower())
        x_variant = bundle['x']
        self.assertEqual(x_variant['status'], 'needs_revision')
        self.assertFalse(x_variant['content_valid'])
        self.assertEqual(x_variant['text'], '')
        self.assertTrue('voice' in x_variant['reason'].lower()
                        or 'sentence' in x_variant['reason'].lower())
        self.assertFalse(bundle['all_content_valid'])
        self.assertEqual(bundle['binding_digest'],
                         bound['approval_binding']['digest'])

    def test_deterministic_and_inputs_unchanged(self):
        approved = approved_receipt()
        before = copy.deepcopy(approved)
        first = channel_variants.checked_channel_variants(approved)
        second = channel_variants.checked_channel_variants(approved)
        self.assertEqual(first, second)
        self.assertEqual(approved, before)

    def test_exact_text_verifier_accepts_built_variants(self):
        approved = approved_receipt()
        post = human_review.current_draft(approved)['post']
        confirmed = approved['product_facts']['confirmed_claims']
        bundle = channel_variants.checked_channel_variants(approved)
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            with self.subTest(channel=channel):
                variant = bundle[channel]
                if not variant['content_valid']:
                    self.assertEqual(variant['text'], '')
                    continue
                ok, reason = channel_variants.verify_exact_variant_text(
                    channel, variant['text'], variant['subject'], post, confirmed)
                self.assertTrue(ok, reason)

    def test_exact_text_verifier_rejects_transforms(self):
        post = 'Vegan leather wallet. Designed in Texas.'
        confirmed = ['Vegan leather wallet', 'Designed in Texas']
        packed = channel_variants.build_channel_variants(post, confirmed)
        good = packed['linkedin']['text']
        ok, _ = channel_variants.verify_exact_variant_text(
            'linkedin', good, '', post, confirmed)
        self.assertTrue(ok)
        tampered = good.replace('Designed in Texas.', 'Designed on Mars.')
        ok, reason = channel_variants.verify_exact_variant_text(
            'linkedin', tampered, '', post, confirmed)
        self.assertFalse(ok)
        self.assertIn('exact approved', reason)
        reordered = ('Update:\n\nDesigned in Texas.\n\n'
                     'Vegan leather wallet.')
        ok, _ = channel_variants.verify_exact_variant_text(
            'linkedin', reordered, '', post, confirmed)
        self.assertFalse(ok)
        unframed = 'Vegan leather wallet.\n\nDesigned in Texas.'
        ok, _ = channel_variants.verify_exact_variant_text(
            'linkedin', unframed, '', post, confirmed)
        self.assertFalse(ok)
        invented = good + ' Only $1 today.'
        ok, reason = channel_variants.verify_exact_variant_text(
            'linkedin', invented, '', post, confirmed)
        self.assertFalse(ok)
        self.assertIn('exact', reason)
        priced_post = 'Wallet costs $49. Designed in Texas.'
        priced_confirmed = ['Wallet costs $49.', 'Designed in Texas.']
        priced = channel_variants.build_linkedin_variant(
            priced_post, priced_confirmed)
        self.assertEqual(priced['status'], 'candidate_pending_checker')
        ok, reason = channel_variants.verify_exact_variant_text(
            'linkedin', priced['text'], '', priced_post, ['Designed in Texas.'])
        self.assertFalse(ok)
        self.assertIn('Measured claims', reason)
        self.assertIn('$49', reason)
        ok, _ = channel_variants.verify_exact_variant_text(
            'email', packed['email']['text'], 'Wrong subject', post, confirmed)
        self.assertFalse(ok)
        ok, _ = channel_variants.verify_exact_variant_text(
            'sms', 'Hello.', '', post, confirmed)
        self.assertFalse(ok)

    def test_verification_failure_downgrades_without_text(self):
        approved = approved_receipt()
        with patch.object(channel_variants, 'verify_exact_variant_text',
                          return_value=(False, 'probe failure')):
            bundle = channel_variants.checked_channel_variants(approved)
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            with self.subTest(channel=channel):
                variant = bundle[channel]
                self.assertFalse(variant['content_valid'])
                self.assertEqual(variant['text'], '')
                self.assertIn('re-verification', variant['reason'])
        self.assertFalse(bundle['all_content_valid'])

    def test_authorize_copy_binds_exact_text(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_channel_variants(approved)
        channel = next(c for c in ('x', 'linkedin', 'instagram', 'email', 'facebook')
                       if bundle[c]['content_valid'] and bundle[c]['text'])
        bound = channel_variants.approve_channel_variant(approved, channel, 'checked_human', 0)
        record = channel_variants.authorize_channel_copy(bound, channel, 0)
        self.assertTrue(record['copy_authorized'])
        self.assertEqual(record['text'], bundle[channel]['text'])
        self.assertEqual(record['text'], bound['channel_approvals'][channel]['text'])
        self.assertNotEqual(record['text'], '')
        self.assertEqual(record['revision'], 0)
        self.assertEqual(record['approved_by'], 'checked_human')
        self.assertEqual(record['receipt_id'], approved['run_id'])
        self.assertEqual(record['binding_digest'],
                         approved['approval_binding']['digest'])
        self.assertEqual(record['binding_version'],
                         approved['approval_binding']['version'])
        self.assertIn('No auto-publish', record['note'])

    def test_authorize_copy_fields_cohere(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_channel_variants(approved)
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            with self.subTest(channel=channel):
                self.assertIsNone(bundle[channel].get('checker_approval'))
                self.assertIsNone(bundle[channel].get('receipt_id'))
        channel = next(c for c in ('x', 'linkedin', 'instagram', 'email', 'facebook')
                       if bundle[c]['content_valid'] and bundle[c]['text'])
        bound = channel_variants.approve_channel_variant(approved, channel, 'checked_human', 0)
        record = channel_variants.authorize_channel_copy(bound, channel, 0)
        self.assertTrue(record['copy_authorized'])
        self.assertEqual(record['receipt_id'], approved['run_id'])
        self.assertEqual(record['binding_digest'],
                         approved['approval_binding']['digest'])
        self.assertEqual(record['revision'],
                         human_review.current_revision(approved))

    def test_variant_approval_binds_exact_text_and_owner(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_channel_variants(approved)
        channel = next(c for c in ('x', 'linkedin', 'instagram', 'email', 'facebook')
                       if bundle[c]['content_valid'] and bundle[c]['text'])
        bound = channel_variants.approve_channel_variant(approved, channel, 'checked_human', 0)
        stored = bound['channel_approvals'][channel]
        self.assertEqual(stored['text'], bundle[channel]['text'])
        self.assertEqual(stored['subject'], bundle[channel]['subject'])
        self.assertEqual(stored['revision'], 0)
        self.assertEqual(stored['pack_binding_digest'],
                         approved['approval_binding']['digest'])
        self.assertEqual(stored['approved_by'], 'checked_human')
        self.assertEqual(stored['approval_version'],
                         channel_variants.VARIANT_APPROVAL_VERSION)
        expected = channel_variants.variant_approval_digest(
            channel, stored['text'], stored['subject'], 0,
            approved['approval_binding']['digest'])
        self.assertEqual(stored['variant_digest'], expected)
        record, current, reason = channel_variants.channel_approval_status(bound, channel)
        self.assertTrue(current, reason)
        self.assertEqual(record['approved_by'], 'checked_human')
        echo = channel_variants.checked_channel_variants(bound)['channel_approvals']
        self.assertTrue(echo[channel]['current'])
        self.assertEqual(echo[channel]['approved_by'], 'checked_human')

    def test_variant_approval_refuses_unverified_text(self):
        pending = offline_receipt()
        post = human_review.current_draft(pending)['post']
        term = first_sentence_term(post)
        voiced = with_voice(pending, [term])
        bound_pack = human_review.approve_current(voiced, 'checked_human')
        bundle = channel_variants.checked_channel_variants(bound_pack)
        vetoed = [c for c in ('x', 'linkedin', 'instagram', 'email', 'facebook')
                  if not bundle[c]['content_valid']]
        self.assertTrue(vetoed)
        for channel in vetoed:
            with self.subTest(channel=channel):
                with self.assertRaises(ValueError):
                    channel_variants.approve_channel_variant(bound_pack, channel, 'checked_human', 0)
                with self.assertRaises(ValueError):
                    channel_variants.authorize_channel_copy(bound_pack, channel, 0)

    def test_variant_approval_stale_on_revision_and_reapproval(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_channel_variants(approved)
        channel = next(c for c in ('x', 'linkedin', 'instagram', 'email', 'facebook')
                       if bundle[c]['content_valid'] and bundle[c]['text'])
        with self.assertRaises(ValueError) as ctx_wrong:
            channel_variants.approve_channel_variant(approved, channel, 'checked_human', 99)
        self.assertIn('stale', str(ctx_wrong.exception).lower())
        bound = channel_variants.approve_channel_variant(approved, channel, 'checked_human', 0)
        post = human_review.current_draft(approved)['post']
        email = human_review.current_draft(approved)['email']
        revised = human_review.apply_revision(bound, post, email, 'checked_human', 0)
        self.assertEqual(human_review.current_revision(revised), 1)
        with self.assertRaises(ValueError) as ctx_missing:
            channel_variants.approve_channel_variant(revised, channel, 'checked_human')
        self.assertIn('expected_revision', str(ctx_missing.exception).lower())
        with self.assertRaises(ValueError) as ctx_copy:
            channel_variants.authorize_channel_copy(revised, channel, 1)
        self.assertIn('human approval', str(ctx_copy.exception).lower())
        reapproved = human_review.approve_current(revised, 'checked_human', 1)
        self.assertTrue(human_review.exportable(reapproved))
        with self.assertRaises(ValueError):
            channel_variants.authorize_channel_copy(reapproved, channel, 1)
        rebound = channel_variants.approve_channel_variant(reapproved, channel, 'checked_human', 1)
        record = channel_variants.authorize_channel_copy(rebound, channel, 1)
        self.assertTrue(record['copy_authorized'])
        self.assertEqual(record['revision'], 1)

    def test_variant_approval_fails_closed_on_tampering(self):
        approved = approved_receipt()
        bundle = channel_variants.checked_channel_variants(approved)
        channel = next(c for c in ('x', 'linkedin', 'instagram', 'email', 'facebook')
                       if bundle[c]['content_valid'] and bundle[c]['text'])
        bound = channel_variants.approve_channel_variant(approved, channel, 'checked_human', 0)
        edited = copy.deepcopy(bound)
        edited['channel_approvals'][channel]['text'] += ' Tampered.'
        with self.assertRaises(ValueError) as ctx_text:
            channel_variants.authorize_channel_copy(edited, channel, 0)
        self.assertIn('exact', str(ctx_text.exception).lower())
        moved = copy.deepcopy(bound)
        moved['maker_draft_v2']['post'] += ' Tampered.'
        with self.assertRaises(ValueError) as ctx_post:
            channel_variants.authorize_channel_copy(moved, channel, 0)
        self.assertIn('binding', str(ctx_post.exception).lower())
        repolicied = copy.deepcopy(bound)
        blocked = list(repolicied.get('blocked_claims') or [])
        blocked.append('Tampered policy rule.')
        repolicied['blocked_claims'] = blocked
        with self.assertRaises(ValueError) as ctx_policy:
            channel_variants.authorize_channel_copy(repolicied, channel, 0)
        self.assertIn('binding', str(ctx_policy.exception).lower())

    def test_authorize_copy_rejects_stale_revision(self):
        approved = approved_receipt()
        with self.assertRaises(ValueError) as ctx:
            channel_variants.authorize_channel_copy(approved, 'x', 99)
        self.assertIn('stale', str(ctx.exception).lower())
        revised = copy.deepcopy(approved)
        revised['revision'] = 1
        with self.assertRaises(ValueError) as ctx_missing:
            channel_variants.authorize_channel_copy(revised, 'x', None)
        self.assertIn('stale', str(ctx_missing.exception).lower())

    def test_authorize_copy_rejects_unknown_and_unapproved(self):
        approved = approved_receipt()
        with self.assertRaises(ValueError) as ctx_channel:
            channel_variants.authorize_channel_copy(approved, 'sms', 0)
        self.assertIn('unknown channel', str(ctx_channel.exception).lower())
        pending = offline_receipt()
        with self.assertRaises(ValueError):
            channel_variants.authorize_channel_copy(pending, 'x', 0)
        tampered = copy.deepcopy(approved)
        tampered['maker_draft_v2']['post'] += ' Tampered.'
        with self.assertRaises(ValueError) as ctx_binding:
            channel_variants.authorize_channel_copy(tampered, 'x', 0)
        self.assertIn('binding', str(ctx_binding.exception).lower())


class CheckedAdPolicyTests(unittest.TestCase):
    def test_checked_entries_expose_policy_fields(self):
        draft = 'Vegan leather wallet. Designed in Texas.'
        confirmed = ['Vegan leather wallet', 'Designed in Texas']
        packed = channel_variants.build_channel_variants(draft, confirmed)
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            with self.subTest(channel=channel):
                entry = channel_variants._checked_variant_entry(
                    packed[channel])
                self.assertIn('ad_policy_passed', entry)
                self.assertIn('ad_policy_hits', entry)
                self.assertIsInstance(entry['ad_policy_passed'], bool)
                self.assertIsInstance(entry['ad_policy_hits'], list)
                for hit in entry['ad_policy_hits']:
                    self.assertIn('category', hit)
                    self.assertIn('match', hit)
                    self.assertIn('reason', hit)
                self.assertEqual(
                    entry['ad_policy_passed'],
                    len(entry['ad_policy_hits']) == 0,
                )

    def test_checked_entry_matches_direct_lint(self):
        from launchcrew.ad_policy_lint import lint_ad_policy
        draft = 'This wallet is guaranteed to last. Designed in Texas.'
        confirmed = ['wallet', 'Designed in Texas']
        packed = channel_variants.build_channel_variants(draft, confirmed)
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            with self.subTest(channel=channel):
                variant = packed[channel]
                self.assertTrue(variant['content_valid'])
                entry = channel_variants._checked_variant_entry(variant)
                combined = variant['text']
                if channel == 'email':
                    combined += ' ' + variant.get('subject', '')
                self.assertEqual(
                    entry['ad_policy_hits'], lint_ad_policy(combined)
                )
                self.assertFalse(entry['ad_policy_passed'])

    def test_checked_entry_falls_back_to_lint_without_stored_fields(self):
        from launchcrew.ad_policy_lint import lint_ad_policy
        legacy = {
            'channel': 'x',
            'variant_kind': channel_variants.VARIANT_KIND,
            'text': 'This wallet is guaranteed to last.',
            'content_valid': True,
            'status': 'candidate_pending_checker',
            'metadata': {},
        }
        entry = channel_variants._checked_variant_entry(legacy)
        self.assertFalse(entry['ad_policy_passed'])
        self.assertEqual(
            entry['ad_policy_hits'],
            lint_ad_policy('This wallet is guaranteed to last.'),
        )
        self.assertTrue(
            any(h['match'] == 'guaranteed'
                for h in entry['ad_policy_hits'])
        )


if __name__ == '__main__':
    unittest.main()
