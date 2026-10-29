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
from backend.live_meta_proof import _check_sam_env, _reserve_sam_latch, _validate_spark_receipt
from launchcrew import spark as spark_module


def test_synthetic_proof_constants_fixed():
    assert spark_module.PROOF_MODEL == 'muse-spark-1.3'
    assert spark_module.PROOF_ORIGIN == 'https://api.meta.ai/v1'
    assert spark_module.PROOF_CHAT_PATH == '/chat/completions'
    assert spark_module.PROOF_MAX_COMPLETION_TOKENS == 2048
    assert spark_module.PROOF_N == 1
    assert spark_module.PROOF_REASONING_EFFORT == 'minimal'
    assert spark_module.PROOF_MAX_BODY_BYTES == 32 * 1024
    assert spark_module.PROOF_MAX_ATTEMPTS == 3


def _proof_request(body):
    raw = json.dumps(body).encode()
    return Request(spark_module.PROOF_ORIGIN + spark_module.PROOF_CHAT_PATH,
                   data=raw, headers={'Content-Type': 'application/json'})


def _valid_body():
    return {'model': 'muse-spark-1.3', 'max_completion_tokens': 2048, 'n': 1,
            'reasoning_effort': 'minimal',
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
    assert captured['body']['reasoning_effort'] == 'minimal'


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


def test_synthetic_sam_env_refuses_base_override(monkeypatch, tmp_path):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_SAM_ENABLED', 'true')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', 'abc123')
    photo = tmp_path / 'photo.jpg'
    photo.write_bytes(b'\xff\xd8\xffrest')
    monkeypatch.setenv('LAUNCHCREW_PROOF_PHOTO_PATH', str(photo))
    monkeypatch.setenv('META_API_BASE_URL', 'https://other.example/v1')
    ok, reason = _check_sam_env()
    assert ok is False
    assert 'override refused' in reason
    monkeypatch.setenv('META_API_BASE_URL', 'https://api.meta.ai/v1')
    ok, _ = _check_sam_env()
    assert ok is True
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    ok, _ = _check_sam_env()
    assert ok is True


def test_synthetic_latch_concurrent_single_reservation(tmp_path):
    import concurrent.futures
    import os
    import subprocess
    import sys
    latch = tmp_path / 'concurrent-latch.json'
    code = "from launchcrew.spark import init_proof_latch; init_proof_latch(r'''%s''')" % str(latch)

    def one():
        env = dict(os.environ)
        env['PYTHONPYCACHEPREFIX'] = str(tmp_path / 'pycache')
        return subprocess.run([sys.executable, '-c', code], capture_output=True, env=env)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(one)
        future_b = pool.submit(one)
        result_a = future_a.result(timeout=30)
        result_b = future_b.result(timeout=30)
    codes = sorted([result_a.returncode, result_b.returncode])
    assert codes[0] == 0
    assert codes[1] != 0
    state = spark_module.read_proof_latch(latch)
    assert state['attempts_used'] == 0
    assert state['uncertain'] is False


def test_synthetic_sam_latch_concurrent_single(tmp_path):
    import concurrent.futures
    import os
    import subprocess
    import sys
    latch = tmp_path / 'sam-latch.json'
    code = ("from backend.live_meta_proof import _reserve_sam_latch; "
            "import sys; sys.exit(0 if _reserve_sam_latch(r'''%s''') else 1)") % str(latch)

    def one():
        env = dict(os.environ)
        env['PYTHONPYCACHEPREFIX'] = str(tmp_path / 'pycache')
        return subprocess.run([sys.executable, '-c', code], capture_output=True, env=env)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(one)
        future_b = pool.submit(one)
        result_a = future_a.result(timeout=30)
        result_b = future_b.result(timeout=30)
    codes = sorted([result_a.returncode, result_b.returncode])
    assert codes[0] == 0
    assert codes[1] != 0
    assert latch.exists()


