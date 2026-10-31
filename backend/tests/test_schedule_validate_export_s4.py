"""S4 schedule slots, validate gate, and schedule export on Postgres.

Deterministic fixtures only, no live model calls, no credentials.
Planning only: scheduling never publishes. The validate gate has
zero overrides: a slot is marked Ready only when its pack is
approved, its format check passes, and every selected channel
variant is approved. The exported schedule JSON lists only Ready
slots and names excluded slots with their exact reasons.
"""
from unittest.mock import patch

import pytest

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
CHANNELS = ('x', 'linkedin', 'instagram', 'email', 'facebook', 'tiktok', 'shopify')


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


def approve(client, run_id, revision=0):
    response = client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': revision})
    assert response.status_code == 200, response.text
    return response.json()


def new_slot(client, run_id=None, slot_type='feed_post'):
    body = {'slot_date': '2026-11-03', 'slot_type': slot_type,
            'pillar': 'product', 'format': slot_type}
    if run_id is not None:
        body['run_id'] = run_id
    response = client.post('/api/calendar/slots', json=body)
    assert response.status_code == 201, response.text
    return response.json()


def valid_channel(client, run_id):
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    return next(c for c in CHANNELS
                if bundle[c]['content_valid'] and bundle[c]['text'])


def test_daily_defaults_and_per_slot_time_editing(client):
    defaults = client.get('/api/calendar/schedule-defaults')
    assert defaults.status_code == 200, defaults.text
    assert defaults.json()['defaults'] == {'feed_post': '09:00', 'story': '13:00', 'reel': '18:00'}
    updated = client.put('/api/calendar/schedule-defaults',
                         json={'defaults': {'feed_post': '08:30', 'story': '13:00', 'reel': '18:00'}})
    assert updated.status_code == 200, updated.text
    assert updated.json()['defaults']['feed_post'] == '08:30'
    assert client.put('/api/calendar/schedule-defaults',
                      json={'defaults': {'feed_post': 'nope'}}).status_code == 422
    assert client.put('/api/calendar/schedule-defaults',
                      json={'defaults': {'broadcast': '09:00'}}).status_code == 422
    assert client.put('/api/calendar/schedule-defaults', json={'defaults': {}}).status_code == 422
    slot = new_slot(client)
    assert slot['planned_time'] == '08:30'
    assert slot['schedule_state'] == 'draft'
    assert slot['selected_channels'] == []
    edited = client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                          json={'planned_time': '10:15'})
    assert edited.status_code == 200, edited.text
    assert edited.json()['planned_time'] == '10:15'
    assert client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                        json={'planned_time': '25:00'}).status_code == 422
    moved = client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                         json={'planned_date': '2026-11-05'})
    assert moved.status_code == 200, moved.text
    assert moved.json()['slot_date'] == '2026-11-05'
    assert client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                        json={'planned_date': 'not-a-date'}).status_code == 422


def test_unapproved_slot_cannot_be_marked_ready_and_names_conditions(client):
    receipt = new_run(client)
    slot = new_slot(client, receipt['run_id'])
    checked = client.get(f'/api/calendar/slots/{slot["id"]}/validate-ready')
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body['ready_eligible'] is False
    assert body['checks'] == {'pack_approved': False, 'format_passed': True,
                              'variants_approved': False}
    assert 'pack_not_approved' in body['failing_conditions']
    assert 'unapproved_channel_variants' in body['failing_conditions']
    refused = client.post(f'/api/calendar/slots/{slot["id"]}/mark-ready')
    assert refused.status_code == 409, refused.text
    detail = refused.json()['detail']
    assert 'pack_not_approved' in detail['failing_conditions']
    assert 'unapproved_channel_variants' in detail['failing_conditions']
    reread = client.get('/api/calendar/slots?start_date=2026-11-01&end_date=2026-11-30')
    assert reread.status_code == 200, reread.text
    assert reread.json()[0]['schedule_state'] == 'draft'


