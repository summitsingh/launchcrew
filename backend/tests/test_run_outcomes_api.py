"""Owner-reported outcome loop API on real Postgres.

Slice 6 vertical slice after an approved export. Deterministic pipeline
only, no model calls, no provider calls, no live measurement claims.
Every test uses synthetic owner input. Outcomes are immutable
self-reports with provenance self_reported, never provider-measured,
with no ROI, auto-post, or seeded rows.
"""
import base64
import copy
import io
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend import auth, store
from launchcrew import run

ACTOR_ONE = 'google:outcome-user-one'
ACTOR_TWO = 'google:outcome-user-two'
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'

FORBIDDEN_TOKENS = ('measured', 'provider', 'roi', 'return on',
                    'auto-post', 'auto_post', 'live measurement')


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


@pytest.fixture(autouse=True)
def no_model_key(monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)


def _sign_in(client, monkeypatch, actor):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    response = Response()
    auth.save_session({'actor': actor}, response)
    opaque = response.headers['set-cookie'].split(';')[0].split('=', 1)[1]
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque)
    return opaque


def _new_run(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _current_revision(client, run_id):
    return client.get(f'/api/runs/{run_id}').json().get('revision', 0)


def _approve_export(client, run_id):
    revision = _current_revision(client, run_id)
    approved = client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': revision})
    assert approved.status_code == 200, approved.text
    exported = client.post(f'/api/runs/{run_id}/export', json={'expected_revision': revision})
    assert exported.status_code == 200, exported.text
    return exported.json()


def _outcome_payload(**extra):
    payload = {'channel': 'x', 'posted_date': '2026-06-01',
               'likes': 10, 'comments': 2, 'clicks': 5, 'sales': 1,
               'note': 'owner note for the day'}
    payload.update(extra)
    return payload


def _log(client, run_id, **extra):
    response = client.post(f'/api/runs/{run_id}/outcomes', json=_outcome_payload(**extra))
    assert response.status_code == 201, response.text
    return response.json()


def _png_data_uri():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (32, 16), (200, 30, 30)).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def _assert_no_workspace(obj):
    if isinstance(obj, dict):
        assert 'workspace_id' not in obj
        for value in obj.values():
            _assert_no_workspace(value)
    elif isinstance(obj, list):
        for value in obj:
            _assert_no_workspace(value)


def _assert_no_forbidden(serialized):
    lowered = serialized.lower()
    for token in FORBIDDEN_TOKENS:
        assert token not in lowered, token


