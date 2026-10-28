"""Incremental stage receipts for async runs.

Controlled timing proofs only: no live model calls, no credentials. The
barrier tests below prove ordering through a stage gate, not live Meta
proof. Keyless deterministic fallback keeps every stage fast and local.
"""
import time
from unittest.mock import patch
import pytest
from backend import run_jobs
from launchcrew import run

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
    event_steps = [entry['step'] for entry in receipt['audit']['event_log']]
    for stage in ['scout', 'maker_draft_v1', 'checker_v1', 'maker_draft_v2', 'checker_v2', 'receipt']:
        assert stage in event_steps
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
