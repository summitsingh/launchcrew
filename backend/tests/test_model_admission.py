"""Durable global model budget and ledger on real Postgres.

Uses only the existing disposable test_engine fixture. No provider HTTP
is performed anywhere in this file. The singleton and ledger are reset
here before each test, independent of other fixtures.
"""
import hashlib
import threading

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend import model_admission as ma

FIXED = ma.RESERVATION_USD_MICROS


@pytest.fixture(autouse=True)
def reset_model_ledger(test_engine):
    with test_engine.begin() as connection:
        connection.execute(text('TRUNCATE model_calls'))
        connection.execute(text("UPDATE model_budget SET remaining_micros=0 WHERE id='global'"))
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


def _digest(tag):
    return hashlib.sha256(tag.encode()).hexdigest()


def _reserve(db, run='run1', stage='Scout', attempt='a1', tag='req1', **overrides):
    params = {'run_id': run, 'stage': stage, 'attempt_id': attempt,
              'request_digest': _digest(tag), 'model': ma.MODEL,
              'max_completion_tokens': 2048, 'n': 1, 'request_bytes_len': 1024}
    params.update(overrides)
    return ma.reserve_model_call(db, **params)


def test_migration_zero_default_and_singleton_guards(test_engine):
    assert _budget(test_engine) == 0
    assert ma.budget_remaining_micros(test_engine) == 0
    with test_engine.begin() as connection:
        ids = connection.execute(text('SELECT id FROM model_budget')).scalars().all()
    assert ids == ['global']
    with pytest.raises(IntegrityError):
        with test_engine.begin() as connection:
            connection.execute(text("UPDATE model_budget SET remaining_micros=-1 WHERE id='global'"))
    assert _budget(test_engine) == 0
    with pytest.raises(IntegrityError):
        with test_engine.begin() as connection:
            connection.execute(
                text("INSERT INTO model_budget(id, remaining_micros) VALUES ('other', 100)"))
    assert _budget(test_engine) == 0


def test_zero_and_partial_budget_denies_without_ledger(test_engine):
    for balance in (0, 1, FIXED - 1):
        _grant(test_engine, balance)
        with pytest.raises(ma.AdmissionDenied):
            _reserve(test_engine)
        assert _budget(test_engine) == balance
        assert _count(test_engine) == 0


def test_one_successful_reserve_debits_fixed_reservation(test_engine):
    _grant(test_engine, FIXED * 2)
    row = _reserve(test_engine)
    assert row['is_owner'] is True
    assert row['status'] == 'admitted'
    assert row['model'] == 'muse-spark-1.3'
    assert row['reservation_micros'] == FIXED == 4_000_000
    assert row['request_digest'] == _digest('req1')
    assert row['outcome'] is None
    assert row['prompt_tokens'] is None
    assert _budget(test_engine) == FIXED
    assert _count(test_engine) == 1
    fetched = ma.get_call_by_identity(test_engine, 'run1', 'Scout', 'a1')
    assert fetched is not None and fetched['id'] == row['id'] and fetched['is_owner'] is False


def test_duplicate_same_key_replays_without_spend_or_resend(test_engine):
    _grant(test_engine, FIXED * 2)
    first = _reserve(test_engine)
    second = _reserve(test_engine)
    assert second['id'] == first['id']
    assert second['is_owner'] is False
    assert second['status'] == 'admitted'
    assert _budget(test_engine) == FIXED
    assert _count(test_engine) == 1


def test_digest_mismatch_refused_and_original_kept(test_engine):
    _grant(test_engine, FIXED * 2)
    first = _reserve(test_engine, tag='req1')
    with pytest.raises(ma.AdmissionConflict):
        _reserve(test_engine, tag='req2')
    assert _budget(test_engine) == FIXED
    assert _count(test_engine) == 1
    fetched = ma.get_call_by_identity(test_engine, 'run1', 'Scout', 'a1')
    assert fetched['request_digest'] == first['request_digest'] == _digest('req1')


