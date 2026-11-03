"""Instagram live selection on Postgres: gated real path, labeled fallback.

Deterministic fixtures only. The Graph API is patched at the transport
seam; the fixture token is synthetic and revoked by construction. No
real network on any path.
"""
import io
import json
from unittest.mock import patch

from launchcrew import instagram_publish as ig_mod

TOKEN = 'fixture-token-not-real'
NUMERIC_ID = '123456789'
MEDIA = 'https://example.invalid/shot.jpg'
IDEA = 'Instagram live selection probe'


def _response(payload):
    return io.BytesIO(json.dumps(payload).encode())


def _live_opener(request, timeout=None):
    if request.full_url.endswith('/media'):
        return _response({'id': 'creation_live_1'})
    if 'fields=permalink' in request.full_url:
        return _response({'id': 'media_live_1',
                          'permalink': 'https://www.instagram.com/p/DbLiveOpener1/'})
    return _response({'id': 'media_live_1'})


def new_run(client):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    return response.json()


def current_revision(client, run_id):
    return client.get(f'/api/runs/{run_id}').json().get('revision', 0)


def approve(client, run_id):
    response = client.post(f'/api/runs/{run_id}/approve',
                           json={'expected_revision': current_revision(client, run_id)})
    assert response.status_code == 200, response.text


def ready_instagram_slot(client, run_id):
    slot = client.post('/api/calendar/slots',
                       json={'slot_date': '2026-11-03', 'slot_type': 'feed_post',
                             'pillar': 'product', 'format': 'feed_post',
                             'run_id': run_id}).json()
    patched = client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                           json={'selected_channels': ['instagram']})
    assert patched.status_code == 200, patched.text
    approved = client.post(f'/api/calendar/slots/{slot["id"]}/approve-channels',
                           json={'channels': ['instagram'],
                                 'expected_revision': current_revision(client, run_id)})
    assert approved.status_code == 200, approved.text
    marked = client.post(f'/api/calendar/slots/{slot["id"]}/mark-ready')
    assert marked.status_code == 200, marked.text
    return marked.json()


