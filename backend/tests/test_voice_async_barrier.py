"""Voice edit and delete barriers for async and sync runs on real Postgres.

Synthetic style references only about gardens, trails, and recipe
cards. No real names, emails, account IDs, photos, secrets, or
personal data. No network, no live model calls, no credentials.
Uses only the existing test_engine and client fixtures. Timing uses
a stage gate plus threading events, never sleeps for correctness,
and no database transaction is held across model calls.
"""
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.responses import Response
from sqlalchemy import text

from backend import auth, run_jobs, store
from launchcrew import run

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
ACTOR_ONE = 'google:voice-barrier-one'
ACTOR_TWO = 'google:voice-barrier-two'


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


def _examples():
    topics = ('garden layout', 'trail map', 'recipe card')
    return [{'input': 'Synthetic draft about %s' % topic,
             'output': 'Synthetic revision about %s' % topic} for topic in topics]


def _voice_content(terms):
    return {'examples': _examples(), 'banned_terms': list(terms)}


def _create_voice(client, terms=('harbor',), title='Synthetic voice'):
    response = client.post('/api/memory', json={
        'kind': 'voice_profile', 'title': title, 'content': _voice_content(terms)})
    assert response.status_code == 201, response.text
    return response.json()


def _edit_voice(client, voice_id, terms, title='Synthetic voice edited'):
    response = client.put('/api/memory/%s' % voice_id, json={
        'title': title, 'content': _voice_content(terms)})
    assert response.status_code == 200, response.text
    return response.json()


def _wait_receipt(client, run_id, timeout=30.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get('/api/runs/%s/receipt' % run_id)
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get('status') in ('completed', 'failed'):
            return last
        time.sleep(0.05)
    raise AssertionError('Timed out waiting for run ' + run_id + ': ' + repr(last))


def _gated_start(monkeypatch, gate):
    original = run_jobs.start_async_run

    def started(run_id, *args, **kwargs):
        kwargs['stage_gate'] = gate
        return original(run_id, *args, **kwargs)

    monkeypatch.setattr(run_jobs, 'start_async_run', started)


def _session_cookie(actor):
    response = Response()
    auth.save_session({'actor': actor}, response)
    return response.headers['set-cookie'].split(';')[0].split('=', 1)[1]


def _sign_in(client, monkeypatch, actor):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    opaque = _session_cookie(actor)
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque)


