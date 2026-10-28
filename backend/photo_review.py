"""Pure photo-revision helpers: receipt photo state and gating.

No I/O, no network, no database. These helpers read and build plain
receipt dicts only. The small revision/draft/check readers below mirror
``launchcrew.human_review`` semantics for the same keys; the approval
and export gates there delegate to :func:`photo_block_reason`.

Privacy: receipts, history, and audit entries built here hold only the
sanitized summary ``{label, reason, policy_version, actor, time}``.
No image bytes, digests, filenames, provider file IDs, or geometry.
"""
import copy

from launchcrew.photo_policy import PHOTO_POLICY_VERSION
from launchcrew.receipts import timestamp

PHOTO_EVENT_CHECKED = 'photo_checked'
PHOTO_EVENT_REMOVED = 'photo_removed'

STATE_NO_PHOTO = 'no_photo'
STATE_REQUESTED_UNCHECKED = 'requested_unchecked'
STATE_CHECK_REQUESTED = 'check_requested'
STATE_CHECKED = 'checked'

BLOCKING_STATES = (STATE_REQUESTED_UNCHECKED, STATE_CHECK_REQUESTED)


def _current_revision(receipt):
    try:
        raw = receipt.get('revision', 0)
        if isinstance(raw, bool):
            return 0
        value = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return value if value >= 0 else 0


def _current_draft(receipt):
    if _current_revision(receipt) > 0 and isinstance(receipt.get('human_draft'), dict):
        human = receipt['human_draft']
        if isinstance(human.get('post'), str) and isinstance(human.get('email'), str):
            return {'post': human['post'], 'email': human['email'],
                    'claims': list(human.get('claims') or [])}
    maker = receipt.get('maker_draft_v2') or {}
    return {'post': maker.get('post'), 'email': maker.get('email'),
            'claims': list(maker.get('claims') or [])}


def _current_check(receipt):
    if _current_revision(receipt) > 0 and isinstance(receipt.get('human_check'), dict):
        return receipt['human_check']
    return receipt.get('checker_v2')


def blank_photo_status():
    """The no-photo legacy state: text-only gates apply unchanged."""
    return {'state': STATE_NO_PHOTO, 'label': None, 'reason': 'no_photo',
            'policy_version': PHOTO_POLICY_VERSION, 'revision': 0,
            'actor': '', 'checked_at': ''}


def photo_status_of(receipt):
    """Return the receipt photo status, defaulting to no-photo legacy."""
    status = receipt.get('photo_status')
    if not isinstance(status, dict):
        return blank_photo_status()
    merged = blank_photo_status()
    merged.update({k: status.get(k, merged[k]) for k in merged})
    if merged['state'] not in (STATE_NO_PHOTO, STATE_REQUESTED_UNCHECKED,
                               STATE_CHECK_REQUESTED, STATE_CHECKED):
        return blank_photo_status()
    return merged


def photo_block_reason(receipt):
    """None when approval/export may proceed; else the photo reason.

    Only a current ``detected`` geometry plus the normal fresh-approval
    machinery passes. Every other photo-bearing state refuses with the
    photo reason. The no-photo legacy path is unchanged.
    """
    if receipt.get('status') == 'failed':
        return None
    status = photo_status_of(receipt)
    if status['state'] == STATE_NO_PHOTO:
        return None
    if (status['state'] == STATE_CHECKED and status['label'] == 'detected'
            and status['revision'] == _current_revision(receipt)):
        return None
    if status['state'] in BLOCKING_STATES:
        detail = status['reason'] or status['state']
    elif status['state'] == STATE_CHECKED:
        detail = '%s: %s' % (status['label'] or 'unknown', status['reason'] or 'photo check did not pass')
    else:
        detail = status['state']
    return 'Photo blocks approval and export (%s); remove the photo or check a better one' % detail


def sanitized_summary(status):
    """Public photo summary: label, reason, policy, actor, time only."""
    return {'label': status.get('label'), 'reason': status.get('reason', ''),
            'policy_version': status.get('policy_version', PHOTO_POLICY_VERSION),
            'actor': status.get('actor', ''), 'time': status.get('checked_at', '')}


