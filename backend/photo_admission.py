"""Durable photo-check admission plus bounded paid transport.

One transaction admits at most one paid sequence per ``(run_id,
revision)`` BEFORE any HTTP: budget lock and decrement, ledger insert,
pack revision bump, and approval invalidation commit first. The Files
plus Responses sequence runs only after that commit, and only for the
single owner admitted here; every other same-key arrival replays the
committed ledger row with zero HTTP. Finalization rechecks the
operation and version under row lock, and a stale finalization lands
``failed_terminal`` in its own commit before the stale error raises.

Exact plan names are kept: :func:`admit_photo_check`,
:func:`finalize_photo_check`, :func:`run_photo_check`. The ``db``
argument is an SQLAlchemy Engine; each function opens its own short
transactions. ``actor`` and ``frame`` are keyword-only additions the
plan routes supply from server auth and validated input. No DB
transaction is ever held across HTTP.
"""
import hashlib
import json
import os
from typing import TypedDict
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend import sam, store
from backend.photo_review import (
    PHOTO_EVENT_CHECKED,
    STATE_CHECK_REQUESTED,
    apply_photo_event,
    attach_verdict,
)
from launchcrew import human_review
from launchcrew.photo_policy import (
    PHOTO_POLICY_VERSION,
    classify_photo_geometry,
    suggest_crop,
)


class SamCallRow(TypedDict):
    id: str
    run_id: str
    revision: int
    status: str
    label: str | None
    reason: str
    policy_version: str
    is_owner: bool


class AdmissionRejected(ValueError):
    """The check is refused before or without paid HTTP; maps to 422."""

    def __init__(self, reason: str):
        super().__init__('Photo check refused: ' + reason)
        self.reason = reason


class AdmissionStale(ValueError):
    """A valid version moved underneath the request; maps to 409."""

    def __init__(self, reason: str):
        super().__init__('Photo revision is stale: ' + reason)
        self.reason = reason


class AdmissionConflict(ValueError):
    """A parallel different-image admission holds the key; maps to 409."""

    def __init__(self, reason: str):
        super().__init__('Photo operation conflict: ' + reason)
        self.reason = reason


def _approved_digests():
    raw = os.environ.get('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', '')
    return {part.strip().lower() for part in raw.split(',') if part.strip()}