def test_synthetic_proof_read_timeout_latches_no_followups(tmp_path):
    latch = tmp_path / 'read-latch.json'
    spark_module.init_proof_latch(latch)
    request = _proof_request(_valid_body())
    opens = {'count': 0}

    class TimeoutRead:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *args, **kwargs):
            raise TimeoutError('synthetic read timeout')

        def __iter__(self):
            raise TimeoutError('synthetic read timeout')

    class FakeOpener:
        def open(self, req, timeout=None):
            opens['count'] += 1
            return TimeoutRead()

    with patch.object(spark_module, '_spark_opener', return_value=FakeOpener()):
        response = spark_module.proof_urlopen(request, timeout=5, latch_path=latch)
        with pytest.raises(TimeoutError):
            with response:
                response.read()
        state = spark_module.read_proof_latch(latch)
        assert state['attempts_used'] == 1
        assert state['uncertain'] is True
        with pytest.raises(spark_module.ProofLatchError):
            spark_module.proof_urlopen(request, timeout=5, latch_path=latch)
        assert opens['count'] == 1


def test_synthetic_sam_ambiguous_grant_cleans_flag_and_zero_no_pass(monkeypatch, tmp_path, capsys):
    import hashlib
    import os
    from backend.live_meta_proof import run_sam_proof
    photo = tmp_path / 'proof.jpg'
    raw = b'\xff\xd8\xffsynthetic-test-bytes'
    photo.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_SAM_ENABLED', 'true')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', digest)
    monkeypatch.setenv('LAUNCHCREW_PROOF_PHOTO_PATH', str(photo))
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    state = {'begins': 0, 'grant': 0, 'zero': 0, 'provider': 0}

    class _FakeResult:
        def scalar(self):
            return 0

        def mappings(self):
            return self

        def first(self):
            return {'status': 'succeeded', 'label': 'synthetic', 'reason': ''}

    class _FakeConn:
        def __init__(self, index):
            self.index = index

        def execute(self, statement, params=None):
            sql = getattr(statement, 'text', str(statement))
            if 'remaining_images=1' in sql:
                state['grant'] += 1
                return _FakeResult()
            if 'remaining_images=0' in sql:
                state['zero'] += 1
                return _FakeResult()
            raise AssertionError('unexpected SQL in ambiguous test')

    class _FakeBegin:
        def __init__(self, index):
            self.index = index

        def __enter__(self):
            return _FakeConn(self.index)

        def __exit__(self, exc_type, exc, tb):
            if self.index == 0:
                raise RuntimeError('synthetic ambiguous grant ack failure')
            return False

    class _FakeEngine:
        def begin(self):
            idx = state['begins']
            state['begins'] += 1
            return _FakeBegin(idx)

    def fake_upload(*args, **kwargs):
        state['provider'] += 1
        raise AssertionError('provider must not run when grant is ambiguous')

    with patch('backend.store.engine', return_value=_FakeEngine()):
        with patch('backend.sam.upload_and_segment', side_effect=fake_upload):
            code = run_sam_proof(latch_path=tmp_path / 'sam-latch.json')
    captured = capsys.readouterr()
    text_out = captured.out + captured.err
    assert code != 0
    assert 'SAM PROOF PASS' not in text_out
    assert os.environ.get('LAUNCHCREW_PHOTO_SAM_ENABLED') == 'false'
    assert state['grant'] == 1
    assert state['zero'] >= 1
    assert state['provider'] == 0


