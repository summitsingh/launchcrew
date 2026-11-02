"""Image characters API on Postgres: CRUD with duplicate guard.

Deterministic fixtures only. Uses the existing ``test_engine`` and
``client`` fixtures.
"""


def create_character(client, **extra):
    body = {'name': 'Maya', 'appearance': 'Athletic woman with short hair'}
    body.update(extra)
    response = client.post('/api/image-characters', json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_crud_round_trip(client):
    created = create_character(client, style_notes='Golden hour shoots')
    assert created['style_notes'] == 'Golden hour shoots'
    listed = client.get('/api/image-characters').json()
    assert [item['id'] for item in listed] == [created['id']]
    fetched = client.get(f'/api/image-characters/{created["id"]}').json()
    assert fetched['appearance'] == 'Athletic woman with short hair'
    updated = client.put(f'/api/image-characters/{created["id"]}',
                         json={'name': 'Maya V2', 'appearance': 'New look'}).json()
    assert updated['name'] == 'Maya V2'
    assert updated['style_notes'] is None
    deleted = client.delete(f'/api/image-characters/{created["id"]}')
    assert deleted.status_code == 204
    assert client.get(f'/api/image-characters/{created["id"]}').status_code == 404


def test_duplicate_name_refuses_409(client):
    create_character(client)
    dup = client.post('/api/image-characters',
                      json={'name': 'maya', 'appearance': 'Other look'})
    assert dup.status_code == 409, dup.text
    other = create_character(client, name='June')
    clash = client.put(f'/api/image-characters/{other["id"]}',
                       json={'name': 'MAYA', 'appearance': 'Other look'})
    assert clash.status_code == 409, clash.text


def test_bad_input_and_missing_404(client):
    empty = client.post('/api/image-characters',
                        json={'name': '  ', 'appearance': 'Look'})
    assert empty.status_code == 422, empty.text
    assert client.get('/api/image-characters/missing').status_code == 404
    assert client.delete('/api/image-characters/missing').status_code == 404
