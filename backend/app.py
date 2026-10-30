"""Typed FastAPI demo API over the preserved Python pipeline."""
from contextlib import asynccontextmanager
import json
from datetime import date as date_cls
from datetime import datetime, timezone
from typing import Literal, Any, get_args
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from backend import adapter, store, auth
from launchcrew import agents, receipts
from launchcrew.outcome_log import KNOWN_CHANNELS as OUTCOME_KNOWN_CHANNELS
from launchcrew.outcome_log import MAX_COUNT as OUTCOME_MAX_COUNT
from launchcrew.outcome_log import MAX_NOTE_LENGTH as OUTCOME_MAX_NOTE_LENGTH
from launchcrew.outcome_log import PROVENANCE as OUTCOME_PROVENANCE
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


ProductFactSource = Literal['owner', 'pasted_text', 'memory', 'listing', 'campaign_brief', 'demo_template']


class ProductFactField(Strict):
    value: str = Field(default='', max_length=200)
    confirmed: bool = False
    source: ProductFactSource = 'owner'


class FounderNoteField(Strict):
    value: str = Field(default='', max_length=280)
    confirmed: bool = False
    source: ProductFactSource = 'owner'


class ProductFactsInput(Strict):
    material: ProductFactField | None = None
    contents: ProductFactField | None = None
    size: ProductFactField | None = None
    price: ProductFactField | None = None
    allowed_claims: list[ProductFactField] = Field(default_factory=list, max_length=12)
    founder_note: FounderNoteField | None = None


ImportSource = Literal['listing', 'instagram_bio', 'instagram_caption']


class ImportSuggestionsIn(Strict):
    text: str = Field(max_length=10000)
    source: ImportSource


class ImportSuggestionItem(Strict):
    text: str
    source: ImportSource
    product_fact_source: ProductFactSource
    status: Literal['unconfirmed'] = 'unconfirmed'
    confirmed: Literal[False] = False
    index: int


class ImportSuggestionsOut(Strict):
    status: Literal['unconfirmed'] = 'unconfirmed'
    source: ImportSource
    product_fact_source: ProductFactSource
    suggestions: list[ImportSuggestionItem]
    truncated: bool
    dropped_duplicates: int
    dropped_overlong: int
    dropped_empty: int
    parser_version: str


class RunInput(Idea):
    agent_name: str = Field(description='Legacy Maker selector. Preserved for compatibility. Maker stage uses maker_name when provided, else agent_name.')
    scout_name: str | None = Field(default=None, description='Scout stage agent name. Defaults to built-in Scout.')
    maker_name: str | None = Field(default=None, description='Maker stage agent name. Defaults to agent_name for compatibility.')
    checker_name: str | None = Field(default=None, description='Checker stage agent name. Defaults to built-in Checker.')
    seed_unverified_claim: bool = False
    memory_ids: list[str] = []
    checker_profile: Literal['standard', 'strict'] = Field(default='standard', description='Legacy strictness. Strict adds the superlatives policy. Checker agent policies add blocks on top.')
    product_facts: ProductFactsInput | None = Field(default=None, description='Slice 1 owner product facts. Only explicitly confirmed fields become evidence; suggestions never do. Absent means legacy demo-template mode.')


class Clone(Strict):
    name: str


class Empty(Strict):
    pass


class ClaimResult(BaseModel):
    model_config = ConfigDict(extra='ignore')
    claim: str = ''
    verified: bool = False
    verdict: str = 'unsupported'
    evidence: str | None = None
    evidence_claims: list[str] | None = None
    reason: str = ''
    blocked: bool = True
    source: str = ''


class LineEvidence(BaseModel):
    model_config = ConfigDict(extra='ignore')
    channel: str = ''
    line: str = ''
    evidence: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ApprovalBinding(BaseModel):
    model_config = ConfigDict(extra='ignore')
    version: str
    digest: str


class Check(BaseModel):
    model_config = ConfigDict(extra='ignore')
    blocked_count: int
    verified_count: int
    blocked_claims: list[dict[str, str]]
    revision_instructions: list[str]
    claim_results: list[ClaimResult] | None = None
    supported_count: int | None = None
    unsupported_count: int | None = None
    conflicts_count: int | None = None


class Draft(BaseModel):
    model_config = ConfigDict(extra='ignore')
    post: str
    email: str
    claims: list[str]
    draft_origin: str | None = None
    model_written: bool | None = None
    maker_schema: str | None = None
    model_used: str | None = None
    line_evidence: list[LineEvidence] | None = None


class Approval(BaseModel):
    model_config = ConfigDict(extra='allow')
    approved_by: str
    action: str
    timestamp: str
    revision: int | None = None
    binding_version: str | None = None
    binding_digest: str | None = None


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
    check: Check | None = None
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


class ProductFactState(BaseModel):
    model_config = ConfigDict(extra='allow')
    field: str = ''
    label: str = ''
    value: str = ''
    confirmed: bool = False
    source: str = ''
    claim: str | None = None


class SuggestedFact(BaseModel):
    model_config = ConfigDict(extra='allow')
    field: str = ''
    label: str = ''
    value: str = ''
    source: str = ''
    reason: str = ''


class FounderNoteState(BaseModel):
    model_config = ConfigDict(extra='allow')
    value: str = ''
    confirmed: bool = False
    source: str = 'owner'
    label: str = 'Founder note'
    sentence_ok: bool = False
    authorized_as_fact: bool = False


class FounderVariant(BaseModel):
    model_config = ConfigDict(extra='allow')
    post: str = ''
    email: str = ''
    label: str = ''
    authorized: bool = False
    verified: bool = False
    note: str = ''


class ProductFactsSection(BaseModel):
    model_config = ConfigDict(extra='allow')
    mode: str = 'demo_template'
    template: str = 'demo_facts.json'
    template_label: str = 'Bundled fictional demo template'
    template_used: bool = True
    template_note: str = ''
    fields: list[ProductFactState] = []
    confirmed_claims: list[str] = []
    allowlist: list[str] = []
    suggested: list[SuggestedFact] = []
    founder_note: FounderNoteState | None = None
    draft_variant: FounderVariant | None = None
    labels: dict[str, str] = {}


