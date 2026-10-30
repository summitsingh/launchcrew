"""Drive intake via server authorization code with one-time session grant.

Source-only tests with fake OAuth exchange and fake Drive responses. No
provider network calls, no real credentials, no live Drive proof. All
states, tokens, file IDs, titles, and contents are synthetic.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
CANONICAL_SCOPE = 'openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/drive.file'
BROAD_SUFFIX = 'https://www.googleapis.com/auth/drive'
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
    with drive_intake._GRANTS_LOCK:
        drive_intake._GRANTS.clear()
    with drive_intake._PHOTO_HANDOFFS_LOCK:
        drive_intake._PHOTO_HANDOFFS.clear()
    yield
    with drive_intake._GRANTS_LOCK:
        drive_intake._GRANTS.clear()
    with drive_intake._PHOTO_HANDOFFS_LOCK:
        drive_intake._PHOTO_HANDOFFS.clear()


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

    def photo_content(self, file_id, resource_key, token, mime):
        self.calls.append(('photo_content', file_id, resource_key, mime))
        if self.error and self.error[0] == 'photo_content':
            raise self.error[1]
        if self.content_payload is not None:
            return self.content_payload
        raise AssertionError('photo tests must supply explicit photo bytes')


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
    with drive_intake._GRANTS_LOCK:
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


def _grant_unclaimed(client, monkeypatch, actor, sub, token_str, state):
    _sign_in(client, monkeypatch, actor)
    token = _valid_token(sub, token_str)
    redirect, exchange = _oauth_mocks(state=state, token=token)
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        authz = client.get('/api/drive-import/authorize', follow_redirects=False)
        assert authz.status_code == 302, authz.text
        callback = client.get(f'/api/drive-import/callback?code=synthetic-code-race&state={state}', follow_redirects=False)
        assert callback.status_code == 303, callback.text
    return token_str


def test_concurrent_picker_claim_single_winner(client, drive_env, monkeypatch):
    token_str = _grant_unclaimed(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-race-claim', 'synthetic-drive-state-race-claim')
    barrier = threading.Barrier(2)
    outcomes = [None, None]

    def one(index):
        try:
            barrier.wait(timeout=30)
            response = client.post('/api/drive-import/picker-token')
            outcomes[index] = (response.status_code, response.text)
        except Exception as error:
            outcomes[index] = ('error', repr(error))

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, [0, 1]))
    codes = sorted(out[0] for out in outcomes)
    assert codes == [200, 403]
    winners = [out for out in outcomes if out[0] == 200]
    losers = [out for out in outcomes if out[0] == 403]
    assert len(winners) == 1
    assert len(losers) == 1
    assert token_str in winners[0][1]
    assert token_str not in losers[0][1]
    assert client.post('/api/drive-import/picker-token').status_code == 403
    with drive_intake._GRANTS_LOCK:
        assert len(drive_intake._GRANTS) == 1
        grant = next(iter(drive_intake._GRANTS.values()))
        assert grant.get('delivered') is True
        assert grant.get('plaintext') is None


def test_concurrent_suggestions_single_read(client, drive_env, monkeypatch):
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-race-read', 'synthetic-drive-state-race-read')
    fake = FakeProvider(metadata={'id': 'demo-file-race', 'name': 'Race file', 'mimeType': TEXT_MIME, 'trashed': False})
    _use_provider(fake)
    barrier = threading.Barrier(2)
    outcomes = [None, None]

    def one(index):
        try:
            barrier.wait(timeout=30)
            response = _suggest(client, file_id='demo-file-race', token=token)
            outcomes[index] = (response.status_code, response.text)
        except Exception as error:
            outcomes[index] = ('error', repr(error))

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, [0, 1]))
    codes = sorted(out[0] for out in outcomes)
    assert codes == [200, 403]
    assert [call[0] for call in fake.calls] == ['metadata', 'content']
    winners = [out for out in outcomes if out[0] == 200]
    assert 'Canvas tote' in winners[0][1]
    losers = [out for out in outcomes if out[0] == 403]
    assert 'Canvas tote' not in losers[0][1]
    assert _suggest(client, file_id='demo-file-race', token=token).status_code == 403
    assert len(fake.calls) == 2


def test_canonical_identity_scopes_accepted(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    token_str = 'synthetic-drive-token-canonical'
    token = _valid_token(SUB_A, token_str)
    token['scope'] = CANONICAL_SCOPE
    state = 'synthetic-drive-state-canonical'
    redirect, exchange = _oauth_mocks(state=state, token=token)
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        assert client.get('/api/drive-import/authorize', follow_redirects=False).status_code == 302
        callback = client.get(f'/api/drive-import/callback?code=synthetic-code-canonical&state={state}', follow_redirects=False)
        assert callback.status_code == 303, callback.text
    claimed = client.post('/api/drive-import/picker-token')
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()['access_token'] == token_str
    fake = FakeProvider(metadata={'id': 'demo-file-01', 'name': 'Canonical file', 'mimeType': TEXT_MIME, 'trashed': False})
    _use_provider(fake)
    response = _suggest(client, file_id='demo-file-01', token=token_str)
    assert response.status_code == 200, response.text
    _assert_unconfirmed_drive(response.json())


def test_canonical_plus_broad_scope_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    token = _valid_token(SUB_A, 'synthetic-drive-token-canonical-broad')
    token['scope'] = CANONICAL_SCOPE + ' ' + BROAD_SUFFIX
    state = 'synthetic-drive-state-canonical-broad'
    redirect, exchange = _oauth_mocks(state=state, token=token)
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        assert client.get('/api/drive-import/authorize', follow_redirects=False).status_code == 302
        response = client.get(f'/api/drive-import/callback?code=synthetic-code-broad&state={state}', follow_redirects=False)
        assert response.status_code == 403
    assert client.post('/api/drive-import/picker-token').status_code == 403
    fake = FakeProvider()
    _use_provider(fake)
    assert _suggest(client, token='synthetic-drive-token-canonical-broad').status_code == 403
    assert fake.calls == []


def test_duplicate_and_ambiguous_scopes_rejected(client, drive_env, monkeypatch):
    cases = [
        OAUTH_SCOPE + ' openid',
        'openid profile email email ' + SCOPE,
        'openid profile email ' + SCOPE + ' ' + SCOPE,
        'openid email ' + drive_intake.DRIVE_EMAIL_CANONICAL + ' profile ' + SCOPE,
        'openid profile ' + drive_intake.DRIVE_PROFILE_CANONICAL + ' email ' + SCOPE,
    ]
    for idx, scope in enumerate(cases):
        _sign_in(client, monkeypatch, SYN_A)
        token = _valid_token(SUB_A, f'synthetic-drive-token-scope-{idx}')
        token['scope'] = scope
        state = f'synthetic-drive-state-scope-{idx}'
        redirect, exchange = _oauth_mocks(state=state, token=token)
        with patch('backend.drive_intake.drive_oauth_client') as factory:
            factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
            factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
            assert client.get('/api/drive-import/authorize', follow_redirects=False).status_code == 302
            response = client.get(f'/api/drive-import/callback?code=c-scope-{idx}&state={state}', follow_redirects=False)
            assert response.status_code == 403, scope
        assert client.post('/api/drive-import/picker-token').status_code == 403
        fake = FakeProvider()
        _use_provider(fake)
        assert _suggest(client, token=token['access_token']).status_code == 403
        assert fake.calls == []


def test_drive_callback_nonce_mismatch_fails_closed(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    response, _ = _authorize(client, token=_valid_token(SUB_A))
    assert response.status_code == 302
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_access_token = AsyncMock(side_effect=ValueError('nonce mismatch'))
        denied = client.get('/api/drive-import/callback?code=x&state=synthetic-drive-state-01', follow_redirects=False)
        assert denied.status_code == 403
    assert client.post('/api/drive-import/picker-token').status_code == 403
    fake = FakeProvider()
    _use_provider(fake)
    assert _suggest(client, token='synthetic-drive-token-01').status_code == 403
    assert fake.calls == []
    with drive_intake._GRANTS_LOCK:
        assert drive_intake._GRANTS == {}


def _photo_bytes(width=24, height=12):
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new('RGB', (width, height), (30, 120, 200)).save(buffer, format='PNG')
    return buffer.getvalue()


def _suggest_photo(client, file_id='demo-photo-01', token='synthetic-drive-token-01', resource_key=None):
    body = {'file_id': file_id, 'drive_token': token}
    if resource_key is not None:
        body['resource_key'] = resource_key
    return client.post('/api/drive-import/photo-suggestions', json=body)


def _assert_unconfirmed_photo(body):
    assert body['status'] == 'unconfirmed'
    assert body['source'] == 'drive_file'
    assert body['product_fact_source'] == 'drive_file'
    assert body['selection_context'] == 'Drive file selection'
    assert body['confirmed'] is False
    assert body['requires_approval'] is True
    assert body['mime_type'] in ('image/jpeg', 'image/png')
    assert body['parser_version'] == 'drive-photo/v1'
    assert isinstance(body['file_title'], str) and body['file_title']
    assert isinstance(body['width'], int) and body['width'] > 0
    assert isinstance(body['height'], int) and body['height'] > 0
    assert body['width'] * body['height'] <= drive_intake.DRIVE_MAX_PHOTO_PIXELS
    assert body['byte_size'] > 0
    assert body['byte_size'] <= drive_intake.DRIVE_MAX_PHOTO_BYTES
    blob = json.dumps(body).lower()
    assert 'synthetic-drive-token' not in blob
    assert 'demo-photo' not in blob
    assert 'data:image' not in blob


def test_photo_success_unconfirmed_with_approval_gate(client, drive_env, monkeypatch):
    raw = _photo_bytes()
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-photo-01')
    headers = FakeHeaders({'Content-Type': 'image/png', 'Content-Length': str(len(raw))})
    fake = FakeProvider(
        metadata={'id': 'demo-photo-01', 'name': 'Campsite photo', 'mimeType': 'image/png', 'trashed': False},
        content=(raw, headers, 200),
    )
    _use_provider(fake)
    response = _suggest_photo(client, token=token)
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_unconfirmed_photo(body)
    assert body['file_title'] == 'Campsite photo'
    assert body['width'] == 24 and body['height'] == 12
    assert [call[0] for call in fake.calls] == ['metadata', 'photo_content']
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []


def test_photo_one_time_grant_and_two_user_denial(client, drive_env, monkeypatch):
    raw = _photo_bytes()
    headers = FakeHeaders({'Content-Type': 'image/png', 'Content-Length': str(len(raw))})
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-photo-once')
    fake = FakeProvider(
        metadata={'id': 'demo-photo-01', 'name': 'Owner photo', 'mimeType': 'image/png', 'trashed': False},
        content=(raw, headers, 200),
    )
    _use_provider(fake)
    assert _suggest_photo(client, token=token).status_code == 200
    assert [call[0] for call in fake.calls] == ['metadata', 'photo_content']
    replay = _suggest_photo(client, token=token)
    assert replay.status_code == 403
    assert len(fake.calls) == 2
    _sign_in(client, monkeypatch, SYN_B)
    assert client.post('/api/drive-import/picker-token').status_code == 403
    assert _suggest_photo(client, token=token).status_code == 403


def test_photo_anonymous_demo_denied_before_provider(client, drive_env, monkeypatch):
    fake = FakeProvider()
    _use_provider(fake)
    assert _suggest_photo(client).status_code == 401
    assert fake.calls == []
    _sign_in(client, monkeypatch, 'facebook:synthetic-fb-01')
    assert _suggest_photo(client).status_code == 403
    assert fake.calls == []


def test_photo_mime_magic_and_size_refused(client, drive_env, monkeypatch):
    raw = _photo_bytes()
    good_headers = FakeHeaders({'Content-Type': 'image/png', 'Content-Length': str(len(raw))})
    token = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-photo-doc')
    fake_doc = FakeProvider(
        metadata={'id': 'demo-photo-01', 'name': 'Doc file', 'mimeType': DOC_MIME, 'trashed': False},
        content=(b'text', FakeHeaders({'Content-Type': 'text/plain'}), 200),
    )
    _use_provider(fake_doc)
    assert _suggest_photo(client, token=token).status_code == 422
    assert [call[0] for call in fake_doc.calls] == ['metadata']
    token2 = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-photo-magic', state='synthetic-drive-state-photo-magic')
    fake_magic = FakeProvider(
        metadata={'id': 'demo-photo-01', 'name': 'Fake photo', 'mimeType': 'image/png', 'trashed': False},
        content=(b'not a png at all', FakeHeaders({'Content-Type': 'image/png'}), 200),
    )
    _use_provider(fake_magic)
    assert _suggest_photo(client, token=token2).status_code == 422
    token3 = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-photo-deceptive', state='synthetic-drive-state-photo-deceptive')
    fake_deceptive = FakeProvider(
        metadata={'id': 'demo-photo-01', 'name': 'Photo file', 'mimeType': 'image/png', 'trashed': False},
        content=(raw, FakeHeaders({'Content-Type': 'text/html'}), 200),
    )
    _use_provider(fake_deceptive)
    assert _suggest_photo(client, token=token3).status_code == 422
    token4 = _full_grant(client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-photo-big', state='synthetic-drive-state-photo-big')
    fake_big = FakeProvider(
        metadata={'id': 'demo-photo-01', 'name': 'Big photo', 'mimeType': 'image/png', 'size': '2000000', 'trashed': False},
        content=(raw, good_headers, 200),
    )
    _use_provider(fake_big)
    assert _suggest_photo(client, token=token4).status_code == 413
    assert [call[0] for call in fake_big.calls] == ['metadata']
    with pytest.raises(HTTPException):
        drive_intake.check_photo_magic(b'not pixels', 'image/png')
    with pytest.raises(HTTPException):
        drive_intake.normalize_photo_mime('application/pdf')
    assert drive_intake.normalize_photo_mime('image/jpeg') == 'image/jpeg'
    assert drive_intake.DRIVE_MAX_PHOTO_BYTES == 1048576
    assert drive_intake.DRIVE_MAX_PHOTO_PIXELS == 8000000
    url = drive_intake.build_photo_content_url('demo-photo-01', None)
    assert url.startswith('https://www.googleapis.com/drive/v3/files/demo-photo-01?')
    assert 'access_token' not in url.lower()


class _OpenerHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _OpenerResponse:
    def __init__(self, data, headers=None, status=200):
        self._data = bytes(data)
        self.headers = headers if headers is not None else _OpenerHeaders({})
        self.status = status

    def read(self, size=-1):
        if size is None or size < 0:
            return self._data
        return self._data[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def _photo_shape_token():
    return 'synthetic-drive-token-shape-01'


def _photo_request_shape(request):
    import urllib.parse

    parsed = urllib.parse.urlsplit(request.full_url)
    assert parsed.scheme == 'https'
    assert parsed.hostname == drive_intake.DRIVE_API_HOST
    assert parsed.path.startswith('/drive/v3/files/')
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    lowered = request.full_url.lower()
    assert 'access_token' not in lowered
    assert 'resourcekey' not in lowered
    assert 'resource_key' not in lowered
    assert request.get_header('Authorization') == 'Bearer ' + _photo_shape_token()
    headers = {name.lower(): value for name, value in request.header_items()}
    return query, headers


def test_photo_transport_uses_documented_url_header_and_photo_cap():
    import urllib.parse

    raw = _photo_bytes()
    for key in (None, 'synthetic-resource-key-01'):
        headers = _OpenerHeaders({'Content-Type': 'image/png', 'Content-Length': str(len(raw))})
        opener = _FakeOpener(response=_OpenerResponse(raw, headers, 200))
        with patch.object(drive_intake.urllib.request, 'build_opener', return_value=opener):
            out, seen, status = drive_intake.DriveProvider().photo_content(
                'demo-photo-01', key, _photo_shape_token(), 'image/png')
        assert bytes(out) == raw
        assert status == 200
        assert len(opener.requests) == 1
        query, sent = _photo_request_shape(opener.requests[0])
        assert set(query) == {'alt', 'supportsAllDrives'}
        assert query['alt'] == 'media'
        assert query['supportsAllDrives'] == 'true'
        assert 'mimetype' not in urllib.parse.urlsplit(opener.requests[0].full_url).query.lower()
        expected = None if key is None else 'demo-photo-01/' + key
        assert sent.get(drive_intake.DRIVE_RESOURCE_KEYS_HEADER.lower()) == expected


def test_photo_transport_over_limit_and_redirect_refused():
    import urllib.error

    big_length = _OpenerHeaders({'Content-Type': 'image/png', 'Content-Length': str(drive_intake.DRIVE_MAX_PHOTO_BYTES + 1)})
    opener = _FakeOpener(response=_OpenerResponse(b'x', big_length, 200))
    with patch.object(drive_intake.urllib.request, 'build_opener', return_value=opener):
        with pytest.raises(HTTPException) as too_large:
            drive_intake.DriveProvider().photo_content('demo-photo-01', None, _photo_shape_token(), 'image/png')
    assert too_large.value.status_code == 413
    body = b'\x89PNG\r\n\x1a\n' + b'x' * drive_intake.DRIVE_MAX_PHOTO_BYTES
    small_length = _OpenerHeaders({'Content-Type': 'image/png', 'Content-Length': '16'})
    opener = _FakeOpener(response=_OpenerResponse(body, small_length, 200))
    with patch.object(drive_intake.urllib.request, 'build_opener', return_value=opener):
        with pytest.raises(HTTPException) as streamed:
            drive_intake.DriveProvider().photo_content('demo-photo-01', None, _photo_shape_token(), 'image/png')
    assert streamed.value.status_code == 413
    redirect = urllib.error.HTTPError(
        drive_intake.build_photo_content_url('demo-photo-01', None), 302, 'Found', _OpenerHeaders({}), None)
    opener = _FakeOpener(error=redirect)
    with patch.object(drive_intake.urllib.request, 'build_opener', return_value=opener):
        with pytest.raises(HTTPException) as moved:
            drive_intake.DriveProvider().photo_content('demo-photo-01', None, _photo_shape_token(), 'image/png')
    assert moved.value.status_code == 502
    with pytest.raises(HTTPException) as leaked:
        drive_intake.check_drive_url(
            'https://www.googleapis.com/drive/v3/files/demo-photo-01?alt=media&resourceKey=synthetic')
    assert leaked.value.status_code == 502


def test_photo_fetch_fallback_enforces_photo_cap_without_photo_method():
    class TextEraProvider:
        def __init__(self, payload):
            self.payload = payload

        def metadata(self, file_id, resource_key, token):
            return {'id': file_id, 'name': 'Legacy photo', 'mimeType': 'image/png', 'trashed': False}

        def content(self, file_id, resource_key, token, mime):
            return self.payload

    raw = _photo_bytes()
    headers = FakeHeaders({'Content-Type': 'image/png', 'Content-Length': str(len(raw))})
    out, _, _ = drive_intake.fetch_photo_content(TextEraProvider((raw, headers, 200)), 'demo-photo-01', None, 't', 'image/png')
    assert bytes(out) == raw
    oversize = b'\x89PNG\r\n\x1a\n' + b'x' * drive_intake.DRIVE_MAX_PHOTO_BYTES
    with pytest.raises(HTTPException) as capped:
        drive_intake.fetch_photo_content(
            TextEraProvider((oversize, FakeHeaders({'Content-Type': 'image/png'}), 200)),
            'demo-photo-01', None, 't', 'image/png')
    assert capped.value.status_code == 413


def _photo_grant_with_session(client, monkeypatch, actor, sub, token_str, state):
    _sign_in(client, monkeypatch, actor)
    opaque = client.cookies.get(auth.COOKIE)
    session_hash = auth.session_key(opaque)
    token = _valid_token(sub, token_str)
    redirect, exchange = _oauth_mocks(state=state, token=token)
    with patch('backend.drive_intake.drive_oauth_client') as factory:
        factory.return_value.authorize_redirect = AsyncMock(side_effect=redirect)
        factory.return_value.authorize_access_token = AsyncMock(side_effect=exchange)
        assert client.get('/api/drive-import/authorize', follow_redirects=False).status_code == 302
        callback = client.get(f'/api/drive-import/callback?code=synthetic-code-photo&state={state}', follow_redirects=False)
        assert callback.status_code == 303, callback.text
    claimed = client.post('/api/drive-import/picker-token')
    assert claimed.status_code == 200, claimed.text
    return token_str, session_hash


def test_photo_handoff_claim_once_returns_original_bytes(client, drive_env, monkeypatch):
    import hashlib

    raw = _photo_bytes()
    token, session_hash = _photo_grant_with_session(
        client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-photo-handoff', 'synthetic-drive-state-handoff')
    headers = FakeHeaders({'Content-Type': 'image/png', 'Content-Length': str(len(raw))})
    fake = FakeProvider(
        metadata={'id': 'demo-photo-01', 'name': 'Handoff photo', 'mimeType': 'image/png', 'trashed': False},
        content=(raw, headers, 200),
    )
    _use_provider(fake)
    response = _suggest_photo(client, token=token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['sha256'] == hashlib.sha256(raw).hexdigest()
    assert 'data:image' not in response.text
    claimed = drive_intake.claim_drive_photo_for_check(actor=SYN_A, session_hash=session_hash, digest=body['sha256'])
    assert claimed['raw'] == raw
    assert claimed['mime'] == 'image/png'
    assert (claimed['width'], claimed['height']) == (24, 12)
    assert hashlib.sha256(claimed['raw']).hexdigest() == body['sha256']
    with drive_intake._PHOTO_HANDOFFS_LOCK:
        assert drive_intake._PHOTO_HANDOFFS == {}
    with pytest.raises(HTTPException) as replay:
        drive_intake.claim_drive_photo_for_check(actor=SYN_A, session_hash=session_hash, digest=body['sha256'])
    assert replay.value.status_code == 403


def test_photo_handoff_wrong_digest_actor_session_denied(client, drive_env, monkeypatch):
    raw = _photo_bytes()
    token, session_hash = _photo_grant_with_session(
        client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-photo-bind', 'synthetic-drive-state-bind')
    headers = FakeHeaders({'Content-Type': 'image/png', 'Content-Length': str(len(raw))})
    fake = FakeProvider(
        metadata={'id': 'demo-photo-01', 'name': 'Bound photo', 'mimeType': 'image/png', 'trashed': False},
        content=(raw, headers, 200),
    )
    _use_provider(fake)
    body = _suggest_photo(client, token=token).json()
    digest = body['sha256']
    with pytest.raises(HTTPException) as wrong_digest:
        drive_intake.claim_drive_photo_for_check(actor=SYN_A, session_hash=session_hash, digest='0' * 64)
    assert wrong_digest.value.status_code == 403
    with pytest.raises(HTTPException) as wrong_session:
        drive_intake.claim_drive_photo_for_check(actor=SYN_A, session_hash='deadbeef', digest=digest)
    assert wrong_session.value.status_code == 403
    _sign_in(client, monkeypatch, SYN_B)
    with pytest.raises(HTTPException) as foreign:
        drive_intake.claim_drive_photo_for_check(actor=SYN_B, session_hash=auth.session_key(client.cookies.get(auth.COOKIE)), digest=digest)
    assert foreign.value.status_code == 403
    claimed = drive_intake.claim_drive_photo_for_check(actor=SYN_A, session_hash=session_hash, digest=digest)
    assert claimed['raw'] == raw


def test_photo_handoff_expiry_and_db_silence(client, drive_env, monkeypatch):
    raw = _photo_bytes()
    token, session_hash = _photo_grant_with_session(
        client, monkeypatch, SYN_A, SUB_A, 'synthetic-drive-token-photo-expire', 'synthetic-drive-state-expire')
    headers = FakeHeaders({'Content-Type': 'image/png', 'Content-Length': str(len(raw))})
    fake = FakeProvider(
        metadata={'id': 'demo-photo-01', 'name': 'Expiring photo', 'mimeType': 'image/png', 'trashed': False},
        content=(raw, headers, 200),
    )
    _use_provider(fake)
    body = _suggest_photo(client, token=token).json()
    with drive_intake._PHOTO_HANDOFFS_LOCK:
        for record in drive_intake._PHOTO_HANDOFFS.values():
            record['expiry_ts'] = time.time() - 1
    with pytest.raises(HTTPException) as expired:
        drive_intake.claim_drive_photo_for_check(actor=SYN_A, session_hash=session_hash, digest=body['sha256'])
    assert expired.value.status_code == 403
    with store.connect() as db:
        sessions = db.execute(text('SELECT data FROM auth_sessions')).scalars().all()
        runs = db.execute(text('SELECT receipt FROM runs')).scalars().all()
        memos = db.execute(text('SELECT facts FROM memory')).scalars().all()
        items = db.execute(text('SELECT content FROM memory_items')).scalars().all()
    blob = json.dumps({'sessions': sessions, 'runs': runs, 'memos': memos, 'items': items})
    assert body['sha256'] not in blob
    assert 'data:image' not in blob
