"""S2 format library, brand kit, and channel capabilities acceptance tests.

Covers all six S2 acceptance tests at the domain level plus the API
surface: standalone format and capability routes, format_spec on run
creation with approval blocking, brand kit versions on receipts, and
the capabilities table exposed on checked channel bundles. The
pipeline runs deterministically with no model calls. Nothing here
auto-posts, auto-sends, or auto-spends.
"""
import copy
from unittest.mock import patch

import pytest

from launchcrew import brand_kit, channel_variants, format_library
from launchcrew.format_library import (
    CAPABILITY_CHANNELS,
    CHANNEL_CAPABILITIES,
    check_format,
)

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'

VOICE_EXAMPLES = [
    {'input': 'Announce the wallet %d' % index, 'output': 'Wallet note %d' % index}
    for index in range(3)
]


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


def voice_content(colors=('navy',)):
    return {
        'examples': copy.deepcopy(VOICE_EXAMPLES),
        'banned_terms': [],
        'brand_colors': list(colors),
        'fonts': ['Grotesk'],
        'logo_reference': 'assets/logo.png',
        'banned_rules': ['hype'],
    }


def create_voice(client, content):
    response = client.post('/api/memory', json={'kind': 'voice_profile', 'title': 'House voice', 'content': content})
    assert response.status_code == 201, response.text
    return response.json()


# Acceptance 1: a feed run with 1 frame is blocked naming the carousel rule.
def test_feed_carousel_single_frame_blocked_naming_rule():
    result = check_format({'format_kind': 'feed_carousel', 'frame_count': 1, 'aspect_ratio': '4:5'})
    assert result['passed'] is False
    assert 'carousel' in ' '.join(result['reasons']).lower()
    assert '5 to 10 frames at 4:5' in ' '.join(result['reasons'])


# Acceptance 2: a feed run with 6 frames at 4:5 passes format check.
def test_feed_carousel_six_frames_passes():
    result = check_format({'format_kind': 'feed_carousel', 'frame_count': 6, 'aspect_ratio': '4:5'})
    assert result['passed'] is True
    assert result['reasons'] == []


# Acceptance 3: reel hook at or over 140 chars blocked naming the limit; under passes.
def test_reel_hook_limit_blocked_and_passing():
    blocked = check_format({'format_kind': 'reel_script', 'hook_text': 'h' * 140, 'shots': ['Wide shot']})
    assert blocked['passed'] is False
    assert 'under 140 characters' in ' '.join(blocked['reasons'])
    narrow = check_format({'format_kind': 'reel_script', 'hook_text': 'h' * 139, 'shots': ['Wide shot']})
    assert narrow['passed'] is True
    missing_shots = check_format({'format_kind': 'reel_script', 'hook_text': 'short hook', 'shots': []})
    assert missing_shots['passed'] is False


# Acceptance 4: story outside 3 to 6 frames blocked naming the rule; inside passes.
def test_story_frame_rule_blocked_and_passing():
    blocked = check_format({'format_kind': 'story_sequence', 'frame_ideas': ['one', 'two']})
    narrow = ' '.join(blocked['reasons'])
    assert blocked['passed'] is False
    assert '3 to 6 frames' in narrow
    assert 'one idea per frame' in narrow
    passing = check_format({'format_kind': 'story_sequence', 'frame_ideas': ['one', 'two', 'three']})
    assert passing['passed'] is True


# Acceptance 5a: over-limit X text trims by rule with trim and capability noted.
def test_x_variant_over_limit_trims_with_capability_noted():
    sentences = ['Opening sentence here.'] + ['Filler sentence number %d here.' % index for index in range(1, 40)]
    draft = ' '.join(sentences)
    assert len(draft) > CHANNEL_CAPABILITIES['x']['caption_limit']
    variant = channel_variants.build_x_variant(draft, [])
    assert variant['content_valid'] is True
    assert variant['status'] == channel_variants.STATUS_CANDIDATE
    assert len(variant['text']) <= CHANNEL_CAPABILITIES['x']['caption_limit']
    assert variant['trim_note']
    assert 'capability' in variant['trim_note'].lower()
    applied = channel_variants.apply_channel_capability('x', draft)
    assert applied['trimmed'] is True
    assert applied['blocked'] is False
    assert 'capability' in applied['reason'].lower()
    assert applied['text'] == variant['text']


