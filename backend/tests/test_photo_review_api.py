"""Run-bound photo API plus approval/export gating on real Postgres.

Uses only the existing ``test_engine`` and ``client`` fixtures; every
helper below is defined in this file. HTTP is mocked at the transport
seam only. Keyless tests assert zero provider HTTP.
"""
import base64
import hashlib
import io
import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from backend import store
from launchcrew import run


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


@pytest.fixture(autouse=True)
def keyless_sam(monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)
    monkeypatch.delenv('LAUNCHCREW_PHOTO_SAM_ENABLED', raising=False)


def _make_run(client):
    response = client.post('/api/runs', json={'idea': 'photo gate probe', 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    return response.json()['run_id']


def _png_bytes(width=32, height=16, color=(200, 30, 30)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), color).save(buffer, format='PNG')
    return buffer.getvalue()


def _data_uri(raw):
    return 'data:image/png;base64,' + base64.b64encode(raw).decode()


def _sse(*events):
    return io.BytesIO(b''.join(b'data: ' + json.dumps(event).encode() + b'\n\n' for event in events))


def _tag(object_id, box, mask):
    x1, y1, x2, y2, w, h = box
    mh, mw = mask
    return ('<0f>%d<|box;x1=%d;y1=%d;x2=%d;y2=%d;w=%d;h=%d|>'
            '<|mask;x=0;y=0;data=%d,%d,~e30=|>') % (object_id, x1, y1, x2, y2, w, h, mh, mw)


CLEAR_TAG = _tag(1, (4, 4, 20, 12, 32, 16), (9, 17))
EDGE_TAG = _tag(1, (0, 4, 20, 12, 32, 16), (9, 21))
FRAME_TAG = _tag(1, (4, 4, 40, 12, 32, 16), (9, 29))
MULTI_TAG = _tag(1, (4, 4, 20, 12, 32, 16), (9, 17)) + ',' + _tag(2, (1, 1, 10, 10, 32, 16), (10, 10))


def _stream_text(payload_text):
    return _sse({'type': 'response.output_text.delta', 'delta': payload_text},
                {'type': 'response.completed'})


def _empty_stream():
    return _sse({'type': 'response.completed'})


def _transport(payload, calls, stream=None):
    def send(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith('/files'):
            return io.BytesIO(b'{"id":"file-live","created_at":1700000000,"expires_at":1700003600}')
        return stream() if stream else _stream_text(payload)
    return send


def _grant(images):
    with store.connect() as db:
        db.execute(text("UPDATE sam_budget SET remaining_images=:n WHERE id='global'"), {'n': images})


def _no_photo_control(client):
    run_id = _make_run(client)
    assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 200
    assert client.post('/api/runs/%s/export' % run_id, json={}).status_code == 200


def _assert_clean(payload):
    text = json.dumps(payload)
    for secret in ('base64', 'file-live', 'file_id', 'photo_sha256', 'sha256', 'mask', '"box"', 'payload'):
        assert secret not in text, secret


def test_keyless_check_returns_not_run_with_zero_http(client):
    from backend import sam as sam_module
    run_id = _make_run(client)
    assert sam_module.photo_sam_operable() is False
    with patch('backend.sam.urlopen', side_effect=AssertionError('zero HTTP expected')):
        response = client.post('/api/runs/%s/photo-check' % run_id,
                               json={'image_data_uri': _data_uri(_png_bytes()), 'expected_revision': 0})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['check']['method'] == 'not_run'
    assert body['check']['label'] is None
    assert body['check']['photo_state'] == 'requested_unchecked'
    assert body['preview'] is None
    receipt = body['receipt']
    assert receipt['revision'] == 1
    assert receipt['photo_status']['state'] == 'requested_unchecked'
    assert receipt['photo_status']['revision'] == 1
    assert receipt['approvals'] == [] and receipt['approval_state'] == 'pending_approval'
    assert receipt['photo_transport']['last_handling'] == 'not_run'
    note = receipt['photo_transport']['note']
    assert 'validation server' in note
    assert 'not forwarded to any segmentation provider' in note
    assert 'not sent anywhere' not in note
    _assert_clean(receipt)


def test_unchecked_photo_blocks_approve_and_export(client):
    _no_photo_control(client)
    run_id = _make_run(client)
    with patch('backend.sam.urlopen', side_effect=AssertionError('zero HTTP expected')):
        check = client.post('/api/runs/%s/photo-check' % run_id,
                            json={'image_data_uri': _data_uri(_png_bytes()), 'expected_revision': 0})
    assert check.status_code == 200
    approve = client.post('/api/runs/%s/approve' % run_id, json={'expected_revision': 1})
    assert approve.status_code == 422
    assert 'Photo' in approve.json()['detail']
    export = client.post('/api/runs/%s/export' % run_id, json={'expected_revision': 1})
    assert export.status_code == 422
    assert 'Photo' in export.json()['detail']


def test_keyless_check_invalidates_prior_approval(client):
    run_id = _make_run(client)
    assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 200
    with patch('backend.sam.urlopen', side_effect=AssertionError('zero HTTP expected')):
        check = client.post('/api/runs/%s/photo-check' % run_id,
                            json={'image_data_uri': _data_uri(_png_bytes()), 'expected_revision': 0})
    assert check.status_code == 200
    reread = client.get('/api/runs/%s' % run_id).json()
    assert reread['approvals'] == [] and reread['approval_state'] == 'pending_approval'
    assert client.post('/api/runs/%s/export' % run_id, json={'expected_revision': 1}).status_code == 422


def _paid_check(client, monkeypatch, tag, stream=None):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_SAM_ENABLED', 'true')
    run_id = _make_run(client)
    raw = _png_bytes()
    monkeypatch.setenv('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', hashlib.sha256(raw).hexdigest())
    _grant(1)
    before = client.get('/api/runs/%s' % run_id).json()['model_usage']
    calls = []
    with patch('backend.sam.urlopen', side_effect=_transport(tag, calls, stream)):
        response = client.post('/api/runs/%s/photo-check' % run_id,
                               json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
    assert response.status_code == 200, response.text
    return run_id, response.json(), before, calls


def test_not_detected_refuses_approval_and_export(client, monkeypatch):
    run_id, body, before, _ = _paid_check(client, monkeypatch, '', stream=_empty_stream)
    assert body['check']['label'] == 'not_detected'
    assert body['preview'] is None
    assert client.post('/api/runs/%s/approve' % run_id, json={'expected_revision': 1}).status_code == 422
    assert client.post('/api/runs/%s/export' % run_id, json={'expected_revision': 1}).status_code == 422
    assert body['receipt']['model_usage'] == before
    _assert_clean(body['receipt'])


def test_possible_clipping_has_no_override(client, monkeypatch):
    run_id, body, _, _ = _paid_check(client, monkeypatch, EDGE_TAG)
    assert body['check']['label'] == 'possible_clipping'
    approve = client.post('/api/runs/%s/approve' % run_id, json={'expected_revision': 1})
    assert approve.status_code == 422
    assert 'Photo' in approve.json()['detail']
    assert client.post('/api/runs/%s/export' % run_id, json={'expected_revision': 1}).status_code == 422


def test_unknown_geometry_refuses_approval_and_export(client, monkeypatch):
    run_id, body, _, _ = _paid_check(client, monkeypatch, FRAME_TAG)
    assert body['check']['label'] == 'unknown'
    assert client.post('/api/runs/%s/approve' % run_id, json={'expected_revision': 1}).status_code == 422
    assert client.post('/api/runs/%s/export' % run_id, json={'expected_revision': 1}).status_code == 422
    run_id2, body2, _, _ = _paid_check(client, monkeypatch, MULTI_TAG)
    assert body2['check']['reason'] == 'needs_review'
    assert client.post('/api/runs/%s/approve' % run_id2, json={'expected_revision': 1}).status_code == 422


def test_detected_approves_and_exports_with_clean_payload(client, monkeypatch):
    run_id, body, before, _ = _paid_check(client, monkeypatch, CLEAR_TAG)
    assert body['check']['label'] == 'detected'
    assert body['preview']['label'] == 'detected'
    assert body['receipt']['model_usage'] == before
    assert 'sent to the segmentation provider' in body['receipt']['photo_transport']['note']
    assert client.post('/api/runs/%s/approve' % run_id, json={'expected_revision': 1}).status_code == 200
    exported = client.post('/api/runs/%s/export' % run_id, json={'expected_revision': 1})
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    assert payload['exported_revision'] == 1
    _assert_clean(payload)


def test_text_edit_after_detected_requires_fresh_check(client, monkeypatch):
    run_id, body, _, _ = _paid_check(client, monkeypatch, CLEAR_TAG)
    assert client.post('/api/runs/%s/approve' % run_id, json={'expected_revision': 1}).status_code == 200
    edit = client.post('/api/runs/%s/revise' % run_id,
                       json={'post': 'Vegan leather wallet. Designed in Texas.',
                             'email': 'For Austin commuters. $49.', 'base_revision': 1})
    assert edit.status_code == 200
    assert edit.json()['revision'] == 2
    approve = client.post('/api/runs/%s/approve' % run_id, json={'expected_revision': 2})
    assert approve.status_code == 422
    assert 'Photo' in approve.json()['detail']


def test_remove_photo_clears_and_requires_reapprove(client):
    run_id = _make_run(client)
    with patch('backend.sam.urlopen', side_effect=AssertionError('zero HTTP expected')):
        check = client.post('/api/runs/%s/photo-check' % run_id,
                            json={'image_data_uri': _data_uri(_png_bytes()), 'expected_revision': 0})
    assert check.status_code == 200
    history_before = check.json()['receipt']['revision_history']
    removed = client.request('DELETE', '/api/runs/%s/photo' % run_id, json={'expected_revision': 1})
    assert removed.status_code == 200, removed.text
    assert removed.json() == {'revision': 2, 'photo_state': 'no_photo', 'approval_state': 'pending_approval'}
    reread = client.get('/api/runs/%s' % run_id).json()
    assert reread['photo_status']['state'] == 'no_photo'
    assert [entry.get('photo_event') for entry in reread['revision_history'][-2:]] == ['photo_checked', 'photo_removed']
    assert reread['revision_history'][:len(history_before)] == history_before
    # The shared Receipt DTO serializes an absent human draft as null; the
    # meaningful claim is that removal fabricates no human draft content.
    assert reread.get('human_draft') is None
    assert reread['maker_draft_v2'] == check.json()['receipt']['maker_draft_v2']
    assert client.post('/api/runs/%s/approve' % run_id, json={'expected_revision': 2}).status_code == 200
    exported = client.post('/api/runs/%s/export' % run_id, json={'expected_revision': 2})
    assert exported.status_code == 200
    _assert_clean(exported.json())
    assert client.request('DELETE', '/api/runs/%s/photo' % run_id, json={'expected_revision': 2}).status_code == 422


def test_remove_rejects_forged_and_stale_versions(client):
    run_id = _make_run(client)
    assert client.request('DELETE', '/api/runs/%s/photo' % run_id, json={}).status_code == 422
    assert client.request('DELETE', '/api/runs/%s/photo' % run_id,
                          json={'expected_revision': True}).status_code == 422
    assert client.request('DELETE', '/api/runs/%s/photo' % run_id,
                          json={'expected_revision': 0, 'actor': 'mallory'}).status_code == 422
    assert client.request('DELETE', '/api/runs/%s/photo' % run_id,
                          json={'expected_revision': 5}).status_code == 409


def test_check_rejects_client_geometry_budget_and_actor_fields(client):
    run_id = _make_run(client)
    uri = _data_uri(_png_bytes())
    for forged in ({'image_data_uri': uri, 'expected_revision': 0, 'geometry': 'detected'},
                   {'image_data_uri': uri, 'expected_revision': 0, 'verdict': 'detected'},
                   {'image_data_uri': uri, 'expected_revision': 0, 'actor': 'mallory'},
                   {'image_data_uri': uri, 'expected_revision': 0, 'budget': 5},
                   {'image_data_uri': uri, 'expected_revision': 0, 'epoch': 1}):
        assert client.post('/api/runs/%s/photo-check' % run_id, json=forged).status_code == 422


def test_failed_run_cannot_approve_or_export(client):
    with store.connect() as db:
        db.execute(text("INSERT INTO agents(name,profile) VALUES ('maker',CAST(:p AS jsonb)) ON CONFLICT DO NOTHING"),
                   {'p': json.dumps({'name': 'Maker'})})
        failed = {'status': 'failed', 'approval_state': 'pending_approval', 'revision': 0}
        db.execute(text("INSERT INTO runs(id,receipt,agent_name,state) VALUES ('run_bad',CAST(:r AS jsonb),'maker','pending_approval')"),
                   {'r': json.dumps(failed)})
    assert client.post('/api/runs/run_bad/approve', json={}).status_code == 422
    assert client.post('/api/runs/run_bad/export', json={}).status_code == 422


def test_unknown_run_is_404(client):
    uri = _data_uri(_png_bytes())
    assert client.post('/api/runs/run_missing/photo-check',
                       json={'image_data_uri': uri, 'expected_revision': 0}).status_code == 404
    assert client.request('DELETE', '/api/runs/run_missing/photo',
                          json={'expected_revision': 0}).status_code == 404
