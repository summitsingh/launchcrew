"""Typed FastAPI demo API over the preserved Python pipeline."""
from contextlib import asynccontextmanager
import copy
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
from backend import adapter, store, auth, drive_intake
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


ProductFactSource = Literal['owner', 'pasted_text', 'memory', 'listing', 'campaign_brief', 'demo_template', 'drive_file']


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


StructuredFieldName = Literal['material', 'contents', 'size', 'price', 'allowed_claim', 'founder_note']


class StructuredImportIn(Strict):
    text: str = Field(max_length=10000)
    source: ImportSource
    active_digest: str | None = Field(default=None, max_length=128)
    confirm_replace: bool = False


class StructuredSuggestionItem(Strict):
    field: StructuredFieldName
    text: str
    source: ImportSource
    product_fact_source: ProductFactSource
    status: Literal['unconfirmed'] = 'unconfirmed'
    confirmed: Literal[False] = False
    index: int


class StructuredImportOut(Strict):
    status: Literal['unconfirmed'] = 'unconfirmed'
    source: ImportSource
    product_fact_source: ProductFactSource
    field_suggestions: list[StructuredSuggestionItem]
    proposal_digest: str
    replaced: bool = False
    truncated: bool
    dropped_duplicates: int
    dropped_overlong: int
    dropped_empty: int
    parser_version: str


class FormatSpec(BaseModel):
    model_config = ConfigDict(extra='allow')
    format_kind: str | None = Field(default=None, max_length=64)
    format: str | None = Field(default=None, max_length=64)
    frame_count: int | None = Field(default=None, ge=0, le=100)
    frames: list[str] | None = None
    aspect_ratio: str | None = Field(default=None, max_length=16)
    hook_text: str | None = Field(default=None, max_length=2000)
    hook: str | None = Field(default=None, max_length=2000)
    shots: list[str] | None = None
    shot_list: list[str] | None = None
    frame_ideas: list[str] | None = None
    target_surface: str | None = Field(default=None, max_length=64)
    surface: str | None = Field(default=None, max_length=64)


class FormatCheckOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    passed: bool = False
    format: str | None = None
    version: str = 'format-library/v1'
    reasons: list[str] = []


class BrandKitOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    version: str = ''
    digest: str = ''
    brand_colors: list[str] = []
    fonts: list[str] = []
    logo_reference: str | None = None
    banned_rules: list[str] = []


class ChannelCapabilityOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    channel: str = ''
    allowed_formats: list[str] = []
    caption_limit: int = 0
    media_constraints: dict[str, Any] = {}


class FormatDefinitionOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    format: str = ''
    label: str = ''
    rule: str = ''


class TrendFormatOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    label: str = ''
    source_label: str = ''
    sanitized_guidance: str = ''
    screened_out_claims: list[str] = []
    role: str = 'maker_angle_guidance_only'
    guidance_only: bool = True
    fact_source: bool = False


class TrendScreenIn(Strict):
    label: str = Field(default='', max_length=2000)
    source_label: str = Field(default='', max_length=200)


class RunInput(Idea):
    agent_name: str = Field(description='Legacy Maker selector. Preserved for compatibility. Maker stage uses maker_name when provided, else agent_name.')
    trend_label: str | None = Field(default=None, max_length=280, description='Optional trend format description: Maker angle guidance only, never a fact source.')
    trend_source: str | None = Field(default=None, max_length=200, description='Required source label when trend_label is provided, naming where the trend was seen.')
    scout_name: str | None = Field(default=None, description='Scout stage agent name. Defaults to built-in Scout.')
    maker_name: str | None = Field(default=None, description='Maker stage agent name. Defaults to agent_name for compatibility.')
    checker_name: str | None = Field(default=None, description='Checker stage agent name. Defaults to built-in Checker.')
    seed_unverified_claim: bool = False
    memory_ids: list[str] = []
    checker_profile: Literal['standard', 'strict'] = Field(default='standard', description='Legacy strictness. Strict adds the superlatives policy. Checker agent policies add blocks on top.')
    product_facts: ProductFactsInput | None = Field(default=None, description='Slice 1 owner product facts. Only explicitly confirmed fields become evidence; suggestions never do. Absent means legacy demo-template mode.')
    fact_variant_id: str | None = Field(default=None, max_length=128, description='Facts-library variant to inherit confirmed facts from. Supply either this or product_facts, never both. The run binds a snapshot copy; later library edits never rewrite this run.')
    waive_missing_core_facts: bool = Field(default=False, description='Explicit owner waiver for missing core facts (material, contents, size, price). When owner input lacks a confirmed core fact and this is false, the run is refused with 422. When true, the waiver is recorded on the receipt.')
    format_spec: FormatSpec | None = Field(default=None, description='Optional S2 format spec (format_kind, frame_count, aspect_ratio, hook_text, shots, frame_ideas, target_surface). Checker enforces the format rules and records format_check on the receipt; a failed check blocks approval.')


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
    latency_ms: float = 0.0
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
    missing_core_facts: list[str] = []
    missing_core_waived: bool = False


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
    brand_kit: BrandKitOut | None = Field(default=None, description='S2 brand kit version and digest recorded from the voice profile brand fields. Changing a brand color, font, logo reference, or banned rule changes the recorded version.')
    format_spec: dict[str, Any] | None = Field(default=None, description='S2 format spec supplied with the run, when any.')
    format_check: FormatCheckOut | None = Field(default=None, description='S2 Checker-enforced format check result. A failed check blocks approval with a plain rule reason.')
    trend_format: TrendFormatOut | None = Field(default=None, description='S3 optional trend format attachment: Maker angle guidance only, never a fact source. Absent when no trend was attached.')


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
app.include_router(drive_intake.router)


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
    # Surface the real validation reason so custom agent saves show why
    # they failed instead of a bare 422 banner. Validator messages carry
    # only field and rule names, never secrets or raw input.
    return JSONResponse({'detail': 'Validation failed: ' + str(error)}, status_code=422)


@app.exception_handler(IntegrityError)
async def conflict(request, error):
    # Name collisions on agent saves report the cause instead of a bare
    # 409 banner. Only the constraint outcome is shared, never input.
    return JSONResponse({'detail': 'Conflict: agent name already exists'}, status_code=409)


@app.get('/api/health')
def health() -> dict[str, str]:
    with store.connect() as db:
        db.execute(text('SELECT 1'))
    return {'status': 'ok', 'auth': auth.health_auth_label(), 'approval_by': 'signed_in_user' if auth.enabled() else 'demo_placeholder'}


@app.get('/api/checker-policies', response_model=CheckerPoliciesOut)
def checker_policies(actor: str = Depends(auth.actor)):
    return {'supported': describe_supported(), 'floor_note': FLOOR_NOTE, 'matching': MATCHING_NOTE}


def _resolve_trend(body):
    """Build the trend attachment for a run or campaign body, or None.

    No trend fields means no change. A trend label without a non-empty
    source label is refused with 422 naming source_label. The returned
    attachment is Maker angle guidance only, never a fact source.
    """
    from launchcrew import trend_picker
    label = getattr(body, 'trend_label', None)
    source = getattr(body, 'trend_source', None)
    blank_label = not (isinstance(label, str) and label.strip())
    blank_source = not (isinstance(source, str) and source.strip())
    if blank_label and blank_source:
        return None
    try:
        return trend_picker.build_trend_attachment(label, source)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get('/api/trends/presets')
def trend_presets(actor: str = Depends(auth.actor)):
    """Return the trend source label presets for the picker UI."""
    from launchcrew import trend_picker
    return {'presets': list(trend_picker.TREND_SOURCE_PRESETS),
            'note': 'Trends are Maker angle guidance only, never a fact source.'}


@app.post('/api/trends/screen')
def screen_trend(body: TrendScreenIn, actor: str = Depends(auth.actor)):
    """Screen a candidate trend label without creating a run.

    Stateless preview: returns the sanitized guidance and the list of
    screened terms. A label without a source label is refused with 422
    naming source_label.
    """
    from launchcrew import trend_picker
    try:
        attachment = trend_picker.build_trend_attachment(body.label, body.source_label)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if attachment is None:
        return {'attachment': None,
                'note': 'No trend provided; the run behaves exactly as today.'}
    return {'attachment': attachment,
            'note': 'Trends are Maker angle guidance only, never a fact source.'}


@app.get('/api/formats', response_model=list[FormatDefinitionOut])
def list_formats(actor: str = Depends(auth.actor)):
    """List the S2 format library with each Checker-enforced rule."""
    from launchcrew.format_library import list_formats as _list_formats
    return _list_formats()


@app.post('/api/formats/check', response_model=FormatCheckOut)
def check_format_route(body: FormatSpec, actor: str = Depends(auth.actor)):
    """Check one format spec against the Checker-enforced format rules.

    Stateless and read-only: no runs, memory writes, model calls, or
    network. Returns a pass/fail record with plain human-readable
    reasons naming the rule that failed.
    """
    from launchcrew.format_library import check_format as _check_format
    return _check_format(body.model_dump(exclude_none=False))


@app.get('/api/channel-capabilities', response_model=list[ChannelCapabilityOut])
def list_channel_capabilities(actor: str = Depends(auth.actor)):
    """Return the per-channel capabilities table (account_capabilities pattern, as data)."""
    from launchcrew.format_library import list_channel_capabilities as _list_capabilities
    return _list_capabilities()


class QuickstartTemplateMeta(BaseModel):
    model_config = ConfigDict(extra='allow')
    template_id: str
    title: str
    kind: str
    fictional: bool
    confirmation_required: bool


class QuickstartTemplateBody(BaseModel):
    model_config = ConfigDict(extra='allow')
    template_id: str
    title: str
    kind: str
    fictional: bool
    confirmation_required: bool
    fictional_note: str
    description: str
    approved_claims: list[str]
    sources: list[str]
    suggested_facts: dict[str, Any]


@app.get('/api/quickstart-templates', response_model=list[QuickstartTemplateMeta])
def list_quickstart_templates(actor: str = Depends(auth.actor)):
    from launchcrew import quickstart_templates as templates
    return templates.list_quickstart_templates()


@app.get('/api/quickstart-templates/{template_id}', response_model=QuickstartTemplateBody)
def get_quickstart_template(template_id: str, actor: str = Depends(auth.actor)):
    from launchcrew import quickstart_templates as templates
    try:
        return templates.load_quickstart_template(template_id)
    except KeyError:
        raise HTTPException(404, 'Quick-start template not found')
    except ValueError as exc:
        raise HTTPException(422, 'Quick-start template is invalid: ' + str(exc))


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


def _structured_out(result, product_source, replaced=False):
    field_suggestions = [{'field': item['field'], 'text': item['text'],
                          'source': item['source'],
                          'product_fact_source': product_source,
                          'status': 'unconfirmed', 'confirmed': False,
                          'index': item['index']} for item in result['field_suggestions']]
    return {'status': 'unconfirmed', 'source': result['source'],
            'product_fact_source': product_source,
            'field_suggestions': field_suggestions,
            'proposal_digest': result['proposal_digest'],
            'replaced': replaced,
            'truncated': result['truncated'],
            'dropped_duplicates': result['dropped_duplicates'],
            'dropped_overlong': result['dropped_overlong'],
            'dropped_empty': result['dropped_empty'],
            'parser_version': result['parser_version']}


@app.post('/api/import-suggestions/structured', response_model=StructuredImportOut)
def import_suggestions_structured(body: StructuredImportIn, actor: str = Depends(auth.actor)):
    """Parse pasted listing or social text into per-field unconfirmed suggestions.

    Stateless owner intake: deterministic stdlib parse only, no database
    writes, no memory writes, no model calls, no network. Every field
    suggestion returns confirmed false with provenance; explicit per-field
    product-facts confirmation is still required before any evidence use.
    A new paste never silently replaces a pending proposal: callers pass
    the pending proposal digest as active_digest, and a different new
    proposal without confirm_replace is refused with 409 carrying the held
    proposal, so the owner can keep both or confirm replacement.
    """
    from launchcrew.import_suggestions import (
        REPLACE_WARNING,
        is_replace_conflict,
        parse_structured_import,
    )
    result = parse_structured_import(body.text, body.source)
    mapping = {'listing': 'listing', 'instagram_bio': 'pasted_text',
               'instagram_caption': 'pasted_text'}
    product_source = mapping[body.source]
    if is_replace_conflict(body.active_digest, result['proposal_digest'], body.confirm_replace):
        held = _structured_out(result, product_source)
        raise HTTPException(409, detail={
            'message': REPLACE_WARNING,
            'active_digest': (body.active_digest or '').strip().lower(),
            'proposal_digest': result['proposal_digest'],
            'proposal': held,
        })
    replaced = bool(
        body.confirm_replace and body.active_digest
        and (body.active_digest or '').strip().lower() != result['proposal_digest']
    )
    return _structured_out(result, product_source, replaced=replaced)


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


class ChannelVariantOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    channel: str = ''
    variant_kind: str = 'presentation_candidate'
    text: str = ''
    subject: str = ''
    content_valid: bool = False
    exportable: bool = False
    independently_exportable: bool = False
    requires_checker_binding: bool = True
    status: str = ''
    reason: str = ''
    trim_note: str = ''
    char_count: int = 0
    kept_sentences: int = 0
    total_sentences: int = 0
    omitted_sentences: int = 0
    approval_note: str = ''
    capability: dict[str, Any] | None = None


class ChannelCopyOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    approved_by: str = ''
    channel: str = ''
    text: str = ''
    subject: str = ''
    revision: int = 0
    receipt_id: str = ''
    binding_version: str = ''
    binding_digest: str = ''
    copy_authorized: bool = False
    note: str = ''


class DraftCopyIn(Strict):
    kind: Literal['post', 'email']
    expected_revision: StrictInt | None = Field(default=None, ge=0)


class DraftCopyOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    approved_by: str = ''
    kind: str = ''
    text: str = ''
    revision: int = 0
    receipt_id: str = ''
    binding_version: str = ''
    binding_digest: str = ''
    copy_authorized: bool = False
    note: str = ''


class ChannelVariantsOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    capabilities: list[dict[str, Any]] = []
    bundle_version: str = 'checked-channel-variants/v1'
    receipt_id: str = ''
    revision: int = 0
    approval_state: str = ''
    binding_version: str = ''
    binding_digest: str = ''
    channel_approvals: dict[str, Any] = {}
    facts_mode: str = ''
    facts_label: str = ''
    template_used: bool = False
    confirmed_claims_count: int = 0
    draft_source: str = 'current post draft'
    all_content_valid: bool = False
    no_auto_publish: bool = True
    note: str = ''
    x: ChannelVariantOut
    linkedin: ChannelVariantOut
    instagram: ChannelVariantOut
    email: ChannelVariantOut
    facebook: ChannelVariantOut
    tiktok: ChannelVariantOut
    shopify: ChannelVariantOut
    provenance: dict[str, Any] = {}


class LaunchMatrixOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    capabilities: list[dict[str, Any]] = []
    bundle_version: str = 'checked-launch-matrix/v1'
    receipt_id: str = ''
    revision: int = 0
    approval_state: str = ''
    binding_version: str = ''
    binding_digest: str = ''
    channel_approvals: dict[str, Any] = {}
    facts_mode: str = ''
    facts_label: str = ''
    template_used: bool = False
    confirmed_claims_count: int = 0
    draft_source: str = 'current post draft'
    all_content_valid: bool = False
    no_auto_publish: bool = True
    note: str = ''
    x: ChannelVariantOut
    linkedin: ChannelVariantOut
    instagram: ChannelVariantOut
    email: ChannelVariantOut
    facebook: ChannelVariantOut
    tiktok: ChannelVariantOut
    shopify: ChannelVariantOut
    provenance: dict[str, Any] = {}


class VerifyLandingPageIn(Strict):
    landing_html: str = Field(min_length=1, max_length=200000)
    landing_url: str | None = Field(default=None, max_length=2000)


class LandingParityOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    version: str = 'landing-parity/v1'
    overall_passed: bool = False
    parity_passed: bool = False
    legal_compliance_passed: bool = False
    ad_prices: list[str] = Field(default_factory=list)
    landing_prices: list[str] = Field(default_factory=list)
    unmatched_ad_prices: list[str] = Field(default_factory=list)
    detected_policies: list[str] = Field(default_factory=list)
    missing_policies: list[str] = Field(default_factory=list)


@app.post('/api/runs', response_model=Receipt, status_code=201)
def create_run(body: RunInput, actor: str = Depends(auth.actor)):
    from backend import model_admission
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        legacy, scout, maker, checker = load_stage_profiles(db, body, workspace_id)
        items = load_memory_selection(db, body.memory_ids, workspace_id)
        product_facts_raw, library_ref = _resolve_run_product_facts(db, body, workspace_id)
        _enforce_missing_core_gate(product_facts_raw, body.waive_missing_core_facts)
        _, maker_name, _ = stage_names(body)
        voice_selection = _capture_voice_selection(db, items, workspace_id)
    run_id = 'run_' + uuid4().hex
    factory = model_admission.admission_factory_for_run(store.engine(), run_id)
    format_raw = body.format_spec.model_dump(exclude_none=False) if body.format_spec is not None else None
    trend = _resolve_trend(body)
    receipt = adapter.execute(run_id, body.idea, legacy, body.seed_unverified_claim,
                              memory_items=items, checker_profile=body.checker_profile,
                              scout_profile=scout, maker_profile=maker, checker_agent=checker,
                              product_facts=product_facts_raw,
                              model_admission_factory=factory,
                              waive_missing_core_facts=body.waive_missing_core_facts,
                              fact_library=library_ref, format_spec=format_raw,
                              trend_format=trend)
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
    inline_raw = body.product_facts.model_dump() if body.product_facts is not None else None
    if inline_raw is not None and body.fact_variant_id:
        raise HTTPException(422, 'Supply either product_facts or fact_variant_id, never both')
    # Invalid product-fact input fails with 422 before accept, never 503.
    parse_product_facts(inline_raw)
    try:
        with store.connect() as db:
            workspace_id = store.ensure_workspace_seeded(db, actor)
            legacy, scout, maker, checker = load_stage_profiles(db, body, workspace_id)
            product_facts_raw, library_ref = _resolve_run_product_facts(db, body, workspace_id)
            _enforce_missing_core_gate(product_facts_raw, body.waive_missing_core_facts)
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
    format_raw = body.format_spec.model_dump(exclude_none=False) if body.format_spec is not None else None
    trend = _resolve_trend(body)
    started = run_jobs.start_async_run(run_id, body.idea, legacy, body.seed_unverified_claim, items,
                                       body.checker_profile, scout, maker, checker, maker_name, actor,
                                       workspace_id=store.workspace_for_actor(actor),
                                       product_facts=product_facts_raw,
                                       waive_missing_core_facts=body.waive_missing_core_facts,
                                       fact_library=library_ref, format_spec=format_raw,
                                       trend_format=trend)
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
        _advance_calendar_slots(db, run_id, workspace_id, 'approved')
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
        _advance_calendar_slots(db, run_id, workspace_id, 'exported')
    response.headers['Content-Disposition'] = 'attachment; filename="launchcrew-pack.json"'
    return exported



@app.get('/api/runs/{run_id}/channel-variants', response_model=ChannelVariantsOut)
def channel_variants(run_id: str, actor: str = Depends(auth.actor)):
    # Checked channel export candidates for one owned run. The bundle
    # derives verbatim from the current approved post draft and the
    # receipt-bound confirmed claims, and refuses unless the receipt
    # is currently exportable: human approval for export on the latest
    # revision with a clean final check and a matching current approval
    # binding. Read-only: no auto-publish, no auto-post, no auto-send.
    # Offline copy happens only after that human approval.
    from launchcrew import channel_variants as channel_mod
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id)
        _reject_when_running(receipt)
        try:
            bundle = channel_mod.checked_channel_variants(receipt)
        except ValueError as error:
            message = str(error)
            if 'stale' in message.lower():
                raise HTTPException(409, message)
            raise HTTPException(422, message)
    return bundle


@app.post('/api/runs/{run_id}/channel-variants/{channel}/approve', response_model=Receipt)
def approve_channel_variant(run_id: str, channel: str, body: ExportIn, actor: str = Depends(auth.actor)):
    # Human approval of one exact channel variant text. The approver
    # reviews the exact rendered candidate from the bundle read, then
    # this binds that exact text and subject to the current revision
    # and the current pack approval binding digest, recording the
    # approver and an audit event. A concurrent revision change
    # refuses stale with 409; unsupported exact text refuses with 422.
    # Pack approval, revision, and export state are unchanged.
    from launchcrew import channel_variants as channel_mod
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id, True)
        _reject_when_running(receipt)
        try:
            revised = channel_mod.approve_channel_variant(receipt, channel, actor, body.expected_revision)
        except ValueError as error:
            message = str(error)
            if 'stale' in message.lower():
                raise HTTPException(409, message)
            raise HTTPException(422, message)
        result = db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'), {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Run not found')
        store.audit(db, run_id, 'channel_variant_approval', actor, workspace_id)
    return revised


@app.post('/api/runs/{run_id}/channel-variants/{channel}/copy', response_model=ChannelCopyOut)
def copy_channel_variant(run_id: str, channel: str, body: ExportIn, actor: str = Depends(auth.actor)):
    # Server-side copy authorization for one exact channel text. Reads
    # the run fresh in the owner workspace, rejects running receipts,
    # requires the caller revision to match the current revision (a
    # concurrent revision change refuses with 409), and requires a
    # current human approval of the exact channel text plus the
    # exportable gate, the approval binding, and the exact rendered
    # text before authorizing. Only the returned text is copied by the
    # UI; cached bundle text is never copied. The authorization is
    # recorded in the receipt audit log without changing approval,
    # revision, or export state. No auto-publish, no auto-post.
    from launchcrew import channel_variants as channel_mod
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id, True)
        _reject_when_running(receipt)
        try:
            record = channel_mod.authorize_channel_copy(receipt, channel, body.expected_revision)
        except ValueError as error:
            message = str(error)
            if 'stale' in message.lower():
                raise HTTPException(409, message)
            raise HTTPException(422, message)
        revised = copy.deepcopy(receipt)
        now = datetime.now(timezone.utc).isoformat()
        events = list((revised.get('audit') or {}).get('event_log') or [])
        events.append({'step': 'channel_copy', 'agent': 'human',
                       'profile': actor or 'human',
                       'action': ('Copied %s text at revision %d for offline use; '
                                  'no publish, post, or send occurred'
                                  % (record['channel'], record['revision'])),
                       'timestamp': now, 'revision': record['revision'],
                       'channel': record['channel']})
        revised.setdefault('audit', {})['event_log'] = events
        result = db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'), {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Run not found')
        store.audit(db, run_id, 'channel_copy', actor, workspace_id)
    return record


@app.post('/api/runs/{run_id}/copy', response_model=DraftCopyOut)
def copy_draft(run_id: str, body: DraftCopyIn, actor: str = Depends(auth.actor)):
    # Server-side copy authorization for the primary post/email draft
    # text. Reads the run fresh in the owner workspace, rejects running
    # receipts, requires the caller revision to match the current
    # revision (a concurrent revision change refuses with 409), and
    # requires a current human approval of the exact draft text plus
    # the exportable gate, the approval binding, and the exact current
    # draft text before authorizing. Only the returned text is copied by
    # the UI; displayed text is never copied without this check. The
    # authorization is recorded in the receipt audit log without
    # changing approval, revision, or export state. No auto-publish, no
    # auto-post.
    from launchcrew import human_review
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id, True)
        _reject_when_running(receipt)
        current = human_review.current_revision(receipt)
        if current > 0 and body.expected_revision is None:
            raise HTTPException(409, 'Copy is stale; expected_revision is required for edited revisions')
        if body.expected_revision is not None and body.expected_revision != current:
            raise HTTPException(409, 'Copy is stale; the draft changed')
        try:
            record = human_review.authorize_draft_copy(receipt, body.kind, body.expected_revision)
        except ValueError as error:
            message = str(error)
            if 'stale' in message.lower():
                raise HTTPException(409, message)
            raise HTTPException(422, message)
        revised = copy.deepcopy(receipt)
        now = datetime.now(timezone.utc).isoformat()
        events = list((revised.get('audit') or {}).get('event_log') or [])
        events.append({'step': 'draft_copy', 'agent': 'human',
                       'profile': actor or 'human',
                       'action': ('Copied %s draft text at revision %d for offline use; '
                                  'no publish, post, or send occurred'
                                  % (record['kind'], record['revision'])),
                       'timestamp': now, 'revision': record['revision'],
                       'kind': record['kind']})
        revised.setdefault('audit', {})['event_log'] = events
        result = db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'), {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Run not found')
        store.audit(db, run_id, 'draft_copy', actor, workspace_id)
    return record


@app.get('/api/runs/{run_id}/launch-matrix', response_model=LaunchMatrixOut)
def launch_matrix(run_id: str, actor: str = Depends(auth.actor)):
    # Checked launch matrix for one owned run. All seven presentation
    # candidates derive verbatim from the current approved post draft
    # and the receipt-bound confirmed claims, and the route refuses
    # unless the receipt is currently exportable: human approval for
    # export on the latest revision with a clean final check and a
    # matching current approval binding. Read-only: no auto-publish,
    # no auto-post, no auto-send.
    from launchcrew import channel_variants as channel_mod
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id)
        _reject_when_running(receipt)
        try:
            bundle = channel_mod.checked_launch_matrix(receipt)
        except ValueError as error:
            message = str(error)
            if 'stale' in message.lower():
                raise HTTPException(409, message)
            raise HTTPException(422, message)
    return bundle


def _pack_filename(run_id):
    safe = ''.join(ch for ch in str(run_id) if ch.isalnum() or ch in ('-', '_'))
    return 'launchcrew-pack-%s.md' % (safe or 'run')


def _fenced(text):
    body = text if isinstance(text, str) else ''
    if '```' in body:
        body = body.replace('```', "'''")
    return '```text\n' + body + '\n```'


