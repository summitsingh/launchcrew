"""Dropbox import API: status shape and closed-gate refusals.

Deterministic only, zero provider HTTP on every path: the module has
no transport, so refusal tests need no network mocks.
"""


def test_status_reports_unconfigured_with_setup_names(client, monkeypatch):
    monkeypatch.delenv('DROPBOX_CLIENT_ID', raising=False)
    monkeypatch.delenv('DROPBOX_CLIENT_SECRET', raising=False)
    response = client.get('/api/dropbox-import/status')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['available'] is False
    assert body['configured'] is False
    assert body['live_verified'] is False
    assert body['reason'] == 'dropbox_not_configured'
    assert body['callback_path'] == '/api/dropbox-import/callback'
    assert 'DROPBOX_CLIENT_ID' in body['setup_names']
    assert 'DROPBOX_CLIENT_SECRET' in body['setup_names']


def test_authorize_and_callback_refuse_closed(client, monkeypatch):
    monkeypatch.delenv('DROPBOX_CLIENT_ID', raising=False)
    monkeypatch.delenv('DROPBOX_CLIENT_SECRET', raising=False)
    authorize = client.get('/api/dropbox-import/authorize')
    assert authorize.status_code == 503, authorize.text
    assert 'not configured' in authorize.text
    callback = client.get('/api/dropbox-import/callback')
    assert callback.status_code == 503, callback.text
