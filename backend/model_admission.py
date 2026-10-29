"""Disjoint durable admission for bounded Standard model calls.

Global Postgres budget with an explicit zero default, kept in integer
USD micros. Each bounded Standard muse-spark-1.3 call reserves one full
fixed planning reservation of 4 USD (4000000 micros) before the caller
may send. This is a local planning reservation only, never an external
provider hard cap. There is no public refill endpoint and no secret in
this module; a private operator grant is future separate work.

Only a committed reservation authorizes the caller to send: the budget
row lock, the full debit, and the ledger insert commit in one
transaction before is_owner true is returned. The budget never goes
negative (application check plus a database constraint). On commit
uncertainty the caller must fail closed and must not send; a later
replay with the same identity returns the persisted row with is_owner
false when the reservation committed.

Per-call bounds validated here: exact model muse-spark-1.3,
max_completion_tokens 2048, n 1, serialized request at most 32 KiB.
Exact Meta HTTPS origin and path plus no redirects and no retries are
enforced by the later transport integration, not here.

Ledger identity is the durable unique triple (run_id, stage,
attempt_id) with a separate request digest. A duplicate arrival with
the same identity and digest replays the persisted row with is_owner
false and never permits a resend, even while still admitted (crash or
restart). A duplicate identity with a different digest is refused. A
terminal, failed, crashed, or ambiguous attempt is never automatically
refunded or retried. Finalization attaches a sanitized outcome code and
numeric usage only; it always returns is_owner false and can never move
an attempt back to send authorization.

Prompts, raw responses, provider tokens, and secret values are never
written to the ledger and never echoed in error text. There is no FK to
runs: sync runs and Campaign execute model work before their run row
commits, while async runs commit before a worker; this module never
locks run rows, so no lock order cycle exists. No HTTP and no
credential access in this module.
"""
import hashlib
import re
from typing import TypedDict
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

MODEL = 'muse-spark-1.3'
MAX_COMPLETION_TOKENS = 2048
N = 1
MAX_BODY_BYTES = 32 * 1024
RESERVATION_USD_MICROS = 4_000_000
BUDGET_ID = 'global'

TERMINAL_STATUSES = ('succeeded', 'failed_terminal', 'ambiguous_terminal')
_MAX_IDENTITY_LEN = 128
_MAX_USAGE = 10_000_000
_OUTCOME_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}$')
_DIGEST_RE = re.compile(r'^[0-9a-f]{64}$')


class ModelCallRow(TypedDict):
    id: str
    run_id: str
    stage: str
    attempt_id: str
    request_digest: str
    model: str
    status: str
    outcome: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    reservation_micros: int
    is_owner: bool


class AdmissionDenied(ValueError):
    """Refused before or without send authorization; caller must not send."""

    def __init__(self, reason: str):
        super().__init__('Model admission denied: ' + reason)
        self.reason = reason


class AdmissionConflict(ValueError):
    """A different request already holds this attempt identity."""

    def __init__(self, reason: str):
        super().__init__('Model admission conflict: ' + reason)
        self.reason = reason


def digest_request_bytes(data: bytes) -> str:
    """Return the sha256 hex digest of canonical serialized request bytes.

    Pure helper with no I/O. Enforces the byte bound without persisting
    or echoing the bytes themselves.
    """
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_BODY_BYTES:
        raise AdmissionDenied('request size bound exceeded')
    return hashlib.sha256(bytes(data)).hexdigest()


def _row_to_call(row, *, is_owner: bool) -> ModelCallRow:
    return {'id': row['id'], 'run_id': row['run_id'], 'stage': row['stage'],
            'attempt_id': row['attempt_id'], 'request_digest': row['request_digest'],
            'model': row['model'], 'status': row['status'], 'outcome': row['outcome'],
            'prompt_tokens': row['prompt_tokens'], 'completion_tokens': row['completion_tokens'],
            'total_tokens': row['total_tokens'],
            'reservation_micros': row['reservation_micros'], 'is_owner': is_owner}


def _check_identity(value) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= _MAX_IDENTITY_LEN
            and value.strip() != '')


def _check_digest(value) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    if _DIGEST_RE.match(lowered) is None:
        return None
    return lowered


