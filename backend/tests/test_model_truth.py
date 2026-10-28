"""Truthful model capability and receipt usage. Offline only, no provider access."""
import io
import json
from unittest.mock import patch

from backend import app as backend_app
from launchcrew import run, spark


def completion(raw, usage=None):
    return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(raw)}}],
                                  'usage': usage or {}}).encode())


def test_keyless_zero_attempt_is_not_sent(monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)
    monkeypatch.delenv('META_WONDER_MODEL', raising=False)
    monkeypatch.delenv('LAUNCHCREW_SAM_DEMO_PHOTO', raising=False)
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('no network')), \
            patch('backend.sam.urlopen', side_effect=AssertionError('no network')):
        result = spark.call_spark_strict_json('s', 'u', {'claims': []})
    assert result['attempted'] is False
    usage = run.model_usage([])
    assert usage['data_mode'] == 'not_sent'
    assert usage['spark_calls'] == 0
    assert usage['model_used'] == 'none'
    assert usage['models_used'] == []
    snapshot = backend_app._capability_snapshot()
    assert snapshot['spark_configured'] is False
    assert snapshot['wonder_configured'] is False
    assert snapshot['sam_configured'] is False
    assert snapshot['spark_variant'] == 'not_configured'
    assert snapshot['wonder_variant'] == 'not_configured'


def test_configured_but_untested_reports_config_without_network(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_WONDER_MODEL', raising=False)
    monkeypatch.delenv('LAUNCHCREW_SAM_DEMO_PHOTO', raising=False)
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('must not call')), \
            patch('backend.sam.urlopen', side_effect=AssertionError('must not call')):
        snapshot = backend_app._capability_snapshot()
    assert snapshot['spark_configured'] is True
    assert snapshot['wonder_configured'] is False
    assert snapshot['sam_configured'] is False
    assert snapshot['spark_variant'] == 'standard'
    assert snapshot['wonder_variant'] == 'not_configured'


def test_configured_unknown_model_makes_no_guarantee(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('META_MODEL', 'custom-future-model-9')
    snapshot = backend_app._capability_snapshot()
    assert snapshot['spark_configured'] is True
    assert snapshot['spark_variant'] == 'unknown'
    raw = json.dumps(snapshot)
    assert 'custom-future-model-9' not in raw
    assert 'offline-fixture' not in raw


def test_failed_attempt_captures_variant_and_stays_unknown_for_custom(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('META_MODEL', 'custom-future-model-9')
    with patch('launchcrew.spark.urlopen', side_effect=TimeoutError('private')):
        result = spark.call_spark_strict_json('s', 'u', {'claims': []})
    assert result['attempted'] is True
    usage = run.model_usage([('spark', result)])
    assert 'custom-future-model-9' not in json.dumps(usage)
    assert usage['data_mode'] == 'unknown'
    assert usage['model_used'] == 'none'
    assert usage['models_used'] == []
    assert usage['error_types'] == ['TimeoutError']
    assert 'No training guarantee is claimed' in usage['data_mode_note']


def test_contributor_failure_captures_contributor_without_false_standard_claim(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('META_MODEL', 'muse-spark-1.3-contributor')
    with patch('launchcrew.spark.urlopen', side_effect=TimeoutError('private')):
        result = spark.call_spark_strict_json('s', 'u', {'claims': []})
    usage = run.model_usage([('spark', result)])
    assert usage['data_mode'] == 'contributor'
    assert 'No training guarantee is claimed' in usage['data_mode_note']


def test_mixed_wonder_standard_and_spark_contributor(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    wonder_ok = {'mode': 'spark', 'model_used': 'muse-wonder-1.0', 'attempted': True,
                 'attempted_model': 'muse-wonder-1.0', 'usage': {}}
    spark_fail = {'mode': 'deterministic_fallback', 'model_used': 'none', 'attempted': True,
                  'attempted_model': 'muse-spark-1.3-contributor', 'error_type': 'TimeoutError', 'usage': {}}
    usage = run.model_usage([('wonder', wonder_ok), ('spark', spark_fail)])
    assert usage['data_mode'] == 'mixed'
    assert usage['wonder_used'] is True
    assert usage['wonder_attempts'] == 1
    assert usage['spark_calls'] == 1


def test_standard_success_stays_standard_no_train_with_actual_request_note(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_MODEL', raising=False)
    with patch('launchcrew.spark.urlopen', return_value=completion({'claims': []}, {'total_tokens': 4})):
        result = spark.call_spark_strict_json('s', 'u', {'claims': []})
    usage = run.model_usage([('spark', result)])
    assert usage['data_mode'] == 'standard_no_train'
    assert usage['model_used'] == 'muse-spark-1.3'
    assert usage['models_used'] == ['muse-spark-1.3']
    assert 'actual requests on this run' in usage['data_mode_note']


def test_successful_unknown_model_is_sanitized_to_unknown(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('META_MODEL', 'custom-future-model-9')
    with patch('launchcrew.spark.urlopen', return_value=completion({'claims': []}, {'total_tokens': 4})):
        result = spark.call_spark_strict_json('s', 'u', {'claims': []})
    assert result['model_used'] == 'custom-future-model-9'
    usage = run.model_usage([('spark', result)])
    assert usage['data_mode'] == 'unknown'
    assert usage['model_used'] == 'unknown'
    assert usage['models_used'] == ['unknown']
    assert 'custom-future-model-9' not in json.dumps(usage)


def test_receipt_dict_without_data_mode_is_not_mutated():
    receipt = {'run_id': 'run_legacy', 'model_usage': {'mode': 'spark', 'spark_calls': 1, 'model_used': 'muse-spark-1.3'}}
    before = json.dumps(receipt, sort_keys=True)
    validated = backend_app.Receipt.model_validate({**receipt, 'idea': 'demo', 'status': 'completed',
                                                    'approval_state': 'pending_approval', 'approvals': [],
                                                    'summary': {}, 'audit': {}})
    assert validated.model_usage.data_mode == 'unknown'
    assert json.dumps(receipt, sort_keys=True) == before
