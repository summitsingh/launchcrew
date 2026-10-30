"""API tests for stateless owner intake via pasted listing or social text.

Requires the Postgres-backed client fixture. Deterministic pipeline only,
no live model calls, no credentials. The host verifier runs this suite.

Pasted text can at most suggest. Every suggestion returns confirmed false
with provenance. A value becomes evidence only when the owner explicitly
confirms it through the typed product_facts contract.
"""
import time
from unittest.mock import patch
from fastapi.responses import Response
import pytest
from launchcrew import run
from backend import auth

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def _suggest(client, text, source):
    return client.post('/api/import-suggestions', json={'text': text, 'source': source})


def _assert_unconfirmed_envelope(body, source, product_source):
    assert body['status'] == 'unconfirmed'
    assert body['source'] == source
    assert body['product_fact_source'] == product_source
    assert body['parser_version'] == 'import-suggestions/v1'
    assert isinstance(body['truncated'], bool)
    for key in ('dropped_duplicates', 'dropped_overlong', 'dropped_empty'):
        assert isinstance(body[key], int)
    for position, item in enumerate(body['suggestions']):
        assert item['status'] == 'unconfirmed'
        assert item['confirmed'] is False
        assert item['source'] == source
        assert item['product_fact_source'] == product_source
        assert item['index'] == position
        assert isinstance(item['text'], str) and item['text']
        assert set(item) == {'text', 'source', 'product_fact_source', 'status', 'confirmed', 'index'}


def test_listing_returns_unconfirmed_with_provenance(client):
    response = _suggest(client, 'Canvas tote\nLarge\n$49', 'listing')
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_unconfirmed_envelope(body, 'listing', 'listing')
    assert [s['text'] for s in body['suggestions']] == ['Canvas tote', 'Large', '$49']
    assert body['truncated'] is False
    assert body['dropped_duplicates'] == 0
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []


def test_instagram_sources_map_to_pasted_text(client):
    for source in ('instagram_bio', 'instagram_caption'):
        response = _suggest(client, 'Sampleville bake stand\nEst. 2021', source)
        assert response.status_code == 200, response.text
        body = response.json()
        _assert_unconfirmed_envelope(body, source, 'pasted_text')
        assert [s['text'] for s in body['suggestions']] == ['Sampleville bake stand', 'Est. 2021']


def test_bounds_and_fidelity(client):
    overlong_line = 'z' * 501
    response = _suggest(client, 'Alpha\n' + overlong_line + '\nBeta', 'listing')
    assert response.status_code == 200, response.text
    body = response.json()
    assert [s['text'] for s in body['suggestions']] == ['Alpha', 'Beta']
    assert body['dropped_overlong'] == 1
    assert body['truncated'] is False

    lines = [f'Sample item {i:02d}' for i in range(25)]
    response = _suggest(client, '\n'.join(lines), 'listing')
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body['suggestions']) == 20
    assert body['truncated'] is True
    assert body['suggestions'][0]['text'] == 'Sample item 00'

    response = _suggest(client, 'Baked fresh\nBaked fresh\nBeta shelf', 'listing')
    assert response.status_code == 200, response.text
    assert response.json()['dropped_duplicates'] == 1

    response = _suggest(client, 'Mini loaf $4\n20% off bundles\n2026-02-14\n- Fresh SOURDOUGH!', 'listing')
    assert response.status_code == 200, response.text
    assert [s['text'] for s in response.json()['suggestions']] == [
        'Mini loaf $4', '20% off bundles', '2026-02-14', '- Fresh SOURDOUGH!']

    response = _suggest(client, '   \n\t\n  ', 'listing')
    assert response.status_code == 200, response.text
    assert response.json()['suggestions'] == []

    response = _suggest(client, '<script>alert(1)</script>', 'listing')
    assert response.status_code == 200, response.text
    assert response.json()['suggestions'][0]['text'] == '<script>alert(1)</script>'


def test_invalid_rejected_without_persistence(client):
    assert _suggest(client, 'x' * 10001, 'listing').status_code == 422
    assert _suggest(client, 'hello\x00world', 'listing').status_code == 422
    assert _suggest(client, 'Sample', 'tiktok').status_code == 422
    assert _suggest(client, 'Sample', 'LISTING').status_code == 422
    assert client.post('/api/import-suggestions', json={'text': 'Sample'}).status_code == 422
    assert client.post('/api/import-suggestions', json={'source': 'listing'}).status_code == 422
    assert client.post('/api/import-suggestions', json={'text': 123, 'source': 'listing'}).status_code == 422
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []


