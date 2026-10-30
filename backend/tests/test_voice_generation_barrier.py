"""Voice generation barriers for sync and campaign on real Postgres.

Proves title-only edits and A->B->A content returns invalidate, and
campaign edits in flight mark each affected day stale with approve and
export refusal. Uses only the existing test_engine and client fixtures.
Timing uses a stage gate plus threading events, never sleeps for
correctness, and no database transaction is held across model calls.

Synthetic style references only about gardens, trails, and recipe
cards. No real names, emails, account IDs, photos, secrets, or
personal data. No network, no live model calls, no credentials.
"""
import threading
import time
from unittest.mock import patch

import pytest
from sqlalchemy import text

from backend import store
from launchcrew import run

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


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


def _edit_voice(client, voice_id, terms, title):
    response = client.put('/api/memory/%s' % voice_id, json={
        'title': title, 'content': _voice_content(terms)})
    assert response.status_code == 200, response.text
    return response.json()


def _run_sync_in_thread(client, voice_id, gate):
    original = run.run_pipeline
    results = []
    errors = []

    def gated(*args, **kwargs):
        kwargs['stage_gate'] = gate
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    def requester():
        try:
            results.append(client.post('/api/runs', json={
                'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice_id]}))
        except Exception as error:
            errors.append(error)

    patcher = patch('launchcrew.run.run_pipeline', side_effect=gated)
    patcher.start()
    thread = threading.Thread(target=requester)
    thread.start()
    return thread, results, errors, patcher


def test_title_only_edit_during_sync_marks_saved_stale(client):
    voice = _create_voice(client, ('harbor',), 'Synthetic voice')
    release = threading.Event()
    entered = threading.Event()

    def gate(stage):
        if stage == 'maker_draft_v1':
            entered.set()
            assert release.wait(timeout=30.0)

    thread, results, errors, patcher = _run_sync_in_thread(client, voice['id'], gate)
    try:
        assert entered.wait(timeout=30.0)
        _edit_voice(client, voice['id'], ('harbor',), 'Synthetic voice retitled')
        release.set()
        thread.join(timeout=30.0)
    finally:
        patcher.stop()
    assert errors == []
    assert len(results) == 1
    assert results[0].status_code == 201, results[0].text
    body = results[0].json()
    assert body['voice_stale'] is True
    assert body['approval_state'] == 'pending_approval'
    assert body['voice_profile']['id'] == voice['id']
    run_id = body['run_id']
    assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 409
    assert client.post('/api/runs/%s/export' % run_id, json={}).status_code == 422


def test_aba_content_during_sync_marks_saved_stale(client):
    voice = _create_voice(client, ('harbor',), 'Synthetic voice')
    release = threading.Event()
    entered = threading.Event()

    def gate(stage):
        if stage == 'maker_draft_v1':
            entered.set()
            assert release.wait(timeout=30.0)

    thread, results, errors, patcher = _run_sync_in_thread(client, voice['id'], gate)
    try:
        assert entered.wait(timeout=30.0)
        _edit_voice(client, voice['id'], ('zebra',), 'Synthetic voice edited')
        _edit_voice(client, voice['id'], ('harbor',), 'Synthetic voice')
        release.set()
        thread.join(timeout=30.0)
    finally:
        patcher.stop()
    assert errors == []
    assert len(results) == 1
    assert results[0].status_code == 201, results[0].text
    body = results[0].json()
    assert body['voice_stale'] is True
    assert body['approval_state'] == 'pending_approval'
    run_id = body['run_id']
    assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 409
    assert client.post('/api/runs/%s/export' % run_id, json={}).status_code == 422


def test_edit_during_campaign_marks_all_days_stale(client):
    voice = _create_voice(client, ('harbor',), 'Synthetic voice')
    release = threading.Event()
    entered = threading.Event()
    edited = {'done': False}
    original = run.run_pipeline

    def gated(*args, **kwargs):
        def gate(stage):
            if stage == 'maker_draft_v1' and not edited['done']:
                entered.set()
                assert release.wait(timeout=30.0)
        kwargs['stage_gate'] = gate
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    results = []
    errors = []

    def requester():
        try:
            results.append(client.post('/api/campaigns', json={
                'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]}))
        except Exception as error:
            errors.append(error)

    with patch('launchcrew.run.run_pipeline', side_effect=gated):
        thread = threading.Thread(target=requester)
        thread.start()
        assert entered.wait(timeout=30.0)
        _edit_voice(client, voice['id'], ('harbor', 'zebra'), 'Synthetic voice edited')
        edited['done'] = True
        release.set()
        thread.join(timeout=60.0)
    assert errors == []
    assert len(results) == 1
    assert results[0].status_code == 201, results[0].text
    campaign = results[0].json()
    assert len(campaign['days']) == 7
    run_ids = [day['run_id'] for day in campaign['days']]
    assert len(set(run_ids)) == 7
    for day in campaign['days']:
        receipt = client.get('/api/runs/%s' % day['run_id']).json()
        assert receipt['voice_stale'] is True
        assert receipt['approval_state'] == 'pending_approval'
        assert receipt['voice_profile']['id'] == voice['id']
        assert any(event.get('step') == 'voice_invalidated'
                   for event in receipt['audit']['event_log'])
        assert client.post('/api/campaigns/%s/days/%d/approve' % (campaign['id'], day['day']), json={}).status_code == 409
        assert client.post('/api/campaigns/%s/days/%d/export' % (campaign['id'], day['day']), json={}).status_code == 422


def test_campaign_failure_preserves_seven_days_and_individual_approval(client):
    voice = _create_voice(client, ('harbor',), 'Synthetic voice')
    original = run.run_pipeline
    calls = {'count': 0}

    def flaky(*args, **kwargs):
        calls['count'] += 1
        if calls['count'] == 3:
            raise RuntimeError('Synthetic day failure')
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=flaky):
        response = client.post('/api/campaigns', json={
            'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]})
    assert response.status_code == 201, response.text
    campaign = response.json()
    assert len(campaign['days']) == 7
    assert [day['day'] for day in campaign['days']] == [1, 2, 3, 4, 5, 6, 7]
    run_ids = [day['run_id'] for day in campaign['days']]
    assert len(set(run_ids)) == 7
    failed = [day for day in campaign['days'] if day['status'] == 'failed']
    completed = [day for day in campaign['days'] if day['status'] == 'completed']
    assert len(failed) == 1
    assert failed[0]['day'] == 3
    assert len(completed) == 6
    assert client.post('/api/campaigns/%s/days/3/approve' % campaign['id'], json={}).status_code == 422
    assert client.post('/api/campaigns/%s/days/3/export' % campaign['id'], json={}).status_code == 422
    for day in completed:
        assert client.post('/api/campaigns/%s/days/%d/approve' % (campaign['id'], day['day']), json={}).status_code == 200
        assert client.post('/api/campaigns/%s/days/%d/export' % (campaign['id'], day['day']), json={}).status_code == 200


def test_no_edit_campaign_days_individually_approvable(client):
    voice = _create_voice(client, ('harbor',), 'Synthetic voice')
    response = client.post('/api/campaigns', json={
        'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]})
    assert response.status_code == 201, response.text
    campaign = response.json()
    assert len(campaign['days']) == 7
    for day in campaign['days']:
        receipt = client.get('/api/runs/%s' % day['run_id']).json()
        assert receipt.get('voice_stale') is not True
        assert receipt['voice_profile']['id'] == voice['id']
    assert client.post('/api/campaigns/%s/days/1/approve' % campaign['id'], json={}).status_code == 200
    assert client.post('/api/campaigns/%s/days/1/export' % campaign['id'], json={}).status_code == 200
    second = client.get('/api/runs/%s' % campaign['days'][1]['run_id']).json()
    assert second['approval_state'] == 'pending_approval'