def test_synthetic_sam_early_digest_fail_cleans_flag_and_zero_no_pass(monkeypatch, tmp_path, capsys):
    import os
    from backend.live_meta_proof import run_sam_proof
    photo = tmp_path / 'proof.jpg'
    photo.write_bytes(b'\xff\xd8\xffsynthetic-test-bytes')
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_SAM_ENABLED', 'true')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', '00' * 32)
    monkeypatch.setenv('LAUNCHCREW_PROOF_PHOTO_PATH', str(photo))
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    state = {'grant': 0, 'zero': 0, 'provider': 0}

    class _FakeResult:
        def scalar(self):
            return 0

        def mappings(self):
            return self

        def first(self):
            return {'status': 'succeeded', 'label': 'synthetic', 'reason': ''}

    class _FakeConn:
        def execute(self, statement, params=None):
            sql = getattr(statement, 'text', str(statement))
            if 'remaining_images=1' in sql:
                state['grant'] += 1
                return _FakeResult()
            if 'remaining_images=0' in sql:
                state['zero'] += 1
                return _FakeResult()
            raise AssertionError('unexpected SQL in early fail test')

    class _FakeBegin:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeEngine:
        def begin(self):
            return _FakeBegin()

    def fake_upload(*args, **kwargs):
        state['provider'] += 1
        raise AssertionError('provider must not run on early fail')

    with patch('backend.store.engine', return_value=_FakeEngine()):
        with patch('backend.sam.upload_and_segment', side_effect=fake_upload):
            code = run_sam_proof(latch_path=tmp_path / 'sam-latch.json')
    captured = capsys.readouterr()
    text_out = captured.out + captured.err
    assert code != 0
    assert 'SAM PROOF PASS' not in text_out
    assert os.environ.get('LAUNCHCREW_PHOTO_SAM_ENABLED') == 'false'
    assert state['grant'] == 0
    assert state['zero'] >= 1
    assert state['provider'] == 0


def test_synthetic_sam_success_cleans_before_pass(monkeypatch, tmp_path, capsys):
    import hashlib
    import os
    from backend.live_meta_proof import run_sam_proof
    photo = tmp_path / 'proof.jpg'
    raw = b'\xff\xd8\xffsynthetic-test-bytes'
    photo.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_SAM_ENABLED', 'true')
    monkeypatch.setenv('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', digest)
    monkeypatch.setenv('LAUNCHCREW_PROOF_PHOTO_PATH', str(photo))
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    state = {'grant': 0, 'zero': 0, 'provider': 0, 'run_create_keyless': None,
             'final_seen': False, 'flag_during_final': None}

    class _FakeResult:
        def __init__(self, scalar=None, row=None):
            self._scalar = scalar
            self._row = row

        def scalar(self):
            return self._scalar

        def mappings(self):
            return self

        def first(self):
            return self._row

    class _FakeConn:
        def execute(self, statement, params=None):
            sql = getattr(statement, 'text', str(statement))
            if 'remaining_images=1' in sql:
                state['grant'] += 1
                return _FakeResult()
            if 'remaining_images=0' in sql:
                state['zero'] += 1
                return _FakeResult()
            if 'SELECT remaining_images' in sql:
                if state['zero'] >= 1:
                    state['final_seen'] = True
                    state['flag_during_final'] = os.environ.get('LAUNCHCREW_PHOTO_SAM_ENABLED')
                return _FakeResult(scalar=0)
            if 'SELECT status' in sql and 'sam_calls' in sql:
                if state['zero'] >= 1:
                    state['final_seen'] = True
                    state['flag_during_final'] = os.environ.get('LAUNCHCREW_PHOTO_SAM_ENABLED')
                return _FakeResult(row={'status': 'succeeded', 'label': 'synthetic-test-label', 'reason': ''})
            raise AssertionError('unexpected SQL in success test')

    class _FakeBegin:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeEngine:
        def begin(self):
            return _FakeBegin()

    def fake_original(raw_arg, mime_arg, concept='product', timeout_s=30.0):
        state['provider'] += 1
        assert hashlib.sha256(raw_arg).hexdigest() == digest
        assert concept == 'jacket'
        return [{'synthetic': True}]

    class _FakeResp:
        def __init__(self, code, payload):
            self.status_code = code
            self._payload = payload

        def json(self):
            return dict(self._payload)

    class _FakeTestClient:
        def __init__(self, app_arg):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, path, json=None):
            if path == '/api/runs':
                key = os.environ.get('META_API_KEY', '').strip()
                state['run_create_keyless'] = (not key)
                return _FakeResp(201, {'run_id': 'synthetic-run-id'})
            if path.endswith('/photo-check'):
                from backend import sam as _sam
                raw_here = photo.read_bytes()
                _sam.upload_and_segment(raw_here, 'image/jpeg', concept='product')
                return _FakeResp(200, {'receipt': {'photo_status': {'state': 'checked'}}})
            raise AssertionError('unexpected POST path')

    with patch('backend.store.engine', return_value=_FakeEngine()):
        with patch('backend.sam.upload_and_segment', side_effect=fake_original):
            with patch('fastapi.testclient.TestClient', _FakeTestClient):
                code = run_sam_proof(latch_path=tmp_path / 'sam-latch.json')
    captured = capsys.readouterr()
    text_out = captured.out + captured.err
    assert code == 0
    assert 'SAM PROOF PASS' in text_out
    assert os.environ.get('LAUNCHCREW_PHOTO_SAM_ENABLED') == 'false'
    assert state['grant'] == 1
    assert state['zero'] >= 1
    assert state['provider'] == 1
    assert state['run_create_keyless'] is True
    assert state['final_seen'] is True
    assert state['flag_during_final'] == 'false'


