"""API regression tests for Milestone M9: quick-start templates.

Requires the Postgres-backed client fixture. Deterministic pipeline only,
no live model calls, no credentials.

Gap 10: the API lists four fictional quick-start templates (wallet, food,
mobile app, local service). Every template body carries complete suggested
facts in the existing product-facts format with nothing confirmed. A run
built from reviewed template facts (confirmed with a genuine source) loads
exactly like ordinary owner facts.
"""
import copy
import time
from unittest.mock import patch
import pytest
from launchcrew import quickstart_templates as qt
from launchcrew import run
from launchcrew.facts import parse_product_facts

EXPECTED_IDS = ['quickstart_wallet', 'quickstart_food',
                'quickstart_mobile_app', 'quickstart_local_service']
EXPECTED_KINDS = ['wallet', 'food', 'mobile_app', 'local_service']


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def confirmed_owner_input(template_id):
    """Reviewed template facts: same values, genuine source, attested."""
    prefill = qt.build_prefill(template_id)
    probe = copy.deepcopy(prefill['suggested_facts'])
    provenance = copy.deepcopy(prefill['provenance'])
    for key in list(provenance):
        entry = qt._entry_for_key(probe, key)
        if isinstance(entry, dict):
            entry['confirmed'] = True
            entry['source'] = 'owner'
        provenance = qt.attest_prefill_field(provenance, key)
    qt.assert_template_review_complete(probe, provenance)
    parsed = parse_product_facts(copy.deepcopy(probe))
    assert parsed['confirmed_claims'], 'reviewed template must yield confirmed claims'
    return probe


def test_list_templates_returns_all_four(client):
    response = client.get('/api/quickstart-templates')
    assert response.status_code == 200, response.text
    listed = response.json()
    assert [t['template_id'] for t in listed] == EXPECTED_IDS
    assert [t['kind'] for t in listed] == EXPECTED_KINDS
    for entry in listed:
        assert entry['fictional'] is True
        assert entry['confirmation_required'] is True


def test_template_detail_is_complete_unconfirmed_facts(client):
    for template_id in EXPECTED_IDS:
        response = client.get('/api/quickstart-templates/%s' % template_id)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['template_id'] == template_id
        assert body['fictional'] is True
        assert body['approved_claims'] == []
        suggested = body['suggested_facts']
        for name in ('material', 'contents', 'size', 'price', 'founder_note'):
            assert suggested[name]['value'].strip(), template_id + '/' + name
            assert suggested[name]['confirmed'] is False
        assert len(suggested['allowed_claims']) > 0
        parsed = parse_product_facts(copy.deepcopy(suggested))
        assert parsed['confirmed_claims'] == []


def test_template_detail_unknown_id_is_404(client):
    response = client.get('/api/quickstart-templates/quickstart_spaceship')
    assert response.status_code == 404


def test_reviewed_wallet_facts_load_into_run(client):
    payload = {'idea': 'Minimalist leather wallet launch',
               'agent_name': 'Maker',
               'product_facts': confirmed_owner_input('quickstart_wallet')}
    response = client.post('/api/runs', json=payload)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['status'] == 'completed'
    assert receipt['product_facts']['mode'] == 'owner_input'
    post = receipt['maker_draft_v2']['post']
    assert 'Full-grain leather minimalist bifold wallet' in post
    assert '$49' in post


def test_reviewed_template_facts_load_into_async_run(client):
    payload = {'idea': 'Habit tracker app launch',
               'agent_name': 'Maker',
               'product_facts': confirmed_owner_input('quickstart_mobile_app')}
    response = client.post('/api/runs/async', json=payload)
    assert response.status_code == 202, response.text
    run_id = response.json()['run_id']
    deadline = time.time() + 30.0
    last = None
    while time.time() < deadline:
        check = client.get('/api/runs/%s/receipt' % run_id)
        assert check.status_code == 200, check.text
        last = check.json()
        if last['status'] == 'completed':
            break
        time.sleep(0.1)
    assert last is not None and last['status'] == 'completed', repr(last)
    assert last['product_facts']['mode'] == 'owner_input'
