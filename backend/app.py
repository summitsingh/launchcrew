"""Typed FastAPI demo API over the preserved Python pipeline."""
from contextlib import asynccontextmanager
import json
from datetime import datetime, timezone
from typing import Literal, Any
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from backend import adapter, store, auth
from launchcrew import agents, receipts
from launchcrew.checker_policies import FLOOR_NOTE, MATCHING_NOTE, describe_supported
from launchcrew.model_meta import (CONTRIBUTOR_SPARK_MODELS as CONTRIBUTOR_SPARK_IDS,
                                   STANDARD_SPARK_MODELS as STANDARD_SPARK_IDS,
                                   STANDARD_WONDER_MODELS as STANDARD_WONDER_IDS)


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Profile(Strict):
    name: str
    role: str
    department: str
    personality: str
    expertise: str
    decision_rules: list[str]
    veto_scope: list[str]
    tools_allowed: list[str]
    spend_limit: Literal[0] = 0
    approval_level: Literal['approve_each'] = 'approve_each'
    examples: list[dict[str, str]]


class Idea(Strict):
    idea: str = Field(min_length=1, max_length=2000)


class RunInput(Idea):
    agent_name: str = Field(description='Legacy Maker selector. Preserved for compatibility. Maker stage uses maker_name when provided, else agent_name.')
    scout_name: str | None = Field(default=None, description='Scout stage agent name. Defaults to built-in Scout.')
    maker_name: str | None = Field(default=None, description='Maker stage agent name. Defaults to agent_name for compatibility.')
    checker_name: str | None = Field(default=None, description='Checker stage agent name. Defaults to built-in Checker.')
    seed_unverified_claim: bool = False
    memory_ids: list[str] = []
    checker_profile: Literal['standard', 'strict'] = Field(default='standard', description='Legacy strictness. Strict adds the superlatives policy. Checker agent policies add blocks on top.')


class Clone(Strict):
    name: str


class Empty(Strict):
    pass


class Check(BaseModel):
    blocked_count: int
    verified_count: int
    blocked_claims: list[dict[str, str]]
    revision_instructions: list[str]


class Draft(BaseModel):
    post: str
    email: str
    claims: list[str]


class Approval(BaseModel):
    model_config = ConfigDict(extra='allow')
    approved_by: str
    action: str
    timestamp: str
    revision: int | None = None


class HumanDraft(BaseModel):
    model_config = ConfigDict(extra='allow')
    post: str
    email: str
    claims: list[str] = []
    revised_by: str | None = None
    revised_at: str | None = None
    revision: int | None = None


class RevisionHistoryEntry(BaseModel):
    model_config = ConfigDict(extra='allow')
    revision: int | None = None
    draft: dict[str, Any] | None = None
    check: dict[str, Any] | None = None
    approval_state: str | None = None
    approvals: list[Approval] = []
    approved_revision: int | None = None
    checker_profile: str | None = None
    checker_policies: list[str] | None = None
    blocked_claims: list[str] | None = None
    stage_bindings: dict[str, str] | None = None
    memory_used: list[dict[str, Any]] | None = None
    revised_by: str | None = None
    revised_at: str | None = None
    superseded_by: int | None = None
    outcome: str | None = None


class ExportEvent(BaseModel):
    model_config = ConfigDict(extra='allow')
    revision: int | None = None
    exported_by: str | None = None
    timestamp: str | None = None


class ScoutFact(BaseModel):
    model_config = ConfigDict(extra='allow')
    claim: str = ''
    verified: bool = False
    evidence: str | None = None
    sources: list[str] = []


class ScoutSection(BaseModel):
    model_config = ConfigDict(extra='allow')
    facts_used: list[ScoutFact] = []
    risks: list[str] = []
    sources: list[str] = []
    model_mode: str | None = None
    model_note: str | None = None


class PhotoStatus(BaseModel):
    model_config = ConfigDict(extra='allow')
    state: str = 'no_photo'
    label: str | None = None
    reason: str = ''
    policy_version: str = 'photo-geometry/v1'
    revision: int = 0
    actor: str = ''
    checked_at: str = ''


class ModelUsage(BaseModel):
    model_config = ConfigDict(extra='allow')
    spark_calls: int = 0
    spark_mode: str = 'deterministic_fallback'
    mode: str = 'deterministic_fallback'
    model_used: str = 'none'
    models_used: list[str] = []
    error_types: list[str] = []
    wonder_used: bool = False
    wonder_attempts: int = 0
    token_counts: dict[str, int] = {}
    tokens_known: bool = False
    data_mode: str = 'unknown'
    data_mode_note: str = ''
    data_basis: str = ''
    request_provider: str = 'unknown'


class ModelCapabilities(Strict):
    spark_configured: bool = False
    wonder_configured: bool = False
    sam_configured: bool = False
    spark_variant: Literal['standard', 'contributor', 'unknown', 'not_configured'] = 'not_configured'
    wonder_variant: Literal['standard', 'unknown', 'not_configured'] = 'not_configured'
    note: str = ('Key presence means configured only; it does not prove the API works, '
                 'credits, or authorization. No live call is made here.')


