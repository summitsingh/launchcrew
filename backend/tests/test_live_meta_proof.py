"""Focused offline boundaries for live proof. No provider access.

All transports here are synthetic test doubles labelled tests. Real proof
never intercepts returned responses; it delegates to the actual opener.
"""
import io
import json
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

import pytest

from backend import sam as sam_module
from backend.live_meta_proof import _validate_spark_receipt
from launchcrew import spark as spark_module


def test_synthetic_proof_constants_fixed():
    assert spark_module.PROOF_MODEL == 'muse-spark-1.3'
    assert spark_module.PROOF_ORIGIN == 'https://api.meta.ai/v1'
    assert spark_module.PROOF_CHAT_PATH == '/chat/completions'
    assert spark_module.PROOF_MAX_COMPLETION_TOKENS == 2048
    assert spark_module.PROOF_N == 1
    assert spark_module.PROOF_MAX_BODY_BYTES == 32 * 1024
    assert spark_module.PROOF_MAX_ATTEMPTS == 3


def _proof_request(body):
    raw = json.dumps(body).encode()
    return Request(spark_module.PROOF_ORIGIN + spark_module.PROOF_CHAT_PATH,
                   data=raw, headers={'Content-Type': 'application/json'})


def _valid_body():
    return {'model': 'muse-spark-1.3', 'max_completion_tokens': 2048, 'n': 1,
            'messages': [{'role': 'user', 'content': 'hi'}],
            'response_format': {'type': 'json_schema',
                                'json_schema': {'name': 't', 'strict': True,
                                                'schema': {'type': 'object'}}}}


def test_synthetic_proof_request_validates_bounds():
    assert spark_module.validate_proof_request(_proof_request(_valid_body()))['model'] == 'muse-spark-1.3'
    bad = _valid_body()
    bad['max_completion_tokens'] = 4096
    with pytest.raises(ValueError):
        spark_module.validate_proof_request(_proof_request(bad))
    bad = _valid_body()
    bad['n'] = 2
    with pytest.raises(ValueError):
        spark_module.validate_proof_request(_proof_request(bad))
    bad = _valid_body()
    bad['model'] = 'other-model'
    with pytest.raises(ValueError):
        spark_module.validate_proof_request(_proof_request(bad))
    bad = _valid_body()
    bad['tools'] = []
    with pytest.raises(ValueError):
        spark_module.validate_proof_request(_proof_request(bad))
    oversize = _valid_body()
    oversize['messages'] = [{'role': 'user', 'content': 'x' * (33 * 1024)}]
    with pytest.raises(ValueError):
        spark_module.validate_proof_request(_proof_request(oversize))
    wrong_url = Request('https://other.example/v1/chat/completions',
                        data=json.dumps(_valid_body()).encode())
    with pytest.raises(ValueError):
        spark_module.validate_proof_request(wrong_url)


def test_synthetic_spark_call_carries_output_token_and_n(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    captured = {}

    def test_synthetic_capture(request, timeout):
        captured['body'] = json.loads(request.data)
        assert len(request.data) <= 32 * 1024
        return io.BytesIO(json.dumps(
            {'choices': [{'message': {'content': json.dumps({'claims': []})}}],
             'usage': {'total_tokens': 1}}).encode())

    with patch('launchcrew.spark.urlopen', side_effect=test_synthetic_capture):
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []})
    assert result['mode'] == 'spark'
    assert captured['body']['max_completion_tokens'] == 2048
    assert captured['body']['n'] == 1


def test_synthetic_spark_redirect_refused_before_resend():
    handler = spark_module._RefuseRedirect()
    request = Request('https://api.meta.ai/v1/chat/completions', data=b'body')
    for code in (301, 302, 303, 307, 308):
        with pytest.raises(RuntimeError, match='redirect refused'):
            handler.redirect_request(request, None, code, 'x', {}, 'https://other.example/')
    assert any(isinstance(item, spark_module._RefuseRedirect)
               for item in spark_module._spark_opener().handlers)


def test_synthetic_latch_one_shot_and_crash(tmp_path):
    latch = tmp_path / 'latch.json'
    spark_module.init_proof_latch(latch)
    with pytest.raises(spark_module.ProofLatchError):
        spark_module.init_proof_latch(latch)
    assert spark_module.claim_proof_attempt(latch)['attempts_used'] == 1
    assert spark_module.claim_proof_attempt(latch)['attempts_used'] == 2
    assert spark_module.claim_proof_attempt(latch)['attempts_used'] == 3
    with pytest.raises(spark_module.ProofLatchError):
        spark_module.claim_proof_attempt(latch)
    with pytest.raises(spark_module.ProofLatchError):
        spark_module.init_proof_latch(latch)
    spark_module.latch_proof_uncertain(latch)
    with pytest.raises(spark_module.ProofLatchError):
        spark_module.claim_proof_attempt(latch)


def _valid_receipt():
    return {'model_usage': {
        'spark_calls': 3, 'spark_mode': 'spark', 'model_used': 'muse-spark-1.3',
        'models_used': ['muse-spark-1.3'], 'error_types': [],
        'wonder_used': False, 'wonder_attempts': 0,
        'token_counts': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
        'tokens_known': True, 'data_mode': 'standard_no_train',
        'data_basis': 'v2', 'request_provider': 'meta'}}


