"""Background pipeline workers for async runs with incremental stage receipts.

One daemon thread per run id executes the real pipeline. Every stage
boundary the pipeline reaches is stored as a run_steps row in its own
short transaction, so no database lock is held across remote inference.
Terminal rows (receipt completed, or the failure row) are written in the
same short transaction that stores the final receipt, so terminal success
is never claimed before the database commit. Polls and reconnects are
read-only and never start work; each run id executes at most once.
"""
import json
import threading
from sqlalchemy import text
from backend import store

STAGE_ORDER = ['accepted', 'deterministic_checks', 'scout', 'maker_draft_v1',
               'checker_v1', 'maker_draft_v2', 'checker_v2', 'receipt']

_lock = threading.Lock()
_workers: dict[str, threading.Thread] = {}


def _sanitized_evidence(evidence):
    if not isinstance(evidence, dict):
        return {}
    clean = {}
    for key, value in evidence.items():
        if not isinstance(key, str) or len(key) > 64:
            continue
        if value is None or isinstance(value, (bool, int, float, str)):
            clean[key] = value if not isinstance(value, str) else value[:256]
    return clean


def record_step(run_id, stage, state, profile='', evidence=None, observed_at=None):
    """Store one step row in a short transaction. Never raises."""
    try:
        with store.connect() as db:
            row = db.execute(text('SELECT COALESCE(MAX(seq), -1) FROM run_steps WHERE run_id=:id'),
                             {'id': run_id}).scalar()
            db.execute(text('INSERT INTO run_steps(run_id,seq,stage,state,observed_at,profile,evidence)'
                            ' VALUES (:run,:seq,:stage,:state,COALESCE(CAST(:at AS timestamptz),now()),:profile,CAST(:evidence AS jsonb))'),
                       {'run': run_id, 'seq': int(row) + 1, 'stage': str(stage)[:64],
                        'state': str(state)[:16], 'at': observed_at,
                        'profile': str(profile or '')[:256],
                        'evidence': json.dumps(_sanitized_evidence(evidence))})
    except Exception:
        pass


def _sink_for(run_id):
    def sink(event):
        stage = (event or {}).get('stage', '')
        state = (event or {}).get('state', '')
        # Terminal claims belong to the finalize transaction that also
        # stores the final receipt, never to a mid-pipeline write.
        if (stage == 'receipt' and state == 'completed') or state == 'failed':
            return
        record_step(run_id, stage, state, (event or {}).get('profile', ''),
                    (event or {}).get('evidence'), (event or {}).get('timestamp'))
    return sink


def is_worker_live(run_id):
    with _lock:
        thread = _workers.get(run_id)
    return bool(thread is not None and thread.is_alive())


def mark_done(run_id):
    with _lock:
        _workers.pop(run_id, None)


def _finalize_success(run_id, receipt, maker_name, actor):
    evidence = {'blocked_count': (receipt.get('checker_v2') or {}).get('blocked_count'),
                'stored': True}
    with store.connect() as db:
        db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id'),
                   {'receipt': json.dumps(receipt), 'state': receipt['approval_state'], 'id': run_id})
        db.execute(text('INSERT INTO memory(run_id,facts) VALUES (:id,CAST(:facts AS jsonb))'
                        ' ON CONFLICT (run_id) DO UPDATE SET facts=EXCLUDED.facts'),
                   {'id': run_id, 'facts': json.dumps(receipt.get('scout', {}).get('facts_used', []))})
        row = db.execute(text('SELECT COALESCE(MAX(seq), -1) FROM run_steps WHERE run_id=:id'),
                         {'id': run_id}).scalar()
        db.execute(text("INSERT INTO run_steps(run_id,seq,stage,state,profile,evidence)"
                        " VALUES (:run,:seq,'receipt','completed','LaunchCrew',CAST(:evidence AS jsonb))"),
                   {'run': run_id, 'seq': int(row) + 1, 'evidence': json.dumps(evidence)})
        store.audit(db, run_id, 'run_completed', actor)


