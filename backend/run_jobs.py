"""Background pipeline workers for async runs with incremental stage receipts.

One daemon thread per run id executes the real pipeline. Every stage
boundary the pipeline reaches is stored as a run_steps row in its own
short transaction, so no database lock is held across remote inference.
A step row that cannot be persisted stops the pipeline with an honest
failed receipt instead of continuing inference without its journal:
required journal loss never becomes a fully journaled completion claim.
Terminal rows (receipt completed, or the single failure row) are written
in the same short transaction that stores the final receipt, so terminal
success is never claimed before the database commit. If that terminal
transaction itself cannot be confirmed, the stored receipt is left as it
is (running when nothing terminal committed) and readers report the
actual stored state as unconfirmed; no synthetic failure overwrites a
possibly committed success and no provider work is retried. Polls and
reconnects are read-only and never start work. The registry starts at
most one live worker per run id; public creation mints a fresh id per
POST and never restarts, and GET polling never starts or restarts work.
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


class StepJournalError(RuntimeError):
    """A stage receipt row could not be persisted.

    The message carries only the bounded failure type, never SQL, params,
    or receipt contents. Raising stops the pipeline at the unjournaled
    stage so later inference never runs blind after required journal
    loss; the failed receipt keeps the known completed stage audit.
    """


def record_step_in(db, run_id, stage, state, profile='', evidence=None, observed_at=None):
    """Insert one step row on the caller's connection. Raises on failure."""
    row = db.execute(text('SELECT COALESCE(MAX(seq), -1) FROM run_steps WHERE run_id=:id'),
                     {'id': run_id}).scalar()
    db.execute(text('INSERT INTO run_steps(run_id,seq,stage,state,observed_at,profile,evidence)'
                    ' VALUES (:run,:seq,:stage,:state,COALESCE(CAST(:at AS timestamptz),now()),:profile,CAST(:evidence AS jsonb))'),
               {'run': run_id, 'seq': int(row) + 1, 'stage': str(stage)[:64],
                'state': str(state)[:16], 'at': observed_at,
                'profile': str(profile or '')[:256],
                'evidence': json.dumps(_sanitized_evidence(evidence))})


def record_step(run_id, stage, state, profile='', evidence=None, observed_at=None):
    """Store one step row in a short transaction.

    Raises StepJournalError (bounded type only) when the row cannot be
    persisted. Callers treat journal loss as pipeline failure, never as
    a fully journaled completion.
    """
    try:
        with store.connect() as db:
            record_step_in(db, run_id, stage, state, profile, evidence, observed_at)
    except Exception as error:
        raise StepJournalError(type(error).__name__) from error


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
    if not isinstance(receipt, dict) or receipt.get('status') != 'completed':
        raise ValueError('Refusing terminal success for a non-completed receipt')
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


def _sanitized_error_type(error):
    """Bounded failure type only: never SQL, params, or receipt contents."""
    name = type(error).__name__ if error is not None else 'PipelineError'
    if not isinstance(name, str) or not name:
        return 'PipelineError'
    return ''.join(char for char in name if char.isalnum() or char == '_')[:64] or 'PipelineError'


