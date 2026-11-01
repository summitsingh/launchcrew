"""SC3 analytics pull on Postgres.

Deterministic fixtures only, no live model calls, no real provider
calls (the platform adapter is deterministic). Only verified
deliveries may pull provider metrics; every canonical metric stores
either an integer or the exact string "not reported", never a fake
0; pulls sync into the run outcome log with source and fetch time;
manual and scheduled refresh both populate calendar outcome badges.
"""
from unittest.mock import patch

from fastapi.responses import Response

from backend import auth
from launchcrew import analytics_pull as analytics_mod
from launchcrew import run as run_mod

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
CHANNELS = ('x', 'linkedin', 'instagram', 'email', 'facebook', 'tiktok', 'shopify')
LIVE_URL = 'https://example.com/posts/launch-1'
ACTOR = 'google:analytics-user-one'


import pytest


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    pipeline = run_mod.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return pipeline(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def sign_in(client, monkeypatch, actor=ACTOR):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    response = Response()
    auth.save_session({'actor': actor}, response)
    opaque = response.headers['set-cookie'].split(';')[0].split('=', 1)[1]
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque)


def new_run(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def current_revision(client, run_id):
    return client.get(f'/api/runs/{run_id}').json().get('revision', 0)


def approve_export(client, run_id):
    revision = current_revision(client, run_id)
    approved = client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': revision})
    assert approved.status_code == 200, approved.text
    exported = client.post(f'/api/runs/{run_id}/export', json={'expected_revision': revision})
    assert exported.status_code == 200, exported.text
    return exported.json()


def new_slot(client, run_id):
    response = client.post('/api/calendar/slots',
                           json={'slot_date': '2026-11-03', 'slot_type': 'feed_post',
                                 'pillar': 'product', 'format': 'feed_post',
                                 'run_id': run_id})
    assert response.status_code == 201, response.text
    return response.json()


def ready_slot(client, run_id, channel):
    slot = new_slot(client, run_id)
    patched = client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                           json={'selected_channels': [channel]})
    assert patched.status_code == 200, patched.text
    approved = client.post(f'/api/calendar/slots/{slot["id"]}/approve-channels',
                           json={'channels': [channel],
                                 'expected_revision': current_revision(client, run_id)})
    assert approved.status_code == 200, approved.text
    return approved.json()


def valid_channel(client, run_id):
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    return next(channel for channel in CHANNELS
                if bundle[channel]['content_valid'] and bundle[channel]['text'])


def preferred_channel(client, run_id):
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    for channel in ('instagram', 'x'):
        entry = bundle.get(channel) or {}
        if entry.get('content_valid') and entry.get('text'):
            return channel
    return valid_channel(client, run_id)


def approved_text(client, run_id, channel):
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    entry = bundle[channel]
    return entry['text'], entry.get('subject') or ''


def verify_delivery(client, slot_id, channel, run_id):
    text, subject = approved_text(client, run_id, channel)
    body = {'live_url': LIVE_URL, 'live_text': text, 'verify_now': True}
    if subject:
        body['live_subject'] = subject
    response = client.post(f'/api/calendar/slots/{slot_id}/deliveries/{channel}/mark-posted',
                           json=body)
    assert response.status_code == 200, response.text
    assert response.json()['delivery_state'] == 'verified'
    return response.json()


def expected_metrics(channel, provided):
    supported = set(analytics_mod.supported_metrics_for(channel))
    return {metric: (provided[metric] if metric in supported and metric in provided
                     else 'not reported')
            for metric in analytics_mod.CANONICAL_METRICS}


def test_verified_post_refreshes_metrics_and_syncs_outcome_log(client, monkeypatch):
    sign_in(client, monkeypatch)
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = preferred_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    verify_delivery(client, slot['id'], channel, run_id)
    provided = {'reach': 1240, 'likes': 88, 'comments': 12}
    response = client.post(
        f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/analytics/refresh',
        json={'provider_metrics': provided, 'source_label': channel + '_graph_api'})
    assert response.status_code == 200, response.text
    pull = response.json()
    assert pull['id'].startswith('apull_')
    assert pull['slot_id'] == slot['id']
    assert pull['channel'] == channel
    assert pull['refresh_mode'] == 'manual'
    assert pull['source_label'] == channel + '_graph_api'
    assert pull['fetched_at']
    assert pull['metrics'] == expected_metrics(channel, provided)
    for metric in ('reach', 'likes', 'comments'):
        assert pull['metrics'][metric] == provided[metric]
    assert pull['reported_metrics'] == ['reach', 'likes', 'comments']
    assert sorted(pull['unreported_metrics']) == ['clicks', 'shares']
    assert pull['run_id'] == run_id
    assert pull['outcome_id'] and pull['outcome_id'].startswith('out_')
    listed = client.get('/api/analytics/pulls',
                        params={'slot_id': slot['id'], 'channel': channel}).json()
    assert [entry['id'] for entry in listed] == [pull['id']]
    badge = client.get(f'/api/calendar/slots/{slot["id"]}/analytics').json()
    assert badge['slot_id'] == slot['id']
    assert badge['has_outcomes'] is True
    assert len(badge['channel_badges']) == 1
    entry = badge['channel_badges'][0]
    assert entry['channel'] == channel
    assert entry['source_label'] == channel + '_graph_api'
    assert entry['fetched_at'] == pull['fetched_at']
    assert entry['refresh_mode'] == 'manual'
    assert entry['metrics'] == pull['metrics']
    assert 'not reported' in badge['summary_text']
    assert channel in badge['summary_text']
    outcomes = client.get(f'/api/runs/{run_id}/outcomes').json()
    synced = [row for row in outcomes if row['id'] == pull['outcome_id']]
    assert len(synced) == 1
    note = synced[0]['note']
    assert channel + '_graph_api' in note
    assert pull['fetched_at'] in note
    assert 'not reported' in note


