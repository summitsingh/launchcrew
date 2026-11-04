"""SC4 media library on Postgres: upload once, derivatives, Checker validation.

Deterministic fixtures only, no live model calls, no real platform
calls. Covers the upload-once contract (format facts plus
non-destructive 4:5 derivative generation), per-channel derivative
resolution without re-upload, and the Checker format block that names
a wrong-aspect original on a feed slot through validate-ready and
mark-ready.
"""
from unittest.mock import patch

import pytest

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


def new_slot(client, run_id=None, slot_type='feed_post'):
    body = {'slot_date': '2026-11-03', 'slot_type': slot_type,
            'pillar': 'product', 'format': slot_type}
    if run_id is not None:
        body['run_id'] = run_id
    response = client.post('/api/calendar/slots', json=body)
    assert response.status_code == 201, response.text
    return response.json()


def upload_image(client, filename='hero.png', width=1080, height=1350):
    response = client.post('/api/media/assets',
                           json={'filename': filename, 'width': width, 'height': height})
    assert response.status_code == 201, response.text
    return response.json()


def valid_channel(client, run_id):
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    return next(c for c in CHANNELS
                if bundle[c]['content_valid'] and bundle[c]['text'])


def ready_slot(client, run_id, channel):
    slot = new_slot(client, run_id)
    patched = client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                           json={'selected_channels': [channel]})
    assert patched.status_code == 200, patched.text
    revision = client.get(f'/api/runs/{run_id}').json().get('revision', 0)
    approved = client.post(f'/api/calendar/slots/{slot["id"]}/approve-channels',
                           json={'channels': [channel], 'expected_revision': revision})
    assert approved.status_code == 200, approved.text
    marked = client.post(f'/api/calendar/slots/{slot["id"]}/mark-ready')
    assert marked.status_code == 200, marked.text
    return marked.json()


def test_upload_records_format_facts_and_nondestructive_derivatives(client):
    asset = upload_image(client)
    assert asset['width'] == 1080
    assert asset['height'] == 1350
    assert asset['aspect_ratio'] == '4:5'
    assert asset['format_facts']['width'] == 1080
    assert asset['format_facts']['aspect_ratio'] == '4:5'
    assert asset['sha256_digest']
    derivatives = asset['derivatives']
    assert set(derivatives) == {'4:5', '1:1', '9:16', '16:9'}
    feed = derivatives['4:5']
    assert feed['aspect_ratio'] == '4:5'
    assert feed['derived_from_id'] == asset['id']
    assert feed['original_preserved'] is True
    assert feed['sha256_digest'] != asset['sha256_digest']
    assert set(feed['crop_box']) == {'x', 'y', 'width', 'height'}

    reread = client.get(f'/api/media/assets/{asset["id"]}')
    assert reread.status_code == 200, reread.text
    body = reread.json()
    assert body['width'] == 1080
    assert body['height'] == 1350
    assert body['aspect_ratio'] == '4:5'
    assert body['sha256_digest'] == asset['sha256_digest']
    assert body['derivatives']['4:5']['sha256_digest'] == feed['sha256_digest']

    listed = client.get('/api/media/assets')
    assert listed.status_code == 200, listed.text
    assert sorted(entry['id'] for entry in listed.json()) == sorted(['media_wallet_starter', asset['id']])

    crop = client.post(f'/api/media/assets/{asset["id"]}/derivatives',
                       json={'derivative_key': '4:5'})
    assert crop.status_code == 200, crop.text
    assert crop.json()['aspect_ratio'] == '4:5'
    assert client.post(f'/api/media/assets/{asset["id"]}/derivatives',
                       json={'derivative_key': '3:4'}).status_code == 422

    intact = client.get(f'/api/media/assets/{asset["id"]}').json()
    assert intact['width'] == 1080
    assert intact['aspect_ratio'] == '4:5'
    assert intact['sha256_digest'] == asset['sha256_digest']


