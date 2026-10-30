"""Receipt creation, local storage, and approval-gated pack export."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

REQUIRED_FIELDS = {'receipt_version', 'run_id', 'generated_at', 'brand', 'mode', 'idea',
                   'agents_used', 'scout', 'maker_draft_v1', 'checker_v1', 'maker_draft_v2',
                   'checker_v2', 'summary', 'approvals', 'approval_state',
                   'visual_verification', 'audit', 'model_usage'}

OPTIONAL_RECEIPT_FIELDS = frozenset({'readiness', 'voice_provenance'})


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def create_receipt(run_id, idea, scout, draft_v1, checker_v1, draft_v2, checker_v2, event_log, model_usage, approve=False, readiness=None, voice_provenance=None):
    """Create a pending completed receipt.

    The approve flag is accepted for compatibility but never creates an
    approval. Approval must happen after the final receipt contains
    product_facts, checker policies, stage bindings, and photo state,
    through the approve_current binding path. Historical unbound approvals
    stay nonexportable until a fresh human revision and approval.
    Readiness and voice provenance are optional schema fields preserved
    through serialization; they default to None until the pipeline
    computes them on the finalized receipt.
    """
    if checker_v2['blocked_count']:
        raise ValueError('Final draft has blocked claims')
    now = timestamp()
    return {'receipt_version': '1.0', 'run_id': run_id, 'generated_at': now,
            'status': 'completed', 'brand': 'LaunchCrew', 'mode': 'demo_no_submit', 'idea': idea,
            'agents_used': ['Scout', 'Maker', 'Checker', 'Maker', 'Checker'],
            'scout': scout, 'maker_draft_v1': draft_v1, 'checker_v1': checker_v1,
            'maker_draft_v2': draft_v2, 'checker_v2': checker_v2,
            'summary': {'total_claims_checked': checker_v1['verified_count'] + checker_v1['blocked_count'] + checker_v2['verified_count'],
                        'verified_count': checker_v1['verified_count'] + checker_v2['verified_count'],
                        'blocked_count': checker_v1['blocked_count'], 'revised': draft_v1 != draft_v2,
                        'submit_attempted': False, 'submit_completed': False},
            'approvals': [],
            'approval_state': 'pending_approval',
            'visual_verification': {'checked': False, 'method': 'not_run'},
            'audit': {'event_log': event_log, 'duplicate_submit_prevented': True, 'stopped_reason': None},
            'model_usage': model_usage,
            'readiness': copy.deepcopy(readiness) if readiness is not None else None,
            'voice_provenance': copy.deepcopy(voice_provenance) if voice_provenance is not None else None}


def save_receipt(receipt, path):
    # Optional readiness and voice_provenance are preserved verbatim when
    # present; they are never stripped or defaulted here. The full receipt
    # dict roundtrips through JSON, so load_receipt returns them unchanged.
    required = {'status', 'run_id', 'approval_state', 'summary', 'audit', 'error_type', 'completed_steps'} if receipt.get('status') == 'failed' else REQUIRED_FIELDS
    if not required <= receipt.keys():
        raise ValueError('Missing required receipt fields')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return path


def load_receipt(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def export_receipt(receipt, path):
    from .human_review import current_check, current_draft, current_revision, exportable
    if not exportable(receipt):
        raise ValueError('Export requires approval of the latest revision and a clean final check')
    payload = copy.deepcopy(receipt)
    payload['exported_draft'] = current_draft(receipt)
    payload['exported_revision'] = current_revision(receipt)
    # Keep original Maker drafts as evidence; the exported draft is explicit.
    _ = current_check(receipt)
    return save_receipt(payload, path)


def failed_receipt(run_id, events, step, error):
    # No input, model output, exception message, headers, or environment in failures.
    return {'receipt_version': '1.0', 'run_id': run_id, 'generated_at': timestamp(),
            'brand': 'LaunchCrew', 'mode': 'demo_no_submit', 'status': 'failed',
            'error_type': type(error).__name__, 'completed_steps': [e['step'] for e in events],
            'approval_state': 'pending_approval', 'approvals': [],
            'submit_attempted': False, 'submit_completed': False,
            'summary': {'submit_attempted': False, 'submit_completed': False},
            'audit': {'event_log': events, 'stopped_reason': step},
            'readiness': None, 'voice_provenance': None}


def pending_receipt(run_id, idea, stage_bindings=None, voice_profile=None):
    """Honest pending receipt for an accepted but unfinished run.

    Status is running, drafts and checks are absent, and no approval or
    export gate accepts it. It is evidence of accepted work, never of
    success, and a later completed or failed receipt replaces it. When a
    voice is selected, the pending receipt carries its id plus stable
    version and digest binding so later edits can invalidate the running
    run in the same workspace before finalization."""
    now = timestamp()
    pending = {'receipt_version': '1.0', 'run_id': run_id, 'generated_at': now,
               'status': 'running', 'brand': 'LaunchCrew', 'mode': 'demo_no_submit',
               'idea': idea, 'agents_used': ['Scout', 'Maker', 'Checker', 'Maker', 'Checker'],
               'scout': None, 'maker_draft_v1': None, 'checker_v1': None,
               'maker_draft_v2': None, 'checker_v2': None,
               'summary': {'submit_attempted': False, 'submit_completed': False},
               'approvals': [], 'approval_state': 'pending_approval',
               'visual_verification': {'checked': False, 'method': 'not_run'},
               'audit': {'event_log': [{'step': 'accepted', 'agent': 'LaunchCrew',
                                        'profile': 'LaunchCrew',
                                        'action': 'Run accepted; pipeline work has not completed',
                                        'timestamp': now}],
                         'duplicate_submit_prevented': True, 'stopped_reason': None},
               'model_usage': None,
               'stage_bindings': dict(stage_bindings or {}),
               'readiness': None, 'voice_provenance': None}
    if voice_profile is not None:
        pending['voice_profile'] = copy.deepcopy(voice_profile)
    return pending


def approve_receipt(receipt, approved_by, expected_revision=None):
    from .human_review import approve_current
    revised = approve_current(receipt, approved_by, expected_revision)
    receipt.clear()
    receipt.update(revised)
    return receipt