def _finalize_failure(run_id, receipt, step, error, maker_name, actor):
    """Store the ORIGINAL failed receipt plus exactly one failed step row.

    The receipt keeps its own error type, completed history, profiles,
    model usage, and stopped reason. No run_completed audit and no
    receipt completed row are written for a failed outcome.
    """
    if not isinstance(receipt, dict) or receipt.get('status') == 'completed':
        raise ValueError('Refusing terminal failure for a completed receipt')
    receipt = dict(receipt)
    receipt['approval_state'] = receipt.get('approval_state') or 'pending_approval'
    evidence = {'error_type': receipt.get('error_type') or _sanitized_error_type(error),
                'stored': True,
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


def _leave_unconfirmed(run_id, error):
    """Terminal persistence failed: leave stored state, mark unconfirmed.

    The commit may or may not have landed, so a synthetic failure must
    not overwrite a possibly committed success. The stored receipt is
    read back; when it is already terminal it is kept untouched, and
    when it is still running the absent worker already makes readers
    report it as unconfirmed. One best-effort audit marker carries only
    the bounded error type. Nothing is retried and nothing is printed
    with params or receipt contents.
    """
    failure_type = _sanitized_error_type(error)
    try:
        with store.connect() as db:
            row = db.execute(text('SELECT receipt FROM runs WHERE id=:id'), {'id': run_id}).fetchone()
            stored = row[0] if row else {}
            if isinstance(stored, dict) and stored.get('status') in ('completed', 'failed'):
                return
            store.audit(db, run_id, 'run_unconfirmed:' + failure_type, 'system')
    except Exception:
        pass


def _work(run_id, idea, legacy, seed, items, checker_profile, scout, maker, checker,
          maker_name, actor, stage_gate, product_facts=None):
    from backend import adapter, model_admission
    last_started = {'stage': 'pipeline'}
    base_sink = _sink_for(run_id)

    def sink(event):
        if isinstance(event, dict) and event.get('state') == 'started' and isinstance(event.get('stage'), str):
            last_started['stage'] = event['stage']
        base_sink(event)

    terminal = None
    pipeline_error = None
    try:
        factory = model_admission.admission_factory_for_run(store.engine(), run_id)
        terminal = adapter.execute(run_id, idea, legacy, seed, memory_items=items,
                                   checker_profile=checker_profile, scout_profile=scout,
                                   maker_profile=maker, checker_agent=checker,
                                   progress_sink=sink, stage_gate=stage_gate,
                                   product_facts=product_facts,
                                   model_admission_factory=factory)
    except Exception as error:
        pipeline_error = error
    try:
        if pipeline_error is not None:
            step = last_started['stage']
            failure = {'receipt_version': '1.0', 'run_id': run_id,
                       'status': 'failed', 'approval_state': 'pending_approval',
                       'idea': idea, 'approvals': [], 'completed_steps': [],
                       'error_type': _sanitized_error_type(pipeline_error),
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
            _finalize_failure(run_id, failure, step, pipeline_error, maker_name, actor)
        elif isinstance(terminal, dict) and terminal.get('status') == 'failed':
            # The pipeline captured its own failed receipt (with model usage,
            # stage bindings, and the actual stopped stage) before raising.
            # Persist that original receipt: the stopped stage comes from it,
            # because last_started still names the prior stage when a gate
            # fails before the failing stage emits its own started note.
            stopped = (terminal.get('audit') or {}).get('stopped_reason')
            if not isinstance(stopped, str) or not stopped:
                stopped = last_started['stage']
            _finalize_failure(run_id, terminal, stopped, None, maker_name, actor)
        else:
            _finalize_success(run_id, terminal, maker_name, actor)
    except Exception as error:
        _leave_unconfirmed(run_id, error)
    finally:
        mark_done(run_id)


def start_async_run(run_id, idea, legacy, seed, items, checker_profile, scout, maker,
                    checker, maker_name, actor, stage_gate=None, product_facts=None):
    """Claim and start the single live worker for run_id.

    Returns False when a worker for run_id is already live, so at most
    one live worker exists per run id. Claim and thread start happen
    under one lock: concurrent starters serialize and only the first
    starts. A second live worker is never started; a new worker after
    the previous one finished is possible only through an explicit
    private call (public creation mints a fresh id per POST and never
    restarts, and GET polling never starts or restarts work).
    """
    with _lock:
        live = _workers.get(run_id)
        if live is not None and live.is_alive():
            return False
        thread = threading.Thread(target=_work, daemon=True, kwargs={
            'run_id': run_id, 'idea': idea, 'legacy': legacy, 'seed': seed,
            'items': items, 'checker_profile': checker_profile, 'scout': scout,
            'maker': maker, 'checker': checker, 'maker_name': maker_name,
            'actor': actor, 'stage_gate': stage_gate, 'product_facts': product_facts})
        _workers[run_id] = thread
        thread.start()
        return True
