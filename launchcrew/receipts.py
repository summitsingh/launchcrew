"""Receipt creation, local storage, and approval-gated pack export."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

REQUIRED_FIELDS = {'receipt_version', 'run_id', 'generated_at', 'brand', 'mode', 'idea',
                   'agents_used', 'scout', 'maker_draft_v1', 'checker_v1', 'maker_draft_v2',
                   'checker_v2', 'summary', 'approvals', 'approval_state',
                   'visual_verification', 'audit', 'model_usage'}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def create_receipt(run_id, idea, scout, draft_v1, checker_v1, draft_v2, checker_v2, event_log, model_usage, approve=False):
    if checker_v2['blocked_count']:
        raise ValueError('Final draft has blocked claims')
    now = timestamp()
    return {'receipt_version': '1.0', 'run_id': run_id, 'generated_at': now,
            'brand': 'LaunchCrew', 'mode': 'demo_no_submit', 'idea': idea,
            'agents_used': ['Scout', 'Maker', 'Checker', 'Maker', 'Checker'],
            'scout': scout, 'maker_draft_v1': draft_v1, 'checker_v1': checker_v1,
            'maker_draft_v2': draft_v2, 'checker_v2': checker_v2,
            'summary': {'total_claims_checked': checker_v1['verified_count'] + checker_v1['blocked_count'] + checker_v2['verified_count'],
                        'verified_count': checker_v1['verified_count'] + checker_v2['verified_count'],
                        'blocked_count': checker_v1['blocked_count'], 'revised': draft_v1 != draft_v2,
                        'submit_attempted': False, 'submit_completed': False},
            'approvals': [{'approved_by': 'demo_human', 'action': 'approved_for_export', 'timestamp': now}] if approve else [],
            'approval_state': 'approved_for_export' if approve else 'pending_approval',
            # SAM will plug in Nov 1 via direct api.meta.ai call, NOT via Muse CLI.
            'visual_verification': {'checked': False, 'method': 'not_run',
                                    'notes': 'SAM photo check is Nov 1 work, not in Oct 28-29 milestone'},
            'audit': {'event_log': event_log, 'duplicate_submit_prevented': True, 'stopped_reason': None},
            'model_usage': model_usage}


def save_receipt(receipt, path):
    if not REQUIRED_FIELDS <= receipt.keys():
        raise ValueError('Missing required receipt fields')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return path


def load_receipt(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def export_receipt(receipt, path):
    if receipt['approval_state'] != 'approved_for_export' or receipt['checker_v2']['blocked_count']:
        raise ValueError('Export requires approval and a clean final check')
    return save_receipt(copy.deepcopy(receipt), path)
