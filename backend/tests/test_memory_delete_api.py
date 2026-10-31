"""Regression tests for memory deletion and voice profile operations.

Requires the Postgres-backed client fixture. Deterministic pipeline only,
no live model calls, no credentials.

Covers the memory delete endpoint used by the Memory view confirmation
dialogue (204 removes the item, missing ids 404, deleted ids no longer
resolve in runs) plus voice profile create, edit, and banned-term
blocking through the same API.
"""
from unittest.mock import patch

import pytest

from launchcrew import run

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


@pytest.fixture(autouse=True)
def no_model_key(monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)


def _examples():
    topics = ('garden layout', 'trail map', 'recipe card')
    return [{'input': 'Synthetic draft about %s' % topic,
             'output': 'Synthetic revision about %s' % topic} for topic in topics]


def _voice_content(terms):
    return {'examples': _examples(), 'banned_terms': list(terms)}


def create_memory(client, kind, title, content):
    response = client.post('/api/memory', json={'kind': kind, 'title': title, 'content': content})
    assert response.status_code == 201, response.text
    return response.json()


def test_delete_removes_item_and_second_delete_404s(client):
    item = create_memory(client, 'brand_fact', 'Wallet fact', {'claim': 'Wallet body is vegan leather'})
    assert client.get('/api/memory/' + item['id']).status_code == 200
    assert client.delete('/api/memory/' + item['id']).status_code == 204
    assert client.get('/api/memory/' + item['id']).status_code == 404
    assert client.delete('/api/memory/' + item['id']).status_code == 404
    listed = client.get('/api/memory').json()
    assert all(entry['id'] != item['id'] for entry in listed)


def test_delete_missing_item_404s(client):
    assert client.delete('/api/memory/mem_missing').status_code == 404


def test_run_with_deleted_memory_id_404s(client):
    item = create_memory(client, 'blocked_rule', 'Old rule', {'claim': 'best in Texas'})
    assert client.delete('/api/memory/' + item['id']).status_code == 204
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [item['id']]})
    assert response.status_code == 404


def test_voice_create_edit_and_banned_term_block(client):
    voice = create_memory(client, 'voice_profile', 'Synthetic voice', _voice_content(['harbor']))
    assert voice['kind'] == 'voice_profile'
    assert voice['content']['banned_terms'] == ['harbor']
    edited = client.put('/api/memory/' + voice['id'],
                        json={'title': 'Synthetic voice edited', 'content': _voice_content(['harbor', 'lighthouse'])})
    assert edited.status_code == 200
    body = edited.json()
    assert body['title'] == 'Synthetic voice edited'
    assert sorted(body['content']['banned_terms']) == ['harbor', 'lighthouse']
    # The harbor term is absent from the deterministic draft, so this run
    # records the voice selection on the receipt without firing the veto.
    # The veto itself is covered by test_voice_banned_term_blocks_draft_claim.
    run_response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]})
    assert run_response.status_code == 201, run_response.text
    receipt = run_response.json()
    assert receipt['voice_profile']['id'] == voice['id']
    assert receipt['voice_profile']['banned_terms'] == ['harbor', 'lighthouse']
    assert receipt.get('voice_stale') is not True


def test_voice_banned_term_blocks_draft_claim(client):
    voice = create_memory(client, 'voice_profile', 'Synthetic voice', _voice_content(['wallet']))
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]})
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['checker_v1']['blocked_count'] >= 1
    voice_blocks = [entry for entry in receipt['checker_v1']['blocked_claims']
                    if entry['reason'].startswith('Blocked by voice profile')]
    assert voice_blocks, receipt['checker_v1']['blocked_claims']
    assert any('wallet' in entry['claim'].casefold() for entry in voice_blocks)
    assert 'wallet' not in receipt['maker_draft_v2']['post'].casefold()


def test_voice_create_rejects_bad_content(client):
    bad_examples = {'examples': [{'input': 'only one', 'output': 'x'}], 'banned_terms': []}
    response = client.post('/api/memory', json={'kind': 'voice_profile', 'title': 'Bad voice', 'content': bad_examples})
    assert response.status_code == 422
    bad_term = dict(_voice_content(['!!!']))
    response = client.post('/api/memory', json={'kind': 'voice_profile', 'title': 'Bad term', 'content': bad_term})
    assert response.status_code == 422


def test_voice_edit_rejects_bad_content_and_kind_change(client):
    voice = create_memory(client, 'voice_profile', 'Synthetic voice', _voice_content(['harbor']))
    bad = client.put('/api/memory/' + voice['id'],
                     json={'title': 'Synthetic voice', 'content': {'examples': [], 'banned_terms': []}})
    assert bad.status_code == 422
    changed = client.put('/api/memory/' + voice['id'],
                         json={'title': 'Synthetic voice', 'content': _voice_content(['harbor']), 'kind': 'brand_fact'})
    assert changed.status_code == 422
    # The stored voice is unchanged after the rejected edits.
    reread = client.get('/api/memory/' + voice['id']).json()
    assert reread['content']['banned_terms'] == ['harbor']


def test_delete_voice_marks_dependent_run_stale(client):
    voice = create_memory(client, 'voice_profile', 'Synthetic voice', _voice_content(['harbor']))
    run_response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [voice['id']]})
    assert run_response.status_code == 201, run_response.text
    run_id = run_response.json()['run_id']
    assert client.delete('/api/memory/' + voice['id']).status_code == 204
    reread = client.get('/api/runs/' + run_id).json()
    assert reread['voice_stale'] is True
    assert reread['approvals'] == []
