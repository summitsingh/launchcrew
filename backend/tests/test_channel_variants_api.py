"""Slice 4 channel-variants API regressions on Postgres.

Deterministic pipeline only, no model calls. The read-only
channel-variants route derives verbatim candidates from the current
approved post draft and the receipt-bound confirmed claims. It
refuses without current human approval plus a matching approval
binding, keeps every candidate non independently exportable, and
never publishes, posts, or sends.
"""
import copy
import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from launchcrew import channel_variants

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
CHANNELS = ('x', 'linkedin', 'instagram', 'email', 'facebook', 'tiktok', 'shopify')


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    from launchcrew import run as run_mod
    pipeline = run_mod.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return pipeline(*args, **kwargs)

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


def test_unapproved_run_refuses_variants(client, test_engine):
    receipt = new_run(client)
    response = client.get(f'/api/runs/{receipt["run_id"]}/channel-variants')
    assert response.status_code == 422, response.text
    assert 'approval' in response.json()['detail'].lower()


def test_approved_run_returns_checked_bundle(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approved = approve(client, run_id)
    response = client.get(f'/api/runs/{run_id}/channel-variants')
    assert response.status_code == 200, response.text
    bundle = response.json()
    for channel in CHANNELS:
        assert channel in bundle
    assert bundle['receipt_id'] == run_id
    assert bundle['revision'] == approved['revision']
    assert bundle['approval_state'] == 'approved_for_export'
    assert bundle['binding_version'] == approved['approval_binding']['version']
    assert bundle['binding_digest'] == approved['approval_binding']['digest']
    assert bundle['confirmed_claims_count'] == len(
        approved['product_facts']['confirmed_claims'])
    assert bundle['draft_source'] == channel_variants.CHECKED_DRAFT_SOURCE
    assert bundle['no_auto_publish'] is True
    assert 'campaign angle' in bundle['note'].lower()
    post = approved['maker_draft_v2']['post']
    confirmed = approved['product_facts']['confirmed_claims']
    for channel in CHANNELS:
        variant = bundle[channel]
        assert variant['exportable'] is False
        assert variant['independently_exportable'] is False
        assert variant['requires_checker_binding'] is True
        if variant['content_valid']:
            ok, reason = channel_variants.verify_exact_variant_text(
                channel, variant['text'], variant.get('subject', ''),
                post, confirmed)
            assert ok, reason
    assert len(bundle['x']['text']) <= channel_variants.X_MAX_CHARS
    provenance = bundle['provenance']
    assert provenance['exportable'] is False
    assert provenance['audience_context'] is None
    assert provenance['angle_context'] is None


def test_tampered_post_refuses_on_binding(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    with test_engine.begin() as connection:
        row = connection.execute(
            text('SELECT receipt FROM runs WHERE id=:id'),
            {'id': run_id}).fetchone()
        stored = copy.deepcopy(dict(row[0]))
        stored['maker_draft_v2']['post'] += ' Tampered.'
        connection.execute(
            text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'),
            {'receipt': json.dumps(stored), 'id': run_id})
    response = client.get(f'/api/runs/{run_id}/channel-variants')
    assert response.status_code == 422, response.text
    assert 'binding' in response.json()['detail'].lower()


def test_revision_resets_variants_until_reapproval(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approved = approve(client, run_id)
    post = approved['maker_draft_v2']['post']
    email = approved['maker_draft_v2']['email']
    revised = client.post(f'/api/runs/{run_id}/revise',
                          json={'post': post, 'email': email, 'base_revision': 0})
    assert revised.status_code == 200, revised.text
    refused = client.get(f'/api/runs/{run_id}/channel-variants')
    assert refused.status_code == 422, refused.text
    reapproved = approve(client, run_id, revision=1)
    assert reapproved['approved_revision'] == 1
    response = client.get(f'/api/runs/{run_id}/channel-variants')
    assert response.status_code == 200, response.text
    assert response.json()['revision'] == 1
    assert response.json()['binding_digest'] == reapproved['approval_binding']['digest']


def test_unknown_run_returns_404(client, test_engine):
    response = client.get('/api/runs/run_missing/channel-variants')
    assert response.status_code == 404, response.text


def test_approved_bundle_exposes_ad_policy_fields(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    response = client.get(f'/api/runs/{run_id}/channel-variants')
    assert response.status_code == 200, response.text
    bundle = response.json()
    for channel in CHANNELS:
        variant = bundle[channel]
        assert 'ad_policy_passed' in variant, channel
        assert 'ad_policy_hits' in variant, channel
        assert isinstance(variant['ad_policy_passed'], bool)
        assert isinstance(variant['ad_policy_hits'], list)
        assert variant['ad_policy_passed'] == (
            len(variant['ad_policy_hits']) == 0)
        for hit in variant['ad_policy_hits']:
            assert 'category' in hit
            assert 'match' in hit
            assert 'reason' in hit


def copy_text(client, run_id, channel, revision):
    return client.post(f'/api/runs/{run_id}/channel-variants/{channel}/copy',
                       json={'expected_revision': revision})


def approve_variant(client, run_id, channel, revision):
    return client.post(f'/api/runs/{run_id}/channel-variants/{channel}/approve',
                       json={'expected_revision': revision})


def valid_channel(client, run_id):
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    return bundle, next(c for c in CHANNELS
                        if bundle[c]['content_valid'] and bundle[c]['text'])


def test_variant_approval_binds_exact_text_then_copy_succeeds(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approved = approve(client, run_id)
    bundle, channel = valid_channel(client, run_id)
    refused = copy_text(client, run_id, channel, 0)
    assert refused.status_code == 422, refused.text
    assert 'exact channel text' in refused.json()['detail'].lower()
    approval = approve_variant(client, run_id, channel, 0)
    assert approval.status_code == 200, approval.text
    stored = approval.json()['channel_approvals'][channel]
    assert stored['text'] == bundle[channel]['text']
    assert stored['subject'] == bundle[channel]['subject']
    assert stored['revision'] == 0
    assert stored['pack_binding_digest'] == approved['approval_binding']['digest']
    assert stored['approved_by'] not in ('', None)
    response = copy_text(client, run_id, channel, 0)
    assert response.status_code == 200, response.text
    record = response.json()
    assert record['copy_authorized'] is True
    assert record['channel'] == channel
    assert record['text'] == stored['text']
    assert record['text'] != ''
    assert record['revision'] == 0
    assert record['receipt_id'] == run_id
    assert record['approved_by'] == stored['approved_by']
    assert record['binding_digest'] == approved['approval_binding']['digest']
    assert record['binding_version'] == approved['approval_binding']['version']
    reread = client.get(f'/api/runs/{run_id}').json()
    steps = [entry.get('step') for entry in reread['audit']['event_log']]
    assert 'channel_variant_approval' in steps
    assert 'channel_copy' in steps
    assert reread['approval_state'] == 'approved_for_export'
    assert reread['approved_revision'] == 0


def test_copy_rejects_stale_revision_with_409(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    response = copy_text(client, run_id, 'x', 99)
    assert response.status_code == 409, response.text
    assert 'stale' in response.json()['detail'].lower()


def test_copy_after_revision_change_requires_current_revision(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approved = approve(client, run_id)
    bundle, channel = valid_channel(client, run_id)
    assert approve_variant(client, run_id, channel, 0).status_code == 200
    assert copy_text(client, run_id, channel, 0).status_code == 200
    revised = client.post(f'/api/runs/{run_id}/revise',
                          json={'post': approved['maker_draft_v2']['post'],
                                'email': approved['maker_draft_v2']['email'],
                                'base_revision': 0})
    assert revised.status_code == 200, revised.text
    refused = copy_text(client, run_id, channel, 0)
    assert refused.status_code == 409, refused.text
    assert 'stale' in refused.json()['detail'].lower()
    reapproved = approve(client, run_id, revision=1)
    stale_approval = copy_text(client, run_id, channel, 1)
    assert stale_approval.status_code == 409, stale_approval.text
    assert 'stale' in stale_approval.json()['detail'].lower()
    assert approve_variant(client, run_id, channel, 1).status_code == 200
    response = copy_text(client, run_id, channel, 1)
    assert response.status_code == 200, response.text
    assert response.json()['revision'] == 1
    assert response.json()['binding_digest'] == reapproved['approval_binding']['digest']


def test_variant_approval_rejects_stale_revision(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    _, channel = valid_channel(client, run_id)
    wrong = approve_variant(client, run_id, channel, 99)
    assert wrong.status_code == 409, wrong.text
    assert 'stale' in wrong.json()['detail'].lower()


def test_variant_approval_and_copy_are_owner_isolated(client, test_engine, monkeypatch):
    from backend import auth as auth_mod
    from fastapi.responses import Response as StarletteResponse

    def sign_in(actor):
        monkeypatch.setenv('AUTH_ENABLED', 'true')
        response = StarletteResponse()
        auth_mod.save_session({'actor': actor}, response)
        client.cookies.clear()
        client.cookies.set(auth_mod.COOKIE,
                           response.headers['set-cookie'].split(';')[0].split('=', 1)[1])

    sign_in('google:iso-owner-one')
    run_id = new_run(client)['run_id']
    approve(client, run_id)
    _, channel = valid_channel(client, run_id)
    assert approve_variant(client, run_id, channel, 0).status_code == 200
    sign_in('google:iso-owner-two')
    assert client.get(f'/api/runs/{run_id}/channel-variants').status_code == 404
    assert approve_variant(client, run_id, channel, 0).status_code == 404
    assert copy_text(client, run_id, channel, 0).status_code == 404


def test_copy_refuses_tampered_approval_and_policy(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    _, channel = valid_channel(client, run_id)
    assert approve_variant(client, run_id, channel, 0).status_code == 200
    with test_engine.begin() as connection:
        row = connection.execute(
            text('SELECT receipt FROM runs WHERE id=:id'),
            {'id': run_id}).fetchone()
        stored = copy.deepcopy(dict(row[0]))
        stored['channel_approvals'][channel]['text'] += ' Tampered.'
        connection.execute(
            text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'),
            {'receipt': json.dumps(stored), 'id': run_id})
    edited = copy_text(client, run_id, channel, 0)
    assert edited.status_code == 409, edited.text
    assert 'stale' in edited.json()['detail'].lower()
    with test_engine.begin() as connection:
        row = connection.execute(
            text('SELECT receipt FROM runs WHERE id=:id'),
            {'id': run_id}).fetchone()
        stored = copy.deepcopy(dict(row[0]))
        blocked = list(stored.get('blocked_claims') or [])
        blocked.append('Tampered policy rule.')
        stored['blocked_claims'] = blocked
        connection.execute(
            text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'),
            {'receipt': json.dumps(stored), 'id': run_id})
    repolicied = copy_text(client, run_id, channel, 0)
    assert repolicied.status_code == 422, repolicied.text
    assert 'binding' in repolicied.json()['detail'].lower()


def test_copy_refuses_unapproved_tampered_and_unknown(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    pending = copy_text(client, run_id, 'x', 0)
    assert pending.status_code == 422, pending.text
    approve(client, run_id)
    unknown = copy_text(client, run_id, 'sms', 0)
    assert unknown.status_code == 422, unknown.text
    assert 'unknown channel' in unknown.json()['detail'].lower()
    with test_engine.begin() as connection:
        row = connection.execute(
            text('SELECT receipt FROM runs WHERE id=:id'),
            {'id': run_id}).fetchone()
        stored = copy.deepcopy(dict(row[0]))
        stored['maker_draft_v2']['post'] += ' Tampered.'
        connection.execute(
            text('UPDATE runs SET receipt=CAST(:receipt AS jsonb) WHERE id=:id'),
            {'receipt': json.dumps(stored), 'id': run_id})
    tampered = copy_text(client, run_id, 'x', 0)
    assert tampered.status_code == 422, tampered.text
    assert 'binding' in tampered.json()['detail'].lower()
    missing = client.post('/api/runs/run_missing/channel-variants/x/copy',
                          json={'expected_revision': 0})
    assert missing.status_code == 404, missing.text