def _build_launch_pack_markdown(receipt):
    """Render the complete approved Launch Pack as Markdown.

    Raises ValueError when the receipt cannot supply the pack. Callers
    gate on human_review.exportable first; this builder re-verifies the
    matrix from the current approved draft and facts.
    """
    from launchcrew import channel_variants as channel_mod
    from launchcrew import human_review, landing_parity
    from launchcrew.ad_policy_lint import AD_POLICY_LINT_VERSION, lint_ad_policy
    binding = human_review.approval_binding(receipt)
    current = human_review.current_revision(receipt)
    draft = human_review.current_draft(receipt)
    post = draft.get('post') if isinstance(draft, dict) else ''
    email = draft.get('email') if isinstance(draft, dict) else ''
    if not isinstance(post, str):
        post = ''
    if not isinstance(email, str):
        email = ''
    approvals = receipt.get('approvals') if isinstance(receipt, dict) else None
    last = approvals[-1] if isinstance(approvals, list) and approvals else {}
    approver = last.get('approved_by') if isinstance(last, dict) else ''
    approved_at = last.get('timestamp') if isinstance(last, dict) else ''
    generated_at = receipt.get('generated_at', '')
    scout = receipt.get('scout') if isinstance(receipt.get('scout'), dict) else {}
    facts_used = scout.get('facts_used') if isinstance(scout.get('facts_used'), list) else []
    risks = scout.get('risks') if isinstance(scout.get('risks'), list) else []
    scout_sources = scout.get('sources') if isinstance(scout.get('sources'), list) else []
    matrix = channel_mod.checked_launch_matrix(receipt)
    lines = []
    lines.append('# LaunchCrew Approved Launch Pack')
    lines.append('')
    lines.append('## Header')
    lines.append('')
    lines.append('- Run ID: %s' % receipt.get('run_id', ''))
    lines.append('- Approved revision: %d' % current)
    lines.append('- Approver: %s' % (approver or ''))
    lines.append('- Binding version: %s' % binding['version'])
    lines.append('- Binding digest: %s' % binding['digest'])
    lines.append('- Approved at: %s' % (approved_at or ''))
    lines.append('- Generated at: %s' % (generated_at or ''))
    lines.append('')
    lines.append('## Scout Grounded Facts')
    lines.append('')
    if facts_used:
        for fact in facts_used:
            if not isinstance(fact, dict):
                continue
            claim = fact.get('claim', '')
            verified = fact.get('verified', False)
            sources = fact.get('sources') if isinstance(fact.get('sources'), list) else []
            lines.append('- Claim: %s' % claim)
            lines.append('  - Verified: %s' % ('yes' if verified else 'no'))
            lines.append('  - Sources: %s' % (', '.join(str(s) for s in sources) or 'none'))
    else:
        lines.append('- No grounded facts recorded.')
    if scout_sources:
        lines.append('')
        lines.append('Scout sources: %s' % ', '.join(str(s) for s in scout_sources))
    lines.append('')
    lines.append('## Identified Risks')
    lines.append('')
    if risks:
        for risk in risks:
            lines.append('- %s' % risk)
    else:
        lines.append('- No risks recorded.')
    lines.append('')
    lines.append('## Maker Primary Drafts')
    lines.append('')
    lines.append('### Post')
    lines.append('')
    lines.append(_fenced(post))
    lines.append('')
    lines.append('### Email')
    lines.append('')
    lines.append(_fenced(email))
    lines.append('')
    lines.append('## 7-Channel Launch Matrix')
    lines.append('')
    for channel in channel_mod.LAUNCH_MATRIX_CHANNELS:
        entry = matrix.get(channel, {})
        record, current_ok, reason = channel_mod.channel_approval_status(receipt, channel)
        lines.append('### %s' % channel)
        lines.append('')
        lines.append('- Status: %s' % entry.get('status', ''))
        lines.append('- Content valid: %s' % ('yes' if entry.get('content_valid') else 'no'))
        lines.append('- Ad policy passed: %s' % ('yes' if entry.get('ad_policy_passed') else 'no'))
        hits = entry.get('ad_policy_hits') if isinstance(entry.get('ad_policy_hits'), list) else []
        if hits:
            lines.append('- Ad policy hits: %s' % ', '.join(
                '%s (%s)' % (h.get('match', ''), h.get('category', '')) for h in hits if isinstance(h, dict)))
        if entry.get('subject'):
            lines.append('- Subject: %s' % entry.get('subject'))
        if entry.get('trim_note'):
            lines.append('- Trim note: %s' % entry.get('trim_note'))
        if record is not None and current_ok:
            lines.append('- Channel approval: approved by %s at revision %s (current)' % (
                record.get('approved_by', ''), record.get('revision', '')))
        elif record is not None:
            lines.append('- Channel approval: approved by %s at revision %s (stale: %s)' % (
                record.get('approved_by', ''), record.get('revision', ''), reason))
        else:
            lines.append('- Channel approval: none (%s)' % reason)
        if entry.get('text'):
            lines.append('')
            lines.append(_fenced(entry.get('text')))
        elif entry.get('reason'):
            lines.append('- Reason: %s' % entry.get('reason'))
        lines.append('')
    lines.append('## Ad Policy Audit Receipt')
    lines.append('')
    lines.append('- Linter version: %s' % AD_POLICY_LINT_VERSION)
    for label, text in (('Post', post), ('Email', email)):
        hits = lint_ad_policy(text if isinstance(text, str) else '')
        lines.append('- %s: %s (%d hit%s)' % (
            label, 'passed' if not hits else 'flagged', len(hits), '' if len(hits) == 1 else 's'))
        for hit in hits:
            if isinstance(hit, dict):
                lines.append('  - %s (%s): %s' % (
                    hit.get('match', ''), hit.get('category', ''), hit.get('reason', '')))
    lines.append('')
    lines.append('## Landing Page Parity Audit Receipt')
    lines.append('')
    lines.append('- Auditor version: %s' % landing_parity.LANDING_PARITY_VERSION)
    ad_prices = landing_parity.extract_prices(post)
    lines.append('- Ad prices in approved post: %s' % (
        ', '.join(ad_prices) if ad_prices else 'none'))
    lines.append('- Landing page audit: not stored on this receipt. Run '
                 'POST /api/runs/{run_id}/verify-landing-page with the '
                 'landing HTML to record a full price-parity and legal-footer audit.')
    lines.append('')
    lines.append('No auto-publish, no auto-post, no auto-send. Offline copy only.')
    lines.append('')
    return '\n'.join(lines)


@app.get('/api/runs/{run_id}/export/bundle')
@app.get('/api/runs/{run_id}/export/markdown')
def export_bundle_markdown(run_id: str, actor: str = Depends(auth.actor)):
    # Complete approved Launch Pack as a structured Markdown document.
    # Read-only: refuses unless the receipt is currently exportable
    # (human approval for export on the latest revision with a clean
    # final check and a matching current approval binding). No
    # auto-publish, no auto-post, no auto-send.
    from launchcrew import channel_variants as channel_mod
    from launchcrew import human_review
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id)
        _reject_when_running(receipt)
        if receipt.get('approval_state') != 'approved_for_export':
            raise HTTPException(409, 'Launch pack export requires human approval for export')
        if not human_review.exportable(receipt):
            raise HTTPException(422, 'Launch pack is not currently exportable; reapprove the latest revision')
        try:
            doc = _build_launch_pack_markdown(receipt)
        except ValueError as error:
            raise HTTPException(422, str(error))
    return Response(content=doc, media_type='text/markdown; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="%s"' % _pack_filename(run_id)})


@app.post('/api/runs/{run_id}/verify-landing-page', response_model=LandingParityOut)
def verify_landing_page(run_id: str, body: VerifyLandingPageIn, actor: str = Depends(auth.actor)):
    # Deterministic ad-to-landing-page parity audit for one owned run.
    # Audits the caller-supplied landing HTML against the current post
    # draft with no network access: every ad price must appear on the
    # page and the page footer must link the required legal policies.
    # Read-only: the receipt is never modified. landing_url is recorded
    # context only and is never fetched.
    from launchcrew import human_review, landing_parity
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id)
        _reject_when_running(receipt)
        draft = human_review.current_draft(receipt)
        post = draft.get('post') if isinstance(draft, dict) else None
        if not isinstance(post, str) or not post.strip():
            raise HTTPException(422, 'Run has no post draft to audit')
        audit = landing_parity.audit_landing_page_parity(post, body.landing_html)
    return audit