def test_edit_during_async_run_leaves_final_stale(client, monkeypatch):
    voice = _create_voice(client, ('harbor',))
    release = threading.Event()
    entered = threading.Event()

    def gate(stage):
        if stage == 'maker_draft_v1':
            entered.set()
            assert release.wait(timeout=30.0)

    _gated_start(monkeypatch, gate)
    response = client.post('/api/runs/async', json={
        'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]})
    assert response.status_code == 202, response.text
    run_id = response.json()['run_id']
    pending = response.json()['receipt']
    assert pending['status'] == 'running'
    assert pending['voice_profile']['id'] == voice['id']
    assert entered.wait(timeout=30.0)
    _edit_voice(client, voice['id'], ('harbor', 'zebra'))
    release.set()
    final = _wait_receipt(client, run_id)
    assert final['status'] == 'completed'
    assert final['voice_stale'] is True
    assert final['approval_state'] == 'pending_approval'
    assert final['approvals'] == []
    assert any(event.get('step') == 'voice_invalidated'
               for event in final['audit']['event_log'])
    assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 409
    assert client.post('/api/runs/%s/export' % run_id, json={}).status_code == 422


def test_delete_during_async_run_leaves_final_stale(client, monkeypatch):
    voice = _create_voice(client, ('harbor',))
    release = threading.Event()
    entered = threading.Event()

    def gate(stage):
        if stage == 'maker_draft_v1':
            entered.set()
            assert release.wait(timeout=30.0)

    _gated_start(monkeypatch, gate)
    response = client.post('/api/runs/async', json={
        'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]})
    assert response.status_code == 202, response.text
    run_id = response.json()['run_id']
    assert entered.wait(timeout=30.0)
    assert client.delete('/api/memory/%s' % voice['id']).status_code == 204
    release.set()
    final = _wait_receipt(client, run_id)
    assert final['status'] == 'completed'
    assert final['voice_stale'] is True
    assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 409
    assert client.post('/api/runs/%s/export' % run_id, json={}).status_code == 422


def test_concurrent_sync_accept_and_edit_marks_saved_stale(client, monkeypatch):
    voice = _create_voice(client, ('harbor',))
    release = threading.Event()
    entered = threading.Event()
    original = run.run_pipeline

    def gated(*args, **kwargs):
        def gate(stage):
            if stage == 'maker_draft_v1':
                entered.set()
                assert release.wait(timeout=30.0)
        kwargs['stage_gate'] = gate
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    results = []
    errors = []

    def requester():
        try:
            results.append(client.post('/api/runs', json={
                'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]}))
        except Exception as error:
            errors.append(error)

    with patch('launchcrew.run.run_pipeline', side_effect=gated):
        thread = threading.Thread(target=requester)
        thread.start()
        assert entered.wait(timeout=30.0)
        _edit_voice(client, voice['id'], ('zebra',))
        release.set()
        thread.join(timeout=30.0)
    assert errors == []
    assert len(results) == 1
    assert results[0].status_code == 201, results[0].text
    body = results[0].json()
    assert body['voice_stale'] is True
    assert body['approval_state'] == 'pending_approval'
    run_id = body['run_id']
    assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 409
    assert client.post('/api/runs/%s/export' % run_id, json={}).status_code == 422


def test_other_actor_unaffected_by_voice_edit(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    voice_one = _create_voice(client, ('harbor',), 'Voice one')
    run_one = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice_one['id']]}).json()
    _sign_in(client, monkeypatch, ACTOR_TWO)
    voice_two = _create_voice(client, ('zebra',), 'Voice two')
    run_two = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice_two['id']]}).json()
    _sign_in(client, monkeypatch, ACTOR_ONE)
    _edit_voice(client, voice_one['id'], ('harbor', 'meadow'))
    stale = client.get('/api/runs/%s' % run_one['run_id']).json()
    assert stale['voice_stale'] is True
    assert client.post('/api/runs/%s/approve' % run_one['run_id'], json={}).status_code == 409
    _sign_in(client, monkeypatch, ACTOR_TWO)
    clean = client.get('/api/runs/%s' % run_two['run_id']).json()
    assert clean.get('voice_stale') is not True
    assert clean['voice_profile']['id'] == voice_two['id']
    assert client.post('/api/runs/%s/approve' % run_two['run_id'], json={}).status_code == 200
    assert client.post('/api/runs/%s/export' % run_two['run_id'], json={}).status_code == 200
    with store.connect() as db:
        owner_one = db.execute(text('SELECT workspace_id FROM runs WHERE id=:id'),
                               {'id': run_one['run_id']}).scalar()
        owner_two = db.execute(text('SELECT workspace_id FROM runs WHERE id=:id'),
                               {'id': run_two['run_id']}).scalar()
    assert owner_one == ACTOR_ONE
    assert owner_two == ACTOR_TWO


def test_no_edit_sync_run_approvable(client):
    voice = _create_voice(client, ('harbor',))
    response = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body.get('voice_stale') is not True
    assert body['voice_profile']['id'] == voice['id']
    run_id = body['run_id']
    assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 200
    assert client.post('/api/runs/%s/export' % run_id, json={}).status_code == 200


def test_no_edit_async_run_approvable(client):
    voice = _create_voice(client, ('harbor',))
    response = client.post('/api/runs/async', json={
        'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]})
    assert response.status_code == 202, response.text
    run_id = response.json()['run_id']
    final = _wait_receipt(client, run_id)
    assert final['status'] == 'completed'
    assert final.get('voice_stale') is not True
    assert final['voice_profile']['id'] == voice['id']
    assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 200
    assert client.post('/api/runs/%s/export' % run_id, json={}).status_code == 200
