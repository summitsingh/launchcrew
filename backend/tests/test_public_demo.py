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
