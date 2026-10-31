"""Draft copy authorization regressions on Postgres.

Deterministic pipeline only, no model calls. The primary post/email
copy buttons must refuse pending, stale, tampered, and foreign packs,
and return only the server-authorized exact text bound to the current
human approval, revision, facts, policy, voice, and photo. Channel
variant approvals keep their own separate gate and keep working.
"""
import copy
import json
from unittest.mock import patch

import pytest
from fastapi.responses import Response as StarletteResponse
from sqlalchemy import text

from backend import auth as auth_mod
from launchcrew import run as run_mod

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
VALID_POST = 'Vegan leather wallet. Designed in Texas.'
VALID_EMAIL = 'For Austin commuters. $49.'


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run_mod.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def new_run(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def approve(client, run_id, revision=0):
    response = client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': revision})
    assert response.status_code == 200, response.text
    return response.json()


def draft_copy(client, run_id, kind, revision=None):
    body = {'kind': kind}
    if revision is not None:
        body['expected_revision'] = revision
    return client.post(f'/api/runs/{run_id}/copy', json=body)


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


def sign_in(client, monkeypatch, actor):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    response = StarletteResponse()
    auth_mod.save_session({'actor': actor}, response)
    client.cookies.clear()
    client.cookies.set(auth_mod.COOKIE,
                       response.headers['set-cookie'].split(';')[0].split('=', 1)[1])


def test_pending_copy_refused_for_post_and_email(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    for kind in ('post', 'email'):
        refused = draft_copy(client, run_id, kind)
        assert refused.status_code == 422, refused.text
        assert 'approval' in refused.json()['detail'].lower()
    reread = client.get(f'/api/runs/{run_id}').json()
    assert reread['approval_state'] == 'pending_approval'
    assert reread.get('approval_binding') is None
    assert reread.get('exported_draft') is None
    steps = [entry.get('step') for entry in reread['audit']['event_log']]
    assert 'draft_copy' not in steps


def test_approved_latest_returns_exact_bound_text(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approved = approve(client, run_id)
    for kind, expected in (('post', receipt['maker_draft_v2']['post']),
                           ('email', receipt['maker_draft_v2']['email'])):
        response = draft_copy(client, run_id, kind)
        assert response.status_code == 200, response.text
        record = response.json()
        assert record['copy_authorized'] is True
        assert record['kind'] == kind
        assert record['text'] == expected
        assert record['text'] != ''
        assert record['revision'] == 0
        assert record['receipt_id'] == run_id
        assert record['approved_by'] == approved['approvals'][-1]['approved_by']
        assert record['binding_digest'] == approved['approval_binding']['digest']
        assert record['binding_version'] == approved['approval_binding']['version']
        assert 'publish' in record['note'].lower()
    explicit = draft_copy(client, run_id, 'post', revision=0)
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()['text'] == receipt['maker_draft_v2']['post']
    reread = client.get(f'/api/runs/{run_id}').json()
    assert reread['approval_state'] == 'approved_for_export'
    assert reread['approved_revision'] == 0
    assert reread['approval_binding'] == approved['approval_binding']
    assert reread.get('exported_draft') is None
    steps = [entry.get('step') for entry in reread['audit']['event_log']]
    assert 'draft_copy' in steps


def test_stale_after_revision_refuses_until_fresh_approval(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    revised = client.post(f'/api/runs/{run_id}/revise',
                          json={'post': VALID_POST, 'email': VALID_EMAIL, 'base_revision': 0})
    assert revised.status_code == 200, revised.text
    stale = draft_copy(client, run_id, 'post', revision=0)
    assert stale.status_code == 409, stale.text
    assert 'stale' in stale.json()['detail'].lower()
    missing = draft_copy(client, run_id, 'post')
    assert missing.status_code == 409, missing.text
    pending = draft_copy(client, run_id, 'post', revision=1)
    assert pending.status_code == 422, pending.text
    assert 'approval' in pending.json()['detail'].lower()
    reapproved = approve(client, run_id, revision=1)
    fresh = draft_copy(client, run_id, 'post', revision=1)
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()['text'] == VALID_POST
    assert fresh.json()['binding_digest'] == reapproved['approval_binding']['digest']
    assert fresh.json()['revision'] == 1
    email = draft_copy(client, run_id, 'email', revision=1)
    assert email.status_code == 200, email.text
    assert email.json()['text'] == VALID_EMAIL
    old = draft_copy(client, run_id, 'email', revision=0)
    assert old.status_code == 409, old.text


def test_post_approval_tampering_refuses_copy(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approved = approve(client, run_id)
    clean = client.get(f'/api/runs/{run_id}').json()

    cases = []
    cases.append(('post copy', lambda r: r['maker_draft_v2'].__setitem__('post', 'Tampered post')))
    cases.append(('email copy', lambda r: r['maker_draft_v2'].__setitem__('email', 'Tampered email')))
    cases.append(('confirmed fact',
                  lambda r: r['product_facts']['confirmed_claims'].__setitem__(0, 'Tampered')))
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

    def tamper_voice_stale(r):
        r['voice_stale'] = True
    cases.append(('voice stale', tamper_voice_stale))

    for name, mutate in cases:
        with test_engine.begin() as connection:
            connection.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'),
                               {'receipt': json.dumps(clean), 'id': run_id})
        tamper_stored(test_engine, run_id, mutate)
        with patch('launchcrew.spark.urlopen', side_effect=AssertionError('no network expected')):
            with patch('backend.sam.urlopen', side_effect=AssertionError('no network expected')):
                refused = draft_copy(client, run_id, 'post')
        assert refused.status_code in (409, 422), name
        detail = refused.json()['detail']
        assert isinstance(detail, str) and detail, name
        reread = client.get(f'/api/runs/{run_id}').json()
        assert reread['approval_binding'] == clean['approval_binding'], name
        assert reread['approved_revision'] == 0, name

    with test_engine.begin() as connection:
        connection.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'),
                           {'receipt': json.dumps(clean), 'id': run_id})

    def tamper_revision(r):
        r['revision'] = 1
        r['approved_revision'] = 1
        r['approvals'][-1]['revision'] = 1
    tamper_stored(test_engine, run_id, tamper_revision)
    assert draft_copy(client, run_id, 'post', revision=1).status_code == 422
    assert approved['approval_binding']['digest'] == clean['approval_binding']['digest']


def test_draft_copy_is_owner_isolated(client, test_engine, monkeypatch):
    sign_in(client, monkeypatch, 'google:iso-draft-one')
    run_id = new_run(client)['run_id']
    approve(client, run_id)
    assert draft_copy(client, run_id, 'post').status_code == 200
    sign_in(client, monkeypatch, 'google:iso-draft-two')
    assert client.get(f'/api/runs/{run_id}').status_code == 404
    assert draft_copy(client, run_id, 'post').status_code == 404
    assert draft_copy(client, run_id, 'email', revision=0).status_code == 404
    sign_in(client, monkeypatch, 'google:iso-draft-one')
    assert draft_copy(client, run_id, 'email').status_code == 200


def test_unknown_run_and_kind_fail_closed(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    assert draft_copy(client, 'run_missing', 'post').status_code == 404
    approve(client, run_id)
    assert draft_copy(client, run_id, 'sms').status_code == 422
    assert client.get(f'/api/runs/{run_id}').json()['approval_state'] == 'approved_for_export'


def test_channel_copy_preserved_alongside_draft_copy(client):
    from launchcrew import channel_variants
    receipt = new_run(client)
    run_id = receipt['run_id']
    approved = approve(client, run_id)
    draft = draft_copy(client, run_id, 'post')
    assert draft.status_code == 200, draft.text
    assert draft.json()['text'] == approved['maker_draft_v2']['post']
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    channel = next(c for c in ('x', 'linkedin', 'instagram', 'email',
                               'facebook', 'tiktok', 'shopify')
                   if bundle[c]['content_valid'] and bundle[c]['text'])
    pending_channel = client.post(f'/api/runs/{run_id}/channel-variants/{channel}/copy',
                                  json={'expected_revision': 0})
    assert pending_channel.status_code == 422, pending_channel.text
    assert 'exact channel text' in pending_channel.json()['detail'].lower()
    variant_approval = client.post(f'/api/runs/{run_id}/channel-variants/{channel}/approve',
                                   json={'expected_revision': 0})
    assert variant_approval.status_code == 200, variant_approval.text
    stored = variant_approval.json()['channel_approvals'][channel]
    channel_copy = client.post(f'/api/runs/{run_id}/channel-variants/{channel}/copy',
                               json={'expected_revision': 0})
    assert channel_copy.status_code == 200, channel_copy.text
    assert channel_copy.json()['copy_authorized'] is True
    assert channel_copy.json()['text'] == stored['text']
    assert channel_copy.json()['binding_digest'] == approved['approval_binding']['digest']
    ok, reason = channel_variants.verify_exact_variant_text(
        channel, channel_copy.json()['text'], stored.get('subject', ''),
        approved['maker_draft_v2']['post'], approved['product_facts']['confirmed_claims'])
    assert ok, reason
    again = draft_copy(client, run_id, 'email')
    assert again.status_code == 200, again.text
    assert again.json()['text'] == approved['maker_draft_v2']['email']
    reread = client.get(f'/api/runs/{run_id}').json()
    assert reread['approval_state'] == 'approved_for_export'
    assert reread['approved_revision'] == 0
    assert reread['approval_binding'] == approved['approval_binding']
