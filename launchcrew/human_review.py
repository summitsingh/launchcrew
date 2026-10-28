"""Deterministic human revision recheck against the SAME run snapshot.

No model calls, no network, no trust in client claims. Rechecking uses only
the verified facts, blocked rules, and Checker policies recorded on the
receipt, so later profile or memory edits cannot rewrite past proof.

Semantics: an edit that fails rechecking is rejected with HTTP 422 and is
not stored. Only text that passes every deterministic claim check is saved
as a new human revision, and any saved change resets export approval.
"""
import copy
import re

from .receipts import timestamp


REVISION_EXPLAINER = (
    'Rechecking compares your edited post and email against the same '
    'verified facts, blocked rules, and Checker policies saved on this run. '
    'Unsupported text is rejected and not saved. Saved text clears the prior '
    'export approval until you approve the latest revision.'
)


class NeedsRevision(ValueError):
    def __init__(self, check):
        super().__init__('Edited text needs revision before it can be saved')
        self.check = check

_SENTENCE_SPLIT = re.compile(r'(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+')


def _sentences(post, email):
    combined = (post or '') + '\n' + (email or '')
    return [s.strip() for s in _SENTENCE_SPLIT.split(combined) if s.strip()]


def current_revision(receipt):
    try:
        raw = receipt.get('revision', 0)
        if isinstance(raw, bool):
            return 0
        value = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return value if value >= 0 else 0


def _entry_sourced(entry):
    sources = entry.get('sources')
    if isinstance(sources, list) and any(isinstance(s, str) and s.strip() for s in sources):
        return True
    evidence = entry.get('evidence')
    if isinstance(evidence, str) and evidence.strip():
        return True
    if isinstance(evidence, list) and any(isinstance(s, str) and s.strip() for s in evidence):
        return True
    return False


def snapshot_allowlist(receipt):
    scout = receipt.get('scout') or {}
    facts_used = scout.get('facts_used') if isinstance(scout, dict) else None
    if isinstance(facts_used, list) and facts_used:
        allowlist = [entry.get('claim') for entry in facts_used
                     if isinstance(entry, dict) and entry.get('verified') is True
                     and isinstance(entry.get('claim'), str) and entry['claim'].strip()
                     and _entry_sourced(entry)]
        if allowlist:
            return allowlist
    return None


def snapshot_sources(receipt):
    scout = receipt.get('scout') or {}
    sources = scout.get('sources') if isinstance(scout, dict) else None
    if isinstance(sources, list) and sources:
        cleaned = [s for s in sources if isinstance(s, str) and s.strip()]
        if cleaned and len(cleaned) == len(sources):
            return list(cleaned)
    return None


def snapshot_blocked(receipt):
    raw = receipt.get('blocked_claims')
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, str) and c.strip()]
    return []


def snapshot_policies(receipt):
    raw = receipt.get('checker_policies')
    if isinstance(raw, list):
        return sorted({str(p) for p in raw if isinstance(p, str)})
    profile = receipt.get('checker_profile', 'standard')
    return ['superlatives'] if profile == 'strict' else []


def snapshot_profile_name(receipt, stage):
    bindings = receipt.get('stage_bindings') or {}
    if isinstance(bindings, dict) and isinstance(bindings.get(stage), str):
        return bindings.get(stage)
    detail = (receipt.get('stage_agents') or {}).get(stage) or {}
    if isinstance(detail, dict) and isinstance(detail.get('name'), str):
        return detail.get('name')
    return None


def valid_revision_context(receipt):
    if not isinstance(receipt, dict):
        return False, 'Receipt unavailable'
    if receipt.get('status') == 'failed':
        return False, 'Failed runs cannot be edited into approved packs'
    if receipt.get('status') != 'completed':
        return False, 'Run has no complete draft context to revise'
    maker = receipt.get('maker_draft_v2')
    checker = receipt.get('checker_v2')
    if not isinstance(maker, dict) or not isinstance(maker.get('post'), str) or not isinstance(maker.get('email'), str):
        return False, 'Run has no complete draft context to revise'
    if not isinstance(checker, dict) or isinstance(checker.get('blocked_count'), bool) or not isinstance(checker.get('blocked_count'), int):
        return False, 'Run has no complete draft context to revise'
    if snapshot_allowlist(receipt) is None:
        return False, 'Run has no verified fact snapshot to recheck against'
    if snapshot_sources(receipt) is None:
        return False, 'Run has no verified fact snapshot to recheck against'
    return True, ''


