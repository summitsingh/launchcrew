"""API regression tests for Slice 1 confirmed owner product facts.

Requires the Postgres-backed client fixture. Deterministic pipeline only,
no live model calls, no credentials. The host verifier runs this suite.

Only explicitly confirmed owner fields become evidence. Pasted text,
listings, and memory items can at most suggest. The bundled fictional
demo template stays available in demo mode only.
"""
import time
from unittest.mock import patch
import pytest
from launchcrew import run

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
DEMO_CLAIMS = ['100% vegan PU leather', 'Designed in Texas', '$49',
               'Vegan leather wallet', 'For Austin commuters']
NOTE = 'I built this wallet for my commute.'


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def field(value, confirmed, source='owner'):
    return {'value': value, 'confirmed': confirmed, 'source': source}


def owner_payload(**extra):
    return {'idea': IDEA, 'agent_name': 'Maker',
            'product_facts': {'material': field('Full-grain leather', True),
                              'price': field('$129', True),
                              **extra}}


def wait_completed(client, run_id, timeout=30.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f'/api/runs/{run_id}/receipt')
        assert response.status_code == 200, response.text
        last = response.json()
        if last['status'] == 'completed':
            return last
        time.sleep(0.05)
    raise AssertionError('Timed out waiting for run ' + run_id + ': ' + repr(last))


def test_owner_input_confirmed_flows_to_receipt(client):
    payload = owner_payload(size=field('Bifold compact', False, 'pasted_text'),
                            founder_note=field(NOTE, True))
    response = client.post('/api/runs', json=payload)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['status'] == 'completed'
    assert 'Full-grain leather' in receipt['maker_draft_v2']['post']
    assert '$129' in receipt['maker_draft_v2']['post']
    assert 'Bifold compact' not in receipt['maker_draft_v2']['post']
    for demo in DEMO_CLAIMS:
        assert demo not in receipt['maker_draft_v2']['post']
    section = receipt['product_facts']
    assert section['mode'] == 'owner_input'
    assert section['template_used'] is False
    assert section['confirmed_claims'] == ['Full-grain leather', '$129']
    assert section['labels']['material'] == 'Material'
    assert section['labels']['founder_note'] == 'Founder note'
    assert [entry['value'] for entry in section['suggested']] == ['Bifold compact']
    assert section['founder_note']['authorized_as_fact'] is False
    variant = section['draft_variant']
    assert NOTE in variant['post'] and NOTE in variant['email']
    assert variant['authorized'] is False and variant['verified'] is False
    assert NOTE not in receipt['maker_draft_v2']['post']
    assert receipt['checker_v2']['blocked_count'] == 0
    # The stored receipt carries the same section for later binding.
    reread = client.get('/api/runs/' + receipt['run_id']).json()
    assert reread['product_facts']['confirmed_claims'] == ['Full-grain leather', '$129']


def test_unconfirmed_memory_and_listing_cannot_authorize(client):
    memory = client.post('/api/memory', json={
        'kind': 'brand_fact', 'title': 'Shop fact',
        'content': {'claim': 'Handmade vegan wallet for commuters'}})
    assert memory.status_code == 201
    item = memory.json()
    payload = owner_payload(size=field('Oversized tote', False, 'listing'))
    payload['memory_ids'] = [item['id']]
    response = client.post('/api/runs', json=payload)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['status'] == 'completed'
    assert 'Handmade vegan wallet for commuters' not in receipt['maker_draft_v2']['post']
    assert 'Oversized tote' not in receipt['maker_draft_v2']['post']
    section = receipt['product_facts']
    assert 'Handmade vegan wallet for commuters' not in section['confirmed_claims']
    assert 'Handmade vegan wallet for commuters' not in section['allowlist']
    assert 'Oversized tote' not in section['confirmed_claims']
    by_value = {entry['value']: entry for entry in section['suggested']}
    assert by_value['Handmade vegan wallet for commuters']['source'] == 'memory'
    assert by_value['Oversized tote']['source'] == 'listing'
    assert receipt['memory_claims'] == []
    assert receipt['memory_used'] == [{'id': item['id'], 'kind': 'brand_fact', 'title': item['title']}]


def test_invalid_product_facts_rejected_422(client):
    bad_inputs = [
        {'material': field('', True)},
        {'material': field('   ', True)},
        {'material': field('Full-grain leather', True),
         'price': field('Full-grain leather', True)},
        {'founder_note': field('First. Second.', True)},
        {'material': field('x' * 201, True)},
        {'material': {'value': 'x', 'confirmed': True, 'source': 'blog'}},
        {'material': {'value': 'x', 'confirmed': True, 'proof': 'y'}},
        {'color': field('brown', True)},
    ]
    for raw in bad_inputs:
        response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                                  'product_facts': raw})
        assert response.status_code == 422, (raw, response.text)
    assert client.get('/api/queue').json() == []


def test_demo_fixture_mode_unchanged(client):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert '$49' in receipt['maker_draft_v2']['post']
    section = receipt['product_facts']
    assert section['mode'] == 'demo_template'
    assert section['template_used'] is True
    assert section['confirmed_claims'] == DEMO_CLAIMS
    assert section['founder_note'] is None
    assert section['draft_variant'] is None


def test_async_carries_product_facts(client):
    response = client.post('/api/runs/async', json=owner_payload())
    assert response.status_code == 202, response.text
    receipt = wait_completed(client, response.json()['run_id'])
    assert 'Full-grain leather' in receipt['maker_draft_v2']['post']
    assert '$129' in receipt['maker_draft_v2']['post']
    section = receipt['product_facts']
    assert section['mode'] == 'owner_input'
    assert section['template_used'] is False
    assert section['confirmed_claims'] == ['Full-grain leather', '$129']
    assert receipt['checker_v2']['blocked_count'] == 0


def test_async_rejects_invalid_product_facts_422(client):
    raw = {'material': field('Full-grain leather', True),
           'price': field('Full-grain leather', True)}
    response = client.post('/api/runs/async', json={'idea': IDEA, 'agent_name': 'Maker',
                                                    'product_facts': raw})
    assert response.status_code == 422, response.text


def test_approval_export_preserved_for_owner_run(client):
    response = client.post('/api/runs', json=owner_payload())
    assert response.status_code == 201, response.text
    run_id = response.json()['run_id']
    approved = client.post(f'/api/runs/{run_id}/approve', json={})
    assert approved.status_code == 200, approved.text
    exported = client.post(f'/api/runs/{run_id}/export', json={})
    assert exported.status_code == 200, exported.text
    assert 'attachment' in exported.headers['content-disposition']
    # An owner run with nothing confirmed completes but cannot be approved.
    empty = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                           'product_facts': {}})
    assert empty.status_code == 201, empty.text
    empty_id = empty.json()['run_id']
    assert empty.json()['product_facts']['confirmed_claims'] == []
    assert client.post(f'/api/runs/{empty_id}/approve', json={}).status_code == 422


def test_campaign_threads_product_facts(client):
    response = client.post('/api/campaigns', json=owner_payload())
    assert response.status_code == 201, response.text
    day = response.json()['days'][0]
    receipt = client.get('/api/runs/' + day['run_id']).json()
    section = receipt['product_facts']
    assert section['mode'] == 'owner_input'
    assert section['confirmed_claims'] == ['Full-grain leather', '$129']
    assert 'Full-grain leather' in receipt['maker_draft_v2']['post']