class Receipt(BaseModel):
    model_config = ConfigDict(extra='allow')
    run_id: str
    idea: str = ''
    memory_used: list[dict[str, Any]] = []
    checker_profile: str = 'standard'
    campaign_day: int | None = None
    campaign_brief: str | None = None
    status: str
    approval_state: Literal['pending_approval', 'approved_for_export']
    approvals: list[Approval]
    revision: int = 0
    approved_revision: int | None = None
    human_draft: HumanDraft | None = None
    human_check: Check | None = None
    revision_history: list[RevisionHistoryEntry] = []
    exported_draft: Draft | HumanDraft | None = None
    exported_revision: int | None = None
    export_history: list[ExportEvent] = []
    last_exported_by: str | None = None
    last_exported_at: str | None = None
    maker_draft_v1: Draft | None = None
    maker_draft_v2: Draft | None = None
    checker_v1: Check | None = None
    checker_v2: Check | None = None
    summary: dict[str, Any]
    audit: dict[str, Any]
    scout: ScoutSection | None = Field(default=None, description='Scout facts, sources, demo risks, and synthesis mode. Absent on historical or failed receipts.')
    stage_bindings: dict[str, str] | None = None
    stage_agents: dict[str, Any] | None = None
    checker_enforcement: dict[str, Any] | None = None
    checker_policies: list[str] | None = None
    model_usage: ModelUsage | None = None
    photo_status: PhotoStatus | None = None
    photo_transport: dict[str, Any] | None = None


class Preview(BaseModel):
    dry_run: bool
    profile: Profile
    sample_idea: str
    first_action: str
    model_called: bool
    side_effects: bool
    checker_enforcement: dict[str, Any] | None = None
    enforcement_note: str | None = None
    supported_policies: list[dict[str, Any]] | None = None


class CheckerPolicyOut(Strict):
    policy: str
    veto_token: str
    rule_line: str
    description: str


class CheckerPoliciesOut(Strict):
    supported: list[CheckerPolicyOut]
    floor_note: str
    matching: str


@asynccontextmanager
async def lifespan(app):
    auth.validate_config()
    store.initialize()
    yield


app = FastAPI(title='LaunchCrew', version='0.1.0', lifespan=lifespan)
app.include_router(auth.router)


