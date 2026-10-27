import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from fastapi.responses import Response
from sqlalchemy import text
from backend import adapter, auth, store
from backend.app import app


def new_run(client, **extra):
    response = client.post('/api/runs', json={'idea': 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram', 'agent_name': 'Maker', **extra})
    assert response.status_code == 201
    return response.json()


def test_health(client):
    assert client.get('/api/health').json() == {'status': 'ok', 'auth': 'disabled_demo', 'approval_by': 'demo_placeholder'}


def test_agent_crud_clone_validation(client):
    profile = client.get('/api/agents/Maker').json()
    assert len(client.get('/api/agents').json()) == 3
    profile['name'] = 'WalletCrew'
    assert client.post('/api/agents', json=profile).status_code == 201
    assert client.post('/api/agents', json=profile).status_code == 409
    profile['personality'] = 'Precise and grounded'
    assert client.put('/api/agents/WalletCrew', json=profile).json()['personality'] == 'Precise and grounded'
    assert client.post('/api/agents/WalletCrew/clone', json={'name': 'WalletCopy'}).status_code == 201
    profile['name'] = 'Renamed'
    assert client.put('/api/agents/WalletCrew', json=profile).status_code == 422
    profile['approval_level'] = 'auto_approve'
    assert client.post('/api/agents', json=profile).status_code == 422


def test_preview_no_mutations_or_models(client):
    with store.connect() as db:
        before = db.execute(text('SELECT count(*) FROM audit')).scalar()
    with patch.object(Path, 'write_text', side_effect=AssertionError('write')), patch('launchcrew.run.spark_for_agent', side_effect=AssertionError('model')), patch('launchcrew.run.wonder_synthesize_for_scout', side_effect=AssertionError('model')):
        response = client.post('/api/agents/Maker/preview', json={'idea': 'Wallet'})
    assert response.status_code == 200
    assert response.json()['model_called'] is False
    assert response.json()['side_effects'] is False
    with store.connect() as db:
        assert db.execute(text('SELECT count(*) FROM audit')).scalar() == before
        assert db.execute(text('SELECT count(*) FROM runs')).scalar() == 0


def test_full_approval_export_flow(client):
    before = set((adapter.ROOT / 'runs').glob('*.json'))
    r = new_run(client, seed_unverified_claim=True)
    id = r['run_id']
    assert r['checker_v1']['blocked_claims'][0]['claim'] == 'best in Texas'
    assert r['checker_v2']['blocked_count'] == 0
    assert 'best in Texas' not in r['maker_draft_v2']['post']
    assert r['approvals'] == [] and r['approval_state'] == 'pending_approval'
    assert client.get(f'/api/runs/{id}').json() == client.get(f'/api/runs/{id}/receipt').json()
    assert client.post(f'/api/runs/{id}/export', json={}).status_code == 422
    approved = client.post(f'/api/runs/{id}/approve', json={})
    assert approved.status_code == 200
    assert approved.json()['approvals'][0]['approved_by'] == 'demo_placeholder'
    assert client.post(f'/api/runs/{id}/approve', json={}).status_code == 422
    result = client.post(f'/api/runs/{id}/export', json={})
    assert result.status_code == 200 and 'attachment' in result.headers['content-disposition']
    assert result.json()['summary']['submit_attempted'] is False
    assert set((adapter.ROOT / 'runs').glob('*.json')) == before
    with store.connect() as db:
        assert db.execute(text('SELECT count(*) FROM memory')).scalar() == 1
        assert db.execute(text('SELECT count(*) FROM approvals')).scalar() == 1
        assert [r[0] for r in db.execute(text('SELECT action FROM audit ORDER BY id'))] == ['run_created', 'approved_for_export', 'exported']


def test_pending_first(client):
    first = new_run(client)
    second = new_run(client)
    client.post(f"/api/runs/{first['run_id']}/approve", json={})
    queue = client.get('/api/queue').json()
    assert [r['run_id'] for r in queue] == [second['run_id'], first['run_id']]


def test_no_batch_or_auto_approval(client):
    r = new_run(client)
    assert client.post('/api/runs/approve', json={'ids': [r['run_id']]}).status_code == 405
    assert client.post('/api/queue/approve', json={}).status_code == 404
    assert client.post('/api/runs', json={'idea': 'Wallet', 'agent_name': 'Maker', 'approve': True}).status_code == 422
    assert client.post(f"/api/runs/{r['run_id']}/approve", json={'ids': ['other']}).status_code == 422
    assert client.get(f"/api/runs/{r['run_id']}").json()['approval_state'] == 'pending_approval'


def test_failed_and_blocked_refused(client):
    r = new_run(client)
    id = r['run_id']
    for status, blocked in [('completed', 1), ('failed', 0)]:
        r['status'] = status
        r['checker_v2']['blocked_count'] = blocked
        with store.connect() as db:
            db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'), {'receipt': json.dumps(r), 'id': id})
        assert client.post(f'/api/runs/{id}/approve', json={}).status_code == 422
        assert client.post(f'/api/runs/{id}/export', json={}).status_code == 422


def test_concurrent_approval_once(client):
    r = new_run(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: client.post(f"/api/runs/{r['run_id']}/approve", json={}).status_code, range(2)))
    assert sorted(statuses) == [200, 422]
    with store.connect() as db:
        assert db.execute(text('SELECT count(*) FROM approvals')).scalar() == 1


def test_transaction_rolls_back_with_audit_failure(client):
    r = new_run(client)
    with patch('backend.store.audit', side_effect=ValueError('audit unavailable')):
        assert client.post(f"/api/runs/{r['run_id']}/approve", json={}).status_code == 422
    assert client.get(f"/api/runs/{r['run_id']}").json()['approval_state'] == 'pending_approval'
    with store.connect() as db:
        assert db.execute(text('SELECT count(*) FROM approvals')).scalar() == 0


def test_cross_origin(client):
    assert client.post('/api/runs', headers={'Origin': 'https://other.invalid'}, json={}).status_code == 403


def test_missing_resources(client):
    assert client.get('/api/agents/missing').status_code == 404
    assert client.get('/api/runs/missing').status_code == 404
    assert client.post('/api/runs/missing/export', json={}).status_code == 404


def test_openapi_matches_committed_document(client):
    assert app.openapi() == json.loads(Path('backend/openapi.json').read_text())


def test_auth_disabled(client):
    assert client.get('/api/auth/status').json() == {'enabled': False, 'user': '', 'live_verified': False}
    assert client.get('/api/auth/google/login', follow_redirects=False).status_code == 404


def test_auth_requires_https_and_configuration(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    monkeypatch.setenv('PUBLIC_BASE_URL', 'http://demo.invalid')
    import pytest
    with pytest.raises(RuntimeError):
        auth.validate_config()


def test_auth_server_session_actor(client, monkeypatch):
    r = new_run(client)
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    assert client.get('/api/queue').status_code == 401
    response = Response()
    auth.save_session({'actor': 'google:demo-test-subject'}, response)
    cookie = response.headers['set-cookie']
    for flag in ('Secure', 'HttpOnly', 'SameSite=lax'):
        assert flag in cookie
    opaque = cookie.split(';')[0].split('=', 1)[1]
    client.cookies.set(auth.COOKIE, opaque)
    approved = client.post(f"/api/runs/{r['run_id']}/approve", json={})
    assert approved.json()['approvals'][0]['approved_by'] == 'google:demo-test-subject'
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/queue').status_code == 401


def test_identity_only_scopes(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    for provider in ('google', 'facebook'):
        monkeypatch.setenv(provider.upper() + '_CLIENT_ID', 'demo-provider')
        monkeypatch.setenv(provider.upper() + '_CLIENT_SECRET', 'demo-provider')
        with patch('backend.auth.OAuth') as oauth:
            auth.oauth_client(provider)
            scope = oauth.return_value.register.call_args.kwargs['client_kwargs']['scope']
            assert set(scope.split()) == ({'openid', 'profile', 'email'} if provider == 'google' else {'public_profile', 'email'})