def test_create_and_read_owner_self_report(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    assert client.get(f'/api/runs/{run_id}/outcomes').json() == []
    _approve_export(client, run_id)
    saved = _log(client, run_id)
    assert saved['id'].startswith('out_')
    assert saved['run_id'] == run_id
    assert saved['export_revision'] == 0
    assert saved['channel'] == 'x'
    assert saved['posted_date'] == '2026-06-01'
    assert (saved['likes'], saved['comments'], saved['clicks'], saved['sales']) == (10, 2, 5, 1)
    assert saved['note'] == 'owner note for the day'
    assert saved['provenance'] == 'self_reported'
    assert saved['actor'] == ACTOR_ONE
    assert saved['created_at']
    _assert_no_workspace(saved)
    _assert_no_forbidden(json.dumps(saved))
    listed = client.get(f'/api/runs/{run_id}/outcomes').json()
    assert listed == [saved]
    _assert_no_workspace(listed)
    reread = client.get(f'/api/runs/{run_id}/outcomes').json()
    assert reread[0]['likes'] == 10 and reread[0]['provenance'] == 'self_reported'
    with store.connect() as db:
        actions = [row[0] for row in db.execute(
            text('SELECT action FROM audit WHERE run_id=:id ORDER BY id'), {'id': run_id})]
    assert 'outcome_logged' in actions


def test_two_user_denial_on_create_and_read(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    _approve_export(client, run_id)
    saved = _log(client, run_id)
    _sign_in(client, monkeypatch, ACTOR_TWO)
    assert client.get(f'/api/runs/{run_id}/outcomes').status_code == 404
    denied = client.post(f'/api/runs/{run_id}/outcomes', json=_outcome_payload())
    assert denied.status_code == 404
    own_id = _new_run(client)['run_id']
    _approve_export(client, own_id)
    own = _log(client, own_id, channel='email', note='second owner note')
    assert own['id'] != saved['id']
    assert [row['id'] for row in client.get(f'/api/runs/{own_id}/outcomes').json()] == [own['id']]
    _sign_in(client, monkeypatch, ACTOR_ONE)
    assert [row['id'] for row in client.get(f'/api/runs/{run_id}/outcomes').json()] == [saved['id']]
    assert client.get(f'/api/runs/{own_id}/outcomes').status_code == 404


def test_anonymous_demo_placeholder_write_and_read_denied(client, monkeypatch):
    run_id = _new_run(client)['run_id']
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    assert client.post(f'/api/runs/{run_id}/export', json={}).status_code == 200
    denied = client.post(f'/api/runs/{run_id}/outcomes', json=_outcome_payload())
    assert denied.status_code == 401
    assert 'Sign in required' in denied.json()['detail']
    read_denied = client.get(f'/api/runs/{run_id}/outcomes')
    assert read_denied.status_code == 401
    assert 'Sign in required' in read_denied.json()['detail']
    with store.connect() as db:
        assert db.execute(text('SELECT count(*) FROM run_outcomes WHERE run_id=:id'),
                          {'id': run_id}).scalar() == 0
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    client.cookies.clear()
    assert client.post(f'/api/runs/{run_id}/outcomes', json=_outcome_payload()).status_code == 401
    assert client.get(f'/api/runs/{run_id}/outcomes').status_code == 401


def test_anonymous_read_denied_without_existence_leak(client, monkeypatch):
    run_id = _new_run(client)['run_id']
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    assert client.post(f'/api/runs/{run_id}/export', json={}).status_code == 200
    existing = client.get(f'/api/runs/{run_id}/outcomes')
    missing = client.get('/api/runs/does-not-exist/outcomes')
    assert existing.status_code == 401
    assert missing.status_code == 401
    assert existing.json() == missing.json()
    assert 'Sign in required' in existing.json()['detail']


def test_pending_refused(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    refused = client.post(f'/api/runs/{run_id}/outcomes', json=_outcome_payload())
    assert refused.status_code == 409
    assert client.get(f'/api/runs/{run_id}/outcomes').json() == []


def test_failed_refused(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    with patch('launchcrew.run.make_draft', side_effect=RuntimeError('synthetic failure')):
        response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201
    assert response.json()['status'] == 'failed'
    run_id = response.json()['run_id']
    refused = client.post(f'/api/runs/{run_id}/outcomes', json=_outcome_payload())
    assert refused.status_code == 422
    assert client.get(f'/api/runs/{run_id}/outcomes').json() == []


def test_unexported_approved_refused_then_export_allows(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    assert client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': 0}).status_code == 200
    refused = client.post(f'/api/runs/{run_id}/outcomes', json=_outcome_payload())
    assert refused.status_code == 409
    assert 'export' in refused.json()['detail'].lower()
    assert client.post(f'/api/runs/{run_id}/export', json={'expected_revision': 0}).status_code == 200
    assert _log(client, run_id)['export_revision'] == 0


def test_stale_edited_blocks_new_but_preserves_history(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    _approve_export(client, run_id)
    first = _log(client, run_id, note='first owner note')
    assert first['export_revision'] == 0
    edit = {'post': 'Vegan leather wallet. Designed in Texas.',
            'email': 'For Austin commuters. $49.', 'base_revision': 0}
    assert client.post(f'/api/runs/{run_id}/revise', json=edit).status_code == 200
    assert _current_revision(client, run_id) == 1
    blocked = client.post(f'/api/runs/{run_id}/outcomes', json=_outcome_payload(note='second attempt'))
    assert blocked.status_code == 409
    history = client.get(f'/api/runs/{run_id}/outcomes').json()
    assert [row['id'] for row in history] == [first['id']]
    assert history[0]['export_revision'] == 0
    assert history[0]['note'] == 'first owner note'
    _approve_export(client, run_id)
    second = _log(client, run_id, note='second owner note')
    assert second['export_revision'] == 1
    both = client.get(f'/api/runs/{run_id}/outcomes').json()
    assert [row['export_revision'] for row in both] == [0, 1]
    assert [row['note'] for row in both] == ['first owner note', 'second owner note']


def test_photo_blocked_refused(client, monkeypatch):
    monkeypatch.delenv('LAUNCHCREW_PHOTO_SAM_ENABLED', raising=False)
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    with patch('backend.sam.urlopen', side_effect=AssertionError('zero HTTP expected')):
        checked = client.post(f'/api/runs/{run_id}/photo-check',
                              json={'image_data_uri': _png_data_uri(), 'expected_revision': 0})
    assert checked.status_code == 200
    refused = client.post(f'/api/runs/{run_id}/outcomes', json=_outcome_payload())
    assert refused.status_code in (409, 422)
    assert client.get(f'/api/runs/{run_id}/outcomes').json() == []


def test_tampered_photo_status_blocks_even_exported(client, monkeypatch, test_engine):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    _approve_export(client, run_id)
    assert _log(client, run_id)['export_revision'] == 0
    with test_engine.begin() as connection:
        row = connection.execute(text('SELECT receipt FROM runs WHERE id=:id'),
                                 {'id': run_id}).fetchone()
        stored = copy.deepcopy(dict(row[0]))
        stored['photo_status'] = {'state': 'requested_unchecked', 'label': None,
                                  'reason': 'not_run: SAM not configured, photo unchecked',
                                  'policy_version': 'photo-geometry/v1',
                                  'revision': 0, 'actor': ACTOR_ONE, 'checked_at': ''}
        connection.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'),
                           {'receipt': json.dumps(stored), 'id': run_id})
    refused = client.post(f'/api/runs/{run_id}/outcomes', json=_outcome_payload(note='photo blocked attempt'))
    assert refused.status_code == 422
    assert 'Photo' in refused.json()['detail']
    history = client.get(f'/api/runs/{run_id}/outcomes').json()
    assert len(history) == 1 and history[0]['export_revision'] == 0


def test_validation_rejects_forged_and_bad_types(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    _approve_export(client, run_id)
    good = _outcome_payload()
    for forged in ({**good, 'workspace_id': ACTOR_ONE},
                   {**good, 'actor': 'mallory'},
                   {**good, 'provenance': 'self_reported', 'export_revision': 0},
                   {**good, 'run_id': run_id},
                   {**good, 'created_at': '2026-06-01T00:00:00Z'}):
        assert client.post(f'/api/runs/{run_id}/outcomes', json=forged).status_code == 422
    for bad_channel in ('social', 'X', 'LinkedIn', '', ' x', 'x ', 'tiktok', 'fb'):
        assert client.post(f'/api/runs/{run_id}/outcomes',
                           json=_outcome_payload(channel=bad_channel)).status_code == 422
    for bad_date in ('', '2026-1-1', '2026/06/01', '2026-13-01', '2026-02-30',
                     '2026-02-29', 'not-a-date', '2026-06-01T00:00:00'):
        assert client.post(f'/api/runs/{run_id}/outcomes',
                           json=_outcome_payload(posted_date=bad_date)).status_code == 422
    for field in ('likes', 'comments', 'clicks', 'sales'):
        for bad in (True, False, -1, 1000001, 1.5, '5', None):
            payload = _outcome_payload()
            payload[field] = bad
            assert client.post(f'/api/runs/{run_id}/outcomes', json=payload).status_code == 422, (field, bad)
    for bad_note in ('', '   ', 'x' * 501, 'line1\nline2', 'tab\there', 'nul\x00here'):
        assert client.post(f'/api/runs/{run_id}/outcomes',
                           json=_outcome_payload(note=bad_note)).status_code == 422
    assert client.post(f'/api/runs/{run_id}/outcomes', json={}).status_code == 422
    assert client.get(f'/api/runs/{run_id}/outcomes').json() == []
    assert _log(client, run_id)['note'] == 'owner note for the day'


def test_no_provider_measurement_or_roi_language(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    _approve_export(client, run_id)
    saved = _log(client, run_id)
    listed = client.get(f'/api/runs/{run_id}/outcomes').json()
    assert listed == [saved]
    _assert_no_forbidden(json.dumps(saved))
    _assert_no_forbidden(json.dumps(listed))
    assert saved['provenance'] == 'self_reported'
    assert set(saved) == {'id', 'run_id', 'export_revision', 'channel', 'posted_date',
                          'likes', 'comments', 'clicks', 'sales', 'note',
                          'provenance', 'actor', 'created_at'}


def _outcome_row(run_id, workspace_id, **extra):
    row = {'id': 'out_' + uuid4().hex, 'run': run_id, 'ws': workspace_id,
           'rev': 0, 'channel': 'email', 'posted': '2026-06-01',
           'likes': 1, 'comments': 1, 'clicks': 1, 'sales': 1,
           'note': 'owner note', 'prov': 'self_reported', 'actor': workspace_id}
    row.update(extra)
    return row


_OUTCOME_INSERT = ('INSERT INTO run_outcomes(id, run_id, workspace_id, export_revision, channel,'
                   ' posted_date, likes, comments, clicks, sales, note, provenance, actor)'
                   ' VALUES (:id, :run, :ws, :rev, :channel, CAST(:posted AS date),'
                   ' :likes, :comments, :clicks, :sales, :note, :prov, :actor)')


def test_migration_fk_and_bounds(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_one = _new_run(client)['run_id']
    _sign_in(client, monkeypatch, ACTOR_TWO)
    run_two = _new_run(client)['run_id']
    with store.connect() as db:
        defaults = db.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'run_outcomes' "
            "AND column_name = 'workspace_id'")).scalar()
    assert defaults is None
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            db.execute(text(_OUTCOME_INSERT), _outcome_row(run_one, ACTOR_TWO))
    with store.connect() as db:
        assert db.execute(text("SELECT count(*) FROM run_outcomes WHERE workspace_id=:ws"),
                          {'ws': ACTOR_TWO}).scalar() == 0
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            row = _outcome_row(run_one, ACTOR_ONE)
            db.execute(text('INSERT INTO run_outcomes(id, run_id, export_revision, channel, posted_date,'
                            ' likes, comments, clicks, sales, note, provenance, actor)'
                            ' VALUES (:id, :run, :rev, :channel, CAST(:posted AS date),'
                            ' :likes, :comments, :clicks, :sales, :note, :prov, :actor)'), row)
    cases = [({'likes': -1}, 'likes'), ({'likes': 1000001}, 'likes'),
             ({'comments': -1}, 'comments'), ({'comments': 1000001}, 'comments'),
             ({'clicks': -5}, 'clicks'), ({'clicks': 2000000}, 'clicks'),
             ({'sales': -1}, 'sales'), ({'sales': 1000001}, 'sales'),
             ({'channel': 'social'}, 'channel'), ({'channel': 'X'}, 'channel'),
             ({'prov': 'provider_measured'}, 'provenance'), ({'prov': 'verified'}, 'provenance'),
             ({'actor': 'demo_placeholder'}, 'actor'), ({'actor': '   '}, 'actor'),
             ({'note': ''}, 'note'), ({'note': '   '}, 'note'),
             ({'note': 'x' * 501}, 'note'), ({'note': 'line1\nline2'}, 'note'),
             ({'rev': -1}, 'revision')]
    for override, _label in cases:
        with pytest.raises(IntegrityError):
            with store.connect() as db:
                db.execute(text(_OUTCOME_INSERT), _outcome_row(run_one, ACTOR_ONE, **override))
    with store.connect() as db:
        assert db.execute(text('SELECT count(*) FROM run_outcomes WHERE run_id=:id'),
                          {'id': run_one}).scalar() == 0
    with store.connect() as db:
        low = _outcome_row(run_one, ACTOR_ONE, likes=0, comments=0, clicks=0, sales=0)
        db.execute(text(_OUTCOME_INSERT), low)
        high = _outcome_row(run_one, ACTOR_ONE, likes=1000000, comments=1000000,
                            clicks=1000000, sales=1000000, note='n' * 500)
        db.execute(text(_OUTCOME_INSERT), high)
        assert db.execute(text('SELECT count(*) FROM run_outcomes WHERE run_id=:id'),
                          {'id': run_one}).scalar() == 2
        assert db.execute(text('SELECT likes FROM run_outcomes WHERE id=:id'),
                          {'id': high['id']}).scalar() == 1000000
    _sign_in(client, monkeypatch, ACTOR_ONE)
    listed = client.get(f'/api/runs/{run_one}/outcomes').json()
    assert len(listed) == 2
    assert {row['likes'] for row in listed} == {0, 1000000}
    _sign_in(client, monkeypatch, ACTOR_TWO)
    assert client.get(f'/api/runs/{run_one}/outcomes').status_code == 404
    with store.connect() as db:
        db.execute(text('DELETE FROM run_outcomes WHERE run_id=:id'), {'id': run_one})
        db.execute(text('DELETE FROM run_outcomes WHERE run_id=:id'), {'id': run_two})
