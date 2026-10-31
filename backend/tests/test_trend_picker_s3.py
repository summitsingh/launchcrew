"""S3 trend format picker acceptance tests.

Covers the milestone contract: an optional trend attaches as Maker angle
guidance only, is screened by the banned-claim and superlative rules, is
recorded on the receipt, and never leaks into drafts or channel variants.
A run without a trend behaves exactly as today. The pipeline runs
deterministically with no model calls. Nothing here auto-posts,
auto-sends, or auto-spends.
"""
from unittest.mock import patch

import pytest

from launchcrew import trend_picker

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'

SUPERLATIVE_TREND = 'The #1 best most durable wallet in the world'


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
    return client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': revision})


# Acceptance 1: a run with a trend records the label, source, and
# guidance-only role on the receipt.
def test_run_with_trend_records_guidance_on_receipt(client, test_engine):
    receipt = new_run(client, trend_label='POV unboxing transition',
                      trend_source='TikTok inspiration page')
    trend = receipt['trend_format']
    assert trend['label'] == 'POV unboxing transition'
    assert trend['source_label'] == 'TikTok inspiration page'
    assert trend['role'] == 'maker_angle_guidance_only'
    assert trend['guidance_only'] is True
    assert trend['fact_source'] is False
    assert trend['sanitized_guidance'] == 'POV unboxing transition'
    assert trend['screened_out_claims'] == []


# Acceptance 2: a trend without the required source label is refused
# with a clear validation message naming source_label.
def test_trend_without_source_label_rejected(client, test_engine):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                              'trend_label': 'POV unboxing transition'})
    assert response.status_code == 422, response.text
    assert 'source_label' in response.text
    blank = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker',
                                           'trend_label': 'POV unboxing transition',
                                           'trend_source': '   '})
    assert blank.status_code == 422, blank.text
    assert 'source_label' in blank.text


# Acceptance 2b: the async run path refuses the same way before accept.
def test_async_run_with_trend_missing_source_rejected(client, test_engine):
    response = client.post('/api/runs/async', json={'idea': IDEA, 'agent_name': 'Maker',
                                                    'trend_label': 'POV unboxing transition',
                                                    'trend_source': ''})
    assert response.status_code == 422, response.text
    assert 'source_label' in response.text


# Acceptance 3: a trend containing a superlative claim is screened and
# the superlative never leaks into the draft or channel variants.
def test_superlative_trend_screened_and_never_leaks(client, test_engine):
    receipt = new_run(client, trend_label=SUPERLATIVE_TREND,
                      trend_source='Seasonal format')
    trend = receipt['trend_format']
    assert trend['role'] == 'maker_angle_guidance_only'
    assert trend['fact_source'] is False
    screened = trend['screened_out_claims']
    assert 'best' in screened
    draft_text = (receipt['maker_draft_v2']['post'] + '\n'
                  + receipt['maker_draft_v2']['email'] + '\n'
                  + '\n'.join(receipt['maker_draft_v2']['claims']))
    lowered = draft_text.lower()
    for term in screened:
        assert term.lower() not in lowered, 'screened term leaked into draft: %r' % term
    assert SUPERLATIVE_TREND.lower() not in lowered
    approved = approve(client, receipt['run_id'])
    assert approved.status_code == 200, approved.text
    bundle = client.get('/api/runs/%s/channel-variants' % receipt['run_id'])
    assert bundle.status_code == 200, bundle.text
    for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook', 'tiktok', 'shopify'):
        text = (bundle.json()[channel].get('text') or '')
        for term in screened:
            assert term.lower() not in text.lower(), 'screened term leaked into %s variant: %r' % (channel, term)


# Acceptance 3b: screened guidance keeps the non-hype angle words.
def test_screened_guidance_keeps_angle_words():
    attachment = trend_picker.build_trend_attachment(SUPERLATIVE_TREND, 'Seasonal format')
    assert 'wallet' in attachment['sanitized_guidance']
    assert attachment['sanitized_guidance'] != SUPERLATIVE_TREND


# Acceptance 4: a campaign day with a trend records it as guidance only.
def test_campaign_day_with_trend_records_guidance(client, test_engine):
    response = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker',
                                                   'trend_label': 'Get ready with me morning routine',
                                                   'trend_source': 'Named creator format'})
    assert response.status_code == 201, response.text
    campaign = response.json()
    assert len(campaign['days']) == 7
    first = campaign['days'][0]
    assert first['trend_guidance']
    assert first['trend_source'] == 'Named creator format'
    stored = client.get('/api/runs/%s' % campaign['days'][0]['run_id'])
    assert stored.status_code == 200, stored.text
    trend = stored.json()['trend_format']
    assert trend['label'] == 'Get ready with me morning routine'
    assert trend['source_label'] == 'Named creator format'
    assert trend['role'] == 'maker_angle_guidance_only'
    assert trend['fact_source'] is False


# Acceptance 4b: a campaign without a trend leaves every day clean.
def test_campaign_without_trend_leaves_days_clean(client, test_engine):
    response = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    for day in response.json()['days']:
        assert day['trend_label'] == ''
        assert day['trend_source'] == ''
        assert day['trend_guidance'] == ''


# Acceptance 5: a run without a trend behaves exactly as today.
def test_run_without_trend_behaves_as_today(client, test_engine):
    plain = new_run(client)
    assert plain['trend_format'] is None
    trended = new_run(client, trend_label='POV unboxing transition',
                      trend_source='TikTok inspiration page')
    assert trended['trend_format'] is not None
    assert plain['maker_draft_v2'] == trended['maker_draft_v2']
    assert plain['checker_v2']['blocked_count'] == trended['checker_v2']['blocked_count'] == 0


# Screen endpoint: previews screening without creating a run.
def test_trends_screen_endpoint(client, test_engine):
    presets = client.get('/api/trends/presets')
    assert presets.status_code == 200, presets.text
    assert 'TikTok inspiration page' in presets.json()['presets']
    screened = client.post('/api/trends/screen',
                           json={'label': SUPERLATIVE_TREND, 'source_label': 'Seasonal format'})
    assert screened.status_code == 200, screened.text
    attachment = screened.json()['attachment']
    assert attachment['role'] == 'maker_angle_guidance_only'
    assert 'best' in attachment['screened_out_claims']
    refused = client.post('/api/trends/screen', json={'label': 'POV unboxing'})
    assert refused.status_code == 422, refused.text
    assert 'source_label' in refused.text
    empty = client.post('/api/trends/screen', json={'label': '', 'source_label': ''})
    assert empty.status_code == 200, empty.text
    assert empty.json()['attachment'] is None


# Domain unit: validation names source_label and rejects overlong labels.
def test_trend_picker_validation_unit():
    assert trend_picker.build_trend_attachment(None, None) is None
    assert trend_picker.build_trend_attachment('', '  ') is None
    with pytest.raises(ValueError, match='source_label'):
        trend_picker.build_trend_attachment('POV unboxing', '')
    with pytest.raises(ValueError, match='source_label'):
        trend_picker.build_trend_attachment('POV unboxing', None)
    with pytest.raises(ValueError, match='at most'):
        trend_picker.build_trend_attachment('x' * 281, 'Seasonal format')
    assert trend_picker.validate_trend_input(None, None) is None
