"""Per-run launch-readiness aggregation over an already-loaded receipt.

Read-only: inspects a receipt dict and returns gate statuses. No DB,
no network, no mutations. Missing keys fail closed to blocked/stale,
never to ready.
"""

from backend.photo_review import photo_block_reason, photo_status_of
from launchcrew.human_review import binding_status, current_check, exportable


def _facts_gate(receipt):
    product = receipt.get('product_facts')
    if not isinstance(product, dict):
        return {'status': 'blocked', 'confirmed_count': 0,
                'reason': 'Approval binding requires product-facts provenance'}
    raw = product.get('confirmed_claims')
    if not isinstance(raw, list):
        return {'status': 'blocked', 'confirmed_count': 0,
                'reason': 'Confirmed claims must be a list'}
    count = sum(1 for c in raw if isinstance(c, str) and c.strip())
    if not count:
        return {'status': 'blocked', 'confirmed_count': 0,
                'reason': 'Run has no verified fact snapshot to recheck against'}
    return {'status': 'pass', 'confirmed_count': count, 'reason': None}


def _checker_gate(receipt):
    check = current_check(receipt)
    if not isinstance(check, dict):
        return {'status': 'blocked', 'verified_count': None,
                'blocked_count': None,
                'reason': 'Approval binding requires a Checker result'}
    blocked = check.get('blocked_count')
    verified = check.get('verified_count')
    if isinstance(blocked, bool) or not isinstance(blocked, int):
        return {'status': 'blocked', 'verified_count': None,
                'blocked_count': None,
                'reason': 'Run has no complete draft context to revise'}
    if blocked != 0:
        return {'status': 'blocked', 'verified_count': verified,
                'blocked_count': blocked,
                'reason': 'Approval requires a clean final check'}
    return {'status': 'pass', 'verified_count': verified,
            'blocked_count': blocked, 'reason': None}


def _approval_gate(receipt):
    bound, reason = binding_status(receipt)
    if bound:
        return {'status': 'current', 'bound': True, 'reason': reason}
    return {'status': 'stale', 'bound': False, 'reason': reason}


def _photo_gate(receipt):
    status = photo_status_of(receipt)
    state = status.get('state')
    reason = photo_block_reason(receipt)
    if reason is None:
        return {'status': 'pass', 'state': state,
                'label': status.get('label'),
                'reason': status.get('reason', '')}
    return {'status': 'blocked', 'state': state,
            'label': status.get('label'), 'reason': reason}


def _export_gate(receipt):
    ok = exportable(receipt)
    if ok:
        return {'status': 'pass', 'exportable': True, 'reason': None}
    return {'status': 'blocked', 'exportable': False,
            'reason': 'Export requires approval of the latest revision and a clean final check'}


def readiness_of(receipt):
    """Aggregate launch-readiness gates for one loaded receipt dict."""
    if not isinstance(receipt, dict):
        facts = {'status': 'blocked', 'confirmed_count': 0,
                 'reason': 'Receipt unavailable'}
        checker = {'status': 'blocked', 'verified_count': None,
                   'blocked_count': None, 'reason': 'Receipt unavailable'}
        approval = {'status': 'stale', 'bound': False,
                    'reason': 'Receipt unavailable'}
        photo = {'status': 'blocked', 'state': None, 'label': None,
                 'reason': 'Receipt unavailable'}
        export = {'status': 'blocked', 'exportable': False,
                  'reason': 'Export requires approval of the latest revision and a clean final check'}
        return {'facts': facts, 'checker': checker, 'approval': approval,
                'photo': photo, 'export': export, 'ready': False}
    facts = _facts_gate(receipt)
    checker = _checker_gate(receipt)
    approval = _approval_gate(receipt)
    photo = _photo_gate(receipt)
    export = _export_gate(receipt)
    ready = (facts['status'] == 'pass'
             and checker['status'] == 'pass'
             and approval['status'] == 'current'
             and photo['status'] == 'pass'
             and export['status'] == 'pass')
    return {'facts': facts, 'checker': checker, 'approval': approval,
            'photo': photo, 'export': export, 'ready': ready}