@app.post('/api/runs/{run_id}/photo-check', response_model=PhotoCheckResponse)
def photo_check(run_id: str, body: PhotoCheckIn, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _reject_when_running(get_receipt(db, run_id, workspace_id))
    from backend import photo_admission, sam
    from backend.photo_admission import AdmissionConflict, AdmissionNotFound, AdmissionRejected, AdmissionStale
    from backend.photo_input import PhotoInputError, parse_photo_data_uri
    from backend.photo_review import (PHOTO_EVENT_UNCHECKED,
                                      apply_photo_event,
                                      photo_status_of, record_unattempted_transport,
                                      unchecked_status)
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
            status = unchecked_status(
                reason='not_run: SAM not configured, photo unchecked',
                actor=actor, revision=human_review.current_revision(receipt))
            revised = apply_photo_event(receipt, event=PHOTO_EVENT_UNCHECKED, actor=actor, status=status)
            revised = record_unattempted_transport(
                revised, handling='not_run',
                note=('SAM is not configured, so the photo bytes stayed on the LaunchCrew validation '
                      'server for this check and were not forwarded to any segmentation provider. '
                      'Photo unchecked: text-only approval stays available; only a completed '
                      'segmentation check binds photo state into approval. '
                      'Text-model usage above is unchanged and covers text models only.'))
            result = db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'),
                       {'receipt': json.dumps(revised), 'state': revised['approval_state'], 'id': run_id, 'ws': workspace_id})
            if result.rowcount == 0:
                raise HTTPException(404, 'Run not found')
            db.execute(text('DELETE FROM approvals WHERE run_id=:id'), {'id': run_id})
            store.audit(db, run_id, 'photo_unchecked', actor, workspace_id)
        kept = photo_status_of(revised)
        check = PhotoCheckOut(method='not_run', label=kept['label'], reason=kept['reason'],
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


# Facts library (Gap 5): named products with per-variant fact sets.
# A variant stores one product-facts input object plus an explicit
# confirmed flag. A run picks a variant and binds a snapshot copy of
# its facts; later library edits never rewrite the stored run receipt.
FACT_LIBRARY_NAME_MAX = 120


class FactProductIn(Strict):
    name: str = Field(min_length=1, max_length=FACT_LIBRARY_NAME_MAX)


class FactProductOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str
    name: str
    variant_count: int = 0
    confirmed_variants: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FactVariantIn(Strict):
    name: str = Field(min_length=1, max_length=FACT_LIBRARY_NAME_MAX)
    product_facts: ProductFactsInput


class FactVariantEdit(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=FACT_LIBRARY_NAME_MAX)
    product_facts: ProductFactsInput | None = None


class FactVariantOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str
    product_id: str
    name: str
    product_facts: dict[str, Any]
    confirmed: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FactProductDetail(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str
    name: str
    variants: list[FactVariantOut] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FactVariantFromRunIn(Strict):
    name: str = Field(min_length=1, max_length=FACT_LIBRARY_NAME_MAX)


def _clean_fact_library_name(value, what):
    if not isinstance(value, str):
        raise HTTPException(422, what + ' name must be a string')
    name = value.strip()
    if not name:
        raise HTTPException(422, what + ' name must not be empty')
    if len(name) > FACT_LIBRARY_NAME_MAX:
        raise HTTPException(422, what + ' name exceeds the length limit')
    return name


def _get_fact_product(db, product_id, workspace_id, lock=False):
    row = db.execute(text('SELECT id, name, created_at, updated_at FROM fact_products WHERE id=:id AND workspace_id=:ws' + (' FOR UPDATE' if lock else '')),
                     {'id': product_id, 'ws': workspace_id}).mappings().first()
    if row is None:
        raise HTTPException(404, 'Fact product not found')
    return row


def _get_fact_variant(db, variant_id, workspace_id, lock=False):
    row = db.execute(text('SELECT id, product_id, name, facts, confirmed, created_at, updated_at FROM fact_variants WHERE id=:id AND workspace_id=:ws' + (' FOR UPDATE' if lock else '')),
                     {'id': variant_id, 'ws': workspace_id}).mappings().first()
    if row is None:
        raise HTTPException(404, 'Fact variant not found')
    return row


def _public_fact_variant(row):
    facts = row['facts']
    return {'id': row['id'], 'product_id': row['product_id'], 'name': row['name'],
            'product_facts': copy.deepcopy(facts) if isinstance(facts, dict) else {},
            'confirmed': bool(row['confirmed']),
            'created_at': row['created_at'], 'updated_at': row['updated_at']}


def _product_variant_counts(db, product_id, workspace_id):
    row = db.execute(text('SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE confirmed) AS confirmed FROM fact_variants WHERE product_id=:id AND workspace_id=:ws'),
                     {'id': product_id, 'ws': workspace_id}).mappings().first()
    return (int(row['total'] or 0), int(row['confirmed'] or 0))


def _validate_variant_facts(raw):
    from launchcrew.facts import parse_product_facts
    try:
        parse_product_facts(raw)
    except ValueError:
        raise HTTPException(422, 'Variant facts are invalid; confirm each fact explicitly')
    return raw


def _resolve_run_product_facts(db, body, workspace_id):
    """Return (product_facts_raw, library_ref) for a run create body.

    Either inline product_facts or a library fact_variant_id, never
    both. The variant snapshot is a deep copy: the run binds these
    facts and later library edits never rewrite the stored receipt.
    """
    inline = body.product_facts.model_dump() if body.product_facts is not None else None
    variant_id = body.fact_variant_id
    if inline is not None and variant_id:
        raise HTTPException(422, 'Supply either product_facts or fact_variant_id, never both')
    if not variant_id:
        return inline, None
    row = _get_fact_variant(db, variant_id, workspace_id)
    raw = copy.deepcopy(row['facts']) if isinstance(row['facts'], dict) else {}
    _validate_variant_facts(raw)
    product = _get_fact_product(db, row['product_id'], workspace_id)
    ref = {'product_id': row['product_id'], 'product_name': product['name'],
           'variant_id': row['id'], 'variant_name': row['name'],
           'confirmed': bool(row['confirmed'])}
    return raw, ref


def _enforce_missing_core_gate(product_facts_raw, waived):
    """Refuse owner-partial runs before drafting unless explicitly waived.

    Demo-template mode (None) carries no gate. Returns silently when
    every core fact is confirmed or when the owner waiver flag is set;
    otherwise raises 422 naming the missing facts so the UI can prompt
    for them or request the waiver flag.
    """
    if product_facts_raw is None:
        return
    from launchcrew.facts import missing_core_facts, parse_product_facts
    try:
        parsed = parse_product_facts(product_facts_raw)
    except ValueError:
        raise
    missing = missing_core_facts(parsed)
    if missing and not waived:
        raise HTTPException(422, {'message': 'Missing core product facts: ' + ', '.join(missing),
                                  'missing_facts': missing, 'requires_waiver': True})


@app.get('/api/fact-products', response_model=list[FactProductOut])
def list_fact_products(actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        rows = db.execute(text('SELECT id, name, created_at, updated_at FROM fact_products WHERE workspace_id=:ws ORDER BY name, id'),
                          {'ws': workspace_id}).mappings().all()
        result = []
        for row in rows:
            total, confirmed = _product_variant_counts(db, row['id'], workspace_id)
            result.append({'id': row['id'], 'name': row['name'], 'variant_count': total,
                           'confirmed_variants': confirmed,
                           'created_at': row['created_at'], 'updated_at': row['updated_at']})
        return result


@app.post('/api/fact-products', response_model=FactProductOut, status_code=201)
def create_fact_product(body: FactProductIn, actor: str = Depends(auth.actor)):
    name = _clean_fact_library_name(body.name, 'Product')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        existing = db.execute(text('SELECT id FROM fact_products WHERE workspace_id=:ws AND LOWER(name)=LOWER(:name)'),
                              {'ws': workspace_id, 'name': name}).fetchone()
        if existing:
            raise HTTPException(409, 'A product with this name already exists')
        product_id = 'fprod_' + uuid4().hex
        db.execute(text('INSERT INTO fact_products(id, workspace_id, name) VALUES (:id,:ws,:name)'),
                   {'id': product_id, 'ws': workspace_id, 'name': name})
        store.audit(db, None, 'fact_product_created', actor, workspace_id)
        row = _get_fact_product(db, product_id, workspace_id)
        return {'id': row['id'], 'name': row['name'], 'variant_count': 0,
                'confirmed_variants': 0, 'created_at': row['created_at'], 'updated_at': row['updated_at']}


@app.get('/api/fact-products/{product_id}', response_model=FactProductDetail)
def get_fact_product(product_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        row = _get_fact_product(db, product_id, workspace_id)
        variants = db.execute(text('SELECT id, product_id, name, facts, confirmed, created_at, updated_at FROM fact_variants WHERE product_id=:id AND workspace_id=:ws ORDER BY name, id'),
                              {'id': product_id, 'ws': workspace_id}).mappings().all()
        return {'id': row['id'], 'name': row['name'],
                'variants': [_public_fact_variant(item) for item in variants],
                'created_at': row['created_at'], 'updated_at': row['updated_at']}


@app.put('/api/fact-products/{product_id}', response_model=FactProductOut)
def rename_fact_product(product_id: str, body: FactProductIn, actor: str = Depends(auth.actor)):
    name = _clean_fact_library_name(body.name, 'Product')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _get_fact_product(db, product_id, workspace_id, lock=True)
        clash = db.execute(text('SELECT id FROM fact_products WHERE workspace_id=:ws AND LOWER(name)=LOWER(:name) AND id != :id'),
                           {'ws': workspace_id, 'name': name, 'id': product_id}).fetchone()
        if clash:
            raise HTTPException(409, 'A product with this name already exists')
        db.execute(text('UPDATE fact_products SET name=:name,updated_at=now() WHERE id=:id AND workspace_id=:ws'),
                   {'name': name, 'id': product_id, 'ws': workspace_id})
        store.audit(db, None, 'fact_product_renamed', actor, workspace_id)
        row = _get_fact_product(db, product_id, workspace_id)
        total, confirmed = _product_variant_counts(db, product_id, workspace_id)
        return {'id': row['id'], 'name': row['name'], 'variant_count': total,
                'confirmed_variants': confirmed, 'created_at': row['created_at'], 'updated_at': row['updated_at']}


@app.delete('/api/fact-products/{product_id}', status_code=204)
def delete_fact_product(product_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _get_fact_product(db, product_id, workspace_id, lock=True)
        db.execute(text('DELETE FROM fact_variants WHERE product_id=:id AND workspace_id=:ws'),
                   {'id': product_id, 'ws': workspace_id})
        result = db.execute(text('DELETE FROM fact_products WHERE id=:id AND workspace_id=:ws'),
                            {'id': product_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Fact product not found')
        store.audit(db, None, 'fact_product_deleted', actor, workspace_id)
    return Response(status_code=204)


@app.get('/api/fact-products/{product_id}/variants', response_model=list[FactVariantOut])
def list_fact_variants(product_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _get_fact_product(db, product_id, workspace_id)
        rows = db.execute(text('SELECT id, product_id, name, facts, confirmed, created_at, updated_at FROM fact_variants WHERE product_id=:id AND workspace_id=:ws ORDER BY name, id'),
                          {'id': product_id, 'ws': workspace_id}).mappings().all()
        return [_public_fact_variant(row) for row in rows]


@app.post('/api/fact-products/{product_id}/variants', response_model=FactVariantOut, status_code=201)
def create_fact_variant(product_id: str, body: FactVariantIn, actor: str = Depends(auth.actor)):
    name = _clean_fact_library_name(body.name, 'Variant')
    raw = _validate_variant_facts(body.product_facts.model_dump())
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _get_fact_product(db, product_id, workspace_id)
        clash = db.execute(text('SELECT id FROM fact_variants WHERE product_id=:id AND workspace_id=:ws AND LOWER(name)=LOWER(:name)'),
                           {'id': product_id, 'ws': workspace_id, 'name': name}).fetchone()
        if clash:
            raise HTTPException(409, 'A variant with this name already exists for this product')
        variant_id = 'fvar_' + uuid4().hex
        db.execute(text('INSERT INTO fact_variants(id, product_id, workspace_id, name, facts, confirmed) VALUES (:id,:prod,:ws,:name,CAST(:facts AS jsonb),:confirmed)'),
                   {'id': variant_id, 'prod': product_id, 'ws': workspace_id, 'name': name,
                    'facts': json.dumps(raw), 'confirmed': False})
        store.audit(db, None, 'fact_variant_created', actor, workspace_id)
        return _public_fact_variant(_get_fact_variant(db, variant_id, workspace_id))


def _receipt_facts_snapshot(receipt):
    """Rebuild a product-facts input object from a run bound section.

    Copies only the stored per-field value, confirmation, and source,
    so the library variant starts from exactly what the run bound.
    """
    section = receipt.get('product_facts') if isinstance(receipt, dict) else None
    if not isinstance(section, dict):
        raise HTTPException(422, 'Run has no bound product facts to save')
    if section.get('mode') != 'owner_input':
        raise HTTPException(422, 'Only owner-input runs can be saved to the facts library')
    raw: dict[str, Any] = {}
    claims: list[dict[str, Any]] = []
    for entry in section.get('fields') or []:
        if not isinstance(entry, dict):
            continue
        field = entry.get('field')
        value = entry.get('value')
        confirmed = entry.get('confirmed')
        source = entry.get('source') or 'owner'
        item = {'value': value if isinstance(value, str) else '',
                'confirmed': confirmed is True, 'source': source}
        if field == 'allowed_claim':
            claims.append(item)
        elif field in ('material', 'contents', 'size', 'price'):
            raw[field] = item
    if claims:
        raw['allowed_claims'] = claims
    note = section.get('founder_note')
    if isinstance(note, dict) and isinstance(note.get('value'), str) and note.get('value'):
        raw['founder_note'] = {'value': note['value'], 'confirmed': note.get('confirmed') is True,
                               'source': note.get('source') or 'owner'}
    return _validate_variant_facts(raw)


@app.post('/api/fact-products/{product_id}/variants/from-run/{run_id}', response_model=FactVariantOut, status_code=201)
def save_fact_variant_from_run(product_id: str, run_id: str, body: FactVariantFromRunIn, actor: str = Depends(auth.actor)):
    name = _clean_fact_library_name(body.name, 'Variant')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _get_fact_product(db, product_id, workspace_id)
        receipt = get_receipt(db, run_id, workspace_id)
        raw = _receipt_facts_snapshot(receipt)
        clash = db.execute(text('SELECT id FROM fact_variants WHERE product_id=:id AND workspace_id=:ws AND LOWER(name)=LOWER(:name)'),
                           {'id': product_id, 'ws': workspace_id, 'name': name}).fetchone()
        if clash:
            raise HTTPException(409, 'A variant with this name already exists for this product')
        variant_id = 'fvar_' + uuid4().hex
        db.execute(text('INSERT INTO fact_variants(id, product_id, workspace_id, name, facts, confirmed) VALUES (:id,:prod,:ws,:name,CAST(:facts AS jsonb),:confirmed)'),
                   {'id': variant_id, 'prod': product_id, 'ws': workspace_id, 'name': name,
                    'facts': json.dumps(raw), 'confirmed': False})
        store.audit(db, run_id, 'fact_variant_saved_from_run', actor, workspace_id)
        return _public_fact_variant(_get_fact_variant(db, variant_id, workspace_id))


@app.get('/api/fact-variants/{variant_id}', response_model=FactVariantOut)
def get_fact_variant(variant_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return _public_fact_variant(_get_fact_variant(db, variant_id, workspace_id))


@app.put('/api/fact-variants/{variant_id}', response_model=FactVariantOut)
def edit_fact_variant(variant_id: str, body: FactVariantEdit, actor: str = Depends(auth.actor)):
    if body.name is None and body.product_facts is None:
        raise HTTPException(422, 'Supply a name, product_facts, or both to edit a variant')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        row = _get_fact_variant(db, variant_id, workspace_id, lock=True)
        updates: dict[str, Any] = {}
        if body.name is not None:
            name = _clean_fact_library_name(body.name, 'Variant')
            clash = db.execute(text('SELECT id FROM fact_variants WHERE product_id=:prod AND workspace_id=:ws AND LOWER(name)=LOWER(:name) AND id != :id'),
                               {'prod': row['product_id'], 'ws': workspace_id, 'name': name, 'id': variant_id}).fetchone()
            if clash:
                raise HTTPException(409, 'A variant with this name already exists for this product')
            updates['name'] = name
        if body.product_facts is not None:
            raw = _validate_variant_facts(body.product_facts.model_dump())
            updates['facts'] = json.dumps(raw)
            # Edited facts need a fresh explicit confirmation.
            updates['confirmed_reset'] = True
        if 'name' in updates:
            db.execute(text('UPDATE fact_variants SET name=:name,updated_at=now() WHERE id=:id AND workspace_id=:ws'),
                       {'name': updates['name'], 'id': variant_id, 'ws': workspace_id})
        if 'facts' in updates:
            db.execute(text('UPDATE fact_variants SET facts=CAST(:facts AS jsonb),confirmed=false,updated_at=now() WHERE id=:id AND workspace_id=:ws'),
                       {'facts': updates['facts'], 'id': variant_id, 'ws': workspace_id})
        store.audit(db, None, 'fact_variant_edited', actor, workspace_id)
        return _public_fact_variant(_get_fact_variant(db, variant_id, workspace_id))


@app.post('/api/fact-variants/{variant_id}/confirm', response_model=FactVariantOut)
def confirm_fact_variant(variant_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        row = _get_fact_variant(db, variant_id, workspace_id, lock=True)
        _validate_variant_facts(copy.deepcopy(row['facts']) if isinstance(row['facts'], dict) else {})
        db.execute(text('UPDATE fact_variants SET confirmed=true,updated_at=now() WHERE id=:id AND workspace_id=:ws'),
                   {'id': variant_id, 'ws': workspace_id})
        store.audit(db, None, 'fact_variant_confirmed', actor, workspace_id)
        return _public_fact_variant(_get_fact_variant(db, variant_id, workspace_id))


@app.delete('/api/fact-variants/{variant_id}', status_code=204)
def delete_fact_variant(variant_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _get_fact_variant(db, variant_id, workspace_id, lock=True)
        result = db.execute(text('DELETE FROM fact_variants WHERE id=:id AND workspace_id=:ws'),
                            {'id': variant_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Fact variant not found')
        store.audit(db, None, 'fact_variant_deleted', actor, workspace_id)
    return Response(status_code=204)


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

# Selectable campaign angles: the seven legacy week angles plus five
# added angles. A seven-day week assigns seven distinct angles from
# this roster in order.
CAMPAIGN_ANGLES = (
    'Origin story',
    'Material and craft',
    'Commuter use',
    'Styling',
    'Care and durability',
    'Social proof',
    'Launch offer',
    'Build in public milestone',
    'Customer problem story',
    'Before and after',
    'Objection answer',
    'Founder lesson',
)

# Default owner-week lineup: opens and closes with familiar angles and
# features all five added angles in between.
OWNER_WEEK_ANGLES = (
    'Origin story',
    'Build in public milestone',
    'Customer problem story',
    'Before and after',
    'Objection answer',
    'Founder lesson',
    'Launch offer',
)


def _owner_campaign_briefs(confirmed_claims, angles=None):
    """Build seven distinct day briefs from the campaign's own confirmed facts.

    Each day gets a distinct angle and a brief of the form
    "Day N (<angle>): <confirmed claim>" with the claims rotating in
    order, so every brief quotes a whole owner-confirmed fact verbatim
    and no bundled demo-template text appears. The day marker keeps
    all seven briefs distinct even when few facts were confirmed. When
    the full brief would reach 140 chars, it falls back to
    "Day N: <confirmed claim>" rather than truncating a fact. Raises
    ValueError for missing facts or for an angles selection that is
    not seven distinct roster names.
    """
    claims = [claim for claim in (confirmed_claims or [])
              if isinstance(claim, str) and claim.strip()]
    if not claims:
        raise ValueError('Owner campaign weeks require at least one confirmed fact')
    chosen = list(angles) if angles is not None else list(OWNER_WEEK_ANGLES)
    if len(chosen) != 7 or len(set(chosen)) != 7:
        raise ValueError('A campaign week needs seven distinct angles')
    for angle in chosen:
        if angle not in CAMPAIGN_ANGLES:
            raise ValueError('Unknown campaign angle: %r' % (angle,))
    plan = []
    for position, angle in enumerate(chosen):
        day = position + 1
        claim = claims[position % len(claims)]
        brief = 'Day %d (%s): %s' % (day, angle, claim)
        if len(brief) >= 140:
            brief = 'Day %d: %s' % (day, claim)
        plan.append((day, angle, brief, claim))
    briefs = [brief for _, _, brief, _ in plan]
    if len(set(briefs)) != 7:
        raise ValueError('Owner campaign briefs must be seven distinct texts')
    return plan


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
    trend_label: str = ''
    trend_source: str = ''
    trend_guidance: str = ''


class CampaignOut(Strict):
    id: str
    idea: str
    agent_name: str
    created_at: datetime
    days: list[CampaignDay]


class CampaignInput(RunInput):
    angles: list[str] | None = Field(default=None, description='Optional seven distinct angle names from the campaign angle roster, assigned to days 1 to 7 in order. Absent means the bundled demo week in demo mode or the default owner lineup with confirmed facts.')

    @field_validator('angles')
    @classmethod
    def _check_angles(cls, value):
        if value is None:
            return None
        if len(value) != 7 or len(set(value)) != 7:
            raise ValueError('angles must hold seven distinct angle names')
        for angle in value:
            if not isinstance(angle, str) or angle not in CAMPAIGN_ANGLES:
                raise ValueError('Unknown campaign angle: %r' % (angle,))
        return list(value)


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
        trend_label, trend_source, trend_guidance = '', '', ''
        if isinstance(receipt, dict):
            if isinstance(receipt.get('campaign_angle'), str) and receipt['campaign_angle'].strip():
                angle = receipt['campaign_angle']
            if isinstance(receipt.get('campaign_brief'), str) and receipt['campaign_brief'].strip():
                brief = receipt['campaign_brief']
            stored_trend = receipt.get('trend_format')
            if isinstance(stored_trend, dict):
                if isinstance(stored_trend.get('label'), str):
                    trend_label = stored_trend['label']
                if isinstance(stored_trend.get('source_label'), str):
                    trend_source = stored_trend['source_label']
                if isinstance(stored_trend.get('sanitized_guidance'), str):
                    trend_guidance = stored_trend['sanitized_guidance']
        current = human_review.current_draft(receipt)
        check = human_review.current_check(receipt)
        result['days'].append({'day': day, 'run_id': receipt['run_id'], 'approval_state': receipt['approval_state'],
                               'status': receipt['status'], 'checker_v2_blocked_count': (check or {}).get('blocked_count'),
                               'idea': receipt.get('idea', ''), 'angle': angle, 'brief': brief,
                               'draft_v2_post': (current or {}).get('post'),
                               'revision': human_review.current_revision(receipt),
                               'approved_revision': receipt.get('approved_revision'),
                               'trend_label': trend_label, 'trend_source': trend_source,
                               'trend_guidance': trend_guidance})
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
def create_campaign(body: CampaignInput, actor: str = Depends(auth.actor)):
    from launchcrew.facts import parse_product_facts
    from backend import model_admission
    if body.product_facts is not None and body.fact_variant_id:
        raise HTTPException(422, 'Supply either product_facts or fact_variant_id, never both')
    with store.connect() as db:
        _resolve_ws = store.ensure_workspace_seeded(db, actor)
        _raw, _ref = _resolve_run_product_facts(db, body, _resolve_ws)
        _enforce_missing_core_gate(_raw, body.waive_missing_core_facts)
    product_facts_raw, library_ref = _raw, _ref
    parsed_product = parse_product_facts(product_facts_raw)
    confirmed_claims = list(parsed_product['confirmed_claims']) if parsed_product is not None else []
    if confirmed_claims:
        # Owner mode: every day brief is built from the campaign's own
        # confirmed facts. The bundled demo template is never used here.
        week_plan = _owner_campaign_briefs(confirmed_claims, angles=body.angles)
    else:
        # Demo mode: the bundled fictional demo template stays available
        # only when the owner confirmed nothing.
        week_plan = []
        for day in range(1, 8):
            demo_angle, demo_brief, demo_claim = CAMPAIGN_BRIEF_BY_DAY[day]
            if body.angles is not None:
                demo_angle = body.angles[day - 1]
            week_plan.append((day, demo_angle, demo_brief, demo_claim))
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
    format_raw = body.format_spec.model_dump(exclude_none=False) if body.format_spec is not None else None
    campaign_trend = _resolve_trend(body)
    for day, angle, brief, brief_claim in week_plan:
        run_id = run_ids[day - 1]
        try:
            factory = model_admission.admission_factory_for_run(engine, run_id)
            receipt = adapter.execute(run_id, body.idea, legacy, body.seed_unverified_claim,
                                      memory_items=items, checker_profile=body.checker_profile,
                                      brief=brief, campaign_day=day, extra_claims=[brief_claim],
                                      scout_profile=scout, maker_profile=maker, checker_agent=checker,
                                      product_facts=product_facts_raw,
                                      model_admission_factory=factory,
                                      waive_missing_core_facts=body.waive_missing_core_facts,
                                      fact_library=library_ref, format_spec=format_raw,
                                      trend_format=campaign_trend)
            if isinstance(receipt, dict):
                receipt['campaign_angle'] = angle
        except Exception as error:
            failed = {'receipt_version': '1.0', 'run_id': run_id, 'generated_at': datetime.now(timezone.utc).isoformat(),
                      'status': 'failed', 'brand': 'LaunchCrew', 'mode': 'demo_no_submit',
                      'idea': body.idea, 'approvals': [], 'completed_steps': [],
                      'error_type': type(error).__name__[:64] or 'PipelineError',
                      'approval_state': 'pending_approval', 'checker_profile': body.checker_profile,
                      'stage_bindings': {'scout': scout_name, 'maker': maker_name, 'checker': checker_name},
                      'summary': {'submit_attempted': False, 'submit_completed': False},
                      'audit': {'event_log': [], 'stopped_reason': 'campaign_day_%d' % day},
                      'voice_profile': voice_binding, 'campaign_day': day, 'campaign_brief': brief,
                      'campaign_angle': angle, 'trend_format': copy.deepcopy(campaign_trend)}
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


WaitlistTier = Literal['free', 'pro', 'team']


class WaitlistIn(Strict):
    email: str = Field(max_length=254)
    interest: str = Field(default='general', max_length=120)
    tier: WaitlistTier = 'pro'

    @field_validator('email')
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized or len(normalized) > 254 or '@' not in normalized:
            raise ValueError('email must be a valid email address')
        local, _, domain = normalized.partition('@')
        if not local or '.' not in domain or normalized.count('@') != 1:
            raise ValueError('email must be a valid email address')
        if any(ch.isspace() for ch in normalized):
            raise ValueError('email must be a valid email address')
        return normalized

    @field_validator('interest')
    @classmethod
    def _normalize_interest(cls, value: str) -> str:
        cleaned = ' '.join(value.strip().split())
        return cleaned or 'general'


class WaitlistOut(Strict):
    id: str
    email: str
    interest: str
    tier: str
    created_at: str
    duplicate: bool = False


_WAITLIST_SELECT = 'id, email, interest, tier, created_at'


def _public_waitlist(row: Any, duplicate: bool = False) -> dict[str, Any]:
    created = row['created_at']
    if isinstance(created, datetime):
        created = created.isoformat()
    return {'id': row['id'], 'email': row['email'], 'interest': row['interest'],
            'tier': row['tier'], 'created_at': str(created), 'duplicate': duplicate}


@app.post('/api/waitlist', response_model=WaitlistOut, status_code=201)
def join_waitlist(body: WaitlistIn):
    """Store a Plans-page waitlist signup. Public; Checker stays unmetered.

    Email is normalized (trimmed, lowercased) and unique, so a repeat
    submission for the same address returns the stored row with
    duplicate=true and HTTP 200 instead of storing twice. The safety
    Checker path is untouched by this route: verification never reads
    credits and is never gated by waitlist state.
    """
    signup_id = 'wl_' + uuid4().hex
    with store.connect() as db:
        try:
            with db.begin_nested():
                db.execute(text('INSERT INTO waitlist_signups (id, email, interest, tier) VALUES (:id, :email, :interest, :tier)'),
                           {'id': signup_id, 'email': body.email, 'interest': body.interest, 'tier': body.tier})
        except IntegrityError:
            row = db.execute(text('SELECT ' + _WAITLIST_SELECT + ' FROM waitlist_signups WHERE email=:email'),
                             {'email': body.email}).mappings().first()
            if row is None:
                raise HTTPException(409, 'Email already on the waitlist')
            return JSONResponse(status_code=200, content=_public_waitlist(row, duplicate=True))
        row = db.execute(text('SELECT ' + _WAITLIST_SELECT + ' FROM waitlist_signups WHERE id=:id'),
                         {'id': signup_id}).mappings().first()
        if row is None:
            raise HTTPException(500, 'Waitlist signup was not stored')
        return _public_waitlist(row)


@app.get('/api/waitlist', response_model=list[WaitlistOut])
def list_waitlist():
    """List waitlist signups oldest first. Public read for the Plans page count."""
    with store.connect() as db:
        rows = db.execute(text('SELECT ' + _WAITLIST_SELECT + ' FROM waitlist_signups ORDER BY created_at, id')).mappings().all()
        return [_public_waitlist(row) for row in rows]


# S1 content calendar: week and month views over workspace-scoped slots.
# Each day carries feed_post, story, and reel slots; empty daily slots
# render as visible gaps, never hidden absences. Slot status derives
# from the linked run and advances on approve/export with no manual edit.

CalendarSlotType = Literal['feed_post', 'story', 'reel']
CalendarSlotStatus = Literal['drafted', 'checked', 'approved', 'exported', 'verified']


class CalendarSlotOut(Strict):
    id: str
    slot_date: str
    slot_type: CalendarSlotType
    pillar: str
    format: str
    status: CalendarSlotStatus
    run_id: str | None = None
    campaign_id: str | None = None
    campaign_day: int | None = None
    planned_time: str = '09:00'
    selected_channels: list[str] = Field(default_factory=list)
    approved_channels: list[str] = Field(default_factory=list)
    schedule_state: str = 'draft'


class CalendarSlotIn(Strict):
    slot_date: str = Field(min_length=10, max_length=10)
    slot_type: CalendarSlotType
    pillar: str = Field(default='product', max_length=80)
    format: str = Field(default='', max_length=120)
    run_id: str | None = None
    campaign_id: str | None = None
    campaign_day: int | None = None


class CalendarPlaceIn(Strict):
    start_date: str = Field(min_length=10, max_length=10)


_CALENDAR_PUBLIC_FIELDS = ('id', 'workspace_id', 'slot_date', 'slot_type', 'pillar',
                           'format', 'status', 'run_id', 'campaign_id', 'campaign_day',
                           'planned_time', 'selected_channels', 'approved_channels',
                           'schedule_state')
_CALENDAR_PUBLIC_SELECT = ('id, workspace_id, slot_date, slot_type, pillar, format, '
                           'status, run_id, campaign_id, campaign_day, planned_time, '
                           'selected_channels, approved_channels, schedule_state')

_SCHEDULE_DEFAULT_TIMES = {'feed_post': '09:00', 'story': '13:00', 'reel': '18:00'}


def _public_calendar_slot(row):
    from launchcrew import calendar as calendar_mod
    if not isinstance(row, dict):
        try:
            row = dict(row)
        except Exception:
            row = {}
    posted = row.get('slot_date', '')
    if hasattr(posted, 'isoformat'):
        posted = posted.isoformat()
    planned = row.get('planned_time')
    if not planned:
        try:
            planned = calendar_mod.default_time_for(row.get('slot_type', ''))
        except Exception:
            planned = '09:00'
    selected = row.get('selected_channels')
    approved = row.get('approved_channels')
    state = row.get('schedule_state')
    return {'id': row['id'], 'slot_date': str(posted), 'slot_type': row['slot_type'],
            'pillar': row['pillar'], 'format': row['format'], 'status': row['status'],
            'run_id': row['run_id'], 'campaign_id': row['campaign_id'],
            'campaign_day': row['campaign_day'],
            'planned_time': planned or '09:00',
            'selected_channels': list(selected) if isinstance(selected, list) else [],
            'approved_channels': list(approved) if isinstance(approved, list) else [],
            'schedule_state': state if state in ('draft', 'ready') else 'draft'}


def _schedule_defaults(db, workspace_id):
    from launchcrew import calendar as calendar_mod
    stored = db.execute(text('SELECT slot_type, planned_time FROM calendar_schedule_defaults WHERE workspace_id=:ws'),
                        {'ws': workspace_id}).all()
    defaults = dict(_SCHEDULE_DEFAULT_TIMES)
    for slot_type, planned_time in stored:
        try:
            calendar_mod.normalize_slot_type(slot_type)
            defaults[slot_type] = calendar_mod.normalize_planned_time(planned_time)
        except ValueError:
            continue
    return defaults


def _parse_calendar_date(value, field_name='slot_date'):
    from launchcrew import calendar as calendar_mod
    try:
        calendar_mod.parse_slot_date(value)
    except ValueError:
        raise HTTPException(422, field_name + ' must be a real calendar date in YYYY-MM-DD format')
    return value


def _advance_calendar_slots(db, run_id, workspace_id, target):
    from launchcrew import calendar as calendar_mod
    rows = db.execute(text('SELECT id, status FROM calendar_slots WHERE run_id=:run AND workspace_id=:ws'),
                      {'run': run_id, 'ws': workspace_id}).mappings().all()
    for row in rows:
        if calendar_mod.should_advance(row['status'], target):
            db.execute(text("UPDATE calendar_slots SET status=:status, updated_at=now() WHERE id=:id AND workspace_id=:ws"),
                       {'status': target, 'id': row['id'], 'ws': workspace_id})


def _sync_calendar_row(db, slot, workspace_id):
    from launchcrew import calendar as calendar_mod
    if not slot['run_id']:
        return slot
    stored = db.execute(text('SELECT receipt FROM runs WHERE id=:id AND workspace_id=:ws'),
                        {'id': slot['run_id'], 'ws': workspace_id}).fetchone()
    if stored is None:
        return slot
    computed = calendar_mod.status_for_receipt(stored[0])
    if calendar_mod.should_advance(slot['status'], computed):
        db.execute(text("UPDATE calendar_slots SET status=:status, updated_at=now() WHERE id=:id AND workspace_id=:ws"),
                   {'status': computed, 'id': slot['id'], 'ws': workspace_id})
        slot = dict(slot)
        slot['status'] = computed
    return slot


@app.get('/api/calendar/slots', response_model=list[CalendarSlotOut])
def list_calendar_slots(start_date: str | None = None, end_date: str | None = None,
                        actor: str = Depends(auth.actor)):
    from launchcrew import calendar as calendar_mod
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        clauses = ['workspace_id=:ws']
        params: dict[str, Any] = {'ws': workspace_id}
        if start_date is not None:
            _parse_calendar_date(start_date, 'start_date')
            clauses.append('slot_date >= CAST(:start AS date)')
            params['start'] = start_date
        if end_date is not None:
            _parse_calendar_date(end_date, 'end_date')
            clauses.append('slot_date <= CAST(:end AS date)')
            params['end'] = end_date
        rows = db.execute(text('SELECT ' + _CALENDAR_PUBLIC_SELECT + ' FROM calendar_slots WHERE '
                               + ' AND '.join(clauses) + ' ORDER BY slot_date, slot_type, id'),
                          params).mappings().all()
        synced = [_sync_calendar_row(db, dict(row), workspace_id) for row in rows]
        return [_public_calendar_slot(slot) for slot in synced]


@app.post('/api/calendar/slots', response_model=CalendarSlotOut, status_code=201)
def create_calendar_slot(body: CalendarSlotIn, actor: str = Depends(auth.actor)):
    from launchcrew import calendar as calendar_mod
    slot_date = _parse_calendar_date(body.slot_date)
    pillar = calendar_mod.normalize_pillar(body.pillar)
    slot_format = ' '.join((body.format or '').strip().split())
    if len(slot_format) > 120:
        raise HTTPException(422, 'format must be at most 120 characters')
    if not slot_format:
        slot_format = body.slot_type
    if body.campaign_day is not None and not 1 <= body.campaign_day <= 7:
        raise HTTPException(422, 'campaign_day must be 1 to 7')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        status = 'drafted'
        if body.run_id is not None:
            row = db.execute(text('SELECT receipt FROM runs WHERE id=:id AND workspace_id=:ws'),
                             {'id': body.run_id, 'ws': workspace_id}).fetchone()
            if row is None:
                raise HTTPException(404, 'Run not found')
            status = calendar_mod.status_for_receipt(row[0])
        if body.campaign_id is not None:
            campaign = db.execute(text('SELECT 1 FROM campaigns WHERE id=:id AND workspace_id=:ws'),
                                  {'id': body.campaign_id, 'ws': workspace_id}).fetchone()
            if campaign is None:
                raise HTTPException(404, 'Campaign not found')
        slot_id = 'slot_' + uuid4().hex
        defaults = _schedule_defaults(db, workspace_id)
        try:
            db.execute(text('INSERT INTO calendar_slots(id, workspace_id, slot_date, slot_type, pillar, format, status, run_id, campaign_id, campaign_day, planned_time, selected_channels, approved_channels, schedule_state)'
                            " VALUES (:id, :ws, CAST(:slot_date AS date), :slot_type, :pillar, :format, :status, :run_id, :campaign_id, :campaign_day, :planned_time, CAST(:selected AS jsonb), CAST(:approved AS jsonb), 'draft')"),
                       {'id': slot_id, 'ws': workspace_id, 'slot_date': slot_date,
                        'slot_type': body.slot_type, 'pillar': pillar, 'format': slot_format,
                        'status': status, 'run_id': body.run_id, 'campaign_id': body.campaign_id,
                        'campaign_day': body.campaign_day,
                        'planned_time': defaults.get(body.slot_type, '09:00'),
                        'selected': '[]', 'approved': '[]'})
        except IntegrityError as error:
            raise HTTPException(422, 'Calendar slot could not be stored: %s' % (error.orig,))
        row = db.execute(text('SELECT ' + _CALENDAR_PUBLIC_SELECT + ' FROM calendar_slots WHERE id=:id AND workspace_id=:ws'),
                         {'id': slot_id, 'ws': workspace_id}).mappings().first()
        if row is None:
            raise HTTPException(500, 'Calendar slot was not stored')
        if body.run_id:
            store.audit(db, body.run_id, 'calendar_slot_created', actor, workspace_id)
        return _public_calendar_slot(row)


@app.post('/api/calendar/campaigns/{campaign_id}/place', response_model=list[CalendarSlotOut], status_code=201)
def place_campaign_on_calendar(campaign_id: str, body: CalendarPlaceIn, actor: str = Depends(auth.actor)):
    from datetime import timedelta
    from launchcrew import calendar as calendar_mod
    start = calendar_mod.parse_slot_date(body.start_date)
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        campaign = db.execute(text('SELECT 1 FROM campaigns WHERE id=:id AND workspace_id=:ws'),
                              {'id': campaign_id, 'ws': workspace_id}).fetchone()
        if campaign is None:
            raise HTTPException(404, 'Campaign not found')
        days = db.execute(text('SELECT d.day, d.run_id, r.receipt FROM campaign_days d JOIN runs r ON r.id=d.run_id'
                               ' WHERE d.campaign_id=:id AND d.workspace_id=:ws AND r.workspace_id=:ws ORDER BY d.day'),
                          {'id': campaign_id, 'ws': workspace_id}).all()
        if len(days) != 7:
            raise HTTPException(422, 'Campaign week needs seven days before calendar placement')
        placed = []
        defaults = _schedule_defaults(db, workspace_id)
        for day, run_id, receipt in days:
            slot_date = (start + timedelta(days=int(day) - 1)).isoformat()
            slot_type = calendar_mod.slot_type_for_day(int(day))
            pillar = calendar_mod.pillar_for_day(int(day))
            status = calendar_mod.status_for_receipt(receipt)
            slot_id = 'slot_' + uuid4().hex
            db.execute(text('INSERT INTO calendar_slots(id, workspace_id, slot_date, slot_type, pillar, format, status, run_id, campaign_id, campaign_day, planned_time, selected_channels, approved_channels, schedule_state)'
                            " VALUES (:id, :ws, CAST(:slot_date AS date), :slot_type, :pillar, :format, :status, :run_id, :campaign_id, :campaign_day, :planned_time, CAST(:selected AS jsonb), CAST(:approved AS jsonb), 'draft')"),
                       {'id': slot_id, 'ws': workspace_id, 'slot_date': slot_date,
                        'slot_type': slot_type, 'pillar': pillar, 'format': slot_type,
                        'status': status, 'run_id': run_id, 'campaign_id': campaign_id,
                        'campaign_day': int(day),
                        'planned_time': defaults.get(slot_type, '09:00'),
                        'selected': '[]', 'approved': '[]'})
            store.audit(db, run_id, 'calendar_slot_created', actor, workspace_id)
            placed.append(slot_id)
        rows = db.execute(text('SELECT ' + _CALENDAR_PUBLIC_SELECT + ' FROM calendar_slots WHERE id = ANY(:ids) ORDER BY slot_date, slot_type, id'),
                         {'ids': placed}).mappings().all()
        return [_public_calendar_slot(row) for row in rows]


@app.delete('/api/calendar/slots/{slot_id}', status_code=204)
def delete_calendar_slot(slot_id: str, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        result = db.execute(text('DELETE FROM calendar_slots WHERE id=:id AND workspace_id=:ws'),
                            {'id': slot_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Calendar slot not found')
    return Response(status_code=204)


# S4 schedule slots: planned times, validate gate, and schedule export.
# Scheduling is planning only; it never publishes.


class ScheduleDefaultsIn(Strict):
    defaults: dict[str, str]


class ScheduleDefaultsOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    defaults: dict[str, str] = {}


class SlotScheduleIn(Strict):
    planned_date: str | None = Field(default=None, min_length=10, max_length=10)
    planned_time: str | None = Field(default=None, min_length=5, max_length=5)
    selected_channels: list[str] | None = None
    approved_channels: list[str] | None = None


class SlotChannelsApproveIn(Strict):
    channels: list[str] = Field(min_length=1)
    expected_revision: StrictInt | None = Field(default=None, ge=0)


class ValidateReadyOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    ready_eligible: bool = False
    failing_conditions: list[str] = []
    checks: dict[str, bool] = {}
    details: list[str] = []
    unapproved_channels: list[str] = []
    format_reason: str | None = None


def _load_slot(db, slot_id, workspace_id):
    row = db.execute(text('SELECT ' + _CALENDAR_PUBLIC_SELECT + ' FROM calendar_slots WHERE id=:id AND workspace_id=:ws'),
                     {'id': slot_id, 'ws': workspace_id}).mappings().first()
    if row is None:
        raise HTTPException(404, 'Calendar slot not found')
    return dict(row)


def _evaluate_slot_ready(slot, receipt):
    """Validate gate: pack approval, format check, channel variant approval.

    Zero overrides: every condition must pass. Returns a dict with
    ready_eligible, failing_conditions (codes), checks, human details,
    the unapproved channel list, and the exact format reason.
    """
    from launchcrew import calendar as calendar_mod
    from launchcrew import channel_variants as channel_mod
    from launchcrew import human_review
    failing: list[str] = []
    details: list[str] = []
    pack_approved = (isinstance(receipt, dict)
                     and receipt.get('approval_state') == 'approved_for_export')
    if not pack_approved:
        failing.append(calendar_mod.PACK_NOT_APPROVED)
        details.append('Pack is not approved')
    if not isinstance(receipt, dict):
        format_passed = False
        format_reason = 'Format check unavailable; link an approved run'
    else:
        format_reason = human_review.format_block_reason(receipt)
        format_passed = format_reason is None
    if not format_passed:
        failing.append(calendar_mod.FORMAT_CHECK_FAILED)
        details.append(format_reason or 'Format check failed')
    selected = slot.get('selected_channels') if isinstance(slot, dict) else None
    selected = list(selected) if isinstance(selected, list) else []
    unapproved: list[str] = []
    if not selected:
        unapproved = []
        details.append('No channels selected')
        failing.append(calendar_mod.UNAPPROVED_CHANNEL_VARIANTS)
        variants_approved = False
    else:
        for channel in selected:
            _, current, _ = channel_mod.channel_approval_status(receipt, channel)
            if not current:
                unapproved.append(channel)
        if unapproved:
            failing.append(calendar_mod.UNAPPROVED_CHANNEL_VARIANTS)
            details.append('Unapproved channel variants: ' + ', '.join(unapproved))
        variants_approved = not unapproved
    return {'ready_eligible': not failing,
            'failing_conditions': failing,
            'checks': {'pack_approved': pack_approved,
                       'format_passed': format_passed,
                       'variants_approved': variants_approved},
            'details': details,
            'unapproved_channels': unapproved,
            'format_reason': format_reason if not format_passed else None}


def _receipt_for_slot(db, slot, workspace_id):
    run_id = slot.get('run_id')
    if not run_id:
        return None
    row = db.execute(text('SELECT receipt FROM runs WHERE id=:id AND workspace_id=:ws'),
                     {'id': run_id, 'ws': workspace_id}).fetchone()
    if row is None:
        return None
    return row[0]


@app.get('/api/calendar/schedule-defaults', response_model=ScheduleDefaultsOut)
def get_schedule_defaults(actor: str = Depends(auth.actor)):
    """Owner daily default planned times per slot type (planning only)."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return {'defaults': _schedule_defaults(db, workspace_id)}


@app.put('/api/calendar/schedule-defaults', response_model=ScheduleDefaultsOut)
def put_schedule_defaults(body: ScheduleDefaultsIn, actor: str = Depends(auth.actor)):
    """Set owner daily default planned times per slot type (planning only)."""
    from launchcrew import calendar as calendar_mod
    cleaned: dict[str, str] = {}
    for slot_type, planned_time in (body.defaults or {}).items():
        try:
            calendar_mod.normalize_slot_type(slot_type)
        except ValueError:
            raise HTTPException(422, 'Unknown slot type: %s' % slot_type)
        try:
            cleaned[slot_type] = calendar_mod.normalize_planned_time(planned_time)
        except ValueError:
            raise HTTPException(422, 'planned_time for %s must be HH:MM' % slot_type)
    if not cleaned:
        raise HTTPException(422, 'defaults must name at least one slot type')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        for slot_type, planned_time in cleaned.items():
            db.execute(text('INSERT INTO calendar_schedule_defaults(workspace_id, slot_type, planned_time)'
                            ' VALUES (:ws, :slot_type, :planned_time)'
                            ' ON CONFLICT (workspace_id, slot_type) DO UPDATE SET planned_time=EXCLUDED.planned_time'),
                       {'ws': workspace_id, 'slot_type': slot_type, 'planned_time': planned_time})
        return {'defaults': _schedule_defaults(db, workspace_id)}


@app.patch('/api/calendar/slots/{slot_id}/schedule', response_model=CalendarSlotOut)
def update_slot_schedule(slot_id: str, body: SlotScheduleIn, actor: str = Depends(auth.actor)):
    """Edit planning fields on one slot: date, time, channel selection.

    Planning only; it never publishes. Changing the date, time, or
    channel selection resets a Ready slot to draft for revalidation.
    """
    from launchcrew import calendar as calendar_mod
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        updates: dict[str, Any] = {}
        demote = False
        if body.planned_date is not None:
            _parse_calendar_date(body.planned_date, 'planned_date')
            current_date = slot['slot_date']
            if hasattr(current_date, 'isoformat'):
                current_date = current_date.isoformat()
            if body.planned_date != current_date:
                updates['slot_date'] = body.planned_date
                demote = True
        if body.planned_time is not None:
            try:
                updates['planned_time'] = calendar_mod.normalize_planned_time(body.planned_time)
            except ValueError:
                raise HTTPException(422, 'planned_time must be HH:MM from 00:00 to 23:59')
            if updates['planned_time'] != (slot.get('planned_time') or ''):
                demote = True
        if body.selected_channels is not None:
            try:
                selected = calendar_mod.normalize_channel_list(body.selected_channels, 'selected_channels')
            except ValueError as error:
                raise HTTPException(422, str(error))
            updates['selected_channels'] = json.dumps(selected)
            if selected != (slot.get('selected_channels') or []):
                demote = True
        if body.approved_channels is not None:
            try:
                approved = calendar_mod.normalize_channel_list(body.approved_channels, 'approved_channels')
            except ValueError as error:
                raise HTTPException(422, str(error))
            updates['approved_channels'] = json.dumps(approved)
        if not updates and not demote:
            return _public_calendar_slot(slot)
        clauses = []
        params: dict[str, Any] = {'id': slot_id, 'ws': workspace_id}
        if 'slot_date' in updates:
            clauses.append('slot_date=CAST(:slot_date AS date)')
            params['slot_date'] = updates['slot_date']
        if 'planned_time' in updates:
            clauses.append('planned_time=:planned_time')
            params['planned_time'] = updates['planned_time']
        if 'selected_channels' in updates:
            clauses.append('selected_channels=CAST(:selected_channels AS jsonb)')
            params['selected_channels'] = updates['selected_channels']
        if 'approved_channels' in updates:
            clauses.append('approved_channels=CAST(:approved_channels AS jsonb)')
            params['approved_channels'] = updates['approved_channels']
        if demote:
            clauses.append("schedule_state='draft'")
        clauses.append('updated_at=now()')
        db.execute(text('UPDATE calendar_slots SET ' + ', '.join(clauses) + ' WHERE id=:id AND workspace_id=:ws'), params)
        store.audit(db, slot.get('run_id'), 'calendar_slot_scheduled', actor, workspace_id)
        return _public_calendar_slot(_load_slot(db, slot_id, workspace_id))


@app.post('/api/calendar/slots/{slot_id}/approve-channels', response_model=CalendarSlotOut)
def approve_slot_channels(slot_id: str, body: SlotChannelsApproveIn, actor: str = Depends(auth.actor)):
    """Approve exact channel variant texts for one slot through its run.

    Each named channel is human-approved on the linked run receipt
    (exact text, current revision, current pack binding); the slot
    mirrors the approvals. Pack approval and the exportable gate stay
    required with no override.
    """
    from launchcrew import calendar as calendar_mod
    from launchcrew import channel_variants as channel_mod
    try:
        channels = calendar_mod.normalize_channel_list(body.channels, 'channels')
    except ValueError as error:
        raise HTTPException(422, str(error))
    if not channels:
        raise HTTPException(422, 'channels must name at least one channel')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        run_id = slot.get('run_id')
        if not run_id:
            raise HTTPException(422, 'Slot has no linked run; link a run before approving channels')
        for channel in channels:
            receipt = _receipt_for_slot(db, slot, workspace_id)
            if receipt is None:
                raise HTTPException(404, 'Run not found')
            try:
                revised = channel_mod.approve_channel_variant(receipt, channel, actor, body.expected_revision)
            except ValueError as error:
                message = str(error)
                if 'stale' in message.lower():
                    raise HTTPException(409, message)
                raise HTTPException(422, message)
            result = db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id AND workspace_id=:ws'),
                                {'receipt': json.dumps(revised), 'state': revised['approval_state'],
                                 'id': run_id, 'ws': workspace_id})
            if result.rowcount == 0:
                raise HTTPException(404, 'Run not found')
            store.audit(db, run_id, 'channel_variant_approval', actor, workspace_id)
        merged = sorted(set((slot.get('approved_channels') or [])) | set(channels))
        db.execute(text('UPDATE calendar_slots SET approved_channels=CAST(:approved AS jsonb), updated_at=now()'
                        ' WHERE id=:id AND workspace_id=:ws'),
                   {'approved': json.dumps(merged), 'id': slot_id, 'ws': workspace_id})
        store.audit(db, run_id, 'calendar_slot_channels_approved', actor, workspace_id)
        return _public_calendar_slot(_load_slot(db, slot_id, workspace_id))


@app.get('/api/calendar/slots/{slot_id}/validate-ready', response_model=ValidateReadyOut)
def validate_slot_ready(slot_id: str, actor: str = Depends(auth.actor)):
    """Validate gate: name exactly which Ready conditions fail, if any."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        receipt = _receipt_for_slot(db, slot, workspace_id)
        return _evaluate_slot_ready(slot, receipt)


@app.post('/api/calendar/slots/{slot_id}/mark-ready', response_model=CalendarSlotOut)
def mark_slot_ready(slot_id: str, actor: str = Depends(auth.actor)):
    """Mark one slot Ready only when all three gate conditions pass.

    No override: any failing condition returns 409 naming each
    failing condition instead of marking the slot Ready.
    """
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        receipt = _receipt_for_slot(db, slot, workspace_id)
        evaluation = _evaluate_slot_ready(slot, receipt)
        if not evaluation['ready_eligible']:
            raise HTTPException(409, detail={'message': 'Slot is not ready; resolve every failing condition',
                                            'failing_conditions': evaluation['failing_conditions'],
                                            'details': evaluation['details'],
                                            'checks': evaluation['checks'],
                                            'unapproved_channels': evaluation['unapproved_channels'],
                                            'format_reason': evaluation['format_reason']})
        db.execute(text("UPDATE calendar_slots SET schedule_state='ready', updated_at=now()"
                        ' WHERE id=:id AND workspace_id=:ws'),
                   {'id': slot_id, 'ws': workspace_id})
        store.audit(db, slot.get('run_id'), 'calendar_slot_marked_ready', actor, workspace_id)
        return _public_calendar_slot(_load_slot(db, slot_id, workspace_id))


@app.get('/api/calendar/schedule-export')
def export_validated_schedule(actor: str = Depends(auth.actor)):
    """Export the validated schedule JSON hand-off (planning only).

    Lists only Ready slots (marked Ready with every gate condition
    still passing) with channel variants, times, and pack references.
    Non-Ready slots are excluded by name with their exact reasons.
    Nothing is submitted anywhere; no publish, post, or send occurs.
    """
    from launchcrew import channel_variants as channel_mod
    from launchcrew import human_review
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        rows = db.execute(text('SELECT ' + _CALENDAR_PUBLIC_SELECT + ' FROM calendar_slots WHERE workspace_id=:ws'
                               ' ORDER BY slot_date, slot_type, id'),
                          {'ws': workspace_id}).mappings().all()
        ready_slots: list[dict[str, Any]] = []
        excluded_slots: list[dict[str, Any]] = []
        for raw in rows:
            slot = _public_calendar_slot(dict(raw))
            receipt = _receipt_for_slot(db, dict(raw), workspace_id)
            evaluation = _evaluate_slot_ready(dict(raw), receipt)
            if slot['schedule_state'] == 'ready' and evaluation['ready_eligible']:
                variants = []
                for channel in slot['selected_channels']:
                    record, _, _ = channel_mod.channel_approval_status(receipt, channel)
                    variants.append({'channel': channel, 'approved': True,
                                     'approved_by': (record or {}).get('approved_by', ''),
                                     'revision': (record or {}).get('revision')})
                pack_reference: dict[str, Any] = {'run_id': slot['run_id'], 'approval_state': None,
                                                  'revision': None, 'binding_digest': None}
                if isinstance(receipt, dict):
                    try:
                        binding = human_review.approval_binding(receipt)
                        digest = binding.get('digest')
                    except Exception:
                        digest = None
                    pack_reference = {'run_id': slot['run_id'],
                                      'approval_state': receipt.get('approval_state'),
                                      'revision': human_review.current_revision(receipt),
                                      'binding_digest': digest}
                ready_slots.append({'slot_id': slot['id'], 'slot_date': slot['slot_date'],
                                    'planned_time': slot['planned_time'], 'slot_type': slot['slot_type'],
                                    'pillar': slot['pillar'], 'format_key': slot['format'],
                                    'run_id': slot['run_id'], 'campaign_id': slot['campaign_id'],
                                    'day_number': slot['campaign_day'],
                                    'selected_channels': slot['selected_channels'],
                                    'channel_variants': variants,
                                    'pack_reference': pack_reference})
            else:
                if slot['schedule_state'] != 'ready' and evaluation['ready_eligible']:
                    reasons = ['Slot is not marked Ready']
                    codes = ['not_marked_ready']
                else:
                    reasons = evaluation['details']
                    codes = evaluation['failing_conditions']
                excluded_slots.append({'slot_id': slot['id'], 'slot_date': slot['slot_date'],
                                       'slot_type': slot['slot_type'],
                                       'failing_conditions': codes, 'reasons': reasons})
        return {'schema_version': 'schedule-export/v1',
                'exported_at': datetime.now(timezone.utc).isoformat(),
                'publishing_mode': 'planning_only_never_publishes',
                'ready_slots': ready_slots,
                'excluded_slots': excluded_slots}


# S5 cross-post verification board: one delivery row per slot per channel.
# Delivery states are not_posted, posted, verified, and failed. Verification
# compares fetched or supplied live content against the approved channel
# variant text (exact, trimmed-by-rule, or mismatch). Every state change
# appends a timestamped attempt; earlier attempts are never overwritten.
# Verified rows feed the outcome log. Nothing here publishes anything.

DeliveryState = Literal['not_posted', 'posted', 'verified', 'failed']
DeliveryMatchKind = Literal['exact', 'trimmed_by_rule', 'mismatch']


class DeliveryOut(Strict):
    id: str
    slot_id: str
    channel: str
    delivery_state: DeliveryState
    live_url: str | None = None
    match_kind: DeliveryMatchKind | None = None
    differing_field: str | None = None
    failure_reason: str | None = None
    attempts: list[dict[str, Any]] = Field(default_factory=list)


class DeliveryMarkPostedIn(Strict):
    live_url: str = Field(min_length=1, max_length=2000)
    live_text: str | None = Field(default=None, max_length=20000)
    live_subject: str | None = Field(default=None, max_length=2000)
    verify_now: bool = False


class DeliveryVerifyIn(Strict):
    live_url: str | None = Field(default=None, max_length=2000)
    live_text: str | None = Field(default=None, max_length=20000)
    live_subject: str | None = Field(default=None, max_length=2000)


class DeliveryFailIn(Strict):
    reason: str = Field(min_length=1, max_length=2000)
    live_url: str | None = Field(default=None, max_length=2000)


class DeliveryOutcomeIn(Strict):
    posted_date: str = Field(min_length=10, max_length=10)
    likes: StrictInt = Field(ge=0, le=OUTCOME_MAX_COUNT)
    comments: StrictInt = Field(ge=0, le=OUTCOME_MAX_COUNT)
    clicks: StrictInt = Field(ge=0, le=OUTCOME_MAX_COUNT)
    sales: StrictInt = Field(ge=0, le=OUTCOME_MAX_COUNT)
    note: str = Field(min_length=1, max_length=OUTCOME_MAX_NOTE_LENGTH)


_DELIVERY_PUBLIC_SELECT = ('id, slot_id, channel, delivery_state, live_url, '
                           'match_kind, differing_field, failure_reason, attempts')


def _public_delivery(row):
    if not isinstance(row, dict):
        try:
            row = dict(row)
        except Exception:
            row = {}
    attempts = row.get('attempts')
    return {'id': row.get('id'), 'slot_id': row.get('slot_id'),
            'channel': row.get('channel'),
            'delivery_state': row.get('delivery_state', 'not_posted'),
            'live_url': row.get('live_url'),
            'match_kind': row.get('match_kind'),
            'differing_field': row.get('differing_field'),
            'failure_reason': row.get('failure_reason'),
            'attempts': list(attempts) if isinstance(attempts, list) else []}


def _normalize_delivery_channel(channel):
    from launchcrew import verification_board as board_mod
    try:
        return board_mod.normalize_channel(channel)
    except ValueError as error:
        raise HTTPException(422, str(error))


def _load_or_init_delivery(db, slot, workspace_id, channel):
    from launchcrew import verification_board as board_mod
    row = db.execute(text('SELECT ' + _DELIVERY_PUBLIC_SELECT + ' FROM calendar_slot_deliveries'
                          ' WHERE slot_id=:slot AND channel=:channel AND workspace_id=:ws'),
                     {'slot': slot['id'], 'channel': channel, 'ws': workspace_id}).mappings().first()
    if row is not None:
        return dict(row)
    delivery_id = 'del_' + uuid4().hex
    db.execute(text('INSERT INTO calendar_slot_deliveries(id, workspace_id, slot_id, channel, delivery_state)'
                    ' VALUES (:id, :ws, :slot, :channel, :state)'),
               {'id': delivery_id, 'ws': workspace_id, 'slot': slot['id'],
                'channel': channel, 'state': 'not_posted'})
    created = db.execute(text('SELECT ' + _DELIVERY_PUBLIC_SELECT + ' FROM calendar_slot_deliveries'
                              ' WHERE id=:id AND workspace_id=:ws'),
                         {'id': delivery_id, 'ws': workspace_id}).mappings().first()
    if created is None:
        raise HTTPException(404, 'Calendar slot not found')
    return dict(created)


def _save_delivery_attempt(db, delivery, workspace_id, state, live_url=None,
                           match_kind=None, differing_field=None, reason=None,
                           live_text_excerpt=''):
    from launchcrew import verification_board as board_mod
    trail = delivery.get('attempts')
    trail = list(trail) if isinstance(trail, list) else []
    entry = board_mod.build_attempt(state, live_url=live_url, match_kind=match_kind,
                                    differing_field=differing_field, reason=reason,
                                    live_text_excerpt=live_text_excerpt or '')
    updated_trail = board_mod.append_attempt(trail, entry)
    db.execute(text('UPDATE calendar_slot_deliveries SET delivery_state=:state, live_url=:url,'
                    ' match_kind=:match, differing_field=:field, failure_reason=:reason,'
                    ' attempts=CAST(:attempts AS jsonb), updated_at=now()'
                    ' WHERE id=:id AND workspace_id=:ws'),
               {'state': state, 'url': live_url, 'match': match_kind, 'field': differing_field,
                'reason': reason, 'attempts': json.dumps(updated_trail),
                'id': delivery['id'], 'ws': workspace_id})
    row = db.execute(text('SELECT ' + _DELIVERY_PUBLIC_SELECT + ' FROM calendar_slot_deliveries'
                          ' WHERE id=:id AND workspace_id=:ws'),
                     {'id': delivery['id'], 'ws': workspace_id}).mappings().first()
    if row is None:
        raise HTTPException(404, 'Calendar slot delivery not found')
    return dict(row)


def _approved_variant_for_slot(db, slot, workspace_id, channel):
    from launchcrew import channel_variants as channel_mod
    from launchcrew import verification_board as board_mod
    run_id = slot.get('run_id')
    if not run_id:
        raise HTTPException(422, 'Slot has no linked run; link a run before verifying deliveries')
    receipt = _receipt_for_slot(db, slot, workspace_id)
    if receipt is None:
        raise HTTPException(404, 'Run not found')
    if channel not in channel_mod.CHANNELS:
        raise HTTPException(422, 'Unknown channel: ' + channel)
    try:
        bundle = channel_mod.checked_channel_variants(receipt)
    except ValueError as error:
        raise HTTPException(422, str(error))
    entry = bundle.get(channel) if isinstance(bundle, dict) else None
    if not isinstance(entry, dict) or not entry.get('text'):
        raise HTTPException(422, 'No approved variant text for channel: ' + channel)
    approved_text, approved_subject = board_mod.approved_text_for_channel(entry)
    if not approved_text:
        raise HTTPException(422, 'No approved variant text for channel: ' + channel)
    return approved_text, approved_subject


def _sync_slot_verified(db, slot, workspace_id):
    """Sync the slot status to verified once its channels verify.

    When the slot names selected channels, all of them must reach
    verified. When it names none, a single verified delivery row is
    enough. Verified is terminal and automatic sync never demotes.
    """
    from launchcrew import calendar as calendar_mod
    rows = db.execute(text('SELECT channel, delivery_state FROM calendar_slot_deliveries'
                           ' WHERE slot_id=:slot AND workspace_id=:ws'),
                      {'slot': slot['id'], 'ws': workspace_id}).mappings().all()
    verified = {str(entry['channel']) for entry in rows
                if entry.get('delivery_state') == 'verified'}
    if not verified:
        return
    selected = slot.get('selected_channels')
    selected = list(selected) if isinstance(selected, list) else []
    ready = all(channel in verified for channel in selected) if selected else True
    if ready and calendar_mod.should_advance(slot.get('status'), 'verified'):
        db.execute(text("UPDATE calendar_slots SET status='verified', updated_at=now()"
                        ' WHERE id=:id AND workspace_id=:ws'),
                   {'id': slot['id'], 'ws': workspace_id})


def _run_delivery_verification(db, slot, delivery, workspace_id, channel,
                               live_url=None, live_text=None, live_subject=None):
    from launchcrew import verification_board as board_mod
    approved_text, approved_subject = _approved_variant_for_slot(db, slot, workspace_id, channel)
    supplied_url = live_url if live_url is not None else delivery.get('live_url')
    supplied_text = live_text
    supplied_subject = live_subject
    if supplied_text is None and supplied_url is None:
        raise HTTPException(422, 'Provide live_text or a live_url to verify')
    if supplied_url is not None:
        try:
            board_mod.normalize_live_url(supplied_url)
        except ValueError as error:
            raise HTTPException(422, str(error))
    try:
        live_content, live_sub, _ = board_mod.resolve_live_content(
            live_url=supplied_url, live_text=supplied_text, live_subject=supplied_subject)
    except ValueError as error:
        updated = _save_delivery_attempt(db, delivery, workspace_id, 'failed',
                                         live_url=supplied_url, match_kind='mismatch',
                                         differing_field='text', reason=str(error),
                                         live_text_excerpt='')
        return _public_delivery(updated)
    outcome = board_mod.compare_live_post_to_variant(
        approved_text, live_content, approved_subject=approved_subject,
        live_subject=live_sub, channel=channel)
    updated = _save_delivery_attempt(
        db, delivery, workspace_id, outcome['delivery_state'], live_url=supplied_url,
        match_kind=outcome['match_kind'], differing_field=outcome['differing_field'],
        reason=outcome['failure_reason'],
        live_text_excerpt=board_mod.excerpt(live_content))
    _sync_slot_verified(db, slot, workspace_id)
    return _public_delivery(updated)


@app.get('/api/calendar/verification-board', response_model=list[DeliveryOut])
def list_verification_board(slot_id: str | None = None, actor: str = Depends(auth.actor)):
    """List slot-channel delivery rows, one row per channel per slot.

    Rows mirror each slot selected channels; channels without a stored
    delivery read as not_posted with an empty attempt trail.
    """
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        params: dict[str, Any] = {'ws': workspace_id}
        slot_filter = ''
        if slot_id is not None:
            slot_filter = ' AND id=:slot'
            params['slot'] = slot_id
        slots = db.execute(text('SELECT ' + _CALENDAR_PUBLIC_SELECT + ' FROM calendar_slots'
                                ' WHERE workspace_id=:ws' + slot_filter
                                + ' ORDER BY slot_date, slot_type, id'),
                           params).mappings().all()
        board: list[dict[str, Any]] = []
        for raw in slots:
            slot = _public_calendar_slot(dict(raw))
            selected = slot.get('selected_channels')
            channels = list(selected) if isinstance(selected, list) else []
            stored = db.execute(text('SELECT ' + _DELIVERY_PUBLIC_SELECT + ' FROM calendar_slot_deliveries'
                                     ' WHERE slot_id=:slot AND workspace_id=:ws'),
                                {'slot': slot['id'], 'ws': workspace_id}).mappings().all()
            by_channel = {str(entry['channel']): dict(entry) for entry in stored}
            for channel in channels:
                if channel in by_channel:
                    board.append(_public_delivery(by_channel[channel]))
                else:
                    board.append({'id': 'pending:' + slot['id'] + ':' + channel,
                                  'slot_id': slot['id'], 'channel': channel,
                                  'delivery_state': 'not_posted', 'live_url': None,
                                  'match_kind': None, 'differing_field': None,
                                  'failure_reason': None, 'attempts': []})
        return board


@app.get('/api/calendar/slots/{slot_id}/deliveries', response_model=list[DeliveryOut])
def list_slot_deliveries(slot_id: str, actor: str = Depends(auth.actor)):
    """List per-channel delivery rows and attempts for one slot."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        rows = db.execute(text('SELECT ' + _DELIVERY_PUBLIC_SELECT + ' FROM calendar_slot_deliveries'
                               ' WHERE slot_id=:slot AND workspace_id=:ws ORDER BY channel, id'),
                          {'slot': slot['id'], 'ws': workspace_id}).mappings().all()
        return [_public_delivery(dict(entry)) for entry in rows]


@app.post('/api/calendar/slots/{slot_id}/deliveries/{channel}/mark-posted',
          response_model=DeliveryOut)
def mark_delivery_posted(slot_id: str, channel: str, body: DeliveryMarkPostedIn,
                         actor: str = Depends(auth.actor)):
    """Mark one slot channel posted with the live URL.

    Records a posted attempt. When verify_now is true and live content
    is available (explicit live_text or the live URL), verification runs
    immediately and its attempt is appended after the posted attempt.
    """
    from launchcrew import verification_board as board_mod
    key = _normalize_delivery_channel(channel)
    try:
        live_url = board_mod.normalize_live_url(body.live_url)
    except ValueError as error:
        raise HTTPException(422, str(error))
    try:
        live_text = board_mod.normalize_optional_text(body.live_text, 'live_text')
        live_subject = board_mod.normalize_optional_text(body.live_subject, 'live_subject', 2000)
    except ValueError as error:
        raise HTTPException(422, str(error))
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        delivery = _load_or_init_delivery(db, slot, workspace_id, key)
        stored_url = delivery.get('live_url')
        posted = _save_delivery_attempt(
            db, delivery, workspace_id, 'posted',
            live_url=live_url if live_url != stored_url or delivery.get('delivery_state') != 'posted' else stored_url,
            live_text_excerpt=board_mod.excerpt(live_text or ''))
        if body.verify_now and (live_text is not None or live_url):
            return _run_delivery_verification(db, slot, posted, workspace_id, key,
                                              live_url=live_url, live_text=live_text,
                                              live_subject=live_subject)
        return _public_delivery(posted)


@app.post('/api/calendar/slots/{slot_id}/deliveries/{channel}/verify',
          response_model=DeliveryOut)
def verify_delivery(slot_id: str, channel: str, body: DeliveryVerifyIn,
                    actor: str = Depends(auth.actor)):
    """Verify one delivery against the approved channel variant.

    Compares the live post (explicit live_text wins; otherwise the
    given or stored live URL is fetched with an SSRF guard) against
    the approved variant text: exact match or trimmed-by-rule verifies,
    any difference fails with the differing field named. Mismatch is a
    visible failure state, never a silent pass. The verification is
    appended as a new timestamped attempt.
    """
    from launchcrew import verification_board as board_mod
    key = _normalize_delivery_channel(channel)
    try:
        live_text = board_mod.normalize_optional_text(body.live_text, 'live_text')
        live_subject = board_mod.normalize_optional_text(body.live_subject, 'live_subject', 2000)
        live_url = None
        if body.live_url is not None:
            live_url = board_mod.normalize_live_url(body.live_url)
    except ValueError as error:
        raise HTTPException(422, str(error))
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        delivery = _load_or_init_delivery(db, slot, workspace_id, key)
        return _run_delivery_verification(db, slot, delivery, workspace_id, key,
                                          live_url=live_url, live_text=live_text,
                                          live_subject=live_subject)


@app.post('/api/calendar/slots/{slot_id}/deliveries/{channel}/fail',
          response_model=DeliveryOut)
def fail_delivery(slot_id: str, channel: str, body: DeliveryFailIn,
                  actor: str = Depends(auth.actor)):
    """Record an owner-reported failure for one delivery row."""
    from launchcrew import verification_board as board_mod
    key = _normalize_delivery_channel(channel)
    reason = body.reason.strip() if isinstance(body.reason, str) else ''
    if not reason:
        raise HTTPException(422, 'reason must be a nonempty string')
    for char in reason:
        code = ord(char)
        if code < 32 or code == 127:
            raise HTTPException(422, 'reason contains unsafe control characters')
    try:
        live_url = None
        if body.live_url is not None:
            live_url = board_mod.normalize_live_url(body.live_url)
    except ValueError as error:
        raise HTTPException(422, str(error))
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        delivery = _load_or_init_delivery(db, slot, workspace_id, key)
        kept_url = live_url if live_url is not None else delivery.get('live_url')
        updated = _save_delivery_attempt(db, delivery, workspace_id, 'failed',
                                         live_url=kept_url, reason=reason,
                                         live_text_excerpt='')
        return _public_delivery(updated)


@app.post('/api/calendar/slots/{slot_id}/deliveries/{channel}/outcomes',
          response_model=OutcomeOut, status_code=201)
def create_delivery_outcome(slot_id: str, channel: str, body: DeliveryOutcomeIn,
                            actor: str = Depends(auth.actor)):
    """Attach outcome numbers from a verified board row to the outcome log.

    Refuses with 409 unless the delivery row is verified. The linked
    run must still hold an approved current exported revision, matching
    the standard outcome gate. Delivery channels outside the outcome
    channel set log under other.
    """
    if not actor or actor == 'demo_placeholder':
        raise HTTPException(401, 'Sign in required to log owner-reported outcomes')
    key = _normalize_delivery_channel(channel)
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        delivery = _load_or_init_delivery(db, slot, workspace_id, key)
        if delivery.get('delivery_state') != 'verified':
            raise HTTPException(409, 'Outcome logging requires a verified delivery row')
        run_id = slot.get('run_id')
        if not run_id:
            raise HTTPException(422, 'Slot has no linked run; link a run before logging outcomes')
        receipt = get_receipt(db, run_id, workspace_id, True)
        _reject_when_running(receipt)
        export_revision = _outcome_export_revision(receipt)
        outcome_channel = key if key in OUTCOME_KNOWN_CHANNELS else 'other'
        try:
            _parse_calendar_date(body.posted_date, 'posted_date')
            posted_value = body.posted_date
        except HTTPException as error:
            raise HTTPException(422, 'posted_date must be a real calendar date in YYYY-MM-DD format') from error
        if not body.note.strip():
            raise HTTPException(422, 'note must not be empty')
        outcome_id = 'out_' + uuid4().hex
        db.execute(text('INSERT INTO run_outcomes(id, run_id, workspace_id, export_revision, channel, posted_date, likes, comments, clicks, sales, note, provenance, actor)'
                        ' VALUES (:id, :run, :ws, :rev, :channel, CAST(:posted AS date), :likes, :comments, :clicks, :sales, :note, :prov, :actor)'),
                   {'id': outcome_id, 'run': run_id, 'ws': workspace_id, 'rev': export_revision,
                    'channel': outcome_channel, 'posted': posted_value, 'likes': body.likes,
                    'comments': body.comments, 'clicks': body.clicks, 'sales': body.sales,
                    'note': body.note, 'prov': OUTCOME_PROVENANCE, 'actor': actor})
        store.audit(db, run_id, 'delivery_outcome_logged', actor, workspace_id)
        row = db.execute(text('SELECT ' + _OUTCOME_PUBLIC_SELECT + ' FROM run_outcomes WHERE id=:id AND workspace_id=:ws'),
                         {'id': outcome_id, 'ws': workspace_id}).mappings().first()
        if row is None:
            raise HTTPException(404, 'Run not found')
        return _public_outcome(row)
