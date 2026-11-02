"""Owner templates API on Postgres: CRUD plus gated apply.

Uses only the existing ``test_engine`` and ``client`` fixtures; every
helper below is defined in this file. The pipeline runs offline with
no model calls.
"""
from unittest.mock import patch

import pytest

IDEA = 'Wallet launch template'
NOTE = 'Built for the commute.'


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    from launchcrew import run as run_mod
    pipeline = run_mod.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return pipeline(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def _confirmed_facts(confirmed=True):
    flag = bool(confirmed)
    return {'material': {'value': 'Full-grain leather', 'confirmed': flag, 'source': 'owner'},
            'contents': {'value': 'Six card slots', 'confirmed': flag, 'source': 'owner'},
            'size': {'value': 'Bifold compact', 'confirmed': flag, 'source': 'owner'},
            'price': {'value': '$49', 'confirmed': flag, 'source': 'owner'},
            'founder_note': {'value': NOTE, 'confirmed': True, 'source': 'owner'}}


def _create(client, **extra):
    body = {'name': 'Launch Pack', 'idea': IDEA}
    body.update(extra)
    response = client.post('/api/owner-templates', json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_crud_round_trip(client):
    created = _create(client, product_facts=_confirmed_facts())
    template_id = created['id']
    assert created['name'] == 'Launch Pack'
    assert created['product_facts']['price']['value'] == '$49'
    listed = client.get('/api/owner-templates').json()
    assert [item['id'] for item in listed] == [template_id]
    fetched = client.get(f'/api/owner-templates/{template_id}').json()
    assert fetched['idea'] == IDEA
    updated = client.put(f'/api/owner-templates/{template_id}',
                         json={'name': 'Launch Pack v2', 'idea': 'New idea'}).json()
    assert updated['name'] == 'Launch Pack v2'
    assert updated['idea'] == 'New idea'
    assert updated['product_facts'] is None
    deleted = client.delete(f'/api/owner-templates/{template_id}')
    assert deleted.status_code == 204
    assert client.get(f'/api/owner-templates/{template_id}').status_code == 404
    assert client.get('/api/owner-templates').json() == []


def test_duplicate_name_refuses_409_case_insensitive(client):
    _create(client)
    dup = client.post('/api/owner-templates', json={'name': 'launch pack', 'idea': IDEA})
    assert dup.status_code == 409, dup.text
    other = _create(client, name='Other')
    clash = client.put(f'/api/owner-templates/{other["id"]}',
                       json={'name': 'LAUNCH PACK', 'idea': IDEA})
    assert clash.status_code == 409, clash.text


def test_bad_input_refuses_422_and_missing_404(client):
    empty = client.post('/api/owner-templates', json={'name': '  ', 'idea': IDEA})
    assert empty.status_code == 422, empty.text
    bad_facts = client.post('/api/owner-templates',
                            json={'name': 'Bad', 'idea': IDEA,
                                  'product_facts': {'material': 'not an object'}})
    assert bad_facts.status_code == 422, bad_facts.text
    assert client.get('/api/owner-templates/missing').status_code == 404
    assert client.delete('/api/owner-templates/missing').status_code == 404
    applied = client.post('/api/owner-templates/missing/apply')
    assert applied.status_code == 404, applied.text


def test_apply_creates_run_and_binds_snapshot(client):
    created = _create(client, product_facts=_confirmed_facts())
    applied = client.post(f'/api/owner-templates/{created["id"]}/apply')
    assert applied.status_code == 201, applied.text
    receipt = applied.json()
    assert receipt['run_id'].startswith('run_')
    assert receipt['status'] == 'completed'
    client.put(f'/api/owner-templates/{created["id"]}',
               json={'name': 'Launch Pack', 'idea': 'Edited idea'})
    reread = client.get(f'/api/runs/{receipt["run_id"]}').json()
    assert 'Edited idea' not in reread['maker_draft_v2']['post']
    assert 'Edited idea' not in reread['maker_draft_v2']['email']


def test_apply_without_confirmed_core_facts_refuses_waiver_gate(client):
    created = _create(client, product_facts=_confirmed_facts(confirmed=False))
    applied = client.post(f'/api/owner-templates/{created["id"]}/apply')
    assert applied.status_code == 422, applied.text
    assert 'requires_waiver' in applied.text


def test_apply_without_facts_creates_demo_run(client):
    created = _create(client)
    applied = client.post(f'/api/owner-templates/{created["id"]}/apply')
    assert applied.status_code == 201, applied.text
    assert applied.json()['status'] == 'completed'
