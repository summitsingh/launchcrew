"""S1 content calendar acceptance on Postgres.

Deterministic fixtures only, no live model calls, no credentials.
Week and month rendering lives in the frontend suite; here the API
proves one-action 7-day campaign placement with correctly typed slots,
per-slot pillars (built-in plus owner-added), and automatic slot
status advancement on run approve/export with no manual status edit.
"""
from unittest.mock import patch

import pytest

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


def new_run(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def new_campaign(client):
    response = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    return response.json()


def test_place_campaign_in_one_action_creates_seven_typed_slots(client):
    week = new_campaign(client)
    response = client.post('/api/calendar/campaigns/%s/place' % week['id'],
                           json={'start_date': '2026-11-02'})
    assert response.status_code == 201, response.text
    slots = response.json()
    assert len(slots) == 7
    assert [slot['campaign_day'] for slot in slots] == [1, 2, 3, 4, 5, 6, 7]
    assert [slot['slot_date'] for slot in slots] == [
        '2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05',
        '2026-11-06', '2026-11-07', '2026-11-08']
    for slot in slots:
        assert slot['slot_type'] in ('feed_post', 'story', 'reel')
        assert slot['pillar']
        assert slot['format']
        assert slot['status'] in ('drafted', 'checked', 'approved', 'exported')
        assert slot['campaign_id'] == week['id']
    run_ids = {day['run_id'] for day in week['days']}
    assert {slot['run_id'] for slot in slots} == run_ids
    listed = client.get('/api/calendar/slots?start_date=2026-11-02&end_date=2026-11-08')
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 7


def test_single_slot_derives_status_and_keeps_custom_pillar(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    response = client.post('/api/calendar/slots', json={
        'slot_date': '2026-11-03', 'slot_type': 'story',
        'pillar': 'founder-story', 'format': 'story',
        'run_id': run_id})
    assert response.status_code == 201, response.text
    slot = response.json()
    assert slot['status'] == 'checked'
    assert slot['pillar'] == 'founder-story'
    assert slot['run_id'] == run_id


def test_approving_run_advances_slot_with_no_manual_edit(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    created = client.post('/api/calendar/slots', json={
        'slot_date': '2026-11-03', 'slot_type': 'feed_post',
        'pillar': 'product', 'format': 'feed_post', 'run_id': run_id})
    assert created.status_code == 201, created.text
    assert created.json()['status'] == 'checked'
    approved = client.post('/api/runs/%s/approve' % run_id, json={})
    assert approved.status_code == 200, approved.text
    listed = client.get('/api/calendar/slots?start_date=2026-11-01&end_date=2026-11-30')
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]['status'] == 'approved'


def test_exporting_run_advances_slot_with_no_manual_edit(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('no network expected')):
        with patch('backend.sam.urlopen', side_effect=AssertionError('no network expected')):
            assert client.post('/api/runs/%s/approve' % run_id, json={}).status_code == 200
            exported = client.post('/api/runs/%s/export' % run_id, json={})
            assert exported.status_code == 200, exported.text
    created = client.post('/api/calendar/slots', json={
        'slot_date': '2026-11-04', 'slot_type': 'reel',
        'pillar': 'offer', 'format': 'reel', 'run_id': run_id})
    assert created.status_code == 201, created.text
    assert created.json()['status'] == 'exported'


def test_campaign_day_approve_advances_placed_slot(client):
    week = new_campaign(client)
    placed = client.post('/api/calendar/campaigns/%s/place' % week['id'],
                         json={'start_date': '2026-11-02'})
    assert placed.status_code == 201, placed.text
    day_one = week['days'][0]
    approved = client.post('/api/campaigns/%s/days/1/approve' % week['id'], json={})
    assert approved.status_code == 200, approved.text
    listed = client.get('/api/calendar/slots?start_date=2026-11-02&end_date=2026-11-02')
    assert listed.status_code == 200, listed.text
    match = [slot for slot in listed.json() if slot['run_id'] == day_one['run_id']]
    assert len(match) == 1
    assert match[0]['status'] == 'approved'


def test_slot_list_filters_by_date_and_delete_removes(client):
    receipt = new_run(client)
    for slot_date in ('2026-11-03', '2026-11-10'):
        response = client.post('/api/calendar/slots', json={
            'slot_date': slot_date, 'slot_type': 'feed_post',
            'pillar': 'product', 'format': 'feed_post', 'run_id': receipt['run_id']})
        assert response.status_code == 201, response.text
    filtered = client.get('/api/calendar/slots?start_date=2026-11-01&end_date=2026-11-05')
    assert filtered.status_code == 200, filtered.text
    assert [slot['slot_date'] for slot in filtered.json()] == ['2026-11-03']
    slot_id = filtered.json()[0]['id']
    deleted = client.delete('/api/calendar/slots/%s' % slot_id)
    assert deleted.status_code == 204, deleted.text
    remaining = client.get('/api/calendar/slots')
    assert remaining.status_code == 200, remaining.text
    assert [slot['id'] for slot in remaining.json()] != [slot_id]
    assert len(remaining.json()) == 1


def test_slot_rejects_bad_type_date_and_unknown_run(client):
    receipt = new_run(client)
    assert client.post('/api/calendar/slots', json={
        'slot_date': '2026-11-03', 'slot_type': 'feed_post',
        'pillar': 'product', 'format': 'feed_post',
        'run_id': 'run_missing'}).status_code == 404
    assert client.post('/api/calendar/slots', json={
        'slot_date': 'not-a-date', 'slot_type': 'feed_post',
        'pillar': 'product', 'format': 'feed_post'}).status_code == 422
    assert client.post('/api/calendar/slots', json={
        'slot_date': '2026-11-03', 'slot_type': 'broadcast',
        'pillar': 'product', 'format': 'broadcast'}).status_code == 422
    assert receipt['run_id']
