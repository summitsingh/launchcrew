"""Drive selected-file intake: stateless unconfirmed suggestions with fake provider.

Source-only tests with fake Drive responses. No provider network calls,
no real credentials, no live Drive proof. All file IDs, tokens, titles,
and contents are synthetic.
"""
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy import text

from backend import auth, drive_intake, store
from backend.app import app
from launchcrew import run

SYN_A = 'google:synthetic-drive-alpha-01'
SYN_B = 'google:synthetic-drive-beta-02'
SUB_A = 'synthetic-drive-alpha-01'
SUB_B = 'synthetic-drive-beta-02'
DRIVE_CLIENT = 'synthetic-drive-client'
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
SCOPE = 'https://www.googleapis.com/auth/drive.file'
DOC_MIME = 'application/vnd.google-apps.document'
TEXT_MIME = 'text/plain'


def _valid_tokeninfo(sub):
    return {
        'scope': SCOPE,
        'expires_in': '3600',
        'aud': DRIVE_CLIENT,
        'audience': DRIVE_CLIENT,
        'issued_to': DRIVE_CLIENT,
        'sub': sub,
        'user_id': sub,
    }


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


@pytest.fixture
def drive_env(monkeypatch):
    monkeypatch.setenv('GOOGLE_DRIVE_CLIENT_ID', DRIVE_CLIENT)
    monkeypatch.setenv('GOOGLE_DRIVE_API_KEY', 'synthetic-drive-key')
    monkeypatch.setenv('GOOGLE_DRIVE_APP_ID', 'synthetic-drive-app')
    return True


class FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeProvider:
    def __init__(self, tokeninfo=None, metadata=None, content=None, error=None):
        self.tokeninfo_payload = tokeninfo
        self.metadata_payload = metadata
        self.content_payload = content
        self.error = error
        self.calls = []

    def tokeninfo(self, token):
        self.calls.append(('tokeninfo', token))
        if self.error and self.error[0] == 'tokeninfo':
            raise self.error[1]
        return dict(self.tokeninfo_payload or {'scope': SCOPE, 'expires_in': '3600'})

    def metadata(self, file_id, resource_key, token):
        self.calls.append(('metadata', file_id, resource_key))
        if self.error and self.error[0] == 'metadata':
            raise self.error[1]
        payload = dict(self.metadata_payload or {'id': file_id, 'name': 'Demo file', 'mimeType': TEXT_MIME, 'trashed': False})
        return payload

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


def test_status_unavailable_without_config(client, monkeypatch):
    monkeypatch.delenv('GOOGLE_DRIVE_CLIENT_ID', raising=False)
    monkeypatch.delenv('GOOGLE_DRIVE_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_DRIVE_APP_ID', raising=False)
    body = client.get('/api/drive-import/status').json()
    assert body['available'] is False
    assert body['configured'] is False
    assert body['live_verified'] is False
    assert body['reason'] == 'drive_not_configured'
    assert body['scope'] == SCOPE
    assert body['supported_mime_types'] == [DOC_MIME, TEXT_MIME]
    assert body['max_bytes'] == 200000
    assert body['max_requests'] == 3
    assert client.get('/api/drive-import/config').status_code == 503


def test_status_available_with_public_config(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    body = client.get('/api/drive-import/status').json()
    assert body['available'] is True
    assert body['configured'] is True
    assert body['live_verified'] is False
    assert body['reason'] == 'ok'
    config = client.get('/api/drive-import/config').json()
    assert config['client_id'] == DRIVE_CLIENT
    assert config['api_key'] == 'synthetic-drive-key'
    assert config['app_id'] == 'synthetic-drive-app'
    assert config['scope'] == SCOPE
    assert config['supported_mime_types'] == [DOC_MIME, TEXT_MIME]
    assert config['max_bytes'] == 200000
    blob = json.dumps(config)
    assert 'secret' not in blob.lower()
    assert 'token' not in blob.lower()


def test_suggestions_unavailable_without_config(client, monkeypatch):
    monkeypatch.delenv('GOOGLE_DRIVE_CLIENT_ID', raising=False)
    fake = FakeProvider()
    _use_provider(fake)
    response = _suggest(client)
    assert response.status_code == 503
    assert fake.calls == []


def test_text_plain_success_unconfirmed(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_A),
        metadata={'id': 'demo-file-01', 'name': 'Demo tote notes', 'mimeType': TEXT_MIME, 'trashed': False},
    )
    _use_provider(fake)
    response = _suggest(client, file_id='demo-file-01', token='synthetic-drive-token-01')
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_unconfirmed_drive(body)
    assert body['file_title'] == 'Demo tote notes'
    assert body['mime_type'] == TEXT_MIME
    assert [s['text'] for s in body['suggestions']] == ['Canvas tote', 'Large', '$49']
    kinds = [call[0] for call in fake.calls]
    assert kinds == ['tokeninfo', 'metadata', 'content']
    assert fake.calls[1][1] == 'demo-file-01'
    assert fake.calls[2][1] == 'demo-file-01'
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []


def test_doc_export_success_unconfirmed(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    data = b'Full-grain leather\nBifold compact'
    headers = FakeHeaders({'Content-Type': 'text/plain', 'Content-Length': str(len(data))})
    fake = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_A),
        metadata={'id': 'demo-doc-02', 'name': 'Demo doc', 'mimeType': DOC_MIME, 'trashed': False},
        content=(data, headers, 200),
    )
    _use_provider(fake)
    response = _suggest(client, file_id='demo-doc-02', token='synthetic-drive-token-02')
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_unconfirmed_drive(body)
    assert body['mime_type'] == DOC_MIME
    assert [s['text'] for s in body['suggestions']] == ['Full-grain leather', 'Bifold compact']
    assert fake.calls[2][3] == DOC_MIME


def test_token_discard_no_persistence(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    token = 'synthetic-drive-token-discard-01'
    fake = FakeProvider(tokeninfo=_valid_tokeninfo(SUB_A))
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


def test_auth_required_when_enabled(client, drive_env, monkeypatch):
    fake = FakeProvider(tokeninfo=_valid_tokeninfo(SUB_A))
    _use_provider(fake)
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    assert _suggest(client).status_code == 401
    assert fake.calls == []
    _sign_in(client, monkeypatch, SYN_A)
    _use_provider(fake)
    response = _suggest(client)
    assert response.status_code == 200, response.text
    _assert_unconfirmed_drive(response.json())


def test_two_user_denial_stateless(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    data_a = b'User one tote\nLarge'
    headers_a = FakeHeaders({'Content-Type': 'text/plain', 'Content-Length': str(len(data_a))})
    fake_a = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_A),
        metadata={'id': 'demo-file-A1', 'name': 'User one file', 'mimeType': TEXT_MIME, 'trashed': False},
        content=(data_a, headers_a, 200),
    )
    _use_provider(fake_a)
    first = _suggest(client, file_id='demo-file-A1', token='synthetic-drive-token-A1')
    assert first.status_code == 200, first.text
    assert [s['text'] for s in first.json()['suggestions']] == ['User one tote', 'Large']
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []
    _sign_in(client, monkeypatch, SYN_B)
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []
    data_b = b'User two wallet\nCompact'
    headers_b = FakeHeaders({'Content-Type': 'text/plain', 'Content-Length': str(len(data_b))})
    fake_b = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_B),
        metadata={'id': 'demo-file-B2', 'name': 'User two file', 'mimeType': TEXT_MIME, 'trashed': False},
        content=(data_b, headers_b, 200),
    )
    _use_provider(fake_b)
    second = _suggest(client, file_id='demo-file-B2', token='synthetic-drive-token-B2')
    assert second.status_code == 200, second.text
    assert [s['text'] for s in second.json()['suggestions']] == ['User two wallet', 'Compact']
    assert 'User one tote' not in second.text
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []


def test_cross_user_token_reuse_denied_by_provider(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_A),
        error=('metadata', HTTPException(403, 'Drive file unavailable or not selected')),
    )
    _use_provider(fake)
    response = _suggest(client, file_id='demo-file-A1', token='synthetic-drive-token-B2')
    assert response.status_code == 403
    assert 'synthetic-drive-token' not in response.text


def test_missing_scope_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    payload = _valid_tokeninfo(SUB_A)
    payload['scope'] = 'openid profile email'
    fake = FakeProvider(tokeninfo=payload)
    _use_provider(fake)
    response = _suggest(client)
    assert response.status_code == 403
    assert 'synthetic-drive-token' not in response.text
    assert fake.calls[0][0] == 'tokeninfo'
    assert len(fake.calls) == 1


