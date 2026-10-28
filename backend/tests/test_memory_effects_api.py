"""API regression tests for learned memory semantics.

Requires the Postgres-backed client fixture. Deterministic pipeline only,
no live model calls, no credentials. The host verifier runs this suite.

Memory rules filter real candidate claims: the learned $49 rule below comes
from an ordinary policy-triggered run (a custom PriceGuard Checker), never
from an injected or seeded claim.
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


def base_profile(name, rules=None, veto=None):
    return {
        'name': name,
        'role': 'Custom role for ' + name,
        'department': 'Growth',
        'personality': 'Custom personality for ' + name,
        'expertise': 'Custom expertise for ' + name,
        'decision_rules': list(rules) if rules else ['Use facts file first'],
        'veto_scope': list(veto) if veto else [],
        'tools_allowed': ['facts_file', 'spark_strict_json', 'receipt_log', 'claim_check'],
        'spend_limit': 0,
        'approval_level': 'approve_each',
        'examples': [],
    }


def create_agent(client, profile):
    response = client.post('/api/agents', json=profile)
    assert response.status_code == 201
    return response.json()


def memory(client, kind, title, content):
    response = client.post('/api/memory', json={'kind': kind, 'title': title, 'content': content})
    assert response.status_code == 201
    return response.json()


def run_with(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_learned_blocked_rule_from_policy_run_filters_real_claim(client):
    create_agent(client, base_profile('MemPriceGuard', ['Block price claims'], ['price_claims']))
    # Ordinary policy-triggered run, no seed: the $49 claim occurs naturally.
    priced = run_with(client, checker_name='MemPriceGuard')
    assert priced['checker_v1']['blocked_count'] == 1
    assert priced['checker_v1']['blocked_claims'][0]['claim'] == '$49'
    assert 'price_claims' in priced['checker_v1']['blocked_claims'][0]['reason']
    assert priced['checker_v2']['blocked_count'] == 0
    assert '$49' not in priced['maker_draft_v2']['post']
    assert client.post('/api/runs/' + priced['run_id'] + '/approve', json={}).status_code == 200
    # Learn the rule from the approved run: the blocked claim is a real one.
    learned = client.post('/api/memory/from-run/' + priced['run_id'], json={'kind': 'blocked_rule'})
    assert learned.status_code == 201
    item = learned.json()
    assert [entry['claim'] for entry in item['content']['blocked_claims']] == ['$49']
    # Default Checker without the rule: no block, price present.
    plain = run_with(client)
    assert plain['checker_v1']['blocked_count'] == 0
    assert '$49' in plain['maker_draft_v1']['post']
    assert '$49' in plain['maker_draft_v2']['post']
    # Default Checker with the learned rule: the real claim is filtered.
    blocked = run_with(client, memory_ids=[item['id']])
    assert blocked['checker_v1']['blocked_count'] == 1
    assert blocked['checker_v1']['blocked_claims'][0]['claim'] == '$49'
    assert blocked['checker_v2']['blocked_count'] == 0
    assert '$49' not in blocked['maker_draft_v2']['post']
    assert blocked['memory_blocked_rules'][0]['claim'] == '$49'
    assert blocked['memory_used'] == [{'id': item['id'], 'kind': 'blocked_rule', 'title': item['title']}]
    # Editing the rule to another real approved claim changes the verdict.
    edited = client.put('/api/memory/' + item['id'],
                        json={'title': item['title'],
                              'content': {'blocked_claims': [{'claim': 'Designed in Texas', 'reason': 'Edited rule'}]}})
    assert edited.status_code == 200
    redesigned = run_with(client, memory_ids=[item['id']])
    assert [entry['claim'] for entry in redesigned['checker_v1']['blocked_claims']] == ['Designed in Texas']
    assert 'Designed in Texas' not in redesigned['maker_draft_v2']['post']
    assert '$49' in redesigned['maker_draft_v2']['post']
    assert client.delete('/api/memory/' + item['id']).status_code == 204
    clean = run_with(client)
    assert clean['checker_v1']['blocked_count'] == 0
    assert '$49' in clean['maker_draft_v2']['post']
    assert client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                           'memory_ids': [item['id']]}).status_code == 404
    # The old receipt still carries its snapshot of the learned rule.
    reread = client.get('/api/runs/' + blocked['run_id']).json()
    assert reread['memory_blocked_rules'][0]['claim'] == '$49'


def test_absent_blocked_claim_never_manufactured(client):
    # A rule for a claim in no candidate stays recorded with zero blocks.
    item = memory(client, 'blocked_rule', 'No hype', {'claim': 'best in Texas'})
    receipt = run_with(client, memory_ids=[item['id']])
    assert receipt['memory_blocked_rules'][0]['claim'] == 'best in Texas'
    assert receipt['checker_v1']['blocked_count'] == 0
    assert 'best in Texas' not in receipt['maker_draft_v1']['post']
    assert 'best in Texas' not in receipt['maker_draft_v2']['post']


def test_unsupported_brand_fact_is_refused_not_approved(client):
    # An unsupported memory claim refuses the run instead of entering facts.
    bad = memory(client, 'brand_fact', 'Bad', {'claim': 'best in Texas'})
    with pytest.raises(ValueError, match='Approved facts failed deterministic checks'):
        client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [bad['id']]})


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