@app.middleware('http')
async def local_requests(request: Request, call_next):
    from urllib.parse import urlsplit
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin:
        # PUBLIC_BASE_URL is the trusted frontend origin behind the Next proxy.
        expected = __import__('os').environ.get('PUBLIC_BASE_URL')
        same_host = urlsplit(origin).netloc == request.headers.get('host')
        if not same_host and origin.rstrip('/') != (expected or '').rstrip('/'):
            return JSONResponse({'detail': 'Cross-origin mutation refused'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.exception_handler(RequestValidationError)
async def sanitized_validation_error(request, error):
    # Never echo raw user input, secrets, ctx, or input in validation responses.
    # Return only loc, msg, and type, all as plain strings or integers.
    detail = []
    for item in error.errors():
        loc = [part for part in item.get("loc", []) if isinstance(part, (str, int))]
        detail.append({"loc": loc, "msg": str(item.get("msg", "")), "type": str(item.get("type", ""))})
    return JSONResponse({"detail": detail}, status_code=422)


@app.exception_handler(ValueError)
async def invalid(request, error):
    return JSONResponse({'detail': 'Validation failed'}, status_code=422)


@app.exception_handler(IntegrityError)
async def conflict(request, error):
    return JSONResponse({'detail': 'Conflict'}, status_code=409)


@app.get('/api/health')
def health() -> dict[str, str]:
    with store.connect() as db:
        db.execute(text('SELECT 1'))
    return {'status': 'ok', 'auth': 'enabled_unverified' if auth.enabled() else 'disabled_demo', 'approval_by': 'signed_in_user' if auth.enabled() else 'demo_placeholder'}


@app.get('/api/checker-policies', response_model=CheckerPoliciesOut)
def checker_policies(actor: str = Depends(auth.actor)):
    return {'supported': describe_supported(), 'floor_note': FLOOR_NOTE, 'matching': MATCHING_NOTE}


def _capability_snapshot():
    import os
    key = bool(os.environ.get('META_API_KEY', '').strip())
    spark_raw = os.environ.get('META_MODEL', 'muse-spark-1.3').strip() if key else ''
    wonder_raw = os.environ.get('META_WONDER_MODEL', '').strip() if key else ''
    sam_raw = os.environ.get('LAUNCHCREW_PHOTO_SAM_ENABLED', '').strip() if key else ''
    if not key:
        spark_variant: str = 'not_configured'
    elif spark_raw in STANDARD_SPARK_IDS:
        spark_variant = 'standard'
    elif spark_raw in CONTRIBUTOR_SPARK_IDS:
        spark_variant = 'contributor'
    else:
        spark_variant = 'unknown'
    if not key or not wonder_raw:
        wonder_variant: str = 'not_configured'
    elif wonder_raw in STANDARD_WONDER_IDS:
        wonder_variant = 'standard'
    else:
        wonder_variant = 'unknown'
    return {'spark_configured': key,
            'wonder_configured': bool(key and wonder_raw),
            'sam_configured': bool(key and sam_raw.lower() == 'true'),
            'spark_variant': spark_variant,
            'wonder_variant': wonder_variant}


@app.get('/api/model-capabilities', response_model=ModelCapabilities)
def model_capabilities(actor: str = Depends(auth.actor)):
    return _capability_snapshot()


@app.get('/api/agents', response_model=list[Profile])
def list_agents(actor: str = Depends(auth.actor)):
    with store.connect() as db:
        return [r[0] for r in db.execute(text('SELECT profile FROM agents ORDER BY name'))]


def get_profile(db, name):
    row = db.execute(text('SELECT profile FROM agents WHERE name=:name'), {'name': name.lower()}).fetchone()
    if not row:
        raise HTTPException(404, 'Agent not found')
    return row[0]


@app.get('/api/agents/{name}', response_model=Profile)
def get_agent(name: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        return get_profile(db, name)


@app.post('/api/agents', response_model=Profile, status_code=201)
def create_agent(profile: Profile, actor: str = Depends(auth.actor)):
    value = agents.validate(profile.model_dump())
    with store.connect() as db:
        db.execute(text('INSERT INTO agents(name,profile) VALUES (:name,CAST(:profile AS jsonb))'), {'name': value['name'].lower(), 'profile': json.dumps(value)})
        store.audit(db, None, 'agent_created', actor)
    return value


@app.put('/api/agents/{name}', response_model=Profile)
def edit_agent(name: str, profile: Profile, actor: str = Depends(auth.actor)):
    value = agents.validate(profile.model_dump())
    with store.connect() as db:
        old = get_profile(db, name)
        if old['name'] != value['name']:
            raise ValueError('Clone to rename')
        db.execute(text('UPDATE agents SET profile=CAST(:profile AS jsonb),updated_at=now() WHERE name=:name'), {'profile': json.dumps(value), 'name': name.lower()})
        store.audit(db, None, 'agent_edited', actor)
    return value


@app.post('/api/agents/{name}/clone', response_model=Profile, status_code=201)
def clone_agent(name: str, body: Clone, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        profile = get_profile(db, name)
    profile['name'] = body.name
    return create_agent(Profile(**profile), actor)


@app.post('/api/agents/{name}/preview', response_model=Preview)
def preview_agent(name: str, body: Idea, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        return adapter.preview(get_profile(db, name), body.idea)


def load_memory_selection(db, memory_ids):
    items = []
    for item_id in (memory_ids or []):
        items.append(memory_item(db, item_id))
    return items


def stage_names(body):
    maker = body.maker_name or body.agent_name
    scout = body.scout_name or 'Scout'
    checker = body.checker_name or 'Checker'
    return scout, maker, checker


def load_stage_profiles(db, body):
    legacy = get_profile(db, body.agent_name)
    scout_name, maker_name, checker_name = stage_names(body)
    scout = get_profile(db, scout_name)
    maker = legacy if maker_name.lower() == body.agent_name.lower() else get_profile(db, maker_name)
    checker = get_profile(db, checker_name)
    return legacy, scout, maker, checker


class AsyncRunCreated(BaseModel):
    model_config = ConfigDict(extra='allow')
    run_id: str
    status: str
    receipt: Receipt


class RunStep(BaseModel):
    model_config = ConfigDict(extra='allow')
    seq: int
    stage: str
    state: str
    observed_at: str | None = None
    profile: str = ''
    evidence: dict[str, Any] = {}


class RunStepsOut(BaseModel):
    run_id: str
    worker_live: bool
    steps: list[RunStep]


@app.post('/api/runs', response_model=Receipt, status_code=201)
def create_run(body: RunInput, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        legacy, scout, maker, checker = load_stage_profiles(db, body)
        items = load_memory_selection(db, body.memory_ids)
        _, maker_name, _ = stage_names(body)
    run_id = 'run_' + uuid4().hex
    receipt = adapter.execute(run_id, body.idea, legacy, body.seed_unverified_claim,
                              memory_items=items, checker_profile=body.checker_profile,
                              scout_profile=scout, maker_profile=maker, checker_agent=checker)
    with store.connect() as db:
        save_run(db, receipt, maker_name, actor)
    return receipt


@app.post('/api/runs/async', response_model=AsyncRunCreated, status_code=202)
def create_run_async(body: RunInput, actor: str = Depends(auth.actor)):
    """Accept a run and execute the real pipeline in a background worker.

    Returns a pending receipt immediately. Stage receipts arrive
    incrementally through GET /api/runs/{run_id}/steps as the worker
    reaches each real pipeline boundary. Polling never starts work.
    """
    from launchcrew import receipts as receipt_mod
    from backend import run_jobs
    try:
        with store.connect() as db:
            legacy, scout, maker, checker = load_stage_profiles(db, body)
            items = load_memory_selection(db, body.memory_ids)
            scout_name, maker_name, checker_name = stage_names(body)
            run_id = 'run_' + uuid4().hex
            pending = receipt_mod.pending_receipt(run_id, body.idea,
                                                  {'scout': scout_name, 'maker': maker_name, 'checker': checker_name})
            db.execute(text('INSERT INTO runs(id,receipt,agent_name,state) VALUES (:id,CAST(:receipt AS jsonb),:agent,:state)'),
                       {'id': run_id, 'receipt': json.dumps(pending), 'agent': maker_name.lower(), 'state': pending['approval_state']})
            db.execute(text('INSERT INTO memory(run_id,facts) VALUES (:id,CAST(:facts AS jsonb))'),
                       {'id': run_id, 'facts': json.dumps([])})
            store.audit(db, run_id, 'run_created', actor)
            # The accepted step commits in this same transaction as the run
            # row: a run is never accepted without its journal row, and a
            # journal failure rolls the whole accept back before any worker
            # starts, so no worker ever runs on an unjournaled accept.
            run_jobs.record_step_in(db, run_id, 'accepted', 'completed', 'LaunchCrew', {'idea_chars': len(body.idea)})
    except HTTPException:
        raise
    except Exception:
        # Bounded acceptance failure: the commit is unconfirmed, so report
        # it as such without SQL, params, receipt, secret, chain, or
        # traceback. No worker starts on an unconfirmed accept and nothing
        # is retried here; the caller retries with a new request. The
        # context manager above already rolled the transaction back.
        raise HTTPException(503, 'Run acceptance unconfirmed; retry with a new request') from None
    started = run_jobs.start_async_run(run_id, body.idea, legacy, body.seed_unverified_claim, items,
                                       body.checker_profile, scout, maker, checker, maker_name, actor)
    if not started:
        raise HTTPException(409, 'Run worker already active for this run')
    return {'run_id': run_id, 'status': 'running', 'receipt': pending}


def save_run(db, receipt, agent_name, actor):
    run_id = receipt['run_id']
    db.execute(text('INSERT INTO runs(id,receipt,agent_name,state) VALUES (:id,CAST(:receipt AS jsonb),:agent,:state)'),
               {'id': run_id, 'receipt': json.dumps(receipt), 'agent': agent_name.lower(), 'state': receipt['approval_state']})
    db.execute(text('INSERT INTO memory(run_id,facts) VALUES (:id,CAST(:facts AS jsonb))'),
               {'id': run_id, 'facts': json.dumps(receipt.get('scout', {}).get('facts_used', []))})
    store.audit(db, run_id, 'run_created', actor)


@app.get('/api/queue', response_model=list[Receipt])
def queue(actor: str = Depends(auth.actor)):
    with store.connect() as db:
        return [r[0] for r in db.execute(text("SELECT receipt FROM runs ORDER BY (state='pending_approval') DESC, created_at, id"))]


def get_receipt(db, run_id, lock=False):
    row = db.execute(text('SELECT receipt FROM runs WHERE id=:id' + (' FOR UPDATE' if lock else '')), {'id': run_id}).fetchone()
    if not row:
        raise HTTPException(404, 'Run not found')
    return row[0]


@app.get('/api/runs/{run_id}', response_model=Receipt)
@app.get('/api/runs/{run_id}/receipt', response_model=Receipt)
def get_run(run_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        return get_receipt(db, run_id)


def canonical_observed_at(value):
    """Serialize a stored timestamptz as canonical UTC ISO-8601.

    Postgres returns timestamptz in the session TimeZone, so a host
    cluster on America/Chicago yields -05:00 while CI yields +00:00 for
    the same instant. Canonicalizing to UTC keeps hosts portable without
    stripping timezone information.
    """
    if value is None:
        return None
    if not isinstance(value, datetime):
        return None
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat()


@app.get('/api/runs/{run_id}/steps', response_model=RunStepsOut)
def get_run_steps(run_id: str, actor: str = Depends(auth.actor)):
    """Stored stage receipts for a run, in pipeline order.

    Each row corresponds to pipeline work that already happened. Polling
    this route never starts, restarts, or duplicates pipeline work.
    """
    from backend import run_jobs
    with store.connect() as db:
        exists = db.execute(text('SELECT 1 FROM runs WHERE id=:id'), {'id': run_id}).fetchone()
        if not exists:
            raise HTTPException(404, 'Run not found')
        rows = db.execute(text('SELECT seq,stage,state,observed_at,profile,evidence'
                               ' FROM run_steps WHERE run_id=:id ORDER BY seq,id'),
                          {'id': run_id}).mappings().all()
    steps = [{'seq': row['seq'], 'stage': row['stage'], 'state': row['state'],
              'observed_at': canonical_observed_at(row['observed_at']),
              'profile': row['profile'] or '', 'evidence': row['evidence'] or {}} for row in rows]
    return {'run_id': run_id, 'worker_live': run_jobs.is_worker_live(run_id), 'steps': steps}


class ReviseIn(Strict):
    post: str = Field(min_length=1, max_length=2000)
    email: str = Field(min_length=1, max_length=2000)
    base_revision: StrictInt = Field(ge=0)


class ApproveIn(Strict):
    expected_revision: StrictInt | None = Field(default=None, ge=0)


class ExportIn(Strict):
    expected_revision: StrictInt | None = Field(default=None, ge=0)


class PhotoCheckIn(Strict):
    image_data_uri: str
    expected_revision: StrictInt = Field(ge=0)


class PhotoCrop(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class PhotoPreview(BaseModel):
    frame_w: int
    frame_h: int
    crop: PhotoCrop | None
    label: Literal['detected']


class PhotoCheckOut(BaseModel):
    method: Literal['sam-3.1', 'not_run']
    label: str | None
    reason: str
    policy_version: str = 'photo-geometry/v1'
    revision: int
    photo_state: str


class PhotoCheckResponse(BaseModel):
    check: PhotoCheckOut
    receipt: Receipt
    preview: PhotoPreview | None = None


class PhotoRemoveIn(Strict):
    expected_revision: StrictInt = Field(ge=0)


class PhotoRemoveOut(BaseModel):
    revision: int
    photo_state: Literal['no_photo']
    approval_state: Literal['pending_approval']


def _reject_when_running(receipt):
    if receipt.get('status') == 'running':
        raise HTTPException(409, 'Run is still running; reload the receipt and retry after it completes')


@app.post('/api/runs/{run_id}/revise', response_model=Receipt)
def revise(run_id: str, body: ReviseIn, actor: str = Depends(auth.actor)):
    from launchcrew import human_review
    with store.connect() as db:
        receipt = get_receipt(db, run_id, True)
        _reject_when_running(receipt)
        try:
            revised = human_review.apply_revision(receipt, body.post.strip(), body.email.strip(), actor, body.base_revision)
        except human_review.NeedsRevision as error:
            raise HTTPException(422, {'message': str(error), 'blocked_claims': error.check['blocked_claims'],
                                      'revision_instructions': error.check['revision_instructions'],
                                      'blocked_count': error.check['blocked_count'],
                                      'verified_count': error.check['verified_count']})
        except ValueError as error:
            message = str(error)
            if 'stale' in message.lower():
                raise HTTPException(409, message)
            raise HTTPException(422, message)
        db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id'), {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id})
        # A saved revision resets approval, so the stale current-approval
        # projection must not remain: a leftover row would collide with the
        # fresh reapproval INSERT below (run_id PRIMARY KEY) and wrongly
        # present the superseded approval as current. Superseded
        # actor/time/revision evidence stays immutable in the receipt
        # revision_history, the receipt audit event_log, and the audit table.
        db.execute(text('DELETE FROM approvals WHERE run_id=:id'), {'id': run_id})
        store.audit(db, run_id, 'human_revised', actor)
    return revised


@app.post('/api/runs/{run_id}/approve', response_model=Receipt)
def approve(run_id: str, body: ApproveIn, actor: str = Depends(auth.actor)):
    from launchcrew import human_review
    with store.connect() as db:
        receipt = get_receipt(db, run_id, True)
        _reject_when_running(receipt)
        expected = body.expected_revision
        if human_review.current_revision(receipt) > 0 and expected is None:
            raise HTTPException(409, 'Approval is stale; expected_revision is required for edited revisions')
        if expected is not None and expected != human_review.current_revision(receipt):
            raise HTTPException(409, 'Approval is stale; the draft changed')
        try:
            receipts.approve_receipt(receipt, actor, expected)
        except ValueError as error:
            message = str(error)
            if 'stale' in message.lower():
                raise HTTPException(409, message)
            raise HTTPException(422, message)
        db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id'), {'receipt': json.dumps(receipt), 'state': receipt['approval_state'], 'id': run_id})
        # The approvals table is a current-approval projection (one row per
        # run): the plain INSERT keeps the PRIMARY KEY guard against double
        # approval and concurrent approval races, with no ON CONFLICT bypass
        # and no version-gate bypass (the stale/missing expected_revision
        # checks above still run first). A revise clears this row, so fresh
        # reapproval after edits inserts cleanly in the same transaction.
        db.execute(text('INSERT INTO approvals(run_id,approved_by) VALUES (:id,:actor)'), {'id': run_id, 'actor': actor})
        store.audit(db, run_id, 'approved_for_export', actor)
    return receipt


@app.post('/api/runs/{run_id}/export', response_model=Receipt)
def export(run_id: str, body: ExportIn, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        from backend.photo_review import photo_block_reason
        from launchcrew import human_review
        receipt = get_receipt(db, run_id, True)
        _reject_when_running(receipt)
        expected = body.expected_revision
        if human_review.current_revision(receipt) > 0 and expected is None:
            raise HTTPException(409, 'Export is stale; expected_revision is required for edited revisions')
        if expected is not None and expected != human_review.current_revision(receipt):
            raise HTTPException(409, 'Export is stale; the draft changed')
        photo_reason = photo_block_reason(receipt)
        if photo_reason is not None:
            raise HTTPException(422, photo_reason)
        try:
            exported = human_review.record_export(receipt, actor)
        except ValueError as error:
            raise HTTPException(422, str(error))
        db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id'), {'receipt': json.dumps(exported), 'state': exported['approval_state'], 'id': run_id})
        store.audit(db, run_id, 'exported', actor)
    return JSONResponse(exported, headers={'Content-Disposition': 'attachment; filename="launchcrew-pack.json"'})



@app.post('/api/runs/{run_id}/photo-check', response_model=PhotoCheckResponse)
def photo_check(run_id: str, body: PhotoCheckIn, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        _reject_when_running(get_receipt(db, run_id))
    from backend import photo_admission, sam
    from backend.photo_admission import AdmissionConflict, AdmissionRejected, AdmissionStale
    from backend.photo_input import PhotoInputError, parse_photo_data_uri
    from backend.photo_review import (PHOTO_EVENT_CHECKED,
                                      STATE_REQUESTED_UNCHECKED, apply_photo_event,
                                      photo_status_of, record_unattempted_transport)
    from launchcrew import human_review
    from launchcrew.photo_policy import PHOTO_POLICY_VERSION
    try:
        parsed = parse_photo_data_uri(body.image_data_uri)
    except PhotoInputError as error:
        raise HTTPException(422, 'Photo input rejected: ' + error.reason)
    if not sam.photo_sam_operable():
        with store.connect() as db:
            receipt = get_receipt(db, run_id, True)
            ok, context_reason = human_review.valid_revision_context(receipt)
            if not ok:
                raise HTTPException(422, context_reason)
            if body.expected_revision != human_review.current_revision(receipt):
                raise HTTPException(409, 'Photo check is stale; the draft changed')
            status = {'state': STATE_REQUESTED_UNCHECKED, 'label': None,
                      'reason': 'not_run: SAM not configured, photo unchecked',
                      'policy_version': PHOTO_POLICY_VERSION,
                      'revision': human_review.current_revision(receipt),
                      'actor': actor, 'checked_at': ''}
            revised = apply_photo_event(receipt, event=PHOTO_EVENT_CHECKED, actor=actor, status=status)
            revised = record_unattempted_transport(
                revised, handling='not_run',
                note=('SAM is not configured, so the photo bytes stayed on the LaunchCrew validation '
                      'server for this check and were not forwarded to any segmentation provider. '
                      'Text-model usage above is unchanged and covers text models only.'))
            db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id'),
                       {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id})
            db.execute(text('DELETE FROM approvals WHERE run_id=:id'), {'id': run_id})
            store.audit(db, run_id, 'photo_check_requested', actor)
        kept = photo_status_of(revised)
        check = PhotoCheckOut(method='not_run', label=None, reason=kept['reason'],
                              policy_version=PHOTO_POLICY_VERSION,
                              revision=revised['revision'], photo_state=kept['state'])
        return PhotoCheckResponse(check=check, receipt=revised, preview=None)
    try:
        row, preview, receipt = photo_admission.run_photo_check(
            store.engine(), run_id, parsed['raw'], parsed['mime'],
            body.expected_revision, body.expected_revision, actor=actor,
            frame=(parsed['width'], parsed['height']))
    except AdmissionRejected as error:
        raise HTTPException(422, str(error))
    except AdmissionStale as error:
        raise HTTPException(409, str(error))
    except AdmissionConflict as error:
        raise HTTPException(409, str(error))
    kept = photo_status_of(receipt)
    check = PhotoCheckOut(method='sam-3.1', label=row['label'], reason=row['reason'] or kept['reason'],
                          policy_version=row['policy_version'] or PHOTO_POLICY_VERSION,
                          revision=receipt.get('revision', 0), photo_state=kept['state'])
    return PhotoCheckResponse(check=check, receipt=receipt,
                              preview=PhotoPreview(**preview) if preview else None)


@app.delete('/api/runs/{run_id}/photo', response_model=PhotoRemoveOut)
def photo_remove(run_id: str, body: PhotoRemoveIn, actor: str = Depends(auth.actor)):
    from backend.photo_review import (PHOTO_EVENT_REMOVED, STATE_NO_PHOTO,
                                      apply_photo_event, blank_photo_status,
                                      photo_status_of)
    from launchcrew import human_review
    with store.connect() as db:
        receipt = get_receipt(db, run_id, True)
        _reject_when_running(receipt)
        ok, context_reason = human_review.valid_revision_context(receipt)
        if not ok:
            raise HTTPException(422, context_reason)
        if body.expected_revision != human_review.current_revision(receipt):
            raise HTTPException(409, 'Photo remove is stale; the draft changed')
        if photo_status_of(receipt)['state'] == STATE_NO_PHOTO:
            raise HTTPException(422, 'No photo is attached to this revision')
        revised = apply_photo_event(receipt, event=PHOTO_EVENT_REMOVED, actor=actor,
                                    status=blank_photo_status())
        db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id'),
                   {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id})
        db.execute(text('DELETE FROM approvals WHERE run_id=:id'), {'id': run_id})
        store.audit(db, run_id, 'photo_removed', actor)
    return PhotoRemoveOut(revision=revised['revision'], photo_state='no_photo',
                          approval_state='pending_approval')


MemoryKind = Literal['brand_fact', 'profile', 'approval_example', 'blocked_rule']


class MemoryItemIn(Strict):
    kind: MemoryKind
    title: str = Field(min_length=1, max_length=200)
    content: dict[str, Any]


class MemoryItemEdit(Strict):
    title: str = Field(min_length=1, max_length=200)
    content: dict[str, Any]
    kind: MemoryKind | None = None


class MemoryItemOut(MemoryItemIn):
    id: str
    source_run_id: str | None
    created_at: datetime
    updated_at: datetime


class LearnMemory(Strict):
    kind: Literal['approval_example', 'blocked_rule']


def memory_item(db, item_id):
    row = db.execute(text('SELECT * FROM memory_items WHERE id=:id'), {'id': item_id}).mappings().first()
    if row is None:
        raise HTTPException(404, 'Memory item not found')
    return dict(row)


def insert_memory(db, body, actor, action, source_run_id=None):
    item_id = 'mem_' + uuid4().hex
    db.execute(text('INSERT INTO memory_items(id,kind,title,content,source_run_id) VALUES (:id,:kind,:title,CAST(:content AS jsonb),:source)'),
               {'id': item_id, 'kind': body.kind, 'title': body.title, 'content': json.dumps(body.content), 'source': source_run_id})
    store.audit(db, source_run_id, action, actor)
    return memory_item(db, item_id)


@app.get('/api/memory', response_model=list[MemoryItemOut])
def list_memory(actor: str = Depends(auth.actor)):
    with store.connect() as db:
        return db.execute(text('SELECT * FROM memory_items ORDER BY created_at,id')).mappings().all()


@app.post('/api/memory', response_model=MemoryItemOut, status_code=201)
def create_memory(body: MemoryItemIn, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        return insert_memory(db, body, actor, 'memory_item_created')


@app.get('/api/memory/{item_id}', response_model=MemoryItemOut)
def get_memory(item_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        return memory_item(db, item_id)


@app.put('/api/memory/{item_id}', response_model=MemoryItemOut)
def edit_memory(item_id: str, body: MemoryItemEdit, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        item = memory_item(db, item_id)
        if 'kind' in body.model_fields_set and body.kind != item['kind']:
            raise HTTPException(422, 'Memory kind is immutable')
        db.execute(text('UPDATE memory_items SET title=:title,content=CAST(:content AS jsonb),updated_at=now() WHERE id=:id'),
                   {'id': item_id, 'title': body.title, 'content': json.dumps(body.content)})
        store.audit(db, None, 'memory_item_edited', actor)
        return memory_item(db, item_id)


@app.delete('/api/memory/{item_id}', status_code=204)
def delete_memory(item_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        memory_item(db, item_id)
        db.execute(text('DELETE FROM memory_items WHERE id=:id'), {'id': item_id})
        store.audit(db, None, 'memory_item_deleted', actor)
    return Response(status_code=204)


@app.post('/api/memory/from-run/{run_id}', response_model=MemoryItemOut, status_code=201)
def learn_memory(run_id: str, body: LearnMemory, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        from launchcrew import human_review
        receipt = get_receipt(db, run_id, True)
        if receipt['approval_state'] != 'approved_for_export':
            raise HTTPException(409, 'Learning requires explicit run approval')
        if not human_review.exportable(receipt):
            raise HTTPException(409, 'Learning requires approval of the latest revision')
        draft = human_review.current_draft(receipt)
        content = ({'idea': receipt['idea'], 'post': draft['post'], 'email': draft['email']}
                   if body.kind == 'approval_example' else {'blocked_claims': receipt['checker_v1']['blocked_claims']})
        item = MemoryItemIn(kind=body.kind, title=f'{body.kind}: {run_id}', content=content)
        return insert_memory(db, item, actor, 'memory_item_learned', run_id)


class RunDiff(Strict):
    run_a_id: str
    run_b_id: str
    same_idea: bool
    idea: str
    draft_v1_post_changed: bool
    draft_v1_email_changed: bool
    draft_v2_post_changed: bool
    draft_v2_email_changed: bool
    draft_v1_post_a: str | None
    draft_v1_post_b: str | None
    draft_v2_post_a: str | None
    draft_v2_post_b: str | None
    draft_v2_email_a: str | None
    draft_v2_email_b: str | None
    checker_v1_blocked_count_a: int | None
    checker_v1_blocked_count_b: int | None
    checker_v2_blocked_count_a: int | None
    checker_v2_blocked_count_b: int | None
    checker_profile_a: str | None = None
    checker_profile_b: str | None = None
    checker_profile_changed: bool = False
    scout_name_a: str | None = None
    scout_name_b: str | None = None
    maker_name_a: str | None = None
    maker_name_b: str | None = None
    checker_name_a: str | None = None
    checker_name_b: str | None = None
    stage_bindings_changed: bool = False
    memory_ids_a: list[str] = []
    memory_ids_b: list[str] = []
    blocked_claims_only_in_a: list[dict[str, str]]
    blocked_claims_only_in_b: list[dict[str, str]]
    approval_state_a: str
    approval_state_b: str
    approval_state_changed: bool
    status_a: str
    status_b: str
    receipt_keys_only_in_a: list[str]
    receipt_keys_only_in_b: list[str]


def stage_binding(receipt, stage):
    bindings = receipt.get('stage_bindings') or {}
    if isinstance(bindings, dict) and isinstance(bindings.get(stage), str):
        return bindings.get(stage)
    detail = (receipt.get('stage_agents') or {}).get(stage) or {}
    if isinstance(detail, dict) and isinstance(detail.get('name'), str):
        return detail.get('name')
    return None


def diff_receipts(a, b):
    bindings_a = {stage: stage_binding(a, stage) for stage in ('scout', 'maker', 'checker')}
    bindings_b = {stage: stage_binding(b, stage) for stage in ('scout', 'maker', 'checker')}
    result = {'run_a_id': a['run_id'], 'run_b_id': b['run_id'],
              'same_idea': a.get('idea') == b.get('idea'), 'idea': a.get('idea', ''),
              'approval_state_changed': a['approval_state'] != b['approval_state'],
              'checker_profile_a': a.get('checker_profile'), 'checker_profile_b': b.get('checker_profile'),
              'checker_profile_changed': a.get('checker_profile') != b.get('checker_profile'),
              'scout_name_a': bindings_a['scout'], 'scout_name_b': bindings_b['scout'],
              'maker_name_a': bindings_a['maker'], 'maker_name_b': bindings_b['maker'],
              'checker_name_a': bindings_a['checker'], 'checker_name_b': bindings_b['checker'],
              'stage_bindings_changed': bindings_a != bindings_b,
              'memory_ids_a': [m.get('id') for m in a.get('memory_used', []) if isinstance(m, dict)],
              'memory_ids_b': [m.get('id') for m in b.get('memory_used', []) if isinstance(m, dict)]}
    for version in ('v1', 'v2'):
        for field in ('post', 'email'):
            left = (a.get(f'maker_draft_{version}') or {}).get(field)
            right = (b.get(f'maker_draft_{version}') or {}).get(field)
            result[f'draft_{version}_{field}_changed'] = left != right
            if version == 'v2' or field == 'post':
                result[f'draft_{version}_{field}_a'] = left
                result[f'draft_{version}_{field}_b'] = right
        for suffix, receipt in (('a', a), ('b', b)):
            result[f'checker_{version}_blocked_count_{suffix}'] = (receipt.get(f'checker_{version}') or {}).get('blocked_count')
    def claims(receipt):
        return [claim for version in ('v1', 'v2') for claim in (receipt.get(f'checker_{version}') or {}).get('blocked_claims', [])]
    for suffix, left, right in (('a', a, b), ('b', b, a)):
        result[f'approval_state_{suffix}'] = left['approval_state']
        result[f'status_{suffix}'] = left['status']
        result[f'receipt_keys_only_in_{suffix}'] = sorted(left.keys() - right.keys())
        unique = {json.dumps(c, sort_keys=True): c for c in claims(left) if c not in claims(right)}
        result[f'blocked_claims_only_in_{suffix}'] = [unique[key] for key in sorted(unique)]
    return result


@app.get('/api/runs/{run_a}/diff/{run_b}', response_model=RunDiff)
def replay_diff(run_a: str, run_b: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        return diff_receipts(get_receipt(db, run_a), get_receipt(db, run_b))


CAMPAIGN_BRIEFS = [
    (1, 'Origin story', 'Designed in Texas for Austin commuters', 'Vegan leather wallet, designed in Texas'),
    (2, 'Material and craft', '100% vegan PU leather, made to last', '100% vegan PU leather, $49'),
    (3, 'Commuter use', 'A wallet for Austin commuters on the go', 'Vegan leather wallet for Austin commuters'),
    (4, 'Styling', 'Designed in Texas, priced for everyday carry', 'Designed in Texas, $49'),
    (5, 'Care and durability', '100% vegan PU leather for Austin commuters', '100% vegan PU leather for Austin commuters'),
    (6, 'Social proof', 'A $49 wallet designed in Texas', 'Vegan leather wallet, $49, designed in Texas'),
    (7, 'Launch offer', 'Launch on Instagram for Austin commuters', 'For Austin commuters, launch on Instagram'),
]
CAMPAIGN_BRIEF_BY_DAY = {day: (angle, brief, claim) for day, angle, brief, claim in CAMPAIGN_BRIEFS}


class CampaignDay(Strict):
    day: int
    run_id: str
    approval_state: Literal['pending_approval', 'approved_for_export']
    status: str
    checker_v2_blocked_count: int | None
    idea: str
    angle: str = ''
    brief: str = ''
    draft_v2_post: str | None = None
    revision: int = 0
    approved_revision: int | None = None


class CampaignOut(Strict):
    id: str
    idea: str
    agent_name: str
    created_at: datetime
    days: list[CampaignDay]


def campaign_detail(db, campaign_id):
    row = db.execute(text('SELECT * FROM campaigns WHERE id=:id'), {'id': campaign_id}).mappings().first()
    if row is None:
        raise HTTPException(404, 'Campaign not found')
    result = dict(row)
    result['days'] = []
    for day, receipt in db.execute(text('SELECT d.day,r.receipt FROM campaign_days d JOIN runs r ON r.id=d.run_id WHERE d.campaign_id=:id ORDER BY d.day'), {'id': campaign_id}):
        from launchcrew import human_review
        angle, brief, _claim = CAMPAIGN_BRIEF_BY_DAY.get(day, ('', '', ''))
        current = human_review.current_draft(receipt)
        check = human_review.current_check(receipt)
        result['days'].append({'day': day, 'run_id': receipt['run_id'], 'approval_state': receipt['approval_state'],
                               'status': receipt['status'], 'checker_v2_blocked_count': (check or {}).get('blocked_count'),
                               'idea': receipt.get('idea', ''), 'angle': angle, 'brief': brief,
                               'draft_v2_post': (current or {}).get('post'),
                               'revision': human_review.current_revision(receipt),
                               'approved_revision': receipt.get('approved_revision')})
    return result


@app.post('/api/campaigns', response_model=CampaignOut, status_code=201)
def create_campaign(body: RunInput, actor: str = Depends(auth.actor)):
    campaign_id = 'camp_' + uuid4().hex
    with store.connect() as db:
        legacy, scout, maker, checker = load_stage_profiles(db, body)
        items = load_memory_selection(db, body.memory_ids)
        _, maker_name, _ = stage_names(body)
        db.execute(text('INSERT INTO campaigns(id,idea,agent_name) VALUES (:id,:idea,:agent)'),
                   {'id': campaign_id, 'idea': body.idea, 'agent': maker_name})
        for day in range(1, 8):
            angle, brief, brief_claim = CAMPAIGN_BRIEF_BY_DAY[day]
            run_id = 'run_' + uuid4().hex
            receipt = adapter.execute(run_id, body.idea, legacy, body.seed_unverified_claim,
                                      memory_items=items, checker_profile=body.checker_profile,
                                      brief=brief, campaign_day=day, extra_claims=[brief_claim],
                                      scout_profile=scout, maker_profile=maker, checker_agent=checker)
            save_run(db, receipt, maker_name, actor)
            db.execute(text('INSERT INTO campaign_days(campaign_id,day,run_id) VALUES (:id,:day,:run)'),
                       {'id': campaign_id, 'day': day, 'run': run_id})
        return campaign_detail(db, campaign_id)


@app.get('/api/campaigns', response_model=list[CampaignOut])
def list_campaigns(actor: str = Depends(auth.actor)):
    with store.connect() as db:
        ids = db.execute(text('SELECT id FROM campaigns ORDER BY created_at,id')).scalars().all()
        return [campaign_detail(db, campaign_id) for campaign_id in ids]


@app.get('/api/campaigns/{campaign_id}', response_model=CampaignOut)
def get_campaign(campaign_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        return campaign_detail(db, campaign_id)


def campaign_run(campaign_id, day):
    with store.connect() as db:
        run_id = db.execute(text('SELECT run_id FROM campaign_days WHERE campaign_id=:id AND day=:day'), {'id': campaign_id, 'day': day}).scalar()
        if run_id is None:
            raise HTTPException(404, 'Campaign day not found')
        return run_id


@app.post('/api/campaigns/{campaign_id}/days/{day}/approve', response_model=Receipt)
def approve_campaign_day(campaign_id: str, day: int, body: ApproveIn, actor: str = Depends(auth.actor)):
    return approve(campaign_run(campaign_id, day), body, actor)


@app.post('/api/campaigns/{campaign_id}/days/{day}/export', response_model=Receipt)
def export_campaign_day(campaign_id: str, day: int, body: ExportIn, actor: str = Depends(auth.actor)):
    return export(campaign_run(campaign_id, day), body, actor)