def test_expired_token_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    payload = _valid_tokeninfo(SUB_A)
    payload['expires_in'] = '0'
    fake = FakeProvider(tokeninfo=payload)
    _use_provider(fake)
    assert _suggest(client).status_code == 403


def test_nonselected_file_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_A),
        error=('metadata', HTTPException(403, 'Drive file unavailable or not selected')),
    )
    _use_provider(fake)
    response = _suggest(client, file_id='demo-file-99')
    assert response.status_code == 403
    assert 'demo-file-99' not in response.text


def test_returned_id_mismatch_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_A),
        metadata={'id': 'other-file-02', 'name': 'Other', 'mimeType': TEXT_MIME, 'trashed': False},
    )
    _use_provider(fake)
    response = _suggest(client, file_id='demo-file-01')
    assert response.status_code == 403


def test_unsupported_mime_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    for mime in ('image/jpeg', 'application/pdf', 'video/mp4', 'text/html', 'application/octet-stream'):
        fake = FakeProvider(
            tokeninfo=_valid_tokeninfo(SUB_A),
            metadata={'id': 'demo-file-01', 'name': 'Demo file', 'mimeType': mime, 'trashed': False},
        )
        _use_provider(fake)
        response = _suggest(client)
        assert response.status_code == 422, mime
        assert client.get('/api/queue').json() == []
        assert client.get('/api/memory').json() == []


def test_trashed_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_A),
        metadata={'id': 'demo-file-01', 'name': 'Demo file', 'mimeType': TEXT_MIME, 'trashed': True},
    )
    _use_provider(fake)
    assert _suggest(client).status_code == 403


def test_oversize_metadata_rejected_before_content(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_A),
        metadata={'id': 'demo-file-01', 'name': 'Demo file', 'mimeType': TEXT_MIME, 'size': '200001', 'trashed': False},
    )
    _use_provider(fake)
    response = _suggest(client)
    assert response.status_code == 413
    assert [call[0] for call in fake.calls] == ['tokeninfo', 'metadata']


def test_oversize_bytes_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    data = b'x' * 200001
    headers = FakeHeaders({'Content-Type': 'text/plain', 'Content-Length': str(len(data))})
    fake = FakeProvider(tokeninfo=_valid_tokeninfo(SUB_A), content=(data, headers, 200))
    _use_provider(fake)
    assert _suggest(client).status_code == 413


def test_oversize_text_chars_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    data = ('y' * 10001).encode('utf-8')
    headers = FakeHeaders({'Content-Type': 'text/plain', 'Content-Length': str(len(data))})
    fake = FakeProvider(tokeninfo=_valid_tokeninfo(SUB_A), content=(data, headers, 200))
    _use_provider(fake)
    assert _suggest(client).status_code == 413


def test_non_text_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    for data in (b'\xff\xfe\x00binary', b'hello\x00world'):
        headers = FakeHeaders({'Content-Type': 'text/plain', 'Content-Length': str(len(data))})
        fake = FakeProvider(tokeninfo=_valid_tokeninfo(SUB_A), content=(data, headers, 200))
        _use_provider(fake)
        assert _suggest(client).status_code == 422


def test_deceptive_mime_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    data = b'<html>not text</html>'
    headers = FakeHeaders({'Content-Type': 'text/html; charset=utf-8', 'Content-Length': str(len(data))})
    fake = FakeProvider(tokeninfo=_valid_tokeninfo(SUB_A), content=(data, headers, 200))
    _use_provider(fake)
    assert _suggest(client).status_code == 422


