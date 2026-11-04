"""SC1 brand account connections and per-account live capabilities.

Priority 8 platforms connect end to end with encrypted server-side
tokens and live capability discovery; the 4 flag-gated platforms stay
behind capability flags. Personal accounts are refused, tokens never
appear in API responses or receipts, and one-tap disconnect deletes the
token while past approvals and exports still work.
"""
from unittest.mock import patch

import pytest
from sqlalchemy import text

from launchcrew import run as run_mod

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
RAW_TOKEN = 'test-provider-token-abc123'

PRIORITY = ['instagram', 'facebook', 'threads', 'x', 'tiktok', 'pinterest', 'youtube', 'linkedin']
FLAGGED = ['reddit', 'wordpress', 'discord', 'telegram']
FLAG_BY_PLATFORM = {
    'reddit': 'LAUNCHCREW_ENABLE_REDDIT_CONNECT',
    'wordpress': 'LAUNCHCREW_ENABLE_WORDPRESS_CONNECT',
    'discord': 'LAUNCHCREW_ENABLE_DISCORD_CONNECT',
    'telegram': 'LAUNCHCREW_ENABLE_TELEGRAM_CONNECT',
}


@pytest.fixture(autouse=True)
def deterministic_pipeline():
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


def approve_export(client, run_id):
    revision = client.get(f'/api/runs/{run_id}').json().get('revision', 0)
    approved = client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': revision})
    assert approved.status_code == 200, approved.text
    exported = client.post(f'/api/runs/{run_id}/export', json={'expected_revision': revision})
    assert exported.status_code == 200, exported.text
    return exported.json()


def connect_brand(client, platform, token=RAW_TOKEN, handle=None, scopes=None, account_type='brand'):
    body = {'code': token, 'account_type': account_type,
            'handle': handle or ('@brand-%s' % platform),
            'account_name': 'Brand %s' % platform,
            'scopes': scopes if scopes is not None else ['brand_publish', 'brand_capabilities_read']}
    response = client.post(f'/api/social/connections/{platform}/callback', json=body)
    return response


def raw_response_text(response):
    try:
        return response.text
    except Exception:
        return ''


def test_platform_registry_priority_vs_flag_gated(client, test_engine):
    response = client.get('/api/social/platforms')
    assert response.status_code == 200, response.text
    rows = {entry['platform']: entry for entry in response.json()}
    assert set(rows) == set(PRIORITY + FLAGGED)
    for platform in PRIORITY:
        entry = rows[platform]
        assert entry['priority'] is True
        assert entry['tier'] == 'priority'
        assert entry['enabled'] is True
    for platform in FLAGGED:
        entry = rows[platform]
        assert entry['priority'] is False
        assert entry['tier'] == 'flag_gated'
        assert entry['enabled'] is False
        assert entry['status'] == 'review_pending_flag'
        assert FLAG_BY_PLATFORM[platform] in (entry['flag_name'] or '')
        assert FLAG_BY_PLATFORM[platform] in (entry['limitation'] or '')


def test_flag_gated_connect_refused_naming_flag(client, test_engine):
    for platform in FLAGGED:
        initiated = client.post(f'/api/social/connections/{platform}/connect', json={'account_type': 'brand'})
        assert initiated.status_code == 409, initiated.text
        assert FLAG_BY_PLATFORM[platform] in initiated.text
        completed = connect_brand(client, platform)
        assert completed.status_code == 409, completed.text
        assert FLAG_BY_PLATFORM[platform] in completed.text


def test_initiate_limitation_follows_connection_state(client):
    from launchcrew import social_connections as social_mod
    assert social_mod.limitation_for('instagram') is not None
    assert 'connected yet' in (social_mod.limitation_for('instagram') or '')
    assert social_mod.limitation_for('instagram', connected=True) is None
    assert social_mod.describe_platform('instagram', connected=True)['limitation'] is None
    listed = {entry['platform']: entry for entry in social_mod.list_platforms(['instagram'])}
    assert listed['instagram']['limitation'] is None
    assert listed['facebook']['limitation'] is not None


def test_personal_account_refused(client, test_engine):
    initiated = client.post('/api/social/connections/instagram/connect', json={'account_type': 'personal'})
    assert initiated.status_code == 422, initiated.text
    assert 'brand' in initiated.text.lower()
    refused = connect_brand(client, 'instagram', account_type='personal')
    assert refused.status_code == 422, refused.text
    assert 'brand' in refused.text.lower()