def _valid_per_call():
    return [{'mode': 'spark', 'usage': {'total_tokens': 5}, 'request_provider': 'meta'}
            for _ in range(3)]


def test_synthetic_receipt_all_three_success_only():
    ok, _ = _validate_spark_receipt(_valid_receipt(), _valid_per_call())
    assert ok is True
    partial = _valid_receipt()
    partial['model_usage']['error_types'] = ['TimeoutError']
    ok, _ = _validate_spark_receipt(partial, _valid_per_call())
    assert ok is False
    short = _valid_receipt()
    short['model_usage']['spark_calls'] = 2
    ok, _ = _validate_spark_receipt(short, _valid_per_call()[:2])
    assert ok is False
    wonder = _valid_receipt()
    wonder['model_usage']['wonder_attempts'] = 1
    ok, _ = _validate_spark_receipt(wonder, _valid_per_call())
    assert ok is False
    per_call = _valid_per_call()
    per_call[1] = {'mode': 'deterministic_fallback', 'usage': {}, 'request_provider': 'meta'}
    ok, _ = _validate_spark_receipt(_valid_receipt(), per_call)
    assert ok is False


def test_synthetic_files_body_order_and_expiry():
    body = sam_module._files_body('b1', 'photo.jpg', 'image/jpeg', b'raw-bytes')
    text = body.decode('utf-8', errors='replace')
    purpose = text.index('name="purpose"')
    anchor = text.index('name="expires_after[anchor]"')
    seconds = text.index('name="expires_after[seconds]"')
    file_part = text.index('name="file"')
    assert purpose < anchor < seconds < file_part
    assert 'created_at' in text and '3600' in text
    assert body.endswith(b'raw-bytes\r\n--b1--\r\n')


def test_synthetic_files_upload_types_strict():
    progress = {'uploads': 1, 'segmentations': 0}
    good = {'id': 'file-x', 'created_at': 1700000000, 'expires_at': 1700003600}
    assert sam_module._validate_files_upload(good, progress) == 'file-x'
    for bad in ({'id': '', 'created_at': 1, 'expires_at': 3601},
                {'id': 'f', 'created_at': True, 'expires_at': 3601},
                {'id': 'f', 'created_at': 1, 'expires_at': True},
                {'id': 'f', 'created_at': '1', 'expires_at': 3601},
                {'id': 'f', 'created_at': 1, 'expires_at': 3600},
                {'id': 'f'}, {'created_at': 1, 'expires_at': 3601}):
        with pytest.raises(sam_module.SamTransportError):
            sam_module._validate_files_upload(bad, dict(progress))


def test_synthetic_invalid_upload_blocks_segment_no_delete(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    calls = []

    def test_synthetic_invalid(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith('/files'):
            return io.BytesIO(b'{"id":"file-x"}')
        raise AssertionError('segmentation must not run after invalid upload')

    with patch('backend.sam.urlopen', side_effect=test_synthetic_invalid):
        with pytest.raises(sam_module.SamTransportError) as error:
            sam_module.upload_and_segment(b'\x89PNG\r\n\x1a\nrest', 'image/png')
    assert error.value.uploads == 1 and error.value.segmentations == 0
    assert calls == [url for url in calls if url.endswith('/files')]
    assert len(calls) == 1


def test_synthetic_admission_invalid_expiry_terminal_budget_spent(client, monkeypatch):
    import base64
    import hashlib
    from sqlalchemy import text
    from backend import store as store_module
    from launchcrew import run as run_module
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_SAM_ENABLED', 'true')
    original = run_module.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        created = client.post('/api/runs', json={'idea': 'expiry terminal probe',
                                                 'agent_name': 'Maker'})
    assert created.status_code == 201
    run_id = created.json()['run_id']
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (32, 16), (10, 20, 30)).save(buffer, format='PNG')
    raw = buffer.getvalue()
    monkeypatch.setenv('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', hashlib.sha256(raw).hexdigest())
    with store_module.engine().begin() as connection:
        connection.execute(text("UPDATE sam_budget SET remaining_images=1 WHERE id='global'"))
    calls = []

    def test_synthetic_expiry_invalid(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith('/files'):
            return io.BytesIO(b'{"id":"file-x","created_at":1,"expires_at":2}')
        raise AssertionError('no segmentation after invalid expiry')

    with patch('backend.sam.urlopen', side_effect=test_synthetic_expiry_invalid):
        response = client.post('/api/runs/%s/photo-check' % run_id, json={
            'image_data_uri': 'data:image/png;base64,' + base64.b64encode(raw).decode(),
            'expected_revision': 0})
    assert response.status_code == 200
    assert len(calls) == 1 and calls[0].endswith('/files')
    with store_module.engine().begin() as connection:
        budget = connection.execute(
            text("SELECT remaining_images FROM sam_budget WHERE id='global'")).scalar()
        row = connection.execute(
            text('SELECT status FROM sam_calls WHERE run_id=:id AND revision=0'),
            {'id': run_id}).mappings().first()
        connection.execute(text("UPDATE sam_budget SET remaining_images=0 WHERE id='global'"))
    assert budget == 0
    assert row is not None and row['status'] == 'failed_terminal'
