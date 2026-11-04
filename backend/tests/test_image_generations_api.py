"""Image generation API: gated providers, assets stored.

Deterministic fixtures only. Provider HTTP is patched at the adapter
seam; fixture keys are synthetic. Zero live network on any path.
"""
import io
import json
from unittest.mock import patch

from launchcrew import image_adapters as adapters_mod

TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)


def _image_response(provider):
    if provider == 'gemini':
        return io.BytesIO(json.dumps(
            {"predictions": [{"bytesBase64Encoded": TINY_PNG_B64}]}).encode())
    return io.BytesIO(json.dumps(
        {"data": [{"b64_json": TINY_PNG_B64}]}).encode())


def _key_name(provider):
    return adapters_mod.KEY_NAMES[provider]


def make_character(client, name='Maya'):
    response = client.post('/api/image-characters',
                           json={'name': name,
                                 'appearance': 'Athletic woman with short hair'})
    assert response.status_code == 201, response.text
    return response.json()


def generate(client, provider, **extra):
    body = {'provider': provider, 'scene': 'Rooftop at golden hour',
            'product_context': 'Cotton tee, $49'}
    body.update(extra)
    return client.post('/api/image-generations', json=body)


def test_no_key_refuses_503_with_zero_http(client, monkeypatch):
    for provider in ('openai', 'xai', 'gemini'):
        monkeypatch.delenv(_key_name(provider), raising=False)
    character = make_character(client)
    with patch.object(adapters_mod, 'urlopen',
                      side_effect=AssertionError('zero HTTP expected')):
        response = generate(client, 'openai', character_id=character['id'])
    assert response.status_code == 503, response.text
    assert 'OPENAI_API_KEY' in response.text
    assert client.get('/api/image-generations').json() == []
    assert [entry['id'] for entry in client.get('/api/media/assets').json()] == ['media_wallet_starter']


def test_unknown_provider_and_bad_input_refuse_422(client):
    bad = generate(client, 'midjourney')
    assert bad.status_code == 422, bad.text
    bad_aspect = generate(client, 'openai', aspect='wide')
    assert bad_aspect.status_code == 422, bad_aspect.text
    missing = generate(client, 'openai', character_id='chr_missing')
    assert missing.status_code == 404, missing.text


def test_generate_all_providers_stores_assets(client, monkeypatch):
    character = make_character(client)
    for provider in ('openai', 'xai', 'gemini'):
        monkeypatch.setenv(_key_name(provider), 'fixture-key')
        with patch.object(adapters_mod, 'urlopen',
                          side_effect=lambda req, timeout=None, p=provider: _image_response(p)):
            response = generate(client, provider, character_id=character['id'])
        assert response.status_code == 201, (provider, response.text)
        body = response.json()
        assert body['provider'] == provider
        assert body['model'] == adapters_mod.PROVIDER_MODELS[provider]
        assert body['character_snapshot'] == 'Maya'
        assert 'Athletic woman' in body['prompt']
        assert len(body['asset_ids']) == 1
        asset = client.get(f'/api/media/assets/{body["asset_ids"][0]}').json()
        assert asset['mime_type'] == 'image/png'
        assert asset['sha256_digest']
        assert set(('4:5', '1:1', '9:16', '16:9')) <= set(asset['derivatives'])
    jobs = client.get('/api/image-generations').json()
    assert [job['provider'] for job in jobs] == ['openai', 'xai', 'gemini']


def test_product_only_shot_without_character(client, monkeypatch):
    import json as _json
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-key')

    def two_images(request, timeout=None):
        count = _json.loads(request.data.decode()).get('n', 1)
        return io.BytesIO(_json.dumps(
            {'data': [{'b64_json': TINY_PNG_B64} for _ in range(count)]}).encode())

    with patch.object(adapters_mod, 'urlopen', side_effect=two_images):
        response = generate(client, 'openai', count=2)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['character_id'] is None
    assert 'no model' in body['prompt']
    assert len(body['asset_ids']) == 2


def test_provider_refusal_stores_nothing(client, monkeypatch):
    monkeypatch.setenv('XAI_API_KEY', 'fixture-key')

    def refused(request, timeout=None):
        return io.BytesIO(json.dumps(
            {'error': {'message': 'Incorrect API key', 'code': 'invalid'}}).encode())

    with patch.object(adapters_mod, 'urlopen', side_effect=refused):
        response = generate(client, 'xai')
    assert response.status_code == 422, response.text
    assert 'Incorrect API key' in response.text
    assert 'fixture-key' not in response.text
    assert client.get('/api/image-generations').json() == []
    assert [entry['id'] for entry in client.get('/api/media/assets').json()] == ['media_wallet_starter']


def test_character_snapshot_survives_character_delete(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-key')
    character = make_character(client)
    with patch.object(adapters_mod, 'urlopen',
                      side_effect=lambda req, timeout=None: _image_response('openai')):
        response = generate(client, 'openai', character_id=character['id'])
    assert response.status_code == 201, response.text
    deleted = client.delete(f'/api/image-characters/{character["id"]}')
    assert deleted.status_code == 204
    jobs = client.get('/api/image-generations').json()
    assert jobs[0]['character_snapshot'] == 'Maya'
