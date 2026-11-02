"""SC2 autonomous Ready-slot publish executor on Postgres.

Deterministic fixtures only, no live model calls, no real platform
calls. Covers the autonomous executor contract: a Ready slot posts at
its scheduled time with no per-post tap and hands off to S5 as posted
(never verified); unapproved slots are refused with no publish call;
editing the pack after approval drops the slot out of Ready and the
executor skips it; a failing publish retries automatically at most
twice under one idempotency key with no duplicate; re-triggering a
posted slot returns the existing result; the kill switch pauses all
execution while leaving slots and packs untouched.
"""
from unittest.mock import patch

import pytest

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
CONNECTABLE = ('x', 'linkedin', 'instagram', 'facebook', 'tiktok')
DUE_AS_OF = '2026-11-03T09:00:00Z'


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    from launchcrew import run as run_mod
    pipeline = run_mod.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return pipeline(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def new_run(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def current_revision(client, run_id):
    return client.get(f'/api/runs/{run_id}').json().get('revision', 0)


def approve(client, run_id):
    response = client.post(f'/api/runs/{run_id}/approve',
                           json={'expected_revision': current_revision(client, run_id)})
    assert response.status_code == 200, response.text
    return response.json()


def new_slot(client, run_id, slot_type='feed_post'):
    body = {'slot_date': '2026-11-03', 'slot_type': slot_type,
            'pillar': 'product', 'format': slot_type}
    if run_id is not None:
        body['run_id'] = run_id
    response = client.post('/api/calendar/slots', json=body)
    assert response.status_code == 201, response.text
    return response.json()


def usable_channel(client, run_id):
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    for channel in CONNECTABLE:
        entry = bundle.get(channel) or {}
        if entry.get('content_valid') and entry.get('text'):
            return channel
    raise AssertionError('no connectable channel has a valid variant')


def ready_slot(client, run_id, channel):
    slot = new_slot(client, run_id)
    patched = client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                           json={'selected_channels': [channel]})
    assert patched.status_code == 200, patched.text
    approved = client.post(f'/api/calendar/slots/{slot["id"]}/approve-channels',
                           json={'channels': [channel],
                                 'expected_revision': current_revision(client, run_id)})
    assert approved.status_code == 200, approved.text
    marked = client.post(f'/api/calendar/slots/{slot["id"]}/mark-ready')
    assert marked.status_code == 200, marked.text
    assert marked.json()['schedule_state'] == 'ready'
    return marked.json()


def connect_brand(client, platform, token='test-transport-token'):
    body = {'code': token, 'account_type': 'brand',
            'handle': '@brand-%s' % platform,
            'account_name': 'Brand %s' % platform,
            'scopes': ['brand_publish', 'brand_capabilities_read']}
    response = client.post(f'/api/social/connections/{platform}/callback', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def executions_for(status_body, slot_id, channel):
    return [entry for entry in status_body.get('executions', [])
            if entry['slot_id'] == slot_id and entry['channel'] == channel]


def test_ready_slot_posts_at_scheduled_time_and_hands_off_to_s5(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    channel = usable_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    connect_brand(client, channel)
    tick = client.post('/api/publish/execute-due', json={'as_of': DUE_AS_OF})
    assert tick.status_code == 200, tick.text
    body = tick.json()
    assert slot['id'] in body['executed_slots']
    status = client.get('/api/publish/status').json()
    rows = executions_for(status, slot['id'], channel)
    assert len(rows) == 1
    execution = rows[0]
    assert execution['status'] == 'posted'
    assert execution['platform_post_id']
    assert execution['live_url']
    assert execution['live_url'].startswith('https://')
    assert execution['attempt_count'] == 1
    assert len(execution['attempts']) == 1
    assert execution['attempts'][0]['attempt_number'] == 1
    assert execution['attempts'][0]['backoff_seconds'] == 0
    assert execution['attempts'][0]['idempotency_key'] == execution['idempotency_key']
    assert execution['attempts'][0]['outcome'] == 'posted'
    deliveries = client.get(f'/api/calendar/slots/{slot["id"]}/deliveries')
    assert deliveries.status_code == 200, deliveries.text
    assert len(deliveries.json()) == 1
    delivery = deliveries.json()[0]
    assert delivery['delivery_state'] == 'posted'
    assert delivery['live_url'] == execution['live_url']
    reread = client.get('/api/calendar/slots?start_date=2026-11-01&end_date=2026-11-30')
    assert reread.status_code == 200, reread.text
    assert reread.json()[0]['status'] != 'verified'
    board = client.get('/api/calendar/verification-board',
                       params={'slot_id': slot['id']})
    assert board.status_code == 200, board.text
    assert board.json()[0]['delivery_state'] == 'posted'


def test_unapproved_slot_refused_with_no_publish_call(client, monkeypatch):
    from launchcrew import publish_executor as executor_mod
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('transport must never run for unapproved content')

    monkeypatch.setattr(executor_mod, 'default_transport', forbidden)
    receipt = new_run(client)
    slot = new_slot(client, receipt['run_id'])
    refused = client.post(f'/api/publish/slots/{slot["id"]}/execute', json={})
    assert refused.status_code == 409, refused.text
    assert 'not Ready' in refused.text
    tick = client.post('/api/publish/execute-due', json={'as_of': DUE_AS_OF})
    assert tick.status_code == 200, tick.text
    assert tick.json()['executed_slots'] == []
    assert calls == []
    status = client.get('/api/publish/status').json()
    assert executions_for(status, slot['id'], 'instagram') == []


def test_edit_after_approval_drops_ready_and_execution_skips(client, test_engine, monkeypatch):
    from sqlalchemy import text
    from launchcrew import publish_executor as executor_mod
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('transport must never run after an edit drops Ready')

    monkeypatch.setattr(executor_mod, 'default_transport', forbidden)
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    channel = usable_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    connect_brand(client, channel)
    revised = client.post(f'/api/runs/{run_id}/revise',
                          json={'post': 'Vegan leather wallet. Designed in Texas.',
                                'email': 'For Austin commuters. $49.',
                                'base_revision': current_revision(client, run_id)})
    assert revised.status_code == 200, revised.text
    reread = client.get('/api/calendar/slots?start_date=2026-11-01&end_date=2026-11-30')
    assert reread.status_code == 200, reread.text
    assert reread.json()[0]['schedule_state'] == 'needs_approval'
    tick = client.post('/api/publish/execute-due', json={'as_of': DUE_AS_OF})
    assert tick.status_code == 200, tick.text
    assert slot['id'] not in tick.json()['executed_slots']
    assert calls == []
    with test_engine.begin() as connection:
        connection.execute(text("UPDATE calendar_slots SET schedule_state='ready', updated_at=now()"
                                " WHERE id=:id"),
                           {'id': slot['id']})
    retick = client.post('/api/publish/execute-due', json={'as_of': DUE_AS_OF})
    assert retick.status_code == 200, retick.text
    assert slot['id'] not in retick.json()['executed_slots']
    assert calls == []
    status = client.get('/api/publish/status').json()
    rows = executions_for(status, slot['id'], channel)
    assert len(rows) == 1
    assert rows[0]['status'] == 'skipped_needs_approval'
    assert rows[0]['last_error']
    assert rows[0]['platform_post_id'] is None
    reread = client.get('/api/calendar/slots?start_date=2026-11-01&end_date=2026-11-30')
    assert reread.status_code == 200, reread.text
    assert reread.json()[0]['schedule_state'] == 'needs_approval'


def test_failing_publish_retries_twice_then_fails_with_reason(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    channel = usable_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    connect_brand(client, channel, token='revoked_test_token')
    tick = client.post('/api/publish/execute-due', json={'as_of': DUE_AS_OF})
    assert tick.status_code == 200, tick.text
    assert slot['id'] not in tick.json()['executed_slots']
    status = client.get('/api/publish/status').json()
    rows = executions_for(status, slot['id'], channel)
    assert len(rows) == 1
    execution = rows[0]
    assert execution['status'] == 'failed'
    assert execution['attempt_count'] == 3
    assert len(execution['attempts']) == 3
    assert [attempt['attempt_number'] for attempt in execution['attempts']] == [1, 2, 3]
    keys = {attempt['idempotency_key'] for attempt in execution['attempts']}
    assert keys == {execution['idempotency_key']}
    assert [attempt['backoff_seconds'] for attempt in execution['attempts']] == [0, 2, 5]
    assert all(attempt['outcome'] == 'failed' for attempt in execution['attempts'])
    assert 'revoked' in (execution['last_error'] or '').lower()
    assert execution['platform_post_id'] is None
    deliveries = client.get(f'/api/calendar/slots/{slot["id"]}/deliveries')
    assert deliveries.status_code == 200, deliveries.text
    assert len(deliveries.json()) == 1
    assert deliveries.json()[0]['delivery_state'] == 'failed'
    assert 'revoked' in (deliveries.json()[0]['failure_reason'] or '').lower()


def test_idempotency_prevents_duplicate_posts(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    channel = usable_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    connect_brand(client, channel)
    first = client.post(f'/api/publish/slots/{slot["id"]}/execute', json={})
    assert first.status_code == 200, first.text
    assert first.json()['executed'] is True
    posted_id = first.json()['executions'][0]['platform_post_id']
    attempts_before = client.get(f'/api/calendar/slots/{slot["id"]}/deliveries').json()
    second = client.post(f'/api/publish/slots/{slot["id"]}/execute', json={})
    assert second.status_code == 200, second.text
    assert second.json()['executed'] is True
    assert second.json()['executions'][0]['platform_post_id'] == posted_id
    attempts_after = client.get(f'/api/calendar/slots/{slot["id"]}/deliveries').json()
    assert attempts_after == attempts_before
    status = client.get('/api/publish/status').json()
    rows = executions_for(status, slot['id'], channel)
    assert len(rows) == 1
    assert rows[0]['attempt_count'] == 1


def test_owner_retry_posts_after_reconnect(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    channel = usable_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    connect_brand(client, channel, token='revoked_test_token')
    failed = client.post(f'/api/publish/slots/{slot["id"]}/execute', json={})
    assert failed.status_code == 200, failed.text
    assert failed.json()['executions'][0]['status'] == 'failed'
    connect_brand(client, channel, token='good-token-after-reconnect')
    retried = client.post(f'/api/publish/slots/{slot["id"]}/retry', json={})
    assert retried.status_code == 200, retried.text
    assert retried.json()['executed'] is True
    execution = retried.json()['executions'][0]
    assert execution['status'] == 'posted'
    assert execution['platform_post_id']
    assert execution['attempt_count'] == 4
    assert execution['attempts'][-1]['outcome'] == 'posted'
    assert execution['attempts'][-1]['simulated'] is True


def test_kill_switch_pauses_leaving_slots_and_packs_untouched(client, monkeypatch):
    from launchcrew import publish_executor as executor_mod
    calls = []
    gate = {'blocked': True}
    real_transport = executor_mod.default_transport

    def gated(*args, **kwargs):
        if gate['blocked']:
            calls.append((args, kwargs))
            raise AssertionError('transport must never run while paused')
        return real_transport(*args, **kwargs)

    monkeypatch.setattr(executor_mod, 'default_transport', gated)
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    channel = usable_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    connect_brand(client, channel)
    before = client.get(f'/api/runs/{run_id}').json()
    paused = client.post('/api/publish/kill-switch',
                         json={'paused': True, 'reason': 'owner hold'})
    assert paused.status_code == 200, paused.text
    assert paused.json()['paused'] is True
    assert paused.json()['reason'] == 'owner hold'
    tick = client.post('/api/publish/execute-due', json={'as_of': DUE_AS_OF})
    assert tick.status_code == 200, tick.text
    assert tick.json()['paused'] is True
    assert tick.json()['executed_slots'] == []
    assert calls == []
    status = client.get('/api/publish/status').json()
    assert status['kill_switch']['paused'] is True
    rows = executions_for(status, slot['id'], channel)
    assert len(rows) == 1
    assert rows[0]['status'] == 'paused_by_kill_switch'
    reread = client.get('/api/calendar/slots?start_date=2026-11-01&end_date=2026-11-30')
    assert reread.status_code == 200, reread.text
    assert reread.json()[0]['schedule_state'] == 'ready'
    after = client.get(f'/api/runs/{run_id}').json()
    assert after['approval_state'] == before['approval_state'] == 'approved_for_export'
    assert after['revision'] == before['revision']
    deliveries = client.get(f'/api/calendar/slots/{slot["id"]}/deliveries')
    assert deliveries.status_code == 200, deliveries.text
    assert deliveries.json() == []
    resumed = client.post('/api/publish/kill-switch', json={'paused': False})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()['paused'] is False
    gate['blocked'] = False
    retick = client.post('/api/publish/execute-due', json={'as_of': DUE_AS_OF})
    assert retick.status_code == 200, retick.text
    assert slot['id'] in retick.json()['executed_slots']
