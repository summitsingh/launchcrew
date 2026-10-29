"""Muse-authored spend guard at the Spark send boundary.

Fake opener plus controlled Postgres. No provider access. Proves zero
budget refusal, reserve committed before HTTP, exact digest of exact
bytes, duplicate and uncertain no resend, sync async Campaign routing
with distinct real run ids, Wonder bypass refusal, keyless unchanged,
and sanitized usage accounting.
"""
import hashlib
import io
import json
import time
from unittest.mock import patch

import pytest
from sqlalchemy import text

from backend import model_admission as ma
from backend import store
from launchcrew import run as run_module
from launchcrew import spark as spark_module
from launchcrew.wonder import wonder_synthesize_for_scout

FIXED = ma.RESERVATION_USD_MICROS


@pytest.fixture(autouse=True)
def reset_model_ledger(test_engine):
    with test_engine.begin() as connection:
        connection.execute(text('TRUNCATE model_calls'))
        connection.execute(text("UPDATE model_budget SET remaining_micros=0 WHERE id='global'"))
    yield
    with test_engine.begin() as connection:
        connection.execute(text('TRUNCATE model_calls'))
        connection.execute(text("UPDATE model_budget SET remaining_micros=0 WHERE id='global'"))


@pytest.fixture(autouse=True)
def clean_model_env(monkeypatch):
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_WONDER_MODEL', raising=False)
    yield


def _grant(db, micros):
    with db.begin() as connection:
        connection.execute(
            text("UPDATE model_budget SET remaining_micros=:n WHERE id='global'"), {'n': micros})


def _budget(db):
    with db.begin() as connection:
        return connection.execute(
            text("SELECT remaining_micros FROM model_budget WHERE id='global'")).scalar()


def _count(db):
    with db.begin() as connection:
        return connection.execute(text('SELECT COUNT(*) FROM model_calls')).scalar()


def _stage_completion(request):
    body = json.loads(request.data)
    required = set(body['response_format']['json_schema']['schema']['required'])
    if required == {'facts_used', 'risks'}:
        raw = {'facts_used': [], 'risks': []}
    elif required == {'claims', 'post_lines', 'email_lines'}:
        raw = {'claims': [], 'post_lines': [], 'email_lines': []}
    else:
        raw = {'claims': []}
    return io.BytesIO(json.dumps(
        {'choices': [{'message': {'content': json.dumps(raw)}, 'finish_reason': 'stop'}],
         'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8}}).encode())


def _admission_for(test_engine, run_id, stage):
    return ma.EngineAdmission(test_engine, run_id=run_id, stage=stage, attempt_id='1')


def test_zero_budget_refusal_no_http(test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    admission = _admission_for(test_engine, 'run_zero', 'Scout:Spark')
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('must not send')) as transport:
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []}, admission=admission)
    assert transport.call_count == 0
    assert result['attempted'] is False
    assert result['request_provider'] == 'none'
    assert _budget(test_engine) == 0
    assert _count(test_engine) == 0
    usage = run_module.model_usage([('spark', result)])
    assert usage['spark_calls'] == 0
    assert usage['data_mode'] == 'not_sent'


def test_missing_admission_fails_closed_when_key_present(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('must not send')) as transport:
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []})
    assert transport.call_count == 0
    assert result['attempted'] is False
    assert result['request_provider'] == 'none'


def test_reserve_before_send_and_exact_digest(test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED)
    run_id = 'run_digest'
    stage = 'Scout:Spark'
    admission = _admission_for(test_engine, run_id, stage)
    seen = {}

    def opener(request, timeout=None):
        assert timeout == 30
        assert request.full_url == 'https://api.meta.ai/v1/chat/completions'
        raw = bytes(request.data)
        assert len(raw) <= 32 * 1024
        seen['raw'] = raw
        seen['digest'] = hashlib.sha256(raw).hexdigest()
        row = ma.get_call_by_identity(test_engine, run_id, stage, '1')
        assert row is not None
        assert row['status'] == 'admitted'
        assert row['request_digest'] == seen['digest']
        assert _budget(test_engine) == 0
        return _stage_completion(request)

    with patch('launchcrew.spark.urlopen', side_effect=opener) as transport:
        result = spark_module.call_spark_strict_json('sys', 'user', {'claims': []}, admission=admission)
    assert transport.call_count == 1
    assert result['mode'] == 'spark'
    assert result['attempted'] is True
    row = ma.get_call_by_identity(test_engine, run_id, stage, '1')
    assert row is not None
    assert row['request_digest'] == seen['digest'] == hashlib.sha256(seen['raw']).hexdigest()
    assert row['status'] == 'succeeded'
    assert row['outcome'] == 'ok'
    assert (row['prompt_tokens'], row['completion_tokens'], row['total_tokens']) == (5, 3, 8)
    assert _budget(test_engine) == 0
    assert _count(test_engine) == 1


