"""API regression tests for per-stage bindings and Checker policies.

Postgres-backed. Codex executes these with the release candidate verifier.
Deterministic fixtures only, no live model calls.
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


def test_checker_policies_endpoint_documents_supported_subset(client):
    response = client.get('/api/checker-policies')
    assert response.status_code == 200
    body = response.json()
    assert sorted(item['policy'] for item in body['supported']) == ['cliches', 'price_claims', 'superlatives']
    assert 'cannot be relaxed' in body['floor_note']
    assert 'Exact match only' in body['matching']
    tokens = {item['veto_token'] for item in body['supported']}
    assert tokens == {'superlatives', 'price_claims', 'cliches'}


def test_preview_reports_enforced_and_advisory(client):
    create_agent(client, base_profile('ApiPriceGuard', ['Block price claims', 'Be nice'], ['price_claims']))
    response = client.post('/api/agents/ApiPriceGuard/preview', json={'idea': IDEA})
    assert response.status_code == 200
    body = response.json()
    assert body['model_called'] is False
    assert body['checker_enforcement']['enforced_policies'] == ['price_claims']
    advisory = [item['entry'] for item in body['checker_enforcement']['advisory_only']]
    assert 'Be nice' in advisory
    assert body['checker_enforcement']['floor_enforced'] is True


def test_stage_bindings_reach_correct_stages_with_identity(client):
    create_agent(client, base_profile('ApiScout'))
    create_agent(client, base_profile('ApiMaker'))
    create_agent(client, base_profile('ApiChecker', ['Block price claims'], ['price_claims']))
    response = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'ApiMaker', 'scout_name': 'ApiScout',
        'maker_name': 'ApiMaker', 'checker_name': 'ApiChecker'})
    assert response.status_code == 201
    receipt = response.json()
    assert receipt['stage_bindings'] == {'scout': 'ApiScout', 'maker': 'ApiMaker', 'checker': 'ApiChecker'}
    assert receipt['stage_agents']['scout']['personality'] == 'Custom personality for ApiScout'
    assert receipt['stage_agents']['maker']['expertise'] == 'Custom expertise for ApiMaker'
    assert receipt['stage_agents']['checker']['veto_scope'] == ['price_claims']
    assert receipt['legacy_agent_name'] == 'ApiMaker'
    assert len(receipt['scout']['risks']) == 3
    assert len(receipt['scout']['facts_used']) == 5


def test_distinct_checker_policies_change_same_idea_verdicts(client):
    create_agent(client, base_profile('ApiPlain'))
    create_agent(client, base_profile('ApiPriced', ['Block price claims'], ['price_claims']))
    plain = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'checker_name': 'ApiPlain'}).json()
    priced = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'checker_name': 'ApiPriced'}).json()
    assert plain['checker_v1']['blocked_count'] == 0
    assert '$49' in plain['maker_draft_v2']['post']
    assert priced['checker_v1']['blocked_count'] > 0
    assert '$49' in [item['claim'] for item in priced['checker_v1']['blocked_claims']]
    assert '$49' not in priced['maker_draft_v2']['post']
    assert priced['checker_enforcement']['effective_policies'] == ['price_claims']


def test_user_profiles_cannot_approve_unsupported_claims(client):
    create_agent(client, base_profile('ApiAllowMaker', ['Allow everything']))
    create_agent(client, base_profile('ApiAllowChecker', ['Allow best in Texas'], ['allow_everything']))
    response = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'ApiAllowMaker', 'checker_name': 'ApiAllowChecker',
        'seed_unverified_claim': True})
    assert response.status_code == 201
    receipt = response.json()
    assert 'best in Texas' in [item['claim'] for item in receipt['checker_v1']['blocked_claims']]
    assert receipt['checker_v2']['blocked_count'] == 0
    assert 'best in Texas' not in receipt['maker_draft_v2']['post']


def test_legacy_agent_name_maker_compat_and_guards(client):
    receipt = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'}).json()
    assert receipt['stage_bindings'] == {'scout': 'Scout', 'maker': 'Maker', 'checker': 'Checker'}
    assert receipt['approval_state'] == 'pending_approval'
    run_id = receipt['run_id']
    assert client.post(f'/api/runs/{run_id}/export', json={}).status_code == 422
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    exported = client.post(f'/api/runs/{run_id}/export', json={})
    assert exported.status_code == 200
    assert exported.json()['approval_state'] == 'approved_for_export'


def test_unknown_stage_name_is_404(client):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'checker_name': 'MissingChecker'})
    assert response.status_code == 404


def test_replay_shows_stage_binding_difference(client):
    create_agent(client, base_profile('ApiReplayA'))
    plain = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'}).json()
    custom = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'scout_name': 'ApiReplayA'}).json()
    diff = client.get(f"/api/runs/{plain['run_id']}/diff/{custom['run_id']}").json()
    assert diff['scout_name_a'] == 'Scout'
    assert diff['scout_name_b'] == 'ApiReplayA'
    assert diff['stage_bindings_changed'] is True


def test_campaign_inherits_stage_bindings(client):
    create_agent(client, base_profile('ApiCampScout'))
    create_agent(client, base_profile('ApiCampChecker', ['Block price claims'], ['price_claims']))
    response = client.post('/api/campaigns', json={
        'idea': IDEA, 'agent_name': 'Maker', 'scout_name': 'ApiCampScout', 'checker_name': 'ApiCampChecker'})
    assert response.status_code == 201
    week = response.json()
    assert len(week['days']) == 7
    first = client.get(f"/api/runs/{week['days'][0]['run_id']}").json()
    assert first['stage_bindings']['scout'] == 'ApiCampScout'
    assert first['stage_bindings']['checker'] == 'ApiCampChecker'
    assert first['approval_state'] == 'pending_approval'
