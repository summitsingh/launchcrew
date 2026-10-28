"""Postgres-backed v2 routes with offline demo pipeline execution."""
import json
from unittest.mock import patch
import pytest
from sqlalchemy import text
from backend import store
from backend.app import app
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
    assert response.status_code == 201
    return response.json()


def campaign(client):
    response = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker', 'seed_unverified_claim': True})
    assert response.status_code == 201
    return response.json()


def test_memory_lifecycle_and_audit(client):
    body = {'kind': 'brand_fact', 'title': 'Demo price', 'content': {'price': '$49'}}
    response = client.post('/api/memory', json=body)
    assert response.status_code == 201
    item = response.json()
    assert item['id'].startswith('mem_') and item['source_run_id'] is None
    url = '/api/memory/' + item['id']
    assert client.get('/api/memory').json() == [item]
    assert client.get(url).json() == item
    edit = {**body, 'title': 'Wallet price', 'content': {'demo': True}}
    assert client.put(url, json={**edit, 'kind': 'profile'}).status_code == 422
    updated = client.put(url, json=edit).json()
    assert updated['title'] == 'Wallet price' and updated['content'] == {'demo': True}
    assert updated['updated_at'] > item['updated_at']
    assert client.put(url, json={'title': '', 'content': {}}).status_code == 422
    assert client.post('/api/memory', json={**body, 'extra': True}).status_code == 422
    deleted = client.delete(url)
    assert deleted.status_code == 204 and deleted.content == b''
    assert client.get('/api/memory').json() == []
    for method in ('get', 'put', 'delete'):
        assert getattr(client, method)(url, **({'json': edit} if method == 'put' else {})).status_code == 404
    with store.connect() as db:
        rows = db.execute(text('SELECT run_id,action FROM audit ORDER BY id')).all()
    assert rows == [(None, 'memory_item_created'), (None, 'memory_item_edited'), (None, 'memory_item_deleted')]


@pytest.mark.parametrize('kind', ['approval_example', 'blocked_rule'])
def test_explicit_learning_only_after_approval(client, kind):
    receipt = new_run(client, seed_unverified_claim=True)
    run_id = receipt['run_id']
    url = f'/api/memory/from-run/{run_id}'
    assert client.post(url, json={'kind': kind}).status_code == 409
    assert client.post(url, json={'kind': 'profile'}).status_code == 422
    assert client.get('/api/memory').json() == []
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    assert client.get('/api/memory').json() == []
    response = client.post(url, json={'kind': kind})
    assert response.status_code == 201
    learned = response.json()
    assert learned['source_run_id'] == run_id
    expected = ({'idea': IDEA, 'post': receipt['maker_draft_v2']['post'], 'email': receipt['maker_draft_v2']['email']}
                if kind == 'approval_example' else {'blocked_claims': receipt['checker_v1']['blocked_claims']})
    assert learned['content'] == expected
    with store.connect() as db:
        assert db.execute(text("SELECT run_id FROM audit WHERE action='memory_item_learned'")).scalar() == run_id
    assert client.post('/api/memory/from-run/missing', json={'kind': kind}).status_code == 404


def test_replay_drafts_checks_approval_keys(client):
    a = new_run(client, seed_unverified_claim=True)
    b = new_run(client)
    client.post(f"/api/runs/{b['run_id']}/approve", json={})
    with store.connect() as db:
        db.execute(text("UPDATE runs SET receipt=receipt || CAST(:extra AS jsonb) WHERE id=:id"), {'id': a['run_id'], 'extra': json.dumps({'demo_extra': True})})
    response = client.get(f"/api/runs/{a['run_id']}/diff/{b['run_id']}")
    assert response.status_code == 200
    diff = response.json()
    assert diff['same_idea'] and diff['idea'] == IDEA
    assert diff['draft_v1_post_changed'] and diff['draft_v1_email_changed']
    assert not diff['draft_v2_post_changed'] and not diff['draft_v2_email_changed']
    assert diff['checker_v1_blocked_count_a'] == 1 and diff['checker_v1_blocked_count_b'] == 0
    assert diff['checker_v2_blocked_count_a'] == diff['checker_v2_blocked_count_b'] == 0
    assert diff['blocked_claims_only_in_a'][0]['claim'] == 'best in Texas'
    assert diff['blocked_claims_only_in_b'] == []
    assert diff['approval_state_changed'] and diff['approval_state_b'] == 'approved_for_export'
    assert diff['receipt_keys_only_in_a'] == ['demo_extra']
    assert diff['draft_v1_post_a'] == a['maker_draft_v1']['post']
    assert diff['draft_v2_email_b'] == b['maker_draft_v2']['email']
    assert client.get(f"/api/runs/{a['run_id']}/diff/missing").status_code == 404
    assert client.get(f"/api/runs/missing/diff/{b['run_id']}").status_code == 404


