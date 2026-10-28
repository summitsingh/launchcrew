"""Durable photo SAM admission and bounded transport on real Postgres.

Uses only the existing ``test_engine`` and ``client`` fixtures; every
helper below is defined in this file. HTTP is mocked at the transport
seam only; SQL and concurrency are real. The global budget is reset to
zero by the fixture before each test; tests grant images explicitly.
"""
import base64
import hashlib
import io
import json
import threading
from unittest.mock import patch

import pytest
from sqlalchemy import text

from backend import photo_admission, sam, store
from backend.photo_input import parse_photo_data_uri
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
def operable_sam(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_SAM_ENABLED', 'true')
    monkeypatch.delenv('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', raising=False)


def _make_run(client):
    response = client.post('/api/runs', json={'idea': 'photo admission probe', 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    return response.json()['run_id']


def _png_bytes(width=32, height=16, color=(200, 30, 30)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), color).save(buffer, format='PNG')
    return buffer.getvalue()


def _data_uri(raw, mime='image/png'):
    kind = 'png' if mime == 'image/png' else 'jpeg'
    return 'data:image/%s;base64,' % kind + base64.b64encode(raw).decode()


def _sse(*events):
    return io.BytesIO(b''.join(b'data: ' + json.dumps(event).encode() + b'\n\n' for event in events))


def _tag(object_id, box, mask):
    x1, y1, x2, y2, w, h = box
    mh, mw = mask
    return ('<0f>%d<|box;x1=%d;y1=%d;x2=%d;y2=%d;w=%d;h=%d|>'
            '<|mask;x=0;y=0;data=%d,%d,~e30=|>') % (object_id, x1, y1, x2, y2, w, h, mh, mw)


CLEAR_TAG = _tag(1, (4, 4, 20, 12, 32, 16), (9, 17))


def _stream_text(payload_text):
    return _sse({'type': 'response.output_text.delta', 'delta': payload_text},
                {'type': 'response.completed'})


def _transport(payload_text, calls):
    def send(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith('/files'):
            assert request.get_header('Accept') == 'application/json'
            return io.BytesIO(b'{"id":"file-live"}')
        assert request.full_url.endswith('/responses')
        assert request.get_header('Accept') == 'text/event-stream'
        body = json.loads(request.data)
        assert body['model'] == 'sam-3.1' and body['stream'] is True
        assert body['metadata'] == {'mask_encoding': 'lossless'}
        assert body['input'][0]['content'][1] == {'type': 'input_image', 'file_id': 'file-live'}
        return _stream_text(payload_text)
    return send


def _grant(images):
    with store.connect() as db:
        db.execute(text("UPDATE sam_budget SET remaining_images=:n WHERE id='global'"), {'n': images})


def _budget():
    with store.connect() as db:
        return db.execute(text("SELECT remaining_images FROM sam_budget WHERE id='global'")).scalar()


def _calls():
    with store.connect() as db:
        return db.execute(text('SELECT run_id, revision, status, label FROM sam_calls')).all()


def _approve_bytes(monkeypatch, raw):
    monkeypatch.setenv('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', hashlib.sha256(raw).hexdigest())


def test_oversize_json_image_rejected_before_admission(client):
    run_id = _make_run(client)
    big = _data_uri(b'\xff\xd8\xff\xe0' + b'a' * (1024 * 1024 + 1), 'image/jpeg')
    response = client.post('/api/runs/%s/photo-check' % run_id,
                           json={'image_data_uri': big, 'expected_revision': 0})
    assert response.status_code == 422
    assert _budget() == 0
    assert _calls() == []


def test_empty_json_image_rejected(client):
    run_id = _make_run(client)
    response = client.post('/api/runs/%s/photo-check' % run_id,
                           json={'image_data_uri': 'data:image/png;base64,', 'expected_revision': 0})
    assert response.status_code == 422
    assert _calls() == []


def test_malformed_truncated_and_animated_rejected(client):
    from PIL import Image
    run_id = _make_run(client)
    good = _png_bytes()
    truncated = good[:40]
    frames = []
    for color in ((200, 30, 30), (30, 200, 30)):
        frames.append(Image.new('RGB', (16, 16), color))
    animated_buffer = io.BytesIO()
    frames[0].save(animated_buffer, format='PNG', save_all=True, append_images=frames[1:])
    animated = animated_buffer.getvalue()
    assert Image.open(io.BytesIO(animated)).n_frames == 2
    for raw in (b'not an image at all', truncated, animated):
        response = client.post('/api/runs/%s/photo-check' % run_id,
                               json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
        assert response.status_code == 422, raw[:12]
    assert _calls() == []


def test_exif_oriented_dims_and_pixel_bound():
    from PIL import Image
    buffer = io.BytesIO()
    frame = Image.new('RGB', (16, 32), (10, 10, 200))
    exif = Image.Exif()
    exif[274] = 6
    frame.save(buffer, format='JPEG', exif=exif)
    parsed = parse_photo_data_uri(_data_uri(buffer.getvalue(), 'image/jpeg'))
    assert (parsed['width'], parsed['height']) == (32, 16)
    wide = _png_bytes(width=4000, height=3000)
    assert len(wide) <= 1024 * 1024
    try:
        parse_photo_data_uri(_data_uri(wide))
        raise AssertionError('pixel bound not enforced')
    except Exception as error:
        assert 'pixel' in str(error).lower()


def test_non_approved_bytes_refused_without_spend(client, monkeypatch):
    run_id = _make_run(client)
    _grant(1)
    raw = _png_bytes()
    calls = []
    with patch('backend.sam.urlopen', side_effect=_transport(CLEAR_TAG, calls)):
        response = client.post('/api/runs/%s/photo-check' % run_id,
                               json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
    assert response.status_code == 422
    assert calls == []
    assert _budget() == 1
    assert _calls() == []


def test_exhausted_budget_refused_without_http(client, monkeypatch):
    run_id = _make_run(client)
    raw = _png_bytes()
    _approve_bytes(monkeypatch, raw)
    calls = []
    with patch('backend.sam.urlopen', side_effect=_transport(CLEAR_TAG, calls)):
        response = client.post('/api/runs/%s/photo-check' % run_id,
                               json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
    assert response.status_code == 422
    assert calls == []
    assert _calls() == []


def test_detected_check_spends_one_image_and_attaches(client, monkeypatch):
    run_id = _make_run(client)
    raw = _png_bytes()
    _approve_bytes(monkeypatch, raw)
    _grant(1)
    calls = []
    with patch('backend.sam.urlopen', side_effect=_transport(CLEAR_TAG, calls)):
        response = client.post('/api/runs/%s/photo-check' % run_id,
                               json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['check']['method'] == 'sam-3.1'
    assert body['check']['label'] == 'detected'
    assert body['check']['photo_state'] == 'checked'
    assert body['preview'] == {'frame_w': 32, 'frame_h': 16,
                               'crop': {'x1': 3, 'y1': 3, 'x2': 21, 'y2': 13}, 'label': 'detected'}
    assert [url.split('/')[-1] for url in calls] == ['files', 'responses']
    assert _budget() == 0
    receipt = body['receipt']
    assert receipt['revision'] == 1
    assert receipt['photo_status']['label'] == 'detected'
    assert receipt['photo_status']['revision'] == 1
    assert receipt['approvals'] == [] and receipt['approval_state'] == 'pending_approval'
    text = json.dumps(receipt)
    for secret in ('base64', 'file-live', 'photo_sha256', 'mask', 'box', 'payload'):
        assert secret not in text
    assert hashlib.sha256(raw).hexdigest() not in text


def test_terminal_call_never_resent(client, monkeypatch):
    run_id = _make_run(client)
    raw = _png_bytes()
    _approve_bytes(monkeypatch, raw)
    _grant(1)
    calls = []
    with patch('backend.sam.urlopen', side_effect=_transport(CLEAR_TAG, calls)):
        first = client.post('/api/runs/%s/photo-check' % run_id,
                            json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
        assert first.status_code == 200
        second = client.post('/api/runs/%s/photo-check' % run_id,
                             json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
    assert second.status_code == 200
    assert second.json()['check']['label'] == first.json()['check']['label'] == 'detected'
    assert second.json()['preview'] is None
    assert len(calls) == 2
    assert _budget() == 0


def test_parallel_different_image_returns_single_sequence(client, monkeypatch):
    run_id = _make_run(client)
    first_raw = _png_bytes(color=(200, 30, 30))
    second_raw = _png_bytes(color=(30, 30, 200))
    monkeypatch.setenv('LAUNCHCREW_PHOTO_APPROVED_DIGESTS',
                       ','.join([hashlib.sha256(first_raw).hexdigest(), hashlib.sha256(second_raw).hexdigest()]))
    _grant(1)
    calls = []
    lock = threading.Lock()

    def slow_transport(request, timeout):
        with lock:
            calls.append(request.full_url)
        if request.full_url.endswith('/files'):
            import time
            time.sleep(0.2)
            return io.BytesIO(b'{"id":"file-live"}')
        return _stream_text(CLEAR_TAG)

    bodies = [{'image_data_uri': _data_uri(raw), 'expected_revision': 0} for raw in (first_raw, second_raw)]
    results = []

    def one(body):
        results.append(client.post('/api/runs/%s/photo-check' % run_id, json=body).status_code)

    threads = [threading.Thread(target=one, args=(body,)) for body in bodies]
    with patch('backend.sam.urlopen', side_effect=slow_transport):
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert sorted(results) == [200, 409]
    assert len([url for url in calls if url.endswith('/files')]) == 1
    assert len(calls) == 2


def test_concurrent_duplicate_admits_one_paid_sequence(client, monkeypatch):
    run_id = _make_run(client)
    raw = _png_bytes()
    _approve_bytes(monkeypatch, raw)
    _grant(1)
    calls = []
    lock = threading.Lock()

    def slow_transport(request, timeout):
        with lock:
            calls.append(request.full_url)
        if request.full_url.endswith('/files'):
            import time
            time.sleep(0.2)
            return io.BytesIO(b'{"id":"file-live"}')
        return _stream_text(CLEAR_TAG)

    body = {'image_data_uri': _data_uri(raw), 'expected_revision': 0}
    results = []

    def one():
        results.append(client.post('/api/runs/%s/photo-check' % run_id, json=body).status_code)

    threads = [threading.Thread(target=one) for _ in range(2)]
    with patch('backend.sam.urlopen', side_effect=slow_transport):
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert sorted(results) == [200, 200]
    # Transport barrier: exactly one upload and one segmentation total for
    # the duplicate pair; the loser replays pending with zero HTTP.
    assert len([url for url in calls if url.endswith('/files')]) == 1
    assert len([url for url in calls if url.endswith('/responses')]) == 1
    assert len(calls) == 2
    assert _budget() == 0


def test_crash_ledger_replay_sends_nothing_and_stays_pending(client, monkeypatch):
    run_id = _make_run(client)
    raw = _png_bytes()
    _approve_bytes(monkeypatch, raw)
    _grant(1)
    digest = hashlib.sha256(raw).hexdigest()
    # Simulate a crash between admission and finalization: the ledger row
    # plus budget decrement commit, but transport never runs.
    row = photo_admission.admit_photo_check(store.engine(), run_id, 0, digest, 0, actor='demo_placeholder')
    assert row['status'] == 'admitted' and row['is_owner'] is True
    assert _budget() == 0
    calls = []

    def no_resend(request, timeout):
        calls.append(request.full_url)
        return _stream_text(CLEAR_TAG)

    with patch('backend.sam.urlopen', side_effect=no_resend):
        response = client.post('/api/runs/%s/photo-check' % run_id,
                               json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
    assert response.status_code == 200, response.text
    body = response.json()
    # Pending and honest: no finished verdict is faked while in flight.
    assert body['check']['label'] is None
    assert body['check']['reason'] == 'check_requested: segmentation in flight'
    assert body['check']['photo_state'] == 'check_requested'
    assert body['preview'] is None
    assert calls == []
    assert _budget() == 0
    with store.connect() as db:
        status = db.execute(text('SELECT status FROM sam_calls')).scalar()
    assert status == 'admitted'
    assert client.post('/api/runs/%s/approve' % run_id, json={'expected_revision': 1}).status_code == 422


def test_upload_failure_prevents_sam_and_never_resends(client, monkeypatch):
    run_id = _make_run(client)
    raw = _png_bytes()
    _approve_bytes(monkeypatch, raw)
    _grant(1)
    calls = []

    def failing_files(request, timeout):
        calls.append(request.full_url)
        raise OSError('files unreachable')

    with patch('backend.sam.urlopen', side_effect=failing_files):
        first = client.post('/api/runs/%s/photo-check' % run_id,
                            json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
        assert first.status_code == 200, first.text
        assert first.json()['check']['label'] == 'unknown'
        second = client.post('/api/runs/%s/photo-check' % run_id,
                             json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
    assert second.status_code == 200
    assert second.json()['check']['label'] == 'unknown'
    assert calls == [url for url in calls if url.endswith('/files')]
    assert len(calls) == 1
    with store.connect() as db:
        status = db.execute(text('SELECT status FROM sam_calls')).scalar()
    assert status == 'failed_terminal'


def test_ambiguous_multi_match_is_terminal_and_never_resent(client, monkeypatch):
    run_id = _make_run(client)
    raw = _png_bytes()
    _approve_bytes(monkeypatch, raw)
    _grant(1)
    ambiguous = _tag(1, (4, 4, 20, 12, 32, 16), (9, 17)) + ',' + _tag(2, (1, 1, 10, 10, 32, 16), (10, 10))
    calls = []
    with patch('backend.sam.urlopen', side_effect=_transport(ambiguous, calls)):
        first = client.post('/api/runs/%s/photo-check' % run_id,
                            json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
        assert first.status_code == 200
        assert first.json()['check']['label'] == 'unknown'
        assert first.json()['check']['reason'] == 'needs_review'
        second = client.post('/api/runs/%s/photo-check' % run_id,
                             json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
    assert second.json()['check']['reason'] == 'needs_review'
    assert len(calls) == 2
    with store.connect() as db:
        status = db.execute(text('SELECT status FROM sam_calls')).scalar()
    assert status == 'failed_terminal'


def test_moved_revision_finalization_attaches_nothing(client, monkeypatch):
    run_id = _make_run(client)
    raw = _png_bytes()
    _approve_bytes(monkeypatch, raw)
    _grant(1)
    digest = hashlib.sha256(raw).hexdigest()
    row = photo_admission.admit_photo_check(store.engine(), run_id, 0, digest, 0, actor='demo_placeholder')
    assert row['status'] == 'admitted'
    receipt = client.get('/api/runs/%s' % run_id).json()
    edit = {'post': 'Vegan leather wallet. Designed in Texas.',
            'email': 'For Austin commuters. $49.',
            'base_revision': receipt.get('revision', 0) + 1}
    # The admission already bumped to revision 1; move it again with a text edit.
    revised = client.post('/api/runs/%s/revise' % run_id, json={
        'post': edit['post'], 'email': edit['email'], 'base_revision': 1})
    assert revised.status_code == 200
    with pytest.raises(Exception) as excinfo:
        photo_admission.finalize_photo_check(
            store.engine(), row['id'],
            {'label': 'detected', 'reason': 'clear_single', 'policy_version': 'photo-geometry/v1'},
            0, actor='demo_placeholder')
    assert 'stale' in str(excinfo.value).lower()
    with store.connect() as db:
        status = db.execute(text('SELECT status FROM sam_calls WHERE id=:id'), {'id': row['id']}).scalar()
        receipt = db.execute(text('SELECT receipt FROM runs WHERE id=:id'), {'id': run_id}).scalar()
    assert status == 'failed_terminal'
    assert receipt['revision'] == 2
    assert 'detected' not in json.dumps(receipt.get('photo_status', {}))
    assert client.post('/api/runs/%s/approve' % run_id, json={'expected_revision': 2}).status_code == 422


def test_forged_fields_and_stale_versions(client):
    run_id = _make_run(client)
    raw = _png_bytes()
    body = {'image_data_uri': _data_uri(raw), 'expected_revision': 0}
    assert client.post('/api/runs/%s/photo-check' % run_id,
                       json={**body, 'verdict': 'detected'}).status_code == 422
    assert client.post('/api/runs/%s/photo-check' % run_id,
                       json={**body, 'actor': 'mallory'}).status_code == 422
    assert client.post('/api/runs/%s/photo-check' % run_id,
                       json={'image_data_uri': body['image_data_uri']}).status_code == 422
    for forged in (True, 1.5, '0'):
        response = client.post('/api/runs/%s/photo-check' % run_id,
                               json={'image_data_uri': body['image_data_uri'], 'expected_revision': forged})
        assert response.status_code == 422, forged
    stale = client.post('/api/runs/%s/photo-check' % run_id,
                        json={'image_data_uri': body['image_data_uri'], 'expected_revision': 7})
    assert stale.status_code == 409


def test_stale_paid_version_returns_409(client, monkeypatch):
    run_id = _make_run(client)
    raw = _png_bytes()
    _approve_bytes(monkeypatch, raw)
    _grant(5)
    calls = []
    with patch('backend.sam.urlopen', side_effect=_transport(CLEAR_TAG, calls)):
        first = client.post('/api/runs/%s/photo-check' % run_id,
                            json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
        assert first.status_code == 200
        other = _png_bytes(color=(30, 30, 200))
        monkeypatch.setenv('LAUNCHCREW_PHOTO_APPROVED_DIGESTS',
                           ','.join([hashlib.sha256(raw).hexdigest(), hashlib.sha256(other).hexdigest()]))
        conflict = client.post('/api/runs/%s/photo-check' % run_id,
                               json={'image_data_uri': _data_uri(other), 'expected_revision': 0})
        assert conflict.status_code == 409
        stale = client.post('/api/runs/%s/photo-check' % run_id,
                            json={'image_data_uri': _data_uri(other), 'expected_revision': 9})
        assert stale.status_code == 409
    assert len([url for url in calls if url.endswith('/files')]) == 1


def test_budget_migration_defaults_zero_and_rejects_negative(test_engine):
    """Prove the migration default on actually fresh migration state.

    The shared ``test_engine`` schema carries budget grants from earlier
    tests, so asserting the default on it would confuse the fixture reset
    with the migration proof. Migrate a fresh schema instead.
    """
    import os
    from uuid import uuid4 as _uuid4
    from alembic import command as _alembic_command
    from alembic.config import Config as _AlembicConfig
    from sqlalchemy import create_engine as _make_engine
    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+psycopg://', 1)
    schema = 'test_budget_mig_' + _uuid4().hex
    admin = _make_engine(url)
    original_engine = store.engine
    try:
        with admin.begin() as connection:
            connection.execute(text('CREATE SCHEMA ' + schema))
        fresh = _make_engine(url, connect_args={'options': '-csearch_path=' + schema})
        try:
            store.engine = lambda: fresh
            _alembic_command.upgrade(_AlembicConfig('alembic.ini'), 'head')
            with fresh.begin() as connection:
                rows = connection.execute(text("SELECT id, remaining_images FROM sam_budget")).all()
            assert rows == [('global', 0)]
            with pytest.raises(Exception):
                with fresh.begin() as connection:
                    connection.execute(text("UPDATE sam_budget SET remaining_images=-1 WHERE id='global'"))
            photo_admission.set_budget_remaining(fresh, 2)
            with fresh.begin() as connection:
                assert connection.execute(text("SELECT remaining_images FROM sam_budget WHERE id='global'")).scalar() == 2
            photo_admission.set_budget_remaining(fresh, 0)
        finally:
            store.engine = original_engine
            fresh.dispose()
    finally:
        with admin.begin() as connection:
            connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        admin.dispose()


def test_failed_run_cannot_attach(client, monkeypatch):
    with store.connect() as db:
        db.execute(text("INSERT INTO agents(name,profile) VALUES ('maker',CAST(:p AS jsonb)) ON CONFLICT DO NOTHING"),
                   {'p': json.dumps({'name': 'Maker'})})
        failed = {'status': 'failed', 'approval_state': 'pending_approval', 'revision': 0}
        db.execute(text("INSERT INTO runs(id,receipt,agent_name,state) VALUES ('run_failed',CAST(:r AS jsonb),'maker','pending_approval')"),
                   {'r': json.dumps(failed)})
    raw = _png_bytes()
    _approve_bytes(monkeypatch, raw)
    _grant(1)
    calls = []
    with patch('backend.sam.urlopen', side_effect=_transport(CLEAR_TAG, calls)):
        response = client.post('/api/runs/run_failed/photo-check',
                               json={'image_data_uri': _data_uri(raw), 'expected_revision': 0})
    assert response.status_code == 422
    assert calls == []
    assert _budget() == 1


def test_zero_automatic_sam_on_other_routes(client, monkeypatch):
    calls = []

    def no_sam(request, timeout):
        calls.append(request.full_url)
        raise AssertionError('no automatic SAM expected')

    with patch('backend.sam.urlopen', side_effect=no_sam):
        run_id = _make_run(client)
        assert client.get('/api/queue').status_code == 200
        assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 200
        campaign = client.post('/api/campaigns', json={'idea': 'photo admission probe', 'agent_name': 'Maker'})
        assert campaign.status_code == 201, campaign.text
    assert calls == []
    assert sam.photo_sam_operable() is True