def test_unsupported_or_omitted_metric_is_not_reported_never_zero(client, monkeypatch):
    sign_in(client, monkeypatch)
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = preferred_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    verify_delivery(client, slot['id'], channel, run_id)
    provided = {'reach': 500, 'likes': 25, 'comments': 4, 'clicks': 999, 'shares': 7}
    response = client.post(
        f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/analytics/refresh',
        json={'provider_metrics': provided})
    assert response.status_code == 200, response.text
    pull = response.json()
    assert pull['metrics'] == expected_metrics(channel, provided)
    if channel == 'instagram':
        assert pull['metrics']['clicks'] == 'not reported'
        assert pull['metrics']['shares'] == 7
    for value in pull['metrics'].values():
        assert value == 'not reported' or (type(value) is int and value >= 0)
    adapter = client.post(
        f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/analytics/refresh',
        json={})
    assert adapter.status_code == 200, adapter.text
    adapted = adapter.json()
    assert adapted['metrics'] == expected_metrics(channel, analytics_mod.adapter_metrics(channel))
    for metric in analytics_mod.CANONICAL_METRICS:
        if metric in analytics_mod.supported_metrics_for(channel):
            assert type(adapted['metrics'][metric]) is int
        else:
            assert adapted['metrics'][metric] == 'not reported'
    assert adapted['id'] == pull['id']
    assert adapted['outcome_id'] == pull['outcome_id']
    outcomes = client.get(f'/api/runs/{run_id}/outcomes').json()
    assert len([row for row in outcomes if row['id'] == pull['outcome_id']]) == 1


def test_unverified_delivery_refuses_analytics_pull(client, monkeypatch):
    sign_in(client, monkeypatch)
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = preferred_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    missing = client.post(
        f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/analytics/refresh',
        json={'provider_metrics': {'reach': 10, 'likes': 1, 'comments': 0}})
    assert missing.status_code == 409, missing.text
    assert 'delivery_not_verified' in missing.text
    posted = client.post(f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/mark-posted',
                         json={'live_url': LIVE_URL, 'verify_now': False})
    assert posted.status_code == 200, posted.text
    assert posted.json()['delivery_state'] == 'posted'
    refused = client.post(
        f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/analytics/refresh',
        json={'provider_metrics': {'reach': 10, 'likes': 1, 'comments': 0}})
    assert refused.status_code == 409, refused.text
    assert 'delivery_not_verified' in refused.text
    assert client.get('/api/analytics/pulls').json() == []
    badge = client.get(f'/api/calendar/slots/{slot["id"]}/analytics').json()
    assert badge == {'slot_id': slot['id'], 'has_outcomes': False,
                     'channel_badges': [], 'summary_text': ''}


def test_manual_and_scheduled_refresh_populate_outcome_badges(client, monkeypatch):
    sign_in(client, monkeypatch)
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = preferred_channel(client, run_id)
    slot_manual = ready_slot(client, run_id, channel)
    slot_scheduled = ready_slot(client, run_id, channel)
    slot_pending = ready_slot(client, run_id, channel)
    verify_delivery(client, slot_manual['id'], channel, run_id)
    verify_delivery(client, slot_scheduled['id'], channel, run_id)
    pending_posted = client.post(
        f'/api/calendar/slots/{slot_pending["id"]}/deliveries/{channel}/mark-posted',
        json={'live_url': LIVE_URL, 'verify_now': False})
    assert pending_posted.status_code == 200, pending_posted.text
    manual = client.post(
        f'/api/calendar/slots/{slot_manual["id"]}/deliveries/{channel}/analytics/refresh',
        json={'provider_metrics': {'reach': 300, 'likes': 11, 'comments': 2}})
    assert manual.status_code == 200, manual.text
    assert manual.json()['refresh_mode'] == 'manual'
    scheduled = client.post('/api/analytics/refresh-scheduled',
                            json={'slot_ids': [slot_scheduled['id'], slot_pending['id']]})
    assert scheduled.status_code == 200, scheduled.text
    body = scheduled.json()
    assert [entry['slot_id'] for entry in body['refreshed']] == [slot_scheduled['id']]
    assert body['refreshed'][0]['refresh_mode'] == 'scheduled'
    assert body['skipped_unverified'] == [slot_pending['id'] + ':' + channel]
    kept = client.get('/api/analytics/pulls',
                      params={'slot_id': slot_manual['id']}).json()
    assert len(kept) == 1 and kept[0]['refresh_mode'] == 'manual'
    full = client.post('/api/analytics/refresh-scheduled', json={})
    assert full.status_code == 200, full.text
    assert sorted(entry['slot_id'] for entry in full.json()['refreshed']) == sorted(
        [slot_manual['id'], slot_scheduled['id']])
    assert slot_pending['id'] + ':' + channel in full.json()['skipped_unverified']
    slots = client.get('/api/calendar/slots',
                       params={'start_date': '2026-11-01',
                               'end_date': '2026-11-30'}).json()
    badges = {slot['id']: slot.get('outcome_badge') for slot in slots}
    for slot_id in (slot_manual['id'], slot_scheduled['id']):
        badge = badges[slot_id]
        assert badge and badge['has_outcomes'] is True
        assert badge['channel_badges'][0]['metrics'] == expected_metrics(
            channel, analytics_mod.adapter_metrics(channel))
        assert 'not reported' in badge['summary_text'] or channel in badge['summary_text']
    pending_badge = client.get(f'/api/calendar/slots/{slot_pending["id"]}/analytics').json()
    assert pending_badge['has_outcomes'] is False
