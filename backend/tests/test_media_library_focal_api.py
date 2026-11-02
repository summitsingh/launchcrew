"""Media focal point API on Postgres: refocus, clamping, original intact.

Deterministic fixtures only, no live model calls, no real platform
calls. Covers owner focal set plus recompute, single-key refocus,
invalid input refusals, and focal-consistent plain generation.
"""
from unittest.mock import patch

import pytest

from launchcrew import media_library as media_mod


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    from launchcrew import run as run_mod
    pipeline = run_mod.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return pipeline(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def upload_image(client, filename='focal.png', width=1600, height=900):
    response = client.post('/api/media/assets',
                           json={'filename': filename, 'width': width, 'height': height})
    assert response.status_code == 201, response.text
    return response.json()


def test_refocus_recomputes_all_crops_and_keeps_original(client):
    asset = upload_image(client)
    asset_id = asset['id']
    before = (asset['width'], asset['height'], asset['aspect_ratio'],
              asset['sha256_digest'])
    centered = dict(asset['derivatives']['4:5']['crop_box'])
    response = client.post(f'/api/media/assets/{asset_id}/focal-point',
                           json={'focal_x': 0.0, 'focal_y': 0.5})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['focal_point'] == {'x': 0.0, 'y': 0.5}
    assert set(body['derivatives']) == set(media_mod.DERIVATIVE_KEYS)
    refocused = body['derivatives']['4:5']
    assert refocused['crop_box']['x'] == 0
    assert refocused['crop_box'] != centered
    assert refocused['focal_point'] == {'x': 0.0, 'y': 0.5}
    assert refocused['sha256_digest'] != asset['derivatives']['4:5']['sha256_digest']
    assert refocused['original_preserved'] is True
    reread = client.get(f'/api/media/assets/{asset_id}').json()
    assert reread['focal_point'] == {'x': 0.0, 'y': 0.5}
    assert (reread['width'], reread['height'], reread['aspect_ratio'],
            reread['sha256_digest']) == before


def test_single_key_refocus_leaves_other_keys(client):
    asset = upload_image(client, filename='single.png')
    asset_id = asset['id']
    original_11 = dict(asset['derivatives']['1:1']['crop_box'])
    response = client.post(f'/api/media/assets/{asset_id}/focal-point',
                           json={'focal_x': 1.0, 'focal_y': 1.0,
                                 'derivative_key': '9:16'})
    assert response.status_code == 200, response.text
    assert set(response.json()['derivatives']) == {'9:16'}
    reread = client.get(f'/api/media/assets/{asset_id}').json()
    assert reread['derivatives']['1:1']['crop_box'] == original_11
    assert reread['derivatives']['9:16']['focal_point'] == {'x': 1.0, 'y': 1.0}


def test_invalid_focal_and_key_and_missing_asset(client):
    asset = upload_image(client, filename='bad.png')
    asset_id = asset['id']
    for bad in ({'focal_x': 1.5, 'focal_y': 0.5},
                {'focal_x': 'left', 'focal_y': 0.5},
                {'focal_x': 0.5}):
        refused = client.post(f'/api/media/assets/{asset_id}/focal-point', json=bad)
        assert refused.status_code == 422, (bad, refused.text)
    wrong_key = client.post(f'/api/media/assets/{asset_id}/focal-point',
                            json={'focal_x': 0.5, 'focal_y': 0.5,
                                  'derivative_key': 'wide'})
    assert wrong_key.status_code == 422, wrong_key.text
    missing = client.post('/api/media/assets/missing/focal-point',
                          json={'focal_x': 0.5, 'focal_y': 0.5})
    assert missing.status_code == 404, missing.text


def test_plain_generate_stays_focal_consistent(client):
    asset = upload_image(client, filename='consistent.png')
    asset_id = asset['id']
    refocused = client.post(f'/api/media/assets/{asset_id}/focal-point',
                            json={'focal_x': 0.0, 'focal_y': 0.0,
                                  'derivative_key': '1:1'})
    assert refocused.status_code == 200, refocused.text
    generated = client.post(f'/api/media/assets/{asset_id}/derivatives',
                            json={'derivative_key': '4:5'})
    assert generated.status_code == 200, generated.text
    record = generated.json()
    assert record['focal_point'] == {'x': 0.0, 'y': 0.0}
    assert record['crop_box']['x'] == 0
