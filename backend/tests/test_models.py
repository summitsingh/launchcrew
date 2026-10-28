"""Offline transport and deterministic gate regressions. No provider access."""
import io
import json
from unittest.mock import patch
import pytest
from backend import adapter, sam
from launchcrew import spark
from launchcrew.facts import load_facts


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)
    monkeypatch.delenv('META_WONDER_MODEL', raising=False)
    monkeypatch.delenv('LAUNCHCREW_SAM_DEMO_PHOTO', raising=False)
    # Fail closed if any test accidentally reaches the real network.
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('Unexpected transport')), \
            patch('backend.sam.urlopen', side_effect=AssertionError('Unexpected transport')):
        yield


def execute(seed=False):
    profile = adapter.agents.load_agent('Maker', adapter.ROOT / 'agents')
    return adapter.execute('model_test', 'Demo wallet', profile, seed)


def completion(raw, usage=None):
    return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(raw)}}],
                                 'usage': usage or {}}).encode())


def test_strict_spark_success_filters_before_maker(monkeypatch, caplog):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    facts, _ = load_facts('facts/demo_facts.json')
    good = facts['approved_claims'][0]
    bad = good + ' and waterproof'
    calls = []

    def transport(request, timeout):
        assert timeout == 30
        body = json.loads(request.data)
        calls.append(body)
        fmt = body['response_format']
        assert fmt['type'] == 'json_schema' and fmt['json_schema']['strict'] is True
        schema = fmt['json_schema']['schema']
        assert schema['additionalProperties'] is False
        raw = {'facts_used': [good, bad], 'risks': []} if len(calls) == 1 else {'claims': [bad, good]}
        return completion(raw, {'total_tokens': 7, 'prompt_tokens': 5, 'completion_tokens': 2,
                                'private_field': 'must-not-persist'})

    with patch('launchcrew.spark.urlopen', side_effect=transport):
        receipt = execute()
    assert len(calls) == 3
    assert not next(f for f in receipt['scout']['facts_used'] if f['claim'] == bad)['verified']
    assert bad not in receipt['maker_draft_v1']['claims']
    assert receipt['maker_draft_v1']['claims'] == [good]
    assert receipt['checker_v1']['blocked_count'] == receipt['checker_v2']['blocked_count'] == 0
    usage = receipt['model_usage']
    assert usage['spark_calls'] == 3 and usage['model_used'] == 'muse-spark-1.3'
    assert usage['token_counts'] == {'total_tokens': 21, 'prompt_tokens': 15, 'completion_tokens': 6}
    assert usage['tokens_known'] is True and usage['wonder_used'] is False
    serialized = json.dumps(receipt) + caplog.text
    for private in ('Authorization', 'offline-fixture', 'private_field', 'must-not-persist'):
        assert private not in serialized


def test_absent_key_never_calls_network():
    with patch('launchcrew.spark.urlopen') as network, patch('backend.sam.urlopen') as visual:
        result = execute()
        direct = spark.call_spark_strict_json('s', 'u', {'claims': []})
    network.assert_not_called()
    visual.assert_not_called()
    assert direct['attempted'] is False
    assert result['model_usage']['mode'] == 'deterministic_fallback'
    assert result['model_usage']['model_used'] == 'none'
    assert result['model_usage']['spark_calls'] == 0
    assert result['visual_verification'] == {'method': 'not_run', 'checked': False}


def test_failure_falls_back_type_only(monkeypatch, caplog):
    baseline = execute(True)
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    with patch('launchcrew.spark.urlopen', side_effect=TimeoutError('Authorization Bearer offline-fixture')):
        receipt = execute(True)
    assert receipt['model_usage']['error_types'] == ['TimeoutError'] * 3
    assert receipt['model_usage']['mode'] == 'TimeoutError'
    for field in ('maker_draft_v1', 'checker_v1', 'maker_draft_v2', 'checker_v2', 'approval_state'):
        assert receipt[field] == baseline[field]
    assert 'Authorization' not in json.dumps(receipt) + caplog.text
    assert 'offline-fixture' not in json.dumps(receipt) + caplog.text


@pytest.mark.parametrize('raw', [{'claims': 'bad'}, {'claims': [1]}, {'claims': [], 'verdict': 'approved'}, []])
def test_invalid_json_shape_falls_back(monkeypatch, raw):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    with patch('launchcrew.spark.urlopen', return_value=completion(raw)):
        result = spark.call_spark_strict_json('s', 'u', {'claims': []})
    assert result['error_type'] == 'ValueError'
    assert 'raw_json' not in result


