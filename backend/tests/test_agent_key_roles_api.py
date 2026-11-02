"""Seat key roles on Postgres: viewer read-only, editor and owner full.

Uses only the existing ``test_engine`` and ``client`` fixtures; every
helper below is defined in this file.
"""


def make_key(client, label='seat', role=None, scopes=None):
    body = {'label': label}
    if role is not None:
        body['role'] = role
    if scopes is not None:
        body['scopes'] = scopes
    response = client.post('/api/agent-surfaces/keys', json=body)
    assert response.status_code == 201, response.text
    return response.json()


def key_headers(raw_key):
    return {'X-Workspace-Key': raw_key}


def test_key_roles_default_owner_and_listed(client):
    created = make_key(client)
    assert created['role'] == 'owner'
    listed = client.get('/api/agent-surfaces/keys').json()
    assert listed[0]['role'] == 'owner'
    assert 'raw_key' not in listed[0]
    revoked = client.post(
        f'/api/agent-surfaces/keys/{created["id"]}/revoke').json()
    assert revoked['role'] == 'owner'


def test_invalid_role_refuses_422(client):
    refused = client.post('/api/agent-surfaces/keys',
                          json={'label': 'bad', 'role': 'admin'})
    assert refused.status_code == 422, refused.text


def test_viewer_key_is_read_only(client):
    created = make_key(client, label='viewer seat', role='viewer')
    assert created['role'] == 'viewer'
    headers = key_headers(created['raw_key'])
    accounts = client.get('/api/agent/accounts', headers=headers)
    assert accounts.status_code == 200, accounts.text
    capabilities = client.get('/api/agent/capabilities', headers=headers)
    assert capabilities.status_code == 200, capabilities.text
    upload = client.post('/api/agent/upload', headers=headers,
                         json={'filename': 'shot.png', 'width': 1080, 'height': 1350})
    assert upload.status_code == 403, upload.text
    assert upload.json()['detail'] == 'insufficient_key_role'
    apply = client.post('/api/agent/apply', headers=headers, json={})
    assert apply.status_code == 403, apply.text
    mcp = client.post('/api/mcp/call', headers=headers,
                      json={'name': 'launchcrew_run_status', 'arguments': {}})
    assert mcp.status_code == 403, mcp.text


def test_editor_key_keeps_write_scopes(client):
    created = make_key(client, label='editor seat', role='editor')
    headers = key_headers(created['raw_key'])
    upload = client.post('/api/agent/upload', headers=headers,
                         json={'filename': 'shot.png', 'width': 1080, 'height': 1350})
    assert upload.status_code == 201, upload.text
    status = client.get('/api/agent/status', headers=headers)
    assert status.status_code == 200, status.text
