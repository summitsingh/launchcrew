"""Approval binding API regressions on Postgres.

Deterministic pipeline only, no model calls. Approval stores a versioned
SHA-256 digest over the checked artifact; export recomputes it every time,
including revision zero. Tampering with facts, copy, policy, photo, check,
or revision after approval refuses export even when approved_revision and
blocked_count still look clean.
"""
import base64
import copy
import io
import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from launchcrew import human_review, run

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def new_run(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def tamper_stored(test_engine, run_id, mutate):
    with test_engine.begin() as connection:
        row = connection.execute(text('SELECT receipt FROM runs WHERE id=:id'),
                                 {'id': run_id}).fetchone()
        assert row is not None
        stored = copy.deepcopy(dict(row[0]))
        mutate(stored)
        connection.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'),
                           {'receipt': json.dumps(stored), 'id': run_id})
    return stored


def test_clean_run_binds_exports_and_reads_back(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approved = client.post(f'/api/runs/{run_id}/approve', json={})
    assert approved.status_code == 200, approved.text
    body = approved.json()
    binding = body.get('approval_binding')
    assert isinstance(binding, dict)
    assert binding['version'] == human_review.APPROVAL_BINDING_VERSION
    assert len(binding['digest']) == 64
    assert body['approved_revision'] == 0
    assert body['approvals'][-1]['binding_digest'] == binding['digest']
    assert body['approvals'][-1]['binding_version'] == binding['version']
    reread = client.get(f'/api/runs/{run_id}').json()
    assert reread['approval_binding'] == binding
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('no network expected')):
        with patch('backend.sam.urlopen', side_effect=AssertionError('no network expected')):
            exported = client.post(f'/api/runs/{run_id}/export', json={})
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    assert payload['exported_revision'] == 0
    assert payload['exported_draft']['post'] == receipt['maker_draft_v2']['post']
    assert payload['exported_draft']['email'] == receipt['maker_draft_v2']['email']
    final = client.get(f'/api/runs/{run_id}').json()
    assert final['approval_binding'] == binding
    assert final['exported_draft']['post'] == receipt['maker_draft_v2']['post']


def test_owner_run_binds_confirmed_facts(client):
    payload = {'idea': IDEA, 'agent_name': 'Maker',
               'product_facts': {'material': {'value': 'Full-grain leather', 'confirmed': True},
                                 'contents': {'value': 'Six card slots', 'confirmed': True},
                                 'size': {'value': 'Bifold compact', 'confirmed': True},
                                 'price': {'value': '$129', 'confirmed': True}}}
    response = client.post('/api/runs', json=payload)
    assert response.status_code == 201, response.text
    run_id = response.json()['run_id']
    approved = client.post(f'/api/runs/{run_id}/approve', json={})
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body['product_facts']['mode'] == 'owner_input'
    assert body['approval_binding']['version'] == human_review.APPROVAL_BINDING_VERSION
    exported = client.post(f'/api/runs/{run_id}/export', json={})
    assert exported.status_code == 200, exported.text
    assert 'Full-grain leather' in exported.json()['exported_draft']['post']