def test_duplicate_same_identity_no_second_http(test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED)
    run_id = 'run_dup'
    admission = _admission_for(test_engine, run_id, 'Maker')
    with patch('launchcrew.spark.urlopen', side_effect=_stage_completion) as transport:
        first = spark_module.call_spark_strict_json('s', 'same-user', {'claims': []}, admission=admission)
    assert transport.call_count == 1
    assert first['attempted'] is True
    replay_admission = _admission_for(test_engine, run_id, 'Maker')
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('resend refused')) as transport:
        second = spark_module.call_spark_strict_json('s', 'same-user', {'claims': []}, admission=replay_admission)
    assert transport.call_count == 0
    assert second['attempted'] is False
    assert _budget(test_engine) == 0
    assert _count(test_engine) == 1


def test_digest_mismatch_conflict_no_http(test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED)
    run_id = 'run_conflict'
    first_admission = _admission_for(test_engine, run_id, 'Checker')
    with patch('launchcrew.spark.urlopen', side_effect=_stage_completion):
        first = spark_module.call_spark_strict_json('s', 'user-one', {'claims': []}, admission=first_admission)
    assert first['attempted'] is True
    second_admission = _admission_for(test_engine, run_id, 'Checker')
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('must not send')) as transport:
        second = spark_module.call_spark_strict_json('s', 'user-two-different', {'claims': []},
                                                     admission=second_admission)
    assert transport.call_count == 0
    assert second['attempted'] is False
    assert _budget(test_engine) == 0
    assert _count(test_engine) == 1


def test_uncertain_ambiguous_terminal_never_resent(test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED)
    run_id = 'run_ambiguous'
    admission = _admission_for(test_engine, run_id, 'Scout:Spark')
    with patch('launchcrew.spark.urlopen', side_effect=TimeoutError('private')) as transport:
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []}, admission=admission)
    assert transport.call_count == 1
    assert result['attempted'] is True
    assert result['error_type'] == 'TimeoutError'
    row = ma.get_call_by_identity(test_engine, run_id, 'Scout:Spark', '1')
    assert row['status'] == 'ambiguous_terminal'
    replay = _admission_for(test_engine, run_id, 'Scout:Spark')
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('resend refused')) as transport:
        second = spark_module.call_spark_strict_json('s', 'u', {'claims': []}, admission=replay)
    assert transport.call_count == 0
    assert second['attempted'] is False
    assert _budget(test_engine) == 0


def test_crash_admitted_replay_no_resend(test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED)
    run_id = 'run_crash'
    admission = _admission_for(test_engine, run_id, 'Maker')
    original_finalize = admission.finalize

    def failing_finalize(*args, **kwargs):
        raise RuntimeError('simulated crash before finalize commit')

    admission.finalize = failing_finalize
    with patch('launchcrew.spark.urlopen', side_effect=_stage_completion) as transport:
        first = spark_module.call_spark_strict_json('s', 'u', {'claims': []}, admission=admission)
    assert transport.call_count == 1
    assert first['attempted'] is True
    admission.finalize = original_finalize
    row = ma.get_call_by_identity(test_engine, run_id, 'Maker', '1')
    assert row['status'] == 'admitted'
    replay = _admission_for(test_engine, run_id, 'Maker')
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('resend refused')) as transport:
        second = spark_module.call_spark_strict_json('s', 'u', {'claims': []}, admission=replay)
    assert transport.call_count == 0
    assert second['attempted'] is False


def test_sync_route_uses_real_run_id_and_reserve(client, test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED * 3)
    with patch('launchcrew.spark.urlopen', side_effect=_stage_completion) as transport:
        response = client.post('/api/runs', json={'idea': 'Demo wallet', 'agent_name': 'Maker'})
    assert response.status_code == 201
    assert transport.call_count == 3
    receipt = response.json()
    run_id = receipt['run_id']
    assert run_id.startswith('run_')
    assert receipt['model_usage']['spark_calls'] == 3
    assert receipt['model_usage']['mode'] == 'spark'
    with test_engine.begin() as connection:
        rows = connection.execute(
            text('SELECT stage, status FROM model_calls WHERE run_id=:id'),
            {'id': run_id}).mappings().all()
    assert sorted(r['stage'] for r in rows) == ['Checker', 'Maker', 'Scout:Spark']
    assert all(r['status'] == 'succeeded' for r in rows)
    assert _budget(test_engine) == 0
    serialized = json.dumps(receipt)
    assert 'offline-fixture' not in serialized


def test_sync_route_zero_budget_refuses_no_http(client, test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('must not send')) as transport:
        response = client.post('/api/runs', json={'idea': 'Demo wallet', 'agent_name': 'Maker'})
    assert response.status_code == 201
    assert transport.call_count == 0
    receipt = response.json()
    assert receipt['model_usage']['spark_calls'] == 0
    assert receipt['model_usage']['mode'] == 'deterministic_fallback'
    assert _count(test_engine) == 0


