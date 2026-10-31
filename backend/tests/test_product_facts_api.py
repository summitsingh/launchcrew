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
    # Milestone M5: owner runs must confirm every core fact (material,
    # contents, size, price) or carry an explicit owner waiver. The base
    # payload confirms all four; partial-fact refusal is covered by the
    # facts-library gate tests.
    return {'idea': IDEA, 'agent_name': 'Maker',
            'product_facts': {'material': field('Full-grain leather', True),
                              'contents': field('Six card slots', True),
                              'size': field('Bifold compact', True),
                              'price': field('$129', True),
                              **extra}}


FULL_CONFIRMED = ['Full-grain leather', 'Six card slots', 'Bifold compact', '$129']


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
    payload = owner_payload(founder_note=field(NOTE, True))
    payload['product_facts']['allowed_claims'] = [field('Oversized tote', False, 'pasted_text')]
    response = client.post('/api/runs', json=payload)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['status'] == 'completed'
    assert 'Full-grain leather' in receipt['maker_draft_v2']['post']
    assert '$129' in receipt['maker_draft_v2']['post']
    assert 'Bifold compact' in receipt['maker_draft_v2']['post']
    assert 'Oversized tote' not in receipt['maker_draft_v2']['post']
    for demo in DEMO_CLAIMS:
        assert demo not in receipt['maker_draft_v2']['post']
    section = receipt['product_facts']
    assert section['mode'] == 'owner_input'
    assert section['template_used'] is False
    assert section['confirmed_claims'] == FULL_CONFIRMED
    assert section['labels']['material'] == 'Material'
    assert section['labels']['founder_note'] == 'Founder note'
    assert [entry['value'] for entry in section['suggested']] == ['Oversized tote']
    assert section['founder_note']['authorized_as_fact'] is False
    variant = section['draft_variant']
    assert NOTE in variant['post'] and NOTE in variant['email']
    assert variant['authorized'] is False and variant['verified'] is False
    assert NOTE not in receipt['maker_draft_v2']['post']
    assert receipt['checker_v2']['blocked_count'] == 0
    # The stored receipt carries the same section for later binding.
    reread = client.get('/api/runs/' + receipt['run_id']).json()
    assert reread['product_facts']['confirmed_claims'] == FULL_CONFIRMED
    assert reread['product_facts']['missing_core_facts'] == []
    assert reread['product_facts']['missing_core_waived'] is False


def test_unconfirmed_memory_and_listing_cannot_authorize(client):
    memory = client.post('/api/memory', json={
        'kind': 'brand_fact', 'title': 'Shop fact',
        'content': {'claim': 'Handmade vegan wallet for commuters'}})
    assert memory.status_code == 201
    item = memory.json()
    payload = owner_payload()
    payload['product_facts']['allowed_claims'] = [field('Oversized tote', False, 'listing')]
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
    assert section['confirmed_claims'] == FULL_CONFIRMED
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
    # An owner run with nothing confirmed is refused unless the owner
    # records an explicit waiver for the missing core facts. A waived
    # empty run completes with the waiver on the receipt but cannot be
    # approved.
    refused = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                             'product_facts': {}})
    assert refused.status_code == 422, refused.text
    empty = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                           'product_facts': {},
                                           'waive_missing_core_facts': True})
    assert empty.status_code == 201, empty.text
    empty_id = empty.json()['run_id']
    assert empty.json()['product_facts']['confirmed_claims'] == []
    assert empty.json()['product_facts']['missing_core_waived'] is True
    assert client.post(f'/api/runs/{empty_id}/approve', json={}).status_code == 422


def test_campaign_threads_product_facts(client):
    response = client.post('/api/campaigns', json=owner_payload())
    assert response.status_code == 201, response.text
    day = response.json()['days'][0]
    receipt = client.get('/api/runs/' + day['run_id']).json()
    section = receipt['product_facts']
    assert section['mode'] == 'owner_input'
    assert section['confirmed_claims'] == FULL_CONFIRMED
    assert section['missing_core_facts'] == []
    assert 'Full-grain leather' in receipt['maker_draft_v2']['post']


