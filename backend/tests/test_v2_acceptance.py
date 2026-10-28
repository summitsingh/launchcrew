"""Acceptance regression tests for Item A behavioral requirements.

Deterministic fixtures only, no live model calls, no credentials.
Memory is consumed only when a run explicitly selects memory_ids, and only
through the documented contract: brand_fact content.claim becomes a run
allowlist claim, blocked_rule content.claim or content.blocked_claims
(string or list-of-dicts entries) becomes a run blocked claim, profile
content.expertise becomes the Maker profile expertise for that run, and
approval_example idea/post/email becomes Maker prompt style context only
(never an approved fact). Items without those fields are recorded
in memory_used but do not change the draft, by design.
"""
import json
import pytest
from unittest.mock import patch
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


def memory(client, kind, title, content):
    response = client.post('/api/memory', json={'kind': kind, 'title': title, 'content': content})
    assert response.status_code == 201
    return response.json()


def run_with(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201
    return response.json()


def test_memory_brand_fact_edit_changes_next_run(client):
    item = memory(client, 'brand_fact', 'Handmade', {'claim': 'Handmade vegan wallet for commuters'})
    first = run_with(client, memory_ids=[item['id']])
    assert first['memory_used'][0]['id'] == item['id']
    assert 'Handmade vegan wallet for commuters' in first['maker_draft_v2']['post']
    assert first['checker_v2']['blocked_count'] == 0
    edited = client.put('/api/memory/' + item['id'], json={'title': 'Handmade edited', 'content': {'claim': 'Handmade vegan wallet, designed in Texas'}})
    assert edited.status_code == 200
    second = run_with(client, memory_ids=[item['id']])
    assert 'Handmade vegan wallet, designed in Texas' in second['maker_draft_v2']['post']
    assert 'Handmade vegan wallet for commuters' not in second['maker_draft_v2']['post']


def test_memory_blocked_rule_delete_removes_block(client):
    item = memory(client, 'blocked_rule', 'No price', {'claim': '$49'})
    blocked = run_with(client, memory_ids=[item['id']])
    assert blocked['checker_v1']['blocked_count'] == 1
    assert blocked['checker_v1']['blocked_claims'][0]['claim'] == '$49'
    assert blocked['checker_v2']['blocked_count'] == 0
    assert '$49' not in blocked['maker_draft_v2']['post']
    assert client.delete('/api/memory/' + item['id']).status_code == 204
    clean = run_with(client)
    assert clean['checker_v1']['blocked_count'] == 0
    assert '$49' in clean['maker_draft_v2']['post']
    assert client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [item['id']]}).status_code == 404


def test_memory_selection_recorded_and_profile_expertise_used(client):
    item = memory(client, 'profile', 'Commuter voice', {'claim': 'Handmade vegan wallet for commuters', 'expertise': 'Austin commuter styling'})
    receipt = run_with(client, memory_ids=[item['id']])
    assert receipt['memory_used'] == [{'id': item['id'], 'kind': 'profile', 'title': 'Commuter voice'}]
    assert receipt['memory_profile_expertise'] == 'Austin commuter styling'
    assert receipt['checker_profile'] == 'standard'


def test_checker_strict_vs_standard_same_idea(client):
    item = memory(client, 'brand_fact', 'Hype claim', {'claim': 'Amazing vegan wallet for commuters'})
    standard = run_with(client, memory_ids=[item['id']], checker_profile='standard')
    assert standard['checker_v1']['blocked_count'] == 0
    assert 'Amazing vegan wallet for commuters' in standard['maker_draft_v2']['post']
    strict = run_with(client, memory_ids=[item['id']], checker_profile='strict')
    assert strict['checker_v1']['blocked_count'] == 1
    assert strict['checker_v1']['blocked_claims'][0]['claim'] == 'Amazing vegan wallet for commuters'
    assert 'superlatives' in strict['checker_v1']['blocked_claims'][0]['reason']
    assert 'superlative or hype' in strict['checker_v1']['blocked_claims'][0]['reason']
    assert strict['checker_profile'] == 'strict'
    assert strict['checker_v2']['blocked_count'] == 0
    assert 'Amazing vegan wallet for commuters' not in strict['maker_draft_v2']['post']
    assert client.post(f"/api/runs/{strict['run_id']}/approve", json={}).status_code == 200
    assert client.post(f"/api/runs/{strict['run_id']}/export", json={}).status_code == 200
    # Deterministic claim safety is enforced in both profiles.
    for profile in ('standard', 'strict'):
        seeded = run_with(client, seed_unverified_claim=True, checker_profile=profile)
        assert any(c['claim'] == 'best in Texas' for c in seeded['checker_v1']['blocked_claims'])
        assert seeded['checker_v2']['blocked_count'] == 0


def test_replay_shows_checker_profile_difference(client):
    item = memory(client, 'brand_fact', 'Hype claim', {'claim': 'Amazing vegan wallet for commuters'})
    standard = run_with(client, memory_ids=[item['id']], checker_profile='standard')
    strict = run_with(client, memory_ids=[item['id']], checker_profile='strict')
    response = client.get(f"/api/runs/{standard['run_id']}/diff/{strict['run_id']}")
    assert response.status_code == 200
    diff = response.json()
    assert diff['same_idea'] is True
    assert diff['checker_profile_a'] == 'standard' and diff['checker_profile_b'] == 'strict'
    assert diff['checker_profile_changed'] is True
    assert diff['checker_v1_blocked_count_a'] == 0 and diff['checker_v1_blocked_count_b'] == 1
    assert diff['draft_v2_post_changed'] is True
    assert diff['memory_ids_a'] == [item['id']] and diff['memory_ids_b'] == [item['id']]


def test_campaign_seven_distinct_briefs_and_independent_gates(client):
    response = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker', 'checker_profile': 'standard'})
    assert response.status_code == 201
    week = response.json()
    assert [day['day'] for day in week['days']] == list(range(1, 8))
    assert len({day['brief'] for day in week['days']}) == 7
    assert len({day['angle'] for day in week['days']}) == 7
    assert len({day['draft_v2_post'] for day in week['days']}) == 7
    assert week['days'][0]['angle'] == 'Origin story'
    assert week['days'][6]['angle'] == 'Launch offer'
    for day in week['days']:
        receipt = client.get(f"/api/runs/{day['run_id']}").json()
        assert receipt['campaign_day'] == day['day']
        assert receipt['campaign_brief'] == day['brief']
    path = f"/api/campaigns/{week['id']}/days/1"
    assert client.post(path + '/export', json={}).status_code == 422
    assert client.post(path + '/approve', json={}).status_code == 200
    assert client.post(path + '/export', json={}).status_code == 200
    assert all(day['approval_state'] == 'pending_approval' for day in client.get('/api/campaigns/' + week['id']).json()['days'][1:])
    # A blocked day refuses approval and export, while another day proceeds.
    day2 = week['days'][1]['run_id']
    receipt = client.get(f'/api/runs/{day2}').json()
    receipt['checker_v2']['blocked_count'] = 1
    with store.connect() as db:
        db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'), {'id': day2, 'receipt': json.dumps(receipt)})
    assert client.post(f"/api/campaigns/{week['id']}/days/2/approve", json={}).status_code == 422
    assert client.post(f"/api/campaigns/{week['id']}/days/2/export", json={}).status_code == 422
    assert client.post(f"/api/campaigns/{week['id']}/days/3/approve", json={}).status_code == 200