# Acceptance 5b: X first sentence over the limit blocks with the capability named.
def test_x_variant_first_sentence_over_limit_blocked_with_capability():
    draft = 'x' * (CHANNEL_CAPABILITIES['x']['caption_limit'] + 10)
    variant = channel_variants.build_x_variant(draft, [])
    assert variant['content_valid'] is False
    assert 'capability' in (variant['reason'] or '').lower()
    applied = channel_variants.apply_channel_capability('x', draft)
    assert applied['blocked'] is True
    assert 'capability' in applied['reason'].lower()


# Acceptance 6 domain: brand kit version changes when a color, font, or logo changes.
def test_brand_kit_version_changes_on_kit_edit():
    first = brand_kit.brand_kit_receipt(voice_content(colors=('navy',)))
    changed_color = brand_kit.brand_kit_receipt(voice_content(colors=('copper',)))
    assert first['version'] != changed_color['version']
    assert first['digest'] != changed_color['digest']
    changed_font = copy.deepcopy(voice_content(colors=('navy',)))
    changed_font['fonts'] = ['Serif']
    assert brand_kit.brand_kit_version(changed_font) != first['version']
    changed_logo = copy.deepcopy(voice_content(colors=('navy',)))
    changed_logo['logo_reference'] = 'assets/logo-v2.png'
    assert brand_kit.brand_kit_version(changed_logo) != first['version']
    assert set(first) >= {'version', 'digest', 'brand_colors', 'fonts', 'logo_reference', 'banned_rules'}


def test_capabilities_table_covers_all_channels():
    assert set(CAPABILITY_CHANNELS) == {'instagram', 'facebook', 'threads', 'x', 'linkedin', 'tiktok', 'pinterest', 'email', 'shopify'}
    for channel in CAPABILITY_CHANNELS:
        row = CHANNEL_CAPABILITIES[channel]
        assert row['channel'] == channel
        assert row['allowed_formats']
        assert isinstance(row['caption_limit'], int) and row['caption_limit'] > 0
        assert {'aspect_ratios', 'min_frames', 'max_frames'} <= set(row['media_constraints'])


def test_single_image_never_for_feed_but_allowed_for_stories_and_ads():
    blocked = check_format({'format_kind': 'single_image', 'target_surface': 'feed'})
    assert blocked['passed'] is False
    assert 'never' in ' '.join(blocked['reasons']).lower()
    for surface in ('stories', 'ads'):
        assert check_format({'format_kind': 'single_image', 'target_surface': surface})['passed'] is True


def test_voice_profile_accepts_brand_kit_fields():
    from launchcrew.voice_profile import validate_profile
    snapshot = validate_profile(voice_content(colors=('#123456', 'ink')))
    assert snapshot['brand_colors'] == ['#123456', 'ink']
    assert snapshot['fonts'] == ['Grotesk']
    assert snapshot['logo_reference'] == 'assets/logo.png'
    assert 'hype' in snapshot['banned_terms']


# API: standalone format check route enforces the same rules.
def test_formats_check_route(client, test_engine):
    blocked = client.post('/api/formats/check', json={'format_kind': 'feed_carousel', 'frame_count': 1, 'aspect_ratio': '4:5'})
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()['passed'] is False
    assert 'carousel' in ' '.join(blocked.json()['reasons']).lower()
    passing = client.post('/api/formats/check', json={'format_kind': 'feed_carousel', 'frame_count': 6, 'aspect_ratio': '4:5'})
    assert passing.status_code == 200, passing.text
    assert passing.json()['passed'] is True


def test_formats_and_capabilities_routes(client, test_engine):
    formats = client.get('/api/formats')
    assert formats.status_code == 200, formats.text
    by_format = {entry['format']: entry for entry in formats.json()}
    assert {'feed_carousel', 'reel_script', 'story_sequence', 'single_image'} <= set(by_format)
    for entry in by_format.values():
        assert entry['rule']
    capabilities = client.get('/api/channel-capabilities')
    assert capabilities.status_code == 200, capabilities.text
    rows = {entry['channel']: entry for entry in capabilities.json()}
    assert set(rows) == set(CAPABILITY_CHANNELS)
    assert rows['x']['caption_limit'] == channel_variants.X_MAX_CHARS