def recheck_text(post, email, receipt):
    """Deterministically recheck post/email against the run snapshot."""
    from .run import check_pack
    ok, reason = valid_revision_context(receipt)
    if not ok:
        raise ValueError(reason)
    if not isinstance(post, str) or not post.strip() or len(post) > 2000:
        raise ValueError('Post must be 1 to 2000 characters')
    if not isinstance(email, str) or not email.strip() or len(email) > 2000:
        raise ValueError('Email must be 1 to 2000 characters')
    facts = {'approved_claims': snapshot_allowlist(receipt),
             'sources': snapshot_sources(receipt)}
    sentences = _sentences(post, email)
    if not sentences:
        raise ValueError('Edited text has no sentences to check')
    draft = {'claims': list(sentences), 'post': post, 'email': email}
    return check_pack(draft, facts, snapshot_blocked(receipt),
                      checker_profile=receipt.get('checker_profile', 'standard'),
                      checker_policies=snapshot_policies(receipt))


def current_draft(receipt):
    if current_revision(receipt) > 0 and isinstance(receipt.get('human_draft'), dict):
        human = receipt['human_draft']
        if isinstance(human.get('post'), str) and isinstance(human.get('email'), str):
            return {'post': human['post'], 'email': human['email'],
                    'claims': list(human.get('claims') or [])}
    maker = receipt.get('maker_draft_v2') or {}
    return {'post': maker.get('post'), 'email': maker.get('email'),
            'claims': list(maker.get('claims') or [])}


def current_check(receipt):
    if current_revision(receipt) > 0 and isinstance(receipt.get('human_check'), dict):
        return receipt['human_check']
    return receipt.get('checker_v2')


def exportable(receipt):
    if receipt.get('status') == 'failed':
        return False
    if receipt.get('approval_state') != 'approved_for_export':
        return False
    from backend.photo_review import photo_block_reason
    if photo_block_reason(receipt) is not None:
        return False
    check = current_check(receipt)
    if not isinstance(check, dict) or isinstance(check.get('blocked_count'), bool) or check.get('blocked_count', 1) != 0:
        return False
    if current_revision(receipt) > 0:
        approved = receipt.get('approved_revision')
        if isinstance(approved, bool) or not isinstance(approved, int):
            return False
        return approved == current_revision(receipt)
    return True


def _history_entry(receipt, previous, actor, now):
    return {'revision': previous,
            'draft': current_draft(receipt),
            'check': copy.deepcopy(current_check(receipt)),
            'approval_state': receipt.get('approval_state'),
            'approvals': copy.deepcopy(list(receipt.get('approvals') or [])),
            'approved_revision': receipt.get('approved_revision'),
            'checker_profile': receipt.get('checker_profile'),
            'checker_policies': copy.deepcopy(receipt.get('checker_policies')),
            'blocked_claims': copy.deepcopy(receipt.get('blocked_claims')),
            'stage_bindings': copy.deepcopy(receipt.get('stage_bindings')),
            'memory_used': copy.deepcopy(receipt.get('memory_used')),
            'revised_by': actor,
            'revised_at': now,
            'superseded_by': previous + 1, 'outcome': 'superseded_by_human_edit'}


