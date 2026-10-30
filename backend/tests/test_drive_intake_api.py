"""Drive intake via server authorization code with one-time session grant.

Source-only tests with fake OAuth exchange and fake Drive responses. No
provider network calls, no real credentials, no live Drive proof. All
states, tokens, file IDs, titles, and contents are synthetic.
"""
import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import text

from backend import auth, drive_intake, store
from backend.app import app
from launchcrew import run

SYN_A = 'google:synthetic-drive-alpha-01'
SYN_B = 'google:synthetic-drive-beta-02'
SUB_A = 'synthetic-drive-alpha-01'
SUB_B = 'synthetic-drive-beta-02'
IDENTITY_CLIENT = 'synthetic-identity-client'
PUBLIC_BASE = 'https://drive-test.invalid'
CALLBACK_URI = PUBLIC_BASE + '/api/drive-import/callback'
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
SCOPE = 'https://www.googleapis.com/auth/drive.file'
OAUTH_SCOPE = 'openid profile email https://www.googleapis.com/auth/drive.file'
DOC_MIME = 'application/vnd.google-apps.document'
TEXT_MIME = 'text/plain'


def _valid_userinfo(sub):
    return {
        'aud': IDENTITY_CLIENT,
        'iss': 'https://accounts.google.com',
        'exp': int(time.time()) + 3600,
        'sub': sub,
    }


def _valid_token(sub, token='synthetic-drive-token-01'):
    return {
        'access_token': token,
        'expires_in': 3600,
        'scope': OAUTH_SCOPE,
        'userinfo': _valid_userinfo(sub),
    }


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


@pytest.fixture(autouse=True)
def clear_grants():
    drive_intake._GRANTS.clear()
    yield
    drive_intake._GRANTS.clear()


@pytest.fixture
def drive_env(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', IDENTITY_CLIENT)
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'synthetic-identity-secret')
    monkeypatch.setenv('PUBLIC_BASE_URL', PUBLIC_BASE)
    monkeypatch.setenv('GOOGLE_DRIVE_API_KEY', 'synthetic-drive-key')
    monkeypatch.setenv('GOOGLE_DRIVE_APP_ID', 'synthetic-drive-app')
    monkeypatch.delenv('GOOGLE_DRIVE_CLIENT_ID', raising=False)
    return True


class FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeProvider:
    def __init__(self, metadata=None, content=None, error=None):
        self.metadata_payload = metadata
        self.content_payload = content
        self.error = error
        self.calls = []

    def metadata(self, file_id, resource_key, token):
        self.calls.append(('metadata', file_id, resource_key))
        if self.error and self.error[0] == 'metadata':
            raise self.error[1]
        return dict(self.metadata_payload or {'id': file_id, 'name': 'Demo file', 'mimeType': TEXT_MIME, 'trashed': False})

    def content(self, file_id, resource_key, token, mime):
        self.calls.append(('content', file_id, resource_key, mime))
        if self.error and self.error[0] == 'content':
            raise self.error[1]
        if self.content_payload is not None:
            return self.content_payload
        data = b'Canvas tote\nLarge\n$49'
        headers = FakeHeaders({'Content-Type': 'text/plain; charset=utf-8', 'Content-Length': str(len(data))})
        return (data, headers, 200)


def _use_provider(fake):
    app.dependency_overrides[drive_intake.get_provider] = lambda: fake


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


def _oauth_mocks(state='synthetic-drive-state-01', nonce='synthetic-drive-nonce-01', token=None):
    async def redirect(request, uri, **kwargs):
        assert uri == CALLBACK_URI
        assert kwargs.get('access_type') == 'online'
        assert kwargs.get('include_granted_scopes') == 'false'
        assert 'offline' not in json.dumps(kwargs).lower() or kwargs.get('access_type') == 'online'
        request.session['_state_google-drive_' + state] = {
            'data': {'nonce': nonce, 'redirect_uri': uri},
            'exp': time.time() + 600,
        }
        return RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?state=' + state, status_code=302)

    async def exchange(request):
        assert token is not None
        return dict(token)

    return redirect, exchange


def _authorize(client, token=None, state='synthetic-drive-state-01'):
    redirect, exchange = _oauth_mocks(state=state, token=token or _valid_token(SUB_A))
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        response = client.get('/api/drive-import/authorize', follow_redirects=False)
        return response, factory


def _callback(client, state='synthetic-drive-state-01', code='synthetic-code-01', token=None):
    _, exchange = _oauth_mocks(state=state, token=token or _valid_token(SUB_A))
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        response = client.get(f'/api/drive-import/callback?code={code}&state={state}', follow_redirects=False)
        return response, factory