def reserve_model_call(db, *, run_id, stage, attempt_id, request_digest,
                       model, max_completion_tokens, n, request_bytes_len) -> ModelCallRow:
    """Reserve one fixed planning reservation, or replay the persisted row.

    Validates the exact Standard model and per-call bounds before any
    debit. On first arrival the budget lock, full debit, and ledger
    insert commit in one transaction before is_owner true is returned;
    only that committed owner may send. A duplicate same identity and
    digest returns the persisted row with is_owner false and never
    permits a resend. A duplicate identity with a different digest is
    refused. Any exception means no authorization: the caller must fail
    closed and must not send.
    """
    if not (_check_identity(run_id) and _check_identity(stage) and _check_identity(attempt_id)):
        raise AdmissionDenied('invalid run identity')
    digest = _check_digest(request_digest)
    if digest is None:
        raise AdmissionDenied('invalid request digest')
    if model != MODEL:
        raise AdmissionDenied('model mismatch')
    if isinstance(max_completion_tokens, bool) or max_completion_tokens != MAX_COMPLETION_TOKENS:
        raise AdmissionDenied('output token bound mismatch')
    if isinstance(n, bool) or n != N:
        raise AdmissionDenied('n bound mismatch')
    if (isinstance(request_bytes_len, bool) or not isinstance(request_bytes_len, int)
            or request_bytes_len < 0 or request_bytes_len > MAX_BODY_BYTES):
        raise AdmissionDenied('request size bound exceeded')
    key = {'run': run_id, 'stage': stage, 'attempt': attempt_id}
    try:
        with db.begin() as connection:
            existing = connection.execute(
                text('SELECT * FROM model_calls WHERE run_id=:run AND stage=:stage '
                     'AND attempt_id=:attempt FOR UPDATE'),
                key).mappings().first()
            if existing is not None:
                if (existing['request_digest'] or '').lower() != digest:
                    raise AdmissionConflict('a different request already holds this attempt identity')
                return _row_to_call(existing, is_owner=False)
            budget = connection.execute(
                text("SELECT remaining_micros FROM model_budget WHERE id='global' FOR UPDATE")
            ).scalar()
            if budget is None:
                raise AdmissionDenied('model budget unavailable')
            # Lock-free re-read after waiting on the budget lock: a
            # concurrent same-key arrival may have committed meanwhile.
            # Returning here spends nothing.
            again = connection.execute(
                text('SELECT * FROM model_calls WHERE run_id=:run AND stage=:stage '
                     'AND attempt_id=:attempt'),
                key).mappings().first()
            if again is not None:
                if (again['request_digest'] or '').lower() != digest:
                    raise AdmissionConflict('a different request already holds this attempt identity')
                return _row_to_call(again, is_owner=False)
            if budget < RESERVATION_USD_MICROS:
                raise AdmissionDenied('model budget exhausted')
            debited = connection.execute(
                text('UPDATE model_budget SET remaining_micros=remaining_micros-:res,'
                     'updated_at=now() WHERE id=\'global\' AND remaining_micros>=:res'),
                {'res': RESERVATION_USD_MICROS})
            if debited.rowcount != 1:
                raise AdmissionDenied('model budget exhausted')
            call_id = 'mc_' + uuid4().hex
            connection.execute(
                text('INSERT INTO model_calls(id,run_id,stage,attempt_id,request_digest,model,'
                     'status,reservation_micros) VALUES (:id,:run,:stage,:attempt,:digest,'
                     ':model,\'admitted\',:res)'),
                {'id': call_id, 'run': run_id, 'stage': stage, 'attempt': attempt_id,
                 'digest': digest, 'model': MODEL, 'res': RESERVATION_USD_MICROS})
            return {'id': call_id, 'run_id': run_id, 'stage': stage, 'attempt_id': attempt_id,
                    'request_digest': digest, 'model': MODEL, 'status': 'admitted',
                    'outcome': None, 'prompt_tokens': None, 'completion_tokens': None,
                    'total_tokens': None, 'reservation_micros': RESERVATION_USD_MICROS,
                    'is_owner': True}
    except IntegrityError:
        pass
    with db.begin() as connection:
        existing = connection.execute(
            text('SELECT * FROM model_calls WHERE run_id=:run AND stage=:stage '
                 'AND attempt_id=:attempt'),
            key).mappings().first()
        if existing is None:
            raise AdmissionConflict('a concurrent model operation holds this identity')
        if (existing['request_digest'] or '').lower() != digest:
            raise AdmissionConflict('a different request already holds this attempt identity')
        return _row_to_call(existing, is_owner=False)


def finalize_model_call(db, call_id, *, status, outcome=None,
                        prompt_tokens=None, completion_tokens=None,
                        total_tokens=None) -> ModelCallRow:
    """Attach a sanitized terminal outcome and numeric usage exactly once.

    Never refunds, never retries, and never returns send authorization:
    is_owner is always false. An already-terminal row replays unchanged.
    """
    if not isinstance(call_id, str) or not _check_identity(call_id):
        raise AdmissionDenied('unknown model operation')
    if status not in TERMINAL_STATUSES:
        raise AdmissionDenied('invalid terminal status')
    if outcome is None or outcome == '':
        clean_outcome = None
    elif not isinstance(outcome, str) or _OUTCOME_RE.match(outcome) is None:
        raise AdmissionDenied('invalid outcome')
    else:
        clean_outcome = outcome
    for value in (prompt_tokens, completion_tokens, total_tokens):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                  or value < 0 or value > _MAX_USAGE):
            raise AdmissionDenied('invalid usage')
    with db.begin() as connection:
        row = connection.execute(
            text('SELECT * FROM model_calls WHERE id=:id FOR UPDATE'),
            {'id': call_id}).mappings().first()
        if row is None:
            raise AdmissionDenied('unknown model operation')
        if row['status'] != 'admitted':
            return _row_to_call(row, is_owner=False)
        connection.execute(
            text('UPDATE model_calls SET status=:status,outcome=:outcome,'
                 'prompt_tokens=:pt,completion_tokens=:ct,total_tokens=:tt,'
                 'updated_at=now() WHERE id=:id AND status=\'admitted\''),
            {'status': status, 'outcome': clean_outcome, 'pt': prompt_tokens,
             'ct': completion_tokens, 'tt': total_tokens, 'id': call_id})
        updated = connection.execute(
            text('SELECT * FROM model_calls WHERE id=:id'),
            {'id': call_id}).mappings().first()
        return _row_to_call(updated, is_owner=False)


def budget_remaining_micros(db) -> int:
    """Read the global planning balance without locking or spending."""
    with db.begin() as connection:
        value = connection.execute(
            text("SELECT remaining_micros FROM model_budget WHERE id='global'")).scalar()
    if value is None:
        raise AdmissionDenied('model budget unavailable')
    return int(value)


def get_call_by_identity(db, run_id, stage, attempt_id) -> ModelCallRow | None:
    """Fetch one ledger row by identity without spending or authorizing."""
    with db.begin() as connection:
        row = connection.execute(
            text('SELECT * FROM model_calls WHERE run_id=:run AND stage=:stage '
                 'AND attempt_id=:attempt'),
            {'run': run_id, 'stage': stage, 'attempt': attempt_id}).mappings().first()
    if row is None:
        return None
    return _row_to_call(row, is_owner=False)