def test_format_failure_blocks_ready_with_exact_reason(client):
    receipt = new_run(client, format_spec={'format_kind': 'feed_carousel',
                                           'frame_count': 2, 'aspect_ratio': '4:5'})
    assert receipt.get('format_check', {}).get('passed') is False
    run_id = receipt['run_id']
    blocked = client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': 0})
    assert blocked.status_code == 422, blocked.text
    slot = new_slot(client, run_id)
    client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                 json={'selected_channels': ['instagram']})
    checked = client.get(f'/api/calendar/slots/{slot["id"]}/validate-ready').json()
    assert checked['ready_eligible'] is False
    assert checked['checks']['pack_approved'] is False
    assert checked['checks']['format_passed'] is False
    assert 'pack_not_approved' in checked['failing_conditions']
    assert 'format_check_failed' in checked['failing_conditions']
    assert checked['format_reason'] == 'Blocked: feed carousel needs 5 to 10 frames at 4:5; got 2 frames.'
    refused = client.post(f'/api/calendar/slots/{slot["id"]}/mark-ready')
    assert refused.status_code == 409, refused.text
    assert 'format_check_failed' in refused.json()['detail']['failing_conditions']


def test_approving_run_and_variants_flips_slot_to_ready(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    slot = new_slot(client, run_id)
    approve(client, run_id)
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    channel = next(c for c in CHANNELS if bundle[c]['content_valid'] and bundle[c]['text'])
    client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                 json={'selected_channels': [channel]})
    partial = client.get(f'/api/calendar/slots/{slot["id"]}/validate-ready').json()
    assert partial['ready_eligible'] is False
    assert partial['checks']['pack_approved'] is True
    assert partial['checks']['format_passed'] is True
    assert partial['checks']['variants_approved'] is False
    assert partial['unapproved_channels'] == [channel]
    approved = client.post(f'/api/calendar/slots/{slot["id"]}/approve-channels',
                           json={'channels': [channel], 'expected_revision': 0})
    assert approved.status_code == 200, approved.text
    assert approved.json()['approved_channels'] == [channel]
    ready = client.get(f'/api/calendar/slots/{slot["id"]}/validate-ready').json()
    assert ready['ready_eligible'] is True
    assert ready['failing_conditions'] == []
    assert ready['checks'] == {'pack_approved': True, 'format_passed': True,
                               'variants_approved': True}
    marked = client.post(f'/api/calendar/slots/{slot["id"]}/mark-ready')
    assert marked.status_code == 200, marked.text
    assert marked.json()['schedule_state'] == 'ready'


def test_export_lists_only_ready_slots_with_reasons(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    ready_slot = new_slot(client, run_id)
    draft_slot = new_slot(client, run_id, slot_type='story')
    approve(client, run_id)
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    channel = next(c for c in CHANNELS if bundle[c]['content_valid'] and bundle[c]['text'])
    client.patch(f'/api/calendar/slots/{ready_slot["id"]}/schedule',
                 json={'selected_channels': [channel], 'planned_time': '18:00'})
    client.post(f'/api/calendar/slots/{ready_slot["id"]}/approve-channels',
                json={'channels': [channel], 'expected_revision': 0})
    assert client.post(f'/api/calendar/slots/{ready_slot["id"]}/mark-ready').status_code == 200
    exported = client.get('/api/calendar/schedule-export')
    assert exported.status_code == 200, exported.text
    document = exported.json()
    assert document['schema_version'] == 'schedule-export/v1'
    assert document['publishing_mode'] == 'planning_only_never_publishes'
    assert document['exported_at']
    assert [entry['slot_id'] for entry in document['ready_slots']] == [ready_slot['id']]
    entry = document['ready_slots'][0]
    assert entry['slot_date'] == '2026-11-03'
    assert entry['planned_time'] == '18:00'
    assert entry['slot_type'] == 'feed_post'
    assert entry['pillar'] == 'product'
    assert entry['format_key'] == 'feed_post'
    assert entry['run_id'] == run_id
    assert entry['selected_channels'] == [channel]
    assert entry['channel_variants'][0]['channel'] == channel
    assert entry['channel_variants'][0]['approved'] is True
    assert entry['pack_reference']['run_id'] == run_id
    assert entry['pack_reference']['approval_state'] == 'approved_for_export'
    excluded_ids = [item['slot_id'] for item in document['excluded_slots']]
    assert draft_slot['id'] in excluded_ids
    excluded = next(item for item in document['excluded_slots'] if item['slot_id'] == draft_slot['id'])
    assert excluded['slot_date'] == '2026-11-03'
    assert excluded['slot_type'] == 'story'
    assert excluded['failing_conditions']
    assert excluded['reasons']
    import json as json_mod
    json_mod.dumps(document)