def test_arbitrary_urls_rejected_without_provider_call(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider(tokeninfo=_valid_tokeninfo(SUB_A))
    _use_provider(fake)
    bad_ids = [
        'https://www.googleapis.com/drive/v3/files/demo-file-01',
        'https://evil.invalid/file',
        'demo-file-01?alt=media',
        'demo/file/01',
        'demo-file-01#frag',
        '',
        'x' * 257,
        'bad id!',
    ]
    for bad in bad_ids:
        response = _suggest(client, file_id=bad)
        assert response.status_code == 422, bad
    assert fake.calls == []
    response = client.post('/api/drive-import/suggestions', json={'file_id': 'demo-file-01', 'drive_token': 't', 'resource_key': 'https://evil.invalid/key'})
    assert response.status_code == 422


def test_wrong_host_and_redirect_refused():
    with pytest.raises(HTTPException) as evil:
        drive_intake.check_drive_url('https://evil.invalid/drive/v3/files/demo-file-01')
    assert evil.value.status_code == 502
    with pytest.raises(HTTPException) as plain:
        drive_intake.check_drive_url('http://www.googleapis.com/drive/v3/files/demo-file-01')
    assert plain.value.status_code == 502
    with pytest.raises(HTTPException) as path:
        drive_intake.check_drive_url('https://www.googleapis.com/upload/drive/v3/files/demo-file-01')
    assert path.value.status_code == 502
    with pytest.raises(HTTPException) as token_host:
        drive_intake.check_tokeninfo_url('https://evil.invalid/tokeninfo')
    assert token_host.value.status_code == 502
    with pytest.raises(HTTPException) as token_query:
        drive_intake.check_tokeninfo_url('https://oauth2.googleapis.com/tokeninfo?access_token=synthetic')
    assert token_query.value.status_code == 502
    with pytest.raises(HTTPException) as drive_token_query:
        drive_intake.check_drive_url('https://www.googleapis.com/drive/v3/files/demo-file-01?access_token=synthetic')
    assert drive_token_query.value.status_code == 502
    drive_intake.check_drive_url('https://www.googleapis.com/drive/v3/files/demo-file-01?alt=media')
    drive_intake.check_tokeninfo_url('https://oauth2.googleapis.com/tokeninfo')
    with pytest.raises(HTTPException) as length:
        drive_intake.check_content_length(FakeHeaders({'Content-Length': '200001'}), 200000)
    assert length.value.status_code == 413


def test_only_read_only_urls_built():
    meta = drive_intake.build_metadata_url('demo-file-01', None)
    assert meta.startswith('https://www.googleapis.com/drive/v3/files/demo-file-01?')
    assert 'fields=' in meta
    assert 'access_token' not in meta.lower()
    doc = drive_intake.build_content_url('demo-file-01', None, DOC_MIME)
    assert '/export?' in doc and 'mimeType=text%2Fplain' in doc
    assert 'access_token' not in doc.lower()
    text_url = drive_intake.build_content_url('demo-file-01', 'key-01', TEXT_MIME)
    assert 'alt=media' in text_url and 'resourceKey=key-01' in text_url
    assert 'access_token' not in text_url.lower()
    for url in (meta, doc, text_url):
        assert '/permissions' not in url
        assert 'create' not in url.lower()
        assert 'delete' not in url.lower()


def test_unconfirmed_drive_stays_suggestion_until_explicit_confirmation(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_A),
        metadata={'id': 'demo-file-01', 'name': 'Demo file', 'mimeType': TEXT_MIME, 'trashed': False},
    )
    _use_provider(fake)
    intake = _suggest(client).json()
    assert [s['text'] for s in intake['suggestions']] == ['Canvas tote', 'Large', '$49']
    unconfirmed = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker',
        'product_facts': {
            'material': {'value': 'Canvas tote', 'confirmed': True, 'source': 'drive_file'},
            'size': {'value': 'Large', 'confirmed': False, 'source': 'drive_file'},
        }})
    assert unconfirmed.status_code == 201, unconfirmed.text
    receipt = unconfirmed.json()
    assert receipt['status'] == 'completed'
    assert 'Canvas tote' in receipt['maker_draft_v2']['post']
    assert 'Large' not in receipt['maker_draft_v2']['post']
    assert 'Large' not in receipt['product_facts']['confirmed_claims']
    assert 'Large' not in receipt['product_facts']['allowlist']
    assert [s['value'] for s in receipt['product_facts']['suggested']] == ['Large']
    assert client.get('/api/memory').json() == []
    confirmed = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker',
        'product_facts': {
            'material': {'value': 'Canvas tote', 'confirmed': True, 'source': 'drive_file'},
            'size': {'value': 'Large', 'confirmed': True, 'source': 'drive_file'},
        }})
    assert confirmed.status_code == 201, confirmed.text
    assert 'Large' in confirmed.json()['maker_draft_v2']['post']


def test_demo_mode_unchanged_after_drive_intake(client, drive_env):
    fake = FakeProvider()
    _use_provider(fake)
    assert _suggest(client).status_code == 401
    assert fake.calls == []
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['product_facts']['mode'] == 'demo_template'
    assert receipt['product_facts']['template_used'] is True