def test_synthetic_proof_request_rejects_non_minimal_reasoning():
    parsed = spark_module.validate_proof_request(_proof_request(_valid_body()))
    assert parsed['reasoning_effort'] == 'minimal'
    missing = _valid_body()
    del missing['reasoning_effort']
    with pytest.raises(ValueError):
        spark_module.validate_proof_request(_proof_request(missing))
    for bad_effort in ('none', 'low', 'high', '', None, 0, False):
        bad = _valid_body()
        bad['reasoning_effort'] = bad_effort
        with pytest.raises(ValueError):
            spark_module.validate_proof_request(_proof_request(bad))


def test_synthetic_spark_success_keeps_strict_schema_and_usage(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_MODEL', raising=False)
    captured = {}

    def test_synthetic_success(request, timeout):
        captured['body'] = json.loads(request.data)
        assert len(request.data) <= 32 * 1024
        return io.BytesIO(json.dumps(
            {'choices': [{'message': {'content': json.dumps({'claims': ['synthetic-ok']})},
                          'finish_reason': 'stop'}],
             'usage': {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20,
                       'private_field': 'must-not-persist'}}).encode())

    with patch('launchcrew.spark.urlopen', side_effect=test_synthetic_success) as transport:
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []})
    assert transport.call_count == 1
    assert result['mode'] == 'spark'
    assert result['raw_json'] == {'claims': ['synthetic-ok']}
    assert result['usage'] == {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}
    assert result['request_provider'] == 'meta'
    body = captured['body']
    assert body['reasoning_effort'] == 'minimal'
    assert body['max_completion_tokens'] == 2048 and body['n'] == 1
    fmt = body['response_format']
    assert fmt['type'] == 'json_schema' and fmt['json_schema']['strict'] is True
    assert fmt['json_schema']['schema']['additionalProperties'] is False


def test_synthetic_spark_null_content_length_is_fallback(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_MODEL', raising=False)

    def test_synthetic_truncated(request, timeout):
        return io.BytesIO(json.dumps(
            {'choices': [{'message': {'content': None}, 'finish_reason': 'length'}],
             'usage': {'prompt_tokens': 10, 'completion_tokens': 2048,
                       'total_tokens': 2058}}).encode())

    with patch('launchcrew.spark.urlopen', side_effect=test_synthetic_truncated) as transport:
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []})
    assert transport.call_count == 1
    assert result['mode'] == 'deterministic_fallback'
    assert result['attempted'] is True
    assert result['error_type'] == 'ValueError'
    assert result['usage'] == {'prompt_tokens': 10, 'completion_tokens': 2048,
                               'total_tokens': 2058}
    assert result['request_provider'] == 'meta'
    assert 'raw_json' not in result
    assert 'length' not in json.dumps(result)