def _session_cookie(actor):
    response = Response()
    auth.save_session({'actor': actor}, response)
    return response.headers['set-cookie'].split(';')[0].split('=', 1)[1]


def test_auth_required_when_enabled(client, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    assert _suggest(client, 'Canvas tote', 'listing').status_code == 401
    opaque = _session_cookie('google:intake-user-one')
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque)
    response = _suggest(client, 'Canvas tote', 'listing')
    assert response.status_code == 200, response.text
    _assert_unconfirmed_envelope(response.json(), 'listing', 'listing')


def test_stateless_no_cross_user_persistence(client, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    opaque_one = _session_cookie('google:intake-user-one')
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque_one)
    first = _suggest(client, 'User one tote\nLarge', 'listing')
    assert first.status_code == 200, first.text
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []
    opaque_two = _session_cookie('google:intake-user-two')
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque_two)
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []
    second = _suggest(client, 'User two wallet\nCompact', 'listing')
    assert second.status_code == 200, second.text
    assert [s['text'] for s in second.json()['suggestions']] == ['User two wallet', 'Compact']
    assert 'User one tote' not in second.text


def test_unconfirmed_intake_stays_suggestion_until_explicit_confirmation(client):
    intake = _suggest(client, 'Full-grain leather\nBifold compact', 'listing').json()
    assert [s['text'] for s in intake['suggestions']] == ['Full-grain leather', 'Bifold compact']
    unconfirmed = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker',
        'product_facts': {
            'material': {'value': 'Full-grain leather', 'confirmed': True, 'source': 'listing'},
            'size': {'value': 'Bifold compact', 'confirmed': False, 'source': 'listing'},
        }})
    assert unconfirmed.status_code == 201, unconfirmed.text
    receipt = unconfirmed.json()
    assert receipt['status'] == 'completed'
    assert 'Full-grain leather' in receipt['maker_draft_v2']['post']
    assert 'Bifold compact' not in receipt['maker_draft_v2']['post']
    assert 'Bifold compact' not in receipt['product_facts']['confirmed_claims']
    assert 'Bifold compact' not in receipt['product_facts']['allowlist']
    assert [s['value'] for s in receipt['product_facts']['suggested']] == ['Bifold compact']
    confirmed = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker',
        'product_facts': {
            'material': {'value': 'Full-grain leather', 'confirmed': True, 'source': 'listing'},
            'size': {'value': 'Bifold compact', 'confirmed': True, 'source': 'listing'},
        }})
    assert confirmed.status_code == 201, confirmed.text
    receipt = confirmed.json()
    assert 'Bifold compact' in receipt['maker_draft_v2']['post']
    assert 'Bifold compact' in receipt['product_facts']['confirmed_claims']


def test_unsupported_pasted_claim_never_enters_evidence(client):
    pasted = 'Handmade vegan wallet for commuters'
    intake = _suggest(client, pasted, 'instagram_caption').json()
    assert intake['suggestions'][0]['text'] == pasted
    assert intake['suggestions'][0]['confirmed'] is False
    assert intake['product_fact_source'] == 'pasted_text'
    response = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker',
        'product_facts': {
            'material': {'value': 'Full-grain leather', 'confirmed': True},
            'allowed_claims': [{'value': pasted, 'confirmed': False, 'source': 'pasted_text'}],
        }})
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['status'] == 'completed'
    assert pasted not in receipt['maker_draft_v2']['post']
    assert pasted not in receipt['maker_draft_v2']['email']
    assert pasted not in receipt['product_facts']['confirmed_claims']
    assert pasted not in receipt['product_facts']['allowlist']
    assert receipt['memory_claims'] == []
    assert client.get('/api/memory').json() == []
    for entry in receipt['scout']['facts_used']:
        assert entry['verified'] is True
        assert entry['sources'] == ['owner_confirmed_input']


def test_demo_mode_unchanged_after_intake(client):
    assert _suggest(client, 'Canvas tote', 'listing').status_code == 200
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['product_facts']['mode'] == 'demo_template'
    assert receipt['product_facts']['template_used'] is True
    assert '$49' in receipt['maker_draft_v2']['post']
