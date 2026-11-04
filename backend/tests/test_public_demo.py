"""Public access and mutation boundaries, without provider calls."""
import pytest


@pytest.mark.parametrize('method,path', [
    ('get', '/api/auth/status'), ('get', '/api/auth/session'),
    ('post', '/api/auth/logout'), ('get', '/api/auth/google/login'),
    ('get', '/api/auth/google/callback'), ('get', '/api/auth/facebook/login'),
    ('get', '/api/auth/facebook/callback'), ('post', '/api/auth/other/start'),
])
def test_public_auth_routes_unavailable(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 404


def test_public_workspace_reads(client):
    assert client.get('/api/health').json()['auth'] == 'disabled_demo'
    for path in ['/api/agents', '/api/queue', '/api/social/connections', '/api/model-capabilities']:
        assert client.get(path).status_code == 200, path


@pytest.mark.parametrize('method,path', [
    ('post', '/api/social/connections/instagram/connect'),
    ('post', '/api/social/connections/instagram/callback'),
    ('post', '/api/social/connections/instagram/complete'),
    ('post', '/api/social/connections/instagram/disconnect'),
    ('delete', '/api/social/connections/instagram'),
    ('get', '/api/social/connections/instagram/callback'),
    ('post', '/api/drive-import/picker-token'),
])
def test_public_connection_mutations_locked_before_validation(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 403
    assert response.json() == {'detail': 'Connection management is locked in public demo mode.'}


def test_public_publish_execution_is_available(client):
    # A missing slot reaches normal resource validation, not a public-mode refusal.
    assert client.post('/api/publish/slots/missing/execute', json={}).status_code == 404


def test_roster_excludes_only_known_verification_agents(client, test_engine):
    from sqlalchemy import text
    profile = client.get('/api/agents/Maker').json()
    for name in ['VerifyClone', 'VerifyScout', 'OwnerMaker']:
        response = client.post('/api/agents', json={**profile, 'name': name})
        assert response.status_code == 201
    names = {item['name'] for item in client.get('/api/agents').json()}
    assert {'Scout', 'Maker', 'Checker', 'OwnerMaker'} <= names
    assert not {'VerifyClone', 'VerifyScout'} & names
    with test_engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM agents WHERE name IN ('verifyclone','verifyscout')")).scalar() == 2


def test_public_connections_expose_storage_state_without_token_material(client, monkeypatch):
    from backend import auth
    from backend.app import app
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    app.dependency_overrides[auth.actor] = lambda: 'demo_placeholder'
    token = 'synthetic-brand-credential'
    connected = client.post('/api/social/connections/instagram/callback', json={
        'token': token, 'account_type': 'brand', 'handle': '@synthetic-brand',
        'scopes': ['brand_publish'],
    })
    assert connected.status_code == 200
    monkeypatch.setenv('AUTH_ENABLED', 'false')
    response = client.get('/api/social/connections')
    assert response.status_code == 200
    assert token not in response.text
    connection = next(item for item in response.json() if item['platform'] == 'instagram')
    assert connection['token_present'] is True
    assert connection['token_security'] == 'encrypted_at_rest'
    assert not {'token', 'access_token', 'encrypted_token', 'code'} & connection.keys()
    assert client.get('/api/publish/status').json()['kill_switch']['paused'] is False
