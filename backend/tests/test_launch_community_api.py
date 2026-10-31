"""Launch matrix and landing-page parity API regressions on Postgres.

Deterministic pipeline only, no model calls. The read-only
launch-matrix route derives all seven presentation candidates from
the current approved post draft and the receipt-bound confirmed
claims, refusing without current human approval plus a matching
approval binding. The verify-landing-page route audits
caller-supplied landing HTML against the current post draft with no
network access and never modifies the receipt.
"""
from unittest.mock import patch

import pytest

from launchcrew import channel_variants

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
MATRIX_CHANNELS = ('x', 'linkedin', 'instagram', 'email', 'facebook', 'tiktok', 'shopify')

FULL_FOOTER_HTML = (
    '<html><body><h1>Vegan leather wallet, $49</h1>'
    '<a href="/privacy">Privacy Policy</a>'
    '<a href="/terms">Terms of Service</a>'
    '<a href="/refunds">Refund Policy</a>'
    '</body></html>'
)


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


def test_unapproved_run_refuses_launch_matrix(client, test_engine):
    receipt = new_run(client)
    response = client.get(f'/api/runs/{receipt["run_id"]}/launch-matrix')
    assert response.status_code == 422, response.text
    assert 'approval' in response.json()['detail'].lower()


def test_approved_run_returns_seven_channel_matrix(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approved = approve(client, run_id)
    response = client.get(f'/api/runs/{run_id}/launch-matrix')
    assert response.status_code == 200, response.text
    bundle = response.json()
    for channel in MATRIX_CHANNELS:
        assert channel in bundle, channel
    assert bundle['bundle_version'] == channel_variants.CHECKED_LAUNCH_MATRIX_VERSION
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
    for channel in MATRIX_CHANNELS:
        variant = bundle[channel]
        assert variant['exportable'] is False
        assert variant['independently_exportable'] is False
        assert variant['requires_checker_binding'] is True
        if variant['content_valid']:
            ok, reason = channel_variants.verify_exact_variant_text(
                channel, variant['text'], variant.get('subject', ''),
                post, confirmed)
            assert ok, reason
    provenance = bundle['provenance']
    assert provenance['matrix'] is True
    assert provenance['channels'] == list(MATRIX_CHANNELS)


def test_launch_matrix_matches_channel_variants_gate(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    matrix = client.get(f'/api/runs/{run_id}/launch-matrix').json()
    packed = client.get(f'/api/runs/{run_id}/channel-variants').json()
    for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook'):
        assert matrix[channel]['text'] == packed[channel]['text']
    assert matrix['binding_digest'] == packed['binding_digest']


def test_launch_matrix_unknown_run_returns_404(client, test_engine):
    response = client.get('/api/runs/run_missing/launch-matrix')
    assert response.status_code == 404, response.text


def test_verify_landing_page_passes_matching_offer(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    response = client.post(f'/api/runs/{run_id}/verify-landing-page',
                           json={'landing_html': FULL_FOOTER_HTML})
    assert response.status_code == 200, response.text
    audit = response.json()
    assert audit['parity_passed'] is True
    assert audit['legal_compliance_passed'] is True
    assert audit['overall_passed'] is True
    assert '$49' in audit['ad_prices']
    assert '$49' in audit['landing_prices']
    assert audit['unmatched_ad_prices'] == []
    assert sorted(audit['detected_policies']) == ['privacy_policy', 'refund_policy', 'terms_of_service']
    assert audit['missing_policies'] == []
    assert audit['version'] == 'landing-parity/v1'


def test_verify_landing_page_flags_price_mismatch(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    html = FULL_FOOTER_HTML.replace('$49', '$99')
    response = client.post(f'/api/runs/{run_id}/verify-landing-page',
                           json={'landing_html': html})
    assert response.status_code == 200, response.text
    audit = response.json()
    assert audit['parity_passed'] is False
    assert audit['overall_passed'] is False
    assert '$49' in audit['unmatched_ad_prices']


def test_verify_landing_page_flags_missing_legal_footer(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    html = '<html><body><h1>Vegan leather wallet, $49</h1></body></html>'
    response = client.post(f'/api/runs/{run_id}/verify-landing-page',
                           json={'landing_html': html,
                                 'landing_url': 'https://example.invalid/shop'})
    assert response.status_code == 200, response.text
    audit = response.json()
    assert audit['parity_passed'] is True
    assert audit['legal_compliance_passed'] is False
    assert audit['overall_passed'] is False
    assert sorted(audit['missing_policies']) == ['privacy_policy', 'refund_policy', 'terms_of_service']


def test_verify_landing_page_leaves_receipt_unchanged(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    before = client.get(f'/api/runs/{run_id}').json()
    response = client.post(f'/api/runs/{run_id}/verify-landing-page',
                           json={'landing_html': FULL_FOOTER_HTML})
    assert response.status_code == 200, response.text
    after = client.get(f'/api/runs/{run_id}').json()
    assert after == before


def test_verify_landing_page_unknown_run_returns_404(client, test_engine):
    response = client.post('/api/runs/run_missing/verify-landing-page',
                           json={'landing_html': FULL_FOOTER_HTML})
    assert response.status_code == 404, response.text


def test_verify_landing_page_rejects_blank_html(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    response = client.post(f'/api/runs/{run_id}/verify-landing-page',
                           json={'landing_html': ''})
    assert response.status_code == 422, response.text


def test_launch_matrix_and_parity_are_owner_isolated(client, test_engine, monkeypatch):
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
    assert client.get(f'/api/runs/{run_id}/launch-matrix').status_code == 200
    sign_in('google:iso-owner-two')
    assert client.get(f'/api/runs/{run_id}/launch-matrix').status_code == 404
    assert client.post(f'/api/runs/{run_id}/verify-landing-page',
                       json={'landing_html': FULL_FOOTER_HTML}).status_code == 404