def apply_photo_event(receipt, *, event, actor, status):
    """Bump the shared pack revision for a photo event, clearing approval.

    Text source truth is preserved: ``human_draft`` post/email/claims are
    untouched and the history entry keeps the existing draft/check
    alongside the ``photo_event`` discriminator. Superseded entries are
    never mutated here; a new entry is appended.
    """
    if event not in (PHOTO_EVENT_CHECKED, PHOTO_EVENT_REMOVED):
        raise ValueError('Unknown photo event')
    revised = copy.deepcopy(receipt)
    previous = _current_revision(revised)
    now = timestamp()
    status = dict(status)
    status['revision'] = previous + 1
    status['actor'] = actor
    status['checked_at'] = now
    history = list(revised.get('revision_history') or [])
    history.append({'revision': previous,
                    'draft': _current_draft(revised),
                    'check': copy.deepcopy(_current_check(revised)),
                    'approval_state': revised.get('approval_state'),
                    'approvals': copy.deepcopy(list(revised.get('approvals') or [])),
                    'approved_revision': revised.get('approved_revision'),
                    'checker_profile': revised.get('checker_profile'),
                    'checker_policies': copy.deepcopy(revised.get('checker_policies')),
                    'blocked_claims': copy.deepcopy(revised.get('blocked_claims')),
                    'stage_bindings': copy.deepcopy(revised.get('stage_bindings')),
                    'memory_used': copy.deepcopy(revised.get('memory_used')),
                    'photo_event': event,
                    'photo_status': copy.deepcopy(status),
                    'revised_by': actor,
                    'revised_at': now,
                    'superseded_by': previous + 1, 'outcome': 'superseded_by_photo_event'})
    revised['revision'] = previous + 1
    revised['photo_status'] = status
    revised['revision_history'] = history
    revised['approvals'] = []
    revised['approved_revision'] = None
    revised['approval_state'] = 'pending_approval'
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': event, 'agent': 'human',
                   'profile': actor or 'human',
                   'action': 'Photo event %s at revision %d' % (event, previous + 1),
                   'timestamp': now, 'revision': previous + 1, 'revised_by': actor,
                   'photo': sanitized_summary(status)})
    revised.setdefault('audit', {})['event_log'] = events
    return revised


def attach_verdict(receipt, *, label, reason, actor):
    """Attach a final verdict to the current revision without bumping."""
    revised = copy.deepcopy(receipt)
    now = timestamp()
    status = photo_status_of(revised)
    status.update({'state': STATE_CHECKED, 'label': label, 'reason': reason,
                   'policy_version': PHOTO_POLICY_VERSION,
                   'revision': _current_revision(revised),
                   'actor': actor, 'checked_at': now})
    revised['photo_status'] = status
    transport = dict(revised.get('photo_transport') or {})
    transport.update({'attempts': int(transport.get('attempts', 0)) + 1,
                      'last_handling': 'segmented' if label else 'delivery_failed',
                      'note': ('Photo bytes were sent to the segmentation provider for this check; '
                               'text-model usage above is unchanged and covers text models only.')})
    revised['photo_transport'] = transport
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': PHOTO_EVENT_CHECKED, 'agent': 'human',
                   'profile': actor or 'human',
                   'action': 'Photo verdict %s at revision %d' % (label or 'unknown', _current_revision(revised)),
                   'timestamp': now, 'revision': _current_revision(revised),
                   'photo': sanitized_summary(status)})
    revised.setdefault('audit', {})['event_log'] = events
    return revised


def record_unattempted_transport(receipt, *, handling, note):
    """Note a photo attempt that sent nothing, separately from text usage."""
    revised = copy.deepcopy(receipt)
    transport = dict(revised.get('photo_transport') or {})
    transport.update({'attempts': int(transport.get('attempts', 0)),
                      'last_handling': handling, 'note': note})
    revised['photo_transport'] = transport
    return revised