def test_owner_binding_success_exact_owner(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    fake = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_A),
        metadata={'id': 'demo-file-01', 'name': 'Owner notes', 'mimeType': TEXT_MIME, 'trashed': False},
    )
    _use_provider(fake)
    response = _suggest(client, file_id='demo-file-01', token='synthetic-drive-token-owner-01')
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_unconfirmed_drive(body)
    assert body['file_title'] == 'Owner notes'
    assert [call[0] for call in fake.calls] == ['tokeninfo', 'metadata', 'content']


def test_owner_binding_wrong_audience_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    payload = _valid_tokeninfo(SUB_A)
    payload['aud'] = 'other-client'
    payload['audience'] = 'other-client'
    payload['issued_to'] = 'other-client'
    fake = FakeProvider(
        tokeninfo=payload,
        metadata={'id': 'demo-file-01', 'name': 'Demo file', 'mimeType': TEXT_MIME, 'trashed': False},
    )
    _use_provider(fake)
    response = _suggest(client, file_id='demo-file-01', token='synthetic-drive-token-wrong-aud-01')
    assert response.status_code == 403
    assert 'synthetic-drive-token' not in response.text
    assert [call[0] for call in fake.calls] == ['tokeninfo']


def test_owner_binding_wrong_google_account_rejected_with_valid_file(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    data = b'Other owner tote\nLarge'
    headers = FakeHeaders({'Content-Type': 'text/plain', 'Content-Length': str(len(data))})
    fake = FakeProvider(
        tokeninfo=_valid_tokeninfo(SUB_B),
        metadata={'id': 'demo-file-01', 'name': 'Demo file', 'mimeType': TEXT_MIME, 'trashed': False},
        content=(data, headers, 200),
    )
    _use_provider(fake)
    response = _suggest(client, file_id='demo-file-01', token='synthetic-drive-token-other-acct-01')
    assert response.status_code == 403
    assert 'synthetic-drive-token' not in response.text
    assert [call[0] for call in fake.calls] == ['tokeninfo']


def test_owner_binding_missing_identity_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    payload = _valid_tokeninfo(SUB_A)
    del payload['sub']
    del payload['user_id']
    fake = FakeProvider(tokeninfo=payload)
    _use_provider(fake)
    response = _suggest(client)
    assert response.status_code == 403
    assert len(fake.calls) == 1


def test_owner_binding_missing_audience_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    payload = _valid_tokeninfo(SUB_A)
    del payload['aud']
    del payload['audience']
    del payload['issued_to']
    fake = FakeProvider(tokeninfo=payload)
    _use_provider(fake)
    response = _suggest(client)
    assert response.status_code == 403
    assert len(fake.calls) == 1


def test_owner_binding_ambiguous_rejected(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, SYN_A)
    payload = _valid_tokeninfo(SUB_A)
    payload['issued_to'] = 'other-client'
    fake = FakeProvider(tokeninfo=payload)
    _use_provider(fake)
    assert _suggest(client).status_code == 403
    assert len(fake.calls) == 1
    payload2 = _valid_tokeninfo(SUB_A)
    payload2['user_id'] = SUB_B
    fake2 = FakeProvider(tokeninfo=payload2)
    _use_provider(fake2)
    assert _suggest(client).status_code == 403
    assert len(fake2.calls) == 1


def test_anonymous_auth_disabled_no_provider_access(client, drive_env):
    fake = FakeProvider(tokeninfo=_valid_tokeninfo(SUB_A))
    _use_provider(fake)
    status = client.get('/api/drive-import/status').json()
    assert status['available'] is False
    assert status['configured'] is True
    assert status['reason'] == 'auth_required'
    assert status['live_verified'] is False
    assert client.get('/api/drive-import/config').status_code == 401
    assert _suggest(client).status_code == 401
    assert fake.calls == []


def test_non_google_actor_denied(client, drive_env, monkeypatch):
    _sign_in(client, monkeypatch, 'facebook:synthetic-fb-01')
    fake = FakeProvider(tokeninfo=_valid_tokeninfo(SUB_A))
    _use_provider(fake)
    status = client.get('/api/drive-import/status').json()
    assert status['available'] is False
    assert status['reason'] == 'auth_required'
    assert client.get('/api/drive-import/config').status_code == 403
    assert _suggest(client).status_code == 403
    assert fake.calls == []