def test_replay_mismatched_ideas_and_failed_receipt(client):
    a = new_run(client)
    b = new_run(client, idea='Another demo idea')
    response = client.get(f"/api/runs/{a['run_id']}/diff/{b['run_id']}")
    assert response.status_code == 200 and response.json()['same_idea'] is False
    with patch('launchcrew.run.make_draft', side_effect=RuntimeError('demo')):
        failed = new_run(client)
    response = client.get(f"/api/runs/{a['run_id']}/diff/{failed['run_id']}")
    assert response.status_code == 200 and response.json()['checker_v2_blocked_count_b'] is None


def test_campaign_seven_individual_packs(client):
    week = campaign(client)
    assert week['id'].startswith('camp_')
    assert [day['day'] for day in week['days']] == list(range(1, 8))
    assert len({day['run_id'] for day in week['days']}) == 7
    assert all(day['approval_state'] == 'pending_approval' for day in week['days'])
    assert len(client.get('/api/queue').json()) == 7
    with store.connect() as db:
        for table in ('runs', 'memory', 'campaign_days'):
            assert db.execute(text('SELECT count(*) FROM ' + table)).scalar() == 7
        assert db.execute(text('SELECT count(*) FROM memory_items')).scalar() == 0
    assert client.get('/api/campaigns').json() == [week]
    assert client.get('/api/campaigns/' + week['id']).json() == week
    path = f"/api/campaigns/{week['id']}/days/1"
    assert client.post(path + '/export', json={}).status_code == 422
    result = client.post(path + '/approve', json={})
    assert result.status_code == 200 and result.json()['approval_state'] == 'approved_for_export'
    exported = client.post(path + '/export', json={})
    assert exported.status_code == 200 and 'attachment' in exported.headers['content-disposition']
    assert exported.json()['run_id'] == week['days'][0]['run_id']
    assert exported.json()['summary']['submit_attempted'] is False
    days = client.get('/api/campaigns/' + week['id']).json()['days']
    assert all(day['approval_state'] == 'pending_approval' for day in days[1:])
    with store.connect() as db:
        actions = db.execute(text('SELECT action FROM audit WHERE run_id=:id ORDER BY id'), {'id': days[0]['run_id']}).scalars().all()
    assert actions == ['run_created', 'approved_for_export', 'exported']
    for suffix in ('approve', 'export'):
        assert client.post(f"/api/campaigns/{week['id']}/{suffix}", json={}).status_code in (404, 405)
        assert client.post(f"/api/campaigns/{week['id']}/days/{suffix}", json={}).status_code in (404, 405)
        assert client.post(f"/api/campaigns/{week['id']}/days/8/{suffix}", json={}).status_code == 404
    assert client.get('/api/campaigns/missing').status_code == 404


@pytest.mark.parametrize('status,blocked', [('completed', 1), ('failed', 0)])
def test_campaign_gate_refuses_unsafe_receipts(client, status, blocked):
    week = campaign(client)
    run_id = week['days'][0]['run_id']
    receipt = client.get(f'/api/runs/{run_id}').json()
    receipt['status'] = status
    receipt['checker_v2']['blocked_count'] = blocked
    with store.connect() as db:
        db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'), {'id': run_id, 'receipt': json.dumps(receipt)})
    assert client.post(f"/api/campaigns/{week['id']}/days/1/approve", json={}).status_code == 422


def test_campaign_transaction_rollback(client):
    with patch('backend.store.audit', side_effect=ValueError('demo rollback')):
        assert client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'}).status_code == 422
    assert client.get('/api/campaigns').json() == [] and client.get('/api/queue').json() == []


def test_v1_approval_export_preserved(client):
    receipt = new_run(client, seed_unverified_claim=True)
    path = '/api/runs/' + receipt['run_id']
    assert client.post(path + '/export', json={}).status_code == 422
    assert client.post(path + '/approve', json={}).status_code == 200
    assert client.post(path + '/export', json={}).status_code == 200


def test_v2_routes_require_existing_actor(client, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    for method, path, body in [
        ('get', '/api/memory', None), ('post', '/api/memory', {'kind': 'profile', 'title': 'Demo', 'content': {}}),
        ('get', '/api/memory/missing', None), ('put', '/api/memory/missing', {'title': 'Demo', 'content': {}}),
        ('delete', '/api/memory/missing', None), ('post', '/api/memory/from-run/missing', {'kind': 'blocked_rule'}),
        ('get', '/api/runs/a/diff/b', None), ('get', '/api/campaigns', None), ('get', '/api/campaigns/missing', None),
        ('post', '/api/campaigns', {'idea': IDEA, 'agent_name': 'Maker'}),
        ('post', '/api/campaigns/missing/days/1/approve', {}), ('post', '/api/campaigns/missing/days/1/export', {})]:
        assert getattr(client, method)(path, **({'json': body} if body is not None else {})).status_code == 401
