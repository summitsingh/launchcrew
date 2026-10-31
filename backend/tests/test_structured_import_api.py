"""API tests for structured per-field import suggestions with replace guard.

Requires the Postgres-backed client fixture. Deterministic pipeline only,
no live model calls, no credentials. Every field suggestion stays
unconfirmed; pending proposals are never silently replaced.
"""
import time
from unittest.mock import patch
from fastapi.responses import Response
import pytest
from launchcrew import run
from launchcrew.import_suggestions import (
    STRUCTURED_PARSER_VERSION,
    parse_structured_import,
)
from backend import auth

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
LISTING_TEXT = '\n'.join([
    'Full-grain leather tote',
    'Holds a 13in laptop in six card slots',
    'Compact bifold size',
    '$49 launch price',
    'Handmade for Austin commuters',
])
BIO_TEXT = '\n'.join([
    'Sampleville bake stand',
    'We bake fresh each morning.',
    'Est. 2021',
])
CAPTION_TEXT = '\n'.join([
    'Fresh batch Friday',
    '20% off bundles',
    'I pack every box myself.',
])


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def _suggest(client, text, source, active_digest=None, confirm_replace=False):
    body = {'text': text, 'source': source}
    if active_digest is not None:
        body['active_digest'] = active_digest
    if confirm_replace:
        body['confirm_replace'] = True
    return client.post('/api/import-suggestions/structured', json=body)


def _assert_structured_envelope(body, source, product_source, replaced=False):
    assert body['status'] == 'unconfirmed'
    assert body['source'] == source
    assert body['product_fact_source'] == product_source
    assert body['parser_version'] == STRUCTURED_PARSER_VERSION
    assert isinstance(body['proposal_digest'], str) and len(body['proposal_digest']) == 64
    assert body['replaced'] is replaced
    assert isinstance(body['truncated'], bool)
    for key in ('dropped_duplicates', 'dropped_overlong', 'dropped_empty'):
        assert isinstance(body[key], int)
    for position, item in enumerate(body['field_suggestions']):
        assert item['status'] == 'unconfirmed'
        assert item['confirmed'] is False
        assert item['source'] == source
        assert item['product_fact_source'] == product_source
        assert item['index'] == position
        assert item['field'] in ('material', 'contents', 'size', 'price',
                                 'allowed_claim', 'founder_note')
        assert isinstance(item['text'], str) and item['text']
        assert set(item) == {'field', 'text', 'source', 'product_fact_source',
                             'status', 'confirmed', 'index'}


def test_listing_splits_into_per_field_suggestions(client):
    response = _suggest(client, LISTING_TEXT, 'listing')
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_structured_envelope(body, 'listing', 'listing')
    by_text = {item['text']: item['field'] for item in body['field_suggestions']}
    assert by_text == {
        'Full-grain leather tote': 'material',
        'Holds a 13in laptop in six card slots': 'contents',
        'Compact bifold size': 'size',
        '$49 launch price': 'price',
        'Handmade for Austin commuters': 'allowed_claim',
    }
    assert body['proposal_digest'] == parse_structured_import(
        LISTING_TEXT, 'listing')['proposal_digest']
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []


def test_bio_and_caption_map_to_pasted_text_with_founder_note(client):
    for source, text, note in (
        ('instagram_bio', BIO_TEXT, 'We bake fresh each morning.'),
        ('instagram_caption', CAPTION_TEXT, 'I pack every box myself.'),
    ):
        response = _suggest(client, text, source)
        assert response.status_code == 200, response.text
        body = response.json()
        _assert_structured_envelope(body, source, 'pasted_text')
        notes = [item for item in body['field_suggestions'] if item['field'] == 'founder_note']
        assert [item['text'] for item in notes] == [note]
        for item in body['field_suggestions']:
            assert item['product_fact_source'] == 'pasted_text'