def test_revision_clears_binding_and_reapproves_new_digest(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    old_digest = client.get(f'/api/runs/{run_id}').json()['approval_binding']['digest']
    edit = {'post': 'Vegan leather wallet. Designed in Texas.',
            'email': 'For Austin commuters. $49.', 'base_revision': 0}
    revised = client.post(f'/api/runs/{run_id}/revise', json=edit)
    assert revised.status_code == 200, revised.text
    body = revised.json()
    assert body['revision'] == 1
    assert body['approval_state'] == 'pending_approval'
    assert body.get('approval_binding') is None
    assert body['approvals'] == []
    assert client.post(f'/api/runs/{run_id}/export', json={'expected_revision': 1}).status_code == 422
    assert client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': 1}).status_code == 200
    reapproved = client.get(f'/api/runs/{run_id}').json()
    assert reapproved['approval_binding']['digest'] != old_digest
    exported = client.post(f'/api/runs/{run_id}/export', json={'expected_revision': 1})
    assert exported.status_code == 200, exported.text
    assert exported.json()['exported_draft']['post'] == edit['post']
    assert exported.json()['exported_draft']['email'] == edit['email']


def test_wrapper_revision_passes_and_exports(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    edit = {'post': 'Hello Designed in Texas, shop now!',
            'email': 'Hi Designed in Texas, learn more.',
            'base_revision': receipt.get('revision', 0)}
    revised = client.post(f'/api/runs/{run_id}/revise', json=edit)
    assert revised.status_code == 200, revised.text
    body = revised.json()
    assert body['human_check']['blocked_count'] == 0
    for claim in body['human_draft']['claims']:
        assert claim in receipt['product_facts']['confirmed_claims']
    assert client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': 1}).status_code == 200
    exported = client.post(f'/api/runs/{run_id}/export', json={'expected_revision': 1})
    assert exported.status_code == 200, exported.text
    assert exported.json()['exported_draft']['post'] == edit['post']


def test_photo_check_and_remove_clear_binding(client, monkeypatch):
    from PIL import Image
    monkeypatch.delenv('META_API_KEY', raising=False)
    monkeypatch.delenv('LAUNCHCREW_PHOTO_SAM_ENABLED', raising=False)
    run_id = new_run(client)['run_id']
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    old_digest = client.get(f'/api/runs/{run_id}').json()['approval_binding']['digest']
    buffer = io.BytesIO()
    Image.new('RGB', (32, 16), (200, 30, 30)).save(buffer, format='PNG')
    uri = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
    with patch('backend.sam.urlopen', side_effect=AssertionError('zero HTTP expected')):
        checked = client.post(f'/api/runs/{run_id}/photo-check',
                              json={'image_data_uri': uri, 'expected_revision': 0})
    assert checked.status_code == 200, checked.text
    body = checked.json()['receipt']
    assert body['revision'] == 1
    assert body.get('approval_binding') is None
    assert body['approval_state'] == 'pending_approval'
    assert body['revision_history'][-1]['approval_binding']['digest'] == old_digest
    removed = client.request('DELETE', f'/api/runs/{run_id}/photo', json={'expected_revision': 1})
    assert removed.status_code == 200, removed.text
    reread = client.get(f'/api/runs/{run_id}').json()
    assert reread['revision'] == 2
    assert reread.get('approval_binding') is None
    assert client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': 2}).status_code == 200
    final = client.get(f'/api/runs/{run_id}').json()
    assert final['approval_binding']['digest'] != old_digest
    assert client.post(f'/api/runs/{run_id}/export', json={'expected_revision': 2}).status_code == 200


def test_stale_revision_refused(client):
    run_id = new_run(client)['run_id']
    edit = {'post': 'Vegan leather wallet. Designed in Texas.',
            'email': 'For Austin commuters. $49.', 'base_revision': 0}
    assert client.post(f'/api/runs/{run_id}/revise', json=edit).status_code == 200
    assert client.post(f'/api/runs/{run_id}/revise', json=edit).status_code == 409
    assert client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': 0}).status_code == 409
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 409
    assert client.post(f'/api/runs/{run_id}/export', json={'expected_revision': 0}).status_code == 409


def test_post_approval_tampering_refuses_export(client, test_engine):
    run_id = new_run(client)['run_id']
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    clean = client.get(f'/api/runs/{run_id}').json()
    assert clean['approval_binding']['digest']

    cases = []
    cases.append(('confirmed fact', lambda r: r['product_facts']['confirmed_claims'].__setitem__(0, 'Tampered')))
    cases.append(('scout source', lambda r: r['scout']['sources'].__setitem__(0, 'tampered_source')))
    cases.append(('post copy', lambda r: r['maker_draft_v2'].__setitem__('post', 'Tampered post')))
    cases.append(('email copy', lambda r: r['maker_draft_v2'].__setitem__('email', 'Tampered email')))
    cases.append(('checker policy', lambda r: r.__setitem__('checker_policies', ['superlatives'])))
    cases.append(('blocked rule', lambda r: r.__setitem__('blocked_claims', ['Designed in Texas'])))

    def tamper_verified(r):
        r['checker_v2']['verified_count'] = r['checker_v2']['verified_count'] + 1
    cases.append(('checker result', tamper_verified))

    def tamper_photo(r):
        r['photo_status'] = {'state': 'checked', 'label': 'detected',
                             'reason': 'clear_single',
                             'policy_version': 'photo-geometry/v1',
                             'revision': 0, 'actor': '', 'checked_at': ''}
    cases.append(('photo state', tamper_photo))

    for name, mutate in cases:
        with test_engine.begin() as connection:
            connection.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'),
                               {'receipt': json.dumps(clean), 'id': run_id})
        tampered = tamper_stored(test_engine, run_id, mutate)
        assert tampered['approval_state'] == 'approved_for_export'
        assert tampered['checker_v2']['blocked_count'] == 0
        with patch('launchcrew.spark.urlopen', side_effect=AssertionError('no network expected')):
            with patch('backend.sam.urlopen', side_effect=AssertionError('no network expected')):
                refused = client.post(f'/api/runs/{run_id}/export', json={})
        assert refused.status_code == 422, name
        # A refused export does not mutate the stored receipt.
        reread = client.get(f'/api/runs/{run_id}').json()
        assert reread['approval_binding'] == clean['approval_binding'], name
        assert reread['approved_revision'] == 0, name

    # Shared revision tampering with a matching approved_revision still fails.
    with test_engine.begin() as connection:
        connection.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'),
                           {'receipt': json.dumps(clean), 'id': run_id})

    def tamper_revision(r):
        r['revision'] = 1
        r['approved_revision'] = 1
        r['approvals'][-1]['revision'] = 1
    tamper_stored(test_engine, run_id, tamper_revision)
    assert client.post(f'/api/runs/{run_id}/export', json={'expected_revision': 1}).status_code == 422


def test_historical_unbound_export_refused(client, test_engine):
    run_id = new_run(client)['run_id']
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200

    def strip_binding(r):
        r['approval_binding'] = None
        r['approvals'][-1].pop('binding_version', None)
        r['approvals'][-1].pop('binding_digest', None)
    tamper_stored(test_engine, run_id, strip_binding)
    reread = client.get(f'/api/runs/{run_id}').json()
    assert reread['approval_state'] == 'approved_for_export'
    assert reread.get('approval_binding') is None
    refused = client.post(f'/api/runs/{run_id}/export', json={})
    assert refused.status_code == 422
    assert 'binding' in refused.json()['detail'].lower()
