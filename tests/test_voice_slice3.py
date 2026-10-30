"""Slice 3 voice vertical slice: synthetic style-only core behavior.

All fixtures are synthetic style references about gardens, trails, and
recipe cards. No real names, emails, account IDs, photos, secrets, or
personal data appear here. No Summit copy is used. Voice samples are
style references only and never become confirmed facts.

Socket-free and offline only. Provider paths are never touched; keyless
runs patch the transport boundary to assert no model call.
"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import adapter
from launchcrew import agents, human_review
from launchcrew.channel_variants import (
    STATUS_CANDIDATE,
    STATUS_NEEDS_REVISION,
    build_channel_variants,
)
from launchcrew.facts import load_facts
from launchcrew.run import check_pack
from launchcrew.voice_profile import (
    STYLE_ONLY_NOTICE,
    snapshot_digest,
    snapshot_version,
    validate_profile,
    voice_block_reason,
    voice_single_block_for_text,
)

ROOT = Path(__file__).resolve().parents[1]
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


def _examples(count=3):
    topics = ('garden layout', 'trail map', 'recipe card', 'shelf plan', 'park sign')
    out = []
    for i in range(count):
        topic = topics[i % len(topics)]
        out.append({
            'input': 'Synthetic draft %d about %s' % (i + 1, topic),
            'output': 'Synthetic revision %d about %s' % (i + 1, topic),
        })
    return out


def _voice_content(banned_terms=None):
    payload = {'examples': _examples(3)}
    if banned_terms is not None:
        payload['banned_terms'] = list(banned_terms)
    return payload


def _voice_item(item_id='mem_voice', banned_terms=None, title='Synthetic voice'):
    return {
        'id': item_id,
        'kind': 'voice_profile',
        'title': title,
        'content': _voice_content(banned_terms),
    }


def _offline_execute(run_id, memory_items):
    profile = agents.load_agent('Maker', ROOT / 'agents')
    env = {'META_API_KEY': '', 'META_WONDER_MODEL': ''}
    with patch.dict(os.environ, env):
        with patch('launchcrew.run.spark_for_agent',
                   side_effect=AssertionError('no transport keyless')), \
             patch('launchcrew.run.wonder_synthesize_for_scout',
                   side_effect=AssertionError('no transport keyless')):
            return adapter.execute(run_id, IDEA, profile, False, memory_items=memory_items)


class VoiceSnapshotTests(unittest.TestCase):
    def test_version_and_digest_deterministic(self):
        first = validate_profile(_voice_content(['harbor']))
        second = validate_profile(_voice_content(['harbor']))
        self.assertEqual(snapshot_digest(first), snapshot_digest(second))
        self.assertEqual(snapshot_version(first), snapshot_version(second))
        self.assertTrue(snapshot_version(first).startswith('voice/v1:'))
        self.assertEqual(len(snapshot_digest(first)), 64)

    def test_term_order_does_not_change_version(self):
        first = validate_profile(_voice_content(['zebra', 'apple']))
        second = validate_profile(_voice_content(['apple', 'zebra']))
        self.assertEqual(snapshot_version(first), snapshot_version(second))

    def test_concrete_reason_names_source_and_term(self):
        reason = voice_block_reason('harbor', 'Synthetic voice', 'voice/v1:abc123')
        self.assertIn('Synthetic voice', reason)
        self.assertIn('voice/v1:abc123', reason)
        self.assertIn('harbor', reason)
        self.assertIn('Blocked by voice profile', reason)

    def test_reason_falls_back_without_source(self):
        reason = voice_block_reason('harbor', None, None)
        self.assertIn('voice', reason)
        self.assertIn('harbor', reason)

    def test_single_block_combines_terms(self):
        snap = validate_profile(_voice_content(['apple', 'zebra']))
        ref = {'title': 'Synthetic voice', 'version': 'voice/v1:test'}
        hit = voice_single_block_for_text(snap, 'Apple near zebra.', ref)
        self.assertIsNotNone(hit)
        self.assertIn('Synthetic voice', hit['reason'])
        self.assertIn('apple', hit['reason'].lower())
        self.assertIn('zebra', hit['reason'].lower())
        clean = voice_single_block_for_text(snap, 'Synthetic garden note.', ref)
        self.assertIsNone(clean)


class VoiceCheckPackTests(unittest.TestCase):
    def setUp(self):
        self.facts, _ = load_facts(ROOT / 'facts/demo_facts.json')

    def test_banned_term_blocks_supported_claim_with_voice_reason(self):
        snap = validate_profile(_voice_content(['Texas']))
        ref = {'title': 'Synthetic voice', 'version': snapshot_version(snap)}
        draft = {'claims': ['Designed in Texas'], 'post': 'Designed in Texas.', 'email': 'Designed in Texas.'}
        result = check_pack(draft, self.facts, voice_snapshot=snap, voice_ref=ref)
        self.assertGreaterEqual(result['blocked_count'], 1)
        reasons = [b['reason'] for b in result['blocked_claims']]
        self.assertTrue(any('Synthetic voice' in r and 'Texas' in r for r in reasons))
        self.assertTrue(any('Blocked by voice profile' in r for r in reasons))

    def test_unsupported_claim_stays_blocked_with_voice(self):
        snap = validate_profile(_voice_content(['harbor']))
        ref = {'title': 'Synthetic voice', 'version': snapshot_version(snap)}
        draft = {'claims': ['best in Texas'], 'post': 'best in Texas.', 'email': 'best in Texas.'}
        result = check_pack(draft, self.facts, voice_snapshot=snap, voice_ref=ref)
        self.assertIn('best in Texas', [c['claim'] for c in result['blocked_claims']])

    def test_clean_text_passes_with_voice(self):
        snap = validate_profile(_voice_content(['harbor']))
        ref = {'title': 'Synthetic voice', 'version': snapshot_version(snap)}
        draft = {'claims': ['$49'], 'post': '$49.', 'email': '$49.'}
        result = check_pack(draft, self.facts, voice_snapshot=snap, voice_ref=ref)
        self.assertEqual(result['blocked_count'], 0)

    def test_empty_voice_never_blocks(self):
        snap = validate_profile(_voice_content([]))
        draft = {'claims': ['Designed in Texas'], 'post': 'Designed in Texas.', 'email': 'Designed in Texas.'}
        result = check_pack(draft, self.facts, voice_snapshot=snap, voice_ref={})
        self.assertEqual(result['blocked_count'], 0)

    def test_malformed_voice_snapshot_fails_closed(self):
        draft = {'claims': ['$49'], 'post': '$49.', 'email': '$49.'}
        with self.assertRaises((TypeError, ValueError)):
            check_pack(draft, self.facts, voice_snapshot={'banned_terms': 'not-a-list'}, voice_ref={})


class VoiceAdapterTests(unittest.TestCase):
    def test_first_valid_voice_wins(self):
        bad = {'id': 'mem_bad', 'kind': 'voice_profile', 'title': 'Bad',
               'content': {'examples': [{'input': 'only one'}]}}
        first = _voice_item('mem_first', ['harbor'])
        second = _voice_item('mem_second', ['zebra'])
        snap, ref, examples = adapter._voice_selection([bad, first, second])
        self.assertIsNotNone(snap)
        self.assertEqual(ref['id'], 'mem_first')
        self.assertEqual(len(examples), 3)
        self.assertIn('harbor', snap['banned_terms'])

    def test_malformed_voice_fails_closed_never_facts(self):
        items = [
            {'id': 'm1', 'kind': 'voice_profile', 'title': 'Bad', 'content': 'not-a-dict'},
            {'id': 'm2', 'kind': 'voice_profile', 'title': 'Bad2',
             'content': {'examples': [], 'banned_terms': ['harbor']}},
        ]
        with self.assertRaises(ValueError):
            adapter._voice_selection(items)
        claims, blocked, _, _, _, _ = adapter._memory_effects(items)
        self.assertEqual(claims, [])
        self.assertEqual(blocked, [])

    def test_voice_content_never_enters_allowlist(self):
        voice = _voice_item('mem_voice', ['harbor'])
        voice['content']['claim'] = 'best in Texas'
        brand = {'id': 'mem_fact', 'kind': 'brand_fact', 'title': 'Fact',
                 'content': {'claim': 'Handmade vegan wallet for commuters'}}
        claims, blocked, _, _, _, used = adapter._memory_effects([voice, brand])
        self.assertEqual(claims, ['Handmade vegan wallet for commuters'])
        self.assertNotIn('best in Texas', claims)
        self.assertEqual([u['id'] for u in used], ['mem_voice', 'mem_fact'])

    def test_receipt_carries_voice_source_and_counts(self):
        receipt = _offline_execute('run_voice_receipt', [_voice_item('mem_v1', ['harbor'])])
        voice = receipt.get('voice_profile')
        self.assertIsInstance(voice, dict)
        self.assertEqual(voice['id'], 'mem_v1')
        self.assertEqual(voice['title'], 'Synthetic voice')
        self.assertTrue(str(voice['version']).startswith('voice/v1:'))
        self.assertEqual(len(voice['digest']), 64)
        self.assertEqual(voice['example_count'], 3)
        self.assertEqual(voice['banned_term_count'], 1)
        self.assertEqual(voice['banned_terms'], ['harbor'])
        self.assertIn('style references only', voice['notice'])
        self.assertIn('never become confirmed facts', voice['notice'])

    def test_keyless_drafts_identical_with_style_only_voice(self):
        with_voice = _offline_execute('run_voice_style', [_voice_item('mem_vs', [])])
        without = _offline_execute('run_voice_plain', [])
        self.assertEqual(with_voice['maker_draft_v1']['post'], without['maker_draft_v1']['post'])
        self.assertEqual(with_voice['maker_draft_v2']['post'], without['maker_draft_v2']['post'])
        self.assertEqual(with_voice['checker_v1']['blocked_count'], 0)
        self.assertIsNotNone(with_voice['voice_profile'])
        self.assertIsNone(without.get('voice_profile'))

    def test_banned_term_filters_v2_and_records_v1_block(self):
        receipt = _offline_execute('run_voice_texas', [_voice_item('mem_vt', ['Texas'])])
        v1_claims = [c['claim'] for c in receipt['checker_v1']['blocked_claims']]
        self.assertIn('Designed in Texas', v1_claims)
        reasons = [c['reason'] for c in receipt['checker_v1']['blocked_claims']]
        self.assertTrue(any('Blocked by voice profile' in r and 'Texas' in r for r in reasons))
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        self.assertNotIn('Designed in Texas', receipt['maker_draft_v2']['post'])
        self.assertNotIn('Designed in Texas', receipt['maker_draft_v2']['claims'])

    def test_voice_examples_never_bypass_checker(self):
        payload = _voice_content([])
        payload['examples'][0]['output'] = 'best in Texas synthetic style line'
        voice = {'id': 'mem_vb', 'kind': 'voice_profile', 'title': 'Synthetic voice', 'content': payload}
        profile = agents.load_agent('Maker', ROOT / 'agents')
        env = {'META_API_KEY': '', 'META_WONDER_MODEL': ''}
        with patch.dict(os.environ, env):
            with patch('launchcrew.run.spark_for_agent',
                       side_effect=AssertionError('no transport')), \
                 patch('launchcrew.run.wonder_synthesize_for_scout',
                       side_effect=AssertionError('no transport')):
                receipt = adapter.execute('run_voice_seed', IDEA, profile, True, memory_items=[voice])
        self.assertIn('best in Texas', [c['claim'] for c in receipt['checker_v1']['blocked_claims']])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        self.assertNotIn('best in Texas', receipt['maker_draft_v2']['post'])


class VoiceHumanReviewTests(unittest.TestCase):
    def _voiced_receipt(self, run_id='run_voice_hr', terms=None):
        terms = ['harbor'] if terms is None else terms
        return _offline_execute(run_id, [_voice_item('mem_hr', terms)])

    def test_recheck_rejects_banned_term_edit(self):
        receipt = self._voiced_receipt()
        good_email = 'For Austin commuters. $49.'
        with self.assertRaises(human_review.NeedsRevision) as ctx:
            human_review.apply_revision(receipt, 'Visit the harbor at noon.', good_email, 'synthetic_human', 0)
        reasons = [c['reason'] for c in ctx.exception.check['blocked_claims']]
        self.assertTrue(any('Blocked by voice profile' in r for r in reasons))

    def test_recheck_accepts_clean_edit(self):
        receipt = self._voiced_receipt()
        revised = human_review.apply_revision(
            receipt, 'Vegan leather wallet. Designed in Texas.', 'For Austin commuters. $49.',
            'synthetic_human', 0)
        self.assertEqual(revised['revision'], 1)
        self.assertEqual(revised['human_check']['blocked_count'], 0)

    def test_binding_covers_voice_and_tamper_invalidates(self):
        receipt = self._voiced_receipt()
        approved = human_review.approve_current(receipt, 'synthetic_human')
        self.assertTrue(human_review.exportable(approved))
        payload = human_review.approval_binding_payload(approved)
        self.assertIsNotNone(payload['voice'])
        self.assertEqual(payload['voice']['id'], 'mem_hr')
        text = str(payload)
        self.assertNotIn('Synthetic revision 1', text)
        tampered = copy.deepcopy(approved)
        tampered['voice_profile']['banned_terms'] = ['tampered-term']
        self.assertFalse(human_review.exportable(tampered))
        bound, reason = human_review.binding_status(tampered)
        self.assertFalse(bound)
        self.assertIn('binding', reason.lower())

    def test_historical_receipt_binds_voice_none(self):
        receipt = _offline_execute('run_voice_none', [])
        self.assertIsNone(receipt.get('voice_profile'))
        payload = human_review.approval_binding_payload(receipt)
        self.assertIsNone(payload['voice'])
        approved = human_review.approve_current(receipt, 'synthetic_human')
        self.assertTrue(human_review.exportable(approved))

    def test_stale_voice_blocks_approve_and_export_until_revision(self):
        receipt = self._voiced_receipt()
        stale = copy.deepcopy(receipt)
        stale['voice_stale'] = True
        stale['approval_state'] = 'pending_approval'
        with self.assertRaisesRegex(ValueError, 'stale'):
            human_review.approve_current(stale, 'synthetic_human')
        approved = human_review.approve_current(receipt, 'synthetic_human')
        approved_stale = copy.deepcopy(approved)
        approved_stale['voice_stale'] = True
        self.assertFalse(human_review.exportable(approved_stale))
        with self.assertRaisesRegex(ValueError, 'stale'):
            human_review.record_export(approved_stale, 'synthetic_human')
        revised = human_review.apply_revision(
            stale, 'Vegan leather wallet. Designed in Texas.', 'For Austin commuters. $49.',
            'synthetic_human', 0)
        self.assertNotIn('voice_stale', revised)
        reapproved = human_review.approve_current(revised, 'synthetic_human', 1)
        self.assertTrue(human_review.exportable(reapproved))

    def test_history_preserves_prior_voice_context(self):
        receipt = self._voiced_receipt()
        revised = human_review.apply_revision(
            receipt, 'Vegan leather wallet. Designed in Texas.', 'For Austin commuters. $49.',
            'synthetic_human', 0)
        entry = revised['revision_history'][-1]
        self.assertEqual(entry['voice_profile']['id'], 'mem_hr')
        self.assertFalse(entry['voice_stale'])


class VoiceChannelTests(unittest.TestCase):
    def test_banned_term_refuses_candidate_with_voice_reason(self):
        snap = validate_profile(_voice_content(['harbor']))
        ref = {'title': 'Synthetic voice', 'version': snapshot_version(snap)}
        draft = 'Visit the harbor at noon. Designed in Texas.'
        bundle = build_channel_variants(draft, ['Designed in Texas'], voice_snapshot=snap, voice_ref=ref)
        blocked = [bundle[ch] for ch in ('x', 'linkedin', 'instagram', 'email', 'facebook')
                   if bundle[ch]['status'] == STATUS_NEEDS_REVISION]
        self.assertTrue(blocked)
        for variant in blocked:
            self.assertTrue(variant['metadata'].get('voice_blocked'))
            self.assertIn('Blocked by voice profile', variant['metadata'].get('voice_reason', ''))
            self.assertIn('Synthetic voice', variant['reason'])
            self.assertFalse(variant['exportable'])
            self.assertFalse(variant['independently_exportable'])
        self.assertEqual(bundle['provenance']['voice']['title'], 'Synthetic voice')
        self.assertEqual(bundle['provenance']['voice']['banned_term_count'], 1)

    def test_clean_candidate_marks_voice_checked(self):
        snap = validate_profile(_voice_content(['harbor']))
        ref = {'title': 'Synthetic voice', 'version': snapshot_version(snap)}
        bundle = build_channel_variants('Designed in Texas.', ['Designed in Texas'],
                                        voice_snapshot=snap, voice_ref=ref)
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            variant = bundle[channel]
            if variant['status'] == STATUS_CANDIDATE:
                self.assertFalse(variant['metadata'].get('voice_blocked'))
        self.assertIsNotNone(bundle['provenance']['voice'])

    def test_absent_voice_leaves_provenance_empty(self):
        bundle = build_channel_variants('Designed in Texas.', ['Designed in Texas'])
        self.assertIsNone(bundle['provenance']['voice'])
        for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
            self.assertNotIn('voice_blocked', bundle[channel].get('metadata', {}))

    def test_style_notice_constant_states_boundary(self):
        for phrase in ('style references only', 'never factual', 'never bypass Checker',
                       'never become confirmed facts'):
            self.assertIn(phrase, STYLE_ONLY_NOTICE)


class VoiceCrossSentenceTests(unittest.TestCase):
    def setUp(self):
        self.facts, _ = load_facts(ROOT / 'facts/demo_facts.json')

    def test_check_pack_blocks_term_across_period(self):
        snap = validate_profile(_voice_content(['blue moon']))
        ref = {'title': 'Synthetic voice', 'version': snapshot_version(snap)}
        draft = {'claims': [], 'post': 'Blue. Moon.', 'email': 'For Austin commuters. $49.'}
        result = check_pack(draft, self.facts, voice_snapshot=snap, voice_ref=ref)
        reasons = [block['reason'] for block in result['blocked_claims']]
        self.assertTrue(any('Blocked by voice profile' in reason and 'blue moon' in reason.lower()
                            for reason in reasons))
        self.assertTrue(any('Synthetic voice' in reason for reason in reasons))

    def test_check_pack_blocks_term_across_newline_in_email(self):
        snap = validate_profile(_voice_content(['blue moon']))
        ref = {'title': 'Synthetic voice', 'version': snapshot_version(snap)}
        draft = {'claims': [], 'post': 'For Austin commuters. $49.', 'email': 'Blue\nMoon'}
        result = check_pack(draft, self.facts, voice_snapshot=snap, voice_ref=ref)
        reasons = [block['reason'] for block in result['blocked_claims']]
        self.assertTrue(any('Blocked by voice profile' in reason and 'blue moon' in reason.lower()
                            for reason in reasons))

    def test_check_pack_preserves_factual_and_adds_voice_for_full(self):
        snap = validate_profile(_voice_content(['blue moon']))
        ref = {'title': 'Synthetic voice', 'version': snapshot_version(snap)}
        draft = {'claims': [], 'post': 'Blue. Moon.', 'email': 'For Austin commuters. $49.'}
        result = check_pack(draft, self.facts, voice_snapshot=snap, voice_ref=ref)
        claims = [block['claim'] for block in result['blocked_claims']]
        reasons = [block['reason'] for block in result['blocked_claims']]
        self.assertIn('Blue', claims)
        self.assertIn('Moon', claims)
        self.assertIn('Blue. Moon.', claims)
        self.assertTrue(any('not found' in reason.lower() or 'unsupported' in reason.lower()
                            or 'not in approved' in reason.lower() for reason in reasons))
        self.assertTrue(any('Blocked by voice profile' in reason for reason in reasons))

    def test_check_pack_adds_voice_reason_when_sentence_already_blocked(self):
        snap = validate_profile(_voice_content(['harbor']))
        ref = {'title': 'Synthetic voice', 'version': snapshot_version(snap)}
        draft = {'claims': [], 'post': 'Visit the harbor at noon.', 'email': 'For Austin commuters. $49.'}
        result = check_pack(draft, self.facts, voice_snapshot=snap, voice_ref=ref)
        matches = [block for block in result['blocked_claims']
                   if block['claim'] == 'Visit the harbor at noon']
        self.assertGreaterEqual(len(matches), 2)
        joined = ' '.join(block['reason'] for block in matches)
        self.assertIn('Blocked by voice profile', joined)
        found = [entry for entry in result['claim_results']
                 if entry.get('claim') == 'Visit the harbor at noon']
        self.assertTrue(found)
        self.assertIn('Blocked by voice profile', found[0]['reason'])
        self.assertIn(';', found[0]['reason'])

    def test_pipeline_v2_never_clean_with_cross_sentence_term(self):
        brand_blue = {'id': 'mem_blue', 'kind': 'brand_fact', 'title': 'Blue fact',
                      'content': {'claim': 'Blue'}}
        brand_moon = {'id': 'mem_moon', 'kind': 'brand_fact', 'title': 'Moon fact',
                      'content': {'claim': 'Moon'}}
        voice = _voice_item('mem_cross', ['blue moon'])
        receipt = _offline_execute('run_voice_cross_v2', [brand_blue, brand_moon, voice])
        self.assertNotEqual(receipt.get('status'), 'completed')
        self.assertEqual(receipt.get('status'), 'failed')
        voice_ref = receipt.get('voice_profile') or {}
        self.assertIn('blue moon', [term.lower() for term in voice_ref.get('banned_terms', [])])

    def test_human_revision_rejects_cross_sentence_term(self):
        receipt = _offline_execute('run_voice_cross_hr', [_voice_item('mem_hrx', ['blue moon'])])
        with self.assertRaises(human_review.NeedsRevision) as ctx:
            human_review.apply_revision(receipt, 'Blue. Moon.', 'For Austin commuters. $49.',
                                        'synthetic_human', 0)
        reasons = [block['reason'] for block in ctx.exception.check['blocked_claims']]
        self.assertTrue(any('Blocked by voice profile' in reason and 'blue moon' in reason.lower()
                            for reason in reasons))

    def test_human_revision_preserves_factual_and_voice_overlap(self):
        receipt = _offline_execute('run_voice_cross_overlap', [_voice_item('mem_hro', ['blue moon'])])
        with self.assertRaises(human_review.NeedsRevision) as ctx:
            human_review.apply_revision(receipt, 'Blue. Moon.', 'For Austin commuters. $49.',
                                        'synthetic_human', 0)
        claims = [block['claim'] for block in ctx.exception.check['blocked_claims']]
        reasons = [block['reason'] for block in ctx.exception.check['blocked_claims']]
        self.assertIn('Blue', claims)
        self.assertIn('Blue. Moon.', claims)
        self.assertTrue(any('Blocked by voice profile' in reason for reason in reasons))

    def test_clean_voiced_revision_still_approvable_and_exportable(self):
        receipt = _offline_execute('run_voice_cross_clean', [_voice_item('mem_hrc', ['blue moon'])])
        revised = human_review.apply_revision(
            receipt, 'Vegan leather wallet. Designed in Texas.', 'For Austin commuters. $49.',
            'synthetic_human', 0)
        self.assertEqual(revised['revision'], 1)
        approved = human_review.approve_current(revised, 'synthetic_human', 1)
        self.assertTrue(human_review.exportable(approved))
        exported = human_review.record_export(approved, 'synthetic_human')
        self.assertEqual(exported['exported_revision'], 1)

    def test_human_recheck_fails_closed_on_malformed_voice(self):
        receipt = _offline_execute('run_voice_malformed_hr', [_voice_item('mem_hrm', ['harbor'])])
        broken = copy.deepcopy(receipt)
        broken['voice_profile'] = {'id': 'mem_hrm', 'title': 'Synthetic voice',
                                   'version': 'voice/v1:test', 'digest': 'd' * 64,
                                   'example_count': 3, 'banned_term_count': 1,
                                   'banned_terms': 'not-a-list', 'notice': STYLE_ONLY_NOTICE}
        with self.assertRaises(ValueError):
            human_review.recheck_text('Vegan leather wallet. Designed in Texas.',
                                      'For Austin commuters. $49.', broken)


if __name__ == '__main__':
    unittest.main()