def test_independent_attempts_each_debit_full_reservation(test_engine):
    _grant(test_engine, FIXED * 3)
    first = _reserve(test_engine, attempt='a1')
    second = _reserve(test_engine, attempt='a2', tag='req2')
    third = _reserve(test_engine, stage='Maker', attempt='a1', tag='req3')
    assert first['is_owner'] is True and second['is_owner'] is True and third['is_owner'] is True
    assert len({first['id'], second['id'], third['id']}) == 3
    assert _budget(test_engine) == 0
    assert _count(test_engine) == 3


def test_last_slot_concurrency_single_winner(test_engine):
    _grant(test_engine, FIXED)
    barrier = threading.Barrier(2)
    results = [None, None]

    def one(index, attempt, tag):
        try:
            barrier.wait(timeout=30)
            row = _reserve(test_engine, attempt=attempt, tag=tag)
            results[index] = ('ok', row['is_owner'], row['id'])
        except ma.AdmissionDenied:
            results[index] = ('denied',)
        except Exception as error:  # pragma: no cover - surfaced below
            results[index] = ('error', repr(error))

    threads = [threading.Thread(target=one, args=(0, 'a1', 'req1')),
               threading.Thread(target=one, args=(1, 'a2', 'req2'))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(kind for kind, *_ in results) == ['denied', 'ok']
    assert _budget(test_engine) == 0
    assert _count(test_engine) == 1


def test_concurrent_duplicate_same_key_single_owner(test_engine):
    _grant(test_engine, FIXED)
    barrier = threading.Barrier(2)
    results = [None, None]

    def one(index):
        try:
            barrier.wait(timeout=30)
            row = _reserve(test_engine)
            results[index] = ('ok', row['is_owner'], row['id'])
        except Exception as error:  # pragma: no cover - surfaced below
            results[index] = ('error', repr(error))

    threads = [threading.Thread(target=one, args=(index,)) for index in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert [kind for kind, *_ in results] == ['ok', 'ok']
    owners = sorted(row[1] for row in results)
    assert owners == [False, True]
    assert results[0][2] == results[1][2]
    assert _budget(test_engine) == 0
    assert _count(test_engine) == 1


def test_crash_restart_replay_stays_pending_without_resend(test_engine):
    _grant(test_engine, FIXED)
    first = _reserve(test_engine)
    assert first['is_owner'] is True
    replay = _reserve(test_engine)
    assert replay['id'] == first['id']
    assert replay['is_owner'] is False
    assert replay['status'] == 'admitted'
    assert _budget(test_engine) == 0
    fetched = ma.get_call_by_identity(test_engine, 'run1', 'Scout', 'a1')
    assert fetched['status'] == 'admitted' and fetched['is_owner'] is False


def test_failed_terminal_no_refund_or_resend(test_engine):
    _grant(test_engine, FIXED * 2)
    row = _reserve(test_engine)
    final = ma.finalize_model_call(test_engine, row['id'], status='failed_terminal',
                                   outcome='transport_error',
                                   prompt_tokens=10, completion_tokens=20, total_tokens=30)
    assert final['is_owner'] is False
    assert final['status'] == 'failed_terminal'
    assert final['outcome'] == 'transport_error'
    assert (final['prompt_tokens'], final['completion_tokens'], final['total_tokens']) == (10, 20, 30)
    assert _budget(test_engine) == FIXED
    replay = _reserve(test_engine)
    assert replay['is_owner'] is False and replay['status'] == 'failed_terminal'
    assert _budget(test_engine) == FIXED
    again = ma.finalize_model_call(test_engine, row['id'], status='succeeded', outcome='ok')
    assert again['status'] == 'failed_terminal' and again['outcome'] == 'transport_error'
    assert again['is_owner'] is False
    assert _budget(test_engine) == FIXED


def test_ambiguous_terminal_no_refund_or_resend(test_engine):
    _grant(test_engine, FIXED)
    row = _reserve(test_engine)
    final = ma.finalize_model_call(test_engine, row['id'], status='ambiguous_terminal',
                                   outcome='ambiguous:read_failed')
    assert final['is_owner'] is False and final['status'] == 'ambiguous_terminal'
    assert _budget(test_engine) == 0
    replay = _reserve(test_engine)
    assert replay['is_owner'] is False and replay['status'] == 'ambiguous_terminal'
    with pytest.raises(ma.AdmissionDenied):
        ma.finalize_model_call(test_engine, row['id'], status='admitted')
    _grant(test_engine, FIXED)
    other = _reserve(test_engine, attempt='a2', tag='req2')
    assert other['is_owner'] is True and other['status'] == 'admitted'
    assert _budget(test_engine) == 0


@pytest.mark.parametrize('override', [
    {'model': 'muse-spark-1.3-contributor'},
    {'model': 'custom-future-model-9'},
    {'model': ''},
    {'max_completion_tokens': 2047},
    {'max_completion_tokens': 2049},
    {'max_completion_tokens': '2048'},
    {'max_completion_tokens': True},
    {'n': 0},
    {'n': 2},
    {'request_bytes_len': 32 * 1024 + 1},
    {'request_bytes_len': -1},
    {'request_bytes_len': '1024'},
    {'request_digest': 'not-hex'},
    {'request_digest': 'abc'},
    {'request_digest': ''},
    {'run_id': ''},
    {'stage': ''},
    {'attempt_id': ''},
], ids=[
    'contributor-model', 'custom-model', 'empty-model',
    'tokens-low', 'tokens-high', 'tokens-str', 'tokens-bool',
    'n-zero', 'n-two', 'body-oversize', 'body-negative', 'body-str',
    'digest-nonhex', 'digest-short', 'digest-empty',
    'run-empty', 'stage-empty', 'attempt-empty',
])
def test_invalid_bound_or_model_denied_before_debit(test_engine, override):
    _grant(test_engine, FIXED * 2)
    before = _budget(test_engine)
    with pytest.raises(ma.AdmissionDenied):
        _reserve(test_engine, **override)
    assert _budget(test_engine) == before == FIXED * 2
    assert _count(test_engine) == 0
    assert 'offline-fixture' not in str(override)


def test_finalize_sanitization_and_never_reauthorizes(test_engine):
    _grant(test_engine, FIXED)
    row = _reserve(test_engine)
    for bad_outcome in ('raw response body with spaces', 'prompt: tell me', 'a' * 65,
                        'bad\nnewline', 'bad;semicolon', 123):
        with pytest.raises(ma.AdmissionDenied):
            ma.finalize_model_call(test_engine, row['id'], status='succeeded', outcome=bad_outcome)
    for bad_usage in (-1, True, '10', 10_000_001):
        with pytest.raises(ma.AdmissionDenied):
            ma.finalize_model_call(test_engine, row['id'], status='succeeded',
                                   prompt_tokens=bad_usage)
    for bad_status in ('admitted', 'pending', '', None):
        with pytest.raises(ma.AdmissionDenied):
            ma.finalize_model_call(test_engine, row['id'], status=bad_status)
    with pytest.raises(ma.AdmissionDenied):
        ma.finalize_model_call(test_engine, 'mc_nonexistent', status='succeeded')
    assert ma.get_call_by_identity(test_engine, 'run1', 'Scout', 'a1')['status'] == 'admitted'
    assert _budget(test_engine) == 0
    final = ma.finalize_model_call(test_engine, row['id'], status='succeeded', outcome='ok',
                                   prompt_tokens=5, completion_tokens=7, total_tokens=12)
    assert final['is_owner'] is False and final['status'] == 'succeeded'
    replay = _reserve(test_engine)
    assert replay['is_owner'] is False and replay['status'] == 'succeeded'
    assert _budget(test_engine) == 0


def test_request_digest_helper_enforces_bound_without_echo():
    digest = ma.digest_request_bytes(b'{"model":"muse-spark-1.3"}')
    assert digest == hashlib.sha256(b'{"model":"muse-spark-1.3"}').hexdigest()
    with pytest.raises(ma.AdmissionDenied) as excinfo:
        ma.digest_request_bytes(b'x' * (32 * 1024 + 1))
    assert 'x' * 16 not in str(excinfo.value)