def apply_revision(receipt, post, email, actor, base_revision):
    """Save a clean human revision; raise ValueError when rejected."""
    ok, reason = valid_revision_context(receipt)
    if not ok:
        raise ValueError(reason)
    if isinstance(base_revision, bool) or not isinstance(base_revision, int):
        raise ValueError('base_revision must be an integer')
    if base_revision != current_revision(receipt):
        raise ValueError('Revision is stale; reload the latest draft before saving')
    check = recheck_text(post, email, receipt)
    if check['blocked_count']:
        raise NeedsRevision(check)
    revised = copy.deepcopy(receipt)
    previous = current_revision(revised)
    now = timestamp()
    history = list(revised.get('revision_history') or [])
    history.append(_history_entry(revised, previous, actor, now))
    sentences = _sentences(post, email)
    revised['revision'] = previous + 1
    revised['human_draft'] = {'post': post, 'email': email, 'claims': sentences,
                              'revised_by': actor, 'revised_at': now, 'revision': previous + 1}
    revised['human_check'] = check
    revised['revision_history'] = history
    revised['approvals'] = []
    revised['approved_revision'] = None
    revised['approval_state'] = 'pending_approval'
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': 'human_revision', 'agent': 'human',
                   'profile': actor or 'human',
                   'action': 'Saved human revision %d; recheck blocked_count=%d' % (previous + 1, check['blocked_count']),
                   'timestamp': now, 'revision': previous + 1, 'revised_by': actor})
    revised.setdefault('audit', {})['event_log'] = events
    return revised


def approve_current(receipt, actor, expected_revision=None):
    if receipt.get('status') == 'failed':
        raise ValueError('Approval requires a completed run')
    if receipt.get('status') != 'completed':
        raise ValueError('Approval requires a completed run')
    if receipt.get('approval_state') != 'pending_approval':
        raise ValueError('Run is not pending approval')
    current = current_revision(receipt)
    if current > 0 and expected_revision is None:
        raise ValueError('Approval is stale; expected_revision is required for edited revisions')
    if expected_revision is not None:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError('expected_revision must be an integer')
        if int(expected_revision) != current:
            raise ValueError('Approval is stale; the draft changed')
    ok, reason = valid_revision_context(receipt)
    if not ok:
        raise ValueError('Approval requires a completed run with draft context')
    check = current_check(receipt)
    if not isinstance(check, dict) or isinstance(check.get('blocked_count'), bool) or check.get('blocked_count', 1) != 0:
        raise ValueError('Approval requires a clean final check')
    from backend.photo_review import photo_block_reason
    photo_reason = photo_block_reason(receipt)
    if photo_reason is not None:
        raise ValueError(photo_reason)
    revised = copy.deepcopy(receipt)
    now = timestamp()
    revised['approvals'] = list(revised.get('approvals') or [])
    revised['approvals'].append({'approved_by': actor, 'action': 'approved_for_export',
                                 'timestamp': now, 'revision': current_revision(revised)})
    revised['approval_state'] = 'approved_for_export'
    revised['approved_revision'] = current_revision(revised)
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': 'approval', 'agent': 'human', 'profile': actor or 'human',
                   'action': 'Approved revision %d for export' % current_revision(revised),
                   'timestamp': now, 'revision': current_revision(revised), 'approved_by': actor})
    revised.setdefault('audit', {})['event_log'] = events
    return revised


def record_export(receipt, actor):
    """Persist actual export revision/actor/time onto a receipt copy."""
    if not exportable(receipt):
        raise ValueError('Export requires approval of the latest revision and a clean final check')
    revised = copy.deepcopy(receipt)
    now = timestamp()
    rev = current_revision(revised)
    draft = current_draft(revised)
    revised['exported_draft'] = draft
    revised['exported_revision'] = rev
    history = list(revised.get('export_history') or [])
    history.append({'revision': rev, 'exported_by': actor, 'timestamp': now})
    revised['export_history'] = history
    revised['last_exported_by'] = actor
    revised['last_exported_at'] = now
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': 'export', 'agent': 'human', 'profile': actor or 'human',
                   'action': 'Exported revision %d for offline use' % rev,
                   'timestamp': now, 'revision': rev, 'exported_by': actor})
    revised.setdefault('audit', {})['event_log'] = events
    return revised


def export_view(receipt):
    if not exportable(receipt):
        raise ValueError('Export requires approval of the latest revision and a clean final check')
    draft = current_draft(receipt)
    view = copy.deepcopy(receipt)
    view['exported_draft'] = draft
    view['exported_revision'] = current_revision(receipt)
    return view
