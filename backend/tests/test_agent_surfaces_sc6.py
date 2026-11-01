"""SC6 agent surfaces on Postgres: workspace keys, REST, MCP, CLI, skill.

Deterministic fixtures only, no live model calls, no real platform
calls. One backend backs four surfaces: the Web UI, the REST API, the
hosted MCP server, and the CLI all read and write the same workspace
state. The validate gate and refusal reasons are identical on every
surface, and the installable skill teaches the validate-then-apply
pattern with those same refusal rules.
"""
import json
from unittest.mock import patch

import pytest

from launchcrew import cli as cli_mod

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


def make_ready_slot(client, run_id=None):
    receipt = new_run(client) if run_id is None else None
    run_id = run_id or receipt['run_id']
    slot = new_slot(client, run_id)
    approve(client, run_id)
    channel = valid_channel(client, run_id)
    patched = client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                           json={'selected_channels': [channel]})
    assert patched.status_code == 200, patched.text
    approved = client.post(f'/api/calendar/slots/{slot["id"]}/approve-channels',
                           json={'channels': [channel], 'expected_revision': 0})
    assert approved.status_code == 200, approved.text
    marked = client.post(f'/api/calendar/slots/{slot["id"]}/mark-ready')
    assert marked.status_code == 200, marked.text
    return run_id, slot['id'], channel


def make_key(client, label='test key'):
    response = client.post('/api/agent-surfaces/keys', json={'label': label})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['raw_key'].startswith('lc_wk_')
    assert body['id'].startswith('wkey_')
    return body


def key_headers(raw_key):
    return {'X-Workspace-Key': raw_key}


def bearer_headers(raw_key):
    return {'Authorization': 'Bearer ' + raw_key}


def test_workspace_key_lifecycle_and_closed_refusals(client):
    created = make_key(client)
    listed = client.get('/api/agent-surfaces/keys')
    assert listed.status_code == 200, listed.text
    entries = listed.json()
    assert [entry['id'] for entry in entries] == [created['id']]
    assert 'raw_key' not in entries[0]
    assert entries[0]['key_prefix'] == created['raw_key'][:12]
    assert entries[0]['revoked'] is False

    refused = client.get('/api/agent/accounts', headers=key_headers('lc_wk_missing'))
    assert refused.status_code == 401, refused.text
    assert refused.json()['detail'] == 'invalid_or_revoked_workspace_key'

    missing = client.get('/api/agent/accounts')
    assert missing.status_code in (200, 401)

    revoked = client.post(f'/api/agent-surfaces/keys/{created["id"]}/revoke')
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()['revoked'] is True

    after = client.get('/api/agent/accounts', headers=key_headers(created['raw_key']))
    assert after.status_code == 401, after.text
    assert after.json()['detail'] == 'invalid_or_revoked_workspace_key'

    assert client.post('/api/agent-surfaces/keys/does_not_exist/revoke').status_code == 404


def test_rest_workspace_key_covers_all_six_operations(client):
    created = make_key(client)
    headers = key_headers(created['raw_key'])

    accounts = client.get('/api/agent/accounts', headers=headers)
    assert accounts.status_code == 200, accounts.text
    assert accounts.json() == client.get('/api/social/connections').json()

    capabilities = client.get('/api/agent/capabilities', headers=headers)
    assert capabilities.status_code == 200, capabilities.text
    assert capabilities.json() == client.get('/api/channel-capabilities').json()

    upload = client.post('/api/agent/upload', headers=headers,
                         json={'filename': 'shot.png', 'width': 1080, 'height': 1350})
    assert upload.status_code == 201, upload.text
    assert upload.json()['id'] in [asset['id'] for asset in client.get('/api/media/assets').json()]

    receipt = new_run(client)
    slot = new_slot(client, receipt['run_id'])
    validate = client.post('/api/agent/validate', headers=headers,
                           json={'slot_id': slot['id']})
    assert validate.status_code == 409, validate.text
    detail = validate.json()['detail']
    web_ui = client.get(f'/api/calendar/slots/{slot["id"]}/validate-ready').json()
    assert detail['failing_conditions'] == web_ui['failing_conditions']
    assert detail['details'] == web_ui['details']

    status = client.get(f'/api/agent/runs/{receipt["run_id"]}/status', headers=headers)
    assert status.status_code == 200, status.text
    assert status.json()['approval_state'] == 'pending_approval'
    overview = client.get('/api/agent/status', headers=headers)
    assert overview.status_code == 200, overview.text
    assert overview.json()['schedule']

    bearer = client.get('/api/agent/status', headers=bearer_headers(created['raw_key']))
    assert bearer.status_code == 200, bearer.text


