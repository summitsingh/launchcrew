"""Auth hardening tests: rotation, expiry, failed runs, signed-in approval, logout.

All provider interaction is mocked or local. No provider network calls, no real
credentials, and no live sign-in. Uses the shared client fixture from conftest,
which truncates agents, runs, memory, approvals, audit, and auth_sessions.
"""
import json
from unittest.mock import AsyncMock, patch

from fastapi.responses import Response
from sqlalchemy import text

from backend import auth, store


ACTOR = 'google:demo-test-subject'


def save_actor_session(actor=ACTOR):
    response = Response()
    auth.save_session({'actor': actor}, response)
    opaque = response.headers['set-cookie'].split(';')[0].split('=', 1)[1]
    return opaque


def enable_auth(client, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    return client


def signed_in(client, monkeypatch, actor=ACTOR):
    enable_auth(client, monkeypatch)
    opaque = save_actor_session(actor)
    client.cookies.set(auth.COOKIE, opaque)
    return opaque


def new_run(client, **extra):
    response = client.post('/api/runs', json={
        'idea': 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram',
        'agent_name': 'Maker', **extra})
    assert response.status_code == 201
    return response.json()


def test_rotation_direct_save_invalidates_old_session(client, monkeypatch):
    enable_auth(client, monkeypatch)
    old = save_actor_session()
    response = Response()
    auth.save_session({'actor': ACTOR}, response, old=old)
    new = response.headers['set-cookie'].split(';')[0].split('=', 1)[1]
    assert new != old
    with store.connect() as db:
        assert db.execute(text('SELECT count(*) FROM auth_sessions')).scalar() == 1
    client.cookies.set(auth.COOKIE, old)
    assert client.get('/api/queue').status_code == 401
    client.cookies.set(auth.COOKIE, new)
    assert client.get('/api/queue').status_code == 200


def test_rotation_mocked_callback_invalidates_old_cookie(client, monkeypatch):
    enable_auth(client, monkeypatch)
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://testserver')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'demo-provider')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'demo-provider')

    async def redirect(request, uri):
        assert uri == 'https://testserver/api/auth/google/callback'
        request.session['demo_state'] = 'nonce'
        from fastapi.responses import RedirectResponse
        return RedirectResponse('https://accounts.google.com/')

    async def exchange(request):
        assert request.session['demo_state'] == 'nonce'
        return {'userinfo': {'sub': 'demo-test-subject'}, 'access_token': 'demo-transient-value'}

    with patch('backend.auth.oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        response = client.get('/api/auth/google/login', follow_redirects=False)
        assert response.status_code == 307
        first = client.cookies.get(auth.COOKIE)
        response = client.get('/api/auth/google/callback', follow_redirects=False)
        assert response.status_code == 303
        second = client.cookies.get(auth.COOKIE)
        assert second and second != first
        assert client.get('/api/auth/status').json()['user'] == ACTOR
    # The pre-callback cookie must no longer open a protected endpoint.
    client.cookies.set(auth.COOKIE, first)
    assert client.get('/api/queue').status_code == 401
    client.cookies.set(auth.COOKIE, second)
    assert client.get('/api/queue').status_code == 200
    with store.connect() as db:
        sessions = db.execute(text('SELECT data FROM auth_sessions')).scalars().all()
    assert sessions == [{'actor': ACTOR}]
    assert 'demo-transient-value' not in json.dumps(sessions)


def test_expired_session_refused_and_status_empty(client, monkeypatch):
    opaque = signed_in(client, monkeypatch)
    assert client.get('/api/queue').status_code == 200
    with store.connect() as db:
        db.execute(text("UPDATE auth_sessions SET expires_at=now()-interval '1 second'"))
    assert client.get('/api/queue').status_code == 401
    assert client.get('/api/auth/status').json() == {
        'enabled': True, 'user': '', 'live_verified': False, 'providers': []}
    # The expired cookie does not become valid again on a later request.
    client.cookies.set(auth.COOKIE, opaque)
    assert client.get('/api/queue').status_code == 401


def test_failed_run_persists_and_cannot_approve_or_export(client):
    with patch('launchcrew.run.make_draft', side_effect=RuntimeError('private input not retained')):
        response = client.post('/api/runs', json={'idea': 'Demo', 'agent_name': 'Maker'})
    assert response.status_code == 201
    data = response.json()
    assert data['status'] == 'failed'
    assert data['error_type'] == 'RuntimeError'
    assert data['approval_state'] == 'pending_approval'
    assert 'private input' not in json.dumps(data)
    run_id = data['run_id']
    fetched = client.get(f'/api/runs/{run_id}')
    assert fetched.status_code == 200
    assert fetched.json()['status'] == 'failed'
    with store.connect() as db:
        row = db.execute(
            text('SELECT state FROM runs WHERE id=:id'), {'id': run_id}).fetchone()
    assert row is not None and row[0] == 'pending_approval'
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 422
    assert client.post(f'/api/runs/{run_id}/export', json={}).status_code == 422
    assert client.get(f'/api/runs/{run_id}').json()['approval_state'] == 'pending_approval'


def test_signed_in_approval_records_actor_in_receipt_table_and_audit(client, monkeypatch):
    demo = new_run(client)
    signed_in(client, monkeypatch)
    assert client.get(f"/api/runs/{demo['run_id']}").status_code == 404
    run = new_run(client)
    approved = client.post(f"/api/runs/{run['run_id']}/approve", json={})
    assert approved.status_code == 200
    assert approved.json()['approvals'][0]['approved_by'] == ACTOR
    with store.connect() as db:
        approvals = db.execute(
            text('SELECT approved_by FROM approvals WHERE run_id=:id'),
            {'id': run['run_id']}).fetchall()
        audit_actors = db.execute(
            text("SELECT actor FROM audit WHERE run_id=:id AND action='approved_for_export'"),
            {'id': run['run_id']}).fetchall()
    assert [row[0] for row in approvals] == [ACTOR]
    assert [row[0] for row in audit_actors] == [ACTOR]


def test_logout_clears_server_session_and_expires_cookie(client, monkeypatch):
    opaque = signed_in(client, monkeypatch)
    assert client.get('/api/queue').status_code == 200
    response = client.post('/api/auth/logout')
    assert response.status_code == 200
    assert response.json() == {'signed_out': True}
    set_cookie = response.headers.get('set-cookie', '')
    assert auth.COOKIE in set_cookie
    assert 'Max-Age=0' in set_cookie or 'expires=' in set_cookie.lower()
    with store.connect() as db:
        assert db.execute(text('SELECT count(*) FROM auth_sessions')).scalar() == 0
    # The old cookie is dead even if a client presents it again.
    client.cookies.set(auth.COOKIE, opaque)
    assert client.get('/api/queue').status_code == 401
    assert client.get('/api/auth/status').json()['user'] == ''
    # Logout is idempotent.
    assert client.post('/api/auth/logout').status_code == 200
    assert client.post('/api/auth/logout').json() == {'signed_out': True}


def test_logout_without_cookie_is_idempotent(client, monkeypatch):
    enable_auth(client, monkeypatch)
    response = client.post('/api/auth/logout')
    assert response.status_code == 200
    assert response.json() == {'signed_out': True}
    assert client.get('/api/queue').status_code == 401


def test_auth_enabled_blocks_protected_endpoints_without_session(client, monkeypatch):
    enable_auth(client, monkeypatch)
    assert client.get('/api/agents').status_code == 401
    assert client.get('/api/queue').status_code == 401
    assert client.post('/api/runs', json={'idea': 'Demo', 'agent_name': 'Maker'}).status_code == 401
    assert client.get('/api/runs/missing').status_code == 401