def test_checker_suggestion_cannot_unblock(monkeypatch):
    baseline = execute(True)
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    facts, _ = load_facts('facts/demo_facts.json')
    with patch('launchcrew.spark.urlopen', side_effect=[
        completion({'facts_used': [], 'risks': []}),
        completion({'claims': facts['approved_claims']}),
        completion({'claims': []})]):
        result = execute(True)
    assert result['checker_v1'] == baseline['checker_v1']
    assert result['checker_v2'] == baseline['checker_v2']
    assert result['approval_state'] == 'pending_approval'
    assert result['approvals'] == []


def test_wonder_failure_audited_then_spark(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('META_WONDER_MODEL', 'muse-wonder-1.0')
    with patch('launchcrew.spark.urlopen', side_effect=[TimeoutError('private'),
        completion({'facts_used': [], 'risks': []}), completion({'claims': []}), completion({'claims': []})]):
        result = execute()
    assert result['model_usage']['wonder_attempts'] == 1
    assert result['model_usage']['spark_calls'] == 3
    assert result['model_usage']['error_types'] == ['TimeoutError']
    assert result['model_usage']['wonder_used'] is False
    assert result['model_usage']['tokens_known'] is False


def test_wonder_success_and_unknown_usage(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('META_WONDER_MODEL', 'muse-wonder-1.0')
    with patch('launchcrew.spark.urlopen', side_effect=[
        completion({'facts_used': [], 'risks': []}), completion({'claims': []}), completion({'claims': []})]):
        result = execute()
    usage = result['model_usage']
    assert usage['wonder_used'] is True and usage['wonder_attempts'] == 1
    assert usage['spark_calls'] == 2 and usage['tokens_known'] is False
    assert usage['models_used'] == ['muse-spark-1.3', 'muse-wonder-1.0']


def sse(*events):
    return io.BytesIO(b''.join(b'data: ' + json.dumps(e).encode() + b'\n\n' for e in events))


TAG = '<0f>2<|box;x1=1;y1=2;x2=3;y2=4;w=8;h=8|><|mask;x=0;y=0;data=2,2,~demo-payload|>'


def stream():
    return sse({'type': 'response.output_text.delta', 'delta': TAG[:30]},
               {'type': 'response.output_text.delta', 'delta': TAG[30:]},
               {'type': 'response.completed'})


def test_sam_parser_pairs_lossless_box_mask():
    records = sam.parse_sse(stream())
    assert records[0]['object_id'] == 2
    assert records[0]['box'] == (1, 2, 3, 4, 8, 8)
    assert records[0]['mask'] == {'x': 0, 'y': 0, 'height': 2, 'width': 2,
                                  'encoding': 'lossless', 'payload': 'demo-payload'}
    assert sam.parse_sse(sse({'type': 'response.completed'})) == []
    with pytest.raises(ValueError):
        sam.parse_sse(sse({'type': 'response.output_text.delta', 'delta': TAG}))
    with pytest.raises(RuntimeError):
        sam.parse_sse(sse({'type': 'response.failed'}))


def test_sam_transport_and_safe_receipt(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setattr(sam, 'DEMO_PHOTOS', tmp_path)
    photo = tmp_path / 'wallet.png'
    photo.write_bytes(b'demo photo fixture')
    assert sam.verify_demo_photo(photo) == {'method': 'not_run', 'checked': False}
    calls = []

    def transport(request, timeout):
        assert 0 < timeout <= 30
        calls.append(request)
        if len(calls) == 1:
            assert request.full_url.endswith('/files')
            assert b'user_data' in request.data and b'demo photo fixture' in request.data
            return io.BytesIO(b'{"id":"file-demo"}')
        body = json.loads(request.data)
        assert request.full_url.endswith('/responses')
        assert body['model'] == 'sam-3.1' and body['stream'] is True
        assert body['metadata'] == {'mask_encoding': 'lossless'}
        assert body['input'][0]['content'][1] == {'type': 'input_image', 'file_id': 'file-demo'}
        return stream()

    monkeypatch.setenv('LAUNCHCREW_SAM_DEMO_PHOTO', photo.name)
    with patch('backend.sam.urlopen', side_effect=transport):
        receipt = execute()
    assert receipt['visual_verification'] == {'method': 'sam-3.1', 'checked': True}
    assert len(calls) == 2
    for private in ('demo-payload', 'file-demo', 'demo photo fixture', 'Authorization', 'offline-fixture'):
        assert private not in json.dumps(receipt) + caplog.text


def test_sam_failure_does_not_block_approval_or_export(tmp_path, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setattr(sam, 'DEMO_PHOTOS', tmp_path)
    photo = tmp_path / 'wallet.png'
    photo.write_bytes(b'demo')
    monkeypatch.setenv('LAUNCHCREW_SAM_DEMO_PHOTO', photo.name)
    with patch('backend.sam.urlopen', side_effect=OSError('Authorization private')):
        receipt = execute()
    assert receipt['visual_verification'] == {'method': 'sam-3.1', 'checked': False, 'error_type': 'OSError'}
    from launchcrew.receipts import approve_receipt
    approve_receipt(receipt, 'demo')
    assert json.loads(adapter.export_pack(receipt))['approval_state'] == 'approved_for_export'
    assert 'Authorization' not in json.dumps(receipt)
    assert sam.verify_demo_photo(tmp_path.parent / 'other.png', enabled=True)['error_type'] == 'ValueError'


def test_non_model_routes_do_not_call_transport(client, monkeypatch):
    run = client.post('/api/runs', json={'idea': 'demo', 'agent_name': 'Maker'}).json()
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    with patch('launchcrew.spark.urlopen') as network, patch('backend.sam.urlopen') as visual:
        profile = client.get('/api/agents/Maker').json()
        profile['name'] = 'Offline'
        for method, path, body in [
            ('get', '/api/health', None), ('get', '/api/agents', None),
            ('post', '/api/agents', profile), ('put', '/api/agents/Offline', profile),
            ('post', '/api/agents/Maker/clone', {'name': 'OfflineCopy'}),
            ('post', '/api/agents/Maker/preview', {'idea': 'demo'}),
            ('get', '/api/queue', None), ('get', '/api/runs/' + run['run_id'], None),
            ('get', '/api/runs/' + run['run_id'] + '/receipt', None),
            ('post', '/api/runs/' + run['run_id'] + '/approve', {}),
            ('post', '/api/runs/' + run['run_id'] + '/export', {}),
            ('get', '/api/auth/status', None), ('post', '/api/auth/logout', {}),
            ('get', '/api/auth/google/login', None), ('get', '/api/auth/facebook/callback', None),
            ('get', '/api/model-capabilities', None), ('get', '/api/checker-policies', None)]:
            response = getattr(client, method)(path, **({'json': body} if body is not None else {}))
            assert response.status_code in (200, 201, 404)
    network.assert_not_called()
    visual.assert_not_called()


def test_runs_route_calls_server_transport(client, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    with patch('launchcrew.spark.urlopen', side_effect=[completion({'facts_used': [], 'risks': []}),
                completion({'claims': []}), completion({'claims': []})]) as network:
        response = client.post('/api/runs', json={'idea': 'demo', 'agent_name': 'Maker'})
    assert response.status_code == 201 and network.call_count == 3
    assert response.json()['model_usage']['mode'] == 'spark'


def test_failed_pipeline_retains_usage_type_only(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    with patch('launchcrew.spark.urlopen', side_effect=[completion({'facts_used': [], 'risks': []}, {'total_tokens': 8}),
               completion({'claims': []})]), patch('launchcrew.run.make_draft', side_effect=RuntimeError('private')):
        result = execute()
    assert result['status'] == 'failed' and result['error_type'] == 'RuntimeError'
    assert result['model_usage']['spark_calls'] == 2
    assert result['model_usage']['token_counts']['total_tokens'] == 8
    assert 'private' not in json.dumps(result)


def test_deterministic_checks_precede_models(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    with patch('launchcrew.run.check_claims', return_value={'blocked_count': 1}), \
            patch('launchcrew.spark.urlopen') as transport:
        result = execute()
    assert result['status'] == 'failed'
    assert result['audit']['stopped_reason'] == 'deterministic_checks'
    transport.assert_not_called()


def test_invalid_candidate_retains_returned_token_counts(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    with patch('launchcrew.spark.urlopen', return_value=completion({'claims': 'invalid'}, {'total_tokens': 9})):
        result = spark.call_spark_strict_json('s', 'u', {'claims': []})
    assert result['error_type'] == 'ValueError'
    assert result['usage'] == {'total_tokens': 9}
