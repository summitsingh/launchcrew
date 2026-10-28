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
        value = int(receipt.get('revision', 0) or 0)
    except (TypeError, ValueError):
        return 0
    return value if value >= 0 else 0


def snapshot_allowlist(receipt):
    scout = receipt.get('scout') or {}
    facts_used = scout.get('facts_used') if isinstance(scout, dict) else None
    if isinstance(facts_used, list) and facts_used:
        allowlist = [entry.get('claim') for entry in facts_used
                     if isinstance(entry, dict) and entry.get('verified')
                     and isinstance(entry.get('claim'), str) and entry['claim'].strip()]
        if allowlist:
            return allowlist
    return None


def snapshot_sources(receipt):
    scout = receipt.get('scout') or {}
    sources = scout.get('sources') if isinstance(scout, dict) else None
    if isinstance(sources, list) and all(isinstance(s, str) for s in sources) and sources:
        return list(sources)
    return ['demo_facts.json']


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
    if receipt.get('maker_draft_v2') is None or receipt.get('checker_v2') is None:
        return False, 'Run has no complete draft context to revise'
    if snapshot_allowlist(receipt) is None:
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
    check = current_check(receipt)
    if not isinstance(check, dict) or check.get('blocked_count', 1) != 0:
        return False
    if current_revision(receipt) > 0:
        return receipt.get('approved_revision') == current_revision(receipt)
    return True


def apply_revision(receipt, post, email, actor, base_revision):
    """Save a clean human revision; raise ValueError when rejected."""
    ok, reason = valid_revision_context(receipt)
    if not ok:
        raise ValueError(reason)
    if base_revision != current_revision(receipt):
        raise ValueError('Revision is stale; reload the latest draft before saving')
    check = recheck_text(post, email, receipt)
    if check['blocked_count']:
        raise NeedsRevision(check)
    revised = copy.deepcopy(receipt)
    previous = current_revision(revised)
    history = list(revised.get('revision_history') or [])
    if revised.get('approval_state') == 'approved_for_export' or revised.get('approvals'):
        history.append({'revision': previous,
                        'approvals': list(revised.get('approvals') or []),
                        'approved_revision': revised.get('approved_revision'),
                        'superseded_by': previous + 1, 'outcome': 'superseded_by_human_edit'})
    sentences = _sentences(post, email)
    revised['revision'] = previous + 1
    revised['human_draft'] = {'post': post, 'email': email, 'claims': sentences,
                              'revised_by': 'human', 'revision': previous + 1}
    revised['human_check'] = check
    revised['revision_history'] = history
    revised['approvals'] = []
    revised['approved_revision'] = None
    revised['approval_state'] = 'pending_approval'
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': 'human_revision', 'agent': 'human',
                   'profile': actor or 'human',
                   'action': 'Saved human revision %d; recheck blocked_count=%d' % (previous + 1, check['blocked_count']),
                   'timestamp': timestamp()})
    revised.setdefault('audit', {})['event_log'] = events
    return revised


def approve_current(receipt, actor, expected_revision=None):
    if receipt.get('status') == 'failed':
        raise ValueError('Approval requires a completed run')
    if receipt.get('approval_state') != 'pending_approval':
        raise ValueError('Run is not pending approval')
    if expected_revision is not None and int(expected_revision) != current_revision(receipt):
        raise ValueError('Approval is stale; the draft changed')
    ok, reason = valid_revision_context(receipt)
    if not ok:
        raise ValueError('Approval requires a completed run with draft context')
    check = current_check(receipt)
    if not isinstance(check, dict) or check.get('blocked_count', 1) != 0:
        raise ValueError('Approval requires a clean final check')
    revised = copy.deepcopy(receipt)
    revised['approvals'] = list(revised.get('approvals') or [])
    revised['approvals'].append({'approved_by': actor, 'action': 'approved_for_export',
                                 'timestamp': timestamp(), 'revision': current_revision(revised)})
    revised['approval_state'] = 'approved_for_export'
    revised['approved_revision'] = current_revision(revised)
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': 'approval', 'agent': 'human', 'profile': actor or 'human',
                   'action': 'Approved revision %d for export' % current_revision(revised),
                   'timestamp': timestamp()})
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
