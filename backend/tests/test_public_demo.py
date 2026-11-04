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