def test_upload_digest_is_the_file_sha256(client):
    import base64
    import hashlib
    raw = b'fake-image-bytes-for-digest-proof'
    response = client.post('/api/media/assets',
                           json={'filename': 'proof.png', 'width': 640, 'height': 480,
                                 'data_b64': base64.b64encode(raw).decode('ascii')})
    assert response.status_code == 201, response.text
    assert response.json()['sha256_digest'] == hashlib.sha256(raw).hexdigest()


def test_attach_two_channels_resolves_each_derivative_without_reupload(client):
    asset = upload_image(client, width=1080, height=1350)
    slot = new_slot(client)
    attached = client.post(f'/api/calendar/slots/{slot["id"]}/media',
                           json={'asset_id': asset['id'], 'channels': ['instagram', 'x']})
    assert attached.status_code == 201, attached.text
    body = attached.json()
    assert body['channels'] == ['instagram', 'x']
    mapping = body['channel_derivatives']
    assert mapping['instagram']['aspect_ratio'] == '4:5'
    assert mapping['instagram']['derived_from_id'] == asset['id']
    assert mapping['instagram']['original_preserved'] is True
    assert mapping['x']['aspect_ratio'] == '16:9'
    assert mapping['x']['derived_from_id'] == asset['id']
    assert body['format_validation']['passed'] is True
    assert body['use_original_without_derivative'] is False

    listed = client.get('/api/media/assets').json()
    assert sorted(entry['id'] for entry in listed) == sorted(['media_wallet_starter', asset['id']])

    state = client.get(f'/api/calendar/slots/{slot["id"]}/media')
    assert state.status_code == 200, state.text
    payload = state.json()
    assert payload['slot_id'] == slot['id']
    assert len(payload['attached']) == 1
    assert payload['attached'][0]['channel_derivatives']['instagram']['aspect_ratio'] == '4:5'
    assert payload['attached'][0]['channel_derivatives']['x']['aspect_ratio'] == '16:9'
    assert payload['format_validation']['passed'] is True
    assert payload['format_validation']['required_aspect_ratio'] == '4:5'


def test_wrong_aspect_original_blocks_ready_and_names_ratio(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve(client, run_id)
    channel = valid_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    wide = upload_image(client, filename='wide.png', width=1920, height=1080)
    assert wide['aspect_ratio'] == '16:9'

    attached = client.post(f'/api/calendar/slots/{slot["id"]}/media',
                           json={'asset_id': wide['id'], 'channels': ['instagram'],
                                 'use_original_without_derivative': True})
    assert attached.status_code == 201, attached.text
    validation = attached.json()['format_validation']
    assert validation['passed'] is False
    assert validation['checked_aspect_ratio'] == '16:9'
    assert validation['required_aspect_ratio'] == '4:5'
    assert any('16:9' in reason and '4:5' in reason for reason in validation['reasons'])

    checked = client.get(f'/api/calendar/slots/{slot["id"]}/validate-ready')
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body['ready_eligible'] is False
    assert 'format_check_failed' in body['failing_conditions']
    assert body['format_reason'] is not None
    assert '16:9' in body['format_reason'] and '4:5' in body['format_reason']

    refused = client.post(f'/api/calendar/slots/{slot["id"]}/mark-ready')
    assert refused.status_code == 409, refused.text
    detail = refused.json()['detail']
    assert 'format_check_failed' in detail['failing_conditions']


def test_derivative_resolves_wrong_aspect_original_on_feed_slot(client):
    slot = new_slot(client)
    wide = upload_image(client, filename='wide.png', width=1920, height=1080)
    attached = client.post(f'/api/calendar/slots/{slot["id"]}/media',
                           json={'asset_id': wide['id'], 'channels': ['instagram']})
    assert attached.status_code == 201, attached.text
    body = attached.json()
    assert body['channel_derivatives']['instagram']['aspect_ratio'] == '4:5'
    assert body['format_validation']['passed'] is True