def test_drive_file_rejected_on_paste_endpoint(client):
    response = _suggest(client, LISTING_TEXT, 'drive_file')
    assert response.status_code == 422
    assert client.get('/api/queue').json() == []


def test_new_paste_with_different_digest_conflicts_without_replacing(client):
    first = _suggest(client, LISTING_TEXT, 'listing').json()
    second = _suggest(client, BIO_TEXT, 'listing', active_digest=first['proposal_digest'])
    assert second.status_code == 409, second.text
    detail = second.json()['detail']
    assert 'pending' in detail['message'].lower()
    assert detail['active_digest'] == first['proposal_digest']
    assert detail['proposal_digest'] != first['proposal_digest']
    held = detail['proposal']
    _assert_structured_envelope(held, 'listing', 'listing')
    assert held['proposal_digest'] == detail['proposal_digest']
    assert held['proposal_digest'] == parse_structured_import(
        BIO_TEXT, 'listing')['proposal_digest']


def test_same_digest_repaste_is_not_a_conflict(client):
    first = _suggest(client, LISTING_TEXT, 'listing').json()
    again = _suggest(client, LISTING_TEXT, 'listing',
                     active_digest=first['proposal_digest'])
    assert again.status_code == 200, again.text
    body = again.json()
    assert body['proposal_digest'] == first['proposal_digest']
    assert body['replaced'] is False


def test_confirmed_replacement_returns_replaced_proposal(client):
    first = _suggest(client, LISTING_TEXT, 'listing').json()
    replaced = _suggest(client, BIO_TEXT, 'listing',
                        active_digest=first['proposal_digest'],
                        confirm_replace=True)
    assert replaced.status_code == 200, replaced.text
    body = replaced.json()
    _assert_structured_envelope(body, 'listing', 'listing', replaced=True)
    assert body['proposal_digest'] != first['proposal_digest']


def test_no_pending_digest_never_conflicts(client):
    body = _suggest(client, LISTING_TEXT, 'listing').json()
    assert body['replaced'] is False


def test_invalid_structured_input_rejected_without_persistence(client):
    assert _suggest(client, 'x' * 10001, 'listing').status_code == 422
    assert _suggest(client, 'hello\x00world', 'listing').status_code == 422
    assert _suggest(client, 'Sample', 'tiktok').status_code == 422
    assert _suggest(client, LISTING_TEXT, 'listing', active_digest='not-a-digest').status_code == 422
    assert _suggest(client, LISTING_TEXT, 'listing', active_digest='x' * 64).status_code == 422
    assert client.post('/api/import-suggestions/structured',
                       json={'source': 'listing'}).status_code == 422
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []


def _session_cookie(actor):
    response = Response()
    auth.save_session({'actor': actor}, response)
    return response.headers['set-cookie'].split(';')[0].split('=', 1)[1]


def test_auth_required_when_enabled(client, monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    assert _suggest(client, LISTING_TEXT, 'listing').status_code == 401
    opaque = _session_cookie('google:intake-user-one')
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque)
    response = _suggest(client, LISTING_TEXT, 'listing')
    assert response.status_code == 200, response.text
    _assert_structured_envelope(response.json(), 'listing', 'listing')


def test_structured_stays_unconfirmed_until_explicit_confirmation(client):
    intake = _suggest(client, LISTING_TEXT, 'listing').json()
    material = next(item for item in intake['field_suggestions'] if item['field'] == 'material')
    size = next(item for item in intake['field_suggestions'] if item['field'] == 'size')
    assert material['confirmed'] is False
    response = client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker',
        'waive_missing_core_facts': True,
        'product_facts': {
            'material': {'value': material['text'], 'confirmed': True, 'source': 'listing'},
            'size': {'value': size['text'], 'confirmed': False, 'source': 'listing'},
        }})
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert material['text'] in receipt['maker_draft_v2']['post']
    assert size['text'] not in receipt['maker_draft_v2']['post']
