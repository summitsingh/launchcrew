"""Milestone M4: Facebook sign-in, identity display, honest verified health.

Mocked provider exchange only. No provider network calls, no real
credentials, no live sign-in. All subjects, names, and emails are
synthetic. Owner-confirmed live proof is recorded only through
auth.record_live_verification, never through a mocked callback.
"""

import json
from unittest.mock import AsyncMock, patch

from fastapi.responses import Response
from sqlalchemy import text

from backend import auth, store

FB_SUBJECT = 'synthetic-fb-subject-01'
FB_NAME = 'Synthetic Friend'
FB_EMAIL = 'friend@synthetic.invalid'
GOOGLE_SUBJECT = 'synthetic-google-subject-01'
GOOGLE_NAME = 'Synthetic Human'
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


def _enable_both(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://auth-test.invalid')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'demo-provider')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'demo-provider')
    monkeypatch.setenv('FACEBOOK_CLIENT_ID', 'demo-provider')
    monkeypatch.setenv('FACEBOOK_CLIENT_SECRET', 'demo-provider')


def test_facebook_status_lists_provider_when_configured(client, monkeypatch):
    _enable_both(monkeypatch)
    body = client.get('/api/auth/status').json()
    assert body['providers'] == ['google', 'facebook']
    assert body['live_verified'] is False
    assert body['display'] == ''


def test_facebook_callback_stores_display_and_keeps_token_server_side(client, monkeypatch):
    _enable_both(monkeypatch)

    async def redirect(request, uri):
        assert uri == 'https://auth-test.invalid/api/auth/facebook/callback'
        request.session['synthetic_state'] = 'nonce'
        from fastapi.responses import RedirectResponse
        return RedirectResponse('https://www.facebook.com/')

    async def exchange(request):
        assert request.session['synthetic_state'] == 'nonce'
        return {'access_token': 'demo-transient-value'}

    class _Profile:
        def json(self):
            return {'id': FB_SUBJECT, 'name': FB_NAME, 'email': FB_EMAIL}

    async def profile(*args, **kwargs):
        return _Profile()

    with patch('backend.auth.oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        factory.return_value.get = AsyncMock(side_effect=profile)
        assert client.get('/api/auth/facebook/login', follow_redirects=False).status_code == 307
        assert client.get('/api/auth/facebook/callback', follow_redirects=False).status_code == 303
        body = client.get('/api/auth/status').json()
        assert body['user'] == 'facebook:' + FB_SUBJECT
        assert body['display'] == FB_NAME
    with store.connect() as db:
        sessions = db.execute(text('SELECT data FROM auth_sessions')).scalars().all()
    assert sessions == [{'actor': 'facebook:' + FB_SUBJECT, 'display': FB_NAME}]
    assert 'demo-transient-value' not in json.dumps(sessions)


def test_facebook_email_fallback_display_when_name_missing(client, monkeypatch):
    _enable_both(monkeypatch)

    async def redirect(request, uri):
        request.session['synthetic_state'] = 'nonce'
        from fastapi.responses import RedirectResponse
        return RedirectResponse('https://www.facebook.com/')

    async def exchange(request):
        return {'access_token': 'demo-transient-value'}

    class _Profile:
        def json(self):
            return {'id': FB_SUBJECT, 'email': FB_EMAIL}

    async def profile(*args, **kwargs):
        return _Profile()

    with patch('backend.auth.oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        factory.return_value.get = AsyncMock(side_effect=profile)
        client.get('/api/auth/facebook/login', follow_redirects=False)
        client.get('/api/auth/facebook/callback', follow_redirects=False)
        assert client.get('/api/auth/status').json()['display'] == FB_EMAIL


def test_google_callback_stores_display_name(client, monkeypatch):
    _enable_both(monkeypatch)

    async def redirect(request, uri):
        request.session['synthetic_state'] = 'nonce'
        from fastapi.responses import RedirectResponse
        return RedirectResponse('https://accounts.google.com/')

    async def exchange(request):
        return {'userinfo': {'sub': GOOGLE_SUBJECT, 'name': GOOGLE_NAME,
                             'email': 'human@synthetic.invalid'},
                'access_token': 'demo-transient-value'}

    with patch('backend.auth.oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        client.get('/api/auth/google/login', follow_redirects=False)
        client.get('/api/auth/google/callback', follow_redirects=False)
        body = client.get('/api/auth/status').json()
        assert body['user'] == 'google:' + GOOGLE_SUBJECT
        assert body['display'] == GOOGLE_NAME


def _sign_in(client, monkeypatch, actor, display=''):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    response = Response()
    auth.save_session({'actor': actor, 'display': display or actor}, response)
    opaque = response.headers['set-cookie'].split(';')[0].split('=', 1)[1]
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque)


def test_facebook_approval_records_signed_in_user(client, monkeypatch):
    _enable_both(monkeypatch)
    actor = 'facebook:' + FB_SUBJECT
    _sign_in(client, monkeypatch, actor, FB_NAME)
    created = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert created.status_code == 201, created.text
    approved = client.post(f"/api/runs/{created.json()['run_id']}/approve", json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()['approvals'][0]['approved_by'] == actor
    with store.connect() as db:
        row = db.execute(text('SELECT approved_by FROM approvals WHERE run_id=:id'),
                         {'id': created.json()['run_id']}).fetchone()
        audit = db.execute(text("SELECT actor FROM audit WHERE run_id=:id AND action='approved_for_export'"),
                           {'id': created.json()['run_id']}).fetchone()
    assert row[0] == actor
    assert audit[0] == actor


def test_health_honest_until_both_providers_verified(client, monkeypatch):
    _enable_both(monkeypatch)
    _sign_in(client, monkeypatch, 'facebook:' + FB_SUBJECT, FB_NAME)
    assert client.get('/api/health').json()['auth'] == 'enabled_unverified'
    assert client.get('/api/auth/status').json()['live_verified'] is False
    auth.record_live_verification('google', 'owner-confirmed live sign-in')
    assert client.get('/api/health').json()['auth'] == 'enabled_unverified'
    assert client.get('/api/auth/status').json()['live_verified'] is False
    auth.record_live_verification('facebook', 'owner-confirmed live sign-in')
    assert client.get('/api/health').json()['auth'] == 'enabled_verified'
    assert client.get('/api/auth/status').json()['live_verified'] is True


def test_health_disabled_demo_when_auth_off(client, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'false')
    assert client.get('/api/health').json() == {
        'status': 'ok', 'auth': 'disabled_demo', 'approval_by': 'demo_placeholder'}
