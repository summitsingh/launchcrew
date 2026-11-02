"""Run-bound media creative API on real Postgres.

Uses only the existing ``test_engine`` and ``client`` fixtures; every
helper below is defined in this file. HTTP is mocked at the transport
seam only. Keyless and zero-budget tests assert zero provider HTTP.
"""
import io
import json
from unittest.mock import patch

from sqlalchemy import text

from backend import model_admission as ma
from backend import store
from launchcrew import media_creative as creative_mod
from launchcrew import run

FIXED = ma.RESERVATION_USD_MICROS
SEP = creative_mod.SEPARATOR


def _offline_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    return patch('launchcrew.run.run_pipeline', side_effect=offline)


def _keyless(monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_WONDER_MODEL', raising=False)


def _reset_ledger(test_engine):
    with test_engine.begin() as connection:
        connection.execute(text('TRUNCATE model_calls'))
        connection.execute(
            text("UPDATE model_budget SET remaining_micros=0 WHERE id='global'"))


def _grant(test_engine, micros):
    with test_engine.begin() as connection:
        connection.execute(
            text("UPDATE model_budget SET remaining_micros=:n WHERE id='global'"),
            {'n': micros})


def _make_run(client):
    response = client.post('/api/runs', json={'idea': 'media creative probe',
                                              'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    body = response.json()
    return body['run_id'], body['revision']


def _completion(raw, usage):
    return io.BytesIO(json.dumps(
        {'choices': [{'message': {'content': json.dumps(raw)},
                      'finish_reason': 'stop'}],
         'usage': dict(usage)}).encode())


def _creative_transport(request, timeout=None):
    body = json.loads(request.data)
    required = set(body['response_format']['json_schema']['schema']['required'])
    usage = {'prompt_tokens': 12, 'completion_tokens': 30, 'total_tokens': 42}
    if required == {'frames'}:
        frames = ['Caption %d%sOwner shot %d' % (i, SEP, i) for i in range(5)]
        return _completion({'frames': frames}, usage)
    if required == {'scenes'}:
        scenes = ['Hook %d%sShot %d%sLine %d' % (i, SEP, i, SEP, i)
                  for i in range(3)]
        return _completion({'scenes': scenes}, usage)
    return _completion({'frames': []}, usage)


def test_bad_format_and_facts_refuse_422(client, monkeypatch):
    _keyless(monkeypatch)
    with _offline_pipeline():
        run_id, _ = _make_run(client)
    bad = client.post('/api/runs/%s/media-creative' % run_id,
                      json={'output_format': 'video', 'confirmed_facts': 'Cotton tee.',
                            'expected_revision': 0})
    assert bad.status_code == 422, bad.text
    empty = client.post('/api/runs/%s/media-creative' % run_id,
                        json={'output_format': 'carousel', 'confirmed_facts': '  ',
                              'expected_revision': 0})
    assert empty.status_code == 422, empty.text


def test_missing_run_404(client, monkeypatch):
    _keyless(monkeypatch)
    missing = client.post('/api/runs/run_missing/media-creative',
                          json={'output_format': 'carousel',
                                'confirmed_facts': 'Cotton tee.',
                                'expected_revision': 0})
    assert missing.status_code == 404, missing.text


def test_stale_revision_409(client, monkeypatch):
    _keyless(monkeypatch)
    with _offline_pipeline():
        run_id, _ = _make_run(client)
    stale = client.post('/api/runs/%s/media-creative' % run_id,
                        json={'output_format': 'carousel',
                              'confirmed_facts': 'Cotton tee.',
                              'expected_revision': 7})
    assert stale.status_code == 409, stale.text


def test_no_key_refuses_503_with_zero_http(client, test_engine, monkeypatch):
    _keyless(monkeypatch)
    _reset_ledger(test_engine)
    with _offline_pipeline():
        run_id, revision = _make_run(client)
    with patch('launchcrew.spark.urlopen',
               side_effect=AssertionError('zero HTTP expected')):
        response = client.post('/api/runs/%s/media-creative' % run_id,
                               json={'output_format': 'carousel',
                                     'confirmed_facts': 'Cotton tee, $49.',
                                     'expected_revision': revision})
    assert response.status_code == 503, response.text
    assert 'not configured' in response.text


def test_zero_budget_refuses_402_with_zero_http(client, test_engine, monkeypatch):
    _keyless(monkeypatch)
    _reset_ledger(test_engine)
    with _offline_pipeline():
        run_id, revision = _make_run(client)
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_WONDER_MODEL', raising=False)
    with patch('launchcrew.spark.urlopen',
               side_effect=AssertionError('zero HTTP expected')):
        response = client.post('/api/runs/%s/media-creative' % run_id,
                               json={'output_format': 'carousel',
                                     'confirmed_facts': 'Cotton tee, $49.',
                                     'expected_revision': revision})
    assert response.status_code == 402, response.text
    assert 'budget' in response.text


def test_live_mocked_carousel_201(client, test_engine, monkeypatch):
    _keyless(monkeypatch)
    _reset_ledger(test_engine)
    with _offline_pipeline():
        run_id, revision = _make_run(client)
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED * 2)
    with patch('launchcrew.spark.urlopen',
               side_effect=_creative_transport) as transport:
        response = client.post('/api/runs/%s/media-creative' % run_id,
                               json={'output_format': 'carousel',
                                     'confirmed_facts': 'Cotton tee, $49.',
                                     'expected_revision': revision})
    assert response.status_code == 201, response.text
    assert transport.call_count == 1
    body = response.json()
    assert body['output_format'] == 'carousel'
    assert body['media_provenance'] == 'model_draft_unverified'
    assert body['model_used'] == 'muse-spark-1.3'
    assert body['revision'] == revision + 1
    assert body['remaining_budget_micros'] == FIXED
    pack = body['pack']
    assert pack['provenance'] == 'model_draft_unverified'
    assert len(pack['frames']) == 5
    assert pack['frames'][0]['caption'] == 'Caption 0'
    assert pack['frames'][0]['shot'] == 'Owner shot 0'
    assert pack['captions'][2] == 'Caption 2'
    reread = client.get('/api/runs/%s' % run_id).json()
    assert reread['revision'] == revision + 1
    assert reread['media_creative']['id'] == body['id']
    assert reread['model_usage']['spark_calls'] == 1
    assert reread['model_usage']['prompt_tokens'] == 12
    assert reread['model_usage']['total_tokens'] == 42
    assert reread['revision_history'][-1]['media_creative_event'] == \
        'media_creative_generated'
    assert reread['approval_state'] == 'pending_approval'
    assert reread['approvals'] == []


def test_live_mocked_short_video_201(client, test_engine, monkeypatch):
    _keyless(monkeypatch)
    _reset_ledger(test_engine)
    with _offline_pipeline():
        run_id, revision = _make_run(client)
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED)
    with patch('launchcrew.spark.urlopen', side_effect=_creative_transport):
        response = client.post('/api/runs/%s/media-creative' % run_id,
                               json={'output_format': 'short_video',
                                     'confirmed_facts': 'Cotton tee, $49.',
                                     'expected_revision': revision})
    assert response.status_code == 201, response.text
    pack = response.json()['pack']
    assert len(pack['scenes']) == 3
    assert pack['scenes'][1]['hook'] == 'Hook 1'
    assert pack['scenes'][1]['voiceover'] == 'Line 1'
    assert pack['voiceover_script'] == 'Line 0\nLine 1\nLine 2'


def test_unparsable_model_pack_refuses_422_and_stores_nothing(
        client, test_engine, monkeypatch):
    _keyless(monkeypatch)
    _reset_ledger(test_engine)
    with _offline_pipeline():
        run_id, revision = _make_run(client)
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED)

    def bad_pack(request, timeout=None):
        return _completion({'frames': ['no separator here']},
                           {'prompt_tokens': 1, 'completion_tokens': 1,
                            'total_tokens': 2})

    with patch('launchcrew.spark.urlopen', side_effect=bad_pack):
        response = client.post('/api/runs/%s/media-creative' % run_id,
                               json={'output_format': 'carousel',
                                     'confirmed_facts': 'Cotton tee, $49.',
                                     'expected_revision': revision})
    assert response.status_code == 422, response.text
    reread = client.get('/api/runs/%s' % run_id).json()
    assert 'media_creative' not in reread
    assert reread['revision'] == revision