def set_budget_remaining(db, count):
    """Operator and test backfill for the global one-shot budget. No route uses this."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError('Budget count must be a non-negative integer')
    with db.begin() as connection:
        connection.execute(text("UPDATE sam_budget SET remaining_images=:n WHERE id='global'"), {'n': count})


def _row_to_call(row, *, is_owner: bool) -> SamCallRow:
    return {'id': row['id'], 'run_id': row['run_id'], 'revision': row['revision'],
            'status': row['status'], 'label': row['label'],
            'reason': row['reason'] or '', 'policy_version': row['policy_version'],
            'is_owner': is_owner}


def _locked_call(connection, run_id, revision):
    return connection.execute(
        text('SELECT * FROM sam_calls WHERE run_id=:run AND revision=:rev FOR UPDATE'),
        {'run': run_id, 'rev': revision}).mappings().first()


def _read_call(connection, run_id, revision):
    # Lock-free re-read for the post-run-lock check. The run row is
    # already held here, so taking a sam_calls lock would invert the
    # sam_calls-before-runs order used everywhere else.
    return connection.execute(
        text('SELECT * FROM sam_calls WHERE run_id=:run AND revision=:rev'),
        {'run': run_id, 'rev': revision}).mappings().first()


def admit_photo_check(db, run_id, revision, photo_sha256, expected_revision, *, actor='') -> SamCallRow:
    """Admit one paid sequence, or replay the existing ledger row.

    Ledger replay runs before any staleness check: a duplicate arrival
    for an admitted key returns the pending row, and a duplicate after
    terminal state returns the persisted summary, without new HTTP. The
    returned row names the single transport owner: only the arrival that
    inserted the ledger row gets ``is_owner`` true. A concurrent same-key
    arrival that waited on the run lock re-reads the committed row after
    acquiring the lock, so it replays pending instead of going stale.
    """
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise AdmissionRejected('revision must be an integer')
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise AdmissionRejected('expected_revision must be an integer')
    if revision != expected_revision:
        raise AdmissionRejected('revision does not match expected_revision')
    digest = (photo_sha256 or '').lower()
    if not digest:
        raise AdmissionRejected('photo digest is required')
    try:
        with db.begin() as connection:
            existing = _locked_call(connection, run_id, revision)
            if existing is not None:
                if (existing['photo_sha256'] or '').lower() != digest:
                    raise AdmissionConflict('a different photo already holds this revision')
                return _row_to_call(existing, is_owner=False)
            holder = connection.execute(
                text('SELECT receipt FROM runs WHERE id=:id FOR UPDATE'), {'id': run_id}).fetchone()
            if holder is None:
                raise AdmissionRejected('run not found')
            receipt = holder[0]
            ok, context_reason = human_review.valid_revision_context(receipt)
            if not ok:
                raise AdmissionRejected(context_reason)
            current = human_review.current_revision(receipt)
            if expected_revision != current:
                raise AdmissionStale('the draft changed; reload the latest revision')
            # A concurrent same-key arrival may have committed while this
            # transaction waited on the run lock. Re-read the ledger now
            # that the run row is held, before any staleness decision.
            existing = _read_call(connection, run_id, revision)
            if existing is not None:
                if (existing['photo_sha256'] or '').lower() != digest:
                    raise AdmissionConflict('a different photo already holds this revision')
                return _row_to_call(existing, is_owner=False)
            budget = connection.execute(
                text("SELECT remaining_images FROM sam_budget WHERE id='global' FOR UPDATE")).scalar()
            if budget is None or budget <= 0:
                raise AdmissionRejected('photo budget exhausted')
            if digest not in _approved_digests():
                raise AdmissionRejected('photo bytes are not operator-approved')
            call_id = 'sam_' + uuid4().hex
            connection.execute(text('UPDATE sam_budget SET remaining_images=remaining_images-1 WHERE id=\'global\''))
            connection.execute(
                text('INSERT INTO sam_calls(id,run_id,revision,photo_sha256,status,policy_version) '
                     'VALUES (:id,:run,:rev,:sha,\'admitted\',:policy)'),
                {'id': call_id, 'run': run_id, 'rev': revision, 'sha': digest,
                 'policy': PHOTO_POLICY_VERSION})
            inflight = {'state': STATE_CHECK_REQUESTED, 'label': None,
                        'reason': 'check_requested: segmentation in flight',
                        'policy_version': PHOTO_POLICY_VERSION,
                        'revision': current, 'actor': actor, 'checked_at': ''}
            revised = apply_photo_event(receipt, event=PHOTO_EVENT_CHECKED, actor=actor, status=inflight)
            connection.execute(
                text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id'),
                {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id})
            connection.execute(text('DELETE FROM approvals WHERE run_id=:id'), {'id': run_id})
            store.audit(connection, run_id, 'photo_check_requested', actor or 'demo_placeholder')
            return {'id': call_id, 'run_id': run_id, 'revision': revision,
                    'status': 'admitted', 'label': None,
                    'reason': 'check_requested: segmentation in flight',
                    'policy_version': PHOTO_POLICY_VERSION, 'is_owner': True}
    except IntegrityError:
        pass
    with db.begin() as connection:
        existing = connection.execute(
            text('SELECT * FROM sam_calls WHERE run_id=:run AND revision=:rev'),
            {'run': run_id, 'rev': revision}).mappings().first()
        if existing is None:
            raise AdmissionConflict('a concurrent photo operation holds this revision')
        if (existing['photo_sha256'] or '').lower() != digest:
            raise AdmissionConflict('a different photo already holds this revision')
        return _row_to_call(existing, is_owner=False)


def finalize_photo_check(db, call_id, verdict, expected_revision, *, actor='',
                         uploads=0, segmentations=0, segmented=False) -> SamCallRow:
    """Finalize an admitted call exactly once; never resend transport.

    A verdict whose label is not a definitive geometry outcome lands
    ``failed_terminal``. A revision that moved before finalization also
    lands ``failed_terminal`` with nothing attached to the receipt: the
    terminal state commits in its own transaction BEFORE the stale error
    raises, so the rollback of the failed finalization cannot resurrect
    ``admitted``. Lock order stays sam_calls-before-runs throughout.
    """
    label = verdict.get('label') if isinstance(verdict, dict) else None
    reason = verdict.get('reason', '') if isinstance(verdict, dict) else ''
    actor = (verdict.get('actor') or actor) if isinstance(verdict, dict) else actor
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise AdmissionRejected('expected_revision must be an integer')
    definitive = label in ('detected', 'not_detected', 'possible_clipping')
    status = 'succeeded' if definitive else 'failed_terminal'
    if label not in ('detected', 'not_detected', 'possible_clipping', 'unknown'):
        label, reason, status = 'unknown', reason or 'fix_photo', 'failed_terminal'
    stale_reason = None
    missing_run = False
    with db.begin() as connection:
        row = connection.execute(
            text('SELECT * FROM sam_calls WHERE id=:id FOR UPDATE'), {'id': call_id}).mappings().first()
        if row is None:
            raise AdmissionRejected('unknown photo operation')
        if row['status'] != 'admitted':
            return _row_to_call(row, is_owner=False)
        if expected_revision != row['revision']:
            stale_reason = 'the draft changed; reload the latest revision'
        else:
            holder = connection.execute(
                text('SELECT receipt FROM runs WHERE id=:id FOR UPDATE'), {'id': row['run_id']}).fetchone()
            if holder is None:
                missing_run = True
            elif human_review.current_revision(holder[0]) != row['revision'] + 1:
                stale_reason = 'the draft changed before the photo verdict landed'
            else:
                revised = attach_verdict(holder[0], label=label, reason=reason, actor=actor,
                                         uploads=uploads, segmentations=segmentations,
                                         segmented=segmented)
                connection.execute(
                    text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id'),
                    {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': row['run_id']})
                connection.execute(
                    text('UPDATE sam_calls SET status=:status,label=:label,reason=:reason,updated_at=now() WHERE id=:id'),
                    {'status': status, 'label': label, 'reason': reason, 'id': call_id})
                store.audit(connection, row['run_id'], 'photo_checked', actor or 'demo_placeholder')
                updated = connection.execute(
                    text('SELECT * FROM sam_calls WHERE id=:id'), {'id': call_id}).mappings().first()
                return _row_to_call(updated, is_owner=False)
    # The failed finalization must still leave a terminal ledger row:
    # mark it here, committed, before raising below.
    with db.begin() as connection:
        connection.execute(
            text("UPDATE sam_calls SET status='failed_terminal',label='unknown',"
                 'reason=:reason,updated_at=now() WHERE id=:id AND status=\'admitted\''),
            {'reason': ('run missing at finalization' if missing_run
                        else 'revision moved before finalization; nothing attached'),
             'id': call_id})
    if missing_run:
        raise AdmissionRejected('run not found')
    assert stale_reason is not None
    raise AdmissionStale(stale_reason)


def _transport_counts(error) -> tuple[int, int]:
    try:
        uploads = int(getattr(error, 'uploads', 0) or 0)
    except (TypeError, ValueError):
        uploads = 0
    try:
        segmentations = int(getattr(error, 'segmentations', 0) or 0)
    except (TypeError, ValueError):
        segmentations = 0
    return uploads, segmentations


def run_photo_check(db, run_id, raw_bytes, mime, revision, expected_revision, *, actor='',
                    frame=None):
    """Admit, transport once, and finalize. Returns (row, preview, receipt).

    Transport runs only for the single owner admitted here, and only
    outside any DB transaction. Replays (pending in-flight or terminal)
    return the persisted row with no preview and zero HTTP. The preview
    crop hint is volatile and never persisted.
    """
    digest = hashlib.sha256(raw_bytes).hexdigest()
    row = admit_photo_check(db, run_id, revision, digest, expected_revision, actor=actor)
    with db.begin() as connection:
        receipt = connection.execute(
            text('SELECT receipt FROM runs WHERE id=:id'), {'id': run_id}).fetchone()[0]
    if not row.get('is_owner', False) or row['status'] != 'admitted':
        return row, None, receipt
    try:
        records = sam.upload_and_segment(raw_bytes, mime)
    except sam.SamTransportError as error:
        uploads, segmentations = _transport_counts(error)
        verdict = {'label': 'unknown', 'reason': 'delivery_failed',
                   'policy_version': PHOTO_POLICY_VERSION, 'actor': actor,
                   'detail': str(error)[:120]}
        final = finalize_photo_check(db, row['id'], verdict, expected_revision, actor=actor,
                                     uploads=uploads, segmentations=segmentations,
                                     segmented=False)
        with db.begin() as connection:
            receipt = connection.execute(
                text('SELECT receipt FROM runs WHERE id=:id'), {'id': run_id}).fetchone()[0]
        return final, None, receipt
    verdict = classify_photo_geometry(records, frame)
    verdict = dict(verdict)
    verdict['actor'] = actor
    preview = None
    if verdict.get('label') == 'detected' and frame is not None and len(records) == 1:
        try:
            crop = suggest_crop(records[0]['box'], frame)
            preview = {'frame_w': frame[0], 'frame_h': frame[1], 'crop': crop, 'label': 'detected'}
        except ValueError:
            preview = None
    final = finalize_photo_check(db, row['id'], verdict, expected_revision, actor=actor,
                                 uploads=1, segmentations=1, segmented=True)
    with db.begin() as connection:
        receipt = connection.execute(
            text('SELECT receipt FROM runs WHERE id=:id'), {'id': run_id}).fetchone()[0]
    return final, preview, receipt