def _finalize_failure(run_id, receipt, step, error, maker_name, actor):
    evidence = {'error_type': type(error).__name__, 'stored': True,
                'completed_steps': list(receipt.get('completed_steps') or [])}
    with store.connect() as db:
        db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id'),
                   {'receipt': json.dumps(receipt), 'state': receipt['approval_state'], 'id': run_id})
        db.execute(text('INSERT INTO memory(run_id,facts) VALUES (:id,CAST(:facts AS jsonb))'
                        ' ON CONFLICT (run_id) DO UPDATE SET facts=EXCLUDED.facts'),
                   {'id': run_id, 'facts': json.dumps([])})
        row = db.execute(text('SELECT COALESCE(MAX(seq), -1) FROM run_steps WHERE run_id=:id'),
                         {'id': run_id}).scalar()
        db.execute(text('INSERT INTO run_steps(run_id,seq,stage,state,profile,evidence)'
                        ' VALUES (:run,:seq,:stage,:state,:profile,CAST(:evidence AS jsonb))'),
                   {'run': run_id, 'seq': int(row) + 1, 'stage': str(step or 'pipeline')[:64],
                    'state': 'failed', 'profile': 'LaunchCrew', 'evidence': json.dumps(evidence)})
        store.audit(db, run_id, 'run_failed', actor)


def _work(run_id, idea, legacy, seed, items, checker_profile, scout, maker, checker,
          maker_name, actor, stage_gate):
    from backend import adapter
    last_started = {'stage': 'pipeline'}
    base_sink = _sink_for(run_id)

    def sink(event):
        if isinstance(event, dict) and event.get('state') == 'started' and isinstance(event.get('stage'), str):
            last_started['stage'] = event['stage']
        base_sink(event)

    try:
        receipt = adapter.execute(run_id, idea, legacy, seed, memory_items=items,
                                  checker_profile=checker_profile, scout_profile=scout,
                                  maker_profile=maker, checker_agent=checker,
                                  progress_sink=sink, stage_gate=stage_gate)
        _finalize_success(run_id, receipt, maker_name, actor)
    except Exception as error:
        step = last_started['stage']
        failure = {'receipt_version': '1.0', 'run_id': run_id,
                   'status': 'failed', 'approval_state': 'pending_approval',
                   'idea': idea, 'approvals': [], 'completed_steps': [],
                   'error_type': type(error).__name__,
                   'checker_profile': checker_profile,
                   'stage_bindings': {'scout': str((scout or {}).get('name') or ''),
                                      'maker': str((maker or {}).get('name') or ''),
                                      'checker': str((checker or {}).get('name') or '')},
                   'summary': {'submit_attempted': False, 'submit_completed': False},
                   'audit': {'event_log': [], 'stopped_reason': step}}
        try:
            # Reuse the stored step history as the completed-steps evidence.
            with store.connect() as db:
                rows = db.execute(text('SELECT stage,state FROM run_steps WHERE run_id=:id ORDER BY seq,id'),
                                  {'id': run_id}).all()
            failure['completed_steps'] = [stage for stage, state in rows if state == 'completed']
            failure['audit'] = {'event_log': [{'step': stage, 'state': state} for stage, state in rows],
                                'stopped_reason': step}
        except Exception:
            pass
        _finalize_failure(run_id, failure, step, error, maker_name, actor)
    finally:
        mark_done(run_id)


def start_async_run(run_id, idea, legacy, seed, items, checker_profile, scout, maker,
                    checker, maker_name, actor, stage_gate=None):
    """Start the single worker for run_id. Returns False if one is live."""
    with _lock:
        live = _workers.get(run_id)
        if live is not None and live.is_alive():
            return False
        thread = threading.Thread(target=_work, daemon=True, kwargs={
            'run_id': run_id, 'idea': idea, 'legacy': legacy, 'seed': seed,
            'items': items, 'checker_profile': checker_profile, 'scout': scout,
            'maker': maker, 'checker': checker, 'maker_name': maker_name,
            'actor': actor, 'stage_gate': stage_gate})
        _workers[run_id] = thread
    thread.start()
    return True