def test_brand_connect_encrypts_and_lists_live_capabilities(client, test_engine):
    connected = connect_brand(client, 'instagram')
    assert connected.status_code == 200, connected.text
    body = connected.json()
    assert body['platform'] == 'instagram'
    assert body['account_type'] == 'brand'
    assert body['status'] == 'connected'
    assert body['token_present'] is True
    assert body['has_token'] is True
    assert body['token_security'] == 'encrypted_at_rest'
    assert 'encrypted_token' not in body
    assert RAW_TOKEN not in raw_response_text(connected)
    assert body['scopes_plain']
    assert any('Publish approved posts' in entry or 'capabilities' in entry.lower()
               for entry in body['scopes_plain'])
    capabilities = body['capabilities']
    assert capabilities.get('source') == 'static_baseline'
    assert capabilities.get('caption_limit')
    assert capabilities.get('allowed_formats')
    assert 'encrypted_token' not in capabilities

    with test_engine.begin() as connection:
        row = connection.execute(
            text('SELECT encrypted_token, account_type, status FROM social_connections'
                 " WHERE workspace_id='demo' AND platform='instagram'")).mappings().first()
    assert row is not None
    assert row['encrypted_token']
    assert RAW_TOKEN not in str(row['encrypted_token'])
    assert row['account_type'] == 'brand'
    assert row['status'] == 'connected'

    listed = client.get('/api/social/connections')
    assert listed.status_code == 200, listed.text
    assert RAW_TOKEN not in listed.text
    entries = {entry['platform']: entry for entry in listed.json()}
    assert entries['instagram']['token_present'] is True
    assert 'encrypted_token' not in entries['instagram']

    table = client.get('/api/channel-capabilities')
    assert table.status_code == 200, table.text
    rows = {entry['channel']: entry for entry in table.json()}
    assert rows['instagram']['source'] == 'static_baseline'
    assert rows['instagram']['connected'] is True
    assert rows['instagram']['caption_limit'] == capabilities['caption_limit']


def test_token_never_in_receipts_or_exports(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    assert RAW_TOKEN not in client.get(f'/api/runs/{run_id}').text
    connected = connect_brand(client, 'x', token='x-token-999', handle='@brand-x')
    assert connected.status_code == 200, connected.text
    reread = client.get(f'/api/runs/{run_id}')
    assert reread.status_code == 200, reread.text
    assert 'x-token-999' not in reread.text
    approve_export(client, run_id)
    exported = client.get(f'/api/runs/{run_id}')
    assert 'x-token-999' not in exported.text
    bundle = client.get(f'/api/runs/{run_id}/export/bundle')
    assert bundle.status_code == 200, bundle.text
    assert 'x-token-999' not in bundle.text
    variants = client.get(f'/api/runs/{run_id}/channel-variants')
    assert variants.status_code == 200, variants.text
    assert 'x-token-999' not in variants.text


def test_disconnect_wipes_token_but_keeps_receipts(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    connected = connect_brand(client, 'facebook')
    assert connected.status_code == 200, connected.text
    removed = client.post('/api/social/connections/facebook/disconnect')
    assert removed.status_code == 200, removed.text
    body = removed.json()
    assert body['status'] == 'disconnected'
    assert body['token_present'] is False
    assert body['has_token'] is False
    assert body['token_security'] == 'no_token_stored'
    assert RAW_TOKEN not in removed.text

    with test_engine.begin() as connection:
        row = connection.execute(
            text('SELECT encrypted_token, status FROM social_connections'
                 " WHERE workspace_id='demo' AND platform='facebook'")).mappings().first()
    assert row is not None
    assert row['encrypted_token'] is None
    assert row['status'] == 'disconnected'

    table = client.get('/api/channel-capabilities')
    assert table.status_code == 200, table.text
    rows = {entry['channel']: entry for entry in table.json()}
    assert rows['facebook']['source'] == 'baseline'

    reread = client.get(f'/api/runs/{run_id}')
    assert reread.status_code == 200, reread.text
    assert reread.json()['approval_state'] == 'approved_for_export'
    bundle = client.get(f'/api/runs/{run_id}/export/bundle')
    assert bundle.status_code == 200, bundle.text
    markdown = client.get(f'/api/runs/{run_id}/export/markdown')
    assert markdown.status_code == 200, markdown.text
