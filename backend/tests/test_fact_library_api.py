"""API regression tests for Milestone M5: facts library and missing-fact gate.

Requires the Postgres-backed client fixture. Deterministic pipeline only,
no live model calls, no credentials.

Gap 5: named products hold per-variant fact sets. A run picks a variant
and binds a snapshot copy of its confirmed facts; later library edits
never rewrite the stored run receipt.

Gap 6: owner input missing a core fact (material, contents, size, price)
is refused with 422 naming the missing facts unless the owner sends an
explicit waiver, which is recorded on the receipt.
"""
import time
from unittest.mock import patch
import pytest
from launchcrew import run

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


def field(value, confirmed=True, source='owner'):
    return {'value': value, 'confirmed': confirmed, 'source': source}


def full_facts():
    return {'material': field('Full-grain leather'),
            'contents': field('Six card slots'),
            'size': field('Bifold compact'),
            'price': field('$129')}


def partial_facts():
    return {'material': field('Full-grain leather')}


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def create_product(client, name='Trail Wallet'):
    response = client.post('/api/fact-products', json={'name': name})
    assert response.status_code == 201, response.text
    return response.json()


def create_variant(client, product_id, name='Standard', facts=None):
    response = client.post('/api/fact-products/%s/variants' % product_id,
                           json={'name': name, 'product_facts': facts or full_facts()})
    assert response.status_code == 201, response.text
    return response.json()


def confirm_variant(client, variant_id):
    response = client.post('/api/fact-variants/%s/confirm' % variant_id)
    assert response.status_code == 200, response.text
    return response.json()


def test_product_crud_and_name_conflicts(client):
    product = create_product(client, 'Trail Wallet')
    assert product['variant_count'] == 0
    assert product['confirmed_variants'] == 0

    listed = client.get('/api/fact-products').json()
    assert [item['name'] for item in listed] == ['Trail Wallet']

    assert client.post('/api/fact-products', json={'name': 'trail wallet'}).status_code == 409

    renamed = client.put('/api/fact-products/' + product['id'], json={'name': 'Summit Tote'}).json()
    assert renamed['name'] == 'Summit Tote'

    detail = client.get('/api/fact-products/' + product['id']).json()
    assert detail['name'] == 'Summit Tote' and detail['variants'] == []

    assert client.get('/api/fact-products/nope').status_code == 404
    assert client.delete('/api/fact-products/' + product['id']).status_code == 204
    assert client.get('/api/fact-products').json() == []


def test_variant_lifecycle_confirm_and_edit_reset(client):
    product = create_product(client)
    variant = create_variant(client, product['id'], 'Standard', partial_facts())
    assert variant['confirmed'] is False

    variants = client.get('/api/fact-products/%s/variants' % product['id']).json()
    assert [item['name'] for item in variants] == ['Standard']

    assert client.post('/api/fact-products/%s/variants' % product['id'],
                       json={'name': 'standard', 'product_facts': full_facts()}).status_code == 409

    confirmed = confirm_variant(client, variant['id'])
    assert confirmed['confirmed'] is True

    edited = client.put('/api/fact-variants/' + variant['id'],
                        json={'product_facts': full_facts()}).json()
    assert edited['confirmed'] is False
    assert edited['product_facts']['price']['value'] == '$129'

    renamed = client.put('/api/fact-variants/' + variant['id'], json={'name': 'Deluxe'}).json()
    assert renamed['name'] == 'Deluxe' and renamed['confirmed'] is False

    assert client.put('/api/fact-variants/' + variant['id'], json={}).status_code == 422

    confirmed_again = confirm_variant(client, variant['id'])
    assert confirmed_again['confirmed'] is True

    assert client.delete('/api/fact-variants/' + variant['id']).status_code == 204
    assert client.get('/api/fact-variants/' + variant['id']).status_code == 404


def test_run_inherits_variant_facts_and_receipt_links_library(client):
    product = create_product(client)
    variant = create_variant(client, product['id'])
    confirm_variant(client, variant['id'])

    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                              'fact_variant_id': variant['id']})
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['status'] == 'completed'
    assert receipt['product_facts']['confirmed_claims'] == [
        'Full-grain leather', 'Six card slots', 'Bifold compact', '$129']
    assert 'Full-grain leather' in receipt['maker_draft_v2']['post']
    assert receipt['fact_library']['variant_id'] == variant['id']
    assert receipt['fact_library']['product_name'] == 'Trail Wallet'
    assert receipt['product_facts']['missing_core_facts'] == []
    assert receipt['product_facts']['missing_core_waived'] is False

    assert client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                          'fact_variant_id': variant['id'],
                                          'product_facts': full_facts()}).status_code == 422
    assert client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                          'fact_variant_id': 'fvar_missing'}).status_code == 404


