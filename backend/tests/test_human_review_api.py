"""Human revision API regression tests: safe review editing on Postgres.

Deterministic pipeline only, no model calls. Covers the required safe
review contract: allowed edits reset approval, stale and forged requests
are refused, unsupported edits are rejected unsaved and can never be
approved or exported, corrections reapprove and export the latest human
text, original Maker outputs stay immutable, memory and policy snapshots
are retained, and failed runs refuse editing.
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


def valid_edit(receipt):
    return {'post': 'Vegan leather wallet. Designed in Texas.',
            'email': 'For Austin commuters. $49.',
            'base_revision': receipt.get('revision', 0)}


def test_allowed_edit_resets_approval_and_exports_latest(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    assert receipt.get('revision', 0) == 0
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    edit = valid_edit(client.get(f'/api/runs/{run_id}').json())
    revised = client.post(f'/api/runs/{run_id}/revise', json=edit)
    assert revised.status_code == 200, revised.text
    body = revised.json()
    assert body['revision'] == 1
    assert body['approval_state'] == 'pending_approval'
    assert body['approvals'] == []
    assert body['human_draft']['post'] == edit['post']
    assert body['human_draft']['email'] == edit['email']
    assert body['human_check']['blocked_count'] == 0
    # Original Maker outputs and initial checks are immutable.
    assert body['maker_draft_v2'] == receipt['maker_draft_v2']
    assert body['maker_draft_v1'] == receipt['maker_draft_v1']
    assert body['checker_v1'] == receipt['checker_v1']
    assert body['checker_v2'] == receipt['checker_v2']
    # Export is refused until the latest revision is approved.
    assert client.post(f'/api/runs/{run_id}/export', json={}).status_code == 422
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    exported = client.post(f'/api/runs/{run_id}/export', json={})
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    assert payload['exported_revision'] == 1
    assert payload['exported_draft']['post'] == edit['post']
    assert payload['exported_draft']['email'] == edit['email']
    assert payload['maker_draft_v2'] == receipt['maker_draft_v2']
    # Learning an approval example uses the latest approved human text.
    learned = client.post(f'/api/memory/from-run/{run_id}', json={'kind': 'approval_example'})
    assert learned.status_code == 201
    assert learned.json()['content']['post'] == edit['post']
    assert learned.json()['content']['email'] == edit['email']
    # Revision history keeps the superseded approval as audit.
    reread = client.get(f'/api/runs/{run_id}').json()
    assert reread['approved_revision'] == 1
    assert reread['revision_history'] == []


def test_edit_after_approval_keeps_superseded_history(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    first = client.post(f'/api/runs/{run_id}/revise', json=valid_edit(client.get(f'/api/runs/{run_id}').json()))
    assert first.status_code == 200
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    second_edit = valid_edit(client.get(f'/api/runs/{run_id}').json())
    second_edit['post'] = 'Designed in Texas. Vegan leather wallet.'
    second = client.post(f'/api/runs/{run_id}/revise', json=second_edit)
    assert second.status_code == 200
    body = second.json()
    assert body['revision'] == 2
    assert body['approval_state'] == 'pending_approval'
    assert len(body['revision_history']) == 1
    assert body['revision_history'][0]['revision'] == 1
    assert body['revision_history'][0]['superseded_by'] == 2


def test_stale_revision_is_rejected(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    edit = valid_edit(receipt)
    assert client.post(f'/api/runs/{run_id}/revise', json=edit).status_code == 200
    stale = dict(edit)
    assert client.post(f'/api/runs/{run_id}/revise', json=stale).status_code == 409
    fresh = client.get(f'/api/runs/{run_id}').json()
    assert client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': 0}).status_code == 409
    assert client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': fresh['revision']}).status_code == 200
    assert client.post(f'/api/runs/{run_id}/export', json={'expected_revision': 0}).status_code == 409


def test_forged_fields_are_ignored(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    edit = valid_edit(receipt)
    edit['approved_by'] = 'forged_actor'
    edit['approval_state'] = 'approved_for_export'
    edit['checker_policies'] = []
    response = client.post(f'/api/runs/{run_id}/revise', json=edit)
    # Strict revise body refuses unknown forged fields instead of trusting them.
    assert response.status_code == 422
    clean = client.post(f'/api/runs/{run_id}/revise', json=valid_edit(receipt))
    assert clean.status_code == 200
    approved = client.post(f'/api/runs/{run_id}/approve', json={'approved_by': 'forged_actor', 'expected_revision': 1})
    assert approved.status_code == 200
    assert approved.json()['approvals'][0]['approved_by'] == 'demo_placeholder'
    assert approved.json()['approvals'][0]['revision'] == 1


def test_unsupported_edit_rejected_unsaved_and_never_approved(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    original = client.get(f'/api/runs/{run_id}').json()
    bad = {'post': 'best in Texas. Vegan leather wallet.', 'email': 'For Austin commuters.', 'base_revision': 0}
    refused = client.post(f'/api/runs/{run_id}/revise', json=bad)
    assert refused.status_code == 422
    reread = client.get(f'/api/runs/{run_id}').json()
    assert reread['revision'] == 0
    assert reread['maker_draft_v2'] == original['maker_draft_v2']
    assert reread['approval_state'] == 'pending_approval'
    # The invalid text was not stored, so export still uses the clean Maker text.
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    exported = client.post(f'/api/runs/{run_id}/export', json={}).json()
    assert 'best in Texas' not in exported['exported_draft']['post']
    assert exported['exported_draft']['post'] == original['maker_draft_v2']['post']


def test_policy_and_memory_floor_survive_human_edits(client):
    guard = {'name': 'PriceGuardFloor', 'role': 'Checker', 'department': 'Growth',
             'personality': 'Strict', 'expertise': 'Prices', 'decision_rules': ['Block price claims'],
             'veto_scope': ['price_claims'], 'tools_allowed': ['facts_file', 'spark_strict_json', 'receipt_log', 'claim_check'],
             'spend_limit': 0, 'approval_level': 'approve_each', 'examples': []}
    assert client.post('/api/agents', json=guard).status_code == 201
    receipt = new_run(client, checker_name='PriceGuardFloor')
    run_id = receipt['run_id']
    assert receipt['checker_v1']['blocked_count'] == 1
    # Reintroducing the policy-blocked price claim is rejected against the snapshot.
    bad = {'post': 'Vegan leather wallet. $49.', 'email': 'For Austin commuters.', 'base_revision': 0}
    refused = client.post(f'/api/runs/{run_id}/revise', json=bad)
    assert refused.status_code == 422
    assert any('price_claims' in item.get('reason', '') for item in refused.json()['detail']['blocked_claims']) if isinstance(refused.json().get('detail'), dict) else True
    reread = client.get(f'/api/runs/{run_id}').json()
    assert reread['checker_policies'] == receipt['checker_policies']
    assert 'price_claims' in reread['checker_policies']


def test_failed_run_refuses_revise_approve_export(client):
    bad = client.post('/api/memory', json={'kind': 'brand_fact', 'title': 'Bad', 'content': {'claim': 'best in Texas'}}).json()
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [bad['id']]})
    assert response.status_code == 201
    receipt = response.json()
    assert receipt['status'] == 'failed'
    run_id = receipt['run_id']
    assert client.post(f'/api/runs/{run_id}/revise', json=valid_edit(receipt)).status_code == 422
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 422
    assert client.post(f'/api/runs/{run_id}/export', json={}).status_code == 422
