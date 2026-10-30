"""Campaign infrastructure-failure atomicity on real Postgres.

Proves the deferred atomic commit lifecycle: no campaign row, day row, or
run row is visible during generation, so concurrent photo or memory work
cannot attach to an uncommitted day. A later-day infrastructure failure
rolls the single commit transaction back with no partial campaign and no
deletion of existing user work. Uses only the existing test_engine and
client fixtures. Timing uses a stage gate plus threading events, never
sleeps for correctness, and no database transaction is held across model
calls.
"""
import threading
from unittest.mock import patch

import pytest
from sqlalchemy import text

from backend import store
from launchcrew import run

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def _new_run(client):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    return response.json()


def test_campaign_generation_hides_partial_until_commit(client):
    release = threading.Event()
    entered = threading.Event()
    original = run.run_pipeline
    gated_calls = {'count': 0}

    def gated(*args, **kwargs):
        gated_calls['count'] += 1

        def gate(stage):
            if stage == 'maker_draft_v1' and gated_calls['count'] == 1:
                entered.set()
                assert release.wait(timeout=30.0)

        kwargs['stage_gate'] = gate
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    results = []
    errors = []

    def requester():
        try:
            results.append(client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'}))
        except Exception as error:  # pragma: no cover - thread transport
            errors.append(error)

    with patch('launchcrew.run.run_pipeline', side_effect=gated):
        thread = threading.Thread(target=requester)
        thread.start()
        try:
            assert entered.wait(timeout=30.0)
            assert client.get('/api/campaigns').json() == []
            assert client.get('/api/queue').json() == []
            with store.connect() as db:
                assert db.execute(text('SELECT count(*) FROM campaigns')).scalar() == 0
                assert db.execute(text('SELECT count(*) FROM campaign_days')).scalar() == 0
                assert db.execute(text('SELECT count(*) FROM runs')).scalar() == 0
            release.set()
            thread.join(timeout=60.0)
        finally:
            if thread.is_alive():
                release.set()
                thread.join(timeout=5.0)
    assert errors == []
    assert len(results) == 1
    assert results[0].status_code == 201, results[0].text
    campaign = results[0].json()
    assert [day['day'] for day in campaign['days']] == [1, 2, 3, 4, 5, 6, 7]
    assert len({day['run_id'] for day in campaign['days']}) == 7
    assert len(client.get('/api/queue').json()) == 7


def test_campaign_late_infra_failure_rolls_back_and_preserves_user_work(client):
    prior = _new_run(client)
    prior_id = prior['run_id']
    assert client.post('/api/runs/%s/approve' % prior_id, json={}).status_code == 200
    learned = client.post('/api/memory/from-run/%s' % prior_id, json={'kind': 'approval_example'})
    assert learned.status_code == 201, learned.text
    learned_id = learned.json()['id']
    assert client.post('/api/runs/%s/export' % prior_id, json={}).status_code == 200

    release = threading.Event()
    entered = threading.Event()
    original = run.run_pipeline
    gated_calls = {'count': 0}

    def gated(*args, **kwargs):
        gated_calls['count'] += 1

        def gate(stage):
            if stage == 'maker_draft_v1' and gated_calls['count'] == 1:
                entered.set()
                assert release.wait(timeout=30.0)

        kwargs['stage_gate'] = gate
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    real_audit = store.audit
    audit_calls = {'count': 0}

    def failing_audit(db, run_id, action, actor='demo_placeholder', workspace_id=None):
        audit_calls['count'] += 1
        if audit_calls['count'] == 3:
            raise ValueError('demo late infra failure')
        return real_audit(db, run_id, action, actor, workspace_id)

    results = []
    errors = []

    def requester():
        try:
            results.append(client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'}))
        except Exception as error:  # pragma: no cover - thread transport
            errors.append(error)

    with patch('launchcrew.run.run_pipeline', side_effect=gated):
        with patch('backend.store.audit', side_effect=failing_audit):
            thread = threading.Thread(target=requester)
            thread.start()
            try:
                assert entered.wait(timeout=30.0)
                assert client.get('/api/campaigns').json() == []
                queue = client.get('/api/queue').json()
                assert [item['run_id'] for item in queue] == [prior_id]
                release.set()
                thread.join(timeout=60.0)
            finally:
                if thread.is_alive():
                    release.set()
                    thread.join(timeout=5.0)
    assert errors == []
    assert len(results) == 1
    assert results[0].status_code == 422, results[0].text
    assert client.get('/api/campaigns').json() == []
    queue = client.get('/api/queue').json()
    assert [item['run_id'] for item in queue] == [prior_id]
    assert client.get('/api/memory/%s' % learned_id).status_code == 200
    assert len(client.get('/api/memory').json()) == 1
    assert client.post('/api/runs/%s/export' % prior_id, json={}).status_code == 200
    assert client.post('/api/campaigns/missing/days/1/approve', json={}).status_code == 404
    assert client.post('/api/campaigns/missing/days/1/export', json={}).status_code == 404
    with store.connect() as db:
        assert db.execute(text('SELECT count(*) FROM campaigns')).scalar() == 0
        assert db.execute(text('SELECT count(*) FROM campaign_days')).scalar() == 0
        assert db.execute(text('SELECT count(*) FROM runs')).scalar() == 1
        assert db.execute(text('SELECT count(*) FROM memory_items')).scalar() == 1
        assert db.execute(text('SELECT count(*) FROM approvals')).scalar() == 1
        assert db.execute(text('SELECT count(*) FROM run_steps')).scalar() == 0
        assert db.execute(text('SELECT count(*) FROM sam_calls')).scalar() == 0
