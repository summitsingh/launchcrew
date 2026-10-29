"""Truthful model capability and receipt usage. Offline only, no provider access."""
import io
import json
from unittest.mock import patch

from backend import app as backend_app, sam
from launchcrew import model_meta, run, spark


def completion(raw, usage=None):
    return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(raw)}}],
                                  'usage': usage or {}}).encode())


class _FakeAdmission:
    # Explicit fake spend admission for offline transport tests. No DB.
    def __init__(self):
        self.reserves = 0
        self.finalizes = []

    def reserve(self, *, request_digest, model, max_completion_tokens, n,
                request_bytes_len):
        assert model == 'muse-spark-1.3'
        assert max_completion_tokens == 2048 and n == 1
        assert request_bytes_len <= 32 * 1024
        self.reserves += 1
        return {'id': 'fake_%d' % self.reserves, 'status': 'admitted', 'is_owner': True}

    def finalize(self, call_id, *, status, outcome=None, prompt_tokens=None,
                 completion_tokens=None, total_tokens=None):
        self.finalizes.append((call_id, status, outcome))
        return {'id': call_id, 'status': status, 'is_owner': False}


def test_keyless_zero_attempt_is_not_sent(monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)
    monkeypatch.delenv('META_WONDER_MODEL', raising=False)
    monkeypatch.delenv('LAUNCHCREW_PHOTO_SAM_ENABLED', raising=False)
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('no network')), \
            patch('backend.sam.urlopen', side_effect=AssertionError('no network')):
        result = spark.call_spark_strict_json('s', 'u', {'claims': []})
    assert result['attempted'] is False
    assert result['request_provider'] == 'none'
    usage = run.model_usage([])
    assert usage['data_mode'] == 'not_sent'
    assert usage['data_basis'] == 'v2'
    assert usage['request_provider'] == 'none'
    assert usage['spark_calls'] == 0
    assert usage['model_used'] == 'none'
    assert usage['models_used'] == []
    snapshot = backend_app._capability_snapshot()
    assert snapshot['spark_configured'] is False
    assert snapshot['wonder_configured'] is False
    assert snapshot['sam_configured'] is False
    assert snapshot['spark_variant'] == 'not_configured'
    assert snapshot['wonder_variant'] == 'not_configured'