def connect_instagram(client, external_id, token=TOKEN):
    body = {'code': token, 'account_type': 'brand', 'handle': '@brand-ig',
            'account_name': 'Brand ig', 'external_account_id': external_id,
            'scopes': ['brand_publish', 'brand_capabilities_read']}
    response = client.post('/api/social/connections/instagram/callback', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def execute(client, slot_id, media_url=None):
    body = {}
    if media_url is not None:
        body['media_url'] = media_url
    return client.post(f'/api/publish/slots/{slot_id}/execute', json=body)


def test_live_instagram_posts_real_id_when_fully_enabled(client, monkeypatch):
    monkeypatch.setenv('LAUNCHCREW_INSTAGRAM_LIVE', 'true')
    receipt = new_run(client)
    approve(client, receipt['run_id'])
    slot = ready_instagram_slot(client, receipt['run_id'])
    connect_instagram(client, NUMERIC_ID)
    with patch.object(ig_mod, 'urlopen', side_effect=_live_opener) as transport:
        done = execute(client, slot['id'], MEDIA)
    assert done.status_code == 200, done.text
    assert done.json()['executed'] is True
    execution = done.json()['executions'][0]
    assert execution['status'] == 'posted'
    assert execution['platform_post_id'] == 'media_live_1'
    assert execution['attempts'][-1]['simulated'] is False
    assert execution['live_url'] == 'https://www.instagram.com/p/DbLiveOpener1/'
    assert transport.call_count == 3


def test_live_instagram_records_permalink_as_live_url(client, monkeypatch):
    monkeypatch.setenv('LAUNCHCREW_INSTAGRAM_LIVE', 'true')
    receipt = new_run(client)
    approve(client, receipt['run_id'])
    slot = ready_instagram_slot(client, receipt['run_id'])
    connect_instagram(client, NUMERIC_ID)
    link = 'https://www.instagram.com/p/DbFakeLink1/'

    def opener(request, timeout=None):
        if request.full_url.endswith('/media'):
            return _response({'id': 'creation_live_9'})
        if 'fields=permalink' in request.full_url:
            return _response({'id': 'media_live_9', 'permalink': link})
        return _response({'id': 'media_live_9'})

    with patch.object(ig_mod, 'urlopen', side_effect=opener):
        done = execute(client, slot['id'], MEDIA)
    assert done.status_code == 200, done.text
    execution = done.json()['executions'][0]
    assert execution['status'] == 'posted'
    assert execution['platform_post_id'] == 'media_live_9'
    assert execution['live_url'] == link


def test_live_instagram_permalink_failure_still_posts(client, monkeypatch):
    monkeypatch.setenv('LAUNCHCREW_INSTAGRAM_LIVE', 'true')
    receipt = new_run(client)
    approve(client, receipt['run_id'])
    slot = ready_instagram_slot(client, receipt['run_id'])
    connect_instagram(client, NUMERIC_ID)

    def opener(request, timeout=None):
        if request.full_url.endswith('/media'):
            return _response({'id': 'creation_live_7'})
        if 'fields=permalink' in request.full_url:
            return _response({'error': {'message': 'transient read failure',
                                        'type': 'OAuthException', 'code': 2}})
        return _response({'id': 'media_live_7'})

    with patch.object(ig_mod, 'urlopen', side_effect=opener):
        done = execute(client, slot['id'], MEDIA)
    assert done.status_code == 200, done.text
    execution = done.json()['executions'][0]
    assert execution['status'] == 'posted'
    assert execution['platform_post_id'] == 'media_live_7'
    assert execution['live_url'] is None


def test_flag_off_stays_simulated(client, monkeypatch):
    monkeypatch.delenv('LAUNCHCREW_INSTAGRAM_LIVE', raising=False)
    receipt = new_run(client)
    approve(client, receipt['run_id'])
    slot = ready_instagram_slot(client, receipt['run_id'])
    connect_instagram(client, NUMERIC_ID)
    with patch.object(ig_mod, 'urlopen',
                      side_effect=AssertionError('zero live HTTP expected')):
        done = execute(client, slot['id'], MEDIA)
    assert done.status_code == 200, done.text
    execution = done.json()['executions'][0]
    assert execution['status'] == 'posted'
    assert execution['attempts'][-1]['simulated'] is True


def test_missing_media_url_stays_simulated(client, monkeypatch):
    monkeypatch.setenv('LAUNCHCREW_INSTAGRAM_LIVE', 'true')
    receipt = new_run(client)
    approve(client, receipt['run_id'])
    slot = ready_instagram_slot(client, receipt['run_id'])
    connect_instagram(client, NUMERIC_ID)
    with patch.object(ig_mod, 'urlopen',
                      side_effect=AssertionError('zero live HTTP expected')):
        done = execute(client, slot['id'])
    assert done.status_code == 200, done.text
    assert done.json()['executions'][0]['attempts'][-1]['simulated'] is True


def test_live_provider_error_records_failed_attempt(client, monkeypatch):
    monkeypatch.setenv('LAUNCHCREW_INSTAGRAM_LIVE', 'true')
    receipt = new_run(client)
    approve(client, receipt['run_id'])
    slot = ready_instagram_slot(client, receipt['run_id'])
    connect_instagram(client, NUMERIC_ID)

    def refused(request, timeout=None):
        return _response({'error': {'message': 'Invalid OAuth access token',
                                    'type': 'OAuthException', 'code': 190}})

    with patch.object(ig_mod, 'urlopen', side_effect=refused):
        done = execute(client, slot['id'], MEDIA)
    assert done.status_code == 200, done.text
    execution = done.json()['executions'][0]
    assert execution['status'] == 'failed'
    assert 'Invalid OAuth' in (execution['last_error'] or '')
    assert TOKEN not in (execution['last_error'] or '')