def _full_grant(client, monkeypatch, actor, sub, token_str='synthetic-drive-token-01', state='synthetic-drive-state-01'):
    _sign_in(client, monkeypatch, actor)
    token = _valid_token(sub, token_str)
    redirect, exchange = _oauth_mocks(state=state, token=token)
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        authz = client.get('/api/drive-import/authorize', follow_redirects=False)
        assert authz.status_code == 302, authz.text
        callback = client.get(f'/api/drive-import/callback?code=synthetic-code-01&state={state}', follow_redirects=False)
        assert callback.status_code == 303, callback.text
    claimed = client.post('/api/drive-import/picker-token')
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()['access_token'] == token_str
    return token_str


def _suggest(client, file_id='demo-file-01', token='synthetic-drive-token-01', resource_key=None):
    body = {'file_id': file_id, 'drive_token': token}
    if resource_key is not None:
        body['resource_key'] = resource_key
    return client.post('/api/drive-import/suggestions', json=body)


def _assert_unconfirmed_drive(body):
    assert body['status'] == 'unconfirmed'
    assert body['source'] == 'drive_file'
    assert body['product_fact_source'] == 'drive_file'
    assert body['selection_context'] == 'Drive file selection'
    assert isinstance(body['file_title'], str) and body['file_title']
    assert body['mime_type'] in (DOC_MIME, TEXT_MIME)
    assert body['parser_version'] == 'drive-import/v1'
    assert isinstance(body['truncated'], bool)
    for key in ('dropped_duplicates', 'dropped_overlong', 'dropped_empty'):
        assert isinstance(body[key], int)
    for position, item in enumerate(body['suggestions']):
        assert item['status'] == 'unconfirmed'
        assert item['confirmed'] is False
        assert item['source'] == 'drive_file'
        assert item['product_fact_source'] == 'drive_file'
        assert item['index'] == position
        assert isinstance(item['text'], str) and item['text']
        assert set(item) == {'text', 'source', 'product_fact_source', 'status', 'confirmed', 'index'}
    blob = json.dumps(body).lower()
    assert 'drive-file-01' not in blob
    assert 'synthetic-drive-token' not in blob


