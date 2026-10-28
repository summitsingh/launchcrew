"""Pure photo-gate unit tests: no DB, no network, no provider.

Covers fail-closed receipt gating for every photo path, the prior-state
history snapshot, honest transport accounting, stdlib-only imports for
the pure helpers, and reject-before-load input bounds.
"""
import base64
import struct
import sys
import zlib

import pytest

from backend import photo_review
from backend.photo_input import MAX_B64_CHARS, parse_photo_data_uri
from launchcrew import photo_policy


def _receipt(**overrides):
    base = {'status': 'completed', 'revision': 0, 'approval_state': 'pending_approval',
            'approvals': [], 'maker_draft_v2': {'post': 'p', 'email': 'e', 'claims': []},
            'checker_v2': {'blocked_count': 0, 'verified_count': 1, 'blocked_claims': [],
                           'revision_instructions': []},
            'revision_history': []}
    base.update(overrides)
    return base


def test_pure_helpers_import_without_pillow_or_sqlalchemy():
    blocked_prefixes = ('PIL', 'sqlalchemy')
    saved = {}
    for name in [m for m in sys.modules if m.split('.')[0] in blocked_prefixes
                 or m in ('backend.photo_review', 'backend.photo_input', 'launchcrew.photo_policy')]:
        saved[name] = sys.modules.pop(name)

    class _Blocker:
        def find_module(self, name, path=None):
            if name.split('.')[0] in blocked_prefixes:
                return self
            return None

        def load_module(self, name):
            raise ImportError('blocked for pure-gate proof: ' + name)

    sys.meta_path.insert(0, _Blocker())
    try:
        import importlib
        importlib.import_module('launchcrew.photo_policy')
        importlib.import_module('backend.photo_review')
        importlib.import_module('backend.photo_input')
    finally:
        sys.meta_path.pop(0)
        sys.modules.update(saved)


def test_absent_status_is_legacy_no_photo_and_passes():
    assert photo_review.photo_status_of(_receipt())['state'] == 'no_photo'
    assert photo_review.photo_block_reason(_receipt()) is None


def test_present_malformed_and_unknown_states_fail_closed():
    for bad in ('checked?', 0, True, [], ['checked']):
        receipt = _receipt(photo_status=bad)
        assert photo_review.photo_status_of(receipt)['state'] != 'no_photo'
        assert photo_review.photo_block_reason(receipt) is not None
    for bad in ({}, {'label': 'detected', 'reason': 'x',
                     'policy_version': 'photo-geometry/v1',
                     'revision': 1, 'actor': '', 'checked_at': ''},
                {'state': None, 'label': 'detected', 'reason': 'x',
                 'policy_version': 'photo-geometry/v1',
                 'revision': 1, 'actor': '', 'checked_at': ''}):
        receipt = _receipt(photo_status=bad)
        assert photo_review.photo_status_of(receipt)['state'] != 'no_photo'
        assert photo_review.photo_block_reason(receipt) is not None
    receipt = _receipt(photo_status={'state': 'mystery', 'label': 'detected',
                                     'reason': 'x', 'policy_version': 'photo-geometry/v1',
                                     'revision': 1, 'actor': '', 'checked_at': ''})
    assert photo_review.photo_block_reason(receipt) is not None


def test_all_gate_paths():
    assert photo_review.photo_block_reason(_receipt(photo_status={
        'state': 'requested_unchecked', 'label': None, 'reason': 'not_run: x',
        'policy_version': 'photo-geometry/v1', 'revision': 1, 'actor': '', 'checked_at': '',
    }, revision=1)) is not None
    assert photo_review.photo_block_reason(_receipt(photo_status={
        'state': 'check_requested', 'label': None, 'reason': 'check_requested: y',
        'policy_version': 'photo-geometry/v1', 'revision': 1, 'actor': '', 'checked_at': '',
    }, revision=1)) is not None
    detected = {'state': 'checked', 'label': 'detected', 'reason': 'clear_single',
                'policy_version': 'photo-geometry/v1', 'revision': 1, 'actor': 'a', 'checked_at': 't'}
    assert photo_review.photo_block_reason(_receipt(photo_status=dict(detected), revision=1)) is None
    assert photo_review.photo_block_reason(_receipt(photo_status=dict(detected), revision=2)) is not None
    bool_rev = dict(detected, revision=True)
    assert photo_review.photo_block_reason(_receipt(photo_status=bool_rev, revision=1)) is not None
    for label, reason in (('not_detected', 'no_match'), ('possible_clipping', 'edge_or_size_gate'),
                          ('unknown', 'needs_review'), ('unknown', 'delivery_failed'),
                          ('unknown', 'fix_photo')):
        status = dict(detected, label=label, reason=reason)
        assert photo_review.photo_block_reason(_receipt(photo_status=status, revision=1)) is not None
    assert photo_review.photo_block_reason(_receipt(status='failed', photo_status=dict(detected),
                                                     revision=1)) is None