def test_owner_campaign_briefs_built_from_confirmed_facts(client):
    # Owner mode builds every day brief from the campaign's own confirmed
    # facts. The bundled demo template is never used once the owner
    # confirms facts, so the day brief claims are authorized evidence.
    from backend.app import CAMPAIGN_ANGLES
    response = client.post('/api/campaigns', json=owner_payload())
    assert response.status_code == 201, response.text
    week = response.json()
    assert [day['day'] for day in week['days']] == list(range(1, 8))
    assert len({day['run_id'] for day in week['days']}) == 7
    assert len({day['angle'] for day in week['days']}) == 7
    assert len({day['brief'] for day in week['days']}) == 7
    for day in week['days']:
        assert day['angle'] in CAMPAIGN_ANGLES
        assert len(day['brief']) < 140
        assert any(claim in day['brief'] for claim in FULL_CONFIRMED)
        for marker in DEMO_CLAIMS:
            assert marker not in day['brief']
        receipt = client.get('/api/runs/' + day['run_id']).json()
        assert receipt['status'] == 'completed'
        assert receipt['campaign_day'] == day['day']
        assert receipt['campaign_brief'] == day['brief']
        assert receipt['campaign_angle'] == day['angle']
        assert 'Full-grain leather' in receipt['maker_draft_v2']['post']
        assert '$129' in receipt['maker_draft_v2']['post']
        section = receipt['product_facts']
        assert section['mode'] == 'owner_input'
        assert section['confirmed_claims'] == FULL_CONFIRMED
        assert section['allowlist'] == FULL_CONFIRMED
        assert receipt['memory_claims'] == []
        assert section['suggested'] == []
        for entry in receipt['scout']['facts_used']:
            assert entry['verified'] is True
            assert entry['sources'] == ['owner_confirmed_input']
        assert receipt['checker_v2']['blocked_count'] == 0
    day2 = client.get('/api/runs/' + week['days'][1]['run_id']).json()
    assert '100% vegan PU leather' not in day2['maker_draft_v2']['post']
    assert '$49' not in day2['maker_draft_v2']['post']
    first = client.post(f"/api/campaigns/{week['id']}/days/1/approve", json={})
    assert first.status_code == 200, first.text
    rest = client.get('/api/campaigns/' + week['id']).json()['days'][1:]
    assert all(d['approval_state'] == 'pending_approval' for d in rest)


def test_owner_confirmed_campaign_claim_authorizes(client):
    from backend.app import CAMPAIGN_BRIEF_BY_DAY
    _, _, brief_claim = CAMPAIGN_BRIEF_BY_DAY[2]
    payload = {'idea': IDEA, 'agent_name': 'Maker',
               'product_facts': {'material': field('Full-grain leather', True),
                                 'contents': field('Six card slots', True),
                                 'size': field('Bifold compact', True),
                                 'price': field('$129', True),
                                 'allowed_claims': [field(brief_claim, True, 'campaign_brief')]}}
    response = client.post('/api/campaigns', json=payload)
    assert response.status_code == 201, response.text
    day2 = response.json()['days'][1]
    receipt = client.get('/api/runs/' + day2['run_id']).json()
    assert brief_claim in receipt['maker_draft_v2']['post']
    assert brief_claim in receipt['product_facts']['confirmed_claims']
    assert brief_claim in receipt['product_facts']['allowlist']


def test_demo_campaign_briefs_still_authorize(client):
    from backend.app import CAMPAIGN_BRIEF_BY_DAY
    response = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    week = response.json()
    assert len({day['draft_v2_post'] for day in week['days']}) == 7
    for day in week['days']:
        _, _, brief_claim = CAMPAIGN_BRIEF_BY_DAY[day['day']]
        receipt = client.get('/api/runs/' + day['run_id']).json()
        assert receipt['product_facts']['mode'] == 'demo_template'
        assert brief_claim in receipt['maker_draft_v2']['post']