def test_cli_applies_exported_schedule_unchanged(client, tmp_path):
    run_id, slot_id, _ = make_ready_slot(client)
    exported = client.get('/api/calendar/schedule-export')
    assert exported.status_code == 200, exported.text
    document = exported.json()
    assert document['schema_version'] == 'schedule-export/v1'
    assert [entry['slot_id'] for entry in document['ready_slots']] == [slot_id]

    schedule_path = tmp_path / 'schedule-export.json'
    schedule_path.write_text(json.dumps(document), encoding='utf-8')

    demoted = client.patch(f'/api/calendar/slots/{slot_id}/schedule',
                           json={'planned_time': '10:15'})
    assert demoted.status_code == 200, demoted.text
    assert demoted.json()['schedule_state'] == 'draft'

    created = make_key(client, label='cli key')
    result = cli_mod.main(['apply', str(schedule_path), '--workspace-key', created['raw_key']],
                          client=client)
    assert result['applied_via'] == 'agent_apply'
    assert result['applied_slot_ids'] == [slot_id]
    assert result['refused_slots'] == []

    reread = client.get('/api/calendar/slots?start_date=2026-11-01&end_date=2026-11-30')
    assert reread.status_code == 200, reread.text
    states = {slot['id']: slot['schedule_state'] for slot in reread.json()}
    assert states[slot_id] == 'ready'

    run_status = cli_mod.main(['run-status', '--run-id', run_id,
                               '--workspace-key', created['raw_key']], client=client)
    assert run_status['approval_state'] == 'approved_for_export'
    accounts = cli_mod.main(['accounts', '--workspace-key', created['raw_key']], client=client)
    assert accounts == client.get('/api/social/connections').json()


def test_mcp_validate_refusal_matches_web_ui(client):
    receipt = new_run(client)
    slot = new_slot(client, receipt['run_id'])
    created = make_key(client)
    headers = key_headers(created['raw_key'])

    web_ui = client.get(f'/api/calendar/slots/{slot["id"]}/validate-ready').json()
    assert web_ui['ready_eligible'] is False
    assert 'pack_not_approved' in web_ui['failing_conditions']

    refused = client.post('/api/mcp/call', headers=headers,
                          json={'name': 'launchcrew_validate',
                                'arguments': {'slot_id': slot['id']}})
    assert refused.status_code == 200, refused.text
    body = refused.json()
    assert body['is_error'] is True
    assert body['failing_conditions'] == web_ui['failing_conditions']
    assert body['details'] == web_ui['details']
    assert body['checks'] == web_ui['checks']
    assert body['format_reason'] == web_ui['format_reason']
    assert 'pack_not_approved' in body['reason'] or body['details']

    tools = client.post('/api/mcp/call', headers=headers,
                        json={'name': 'launchcrew_run_status',
                              'arguments': {'run_id': receipt['run_id']}})
    assert tools.status_code == 200, tools.text
    assert tools.json()['approval_state'] == 'pending_approval'

    listing = client.get('/api/mcp/tools', headers=headers)
    assert listing.status_code == 200, listing.text
    names = [tool['name'] for tool in listing.json()['tools']]
    assert names == ['launchcrew_accounts', 'launchcrew_capabilities', 'launchcrew_upload',
                     'launchcrew_validate', 'launchcrew_apply', 'launchcrew_run_status']

    unknown = client.post('/api/mcp/call', headers=headers,
                          json={'name': 'launchcrew_unknown', 'arguments': {}})
    assert unknown.status_code == 404, unknown.text
    assert client.post('/api/mcp/call',
                       json={'name': 'launchcrew_validate',
                             'arguments': {'slot_id': slot['id']}}).status_code in (200, 401)


def test_skill_endpoint_teaches_validate_then_apply(client):
    response = client.get('/api/agent-surfaces/skill')
    assert response.status_code == 200, response.text
    skill = response.json()
    assert skill['name'] == 'launchcrew-socialclaw'
    assert skill['version']
    assert skill['tools'] == ['launchcrew_accounts', 'launchcrew_capabilities', 'launchcrew_upload',
                              'launchcrew_validate', 'launchcrew_apply', 'launchcrew_run_status']
    codes = [rule['code'] for rule in skill['refusal_rules']]
    for code in ('pack_not_approved', 'format_check_failed', 'unapproved_channel_variants',
                 'invalid_or_revoked_workspace_key'):
        assert code in codes
    content = skill['content_markdown']
    assert 'validate' in content.lower() and 'apply' in content.lower()
    assert 'schedule-export/v1' in content
    assert 'launchcrew_validate' in content
    assert 'launchcrew apply schedule-export.json' in content
    for code in ('pack_not_approved', 'format_check_failed', 'unapproved_channel_variants'):
        assert code in content