def test_configured_reports_present_without_proving_api(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_WONDER_MODEL', raising=False)
    monkeypatch.delenv('LAUNCHCREW_PHOTO_SAM_ENABLED', raising=False)
    with patch('launchcrew.spark.urlopen', side_effect=AssertionError('must not call')), \
            patch('backend.sam.urlopen', side_effect=AssertionError('must not call')):
        snapshot = backend_app._capability_snapshot()
    assert snapshot['spark_configured'] is True
    assert snapshot['wonder_configured'] is False
    assert snapshot['sam_configured'] is False
    assert snapshot['spark_variant'] == 'standard'
    assert snapshot['wonder_variant'] == 'not_configured'


def test_sam_flag_follows_operator_setting_not_legacy_env(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('LAUNCHCREW_SAM_DEMO_PHOTO', 'legacy-photo.jpg')
    monkeypatch.delenv('LAUNCHCREW_PHOTO_SAM_ENABLED', raising=False)
    assert backend_app._capability_snapshot()['sam_configured'] is False
    monkeypatch.setenv('LAUNCHCREW_PHOTO_SAM_ENABLED', 'true')
    assert backend_app._capability_snapshot()['sam_configured'] is True
    assert sam.photo_sam_operable() is True
    monkeypatch.delenv('META_API_KEY', raising=False)
    assert sam.photo_sam_operable() is False
    assert backend_app._capability_snapshot()['sam_configured'] is False


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
    # Custom models are disabled under the spend guard: refusal before HTTP,
    # zero HTTP, must not count as attempted.
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('META_MODEL', 'custom-future-model-9')
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    with patch('launchcrew.spark.urlopen', side_effect=TimeoutError('private')) as transport:
        result = spark.call_spark_strict_json('s', 'u', {'claims': []}, admission=_FakeAdmission())
    assert transport.call_count == 0
    assert result['attempted'] is False
    assert result['request_provider'] == 'none'
    usage = run.model_usage([('spark', result)])
    assert 'custom-future-model-9' not in json.dumps(usage)
    assert usage['data_mode'] == 'not_sent'
    assert usage['data_basis'] == 'v2'
    assert usage['model_used'] == 'none'
    assert usage['models_used'] == []
    assert usage['spark_calls'] == 0
    assert usage['error_types'] == []


def test_contributor_failure_states_training_permission(monkeypatch):
    # Contributor models are disabled under the spend guard: refusal before
    # HTTP, zero HTTP, must not count as attempted.
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('META_MODEL', 'muse-spark-1.3-contributor')
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    with patch('launchcrew.spark.urlopen', side_effect=TimeoutError('private')) as transport:
        result = spark.call_spark_strict_json('s', 'u', {'claims': []}, admission=_FakeAdmission())
    assert transport.call_count == 0
    assert result['attempted'] is False
    usage = run.model_usage([('spark', result)])
    assert usage['data_mode'] == 'not_sent'
    assert usage['request_provider'] == 'none'
    assert usage['spark_calls'] == 0


def test_mixed_wonder_standard_and_spark_contributor(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    wonder_ok = {'mode': 'spark', 'model_used': 'muse-wonder-1.0', 'attempted': True,
                 'attempted_model': 'muse-wonder-1.0', 'usage': {}, 'request_provider': 'meta'}
    spark_fail = {'mode': 'deterministic_fallback', 'model_used': 'none', 'attempted': True,
                  'attempted_model': 'muse-spark-1.3-contributor', 'error_type': 'TimeoutError', 'usage': {},
                  'request_provider': 'meta'}
    usage = run.model_usage([('wonder', wonder_ok), ('spark', spark_fail)])
    assert usage['data_mode'] == 'mixed'
    assert usage['request_provider'] == 'meta'
    assert 'may be used as training data' in usage['data_mode_note']
    assert usage['wonder_used'] is True
    assert usage['wonder_attempts'] == 1
    assert usage['spark_calls'] == 1


def test_standard_success_references_request_variant_not_certification(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    with patch('launchcrew.spark.urlopen', return_value=completion({'claims': []}, {'total_tokens': 4})):
        result = spark.call_spark_strict_json('s', 'u', {'claims': []}, admission=_FakeAdmission())
    assert result['request_provider'] == 'meta'
    usage = run.model_usage([('spark', result)])
    assert usage['data_mode'] == 'standard_no_train'
    assert usage['data_basis'] == 'v2'
    assert usage['request_provider'] == 'meta'
    assert usage['model_used'] == 'muse-spark-1.3'
    assert usage['models_used'] == ['muse-spark-1.3']
    assert 'actual requests on this run' in usage['data_mode_note']
    assert 'request variant' in usage['data_mode_note']
    assert 'not an independent certification' in usage['data_mode_note']


def test_successful_unknown_model_is_sanitized_to_unknown(monkeypatch):
    # Custom models are disabled under the spend guard: refusal, zero HTTP.
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setenv('META_MODEL', 'custom-future-model-9')
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    with patch('launchcrew.spark.urlopen', return_value=completion({'claims': []}, {'total_tokens': 4})) as transport:
        result = spark.call_spark_strict_json('s', 'u', {'claims': []}, admission=_FakeAdmission())
    assert transport.call_count == 0
    assert result['attempted'] is False
    usage = run.model_usage([('spark', result)])
    assert usage['data_mode'] == 'not_sent'
    assert usage['model_used'] == 'none'
    assert usage['models_used'] == []
    assert 'custom-future-model-9' not in json.dumps(usage)


def test_provider_allowlist_strict():
    assert model_meta.request_provider_from_base_url(None) == 'meta'
    assert model_meta.request_provider_from_base_url('') == 'meta'
    assert model_meta.request_provider_from_base_url('https://api.meta.ai/v1') == 'meta'
    assert model_meta.request_provider_from_base_url('https://api.meta.ai:443/v1') == 'meta'
    assert model_meta.request_provider_from_base_url('http://localhost:8000/v1') == 'unknown'
    assert model_meta.request_provider_from_base_url('http://api.meta.ai/v1') == 'unknown'
    assert model_meta.request_provider_from_base_url('https://api.meta.ai.evil.com/v1') == 'unknown'
    assert model_meta.request_provider_from_base_url('https://evil-api.meta.ai.evil.com/v1') == 'unknown'
    assert model_meta.request_provider_from_base_url('https://user:pass' + chr(64) + 'api.meta.ai/v1') == 'unknown'
    assert model_meta.request_provider_from_base_url('https://api.meta.ai:8443/v1') == 'unknown'
    assert model_meta.request_provider_from_base_url('not a url') == 'unknown'


def test_custom_endpoint_known_id_failure_is_unknown(monkeypatch):
    # Non-official endpoints are refused under the spend guard: zero HTTP.
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.setenv('META_API_BASE_URL', 'http://localhost:8000/v1')
    with patch('launchcrew.spark.urlopen', side_effect=TimeoutError('private')) as transport:
        result = spark.call_spark_strict_json('s', 'u', {'claims': []}, admission=_FakeAdmission())
    assert transport.call_count == 0
    assert result['attempted'] is False
    assert result['request_provider'] == 'none'
    usage = run.model_usage([('spark', result)])
    assert usage['data_mode'] == 'not_sent'
    assert usage['request_provider'] == 'none'
    assert 'localhost' not in json.dumps(usage)
    assert 'offline-fixture' not in json.dumps(usage)


def test_custom_endpoint_known_id_success_is_unknown(monkeypatch):
    # Non-official endpoints are refused under the spend guard: zero HTTP.
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.setenv('META_API_BASE_URL', 'https://custom.example.org/v1')
    with patch('launchcrew.spark.urlopen', return_value=completion({'claims': []}, {'total_tokens': 4})) as transport:
        result = spark.call_spark_strict_json('s', 'u', {'claims': []}, admission=_FakeAdmission())
    assert transport.call_count == 0
    assert result['attempted'] is False
    usage = run.model_usage([('spark', result)])
    assert usage['data_mode'] == 'not_sent'
    assert usage['request_provider'] == 'none'
    assert 'custom.example.org' not in json.dumps(usage)


def test_hostname_spoof_is_unknown(monkeypatch):
    # Spoofed endpoints are refused under the spend guard: zero HTTP.
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.setenv('META_API_BASE_URL', 'https://api.meta.ai.evil.com/v1')
    with patch('launchcrew.spark.urlopen', side_effect=TimeoutError('private')) as transport:
        result = spark.call_spark_strict_json('s', 'u', {'claims': []}, admission=_FakeAdmission())
    assert transport.call_count == 0
    assert result['attempted'] is False
    usage = run.model_usage([('spark', result)])
    assert usage['data_mode'] == 'not_sent'
    assert usage['request_provider'] == 'none'


def test_historical_stub_missing_provider_fails_closed():
    legacy_attempt = {'mode': 'spark', 'model_used': 'muse-spark-1.3', 'attempted': True,
                      'attempted_model': 'muse-spark-1.3', 'usage': {'total_tokens': 4}}
    usage = run.model_usage([('spark', legacy_attempt)])
    assert usage['data_mode'] == 'unknown'
    assert usage['request_provider'] == 'unknown'
    assert usage['data_basis'] == 'v2'


def test_unknown_provider_with_known_meta_id_fails_closed():
    attempt = {'mode': 'spark', 'model_used': 'muse-spark-1.3', 'attempted': True,
               'attempted_model': 'muse-spark-1.3', 'usage': {'total_tokens': 4},
               'request_provider': 'unknown'}
    usage = run.model_usage([('spark', attempt)])
    assert usage['data_mode'] == 'unknown'
    assert usage['request_provider'] == 'unknown'


def test_stored_usage_immutable_after_config_change(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    with patch('launchcrew.spark.urlopen', return_value=completion({'claims': []}, {'total_tokens': 4})):
        result = spark.call_spark_strict_json('s', 'u', {'claims': []}, admission=_FakeAdmission())
    usage = run.model_usage([('spark', result)])
    before = json.dumps(usage, sort_keys=True)
    assert usage['data_mode'] == 'standard_no_train'
    monkeypatch.setenv('META_API_BASE_URL', 'http://localhost:8000/v1')
    monkeypatch.setenv('META_MODEL', 'custom-future-model-9')
    assert json.dumps(usage, sort_keys=True) == before
    validated = backend_app.ModelUsage.model_validate(json.loads(before))
    assert validated.data_mode == 'standard_no_train'
    assert validated.data_basis == 'v2'
    assert validated.request_provider == 'meta'


def test_receipt_dict_without_data_mode_is_not_mutated():
    receipt = {'run_id': 'run_legacy', 'model_usage': {'mode': 'spark', 'spark_calls': 1, 'model_used': 'muse-spark-1.3'}}
    before = json.dumps(receipt, sort_keys=True)
    validated = backend_app.Receipt.model_validate({**receipt, 'idea': 'demo', 'status': 'completed',
                                                    'approval_state': 'pending_approval', 'approvals': [],
                                                    'summary': {}, 'audit': {}})
    assert validated.model_usage.data_mode == 'unknown'
    assert validated.model_usage.data_basis == ''
    assert json.dumps(receipt, sort_keys=True) == before


def test_legacy_old_standard_field_preserved_without_new_basis():
    receipt = {'run_id': 'run_legacy_old', 'model_usage': {
        'mode': 'spark', 'spark_calls': 1, 'model_used': 'muse-spark-1.3',
        'data_mode': 'standard_no_train',
        'data_mode_note': 'Stated intent for user data, not a verified API setting.'}}
    before = json.dumps(receipt, sort_keys=True)
    validated = backend_app.Receipt.model_validate({**receipt, 'idea': 'demo', 'status': 'completed',
                                                    'approval_state': 'pending_approval', 'approvals': [],
                                                    'summary': {}, 'audit': {}})
    assert validated.model_usage.data_mode == 'standard_no_train'
    assert validated.model_usage.data_basis == ''
    assert validated.model_usage.request_provider == 'unknown'
    assert json.dumps(receipt, sort_keys=True) == before