@pytest.mark.parametrize('content', [{'secret': 'x'}, ['x'], 123, True, None])
def test_synthetic_spark_nonstring_content_is_fallback(monkeypatch, content):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_MODEL', raising=False)

    def test_synthetic_nonstring(request, timeout):
        return io.BytesIO(json.dumps(
            {'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}],
             'usage': {'prompt_tokens': 3, 'completion_tokens': 4,
                       'total_tokens': 7}}).encode())

    with patch('launchcrew.spark.urlopen', side_effect=test_synthetic_nonstring) as transport:
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []})
    assert transport.call_count == 1
    assert result['mode'] == 'deterministic_fallback'
    assert result['error_type'] == 'ValueError'
    assert result['usage'] == {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}
    assert 'raw_json' not in result


@pytest.mark.parametrize('choices', [
    None, [], 'not-a-list', [None], ['x'], [{}],
    [{'message': None}], [{'message': 'x'}], [{'message': {}}],
    [{'message': {'content': ''}}], [{'message': {'content': '   '}}],
    [{'message': {'content': 'not-json'}}],
])
def test_synthetic_spark_malformed_choice_is_fallback(monkeypatch, choices):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_MODEL', raising=False)

    def test_synthetic_malformed(request, timeout):
        return io.BytesIO(json.dumps(
            {'choices': choices,
             'usage': {'prompt_tokens': 1, 'completion_tokens': 2,
                       'total_tokens': 3}}).encode())

    with patch('launchcrew.spark.urlopen', side_effect=test_synthetic_malformed) as transport:
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []})
    assert transport.call_count == 1
    assert result['mode'] == 'deterministic_fallback'
    assert result['error_type'] == 'ValueError'
    assert result['usage'] == {'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 3}
    assert 'raw_json' not in result


def test_synthetic_spark_malformed_never_leaks_provider_text(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_MODEL', raising=False)
    marker = 'SECRET-PROVIDER-TEXT-7f3a9c-unique'

    def test_synthetic_leak(request, timeout):
        return io.BytesIO(json.dumps(
            {'choices': [{'message': {'content': marker + ' not json'},
                          'finish_reason': 'stop'}],
             'usage': {'prompt_tokens': 5, 'completion_tokens': 6, 'total_tokens': 11,
                       'private_field': marker}}).encode())

    with patch('launchcrew.spark.urlopen', side_effect=test_synthetic_leak):
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []})
    assert result['mode'] == 'deterministic_fallback'
    assert result['usage'] == {'prompt_tokens': 5, 'completion_tokens': 6, 'total_tokens': 11}
    assert marker not in json.dumps(result)
    assert 'offline-fixture' not in json.dumps(result)

    def test_synthetic_leak_schema(request, timeout):
        return io.BytesIO(json.dumps(
            {'choices': [{'message': {'content': json.dumps(
                {'claims': [marker], 'extra': marker})}}],
             'usage': {'total_tokens': 2}}).encode())

    with patch('launchcrew.spark.urlopen', side_effect=test_synthetic_leak_schema):
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []})
    assert result['mode'] == 'deterministic_fallback'
    assert marker not in json.dumps(result)


def test_synthetic_spark_malformed_makes_single_http_call(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_MODEL', raising=False)
    calls = []

    def test_synthetic_counted(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(json.dumps(
            {'choices': [{'message': {'content': None}, 'finish_reason': 'length'}],
             'usage': {'total_tokens': 9}}).encode())

    with patch('launchcrew.spark.urlopen', side_effect=test_synthetic_counted):
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []})
    assert result['mode'] == 'deterministic_fallback'
    assert len(calls) == 1