# API acceptance 1 and 2: run format_spec recorded on the receipt.
def test_run_format_spec_recorded_on_receipt(client, test_engine):
    failing = new_run(client, format_spec={'format_kind': 'feed_carousel', 'frame_count': 1, 'aspect_ratio': '4:5'})
    assert failing['format_check']['passed'] is False
    assert 'carousel' in ' '.join(failing['format_check']['reasons']).lower()
    passing = new_run(client, format_spec={'format_kind': 'feed_carousel', 'frame_count': 6, 'aspect_ratio': '4:5'})
    assert passing['format_check']['passed'] is True


# API: failed format check blocks approval naming the rule; passing approves.
def test_failed_format_check_blocks_approval(client, test_engine):
    failing = new_run(client, format_spec={'format_kind': 'feed_carousel', 'frame_count': 1, 'aspect_ratio': '4:5'})
    refused = approve(client, failing['run_id'])
    assert refused.status_code == 422, refused.text
    assert 'carousel' in refused.json()['detail'].lower()
    passing = new_run(client, format_spec={'format_kind': 'feed_carousel', 'frame_count': 6, 'aspect_ratio': '4:5'})
    approved = approve(client, passing['run_id'])
    assert approved.status_code == 200, approved.text
    assert approved.json()['approval_state'] == 'approved_for_export'


# API: campaign run receipts carry the format check.
def test_campaign_format_spec_recorded(client, test_engine):
    response = client.post('/api/campaigns', json={
        'idea': IDEA, 'agent_name': 'Maker',
        'format_spec': {'format_kind': 'story_sequence', 'frame_ideas': ['one', 'two', 'three']}})
    assert response.status_code == 201, response.text
    campaign = response.json()
    assert len(campaign['days']) == 7
    first = client.get('/api/runs/%s' % campaign['days'][0]['run_id'])
    assert first.status_code == 200, first.text
    assert first.json()['format_check']['passed'] is True


# API acceptance 6: changing a brand color changes the brand kit version on the receipt.
def test_brand_kit_version_changes_on_receipt(client, test_engine):
    item = create_voice(client, voice_content(colors=('navy',)))
    first = new_run(client, memory_ids=[item['id']])
    assert first['brand_kit']['version'].startswith('brand-kit/v1:')
    edited = client.put('/api/memory/%s' % item['id'], json={'title': 'House voice', 'content': voice_content(colors=('copper',))})
    assert edited.status_code == 200, edited.text
    second = new_run(client, memory_ids=[item['id']])
    assert second['brand_kit']['version'] != first['brand_kit']['version']
    assert second['brand_kit']['brand_colors'] == ['copper']


# API acceptance 5: checked bundle exposes and obeys the capabilities table.
def test_checked_bundle_exposes_capabilities(client, test_engine):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approved = approve(client, run_id)
    assert approved.status_code == 200, approved.text
    response = client.get('/api/runs/%s/channel-variants' % run_id)
    assert response.status_code == 200, response.text
    bundle = response.json()
    assert 'capabilities' in bundle
    rows = {entry['channel']: entry for entry in bundle['capabilities']}
    assert set(rows) == set(CAPABILITY_CHANNELS)
    for channel in ('x', 'linkedin', 'instagram', 'email', 'facebook', 'tiktok', 'shopify'):
        variant = bundle[channel]
        assert variant['capability']['channel'] == channel
        assert variant['capability']['caption_limit'] == rows[channel]['caption_limit']
        if variant['content_valid'] and variant['text']:
            assert len(variant['text']) <= variant['capability']['caption_limit']


# Brand banned rules veto drafts through the voice path.
def test_brand_banned_rules_block_through_voice(client, test_engine):
    content = voice_content(colors=('navy',))
    content['banned_rules'] = ['moonshine']
    item = create_voice(client, content)
    receipt = new_run(client, memory_ids=[item['id']])
    assert 'moonshine' in receipt['voice_profile']['banned_terms']
    assert 'moonshine' in receipt['brand_kit']['banned_rules']
    from launchcrew.voice_profile import voice_single_block_for_text
    ref = {'title': 'House voice', 'version': receipt['voice_profile']['version']}
    block = voice_single_block_for_text(
        {'banned_terms': receipt['voice_profile']['banned_terms']},
        'A moonshine story for commuters', ref)
    assert block is not None
    assert 'moonshine' in block['reason']
