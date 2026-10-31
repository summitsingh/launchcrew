"""Milestone M8: custom agent save errors, stage execution, crew presets.

Postgres-backed. Deterministic fixtures only, no live model calls.
"""
from unittest.mock import patch
import pytest
from launchcrew import run

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'

EXPECTED_POLICIES = {
    'Support': ['price_claims'],
    'Designer': ['superlatives'],
    'Analyst': ['cliches'],
    'Research': ['custom:moonshot'],
}

EXPECTED_ROLES = {
    'Support': 'Intended FAQ Reply Drafter',
    'Designer': 'Intended Photo Layout Suggestion Helper',
    'Analyst': 'Intended Outcome Summary Helper',
    'Research': 'Intended Sourced Fact Suggestion Helper',
}


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


def test_custom_agent_validation_surfaces_reason(client):
    profile = base_profile('M8BadRules')
    profile['decision_rules'] = []
    response = client.post('/api/agents', json=profile)
    assert response.status_code == 422
    detail = response.json()['detail']
    assert isinstance(detail, str), response.json()
    assert detail != 'Validation failed', response.json()
    assert 'Decision rules' in detail, response.json()


def test_custom_agent_unsupported_tool_surfaces_reason(client):
    profile = base_profile('M8BadTool')
    profile['tools_allowed'] = ['facts_file', 'network_search']
    response = client.post('/api/agents', json=profile)
    assert response.status_code == 422
    assert 'Unsupported tool' in response.json()['detail'], response.json()


def test_custom_agent_duplicate_name_surfaces_conflict(client):
    first = client.post('/api/agents', json=base_profile('M8Dup'))
    assert first.status_code == 201, first.json()
    second = client.post('/api/agents', json=base_profile('M8Dup'))
    assert second.status_code == 409
    assert 'already exists' in second.json()['detail'], second.json()


def test_saved_custom_agent_selects_stage_and_executes(client):
    created = client.post('/api/agents', json=base_profile('M8StageMaker'))
    assert created.status_code == 201, created.json()
    response = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'M8StageMaker', 'maker_name': 'M8StageMaker'})
    assert response.status_code == 201, response.json()
    receipt = response.json()
    assert receipt['stage_bindings']['maker'] == 'M8StageMaker'
    assert receipt['stage_agents']['maker']['personality'] == 'Custom personality for M8StageMaker'
    assert receipt['approval_state'] == 'pending_approval'


def test_crew_presets_seeded_and_selectable(client):
    names = {profile['name'] for profile in client.get('/api/agents').json()}
    for preset in ('Support', 'Designer', 'Analyst', 'Research'):
        assert preset in names, names


def test_crew_preset_prompts_are_distinct(client):
    bodies = {name: client.get('/api/agents/' + name).json()
              for name in ('Support', 'Designer', 'Analyst', 'Research')}
    roles = {body['role'] for body in bodies.values()}
    assert roles == set(EXPECTED_ROLES.values()), roles
    personalities = {body['personality'] for body in bodies.values()}
    assert len(personalities) == 4, personalities


def test_crew_preset_checker_policies_are_distinct(client):
    seen = {}
    for name, expected in EXPECTED_POLICIES.items():
        preview = client.post('/api/agents/' + name + '/preview', json={'idea': IDEA})
        assert preview.status_code == 200, preview.json()
        enforced = preview.json()['checker_enforcement']['enforced_policies']
        assert enforced == expected, (name, enforced)
        seen[name] = tuple(enforced)
    assert len(set(seen.values())) == 4, seen


def _run_with_checker(client, checker):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'checker_name': checker})
    assert response.status_code == 201, response.json()
    return response.json()


def test_support_preset_executes_price_policy_on_spine(client):
    receipt = _run_with_checker(client, 'Support')
    assert receipt['stage_bindings']['checker'] == 'Support'
    assert receipt['stage_agents']['checker']['role'] == EXPECTED_ROLES['Support']
    assert receipt['checker_enforcement']['effective_policies'] == ['price_claims']
    assert '$49' in [item['claim'] for item in receipt['checker_v1']['blocked_claims']]


def test_designer_preset_executes_superlative_policy_on_spine(client):
    receipt = _run_with_checker(client, 'Designer')
    assert receipt['stage_bindings']['checker'] == 'Designer'
    assert receipt['stage_agents']['checker']['role'] == EXPECTED_ROLES['Designer']
    assert receipt['checker_enforcement']['effective_policies'] == ['superlatives']


def test_designer_preset_blocks_seeded_superlative(client):
    response = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker', 'checker_name': 'Designer',
        'seed_unverified_claim': True})
    assert response.status_code == 201, response.json()
    receipt = response.json()
    assert 'best in Texas' in [item['claim'] for item in receipt['checker_v1']['blocked_claims']]


def test_analyst_preset_executes_cliche_policy_on_spine(client):
    receipt = _run_with_checker(client, 'Analyst')
    assert receipt['stage_bindings']['checker'] == 'Analyst'
    assert receipt['stage_agents']['checker']['role'] == EXPECTED_ROLES['Analyst']
    assert receipt['checker_enforcement']['effective_policies'] == ['cliches']


def test_research_preset_executes_custom_policy_on_spine(client):
    receipt = _run_with_checker(client, 'Research')
    assert receipt['stage_bindings']['checker'] == 'Research'
    assert receipt['stage_agents']['checker']['role'] == EXPECTED_ROLES['Research']
    assert receipt['checker_enforcement']['effective_policies'] == ['custom:moonshot']


def test_research_custom_term_blocks_exact_match_only():
    from launchcrew.checker_policies import policy_blocks
    assert policy_blocks('custom:moonshot', 'Our moonshot launch plan') is True
    assert policy_blocks('custom:moonshot', 'Plain vegan leather wallet') is False