class VoiceProfileSection(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str | None = None
    title: str | None = None
    version: str | None = None
    digest: str | None = None
    example_count: int | None = None
    banned_term_count: int | None = None
    banned_terms: list[str] | None = None
    notice: str | None = None


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
    approval_binding: ApprovalBinding | None = None
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
    product_facts: ProductFactsSection | None = Field(default=None, description='Slice 1 confirmed product facts with provenance. Absent on historical or pending receipts.')
    voice_profile: VoiceProfileSection | None = Field(default=None, description='Slice 3 selected voice source/version with banned terms. Style samples stay in Memory and never become facts.')
    voice_stale: bool | None = Field(default=None, description='True when the selected voice was edited or deleted after this receipt; a new human revision check is required.')


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


@app.post('/api/import-suggestions', response_model=ImportSuggestionsOut)
def import_suggestions(body: ImportSuggestionsIn, actor: str = Depends(auth.actor)):
    """Parse pasted listing or social text into unconfirmed suggestions.

    Stateless owner intake: deterministic stdlib parse only, no database
    writes, no memory writes, no model calls, no network. Every suggestion
    returns confirmed false with provenance; explicit product-facts
    confirmation is still required before any evidence use.
    """
    from launchcrew.import_suggestions import parse_import_text
    result = parse_import_text(body.text, body.source)
    mapping = {'listing': 'listing', 'instagram_bio': 'pasted_text',
               'instagram_caption': 'pasted_text'}
    product_source = mapping[body.source]
    suggestions = [{'text': item['text'], 'source': item['source'],
                    'product_fact_source': product_source,
                    'status': 'unconfirmed', 'confirmed': False,
                    'index': item['index']} for item in result['suggestions']]
    return {'status': 'unconfirmed', 'source': result['source'],
            'product_fact_source': product_source,
            'suggestions': suggestions, 'truncated': result['truncated'],
            'dropped_duplicates': result['dropped_duplicates'],
            'dropped_overlong': result['dropped_overlong'],
            'dropped_empty': result['dropped_empty'],
            'parser_version': result['parser_version']}


@app.get('/api/agents', response_model=list[Profile])
def list_agents(actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return [r[0] for r in db.execute(text('SELECT profile FROM agents WHERE workspace_id=:ws ORDER BY name'), {'ws': workspace_id})]


def get_profile(db, name, workspace_id):
    row = db.execute(text('SELECT profile FROM agents WHERE workspace_id=:ws AND name=:name'), {'ws': workspace_id, 'name': name.lower()}).fetchone()
    if not row:
        raise HTTPException(404, 'Agent not found')
    return row[0]


@app.get('/api/agents/{name}', response_model=Profile)
def get_agent(name: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return get_profile(db, name, workspace_id)


@app.post('/api/agents', response_model=Profile, status_code=201)
def create_agent(profile: Profile, actor: str = Depends(auth.actor)):
    value = agents.validate(profile.model_dump())
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        db.execute(text('INSERT INTO agents(workspace_id,name,profile) VALUES (:ws,:name,CAST(:profile AS jsonb))'), {'ws': workspace_id, 'name': value['name'].lower(), 'profile': json.dumps(value)})
        store.audit(db, None, 'agent_created', actor, workspace_id)
    return value


@app.put('/api/agents/{name}', response_model=Profile)
def edit_agent(name: str, profile: Profile, actor: str = Depends(auth.actor)):
    value = agents.validate(profile.model_dump())
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        old = get_profile(db, name, workspace_id)
        if old['name'] != value['name']:
            raise ValueError('Clone to rename')
        result = db.execute(text('UPDATE agents SET profile=CAST(:profile AS jsonb),updated_at=now() WHERE workspace_id=:ws AND name=:name'), {'profile': json.dumps(value), 'ws': workspace_id, 'name': name.lower()})
        if result.rowcount == 0:
            raise HTTPException(404, 'Agent not found')
        store.audit(db, None, 'agent_edited', actor, workspace_id)
    return value


@app.post('/api/agents/{name}/clone', response_model=Profile, status_code=201)
def clone_agent(name: str, body: Clone, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        profile = get_profile(db, name, workspace_id)
    profile['name'] = body.name
    return create_agent(Profile(**profile), actor)


@app.post('/api/agents/{name}/preview', response_model=Preview)
def preview_agent(name: str, body: Idea, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return adapter.preview(get_profile(db, name, workspace_id), body.idea)


def load_memory_selection(db, memory_ids, workspace_id, lock=False):
    items = []
    for item_id in (memory_ids or []):
        items.append(memory_item(db, item_id, workspace_id, lock=lock))
    return items


def stage_names(body):
    maker = body.maker_name or body.agent_name
    scout = body.scout_name or 'Scout'
    checker = body.checker_name or 'Checker'
    return scout, maker, checker


def load_stage_profiles(db, body, workspace_id):
    legacy = get_profile(db, body.agent_name, workspace_id)
    scout_name, maker_name, checker_name = stage_names(body)
    scout = get_profile(db, scout_name, workspace_id)
    maker = legacy if maker_name.lower() == body.agent_name.lower() else get_profile(db, maker_name, workspace_id)
    checker = get_profile(db, checker_name, workspace_id)
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
    from backend import model_admission
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        legacy, scout, maker, checker = load_stage_profiles(db, body, workspace_id)
        items = load_memory_selection(db, body.memory_ids, workspace_id)
        _, maker_name, _ = stage_names(body)
        voice_selection = _capture_voice_selection(db, items, workspace_id)
    run_id = 'run_' + uuid4().hex
    factory = model_admission.admission_factory_for_run(store.engine(), run_id)
    receipt = adapter.execute(run_id, body.idea, legacy, body.seed_unverified_claim,
                              memory_items=items, checker_profile=body.checker_profile,
                              scout_profile=scout, maker_profile=maker, checker_agent=checker,
                              product_facts=body.product_facts.model_dump() if body.product_facts is not None else None,
                              model_admission_factory=factory)
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _mark_sync_voice_stale_if_changed(db, receipt, workspace_id, actor, lock=True, selection=voice_selection)
        save_run(db, receipt, maker_name, actor, workspace_id)
    return receipt


@app.post('/api/runs/async', response_model=AsyncRunCreated, status_code=202)
def create_run_async(body: RunInput, actor: str = Depends(auth.actor)):
    """Accept a run and execute the real pipeline in a background worker.

    Returns a pending receipt immediately. Stage receipts arrive
    incrementally through GET /api/runs/{run_id}/steps as the worker
    reaches each real pipeline boundary. Polling never starts work.
    """
    from launchcrew import receipts as receipt_mod
    from launchcrew.facts import parse_product_facts
    from backend import run_jobs
    product_facts_raw = body.product_facts.model_dump() if body.product_facts is not None else None
    # Invalid product-fact input fails with 422 before accept, never 503.
    parse_product_facts(product_facts_raw)
    try:
        with store.connect() as db:
            workspace_id = store.ensure_workspace_seeded(db, actor)
            legacy, scout, maker, checker = load_stage_profiles(db, body, workspace_id)
            items = load_memory_selection(db, body.memory_ids, workspace_id, lock=True)
            scout_name, maker_name, checker_name = stage_names(body)
            run_id = 'run_' + uuid4().hex
            pending = receipt_mod.pending_receipt(run_id, body.idea,
                                                  {'scout': scout_name, 'maker': maker_name, 'checker': checker_name},
                                                  _voice_receipt_binding(items))
            db.execute(text('INSERT INTO runs(id,receipt,agent_name,state,workspace_id) VALUES (:id,CAST(:receipt AS jsonb),:agent,:state,:ws)'),
                       {'id': run_id, 'receipt': json.dumps(pending), 'agent': maker_name.lower(), 'state': pending['approval_state'], 'ws': workspace_id})
            db.execute(text('INSERT INTO memory(run_id,facts) VALUES (:id,CAST(:facts AS jsonb))'),
                       {'id': run_id, 'facts': json.dumps([])})
            store.audit(db, run_id, 'run_created', actor, workspace_id)
            # The accepted step commits in this same transaction as the run
            # row: a run is never accepted without its journal row, and a
            # journal failure rolls the whole accept back before any worker
            # starts, so no worker ever runs on an unjournaled accept.
            run_jobs.record_step_in(db, run_id, 'accepted', 'completed', 'LaunchCrew', {'idea_chars': len(body.idea)}, workspace_id=workspace_id)
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
                                       body.checker_profile, scout, maker, checker, maker_name, actor,
                                       workspace_id=store.workspace_for_actor(actor),
                                       product_facts=product_facts_raw)
    if not started:
        raise HTTPException(409, 'Run worker already active for this run')
    return {'run_id': run_id, 'status': 'running', 'receipt': pending}


def save_run(db, receipt, agent_name, actor, workspace_id):
    run_id = receipt['run_id']
    db.execute(text('INSERT INTO runs(id,receipt,agent_name,state,workspace_id) VALUES (:id,CAST(:receipt AS jsonb),:agent,:state,:ws)'),
               {'id': run_id, 'receipt': json.dumps(receipt), 'agent': agent_name.lower(), 'state': receipt['approval_state'], 'ws': workspace_id})
    db.execute(text('INSERT INTO memory(run_id,facts) VALUES (:id,CAST(:facts AS jsonb))'),
               {'id': run_id, 'facts': json.dumps(receipt.get('scout', {}).get('facts_used', []))})
    store.audit(db, run_id, 'run_created', actor, workspace_id)


@app.get('/api/queue', response_model=list[Receipt])
def queue(actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return [r[0] for r in db.execute(text("SELECT receipt FROM runs WHERE workspace_id=:ws ORDER BY (state='pending_approval') DESC, created_at, id"), {'ws': workspace_id})]


def get_receipt(db, run_id, workspace_id, lock=False):
    row = db.execute(text('SELECT receipt FROM runs WHERE id=:id AND workspace_id=:ws' + (' FOR UPDATE' if lock else '')), {'id': run_id, 'ws': workspace_id}).fetchone()
    if not row:
        raise HTTPException(404, 'Run not found')
    return row[0]


@app.get('/api/runs/{run_id}', response_model=Receipt)
@app.get('/api/runs/{run_id}/receipt', response_model=Receipt)
def get_run(run_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return get_receipt(db, run_id, workspace_id)


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
        workspace_id = store.ensure_workspace_seeded(db, actor)
        exists = db.execute(text('SELECT 1 FROM runs WHERE id=:id AND workspace_id=:ws'), {'id': run_id, 'ws': workspace_id}).fetchone()
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
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id, True)
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
        result = db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'), {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Run not found')
        # A saved revision resets approval, so the stale current-approval
        # projection must not remain: a leftover row would collide with the
        # fresh reapproval INSERT below (run_id PRIMARY KEY) and wrongly
        # present the superseded approval as current. Superseded
        # actor/time/revision evidence stays immutable in the receipt
        # revision_history, the receipt audit event_log, and the audit table.
        db.execute(text('DELETE FROM approvals WHERE run_id=:id'), {'id': run_id})
        store.audit(db, run_id, 'human_revised', actor, workspace_id)
    return revised


@app.post('/api/runs/{run_id}/approve', response_model=Receipt)
def approve(run_id: str, body: ApproveIn, actor: str = Depends(auth.actor)):
    from launchcrew import human_review
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id, True)
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
        result = db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'), {'receipt': json.dumps(receipt), 'state': receipt['approval_state'], 'id': run_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Run not found')
        # The approvals table is a current-approval projection (one row per
        # run): the plain INSERT keeps the PRIMARY KEY guard against double
        # approval and concurrent approval races, with no ON CONFLICT bypass
        # and no version-gate bypass (the stale/missing expected_revision
        # checks above still run first). A revise clears this row, so fresh
        # reapproval after edits inserts cleanly in the same transaction.
        db.execute(text('INSERT INTO approvals(run_id,approved_by) VALUES (:id,:actor)'), {'id': run_id, 'actor': actor})
        store.audit(db, run_id, 'approved_for_export', actor, workspace_id)
    return receipt


@app.post('/api/runs/{run_id}/export', response_model=Receipt)
def export(run_id: str, body: ExportIn, response: Response, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        from backend.photo_review import photo_block_reason
        from launchcrew import human_review
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id, True)
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
        result = db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'), {'receipt': json.dumps(exported), 'state': exported['approval_state'], 'id': run_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Run not found')
        store.audit(db, run_id, 'exported', actor, workspace_id)
    response.headers['Content-Disposition'] = 'attachment; filename="launchcrew-pack.json"'
    return exported



@app.post('/api/runs/{run_id}/photo-check', response_model=PhotoCheckResponse)
def photo_check(run_id: str, body: PhotoCheckIn, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _reject_when_running(get_receipt(db, run_id, workspace_id))
    from backend import photo_admission, sam
    from backend.photo_admission import AdmissionConflict, AdmissionNotFound, AdmissionRejected, AdmissionStale
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
            workspace_id = store.ensure_workspace_seeded(db, actor)
            receipt = get_receipt(db, run_id, workspace_id, True)
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
            result = db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'),
                       {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id, 'ws': workspace_id})
            if result.rowcount == 0:
                raise HTTPException(404, 'Run not found')
            db.execute(text('DELETE FROM approvals WHERE run_id=:id'), {'id': run_id})
            store.audit(db, run_id, 'photo_check_requested', actor, workspace_id)
        kept = photo_status_of(revised)
        check = PhotoCheckOut(method='not_run', label=None, reason=kept['reason'],
                              policy_version=PHOTO_POLICY_VERSION,
                              revision=revised['revision'], photo_state=kept['state'])
        return PhotoCheckResponse(check=check, receipt=revised, preview=None)
    try:
        row, preview, receipt = photo_admission.run_photo_check(
            store.engine(), run_id, parsed['raw'], parsed['mime'],
            body.expected_revision, body.expected_revision, actor=actor,
            workspace_id=store.workspace_for_actor(actor),
            frame=(parsed['width'], parsed['height']))
    except AdmissionNotFound:
        raise HTTPException(404, 'Run not found')
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
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id, True)
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
        result = db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'),
                   {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Run not found')
        db.execute(text('DELETE FROM approvals WHERE run_id=:id'), {'id': run_id})
        store.audit(db, run_id, 'photo_removed', actor, workspace_id)
    return PhotoRemoveOut(revision=revised['revision'], photo_state='no_photo',
                          approval_state='pending_approval')


MemoryKind = Literal['brand_fact', 'profile', 'approval_example', 'blocked_rule', 'voice_profile']


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


_MEMORY_PUBLIC_FIELDS = ('id', 'kind', 'title', 'content', 'source_run_id', 'created_at', 'updated_at')
_MEMORY_PUBLIC_SELECT = 'id, kind, title, content, source_run_id, created_at, updated_at'


def _public_memory_item(row):
    # Project only declared MemoryItemOut fields. workspace_id stays internal
    # and Strict extra=forbid rejects any leak, so never return SELECT * dicts.
    return {key: row[key] for key in _MEMORY_PUBLIC_FIELDS}


def memory_item(db, item_id, workspace_id, lock=False):
    row = db.execute(text('SELECT ' + _MEMORY_PUBLIC_SELECT + ' FROM memory_items WHERE id=:id AND workspace_id=:ws' + (' FOR UPDATE' if lock else '')), {'id': item_id, 'ws': workspace_id}).mappings().first()
    if row is None:
        raise HTTPException(404, 'Memory item not found')
    return _public_memory_item(row)


def _validate_voice_content(content):
    from launchcrew import voice_profile as voice_mod
    try:
        return voice_mod.validate_profile(content)
    except (TypeError, ValueError) as error:
        raise HTTPException(422, 'Invalid voice profile: ' + str(error))


def _voice_receipt_binding(items):
    from backend import adapter as adapter_mod
    from launchcrew.voice_profile import STYLE_ONLY_NOTICE
    try:
        snapshot, ref, _ = adapter_mod._voice_selection(items)
    except ValueError as error:
        raise HTTPException(422, str(error))
    if snapshot is None or ref is None:
        return None
    return {'id': ref.get('id'), 'title': ref.get('title'),
            'version': ref.get('version'), 'digest': ref.get('digest'),
            'example_count': len(snapshot.get('examples', [])),
            'banned_term_count': len(snapshot.get('banned_terms', [])),
            'banned_terms': list(snapshot.get('banned_terms', [])),
            'notice': STYLE_ONLY_NOTICE}


def _canonical_voice_updated_at(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        try:
            return aware.astimezone(timezone.utc).isoformat()
        except Exception:
            return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return None


def _voice_row_get(row, key):
    try:
        value = row[key]
    except Exception:
        try:
            value = dict(row).get(key)
        except Exception:
            return None
    return value


def _fetch_voice_row(db, voice_id, workspace_id, lock=False):
    row = db.execute(text('SELECT title, content, updated_at, xmin FROM memory_items WHERE id=:id AND workspace_id=:ws' + (' FOR UPDATE' if lock else '')),
                     {'id': voice_id, 'ws': workspace_id}).mappings().first()
    if row is None:
        return None
    return {'title': _voice_row_get(row, 'title'),
            'content': _voice_row_get(row, 'content'),
            'updated_at': _voice_row_get(row, 'updated_at'),
            'xmin': _voice_row_get(row, 'xmin')}


def _capture_voice_selection(db, items, workspace_id):
    from backend import adapter as adapter_mod
    try:
        snapshot, ref, _ = adapter_mod._voice_selection(items)
    except ValueError:
        raise
    if snapshot is None or ref is None:
        return None
    voice_id = ref.get('id')
    if not isinstance(voice_id, str):
        return None
    current = _fetch_voice_row(db, voice_id, workspace_id, lock=False)
    if current is None:
        return {'id': voice_id, 'title': ref.get('title'),
                'digest': ref.get('digest'), 'updated_at': None, 'xmin': None}
    return {'id': voice_id,
            'title': current.get('title'),
            'digest': ref.get('digest'),
            'updated_at': _canonical_voice_updated_at(current.get('updated_at')),
            'xmin': current.get('xmin')}


def _mark_sync_voice_stale_if_changed(db, receipt, workspace_id, actor, lock=True, selection=None):
    if not isinstance(receipt, dict):
        return False
    voice = receipt.get('voice_profile')
    if voice is None:
        return False
    if not isinstance(voice, dict) or not isinstance(voice.get('id'), str):
        receipt['voice_stale'] = True
        receipt['approvals'] = []
        receipt['approved_revision'] = None
        receipt['approval_binding'] = None
        receipt['approval_state'] = 'pending_approval'
        return True
    voice_id = voice['id']
    if isinstance(selection, dict) and isinstance(selection.get('digest'), str):
        old_digest = selection.get('digest')
    else:
        old_digest = voice.get('digest')
    if isinstance(selection, dict) and isinstance(selection.get('title'), str):
        old_title = selection.get('title')
    else:
        old_title = voice.get('title')
    if isinstance(selection, dict):
        old_updated = selection.get('updated_at')
        old_xmin = selection.get('xmin')
    else:
        old_updated = voice.get('source_updated_at') if isinstance(voice.get('source_updated_at'), str) else None
        old_xmin = voice.get('source_xmin')
    current_row = _fetch_voice_row(db, voice_id, workspace_id, lock=lock)
    if current_row is None:
        changed = True
    else:
        try:
            from launchcrew.voice_profile import snapshot_digest, validate_profile
            current_digest = snapshot_digest(validate_profile(current_row.get('content')))
        except (TypeError, ValueError):
            changed = True
        else:
            current_title = current_row.get('title')
            current_updated = _canonical_voice_updated_at(current_row.get('updated_at'))
            current_xmin = current_row.get('xmin')
            if current_digest != old_digest:
                changed = True
            elif isinstance(old_title, str) and isinstance(current_title, str) and current_title != old_title:
                changed = True
            elif old_updated is not None and current_updated is not None and current_updated != old_updated:
                changed = True
            elif old_xmin is not None and current_xmin is not None and current_xmin != old_xmin:
                changed = True
            else:
                changed = False
    if not changed:
        return False
    from launchcrew import human_review as human_review_mod
    receipt['voice_stale'] = True
    receipt['approvals'] = []
    receipt['approved_revision'] = None
    receipt['approval_binding'] = None
    receipt['approval_state'] = 'pending_approval'
    now = datetime.now(timezone.utc).isoformat()
    try:
        rev = human_review_mod.current_revision(receipt)
    except Exception:
        rev = 0
    events = list((receipt.get('audit') or {}).get('event_log') or [])
    events.append({'step': 'voice_invalidated', 'agent': 'system',
                   'profile': actor or 'system',
                   'action': ('Voice profile edited or deleted during pipeline; approval invalidated, '
                              'a new human revision check is required before export'),
                   'timestamp': now, 'revision': rev, 'voice_id': voice_id})
    receipt.setdefault('audit', {})['event_log'] = events
    return True


def _invalidate_voice_runs(db, workspace_id, voice_id, actor, action):
    import copy as copy_mod
    from launchcrew import human_review
    rows = db.execute(text("SELECT id, receipt FROM runs WHERE workspace_id=:ws AND receipt->'voice_profile'->>'id' = :vid FOR UPDATE"),
                      {'ws': workspace_id, 'vid': voice_id}).all()
    for run_id, receipt in rows:
        if not isinstance(receipt, dict):
            continue
        if receipt.get('status') not in ('completed', 'running'):
            continue
        voice = receipt.get('voice_profile')
        if not isinstance(voice, dict) or voice.get('id') != voice_id:
            continue
        revised = copy_mod.deepcopy(receipt)
        revised['voice_stale'] = True
        revised['approvals'] = []
        revised['approved_revision'] = None
        revised['approval_binding'] = None
        revised['approval_state'] = 'pending_approval'
        now = datetime.now(timezone.utc).isoformat()
        try:
            rev = human_review.current_revision(revised)
        except Exception:
            rev = 0
        events = list((revised.get('audit') or {}).get('event_log') or [])
        events.append({'step': 'voice_invalidated', 'agent': 'system',
                       'profile': actor or 'system',
                       'action': ('Voice profile %s; approval invalidated, '
                                  'a new human revision check is required before export' % action),
                       'timestamp': now, 'revision': rev, 'voice_id': voice_id})
        revised.setdefault('audit', {})['event_log'] = events
        db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'),
                   {'receipt': json.dumps(revised), 'state': 'pending_approval', 'id': run_id, 'ws': workspace_id})
        db.execute(text('DELETE FROM approvals WHERE run_id=:id'), {'id': run_id})
        store.audit(db, run_id, 'voice_invalidated', actor, workspace_id)


def insert_memory(db, body, actor, action, workspace_id, source_run_id=None):
    item_id = 'mem_' + uuid4().hex
    db.execute(text('INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id) VALUES (:id,:kind,:title,CAST(:content AS jsonb),:source,:ws)'),
               {'id': item_id, 'kind': body.kind, 'title': body.title, 'content': json.dumps(body.content), 'source': source_run_id, 'ws': workspace_id})
    store.audit(db, source_run_id, action, actor, workspace_id)
    return memory_item(db, item_id, workspace_id)


@app.get('/api/memory', response_model=list[MemoryItemOut])
def list_memory(actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        rows = db.execute(text('SELECT ' + _MEMORY_PUBLIC_SELECT + ' FROM memory_items WHERE workspace_id=:ws ORDER BY created_at,id'), {'ws': workspace_id}).mappings().all()
        return [_public_memory_item(row) for row in rows]


@app.post('/api/memory', response_model=MemoryItemOut, status_code=201)
def create_memory(body: MemoryItemIn, actor: str = Depends(auth.actor)):
    if body.kind == 'voice_profile':
        _validate_voice_content(body.content)
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return insert_memory(db, body, actor, 'memory_item_created', workspace_id)


@app.get('/api/memory/{item_id}', response_model=MemoryItemOut)
def get_memory(item_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return memory_item(db, item_id, workspace_id)


@app.put('/api/memory/{item_id}', response_model=MemoryItemOut)
def edit_memory(item_id: str, body: MemoryItemEdit, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        item = memory_item(db, item_id, workspace_id, lock=True)
        if 'kind' in body.model_fields_set and body.kind != item['kind']:
            raise HTTPException(422, 'Memory kind is immutable')
        if item['kind'] == 'voice_profile':
            _validate_voice_content(body.content)
        result = db.execute(text('UPDATE memory_items SET title=:title,content=CAST(:content AS jsonb),updated_at=now() WHERE id=:id AND workspace_id=:ws'),
                   {'id': item_id, 'title': body.title, 'content': json.dumps(body.content), 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Memory item not found')
        store.audit(db, None, 'memory_item_edited', actor, workspace_id)
        if item['kind'] == 'voice_profile':
            _invalidate_voice_runs(db, workspace_id, item_id, actor, 'edited')
        return memory_item(db, item_id, workspace_id)


@app.delete('/api/memory/{item_id}', status_code=204)
def delete_memory(item_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        item = memory_item(db, item_id, workspace_id, lock=True)
        result = db.execute(text('DELETE FROM memory_items WHERE id=:id AND workspace_id=:ws'), {'id': item_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Memory item not found')
        store.audit(db, None, 'memory_item_deleted', actor, workspace_id)
        if item['kind'] == 'voice_profile':
            _invalidate_voice_runs(db, workspace_id, item_id, actor, 'deleted')
    return Response(status_code=204)


@app.post('/api/memory/from-run/{run_id}', response_model=MemoryItemOut, status_code=201)
def learn_memory(run_id: str, body: LearnMemory, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        from launchcrew import human_review
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id, True)
        if receipt['approval_state'] != 'approved_for_export':
            raise HTTPException(409, 'Learning requires explicit run approval')
        if not human_review.exportable(receipt):
            raise HTTPException(409, 'Learning requires approval of the latest revision')
        draft = human_review.current_draft(receipt)
        content = ({'idea': receipt['idea'], 'post': draft['post'], 'email': draft['email']}
                   if body.kind == 'approval_example' else {'blocked_claims': receipt['checker_v1']['blocked_claims']})
        item = MemoryItemIn(kind=body.kind, title=f'{body.kind}: {run_id}', content=content)
        return insert_memory(db, item, actor, 'memory_item_learned', workspace_id, run_id)


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
    voice_id_a: str | None = None
    voice_id_b: str | None = None
    voice_title_a: str | None = None
    voice_title_b: str | None = None
    voice_version_a: str | None = None
    voice_version_b: str | None = None
    voice_changed: bool = False
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


def _voice_summary(receipt):
    raw = receipt.get('voice_profile') if isinstance(receipt, dict) else None
    if not isinstance(raw, dict):
        return None, None, None
    voice_id = raw.get('id') if isinstance(raw.get('id'), str) else None
    title = raw.get('title') if isinstance(raw.get('title'), str) else None
    version = raw.get('version') if isinstance(raw.get('version'), str) else None
    return voice_id, title, version


def diff_receipts(a, b):
    bindings_a = {stage: stage_binding(a, stage) for stage in ('scout', 'maker', 'checker')}
    bindings_b = {stage: stage_binding(b, stage) for stage in ('scout', 'maker', 'checker')}
    voice_a = _voice_summary(a)
    voice_b = _voice_summary(b)
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
              'memory_ids_b': [m.get('id') for m in b.get('memory_used', []) if isinstance(m, dict)],
              'voice_id_a': voice_a[0], 'voice_id_b': voice_b[0],
              'voice_title_a': voice_a[1], 'voice_title_b': voice_b[1],
              'voice_version_a': voice_a[2], 'voice_version_b': voice_b[2],
              'voice_changed': voice_a != voice_b}
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
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return diff_receipts(get_receipt(db, run_a, workspace_id), get_receipt(db, run_b, workspace_id))


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


_CAMPAIGN_PUBLIC_FIELDS = ('id', 'idea', 'agent_name', 'created_at')


def campaign_detail(db, campaign_id, workspace_id):
    row = db.execute(text('SELECT id, idea, agent_name, created_at FROM campaigns WHERE id=:id AND workspace_id=:ws'), {'id': campaign_id, 'ws': workspace_id}).mappings().first()
    if row is None:
        raise HTTPException(404, 'Campaign not found')
    # Project only declared CampaignOut fields. workspace_id stays internal
    # and Strict extra=forbid rejects any leak, so never return SELECT * dicts.
    result = {key: row[key] for key in _CAMPAIGN_PUBLIC_FIELDS}
    result['days'] = []
    for day, receipt in db.execute(text('SELECT d.day,r.receipt FROM campaign_days d JOIN runs r ON r.id=d.run_id WHERE d.campaign_id=:id AND d.workspace_id=:ws AND r.workspace_id=:ws ORDER BY d.day'), {'id': campaign_id, 'ws': workspace_id}):
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


def _insert_campaign_committed_day(db, campaign_id, day, run_id, receipt, maker_name, actor, workspace_id, voice_selection):
    if not isinstance(receipt, dict):
        raise ValueError('Campaign day receipt unavailable')
    status = receipt.get('status')
    if status == 'completed':
        _mark_sync_voice_stale_if_changed(db, receipt, workspace_id, actor, lock=True, selection=voice_selection)
        facts = (receipt.get('scout') or {}).get('facts_used', []) if isinstance(receipt.get('scout'), dict) else []
        audit_action = 'run_created'
        stored = receipt
    else:
        stored = dict(receipt)
        stored['approval_state'] = stored.get('approval_state') or 'pending_approval'
        facts = []
        audit_action = 'run_failed'
    db.execute(text('INSERT INTO runs(id,receipt,agent_name,state,workspace_id) VALUES (:id,CAST(:receipt AS jsonb),:agent,:state,:ws)'),
               {'id': run_id, 'receipt': json.dumps(stored), 'agent': maker_name.lower(), 'state': stored['approval_state'], 'ws': workspace_id})
    db.execute(text('INSERT INTO memory(run_id,facts) VALUES (:id,CAST(:facts AS jsonb))'),
               {'id': run_id, 'facts': json.dumps(facts)})
    db.execute(text('INSERT INTO campaign_days(campaign_id,day,run_id,workspace_id) VALUES (:id,:day,:run,:ws)'),
               {'id': campaign_id, 'day': day, 'run': run_id, 'ws': workspace_id})
    store.audit(db, run_id, audit_action, actor, workspace_id)
    return stored


@app.post('/api/campaigns', response_model=CampaignOut, status_code=201)
def create_campaign(body: RunInput, actor: str = Depends(auth.actor)):
    from launchcrew.facts import parse_product_facts
    from backend import model_admission
    product_facts_raw = body.product_facts.model_dump() if body.product_facts is not None else None
    parse_product_facts(product_facts_raw)
    campaign_id = 'camp_' + uuid4().hex
    engine = store.engine()
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        legacy, scout, maker, checker = load_stage_profiles(db, body, workspace_id)
        items = load_memory_selection(db, body.memory_ids, workspace_id)
        scout_name, maker_name, checker_name = stage_names(body)
        voice_selection = _capture_voice_selection(db, items, workspace_id)
        voice_binding = _voice_receipt_binding(items)
    run_ids = []
    seen = set()
    while len(run_ids) < 7:
        candidate = 'run_' + uuid4().hex
        if candidate not in seen:
            seen.add(candidate)
            run_ids.append(candidate)
    staged = []
    for day in range(1, 8):
        _angle, brief, brief_claim = CAMPAIGN_BRIEF_BY_DAY[day]
        run_id = run_ids[day - 1]
        try:
            factory = model_admission.admission_factory_for_run(engine, run_id)
            receipt = adapter.execute(run_id, body.idea, legacy, body.seed_unverified_claim,
                                      memory_items=items, checker_profile=body.checker_profile,
                                      brief=brief, campaign_day=day, extra_claims=[brief_claim],
                                      scout_profile=scout, maker_profile=maker, checker_agent=checker,
                                      product_facts=product_facts_raw,
                                      model_admission_factory=factory)
        except Exception as error:
            failed = {'receipt_version': '1.0', 'run_id': run_id, 'generated_at': datetime.now(timezone.utc).isoformat(),
                      'status': 'failed', 'brand': 'LaunchCrew', 'mode': 'demo_no_submit',
                      'idea': body.idea, 'approvals': [], 'completed_steps': [],
                      'error_type': type(error).__name__[:64] or 'PipelineError',
                      'approval_state': 'pending_approval', 'checker_profile': body.checker_profile,
                      'stage_bindings': {'scout': scout_name, 'maker': maker_name, 'checker': checker_name},
                      'summary': {'submit_attempted': False, 'submit_completed': False},
                      'audit': {'event_log': [], 'stopped_reason': 'campaign_day_%d' % day},
                      'voice_profile': voice_binding, 'campaign_day': day, 'campaign_brief': brief}
            staged.append((day, run_id, failed))
            continue
        staged.append((day, run_id, receipt))
    with store.connect() as db:
        commit_ws = store.ensure_workspace_seeded(db, actor)
        db.execute(text('INSERT INTO campaigns(id,idea,agent_name,workspace_id) VALUES (:id,:idea,:agent,:ws)'),
                   {'id': campaign_id, 'idea': body.idea, 'agent': maker_name, 'ws': commit_ws})
        for day, run_id, receipt in staged:
            _insert_campaign_committed_day(db, campaign_id, day, run_id, receipt, maker_name, actor, commit_ws, voice_selection)
    with store.connect() as db:
        detail_ws = store.ensure_workspace_seeded(db, actor)
        return campaign_detail(db, campaign_id, detail_ws)


@app.get('/api/campaigns', response_model=list[CampaignOut])
def list_campaigns(actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        ids = db.execute(text('SELECT id FROM campaigns WHERE workspace_id=:ws ORDER BY created_at,id'), {'ws': workspace_id}).scalars().all()
        return [campaign_detail(db, campaign_id, workspace_id) for campaign_id in ids]


@app.get('/api/campaigns/{campaign_id}', response_model=CampaignOut)
def get_campaign(campaign_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return campaign_detail(db, campaign_id, workspace_id)


def campaign_run(campaign_id, day, workspace_id):
    with store.connect() as db:
        run_id = db.execute(text('SELECT d.run_id FROM campaign_days d JOIN campaigns c ON c.id=d.campaign_id JOIN runs r ON r.id=d.run_id WHERE d.campaign_id=:id AND d.day=:day AND d.workspace_id=:ws AND c.workspace_id=:ws AND r.workspace_id=:ws'), {'id': campaign_id, 'day': day, 'ws': workspace_id}).scalar()
        if run_id is None:
            raise HTTPException(404, 'Campaign day not found')
        return run_id


@app.post('/api/campaigns/{campaign_id}/days/{day}/approve', response_model=Receipt)
def approve_campaign_day(campaign_id: str, day: int, body: ApproveIn, actor: str = Depends(auth.actor)):
    workspace_id = store.workspace_for_actor(actor)
    return approve(campaign_run(campaign_id, day, workspace_id), body, actor)


@app.post('/api/campaigns/{campaign_id}/days/{day}/export', response_model=Receipt)
def export_campaign_day(campaign_id: str, day: int, body: ExportIn, response: Response, actor: str = Depends(auth.actor)):
    workspace_id = store.workspace_for_actor(actor)
    return export(campaign_run(campaign_id, day, workspace_id), body, response, actor)


# Slice 6 owner-reported outcome loop after an approved export.
# Reuses launchcrew.outcome_log bounds; rows are immutable self-reports,
# never provider-measured, with no ROI, auto-post, or seeding.

OutcomeChannel = Literal['email', 'facebook', 'in_person', 'instagram',
                         'linkedin', 'other', 'phone', 'sms', 'web', 'x']

if set(get_args(OutcomeChannel)) != set(OUTCOME_KNOWN_CHANNELS):
    raise RuntimeError('Outcome channels must match launchcrew.outcome_log')
if OUTCOME_PROVENANCE != 'self_reported':
    raise RuntimeError('Outcome provenance must stay self_reported')


class OutcomeIn(Strict):
    channel: OutcomeChannel
    posted_date: str = Field(min_length=10, max_length=10)
    likes: StrictInt = Field(ge=0, le=OUTCOME_MAX_COUNT)
    comments: StrictInt = Field(ge=0, le=OUTCOME_MAX_COUNT)
    clicks: StrictInt = Field(ge=0, le=OUTCOME_MAX_COUNT)
    sales: StrictInt = Field(ge=0, le=OUTCOME_MAX_COUNT)
    note: str = Field(min_length=1, max_length=OUTCOME_MAX_NOTE_LENGTH)

    @field_validator('posted_date')
    @classmethod
    def _exact_posted_date(cls, value):
        if not isinstance(value, str):
            raise ValueError('posted_date must be a string in YYYY-MM-DD format')
        if len(value) != 10 or value[4] != '-' or value[7] != '-':
            raise ValueError('posted_date must be in YYYY-MM-DD format')
        parts = value.split('-')
        if (len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2
                or len(parts[2]) != 2
                or not all(part.isascii() and part.isdigit() for part in parts)):
            raise ValueError('posted_date must be in YYYY-MM-DD format')
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        try:
            date_cls(year, month, day)
        except ValueError:
            raise ValueError('posted_date is not a real calendar date')
        return value

    @field_validator('note')
    @classmethod
    def _safe_note(cls, value):
        if not isinstance(value, str):
            raise ValueError('note must be a string')
        if not value.strip():
            raise ValueError('note must not be empty')
        if len(value) > OUTCOME_MAX_NOTE_LENGTH:
            raise ValueError('note must be <= 500 characters')
        for char in value:
            code = ord(char)
            if code < 32 or code == 127:
                raise ValueError('note contains unsafe control characters')
        return value


class OutcomeOut(Strict):
    id: str
    run_id: str
    export_revision: int
    channel: OutcomeChannel
    posted_date: str
    likes: int
    comments: int
    clicks: int
    sales: int
    note: str
    provenance: Literal['self_reported']
    actor: str
    created_at: datetime


_OUTCOME_PUBLIC_FIELDS = ('id', 'run_id', 'export_revision', 'channel',
                          'posted_date', 'likes', 'comments', 'clicks',
                          'sales', 'note', 'provenance', 'actor',
                          'created_at')
_OUTCOME_PUBLIC_SELECT = ('id, run_id, export_revision, channel, posted_date, '
                          'likes, comments, clicks, sales, note, provenance, '
                          'actor, created_at')


def _public_outcome(row):
    # Project only declared OutcomeOut fields. workspace_id stays internal
    # and Strict extra=forbid rejects any leak, so never return SELECT * dicts.
    # posted_date leaves Postgres as a date; the contract keeps the exact
    # YYYY-MM-DD string from launchcrew.outcome_log.
    posted = row['posted_date']
    if hasattr(posted, 'isoformat'):
        posted = posted.isoformat()
    result = {key: row[key] for key in _OUTCOME_PUBLIC_FIELDS if key != 'posted_date'}
    result['posted_date'] = posted
    return result


def _outcome_export_revision(receipt):
    from backend.photo_review import photo_block_reason
    from launchcrew import human_review
    if receipt.get('status') == 'failed':
        raise HTTPException(422, 'Owner outcomes require a completed run')
    if receipt.get('status') != 'completed':
        raise HTTPException(409, 'Owner outcomes require a completed run; reload and retry after it completes')
    if receipt.get('approval_state') != 'approved_for_export':
        raise HTTPException(409, 'Owner outcomes require an approved export; approve the latest revision and export before logging outcomes')
    current = human_review.current_revision(receipt)
    if receipt.get('approved_revision') != current:
        raise HTTPException(409, 'Owner outcomes require approval of the latest revision; a later edit needs fresh approval and export before new logs')
    if receipt.get('exported_revision') != current:
        raise HTTPException(409, 'Owner outcomes require export of the latest revision; export before logging outcomes')
    photo_reason = photo_block_reason(receipt)
    if photo_reason is not None:
        raise HTTPException(422, photo_reason)
    if not human_review.exportable(receipt):
        raise HTTPException(409, 'Owner outcomes require a currently exportable revision; reapprove and export before logging outcomes')
    return current


@app.post('/api/runs/{run_id}/outcomes', response_model=OutcomeOut, status_code=201)
def create_outcome(run_id: str, body: OutcomeIn, actor: str = Depends(auth.actor)):
    """Log one immutable owner self-report for the current exported revision.

    Owner-entered only, never provider-measured. Requires a signed-in
    actor, an owned run, and an approved current exported revision. The
    export revision, workspace, actor, provenance, and server timestamp
    come from the server; the client supplies only channel, posted date,
    metrics, and note. Historical rows keep their stored export revision
    after later edits; new logs stay blocked until reapproval and reexport.
    """
    if not actor or actor == 'demo_placeholder':
        raise HTTPException(401, 'Sign in required to log owner-reported outcomes')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id, True)
        _reject_when_running(receipt)
        export_revision = _outcome_export_revision(receipt)
        outcome_id = 'out_' + uuid4().hex
        db.execute(text('INSERT INTO run_outcomes(id, run_id, workspace_id, export_revision, channel, posted_date, likes, comments, clicks, sales, note, provenance, actor)'
                        ' VALUES (:id, :run, :ws, :rev, :channel, CAST(:posted AS date), :likes, :comments, :clicks, :sales, :note, :prov, :actor)'),
                   {'id': outcome_id, 'run': run_id, 'ws': workspace_id, 'rev': export_revision,
                    'channel': body.channel, 'posted': body.posted_date, 'likes': body.likes,
                    'comments': body.comments, 'clicks': body.clicks, 'sales': body.sales,
                    'note': body.note, 'prov': OUTCOME_PROVENANCE, 'actor': actor})
        store.audit(db, run_id, 'outcome_logged', actor, workspace_id)
        row = db.execute(text('SELECT ' + _OUTCOME_PUBLIC_SELECT + ' FROM run_outcomes WHERE id=:id AND workspace_id=:ws'),
                         {'id': outcome_id, 'ws': workspace_id}).mappings().first()
        if row is None:
            raise HTTPException(404, 'Run not found')
        return _public_outcome(row)


@app.get('/api/runs/{run_id}/outcomes', response_model=list[OutcomeOut])
def list_outcomes(run_id: str, actor: str = Depends(auth.actor)):
    """List owner self-reports for an owned run, oldest first.

    Owner-entered only, never provider-measured. Requires a signed-in
    actor, matching POST. Reads are workspace scoped and return 404 for
    foreign runs. Historical rows keep their stored export revision after
    later edits; this read never gates on the current approval or export
    state.
    """
    if not actor or actor == 'demo_placeholder':
        raise HTTPException(401, 'Sign in required to read owner-reported outcomes')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        exists = db.execute(text('SELECT 1 FROM runs WHERE id=:id AND workspace_id=:ws'),
                            {'id': run_id, 'ws': workspace_id}).fetchone()
        if not exists:
            raise HTTPException(404, 'Run not found')
        rows = db.execute(text('SELECT ' + _OUTCOME_PUBLIC_SELECT + ' FROM run_outcomes WHERE run_id=:id AND workspace_id=:ws ORDER BY created_at, id'),
                          {'id': run_id, 'ws': workspace_id}).mappings().all()
        return [_public_outcome(row) for row in rows]
