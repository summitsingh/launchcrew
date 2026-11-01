"""SC5 viral format generator on Postgres: metered credits failing
closed at zero, owner media only, and Checked approval-bound packs.

Deterministic fixtures only, no live model calls, no real platform
calls. Three owner screenshots plus confirmed facts produce a Checked
carousel pack bound to approval integrity with one visible credit
spent; one owner screen recording produces a Checked short video pack;
a zero credit balance refuses generation before any pipeline call; and
non-owner media or wrong screenshot counts refuse with 422.
"""
from unittest.mock import patch

import pytest

FACTS = ('Our Trail Wallet costs $49. It holds 12 cards in full grain leather. '
         'It ships free across the United States in 3 days.')

CAROUSEL_FACTS = ('Our Trail Wallet costs $49. It holds 12 cards in full grain leather. '
                  'Free shipping across the United States in 3 days. '
                  'Every stitch is checked by hand before it ships.')


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    from launchcrew import run as run_mod
    pipeline = run_mod.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return pipeline(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def upload_image(client, filename='shot.png', width=1080, height=1350):
    response = client.post('/api/media/assets',
                           json={'filename': filename, 'width': width, 'height': height})
    assert response.status_code == 201, response.text
    return response.json()


def upload_video(client, filename='recording.mp4'):
    response = client.post('/api/media/assets',
                           json={'filename': filename, 'mime_type': 'video/mp4',
                                 'width': 720, 'height': 1280, 'duration_seconds': 24})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['media_type'] == 'video'
    return body


def credits(client):
    response = client.get('/api/viral-generator/credits')
    assert response.status_code == 200, response.text
    return response.json()


def generate(client, payload):
    return client.post('/api/viral-generator/generate', json=payload)


def three_screenshots(client):
    return [upload_image(client, 'shot-%d.png' % index)['id'] for index in range(3)]


def test_three_owner_screenshots_produce_checked_carousel_pack(client):
    before = credits(client)
    assert before['remaining_credits'] == 10
    assert before['total_used_credits'] == 0
    asset_ids = three_screenshots(client)
    response = generate(client, {'media_mode': 'screenshots', 'asset_ids': asset_ids,
                                 'confirmed_facts': CAROUSEL_FACTS})
    assert response.status_code == 201, response.text
    generation = response.json()
    assert generation['id'].startswith('vgen_')
    assert generation['output_format'] == 'carousel'
    assert generation['media_mode'] == 'screenshots'
    assert generation['media_provenance'] == 'owner_upload_only'
    assert generation['checker_passed'] is True
    assert generation['checker_decision'] == 'pass'
    assert generation['run_status'] == 'completed'
    assert generation['approval_state'] == 'pending_approval'
    assert generation['run_id']
    frames = generation['frames_or_scenes']
    assert 5 <= len(frames) <= 10
    for frame in frames:
        assert frame['aspect_ratio'] == '4:5'
        assert frame['media_provenance'] == 'owner_upload_only'
    joined = ' '.join(frame['text'] for frame in frames)
    assert 'Trail Wallet' in joined
    assert '$49' in joined
    assert 'ships' in joined
    assert generation['credits_charged'] == 1
    assert generation['remaining_credits_after'] == before['remaining_credits'] - 1
    receipt = client.get('/api/runs/%s' % generation['run_id'])
    assert receipt.status_code == 200, receipt.text
    pack = receipt.json()
    assert pack['status'] == 'completed'
    assert pack['checker_v2']['blocked_count'] == 0
    assert pack['approval_state'] == 'pending_approval'
    assert pack['format_check']['passed'] is True
    assert pack['format_check']['format'] == 'feed_carousel'
    after = credits(client)
    assert after['remaining_credits'] == before['remaining_credits'] - 1
    assert after['total_used_credits'] == before['total_used_credits'] + 1
    listed = client.get('/api/viral-generator/generations')
    assert listed.status_code == 200, listed.text
    assert [entry['id'] for entry in listed.json()] == [generation['id']]


def test_single_owner_recording_produces_checked_short_video_pack(client):
    asset = upload_video(client)
    response = generate(client, {'media_mode': 'screen_recording',
                                 'asset_ids': [asset['id']],
                                 'confirmed_facts': FACTS})
    assert response.status_code == 201, response.text
    generation = response.json()
    assert generation['output_format'] == 'short_video'
    assert generation['media_mode'] == 'screen_recording'
    assert generation['media_provenance'] == 'owner_upload_only'
    assert generation['checker_passed'] is True
    assert generation['run_status'] == 'completed'
    assert generation['approval_state'] == 'pending_approval'
    scenes = generation['frames_or_scenes']
    assert len(scenes) == 3
    for scene in scenes:
        assert scene['aspect_ratio'] == '9:16'
        assert scene['media_provenance'] == 'owner_upload_only'
    receipt = client.get('/api/runs/%s' % generation['run_id']).json()
    assert receipt['status'] == 'completed'
    assert receipt['checker_v2']['blocked_count'] == 0
    assert receipt['format_check']['passed'] is True
    assert receipt['format_check']['format'] == 'reel_script'
    assert credits(client)['remaining_credits'] == 9


def test_inline_owner_screenshots_count_without_asset_ids(client):
    response = generate(client, {'media_mode': 'screenshots',
                                 'screenshots': [{'filename': 'owner-1.png'},
                                                 {'filename': 'owner-2.png'},
                                                 {'filename': 'owner-3.png'}],
                                 'confirmed_facts': CAROUSEL_FACTS})
    assert response.status_code == 201, response.text
    assert response.json()['checker_passed'] is True
    assert credits(client)['remaining_credits'] == 9


def test_zero_credits_refuse_before_any_pipeline_call(client):
    asset_ids = three_screenshots(client)
    set_balance = client.post('/api/viral-generator/credits', json={'remaining_credits': 0})
    assert set_balance.status_code == 200, set_balance.text
    assert set_balance.json()['remaining_credits'] == 0
    with patch('launchcrew.run.run_pipeline',
               side_effect=AssertionError('pipeline must not run when credits are exhausted')):
        refused = generate(client, {'media_mode': 'screenshots', 'asset_ids': asset_ids,
                                    'confirmed_facts': CAROUSEL_FACTS})
    assert refused.status_code == 402, refused.text
    assert 'viral_credits_exhausted' in refused.text
    assert '0 credits remaining' in refused.text
    assert 'before any provider call' in refused.text
    assert client.get('/api/viral-generator/generations').json() == []
    assert credits(client) == {'workspace_id': 'demo', 'remaining_credits': 0,
                               'total_used_credits': 0}
    replenished = client.put('/api/viral-generator/credits', json={'remaining_credits': 2})
    assert replenished.status_code == 200, replenished.text
    assert replenished.json()['remaining_credits'] == 2
    retry = generate(client, {'media_mode': 'screenshots', 'asset_ids': asset_ids,
                              'confirmed_facts': CAROUSEL_FACTS})
    assert retry.status_code == 201, retry.text
    assert retry.json()['remaining_credits_after'] == 1


def test_non_owner_media_source_refused(client):
    asset_ids = three_screenshots(client)
    refused = generate(client, {'media_mode': 'screenshots', 'asset_ids': asset_ids,
                                'media_source': 'creator_library',
                                'confirmed_facts': CAROUSEL_FACTS})
    assert refused.status_code == 422, refused.text
    assert 'owner_media_only' in refused.text
    foreign = generate(client, {'media_mode': 'screenshots',
                                'screenshots': [{'source': 'creator_library',
                                                 'clip_id': 'creator_clip_1'}],
                                'confirmed_facts': CAROUSEL_FACTS})
    assert foreign.status_code == 422, foreign.text
    assert 'owner_media_only' in foreign.text
    assert credits(client)['remaining_credits'] == 10


def test_wrong_screenshot_and_recording_counts_refused(client):
    asset_ids = three_screenshots(client)
    too_few = generate(client, {'media_mode': 'screenshots',
                                'asset_ids': asset_ids[:2],
                                'confirmed_facts': CAROUSEL_FACTS})
    assert too_few.status_code == 422, too_few.text
    assert 'screenshots_count_must_be_3_to_10' in too_few.text
    too_many = generate(client, {'media_mode': 'screenshots',
                                 'screenshots': [{'filename': 'owner-%d.png' % index}
                                                 for index in range(11)],
                                 'confirmed_facts': CAROUSEL_FACTS})
    assert too_many.status_code == 422, too_many.text
    assert 'screenshots_count_must_be_3_to_10' in too_many.text
    two_recordings = generate(client, {'media_mode': 'screen_recording',
                                       'screenshots': [{'filename': 'a.png'}],
                                       'screen_recording': {'filename': 'b.mp4'},
                                       'confirmed_facts': FACTS})
    assert two_recordings.status_code == 422, two_recordings.text
    assert 'screen_recording_requires_single_video' in two_recordings.text
    empty_facts = generate(client, {'media_mode': 'screenshots', 'asset_ids': asset_ids,
                                    'confirmed_facts': '   '})
    assert empty_facts.status_code == 422, empty_facts.text
    assert credits(client)['remaining_credits'] == 10
