"""Google-only auth wiring: fail-closed enable, status, cookie, callback, isolation.

Source-only tests with mocked provider exchange. No provider network calls,
no real credentials, no live sign-in. All subjects are synthetic.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import Response
from sqlalchemy import text

from backend import auth, store

SYN_A = 'google:synthetic-alpha-01'
SYN_B = 'google:synthetic-beta-02'
SYN_CALLBACK = 'synthetic-callback-01'
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


def _cookie(actor):
    response = Response()
    auth.save_session({'actor': actor}, response)
    return response.headers['set-cookie'].split(';')[0].split('=', 1)[1]


def _sign_in(client, monkeypatch, actor):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    opaque = _cookie(actor)
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque)
    return opaque


def _new_run(client):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    return response.json()


def test_enable_refused_without_google_config(client, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://auth-test.invalid')
    monkeypatch.delenv('GOOGLE_CLIENT_ID', raising=False)
    monkeypatch.delenv('GOOGLE_CLIENT_SECRET', raising=False)
    monkeypatch.delenv('FACEBOOK_CLIENT_ID', raising=False)
    monkeypatch.delenv('FACEBOOK_CLIENT_SECRET', raising=False)
    with pytest.raises(RuntimeError):
        auth.validate_config()
    monkeypatch.setenv('FACEBOOK_CLIENT_ID', 'demo-provider')
    monkeypatch.setenv('FACEBOOK_CLIENT_SECRET', 'demo-provider')
    with pytest.raises(RuntimeError):
        auth.validate_config()
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'demo-provider')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'demo-provider')
    auth.validate_config()


def test_enable_refused_with_invalid_base_url(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'demo-provider')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'demo-provider')
    for bad in ('', 'http://auth-test.invalid', 'https://auth-test.invalid/app',
                'https://auth-test.invalid?x=1', 'https://auth-test.invalid#x',
                'not-a-url'):
        monkeypatch.setenv('PUBLIC_BASE_URL', bad)
        with pytest.raises(RuntimeError):
            auth.validate_config()
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://auth-test.invalid')
    auth.validate_config()
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://auth-test.invalid/')
    auth.validate_config()


def test_status_google_only_providers(client, monkeypatch):
    assert client.get('/api/auth/status').json() == {
        'enabled': False, 'user': '', 'live_verified': False, 'providers': []}
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    monkeypatch.delenv('GOOGLE_CLIENT_ID', raising=False)
    monkeypatch.delenv('GOOGLE_CLIENT_SECRET', raising=False)
    monkeypatch.delenv('FACEBOOK_CLIENT_ID', raising=False)
    monkeypatch.delenv('FACEBOOK_CLIENT_SECRET', raising=False)
    assert client.get('/api/auth/status').json()['providers'] == []
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'demo-provider')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'demo-provider')
    body = client.get('/api/auth/status').json()
    assert body['providers'] == ['google']
    assert body['live_verified'] is False
    monkeypatch.setenv('FACEBOOK_CLIENT_ID', 'demo-provider')
    monkeypatch.setenv('FACEBOOK_CLIENT_SECRET', 'demo-provider')
    assert client.get('/api/auth/status').json()['providers'] == ['google', 'facebook']
    monkeypatch.setenv('AUTH_ENABLED', 'false')
    assert client.get('/api/auth/status').json()['providers'] == []


def test_facebook_login_unavailable_google_only(client, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://auth-test.invalid')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'demo-provider')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'demo-provider')
    monkeypatch.delenv('FACEBOOK_CLIENT_ID', raising=False)
    monkeypatch.delenv('FACEBOOK_CLIENT_SECRET', raising=False)
    assert client.get('/api/auth/facebook/login', follow_redirects=False).status_code == 404
    assert client.get('/api/auth/facebook/callback', follow_redirects=False).status_code == 404


def test_secure_cookie_flags_and_path():
    response = Response()
    auth.save_session({'actor': SYN_A}, response)
    cookie = response.headers['set-cookie']
    for flag in ('Secure', 'HttpOnly', 'SameSite=lax', 'Path=/api', 'Max-Age=28800'):
        assert flag in cookie


def test_google_callback_uri_exact_prod(client, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://launchcrew.summitsingh.com')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'demo-provider')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'demo-provider')

    async def redirect(request, uri):
        assert uri == 'https://launchcrew.summitsingh.com/api/auth/google/callback'
        request.session['synthetic_state'] = 'nonce'
        from fastapi.responses import RedirectResponse
        return RedirectResponse('https://accounts.google.com/')

    async def exchange(request):
        assert request.session['synthetic_state'] == 'nonce'
        return {'userinfo': {'sub': SYN_CALLBACK}, 'access_token': 'demo-transient-value'}

    with patch('backend.auth.oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        assert client.get('/api/auth/google/login', follow_redirects=False).status_code == 307
        first = client.cookies.get(auth.COOKIE)
        assert client.get('/api/auth/google/callback', follow_redirects=False).status_code == 303
        second = client.cookies.get(auth.COOKIE)
        assert second and second != first
        assert client.get('/api/auth/status').json()['user'] == 'google:' + SYN_CALLBACK
    client.cookies.set(auth.COOKIE, first)
    assert client.get('/api/queue').status_code == 401
    client.cookies.set(auth.COOKIE, second)
    assert client.get('/api/queue').status_code == 200
    with store.connect() as db:
        sessions = db.execute(text('SELECT data FROM auth_sessions')).scalars().all()
    assert sessions == [{'actor': 'google:' + SYN_CALLBACK}]
    assert 'demo-transient-value' not in json.dumps(sessions)


def test_two_synthetic_actor_isolation(client, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    run_id = _new_run(client)['run_id']
    assert client.get('/api/queue').json() != []
    _sign_in(client, monkeypatch, SYN_B)
    assert client.get('/api/queue').json() == []
    assert client.get(f'/api/runs/{run_id}').status_code == 404
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 404
    owned = _new_run(client)['run_id']
    approved = client.post(f'/api/runs/{owned}/approve', json={})
    assert approved.json()['approvals'][0]['approved_by'] == SYN_B
    _sign_in(client, monkeypatch, SYN_A)
    assert client.get(f'/api/runs/{run_id}').status_code == 200
    assert client.get(f'/api/runs/{owned}').status_code == 404
    assert approved.json()['approvals'][0]['approved_by'] != SYN_A


def test_logout_isolated_per_actor(client, monkeypatch):
    first = _sign_in(client, monkeypatch, SYN_A)
    with store.connect() as db:
        assert db.execute(text('SELECT count(*) FROM auth_sessions')).scalar() == 1
    second = _cookie(SYN_B)
    client.cookies.set(auth.COOKIE, first)
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/queue').status_code == 401
    client.cookies.set(auth.COOKIE, second)
    assert client.get('/api/queue').status_code == 200
    with store.connect() as db:
        rows = db.execute(text('SELECT data FROM auth_sessions')).scalars().all()
    assert rows == [{'actor': SYN_B}]


def test_anonymous_refused_when_enabled(client, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    assert client.get('/api/agents').status_code == 401
    assert client.get('/api/queue').status_code == 401
    assert client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'}).status_code == 401
    assert client.get('/api/memory').status_code == 401
    assert client.get('/api/campaigns').status_code == 401


def test_live_verified_false_until_proof(client, monkeypatch):
    assert client.get('/api/auth/status').json()['live_verified'] is False
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    assert client.get('/api/auth/status').json()['live_verified'] is False
    _sign_in(client, monkeypatch, SYN_A)
    assert client.get('/api/auth/status').json()['live_verified'] is False


def test_openapi_status_includes_providers_array():
    from pathlib import Path
    from backend.app import app
    doc = app.openapi()
    schema = doc['paths']['/api/auth/status']['get']['responses']['200']['content']['application/json']['schema']
    kinds = schema['additionalProperties']['anyOf']
    assert {'type': 'string'} in kinds
    assert {'type': 'boolean'} in kinds
    assert {'items': {'type': 'string'}, 'type': 'array'} in kinds
    committed = json.loads(Path('backend/openapi.json').read_text())
    assert committed['paths']['/api/auth/status'] == doc['paths']['/api/auth/status']
