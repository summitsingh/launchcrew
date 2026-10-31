"""M1 live model drafts: mocked Spark path plus offline fallback labels.

Mocked transport only, no provider access. Proves a signed-in style run
through POST /api/runs with the Meta key present produces distinct real
launch copy (not joined or reordered facts), includes the founder note in
the draft variant, reports model name plus Spark call count plus token
counts plus measured latency on the receipt, and keeps model_written true
through approval and export. The keyless offline path stays deterministic
and explicitly labeled deterministic_fallback.
"""
import io
import json
from unittest.mock import patch

from sqlalchemy import text

from backend import model_admission as ma

FIXED = ma.RESERVATION_USD_MICROS
NOTE = 'I built this wallet for my commute.'
POST_LINES = ['Hello Full-grain leather, shop now!', 'Hello $49, learn more.']
EMAIL_LINES = ['Hi Full-grain leather, see details.', 'Hi $49, tap the link.']


def _grant(db, micros):
    with db.begin() as connection:
        connection.execute(
            text("UPDATE model_budget SET remaining_micros=:n WHERE id='global'"), {'n': micros})


def _completion(raw, usage):
    return io.BytesIO(json.dumps(
        {'choices': [{'message': {'content': json.dumps(raw)}, 'finish_reason': 'stop'}],
         'usage': dict(usage)}).encode())


def _live_transport(request, timeout=None):
    body = json.loads(request.data)
    required = set(body['response_format']['json_schema']['schema']['required'])
    if required == {'facts_used', 'risks'}:
        return _completion({'facts_used': [], 'risks': []},
                           {'prompt_tokens': 10, 'completion_tokens': 4, 'total_tokens': 14})
    if required == {'claims', 'post_lines', 'email_lines'}:
        return _completion({'claims': ['Full-grain leather', '$49'],
                            'post_lines': list(POST_LINES),
                            'email_lines': list(EMAIL_LINES)},
                           {'prompt_tokens': 20, 'completion_tokens': 8, 'total_tokens': 28})
    return _completion({'claims': []},
                       {'prompt_tokens': 6, 'completion_tokens': 2, 'total_tokens': 8})


def _product_facts():
    return {'material': {'value': 'Full-grain leather', 'confirmed': True, 'source': 'owner'},
            'price': {'value': '$49', 'confirmed': True, 'source': 'owner'},
            'founder_note': {'value': NOTE, 'confirmed': True, 'source': 'owner'}}


def _reset_ledger(test_engine):
    with test_engine.begin() as connection:
        connection.execute(text('TRUNCATE model_calls'))
        connection.execute(text("UPDATE model_budget SET remaining_micros=0 WHERE id='global'"))


def test_live_mocked_run_produces_distinct_model_copy(client, test_engine, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_WONDER_MODEL', raising=False)
    _reset_ledger(test_engine)
    _grant(test_engine, FIXED * 3)
    with patch('launchcrew.spark.urlopen', side_effect=_live_transport) as transport:
        response = client.post('/api/runs', json={
            'idea': 'Full-grain leather wallet launch', 'agent_name': 'Maker',
            'checker_profile': 'standard', 'product_facts': _product_facts()})
    assert response.status_code == 201
    assert transport.call_count == 3
    receipt = response.json()
    run_id = receipt['run_id']
    joined = 'Full-grain leather. $49.'
    v2 = receipt['maker_draft_v2']
    assert v2['post'] != v2['email']
    assert v2['post'] == ' '.join(POST_LINES)
    assert v2['email'] == '\n'.join(EMAIL_LINES)
    assert v2['post'] != joined
    assert v2['email'] != joined
    assert v2['claims'] == ['Full-grain leather', '$49']
    assert v2['draft_origin'] == 'model_safe'
    assert v2['model_written'] is True
    assert v2['model_used'] == 'muse-spark-1.3'
    assert receipt['maker_draft_v1']['model_written'] is True
    assert receipt['checker_v1']['blocked_count'] == 0
    assert receipt['checker_v2']['blocked_count'] == 0
    usage = receipt['model_usage']
    assert usage['model_used'] == 'muse-spark-1.3'
    assert usage['spark_calls'] == 3
    assert usage['spark_mode'] == 'spark'
    assert usage['token_counts'] == {'prompt_tokens': 36, 'completion_tokens': 14,
                                     'total_tokens': 50}
    assert usage['tokens_known'] is True
    assert isinstance(usage['latency_ms'], (int, float))
    assert usage['latency_ms'] >= 0
    variant = receipt['product_facts']['draft_variant']
    assert variant is not None
    assert NOTE in variant['post'] or NOTE in variant['email']
    assert NOTE not in v2['post']
    assert NOTE not in v2['email']
    assert 'offline-fixture' not in json.dumps(receipt)
    approved = client.post('/api/runs/%s/approve' % run_id, json={})
    assert approved.status_code == 200
    exported = client.post('/api/runs/%s/export' % run_id, json={})
    assert exported.status_code == 200
    pack = exported.json()
    assert pack['exported_draft']['model_written'] is True
    assert pack['exported_draft']['post'] == v2['post']
    assert pack['exported_draft']['email'] == v2['email']
    _reset_ledger(test_engine)


def test_offline_fallback_stays_deterministic_and_labeled(client, test_engine, monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)
    monkeypatch.delenv('META_MODEL', raising=False)
    monkeypatch.delenv('META_API_BASE_URL', raising=False)
    monkeypatch.delenv('META_WONDER_MODEL', raising=False)
    _reset_ledger(test_engine)
    with patch('launchcrew.spark.urlopen',
               side_effect=AssertionError('no transport offline')) as transport:
        response = client.post('/api/runs', json={
            'idea': 'Full-grain leather wallet launch', 'agent_name': 'Maker',
            'checker_profile': 'standard', 'product_facts': _product_facts()})
    assert response.status_code == 201
    transport.assert_not_called()
    receipt = response.json()
    usage = receipt['model_usage']
    assert usage['spark_calls'] == 0
    assert usage['spark_mode'] == 'deterministic_fallback'
    assert usage['mode'] == 'deterministic_fallback'
    assert usage['model_used'] == 'none'
    assert usage['token_counts'] == {'prompt_tokens': 0, 'completion_tokens': 0,
                                     'total_tokens': 0}
    assert isinstance(usage['latency_ms'], (int, float))
    for key in ('maker_draft_v1', 'maker_draft_v2'):
        draft = receipt[key]
        assert draft['draft_origin'] == 'deterministic_fallback'
        assert draft['model_written'] is False
        assert draft['model_used'] == 'none'
    assert receipt['maker_draft_v2']['post'] == receipt['maker_draft_v2']['email']
    variant = receipt['product_facts']['draft_variant']
    assert variant is not None
    assert NOTE in variant['post'] or NOTE in variant['email']
    _reset_ledger(test_engine)