def test_history_snapshot_keeps_prior_photo_state_and_text_source():
    receipt = _receipt(revision=1, photo_status={
        'state': 'check_requested', 'label': None, 'reason': 'check_requested: segmentation in flight',
        'policy_version': 'photo-geometry/v1', 'revision': 1, 'actor': 'a', 'checked_at': 't'})
    before = list(receipt['revision_history'])
    revised = photo_review.apply_photo_event(
        receipt, event=photo_review.PHOTO_EVENT_REMOVED, actor='a',
        status=photo_review.blank_photo_status())
    assert revised['revision'] == 2
    assert revised['photo_status']['state'] == 'no_photo'
    entry = revised['revision_history'][-1]
    assert entry['photo_event'] == 'photo_removed'
    assert entry['photo_status']['state'] == 'check_requested'
    assert entry['photo_status']['revision'] == 1
    assert revised['revision_history'][:len(before)] == before
    assert 'human_draft' not in revised or revised.get('human_draft') is None


def test_pending_receipt_audit_step_is_requested_not_checked():
    receipt = _receipt(revision=0)
    revised = photo_review.apply_photo_event(
        receipt, event=photo_review.PHOTO_EVENT_CHECKED, actor='a',
        status={'state': 'check_requested', 'label': None,
                'reason': 'check_requested: segmentation in flight',
                'policy_version': 'photo-geometry/v1'})
    assert revised['audit']['event_log'][-1]['step'] == 'photo_check_requested'
    assert revised['revision_history'][-1]['photo_event'] == 'photo_checked'
    terminal = photo_review.attach_verdict(
        revised, label='detected', reason='clear_single', actor='a',
        uploads=1, segmentations=1, segmented=True)
    assert terminal['audit']['event_log'][-1]['step'] == 'photo_checked'


def test_attach_verdict_reports_actual_attempts():
    done = photo_review.attach_verdict(_receipt(revision=1), label='detected',
                                       reason='clear_single', actor='a',
                                       uploads=1, segmentations=1, segmented=True)
    assert done['photo_transport']['last_handling'] == 'segmented'
    assert done['photo_transport']['uploads'] == 1
    assert done['photo_transport']['segmentations'] == 1
    assert 'sent to the segmentation provider' in done['photo_transport']['note']
    failed = photo_review.attach_verdict(_receipt(revision=1), label='unknown',
                                         reason='delivery_failed', actor='a',
                                         uploads=1, segmentations=0, segmented=False)
    assert failed['photo_transport']['last_handling'] == 'delivery_failed'
    assert failed['photo_transport']['uploads'] == 1
    assert failed['photo_transport']['segmentations'] == 0
    text = str(failed['photo_transport']['note'])
    assert 'attempted' in text
    assert 'no completed segmentation result was confirmed' in text
    assert 'nothing was segmented' not in text
    assert 'sent to the segmentation provider' not in text
    untouched = photo_review.attach_verdict(_receipt(revision=1), label='unknown',
                                            reason='fix_photo', actor='a')
    assert untouched['photo_transport']['last_handling'] == 'delivery_failed'
    assert 'No photo bytes were sent' in untouched['photo_transport']['note']


def _chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)


def _png(width, height, rgb=(200, 30, 30)):
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    raw_scan = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', ihdr)
            + _chunk(b'IDAT', zlib.compress(raw_scan)) + _chunk(b'IEND', b''))


def _uri(raw, mime='png'):
    return 'data:image/%s;base64,' % mime + base64.b64encode(raw).decode()


def test_enormous_header_dims_rejected_before_pixel_allocation():
    tiny = (b'\x89PNG\r\n\x1a\n'
            + _chunk(b'IHDR', struct.pack('>IIBBBBB', 10000, 10000, 8, 2, 0, 0, 0))
            + _chunk(b'IEND', b''))
    assert len(tiny) < 100
    with pytest.raises(Exception, match='8 million pixel'):
        parse_photo_data_uri(_uri(tiny))


def test_overlong_encoding_rejected_before_base64_allocation():
    with pytest.raises(Exception, match='1 MiB'):
        parse_photo_data_uri('data:image/png;base64,' + 'A' * (MAX_B64_CHARS + 4))


def test_exact_bytes_preserved_and_malformed_rejected():
    raw = _png(4, 3)
    parsed = parse_photo_data_uri(_uri(raw))
    assert parsed['raw'] == raw
    assert (parsed['width'], parsed['height']) == (4, 3)
    with pytest.raises(Exception):
        parse_photo_data_uri(_uri(b'not an image at all'))
    with pytest.raises(Exception):
        parse_photo_data_uri(_uri(raw[:20]))
