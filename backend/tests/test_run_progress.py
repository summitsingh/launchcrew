"""Incremental stage receipts for async runs.

Controlled timing proofs only: no live model calls, no credentials. The
barrier tests below prove ordering through a stage gate, not live Meta
proof. Keyless deterministic fallback keeps every stage fast and local.
"""
import time
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from backend import run_jobs
from launchcrew import run


def parse_instant(value):
    """Parse an ISO-8601 timestamp as an aware instant, keeping offsets."""
    text = str(value)
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


@pytest.fixture(autouse=True)
def no_model_key(monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)


def wait_until(client, run_id, predicate, timeout=30.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        steps = client.get(f'/api/runs/{run_id}/steps')
        assert steps.status_code == 200, steps.text
        receipt = client.get(f'/api/runs/{run_id}/receipt')
        assert receipt.status_code == 200, receipt.text
        last = (steps.json(), receipt.json())
        if predicate(*last):
            return last
        time.sleep(0.05)
    raise AssertionError('Timed out waiting for run ' + run_id + ': ' + repr(last))


def gated_start(monkeypatch, gate):
    original = run_jobs.start_async_run

    def started(run_id, *args, **kwargs):
        kwargs['stage_gate'] = gate
        return original(run_id, *args, **kwargs)

    monkeypatch.setattr(run_jobs, 'start_async_run', started)


def create_async(client):
    response = client.post('/api/runs/async', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body['status'] == 'running'
    assert body['receipt']['status'] == 'running'
    assert body['receipt']['approval_state'] == 'pending_approval'
    assert body['receipt']['maker_draft_v2'] is None
    return body['run_id']


def completed_stages(steps):
    return [row['stage'] for row in steps['steps'] if row['state'] == 'completed']


def test_first_completion_arrives_before_later_stage_released(client, monkeypatch):
    """Scout completion is observable while Maker is still gated."""
    import threading
    release = threading.Event()

    def gate(stage):
        if stage == 'maker_draft_v1' and not release.is_set():
            assert release.wait(timeout=30.0), 'Maker gate was never released'

    gated_start(monkeypatch, gate)
    run_id = create_async(client)

    steps, receipt = wait_until(
        client, run_id,
        lambda steps, receipt: 'scout' in completed_stages(steps) and receipt['status'] == 'running')
    assert 'maker_draft_v1' not in completed_stages(steps)
    assert receipt['status'] == 'running'
    assert receipt['maker_draft_v2'] is None
    scout_rows = [row for row in steps['steps'] if row['stage'] == 'scout' and row['state'] == 'completed']
    assert len(scout_rows) == 1
    assert scout_rows[0]['observed_at']
    assert scout_rows[0]['profile'] == 'Scout'
    assert scout_rows[0]['evidence']['facts_used'] >= 1

    # Mutations stay refused while the run is in flight.
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 409
    assert client.post(f'/api/runs/{run_id}/revise',
                       json={'post': 'x', 'email': 'y', 'base_revision': 0}).status_code == 409
    assert client.post(f'/api/runs/{run_id}/export', json={}).status_code == 409

    release.set()
    steps, receipt = wait_until(
        client, run_id, lambda steps, receipt: receipt['status'] == 'completed')

    # Final receipt matches the observed step order, timestamps, and profiles.
    assert completed_stages(steps) == ['accepted', 'deterministic_checks', 'scout',
                                       'maker_draft_v1', 'checker_v1',
                                       'maker_draft_v2', 'checker_v2', 'receipt']
    assert steps['steps'][-1]['evidence'].get('stored') is True
    # Started rows exist for every pipeline stage: the stored history is
    # not a finished-only list.
    started = [row['stage'] for row in steps['steps'] if row['state'] == 'started']
    for stage in ['deterministic_checks', 'scout', 'maker_draft_v1', 'checker_v1',
                  'maker_draft_v2', 'checker_v2', 'receipt']:
        assert stage in started
    # Each completed stage shares one clock reading and profile between
    # its stored step row and the receipt audit entry for the same
    # observed completion. The terminal stored row is the commit
    # observation, distinct from the prepared receipt audit entry.
    by_stage = {}
    for row in steps['steps']:
        if row['state'] == 'completed':
            by_stage.setdefault(row['stage'], row)
    logged = {entry['step']: entry for entry in receipt['audit']['event_log']}
    for stage in ['deterministic_checks', 'scout', 'maker_draft_v1', 'checker_v1',
                  'maker_draft_v2', 'checker_v2']:
        # Same observed completion instant, portable across database
        # TimeZone settings: Postgres renders timestamptz in the session
        # zone, so compare aware instants, not raw strings.
        stored = parse_instant(by_stage[stage]['observed_at'])
        prepared = parse_instant(logged[stage]['timestamp'])
        assert stored == prepared
        assert stored.microsecond == prepared.microsecond
        assert by_stage[stage]['profile'] == logged[stage]['profile']
        assert by_stage[stage]['profile']
    assert 'receipt' in logged
    assert by_stage['receipt']['evidence'].get('stored') is True
    # Stored rows keep pipeline order through unique sequence ids, valid
    # timezone-aware UTC observed times, and nondecreasing instants: two
    # legitimate quick events may share one millisecond, so uniqueness of
    # raw strings or millisecond instants is never required. Ties are
    # ordered by seq, never by the clock alone.
    seqs = [row['seq'] for row in steps['steps']]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    observed = [row['observed_at'] for row in steps['steps']]
    assert observed
    for value in observed:
        assert isinstance(value, str) and value
        parsed = parse_instant(value)
        assert parsed.tzinfo is not None
        assert str(value).endswith('+00:00')
    instants = [parse_instant(value) for value in observed]
    assert all(later >= earlier for earlier, later in zip(instants, instants[1:]))
    assert receipt['stage_bindings'] == {'scout': 'Scout', 'maker': 'Maker', 'checker': 'Checker'}
    assert receipt['checker_v2']['blocked_count'] == 0
    # Completion was claimed only with the stored receipt: the terminal
    # step row and the completed receipt land in one transaction.
    assert receipt['approval_state'] == 'pending_approval'


def test_failure_retains_completed_steps_and_blocks_approval_export(client, monkeypatch):
    def gate(stage):
        if stage == 'checker_v1':
            raise RuntimeError('Simulated checker outage')

    gated_start(monkeypatch, gate)
    run_id = create_async(client)
    steps, receipt = wait_until(
        client, run_id, lambda steps, receipt: receipt['status'] == 'failed')

    assert receipt['error_type'] == 'RuntimeError'
    assert set(receipt['completed_steps']) >= {'scout', 'maker_draft_v1'}
    assert receipt['audit']['stopped_reason'] == 'checker_v1'
    failed_rows = [row for row in steps['steps'] if row['state'] == 'failed']
    assert len(failed_rows) == 1 and failed_rows[0]['stage'] == 'checker_v1'
    assert failed_rows[0]['evidence'].get('stored') is True
    # The stored failure is the pipeline's original failed receipt, not a
    # synthetic rebuild: it keeps model usage, stage bindings, and the
    # actual stopped stage, with no completed claim anywhere.
    assert receipt['model_usage'] is not None
    assert receipt['stage_bindings'] == {'scout': 'Scout', 'maker': 'Maker', 'checker': 'Checker'}
    assert receipt['status'] == 'failed'
    assert [row for row in steps['steps']
            if row['stage'] == 'receipt' and row['state'] == 'completed'] == []
    assert completed_stages(steps) == ['accepted', 'deterministic_checks', 'scout', 'maker_draft_v1']
    from sqlalchemy import text
    from backend import store
    with store.connect() as db:
        actions = [row[0] for row in db.execute(
            text('SELECT action FROM audit WHERE run_id=:id ORDER BY id'), {'id': run_id})]
    assert 'run_failed' in actions
    assert 'run_completed' not in actions
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code in (409, 422)
    assert client.post(f'/api/runs/{run_id}/export', json={}).status_code == 422
    assert client.post(f'/api/runs/{run_id}/revise',
                       json={'post': 'x', 'email': 'y', 'base_revision': 0}).status_code == 422


def test_recovery_polling_causes_no_duplicate_pipeline_work(client, monkeypatch):
    calls = []
    original = run.run_pipeline

    def counted(*args, **kwargs):
        calls.append(1)
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    run_id = None
    with patch('launchcrew.run.run_pipeline', side_effect=counted):
        response = client.post('/api/runs/async', json={'idea': IDEA, 'agent_name': 'Maker'})
        assert response.status_code == 202, response.text
        run_id = response.json()['run_id']
        # Simulate disconnects and reconnects: repeated fresh reads of
        # steps and receipt from independent clients.
        from fastapi.testclient import TestClient
        from backend.app import app
        with TestClient(app, base_url='https://testserver') as second:
            for _ in range(20):
                assert second.get(f'/api/runs/{run_id}/steps').status_code == 200
                assert second.get(f'/api/runs/{run_id}/receipt').status_code == 200
                assert client.get(f'/api/runs/{run_id}/steps').status_code == 200
            wait_until(client, run_id, lambda steps, receipt: receipt['status'] == 'completed')
            for _ in range(10):
                assert second.get(f'/api/runs/{run_id}/steps').status_code == 200
                assert client.get(f'/api/runs/{run_id}/receipt').status_code == 200
    assert len(calls) == 1


def test_unknown_run_steps_are_not_found(client):
    assert client.get('/api/runs/run_missing/steps').status_code == 404


def test_observed_at_is_canonical_utc_across_zone_offsets():
    """Step timestamps stay comparable when the database zone changes.

    A Chicago rendering (-05:00) and a UTC rendering (+00:00) of one
    instant must parse to the same aware instant, and the API canonical
    form must always be UTC with its zone retained.
    """
    from datetime import timedelta
    from backend.app import canonical_observed_at

    chicago = timezone(timedelta(hours=-5))
    same = datetime(2026, 10, 28, 5, 18, 37, 890757, tzinfo=chicago)
    assert parse_instant('2026-10-28T05:18:37.890757-05:00') == parse_instant('2026-10-28T10:18:37.890757+00:00')
    assert parse_instant(canonical_observed_at(same)) == same
    assert str(canonical_observed_at(same)).endswith('+00:00')
    assert canonical_observed_at(None) is None


def test_same_millisecond_events_keep_sequence_order():
    """Two ordered events in one millisecond stay ordered without unique instants.

    Raw timestamp strings differ at full microsecond precision while the
    millisecond clock reading ties: the shared millisecond is legitimate,
    and pipeline order comes from seq, never from forcing the clock apart.
    """
    first = '2026-10-28T10:18:37.890757+00:00'
    second = '2026-10-28T10:18:37.890900+00:00'
    assert first != second
    earlier, later = parse_instant(first), parse_instant(second)
    assert earlier.tzinfo is not None and later.tzinfo is not None
    assert earlier < later
    assert earlier.astimezone(timezone.utc).isoformat() == first
    # The millisecond reading ties: Date-style millisecond truncation
    # cannot tell these legitimate events apart.
    assert int(earlier.timestamp() * 1000) == int(later.timestamp() * 1000)
    assert earlier.microsecond != later.microsecond
    # Order is carried by seq even when the millisecond clock ties.
    rows = [{'seq': 0, 'observed_at': first}, {'seq': 1, 'observed_at': second}]
    seqs = [row['seq'] for row in rows]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(rows)
    instants = [parse_instant(row['observed_at']) for row in rows]
    assert all(later >= earlier for earlier, later in zip(instants, instants[1:]))


def test_accept_journal_failure_rolls_back_run_and_starts_no_worker(client, monkeypatch):
    """An unjournaled accept stays unconfirmed with a bounded response."""
    from backend import store
    from sqlalchemy import text

    sentinel = 'SENTINEL_PRIVATE_IDEA_do_not_echo_9f3a'
    real_record = run_jobs.record_step_in

    def failing_record(db, run_id, stage, *args, **kwargs):
        if stage == 'accepted':
            raise run_jobs.StepJournalError('OperationalError')
        return real_record(db, run_id, stage, *args, **kwargs)

    monkeypatch.setattr(run_jobs, 'record_step_in', failing_record)
    before = set(run_jobs._workers)
    response = client.post('/api/runs/async', json={'idea': IDEA + ' ' + sentinel, 'agent_name': 'Maker'})
    assert response.status_code == 503, response.text
    body = response.json()
    assert body == {'detail': 'Run acceptance unconfirmed; retry with a new request'}
    lowered = response.text.lower()
    assert sentinel.lower() not in lowered
    assert 'select' not in lowered and 'insert' not in lowered
    assert 'traceback' not in lowered and 'operationalerror' not in lowered
    with store.connect() as db:
        assert db.execute(text('SELECT COUNT(*) FROM runs')).scalar() == 0
        assert db.execute(text('SELECT COUNT(*) FROM run_steps')).scalar() == 0
        assert db.execute(text("SELECT COUNT(*) FROM audit WHERE action='run_created'")).scalar() == 0
    assert set(run_jobs._workers) == before


def test_step_journal_loss_fails_honestly_without_further_model_work(client, monkeypatch):
    """Lost journal rows stop the pipeline; no completed claim follows."""
    from launchcrew import run as core_run
    from sqlalchemy import text
    from backend import store

    calls = []
    original_pipeline = core_run.run_pipeline

    def counted(*args, **kwargs):
        calls.append(1)
        return original_pipeline(*args, **kwargs)

    real_record = run_jobs.record_step
    seen_stages = []

    def failing_record(run_id, stage, state, *args, **kwargs):
        seen_stages.append((stage, state))
        if stage == 'scout' and state == 'started':
            raise run_jobs.StepJournalError('OperationalError')
        return real_record(run_id, stage, state, *args, **kwargs)

    monkeypatch.setattr(run_jobs, 'record_step', failing_record)
    monkeypatch.setattr(core_run, 'run_pipeline', counted)
    run_id = create_async(client)

    def failed_and_journaled(steps, receipt):
        if receipt['status'] != 'failed':
            return False
        failed = [row for row in steps['steps']
                  if row['state'] == 'failed' and row['stage'] == 'scout']
        return len(failed) == 1

    steps, receipt = wait_until(client, run_id, failed_and_journaled)
    assert len(calls) == 1
    assert receipt['error_type'] == 'StepJournalError'
    assert receipt['audit']['stopped_reason'] == 'scout'
    failed_rows = [row for row in steps['steps'] if row['state'] == 'failed']
    assert len(failed_rows) == 1 and failed_rows[0]['stage'] == 'scout'
    assert 'maker_draft_v1' not in completed_stages(steps)
    assert [row for row in steps['steps']
            if row['stage'] == 'receipt' and row['state'] == 'completed'] == []
    with store.connect() as db:
        actions = [row[0] for row in db.execute(
            text('SELECT action FROM audit WHERE run_id=:id ORDER BY id'), {'id': run_id})]
    assert 'run_failed' in actions
    assert 'run_completed' not in actions
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code in (409, 422)
    assert client.post(f'/api/runs/{run_id}/export', json={}).status_code == 422


def test_terminal_persist_failure_leaves_stored_state_unconfirmed(client, monkeypatch):
    """A failed finalize never overwrites stored truth with a synthetic failure."""
    import threading
    from sqlalchemy import text
    from backend import store

    hook_calls = []
    real_hook = threading.excepthook
    hooked = []
    threading.excepthook = hooked.append

    def failing_finalize(run_id, receipt, maker_name, actor, workspace_id=None):
        hook_calls.append(run_id)
        raise RuntimeError('Simulated terminal commit loss with receipt Richards')

    monkeypatch.setattr(run_jobs, '_finalize_success', failing_finalize)
    try:
        run_id = create_async(client)
        steps, receipt = wait_until(
            client, run_id,
            lambda steps, receipt: not run_jobs.is_worker_live(run_id) and receipt['status'] == 'running',
            timeout=30.0)
    finally:
        threading.excepthook = real_hook
    # No raw thread traceback escaped, and the stored receipt was left as
    # the running pending receipt: readers recover actual DB truth.
    assert hooked == []
    assert hook_calls == [run_id]
    assert receipt['status'] == 'running'
    assert receipt['maker_draft_v2'] is None
    assert [row for row in steps['steps']
            if row['stage'] == 'receipt' and row['state'] == 'completed'] == []
    with store.connect() as db:
        actions = [row[0] for row in db.execute(
            text('SELECT action FROM audit WHERE run_id=:id ORDER BY id'), {'id': run_id})]
        stored = db.execute(text('SELECT receipt FROM runs WHERE id=:id'),
                            {'id': run_id}).fetchone()[0]
    assert stored['status'] == 'running'
    assert 'run_completed' not in actions
    assert 'run_failed' not in actions
    assert any(action.startswith('run_unconfirmed:RuntimeError') for action in actions)
    assert 'Richards' not in ' '.join(actions)


def test_concurrent_starters_claim_at_most_one_live_worker(client, monkeypatch):
    """Concurrent starters serialize: exactly one worker starts per run id."""
    import threading
    from backend import store
    from sqlalchemy import text

    calls = []
    release = threading.Event()

    def stub_work(**kwargs):
        calls.append(1)
        assert release.wait(timeout=30.0)
        run_jobs.mark_done(kwargs['run_id'])

    monkeypatch.setattr(run_jobs, '_work', stub_work)
    with store.connect() as db:
        assert db.execute(text('SELECT COUNT(*) FROM runs')).scalar() == 0
    run_id = 'run_raceproof'
    results = []
    errors = []

    def starter():
        try:
            results.append(run_jobs.start_async_run(
                run_id, IDEA, {}, False, [], 'standard', {'name': 'Scout'},
                {'name': 'Maker'}, {'name': 'Checker'}, 'Maker', 'tester'))
        except Exception as error:  # pragma: no cover - serialized start never raises
            errors.append(error)

    threads = [threading.Thread(target=starter) for _ in range(8)]
    for thread in threads:
        thread.start()
    deadline = time.time() + 30.0
    while time.time() < deadline and results.count(True) == 0:
        time.sleep(0.01)
    while time.time() < deadline and len(results) < len(threads):
        time.sleep(0.01)
    release.set()
    for thread in threads:
        thread.join(timeout=30.0)
    assert errors == []
    assert results.count(True) == 1
    assert len(results) == len(threads)
    assert calls == [1]
    deadline = time.time() + 30.0
    while time.time() < deadline and run_jobs.is_worker_live(run_id):
        time.sleep(0.01)
    assert not run_jobs.is_worker_live(run_id)
