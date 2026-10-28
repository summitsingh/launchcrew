"""API regression tests for learned memory semantics.

Requires the Postgres-backed client fixture. Deterministic pipeline only,
no live model calls, no credentials. The host verifier runs this suite.
"""
from unittest.mock import patch
from launchcrew import run

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


def memory(client, kind, title, content):
    response = client.post('/api/memory', json={'kind': kind, 'title': title, 'content': content})
    assert response.status_code == 201
    return response.json()


def run_with(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_learned_blocked_rule_dict_format_blocks_and_delete_removes(client):
    item = memory(client, 'blocked_rule', 'No hype', {'claim': 'best in Texas'})
    blocked = run_with(client, memory_ids=[item['id']])
    assert blocked['checker_v1']['blocked_count'] == 1
    assert blocked['checker_v1']['blocked_claims'][0]['claim'] == 'best in Texas'
    assert blocked['checker_v2']['blocked_count'] == 0
    assert blocked['memory_blocked_rules'][0]['claim'] == 'best in Texas'
    assert blocked['memory_used'] == [{'id': item['id'], 'kind': 'blocked_rule', 'title': 'No hype'}]
    pending = client.post('/api/memory/from-run/' + blocked['run_id'], json={'kind': 'blocked_rule'})
    assert pending.status_code == 409  # pending run is not approved, learning refused
    edited = client.put('/api/memory/' + item['id'],
                        json={'title': 'No hype edited', 'content': {'blocked_claims': [{'nope': 1}]}})
    assert edited.status_code == 200
    unblocked = run_with(client, memory_ids=[item['id']])
    assert unblocked['checker_v1']['blocked_count'] == 0
    assert client.delete('/api/memory/' + item['id']).status_code == 204
    clean = run_with(client)
    assert clean['checker_v1']['blocked_count'] == 0
    assert client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                           'memory_ids': [item['id']]}).status_code == 404


def test_learned_example_from_approved_run_is_style_only_and_snapshot_stable(client):
    plain = run_with(client, seed_unverified_claim=False)
    assert client.post('/api/runs/' + plain['run_id'] + '/approve', json={}).status_code == 200
    learned = client.post('/api/memory/from-run/' + plain['run_id'], json={'kind': 'approval_example'})
    assert learned.status_code == 201
    item = learned.json()
    assert set(item['content']) == {'idea', 'post', 'email'}
    with_example = run_with(client, memory_ids=[item['id']])
    without = run_with(client)
    # Style context never becomes an approved fact: keyless drafts are identical.
    assert with_example['maker_draft_v2'] == without['maker_draft_v2']
    assert len(with_example['memory_examples']) == 1
    assert with_example['memory_examples'][0]['id'] == item['id']
    assert with_example['memory_used'] == [{'id': item['id'], 'kind': 'approval_example', 'title': item['title']}]
    # Editing the example does not rewrite the earlier receipt snapshot.
    client.put('/api/memory/' + item['id'],
               json={'title': item['title'], 'content': {'idea': 'changed', 'post': 'changed post', 'email': 'changed email'}})
    reread = client.get('/api/runs/' + with_example['run_id']).json()
    assert reread['memory_examples'][0]['post'] != 'changed post'
    assert client.post('/api/memory/from-run/' + plain['run_id'], json={'kind': 'approval_example'}).status_code == 201


def test_profile_and_example_claim_fields_never_become_facts(client):
    profile_item = memory(client, 'profile', 'Voice', {'claim': 'best in Texas', 'expertise': 'Austin voice'})
    example_item = memory(client, 'approval_example', 'Style', {'claim': 'best in Texas', 'idea': 'i', 'post': 'p', 'email': 'e'})
    receipt = run_with(client, memory_ids=[profile_item['id'], example_item['id']])
    assert receipt['memory_claims'] == []
    assert receipt['checker_v1']['blocked_count'] == 0
    assert 'best in Texas' not in receipt['maker_draft_v2']['post']