def test_library_edits_never_rewrite_bound_run(client):
    product = create_product(client)
    variant = create_variant(client, product['id'])
    confirm_variant(client, variant['id'])

    receipt = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                             'fact_variant_id': variant['id']}).json()
    run_id = receipt['run_id']
    bound = list(receipt['product_facts']['confirmed_claims'])

    altered = {'material': field('Recycled canvas'),
               'contents': field('Six card slots'),
               'size': field('Bifold compact'),
               'price': field('$99')}
    client.put('/api/fact-variants/' + variant['id'], json={'product_facts': altered})
    confirm_variant(client, variant['id'])

    reread = client.get('/api/runs/' + run_id).json()
    assert reread['product_facts']['confirmed_claims'] == bound
    assert 'Recycled canvas' not in reread['maker_draft_v2']['post']
    assert reread['product_facts']['fields'][0]['value'] == 'Full-grain leather'

    fresh = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                           'fact_variant_id': variant['id']}).json()
    assert 'Recycled canvas' in fresh['product_facts']['confirmed_claims']


def test_partial_owner_facts_refused_without_waiver(client):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                              'product_facts': partial_facts()})
    assert response.status_code == 422, response.text
    body = response.json()
    assert body['detail']['missing_facts'] == ['contents', 'size', 'price']
    assert body['detail']['requires_waiver'] is True

    async_response = client.post('/api/runs/async', json={'idea': IDEA, 'agent_name': 'Maker',
                                                          'product_facts': partial_facts()})
    assert async_response.status_code == 422
    assert async_response.json()['detail']['missing_facts'] == ['contents', 'size', 'price']


def test_partial_owner_facts_with_waiver_records_it(client):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                              'product_facts': partial_facts(),
                                              'waive_missing_core_facts': True})
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['status'] == 'completed'
    assert receipt['product_facts']['missing_core_facts'] == ['contents', 'size', 'price']
    assert receipt['product_facts']['missing_core_waived'] is True
    assert receipt['missing_core_facts'] == ['contents', 'size', 'price']
    assert receipt['missing_facts_waived'] is True
    assert 'Full-grain leather' in receipt['maker_draft_v2']['post']

    reread = client.get('/api/runs/' + receipt['run_id']).json()
    assert reread['product_facts']['missing_core_waived'] is True
    assert reread['missing_facts_waived'] is True


def test_async_partial_with_waiver_completes_and_records_it(client):
    response = client.post('/api/runs/async', json={'idea': IDEA, 'agent_name': 'Maker',
                                                    'product_facts': partial_facts(),
                                                    'waive_missing_core_facts': True})
    assert response.status_code == 202, response.text
    run_id = response.json()['run_id']
    deadline = time.time() + 30.0
    last = None
    while time.time() < deadline:
        poll = client.get('/api/runs/%s/receipt' % run_id)
        assert poll.status_code == 200, poll.text
        last = poll.json()
        if last['status'] == 'completed':
            break
        time.sleep(0.05)
    assert last is not None and last['status'] == 'completed', repr(last)
    assert last['product_facts']['missing_core_waived'] is True
    assert last['missing_facts_waived'] is True


def test_save_current_run_facts_to_library_and_reuse(client):
    product = create_product(client, 'Archive Tote')
    full = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                          'product_facts': full_facts(),
                                          'waive_missing_core_facts': False})
    assert full.status_code == 201, full.text
    run_id = full.json()['run_id']

    saved = client.post('/api/fact-products/%s/variants/from-run/%s' % (product['id'], run_id),
                        json={'name': 'Archived'})
    assert saved.status_code == 201, saved.text
    variant = saved.json()
    assert variant['confirmed'] is False
    assert variant['product_facts']['material'] == field('Full-grain leather')
    confirm_variant(client, variant['id'])

    reused = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                            'fact_variant_id': variant['id']})
    assert reused.status_code == 201, reused.text
    assert reused.json()['product_facts']['confirmed_claims'] == [
        'Full-grain leather', 'Six card slots', 'Bifold compact', '$129']