def test_drive_oauth_uses_identity_client_and_narrow_scope(drive_env, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    with patch('backend.drive_intake.OAuth') as oauth:
        drive_intake.drive_oauth_client()
        kwargs = oauth.return_value.register.call_args.kwargs
        assert kwargs['client_id'] == IDENTITY_CLIENT
        assert kwargs['client_secret'] == 'synthetic-identity-secret'
        assert kwargs['client_kwargs']['scope'] == OAUTH_SCOPE
        assert oauth.return_value.register.call_args.args[0] == 'google-drive'
    assert drive_intake.DRIVE_OAUTH_SCOPE == OAUTH_SCOPE
    assert 'offline' not in OAUTH_SCOPE


def test_status_and_config_without_separate_drive_client(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    body = client.get('/api/drive-import/status').json()
    assert body['available'] is True
    assert body['configured'] is True
    assert body['live_verified'] is False
    assert body['reason'] == 'ok'
    assert body['scope'] == SCOPE
    assert body['max_requests'] == 3
    config = client.get('/api/drive-import/config').json()
    assert config['api_key'] == 'synthetic-drive-key'
    assert config['app_id'] == 'synthetic-drive-app'
    assert 'client_id' not in config
    blob = json.dumps(config)
    assert 'secret' not in blob.lower()
    assert 'token' not in blob.lower()


def test_authorize_preserves_session_without_rotation(client, drive_env, monkeypatch):
    before = _sign_in(client, monkeypatch, SYN_A)
    response, _ = _authorize(client)
    assert response.status_code == 302
    location = response.headers['location']
    assert location.startswith('https://accounts.google.com/')
    assert 'synthetic-drive-state-01' in location
    assert 'access_token' not in location.lower()
    assert 'synthetic-drive-token' not in location.lower()
    after = client.cookies.get(auth.COOKIE)
    assert after == before
    assert client.get('/api/auth/status').json()['user'] == SYN_A
    assert client.get('/api/queue').status_code == 200
    with store.connect() as db:
        rows = db.execute(text('SELECT data FROM auth_sessions')).scalars().all()
    assert len(rows) == 1
    assert rows[0]['actor'] == SYN_A
    assert rows[0]['drive_oauth_binding']['actor'] == SYN_A
    assert rows[0]['drive_oauth_binding']['state'] == 'synthetic-drive-state-01'


def test_exact_owner_success_unconfirmed(client, drive_env, monkeypatch):
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-owner-01')
    fake = FakeProvider(metadata={'id': 'demo-file-01', 'name': 'Owner notes', 'mimeType': TEXT_MIME, 'trashed': False})
    _use_provider(fake)
    response = _suggest(client, file_id='demo-file-01', token=token)
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_unconfirmed_drive(body)
    assert body['file_title'] == 'Owner notes'
    assert [call[0] for call in fake.calls] == ['metadata', 'content']
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []


def test_doc_export_success_unconfirmed(client, drive_env, monkeypatch):
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-doc-02')
    data = b'Full-grain leather\nBifold compact'
    headers = FakeHeaders({'Content-Type': 'text/plain', 'Content-Length': str(len(data))})
    fake = FakeProvider(
        metadata={'id': 'demo-doc-02', 'name': 'Demo doc', 'mimeType': DOC_MIME, 'trashed': False},
        content=(data, headers, 200),
    )
    _use_provider(fake)
    response = _suggest(client, file_id='demo-doc-02', token=token)
    assert response.status_code == 200, response.text
    assert response.json()['mime_type'] == DOC_MIME
    assert fake.calls[1][3] == DOC_MIME


def test_two_user_denial(client, drive_env, monkeypatch):
    token_a = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-A1')
    fake_a = FakeProvider(metadata={'id': 'demo-file-A1', 'name': 'User one file', 'mimeType': TEXT_MIME, 'trashed': False})
    _use_provider(fake_a)
    first = _suggest(client, file_id='demo-file-A1', token=token_a)
    assert first.status_code == 200, first.text
    _sign_in(client, monkeypatch, SYN_B)
    assert client.post('/api/drive-import/picker-token').status_code == 403
    fake_b = FakeProvider(metadata={'id': 'demo-file-A1', 'name': 'User one file', 'mimeType': TEXT_MIME, 'trashed': False})
    _use_provider(fake_b)
    cross = _suggest(client, file_id='demo-file-A1', token=token_a)
    assert cross.status_code == 403
    assert fake_b.calls == []
    token_b = _full_grant(client, monkeypatch, SYN_B, SUB_B, 'synthetic-drive-token-B2')
    fake_c = FakeProvider(metadata={'id': 'demo-file-B2', 'name': 'User two file', 'mimeType': TEXT_MIME, 'trashed': False})
    _use_provider(fake_c)
    second = _suggest(client, file_id='demo-file-B2', token=token_b)
    assert second.status_code == 200, second.text
    assert 'User one tote' not in second.text


def test_wrong_audience_issuer_sub_scope_rejected(client, drive_env, monkeypatch):
    cases = []
    bad_aud = _valid_token(SUB_A, 'synthetic-drive-token-bad-aud')
    bad_aud['userinfo']['aud'] = 'other-client'
    cases.append(bad_aud)
    bad_iss = _valid_token(SUB_A, 'synthetic-drive-token-bad-iss')
    bad_iss['userinfo']['iss'] = 'https://evil.invalid'
    cases.append(bad_iss)
    bad_exp = _valid_token(SUB_A, 'synthetic-drive-token-bad-exp')
    bad_exp['userinfo']['exp'] = int(time.time()) - 10
    cases.append(bad_exp)
    bad_sub = _valid_token(SUB_B, 'synthetic-drive-token-bad-sub')
    cases.append(bad_sub)
    bad_scope = _valid_token(SUB_A, 'synthetic-drive-token-bad-scope')
    bad_scope['scope'] = 'openid profile email'
    cases.append(bad_scope)
    broad_scope = _valid_token(SUB_A, 'synthetic-drive-token-broad')
    broad_scope['scope'] = OAUTH_SCOPE + ' https://www.googleapis.com/auth/drive'
    cases.append(broad_scope)
    offline = _valid_token(SUB_A, 'synthetic-drive-token-offline')
    offline['refresh_token'] = 'synthetic-refresh-01'
    cases.append(offline)
    for index, token in enumerate(cases):
        _sign_in(client, monkeypatch, SYN_A)
        state = f'synthetic-drive-state-bad-{index}'
        redirect, exchange = _oauth_mocks(state=state, token=token)
        with patch('backend.drive_intake.drive_oauth_client') as factory:
            factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
            factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
            assert client.get('/api/drive-import/authorize', follow_redirects=False).status_code == 302
            response = client.get(f'/api/drive-import/callback?code=c-{index}&state={state}', follow_redirects=False)
            assert response.status_code == 403, token
        assert client.post('/api/drive-import/picker-token').status_code == 403
        fake = FakeProvider()
        _use_provider(fake)
        assert _suggest(client, token=token['access_token']).status_code == 403
        assert fake.calls == []


def test_state_session_replay_and_expiry_rejected_before_exchange(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    response, _ = _authorize(client, token=_valid_token(SUB_A))
    assert response.status_code == 302
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_access_token = AsyncMock(return_value=_valid_token(SUB_A))
        wrong = client.get('/api/drive-import/callback?code=x&state=wrong-state', follow_redirects=False)
        assert wrong.status_code == 403
        factory.return_value.authorize_access_token.assert_not_called()
    other = _cookie(SYN_A)
    client.cookies.set(auth.COOKIE, other)
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_access_token = AsyncMock(return_value=_valid_token(SUB_A))
        mismatch = client.get('/api/drive-import/callback?code=x&state=synthetic-drive-state-01', follow_redirects=False)
        assert mismatch.status_code in (401, 403)
        factory.return_value.authorize_access_token.assert_not_called()
    _sign_in(client, monkeypatch, SYN_A)
    _, _ = _authorize(client, token=_valid_token(SUB_A))
    with store.connect() as db:
        row = db.execute(text('SELECT data FROM auth_sessions')).scalar()
        row['drive_oauth_binding']['expiry_ts'] = time.time() - 1
        db.execute(text('UPDATE auth_sessions SET data=CAST(:data AS jsonb)'), {'data': json.dumps(row)})
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_access_token = AsyncMock(return_value=_valid_token(SUB_A))
        expired = client.get('/api/drive-import/callback?code=x&state=synthetic-drive-state-01', follow_redirects=False)
        assert expired.status_code == 403
        factory.return_value.authorize_access_token.assert_not_called()
    _sign_in(client, monkeypatch, SYN_A)
    redirect, exchange = _oauth_mocks(state='synthetic-drive-state-replay', token=_valid_token(SUB_A))
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        assert client.get('/api/drive-import/authorize', follow_redirects=False).status_code == 302
        first = client.get('/api/drive-import/callback?code=c1&state=synthetic-drive-state-replay', follow_redirects=False)
        assert first.status_code == 303
        assert first.headers['location'] == '/?drive=authorized'
        assert 'synthetic-drive-token' not in first.headers['location'].lower()
        second = client.get('/api/drive-import/callback?code=c1&state=synthetic-drive-state-replay', follow_redirects=False)
        assert second.status_code == 403


def test_anonymous_demo_non_google_denied(client, drive_env, monkeypatch):
    fake = FakeProvider()
    _use_provider(fake)
    assert client.get('/api/drive-import/authorize', follow_redirects=False).status_code == 401
    assert client.get('/api/drive-import/callback?code=x&state=y', follow_redirects=False).status_code == 401
    assert client.post('/api/drive-import/picker-token').status_code == 401
    assert _suggest(client).status_code == 401
    assert fake.calls == []
    status = client.get('/api/drive-import/status').json()
    assert status['reason'] == 'auth_required'
    assert client.get('/api/drive-import/config').status_code == 401
    _sign_in(client, monkeypatch, 'facebook:synthetic-fb-01')
    assert client.get('/api/drive-import/authorize', follow_redirects=False).status_code == 403
    assert client.post('/api/drive-import/picker-token').status_code == 403
    assert _suggest(client).status_code == 403
    assert fake.calls == []


def test_token_never_in_url_log_db_receipt(client, drive_env, monkeypatch):
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-private-01')
    fake = FakeProvider(metadata={'id': 'demo-file-01', 'name': 'Demo file', 'mimeType': TEXT_MIME, 'trashed': False})
    _use_provider(fake)
    response = _suggest(client, file_id='demo-file-01', token=token)
    assert response.status_code == 200, response.text
    assert token not in response.text
    assert 'demo-file-01' not in response.text
    with store.connect() as db:
        sessions = db.execute(text('SELECT data FROM auth_sessions')).scalars().all()
        runs = db.execute(text('SELECT receipt FROM runs')).scalars().all()
        memos = db.execute(text('SELECT facts FROM memory')).scalars().all()
        items = db.execute(text('SELECT content FROM memory_items')).scalars().all()
        titles = db.execute(text('SELECT title FROM memory_items')).scalars().all()
        audits = db.execute(text('SELECT action FROM audit')).scalars().all()
        actors = db.execute(text('SELECT actor FROM audit')).scalars().all()
    blob = json.dumps({'sessions': sessions, 'runs': runs, 'memos': memos, 'items': items, 'titles': titles, 'audits': audits, 'actors': actors})
    assert token not in blob
    assert 'demo-file-01' not in blob


def test_one_time_grant_claim_and_suggest(client, drive_env, monkeypatch):
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-once-01')
    assert client.post('/api/drive-import/picker-token').status_code == 403
    fake = FakeProvider(metadata={'id': 'demo-file-01', 'name': 'Demo file', 'mimeType': TEXT_MIME, 'trashed': False})
    _use_provider(fake)
    assert _suggest(client, token=token).status_code == 200
    assert [call[0] for call in fake.calls] == ['metadata', 'content']
    replay = _suggest(client, token=token)
    assert replay.status_code == 403
    assert len(fake.calls) == 2
    drive_intake._GRANTS.clear()
    assert _suggest(client, token='synthetic-drive-token-once-01').status_code == 403


def test_foreign_token_without_grant_rejected_before_provider(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider()
    _use_provider(fake)
    response = _suggest(client, token='synthetic-foreign-token-01')
    assert response.status_code == 403
    assert fake.calls == []


def test_file_id_and_content_bounds(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider()
    _use_provider(fake)
    for bad in ('https://www.googleapis.com/drive/v3/files/demo-file-01', 'demo-file-01?alt=media', 'demo/file/01', '', 'x' * 257, 'bad id!'):
        assert _suggest(client, file_id=bad, token='synthetic-drive-token-01').status_code == 422
    assert fake.calls == []
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-bounds-01')
    oversize_meta = FakeProvider(metadata={'id': 'demo-file-01', 'name': 'Demo', 'mimeType': TEXT_MIME, 'size': '200001', 'trashed': False})
    _use_provider(oversize_meta)
    assert _suggest(client, token=token).status_code == 413
    assert [call[0] for call in oversize_meta.calls] == ['metadata']
    token2 = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-bounds-02')
    bad_data = b'x' * 200001
    bad_headers = FakeHeaders({'Content-Type': 'text/plain', 'Content-Length': str(len(bad_data))})
    oversize_content = FakeProvider(content=(bad_data, bad_headers, 200))
    _use_provider(oversize_content)
    assert _suggest(client, token=token2).status_code == 413
    token3 = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-bounds-03')
    html_headers = FakeHeaders({'Content-Type': 'text/html', 'Content-Length': '20'})
    deceptive = FakeProvider(content=(b'<html>not text</html>', html_headers, 200))
    _use_provider(deceptive)
    assert _suggest(client, token=token3).status_code == 422


def test_provider_failure_and_redirect_refused(client, drive_env, monkeypatch):
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-fail-01')
    fake = FakeProvider(error=('metadata', HTTPException(403, 'Drive file unavailable or not selected')))
    _use_provider(fake)
    assert _suggest(client, token=token).status_code == 403
    with pytest.raises(HTTPException) as evil:
        drive_intake.check_drive_url('https://evil.invalid/drive/v3/files/demo-file-01')
    assert evil.value.status_code == 502
    with pytest.raises(HTTPException) as token_query:
        drive_intake.check_drive_url('https://www.googleapis.com/drive/v3/files/demo-file-01?access_token=synthetic')
    assert token_query.value.status_code == 502
    drive_intake.check_drive_url('https://www.googleapis.com/drive/v3/files/demo-file-01?alt=media')
    with pytest.raises(HTTPException) as length:
        drive_intake.check_content_length(FakeHeaders({'Content-Length': '200001'}), 200000)
    assert length.value.status_code == 413
    meta = drive_intake.build_metadata_url('demo-file-01', None)
    assert meta.startswith('https://www.googleapis.com/drive/v3/files/demo-file-01?')
    assert 'access_token' not in meta.lower()


def test_unconfirmed_stays_suggestion_until_explicit_confirmation(client, drive_env, monkeypatch):
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-confirm-01')
    fake = FakeProvider(metadata={'id': 'demo-file-01', 'name': 'Demo file', 'mimeType': TEXT_MIME, 'trashed': False})
    _use_provider(fake)
    intake = _suggest(client, token=token).json()
    assert [s['text'] for s in intake['suggestions']] == ['Canvas tote', 'Large', '$49']
    unconfirmed = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker',
        'product_facts': {
            'material': {'value': 'Canvas tote', 'confirmed': True, 'source': 'drive_file'},
            'size': {'value': 'Large', 'confirmed': False, 'source': 'drive_file'},
        }})
    assert unconfirmed.status_code == 201, unconfirmed.text
    receipt = unconfirmed.json()
    assert 'Canvas tote' in receipt['maker_draft_v2']['post']
    assert 'Large' not in receipt['maker_draft_v2']['post']
    assert client.get('/api/memory').json() == []