def _wait_completed(client, run_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        receipt = client.get('/api/runs/%s/receipt' % run_id)
        assert receipt.status_code == 200
        body = receipt.json()
        if body['status'] == 'completed':
            return body
        time.sleep(0.05)
    raise AssertionError('async run did not complete: ' + run_id)


def test_async_worker_uses_distinct_real_run_id(client, test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED * 3)
    with patch('launchcrew.spark.urlopen', side_effect=_stage_completion) as transport:
        created = client.post('/api/runs/async', json={'idea': 'Demo wallet', 'agent_name': 'Maker'})
        assert created.status_code == 202
        run_id = created.json()['run_id']
        receipt = _wait_completed(client, run_id)
    assert transport.call_count == 3
    assert receipt['run_id'] == run_id
    assert receipt['model_usage']['spark_calls'] == 3
    with test_engine.begin() as connection:
        rows = connection.execute(
            text('SELECT stage FROM model_calls WHERE run_id=:id'), {'id': run_id}).scalars().all()
    assert sorted(rows) == ['Checker', 'Maker', 'Scout:Spark']


def test_campaign_seven_distinct_run_ids(client, test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED * 21)
    with patch('launchcrew.spark.urlopen', side_effect=_stage_completion) as transport:
        response = client.post('/api/campaigns', json={'idea': 'Demo wallet', 'agent_name': 'Maker'})
    assert response.status_code == 201
    assert transport.call_count == 21
    week = response.json()
    run_ids = [day['run_id'] for day in week['days']]
    assert len(run_ids) == 7
    assert len(set(run_ids)) == 7
    assert all(r.startswith('run_') for r in run_ids)
    assert _count(test_engine) == 21
    assert _budget(test_engine) == 0
    with test_engine.begin() as connection:
        for run_id in run_ids:
            stages = connection.execute(
                text('SELECT stage FROM model_calls WHERE run_id=:id'),
                {'id': run_id}).scalars().all()
            assert sorted(stages) == ['Checker', 'Maker', 'Scout:Spark']


def test_wonder_bypass_refused_even_with_budget(client, test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('META_WONDER_MODEL', 'muse-wonder-1.0')
    _grant(test_engine, FIXED * 3)
    with patch('launchcrew.spark.urlopen', side_effect=_stage_completion) as transport:
        direct = wonder_synthesize_for_scout(
            'task', None, {'name': 'Scout'},
            admission=_admission_for(test_engine, 'run_wonder', 'Scout:Wonder'))
    assert transport.call_count == 0
    assert direct['attempted'] is False
    with patch('launchcrew.spark.urlopen', side_effect=_stage_completion) as transport:
        response = client.post('/api/runs', json={'idea': 'Demo wallet', 'agent_name': 'Maker'})
    assert response.status_code == 201
    assert transport.call_count == 3
    usage = response.json()['model_usage']
    assert usage['wonder_attempts'] == 0
    assert usage['wonder_used'] is False
    assert usage['spark_calls'] == 3


def test_alternate_model_and_endpoint_refused_with_budget(test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED)
    admission = _admission_for(test_engine, 'run_alt', 'Maker')
    monkeypatch.setenv('META_MODEL', 'muse-spark-1.3-contributor')
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('must not send')) as transport:
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []}, admission=admission)
    assert transport.call_count == 0
    assert result['attempted'] is False
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.setenv('META_API_BASE_URL', 'https://custom.example.org/v1')
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('must not send')) as transport:
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []}, admission=admission)
    assert transport.call_count == 0
    assert result['attempted'] is False
    assert _budget(test_engine) == FIXED
    assert _count(test_engine) == 0


def test_no_key_path_unchanged_without_admission(monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('no network')):
        result = spark_module.call_spark_strict_json('s', 'u', {'claims': []})
        assert result['attempted'] is False
        assert result['request_provider'] == 'none'
        assert wonder_synthesize_for_scout('demo', lambda: None) is None


def test_usage_accounting_sanitized_no_secrets(test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    _grant(test_engine, FIXED)
    admission = _admission_for(test_engine, 'run_usage', 'Checker')

    def opener(request, timeout=None):
        return io.BytesIO(json.dumps(
            {'choices': [{'message': {'content': json.dumps({'claims': []})}, 'finish_reason': 'stop'}],
             'usage': {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20,
                       'private_field': 'must-not-persist'}}).encode())

    with patch('launchcrew.spark.urlopen', side_effect=opener):
        result = spark_module.call_spark_strict_json('sys-prompt-private', 'user-prompt-private',
                                                     {'claims': []}, admission=admission)
    assert result['usage'] == {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}
    row = ma.get_call_by_identity(test_engine, 'run_usage', 'Checker', '1')
    assert (row['prompt_tokens'], row['completion_tokens'], row['total_tokens']) == (12, 8, 20)
    assert row['outcome'] == 'ok'
    serialized = json.dumps(result) + json.dumps(row)
    assert 'offline-fixture' not in serialized
    assert 'sys-prompt-private' not in serialized
    assert 'user-prompt-private' not in serialized
    assert 'must-not-persist' not in serialized
    assert 'postgresql' not in serialized.lower()
