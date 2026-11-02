"""Typed FastAPI demo API over the preserved Python pipeline."""
from contextlib import asynccontextmanager
import copy
import json
import secrets
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
    """Return the per-channel capabilities table (account_capabilities pattern, as data).

    When the workspace has a connected brand account for a channel, the
    fetched live account row overrides the baseline S2 row with source
    live_account_capabilities and the connected handle. Otherwise the
    baseline S2 row is returned with source baseline.
    """
    from launchcrew.format_library import list_channel_capabilities as _list_capabilities
    baseline = _list_capabilities()
    try:
        with store.connect() as db:
            workspace_id = store.ensure_workspace_seeded(db, actor)
            return _overlay_live_capabilities(db, workspace_id, baseline)
    except Exception:
        return [{**row, 'source': 'baseline', 'connected': False} for row in baseline]


def _connected_accounts_by_platform(db, workspace_id):
    from launchcrew import social_connections as social_mod
    try:
        rows = db.execute(text('SELECT platform, account_handle, capabilities FROM social_connections'
                               ' WHERE workspace_id=:ws AND status=:status'),
                          {'ws': workspace_id, 'status': 'connected'}).mappings().all()
    except Exception:
        return {}
    grouped = {}
    for row in rows:
        platform = str(row.get('platform') or '').strip().lower()
        if social_mod.normalize_platform(platform) is None:
            continue
        grouped[platform] = {'account_handle': row.get('account_handle'),
                             'capabilities': row.get('capabilities') or {}}
    return grouped


def _overlay_live_capabilities(db, workspace_id, baseline_rows):
    from launchcrew import social_connections as social_mod
    grouped = _connected_accounts_by_platform(db, workspace_id)
    overlaid = []
    seen = set()
    for row in baseline_rows or []:
        channel = str((row or {}).get('channel') or '').strip().lower()
        seen.add(channel)
        live = grouped.get(channel)
        if live is not None:
            overlaid.append(social_mod.live_capability_row(channel, live['capabilities'], live['account_handle']))
        else:
            overlaid.append(social_mod.baseline_capability_row(channel, dict(row)))
    for platform, live in grouped.items():
        if platform not in seen:
            overlaid.append(social_mod.live_capability_row(platform, live['capabilities'], live['account_handle']))
    return overlaid


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
        _drop_ready_slots_for_run(db, run_id, workspace_id)
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
        try:
            bundle['capabilities'] = _overlay_live_capabilities(db, workspace_id, bundle.get('capabilities'))
        except Exception:
            pass
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
        try:
            bundle['capabilities'] = _overlay_live_capabilities(db, workspace_id, bundle.get('capabilities'))
        except Exception:
            pass
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
        _drop_ready_slots_for_run(db, run_id, workspace_id)


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


class OwnerTemplateIn(Strict):
    name: str = Field(min_length=1, max_length=FACT_LIBRARY_NAME_MAX)
    idea: str = Field(min_length=1, max_length=2000)
    agent_name: str = Field(default='Maker', min_length=1, max_length=120)
    scout_name: str | None = Field(default=None, min_length=1, max_length=120)
    maker_name: str | None = Field(default=None, min_length=1, max_length=120)
    checker_name: str | None = Field(default=None, min_length=1, max_length=120)
    checker_profile: Literal['standard', 'strict'] = Field(default='standard')
    product_facts: dict[str, Any] | None = None


class OwnerTemplateOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = ''
    name: str = ''
    idea: str = ''
    agent_name: str = 'Maker'
    scout_name: str | None = None
    maker_name: str | None = None
    checker_name: str | None = None
    checker_profile: str = 'standard'
    product_facts: dict[str, Any] | None = None
    run_count: int = 0
    created_at: Any | None = None
    updated_at: Any | None = None


def _get_owner_template(db, template_id, workspace_id, lock=False):
    row = db.execute(text('SELECT id, workspace_id, name, idea, agent_name, scout_name,'
                          ' maker_name, checker_name, checker_profile, product_facts,'
                          ' created_at, updated_at FROM owner_templates'
                          ' WHERE id=:id AND workspace_id=:ws' + (' FOR UPDATE' if lock else '')),
                     {'id': template_id, 'ws': workspace_id}).mappings().first()
    if row is None:
        raise HTTPException(404, 'Owner template not found')
    return dict(row)


def _public_owner_template(row):
    data = dict(row)
    for name in ('created_at', 'updated_at'):
        value = data.get(name)
        if hasattr(value, 'isoformat'):
            data[name] = value.isoformat()
    return {'id': data.get('id'), 'name': data.get('name'), 'idea': data.get('idea'),
            'agent_name': data.get('agent_name') or 'Maker',
            'scout_name': data.get('scout_name'), 'maker_name': data.get('maker_name'),
            'checker_name': data.get('checker_name'),
            'checker_profile': data.get('checker_profile') or 'standard',
            'product_facts': data.get('product_facts'),
            'created_at': data.get('created_at'), 'updated_at': data.get('updated_at')}


def _validate_owner_template_facts(product_facts):
    if product_facts is None:
        return None
    if not isinstance(product_facts, dict):
        raise HTTPException(422, 'Template product_facts must be an object')
    from launchcrew.facts import parse_product_facts
    try:
        parse_product_facts(product_facts)
    except ValueError as error:
        raise HTTPException(422, 'Template product_facts invalid: ' + str(error))
    return copy.deepcopy(product_facts)


@app.get('/api/owner-templates', response_model=list[OwnerTemplateOut])
def list_owner_templates(actor: str = Depends(auth.actor)):
    """List workspace owner templates with creation order."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        rows = db.execute(text('SELECT id, workspace_id, name, idea, agent_name, scout_name,'
                               ' maker_name, checker_name, checker_profile, product_facts,'
                               ' created_at, updated_at FROM owner_templates'
                               ' WHERE workspace_id=:ws ORDER BY created_at, id'),
                          {'ws': workspace_id}).mappings().all()
        return [_public_owner_template(dict(row)) for row in rows]


@app.post('/api/owner-templates', response_model=OwnerTemplateOut, status_code=201)
def create_owner_template(body: OwnerTemplateIn, actor: str = Depends(auth.actor)):
    """Save one owner template; duplicate names refuse with 409."""
    name = _clean_fact_library_name(body.name, 'Template')
    facts = _validate_owner_template_facts(body.product_facts)
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        existing = db.execute(text('SELECT id FROM owner_templates'
                                   ' WHERE workspace_id=:ws AND LOWER(name)=LOWER(:name)'),
                              {'ws': workspace_id, 'name': name}).fetchone()
        if existing:
            raise HTTPException(409, 'A template with this name already exists')
        template_id = 'otmp_' + uuid4().hex
        db.execute(text('INSERT INTO owner_templates(id, workspace_id, name, idea, agent_name,'
                        ' scout_name, maker_name, checker_name, checker_profile, product_facts)'
                        ' VALUES (:id,:ws,:name,:idea,:agent,:scout,:maker,:checker,:profile,'
                        'CAST(:facts AS jsonb))'),
                   {'id': template_id, 'ws': workspace_id, 'name': name,
                    'idea': body.idea.strip(), 'agent': (body.agent_name or 'Maker').strip(),
                    'scout': body.scout_name, 'maker': body.maker_name,
                    'checker': body.checker_name, 'profile': body.checker_profile,
                    'facts': json.dumps(facts) if facts is not None else None})
        store.audit(db, None, 'owner_template_created', actor, workspace_id)
        return _public_owner_template(_get_owner_template(db, template_id, workspace_id))


@app.get('/api/owner-templates/{template_id}', response_model=OwnerTemplateOut)
def get_owner_template(template_id: str, actor: str = Depends(auth.actor)):
    """Return one owner template."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return _public_owner_template(_get_owner_template(db, template_id, workspace_id))


@app.put('/api/owner-templates/{template_id}', response_model=OwnerTemplateOut)
def update_owner_template(template_id: str, body: OwnerTemplateIn,
                          actor: str = Depends(auth.actor)):
    """Replace one owner template; duplicate names refuse with 409."""
    name = _clean_fact_library_name(body.name, 'Template')
    facts = _validate_owner_template_facts(body.product_facts)
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _get_owner_template(db, template_id, workspace_id, lock=True)
        existing = db.execute(text('SELECT id FROM owner_templates'
                                   ' WHERE workspace_id=:ws AND LOWER(name)=LOWER(:name)'
                                   ' AND id<>:id'),
                              {'ws': workspace_id, 'name': name, 'id': template_id}).fetchone()
        if existing:
            raise HTTPException(409, 'A template with this name already exists')
        updated = db.execute(text('UPDATE owner_templates SET name=:name, idea=:idea,'
                                  ' agent_name=:agent, scout_name=:scout, maker_name=:maker,'
                                  ' checker_name=:checker, checker_profile=:profile,'
                                  ' product_facts=CAST(:facts AS jsonb), updated_at=now()'
                                  ' WHERE id=:id AND workspace_id=:ws'),
                             {'name': name, 'idea': body.idea.strip(),
                              'agent': (body.agent_name or 'Maker').strip(),
                              'scout': body.scout_name, 'maker': body.maker_name,
                              'checker': body.checker_name, 'profile': body.checker_profile,
                              'facts': json.dumps(facts) if facts is not None else None,
                              'id': template_id, 'ws': workspace_id})
        if updated.rowcount == 0:
            raise HTTPException(404, 'Owner template not found')
        store.audit(db, None, 'owner_template_updated', actor, workspace_id)
        return _public_owner_template(_get_owner_template(db, template_id, workspace_id))


@app.delete('/api/owner-templates/{template_id}', status_code=204)
def delete_owner_template(template_id: str, actor: str = Depends(auth.actor)):
    """Delete one owner template; runs created from it keep their snapshots."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _get_owner_template(db, template_id, workspace_id, lock=True)
        result = db.execute(text('DELETE FROM owner_templates WHERE id=:id AND workspace_id=:ws'),
                            {'id': template_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Owner template not found')
        store.audit(db, None, 'owner_template_deleted', actor, workspace_id)
    return Response(status_code=204)


@app.post('/api/owner-templates/{template_id}/apply', response_model=Receipt, status_code=201)
def apply_owner_template(template_id: str, actor: str = Depends(auth.actor)):
    """Create a run from one owner template through the normal pipeline.

    The run binds a snapshot copy of the template facts and the
    missing-core facts gate applies with no template waiver, so later
    template edits never rewrite the stored run receipt.
    """
    from types import SimpleNamespace
    from backend import adapter, model_admission
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        template = _get_owner_template(db, template_id, workspace_id)
        facts_raw = copy.deepcopy(template.get('product_facts')) \
            if isinstance(template.get('product_facts'), dict) else None
        _enforce_missing_core_gate(facts_raw, False)
        body = SimpleNamespace(agent_name=template.get('agent_name') or 'Maker',
                               scout_name=template.get('scout_name'),
                               maker_name=template.get('maker_name'),
                               checker_name=template.get('checker_name'))
        legacy, scout, maker, checker = load_stage_profiles(db, body, workspace_id)
        _, maker_name, _ = stage_names(body)
    run_id = 'run_' + uuid4().hex
    factory = model_admission.admission_factory_for_run(store.engine(), run_id)
    receipt = adapter.execute(
        run_id, template['idea'], legacy, False, memory_items=[],
        checker_profile=template.get('checker_profile') or 'standard',
        scout_profile=scout, maker_profile=maker, checker_agent=checker,
        product_facts=facts_raw, model_admission_factory=factory,
        fact_library=None)
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _mark_sync_voice_stale_if_changed(db, receipt, workspace_id, actor, lock=True, selection=None)
        save_run(db, receipt, maker_name, actor, workspace_id)
        store.audit(db, run_id, 'owner_template_applied', actor, workspace_id)
    return receipt


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
    outcome_badge: dict[str, Any] | None = None


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
            'schedule_state': state if state in ('draft', 'ready', 'needs_approval') else 'draft',
            'outcome_badge': row.get('outcome_badge')}


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
        badges = _slot_outcome_badges(db, workspace_id, [slot['id'] for slot in synced])
        decorated = []
        for slot in synced:
            slot = dict(slot)
            slot['outcome_badge'] = badges.get(slot['id'])
            decorated.append(_public_calendar_slot(slot))
        return decorated


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


def _media_gate_reasons(db, slot_id, workspace_id):
    """Collect failing Checker media reasons attached to one slot.

    Missing tables (before the SC4 migration) or slots with no media
    attachments read as no media reasons, never as a gate failure.
    """
    try:
        rows = db.execute(text('SELECT format_validation FROM media_attachments'
                               ' WHERE slot_id=:slot AND workspace_id=:ws'),
                          {'slot': slot_id, 'ws': workspace_id}).mappings().all()
    except Exception:
        return []
    reasons: list[str] = []
    for row in rows:
        validation = row.get('format_validation')
        if isinstance(validation, dict) and validation.get('passed') is False:
            for reason in validation.get('reasons') or []:
                if isinstance(reason, str) and reason.strip() and reason not in reasons:
                    reasons.append(reason)
    return reasons


def _evaluate_slot_ready(slot, receipt, media_reasons=None):
    """Validate gate: pack approval, format check, channel variant approval.

    Zero overrides: every condition must pass. A failing Checker media
    validation attached to the slot also fails the format condition
    with the aspect ratio mismatch named. Returns a dict with
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
    for reason in media_reasons or []:
        if not isinstance(reason, str) or not reason.strip():
            continue
        if calendar_mod.FORMAT_CHECK_FAILED not in failing:
            failing.append(calendar_mod.FORMAT_CHECK_FAILED)
        if reason not in details:
            details.append(reason)
        format_passed = False
        if format_reason is None:
            format_reason = reason
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
        return _evaluate_slot_ready(slot, receipt,
                                    _media_gate_reasons(db, slot['id'], workspace_id))


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
        evaluation = _evaluate_slot_ready(slot, receipt,
                                          _media_gate_reasons(db, slot['id'], workspace_id))
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
            evaluation = _evaluate_slot_ready(dict(raw), receipt,
                                              _media_gate_reasons(db, slot['id'], workspace_id))
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


# SC3 analytics pull: provider metrics for verified deliveries only.
# Every canonical metric (reach, likes, comments, clicks, shares) is
# either an integer or the exact string "not reported". Unsupported
# or omitted metrics are never coerced to a fake 0. Pulls sync into
# the run outcome log labeled with source and fetch time, and feed
# the calendar outcome badges.

class AnalyticsPullOut(Strict):
    id: str
    slot_id: str
    channel: str
    run_id: str | None = None
    outcome_id: str | None = None
    source_label: str
    refresh_mode: Literal['manual', 'scheduled']
    fetched_at: datetime
    metrics: dict[str, Any]
    reported_metrics: list[str] = Field(default_factory=list)
    unreported_metrics: list[str] = Field(default_factory=list)


class AnalyticsRefreshIn(Strict):
    provider_metrics: dict[str, Any] | None = None
    source_label: str | None = Field(default=None, max_length=120)


class AnalyticsScheduledIn(Strict):
    slot_ids: list[str] | None = None


class SlotAnalyticsOut(Strict):
    slot_id: str
    has_outcomes: bool = False
    channel_badges: list[dict[str, Any]] = Field(default_factory=list)
    summary_text: str = ''


class ScheduledRefreshOut(Strict):
    refreshed: list[AnalyticsPullOut] = Field(default_factory=list)
    skipped_unverified: list[str] = Field(default_factory=list)


_ANALYTICS_PUBLIC_SELECT = ('id, slot_id, channel, run_id, outcome_id, '
                            'source_label, refresh_mode, fetched_at, metrics, '
                            'reported_metrics, unreported_metrics, '
                            'raw_provider_payload, created_at')


def _public_analytics_pull(row):
    if not isinstance(row, dict):
        try:
            row = dict(row)
        except Exception:
            row = {}
    fetched = row.get('fetched_at')
    if hasattr(fetched, 'isoformat'):
        fetched = fetched.isoformat()
    reported = row.get('reported_metrics')
    unreported = row.get('unreported_metrics')
    return {'id': row.get('id'), 'slot_id': row.get('slot_id'),
            'channel': row.get('channel'), 'run_id': row.get('run_id'),
            'outcome_id': row.get('outcome_id'),
            'source_label': row.get('source_label'),
            'refresh_mode': row.get('refresh_mode'), 'fetched_at': fetched,
            'metrics': dict(row.get('metrics') or {}),
            'reported_metrics': list(reported) if isinstance(reported, list) else [],
            'unreported_metrics': list(unreported) if isinstance(unreported, list) else []}


def _verified_delivery_or_409(db, slot, workspace_id, channel):
    row = db.execute(text('SELECT ' + _DELIVERY_PUBLIC_SELECT + ' FROM calendar_slot_deliveries'
                          ' WHERE slot_id=:slot AND channel=:channel AND workspace_id=:ws'),
                     {'slot': slot['id'], 'channel': channel, 'ws': workspace_id}).mappings().first()
    if row is None or dict(row).get('delivery_state') != 'verified':
        raise HTTPException(409, 'delivery_not_verified: post is not verified for channel ' + channel)
    return dict(row)


def _sync_provider_outcome(db, slot, workspace_id, channel, source_label,
                           fetched_at, metrics, outcome_id, actor):
    """Create or update the linked run_outcomes row for a provider pull.

    The row is labeled with the provider source and fetch time in its
    note, which preserves the exact metrics rendering including
    "not reported" markers. Integer columns carry reported counts;
    unreported metrics read as not reported in the note, never as
    measured zeros.
    """
    from launchcrew import analytics_pull as analytics_mod
    run_id = slot.get('run_id')
    if not run_id:
        return None
    exists = db.execute(text('SELECT 1 FROM runs WHERE id=:id AND workspace_id=:ws'),
                        {'id': run_id, 'ws': workspace_id}).fetchone()
    if exists is None:
        return None
    outcome_channel = channel if channel in OUTCOME_KNOWN_CHANNELS else 'other'
    note = analytics_mod.outcome_note(source_label, fetched_at, channel, metrics)
    if len(note) > 500:
        note = note[:500]
    likes = metrics.get('likes')
    comments = metrics.get('comments')
    clicks = metrics.get('clicks')
    posted = slot.get('slot_date')
    if hasattr(posted, 'isoformat'):
        posted = posted.isoformat()
    if not isinstance(posted, str) or not posted:
        posted = fetched_at[:10]
    try:
        receipt_row = db.execute(text('SELECT receipt FROM runs WHERE id=:id AND workspace_id=:ws'),
                                 {'id': run_id, 'ws': workspace_id}).fetchone()
        receipt = receipt_row[0] if receipt_row else None
        revision = receipt.get('revision', 0) if isinstance(receipt, dict) else 0
    except Exception:
        revision = 0
    sync_actor = actor if actor and actor != 'demo_placeholder' else 'provider_sync'
    values = {'likes': likes if type(likes) is int else 0,
              'comments': comments if type(comments) is int else 0,
              'clicks': clicks if type(clicks) is int else 0,
              'note': note, 'channel': outcome_channel, 'posted': posted,
              'rev': revision if isinstance(revision, int) and revision >= 0 else 0,
              'prov': OUTCOME_PROVENANCE, 'actor': sync_actor,
              'run': run_id, 'ws': workspace_id}
    if outcome_id:
        kept = db.execute(text('SELECT id FROM run_outcomes WHERE id=:id AND workspace_id=:ws'),
                          {'id': outcome_id, 'ws': workspace_id}).fetchone()
        if kept is not None:
            db.execute(text('UPDATE run_outcomes SET channel=:channel, posted_date=CAST(:posted AS date),'
                            ' likes=:likes, comments=:comments, clicks=:clicks,'
                            ' note=:note, provenance=:prov, actor=:actor'
                            ' WHERE id=:id AND workspace_id=:ws'),
                       dict(values, id=outcome_id))
            return outcome_id
    fresh_id = 'out_' + uuid4().hex
    db.execute(text('INSERT INTO run_outcomes(id, run_id, workspace_id, export_revision, channel, posted_date, likes, comments, clicks, sales, note, provenance, actor)'
                    ' VALUES (:id, :run, :ws, :rev, :channel, CAST(:posted AS date), :likes, :comments, :clicks, 0, :note, :prov, :actor)'),
               dict(values, id=fresh_id))
    return fresh_id


def _refresh_delivery_analytics(db, slot, workspace_id, channel, refresh_mode,
                                provider_metrics, source_label, actor):
    """Refresh provider metrics for one verified delivery (upsert per slot+channel)."""
    from launchcrew import analytics_pull as analytics_mod
    key = _normalize_delivery_channel(channel)
    _verified_delivery_or_409(db, slot, workspace_id, key)
    try:
        mode = analytics_mod.normalize_refresh_mode(refresh_mode)
    except ValueError as error:
        raise HTTPException(422, str(error))
    try:
        source = analytics_mod.normalize_source_label(source_label, key)
    except ValueError as error:
        raise HTTPException(422, str(error))
    try:
        built = analytics_mod.build_metrics(key, provider_metrics)
    except ValueError as error:
        raise HTTPException(422, str(error))
    fetched_at = analytics_mod.utc_now_iso()
    raw = dict(provider_metrics) if isinstance(provider_metrics, dict) else analytics_mod.adapter_metrics(key)
    existing = db.execute(text('SELECT ' + _ANALYTICS_PUBLIC_SELECT + ' FROM analytics_pulls'
                               ' WHERE slot_id=:slot AND channel=:channel AND workspace_id=:ws'),
                          {'slot': slot['id'], 'channel': key, 'ws': workspace_id}).mappings().first()
    prior_outcome = dict(existing).get('outcome_id') if existing is not None else None
    params = {'ws': workspace_id, 'slot': slot['id'], 'channel': key,
              'run': slot.get('run_id'), 'source': source,
              'mode': mode, 'fetched': fetched_at,
              'metrics': json.dumps(built['metrics']),
              'reported': json.dumps(built['reported_metrics']),
              'unreported': json.dumps(built['unreported_metrics']),
              'raw': json.dumps(raw)}
    if existing is not None:
        pull_id = dict(existing)['id']
        db.execute(text('UPDATE analytics_pulls SET run_id=:run,'
                        ' source_label=:source, refresh_mode=:mode, fetched_at=CAST(:fetched AS timestamptz),'
                        ' metrics=CAST(:metrics AS jsonb), reported_metrics=CAST(:reported AS jsonb),'
                        ' unreported_metrics=CAST(:unreported AS jsonb),'
                        ' raw_provider_payload=CAST(:raw AS jsonb)'
                        ' WHERE id=:id AND workspace_id=:ws'),
                   dict(params, id=pull_id))
    else:
        pull_id = 'apull_' + uuid4().hex
        db.execute(text('INSERT INTO analytics_pulls(id, workspace_id, slot_id, channel, run_id, source_label, refresh_mode, fetched_at, metrics, reported_metrics, unreported_metrics, raw_provider_payload)'
                        ' VALUES (:id, :ws, :slot, :channel, :run, :source, :mode, CAST(:fetched AS timestamptz), CAST(:metrics AS jsonb), CAST(:reported AS jsonb), CAST(:unreported AS jsonb), CAST(:raw AS jsonb))'),
                   dict(params, id=pull_id))
    stored = db.execute(text('SELECT ' + _ANALYTICS_PUBLIC_SELECT + ' FROM analytics_pulls'
                             ' WHERE id=:id AND workspace_id=:ws'),
                        {'id': pull_id, 'ws': workspace_id}).mappings().first()
    if stored is None:
        raise HTTPException(500, 'Analytics pull was not stored')
    stored_fetched = _public_analytics_pull(dict(stored))['fetched_at']
    outcome_id = _sync_provider_outcome(db, slot, workspace_id, key, source,
                                        stored_fetched, built['metrics'], prior_outcome, actor)
    db.execute(text('UPDATE analytics_pulls SET outcome_id=:outcome WHERE id=:id AND workspace_id=:ws'),
               {'outcome': outcome_id, 'id': pull_id, 'ws': workspace_id})
    store.audit(db, slot.get('run_id'), 'analytics_pull_refreshed', actor, workspace_id)
    fresh = db.execute(text('SELECT ' + _ANALYTICS_PUBLIC_SELECT + ' FROM analytics_pulls'
                            ' WHERE id=:id AND workspace_id=:ws'),
                       {'id': pull_id, 'ws': workspace_id}).mappings().first()
    if fresh is None:
        raise HTTPException(500, 'Analytics pull was not stored')
    return _public_analytics_pull(dict(fresh))


def _slot_badge_from_pulls(pull_rows):
    from launchcrew import analytics_pull as analytics_mod
    badges = [analytics_mod.build_channel_badge(entry['channel'], entry['source_label'],
                                                entry['fetched_at'], entry['refresh_mode'],
                                                entry['metrics'])
              for entry in pull_rows]
    return analytics_mod.build_outcome_badge(badges)


def _slot_outcome_badges(db, workspace_id, slot_ids):
    """Map slot ids to calendar outcome badges from the latest pulls."""
    if not slot_ids:
        return {}
    rows = db.execute(text('SELECT ' + _ANALYTICS_PUBLIC_SELECT + ' FROM analytics_pulls'
                           ' WHERE workspace_id=:ws AND slot_id = ANY(:slots)'
                           ' ORDER BY fetched_at DESC, id'),
                      {'ws': workspace_id, 'slots': list(slot_ids)}).mappings().all()
    by_slot: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        public = _public_analytics_pull(dict(row))
        by_slot.setdefault(public['slot_id'], []).append(public)
    return {slot_id: _slot_badge_from_pulls(pulls) for slot_id, pulls in by_slot.items()}


@app.post('/api/calendar/slots/{slot_id}/deliveries/{channel}/analytics/refresh',
          response_model=AnalyticsPullOut)
def refresh_delivery_analytics(slot_id: str, channel: str, body: AnalyticsRefreshIn,
                               actor: str = Depends(auth.actor)):
    """Manually refresh provider metrics for one verified delivery.

    Refuses with 409 unless the delivery row is verified. Accepts an
    optional explicit provider payload; otherwise a deterministic
    platform adapter supplies the supported metrics. Unsupported or
    omitted metrics store as "not reported", never as 0. The pull
    syncs into the run outcome log with source and fetch time.
    """
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        return _refresh_delivery_analytics(db, slot, workspace_id, channel, 'manual',
                                           body.provider_metrics, body.source_label, actor)


@app.post('/api/analytics/refresh-scheduled', response_model=ScheduledRefreshOut)
def refresh_scheduled_analytics(body: AnalyticsScheduledIn,
                                actor: str = Depends(auth.actor)):
    """Batch-refresh provider metrics for verified deliveries on a schedule.

    Refreshes every verified slot delivery in the workspace (or only
    the given slot ids) with refresh_mode "scheduled". Unverified
    deliveries are skipped and named, never pulled.
    """
    from launchcrew import verification_board as board_mod
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        if body.slot_ids is None:
            rows = db.execute(text('SELECT id FROM calendar_slots WHERE workspace_id=:ws'),
                              {'ws': workspace_id}).mappings().all()
            slot_ids = [str(entry['id']) for entry in rows]
        else:
            slot_ids = []
            for entry in body.slot_ids:
                if not isinstance(entry, str) or not entry.strip():
                    raise HTTPException(422, 'slot_ids must list nonempty slot ids')
                slot_ids.append(entry.strip())
            for slot_id in slot_ids:
                _load_slot(db, slot_id, workspace_id)
        refreshed: list[dict[str, Any]] = []
        skipped: list[str] = []
        for slot_id in slot_ids:
            slot = _load_slot(db, slot_id, workspace_id)
            deliveries = db.execute(text('SELECT ' + _DELIVERY_PUBLIC_SELECT
                                        + ' FROM calendar_slot_deliveries'
                                          ' WHERE slot_id=:slot AND workspace_id=:ws'),
                                    {'slot': slot['id'], 'ws': workspace_id}).mappings().all()
            for entry in deliveries:
                delivery = dict(entry)
                channel = board_mod.normalize_channel(str(delivery.get('channel') or ''))
                if delivery.get('delivery_state') != 'verified':
                    skipped.append(slot['id'] + ':' + channel)
                    continue
                refreshed.append(_refresh_delivery_analytics(db, slot, workspace_id, channel,
                                                             'scheduled', None, None, actor))
        return {'refreshed': refreshed, 'skipped_unverified': skipped}


@app.get('/api/analytics/pulls', response_model=list[AnalyticsPullOut])
def list_analytics_pulls(slot_id: str | None = None, channel: str | None = None,
                         actor: str = Depends(auth.actor)):
    """List analytics pulls, newest first, with optional slot and channel filters."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        clauses = ['workspace_id=:ws']
        params: dict[str, Any] = {'ws': workspace_id}
        if slot_id is not None:
            clauses.append('slot_id=:slot')
            params['slot'] = slot_id
        if channel is not None:
            clauses.append('channel=:channel')
            params['channel'] = _normalize_delivery_channel(channel)
        rows = db.execute(text('SELECT ' + _ANALYTICS_PUBLIC_SELECT + ' FROM analytics_pulls WHERE '
                               + ' AND '.join(clauses) + ' ORDER BY fetched_at DESC, id'),
                          params).mappings().all()
        return [_public_analytics_pull(dict(entry)) for entry in rows]


@app.get('/api/calendar/slots/{slot_id}/analytics', response_model=SlotAnalyticsOut)
def get_slot_analytics(slot_id: str, actor: str = Depends(auth.actor)):
    """Return the calendar outcome badge for one slot."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        badges = _slot_outcome_badges(db, workspace_id, [slot['id']])
        badge = badges.get(slot['id'], {'has_outcomes': False,
                                        'channel_badges': [], 'summary_text': ''})
        return {'slot_id': slot['id'], 'has_outcomes': badge['has_outcomes'],
                'channel_badges': badge['channel_badges'],
                'summary_text': badge['summary_text']}


class SocialPlatformOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    platform: str = ''
    priority: bool = False
    tier: str = ''
    enabled: bool = False
    status: str = ''
    oauth_configured: bool = False
    limitation: str | None = None
    flag_name: str | None = None
    client_env: str | None = None


class SocialConnectionOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = ''
    workspace_id: str = ''
    platform: str = ''
    account_handle: str | None = None
    account_name: str | None = None
    external_account_id: str | None = None
    account_type: str = 'brand'
    status: str = ''
    token_present: bool = False
    has_token: bool = False
    token_security: str = ''
    scopes: list[str] = []
    scopes_plain: list[str] = []
    capabilities: dict[str, Any] = {}
    capabilities_source: str = ''
    connected_at: Any | None = None
    disconnected_at: Any | None = None


class SocialConnectIn(Strict):
    account_type: str = 'brand'


class SocialCallbackIn(Strict):
    code: str | None = Field(default=None, max_length=2000)
    token: str | None = Field(default=None, max_length=4000)
    handle: str | None = Field(default=None, max_length=200)
    account_handle: str | None = Field(default=None, max_length=200)
    account_name: str | None = Field(default=None, max_length=200)
    external_account_id: str | None = Field(default=None, max_length=200)
    account_type: str = 'brand'
    scopes: list[str] = Field(default_factory=list, max_length=50)


def _require_social_platform(platform: str) -> str:
    from launchcrew import social_connections as social_mod
    key = social_mod.normalize_platform(platform)
    if key is None:
        raise HTTPException(404, 'Unknown social platform')
    return key


def _social_row_to_public(row) -> dict[str, Any]:
    from launchcrew import social_connections as social_mod
    data = dict(row) if not isinstance(row, dict) else dict(row)
    return social_mod.public_connection(data)


@app.get('/api/social/platforms', response_model=list[SocialPlatformOut])
def list_social_platforms(actor: str = Depends(auth.actor)):
    """List all 12 social platforms with priority vs flag-gated status."""
    from launchcrew import social_connections as social_mod
    with store.connect() as db:
        store.ensure_workspace_seeded(db, actor)
    return social_mod.list_platforms()


@app.get('/api/social/connections', response_model=list[SocialConnectionOut])
def list_social_connections(actor: str = Depends(auth.actor)):
    """List workspace brand account connections without ever exposing tokens."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        try:
            rows = db.execute(text('SELECT id, workspace_id, platform, account_handle, account_name,'
                                   ' external_account_id, account_type, encrypted_token, scopes, scopes_plain,'
                                   ' capabilities, status, connected_at, disconnected_at'
                                   ' FROM social_connections WHERE workspace_id=:ws ORDER BY platform'),
                              {'ws': workspace_id}).mappings().all()
        except Exception:
            return []
        return [_social_row_to_public(dict(row)) for row in rows]


@app.post('/api/social/connections/{platform}/connect')
def initiate_social_connect(platform: str, body: SocialConnectIn | None = None,
                            actor: str = Depends(auth.actor)):
    """Initiate the OAuth authorize URL for one platform.

    Refuses flag-gated platforms when the capability flag is disabled,
    naming the flag with 409. Never creates a connection row: only an
    explicit owner callback completes a brand account connection.
    """
    from launchcrew import social_connections as social_mod
    key = _require_social_platform(platform)
    requested_type = (body.account_type if body is not None else 'brand')
    if isinstance(requested_type, str) and requested_type.strip().lower() != 'brand':
        raise HTTPException(422, 'Only brand accounts may be connected by explicit owner action;'
                                 ' personal accounts are never connected')
    if not social_mod.platform_enabled(key):
        raise HTTPException(409, 'Platform %s is behind capability flag %s pending platform review' % (
            key, social_mod.flag_name_for(key)))
    with store.connect() as db:
        store.ensure_workspace_seeded(db, actor)
    state = secrets.token_urlsafe(24)
    client_env = social_mod.CLIENT_ENV_BY_PLATFORM.get(key, '')
    configured = social_mod.oauth_configured(key)
    limitation = social_mod.limitation_for(key)
    authorize_url = ('https://connect.example.com/%s/authorize?state=%s' % (key, state))
    if configured:
        authorize_url += '&client_configured=true'
    return {'platform': key, 'authorize_url': authorize_url, 'state': state,
            'oauth_configured': configured, 'limitation': limitation,
            'account_type': 'brand',
            'note': 'Complete the brand account connection with the callback step; only brand accounts connect.'}


@app.post('/api/social/connections/{platform}/callback', response_model=SocialConnectionOut)
@app.post('/api/social/connections/{platform}/complete', response_model=SocialConnectionOut)
def complete_social_connect(platform: str, body: SocialCallbackIn,
                            actor: str = Depends(auth.actor)):
    """Complete a brand account OAuth connection: encrypt token and fetch live capabilities.

    Accepts the provider code or token plus the brand handle, refuses
    personal accounts, refuses flag-gated platforms when the flag is
    disabled, and never echoes the token in the response.
    """
    from launchcrew import social_connections as social_mod
    key = _require_social_platform(platform)
    try:
        social_mod.validate_brand_account(body.account_type)
    except ValueError as error:
        raise HTTPException(422, str(error))
    if not social_mod.platform_enabled(key):
        raise HTTPException(409, 'Platform %s is behind capability flag %s pending platform review' % (
            key, social_mod.flag_name_for(key)))
    raw_token = (body.token or '').strip() or (body.code or '').strip()
    if not raw_token:
        raise HTTPException(422, 'A provider code or token is required to complete the brand connection')
    handle = (body.handle or body.account_handle or '').strip() or ('@brand-%s' % key)
    name = (body.account_name or '').strip() or handle
    external_id = (body.external_account_id or '').strip() or ('ext_%s_%s' % (key, handle.lstrip('@')))
    scopes = [str(item).strip() for item in (body.scopes or []) if isinstance(item, str) and item.strip()][:50]
    if not scopes:
        scopes = ['brand_profile', 'brand_capabilities_read']
    try:
        encrypted = social_mod.encrypt_token(raw_token)
    except ValueError as error:
        raise HTTPException(422, str(error))
    scopes_plain = social_mod.scopes_to_plain(scopes)
    capabilities = social_mod.fetch_live_capabilities(key)
    connection_id = 'conn_' + uuid4().hex
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        db.execute(text('INSERT INTO social_connections(id, workspace_id, platform, account_handle, account_name,'
                        ' external_account_id, account_type, encrypted_token, scopes, scopes_plain, capabilities,'
                        ' status, connected_at, disconnected_at)'
                        ' VALUES (:id,:ws,:platform,:handle,:name,:ext,:atype,:token,'
                        'CAST(:scopes AS jsonb),CAST(:plain AS jsonb),CAST(:caps AS jsonb),:status,now(),NULL)'
                        ' ON CONFLICT (workspace_id, platform) DO UPDATE SET'
                        ' account_handle=EXCLUDED.account_handle, account_name=EXCLUDED.account_name,'
                        ' external_account_id=EXCLUDED.external_account_id, account_type=EXCLUDED.account_type,'
                        ' encrypted_token=EXCLUDED.encrypted_token, scopes=EXCLUDED.scopes,'
                        ' scopes_plain=EXCLUDED.scopes_plain, capabilities=EXCLUDED.capabilities,'
                        ' status=:status, connected_at=now(), disconnected_at=NULL, updated_at=now()'),
                   {'id': connection_id, 'ws': workspace_id, 'platform': key, 'handle': handle,
                    'name': name, 'ext': external_id, 'atype': 'brand', 'token': encrypted,
                    'scopes': json.dumps(scopes), 'plain': json.dumps(scopes_plain),
                    'caps': json.dumps(capabilities), 'status': 'connected'})
        store.audit(db, None, 'social_connected', actor, workspace_id)
        row = db.execute(text('SELECT id, workspace_id, platform, account_handle, account_name,'
                              ' external_account_id, account_type, encrypted_token, scopes, scopes_plain,'
                              ' capabilities, status, connected_at, disconnected_at'
                              ' FROM social_connections WHERE workspace_id=:ws AND platform=:platform'),
                         {'ws': workspace_id, 'platform': key}).mappings().first()
        if row is None:
            raise HTTPException(404, 'Connection not found')
        return _social_row_to_public(dict(row))


@app.post('/api/social/connections/{platform}/disconnect', response_model=SocialConnectionOut)
def disconnect_social_connection(platform: str, actor: str = Depends(auth.actor)):
    """One-tap disconnect: revokes where the platform allows and deletes the stored token.

    Sets encrypted_token NULL and status disconnected while leaving all
    run receipts, verification history, and exports intact and exportable.
    """
    key = _require_social_platform(platform)
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        row = db.execute(text('SELECT id, workspace_id, platform, account_handle, account_name,'
                              ' external_account_id, account_type, encrypted_token, scopes, scopes_plain,'
                              ' capabilities, status, connected_at, disconnected_at'
                              ' FROM social_connections WHERE workspace_id=:ws AND platform=:platform'),
                         {'ws': workspace_id, 'platform': key}).mappings().first()
        if row is None:
            raise HTTPException(404, 'Connection not found')
        db.execute(text('UPDATE social_connections SET encrypted_token=NULL, status=:status,'
                        ' disconnected_at=now(), updated_at=now()'
                        ' WHERE workspace_id=:ws AND platform=:platform'),
                   {'status': 'disconnected', 'ws': workspace_id, 'platform': key})
        store.audit(db, None, 'social_disconnected', actor, workspace_id)
        updated = db.execute(text('SELECT id, workspace_id, platform, account_handle, account_name,'
                                  ' external_account_id, account_type, encrypted_token, scopes, scopes_plain,'
                                  ' capabilities, status, connected_at, disconnected_at'
                                  ' FROM social_connections WHERE workspace_id=:ws AND platform=:platform'),
                             {'ws': workspace_id, 'platform': key}).mappings().first()
        if updated is None:
            raise HTTPException(404, 'Connection not found')
        return _social_row_to_public(dict(updated))


# SC2 autonomous Ready-slot publish executor: execution runs only on
# calendar slots in Ready state at the slot scheduled time, with no
# per-post tap. The executor re-checks the approval binding at
# execution time; any mismatch or later edit drops the slot out of
# Ready and skips it as needs-approval without calling any platform
# transport. Each attempt is recorded under a deterministic idempotency
# key with bounded automatic retries (at most 2). Platform success
# records posted and hands off to the S5 verification board; it never
# marks a slot verified. The owner kill switch pauses all execution
# without touching calendar slots or packs.

class KillSwitchIn(Strict):
    paused: bool = False
    reason: str | None = Field(default=None, max_length=500)


class KillSwitchOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    paused: bool = False
    updated_at: Any | None = None
    updated_by: str | None = None
    reason: str | None = None


class PublishExecutionAttemptOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    attempt_number: int = 0
    timestamp: str | None = None
    channel: str = ''
    idempotency_key: str = ''
    backoff_seconds: int = 0
    outcome: str = ''
    platform_post_id: str | None = None
    live_url: str | None = None
    failure_reason: str | None = None


class PublishExecutionOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = ''
    slot_id: str = ''
    channel: str = ''
    idempotency_key: str = ''
    status: str = 'pending'
    platform_post_id: str | None = None
    live_url: str | None = None
    attempt_count: int = 0
    max_auto_retries: int = 2
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    last_error: str | None = None


class ExecuteDueIn(Strict):
    as_of: str | None = Field(default=None, max_length=64)
    simulate_failure: str | None = Field(default=None, max_length=64)


class SlotExecuteIn(Strict):
    simulate_failure: str | None = Field(default=None, max_length=64)


class PublishDueSlotOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    slot_id: str = ''
    slot_date: str = ''
    planned_time: str = ''
    channels: list[str] = Field(default_factory=list)


class SlotExecuteResultOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    slot_id: str = ''
    executed: bool = False
    skipped: bool = False
    paused: bool = False
    failing_condition: str | None = None
    reason: str | None = None
    executions: list[PublishExecutionOut] = Field(default_factory=list)


class ExecuteDueOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    as_of: str = ''
    paused: bool = False
    executed_slots: list[str] = Field(default_factory=list)
    skipped_slots: list[dict[str, Any]] = Field(default_factory=list)
    results: list[SlotExecuteResultOut] = Field(default_factory=list)


class PublishStatusOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    kill_switch: KillSwitchOut = Field(default_factory=KillSwitchOut)
    due_slots: list[PublishDueSlotOut] = Field(default_factory=list)
    ready_slots: list[PublishDueSlotOut] = Field(default_factory=list)
    executions: list[PublishExecutionOut] = Field(default_factory=list)


def _drop_ready_slots_for_run(db, run_id, workspace_id):
    """Drop linked Ready slots to needs-approval after a post-approval edit.

    Any revision or invalidation of the run pack means the slot is no
    longer Ready, so the executor will skip it at execution time.
    """
    db.execute(text("UPDATE calendar_slots SET schedule_state='needs_approval', updated_at=now()"
                    " WHERE run_id=:run AND workspace_id=:ws AND schedule_state='ready'"),
               {'run': run_id, 'ws': workspace_id})


def _publish_kill_switch(db, workspace_id):
    row = db.execute(text('SELECT workspace_id, kill_switch_paused, updated_at, updated_by, reason'
                          ' FROM publish_executor_settings WHERE workspace_id=:ws'),
                     {'ws': workspace_id}).mappings().first()
    if row is None:
        return {'paused': False, 'updated_at': None, 'updated_by': None, 'reason': None}
    updated = row['updated_at']
    if isinstance(updated, datetime):
        updated = updated.isoformat()
    return {'paused': bool(row['kill_switch_paused']), 'updated_at': updated,
            'updated_by': row['updated_by'], 'reason': row['reason']}


def _parse_execute_as_of(value):
    if value is None:
        return datetime.now(timezone.utc)
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(422, 'as_of must be a nonempty ISO timestamp')
    try:
        parsed = datetime.fromisoformat(cleaned.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(422, 'as_of must be an ISO timestamp')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _slot_scheduled_at(slot):
    """UTC datetime for a slot date plus planned time, or None."""
    from launchcrew import calendar as calendar_mod
    raw_date = slot.get('slot_date') or ''
    if hasattr(raw_date, 'isoformat'):
        raw_date = raw_date.isoformat()
    try:
        day = calendar_mod.parse_slot_date(raw_date)
        planned = calendar_mod.normalize_planned_time(slot.get('planned_time') or '09:00')
    except ValueError:
        return None
    hours, minutes = int(planned[0:2]), int(planned[3:5])
    return datetime(day.year, day.month, day.day, hours, minutes, tzinfo=timezone.utc)


def _slot_is_due(slot, as_of):
    scheduled = _slot_scheduled_at(slot)
    return scheduled is not None and scheduled <= as_of


def _public_execution(row):
    if not isinstance(row, dict):
        try:
            row = dict(row)
        except Exception:
            row = {}
    attempts = row.get('attempts')
    return {'id': row.get('id'), 'slot_id': row.get('slot_id'),
            'channel': row.get('channel'), 'idempotency_key': row.get('idempotency_key'),
            'status': row.get('status', 'pending'),
            'platform_post_id': row.get('platform_post_id'),
            'live_url': row.get('live_url'),
            'attempt_count': int(row.get('attempt_count') or 0),
            'max_auto_retries': int(row.get('max_auto_retries') or 2),
            'attempts': list(attempts) if isinstance(attempts, list) else [],
            'last_error': row.get('last_error')}


_EXECUTION_PUBLIC_SELECT = ('id, slot_id, channel, idempotency_key, status, platform_post_id,'
                            ' live_url, attempt_count, max_auto_retries, attempts, last_error')


def _load_execution_by_key(db, workspace_id, key):
    row = db.execute(text('SELECT ' + _EXECUTION_PUBLIC_SELECT + ' FROM publish_executions'
                          ' WHERE idempotency_key=:key AND workspace_id=:ws'),
                     {'key': key, 'ws': workspace_id}).mappings().first()
    return dict(row) if row is not None else None


def _save_execution(db, workspace_id, slot_id, channel, key, status,
                    platform_post_id=None, live_url=None, attempt_count=0,
                    max_auto_retries=2, attempts=None, last_error=None):
    from launchcrew import publish_executor as executor_mod
    attempts = list(attempts) if isinstance(attempts, list) else []
    existing = _load_execution_by_key(db, workspace_id, key)
    if existing is None:
        execution_id = 'exe_' + uuid4().hex
        db.execute(text('INSERT INTO publish_executions(id, workspace_id, slot_id, channel,'
                        ' idempotency_key, status, platform_post_id, live_url, attempt_count,'
                        ' max_auto_retries, attempts, last_error)'
                        ' VALUES (:id,:ws,:slot,:channel,:key,:status,:post,:url,:count,:retries,'
                        'CAST(:attempts AS jsonb),:error)'),
                   {'id': execution_id, 'ws': workspace_id, 'slot': slot_id,
                    'channel': channel, 'key': key, 'status': status,
                    'post': platform_post_id, 'url': live_url, 'count': attempt_count,
                    'retries': max_auto_retries, 'attempts': json.dumps(attempts),
                    'error': last_error})
    else:
        db.execute(text('UPDATE publish_executions SET status=:status, platform_post_id=:post,'
                        ' live_url=:url, attempt_count=:count, max_auto_retries=:retries,'
                        ' attempts=CAST(:attempts AS jsonb), last_error=:error, updated_at=now()'
                        ' WHERE idempotency_key=:key AND workspace_id=:ws'),
                   {'status': status, 'post': platform_post_id, 'url': live_url,
                    'count': attempt_count, 'retries': max_auto_retries,
                    'attempts': json.dumps(attempts), 'error': last_error,
                    'key': key, 'ws': workspace_id})
    stored = _load_execution_by_key(db, workspace_id, key)
    if stored is None:
        raise HTTPException(500, 'Publish execution was not stored')
    return stored


def _verify_execution_binding(receipt, slot, channel):
    """Integrity re-check at execution time: every condition must pass.

    Returns (ok, failing_condition, detail). Any failure means the slot
    is no longer Ready and the executor must never call the transport.
    """
    from launchcrew import calendar as calendar_mod
    from launchcrew import channel_variants as channel_mod
    from launchcrew import human_review
    if not isinstance(receipt, dict) or receipt.get('approval_state') != 'approved_for_export':
        return False, calendar_mod.PACK_NOT_APPROVED, 'Pack is not approved'
    try:
        current = human_review.current_revision(receipt)
    except Exception:
        return False, calendar_mod.PACK_NOT_APPROVED, 'Pack revision is unavailable'
    approved_revision = receipt.get('approved_revision')
    if not isinstance(approved_revision, int) or approved_revision != current:
        return False, 'revision_changed_since_approval', (
            'Pack changed since approval; the slot needs re-approval')
    bound, binding_reason = human_review.binding_status(receipt)
    if not bound:
        return False, 'approval_binding_mismatch', binding_reason or (
            'Approval binding mismatch; facts, copy, policy, voice, photo,'
            ' or check changed since approval')
    format_reason = human_review.format_block_reason(receipt)
    if format_reason is not None:
        return False, calendar_mod.FORMAT_CHECK_FAILED, format_reason
    _, current_ok, status_reason = channel_mod.channel_approval_status(receipt, channel)
    if not current_ok:
        return False, calendar_mod.UNAPPROVED_CHANNEL_VARIANTS, status_reason or (
            'Unapproved channel variants: ' + channel)
    return True, None, ''


def _execute_slot_channel(db, slot, channel, workspace_id, actor, simulate_failure=None,
                          manual_retry=False):
    """Execute one slot channel under the full Ready gate.

    Returns a dict with status (posted, failed, skipped_needs_approval,
    paused_by_kill_switch, already_posted), the stored execution row,
    and a plain-language reason. Never calls the platform transport
    unless the slot is marked Ready and every binding check passes.
    Automatic execution allows 1 initial attempt plus the bounded auto
    retries; an explicit owner retry allows exactly one extra attempt
    beyond the exhausted trail, appended with its own attempt number.
    """
    from launchcrew import channel_variants as channel_mod
    from launchcrew import human_review
    from launchcrew import publish_executor as executor_mod
    key = executor_mod.normalize_channel(channel)
    receipt = _receipt_for_slot(db, slot, workspace_id)
    try:
        binding = human_review.approval_binding(receipt) if isinstance(receipt, dict) else None
        digest = binding.get('digest') if isinstance(binding, dict) else None
    except Exception:
        digest = None
    idem_key = executor_mod.idempotency_key(slot['id'], key, digest)
    kill = _publish_kill_switch(db, workspace_id)
    if kill['paused']:
        stored = _save_execution(db, workspace_id, slot['id'], key, idem_key,
                                 'paused_by_kill_switch',
                                 last_error='Execution is paused by the owner kill switch.')
        store.audit(db, slot.get('run_id'), 'publish_paused_by_kill_switch', actor, workspace_id)
        return {'status': 'paused_by_kill_switch', 'execution': _public_execution(stored),
                'reason': 'Execution is paused by the owner kill switch.'}
    if slot.get('schedule_state') != 'ready':
        stored = _save_execution(db, workspace_id, slot['id'], key, idem_key,
                                 'skipped_needs_approval',
                                 last_error='Slot is not Ready; it needs approval before publishing.')
        return {'status': 'skipped_needs_approval', 'execution': _public_execution(stored),
                'reason': 'Slot is not Ready; it needs approval before publishing.'}
    ok, condition, detail = _verify_execution_binding(receipt, slot, key)
    if not ok:
        db.execute(text("UPDATE calendar_slots SET schedule_state='needs_approval', updated_at=now()"
                        " WHERE id=:id AND workspace_id=:ws AND schedule_state='ready'"),
                   {'id': slot['id'], 'ws': workspace_id})
        stored = _save_execution(db, workspace_id, slot['id'], key, idem_key,
                                 'skipped_needs_approval', last_error=detail)
        store.audit(db, slot.get('run_id'), 'publish_skipped_needs_approval', actor, workspace_id)
        return {'status': 'skipped_needs_approval', 'execution': _public_execution(stored),
                'reason': detail, 'failing_condition': condition}
    existing = _load_execution_by_key(db, workspace_id, idem_key)
    if (existing is not None and existing.get('status') == 'posted'
            and existing.get('platform_post_id')):
        return {'status': 'already_posted', 'execution': _public_execution(existing),
                'reason': 'Already posted; the existing result is returned with no re-post.'}
    try:
        bundle = channel_mod.checked_channel_variants(receipt)
    except ValueError as error:
        detail = str(error) or 'Approved variant text is unavailable'
        db.execute(text("UPDATE calendar_slots SET schedule_state='needs_approval', updated_at=now()"
                        " WHERE id=:id AND workspace_id=:ws AND schedule_state='ready'"),
                   {'id': slot['id'], 'ws': workspace_id})
        stored = _save_execution(db, workspace_id, slot['id'], key, idem_key,
                                 'skipped_needs_approval', last_error=detail)
        return {'status': 'skipped_needs_approval', 'execution': _public_execution(stored),
                'reason': detail, 'failing_condition': 'unapproved_channel_variants'}
    entry = bundle.get(key) if isinstance(bundle, dict) else None
    variant_text = entry.get('text') if isinstance(entry, dict) else ''
    subject = entry.get('subject') if isinstance(entry, dict) else None
    connection = db.execute(text('SELECT status, encrypted_token FROM social_connections'
                                 ' WHERE workspace_id=:ws AND platform=:platform'),
                            {'ws': workspace_id, 'platform': key}).mappings().first()
    connection = dict(connection) if connection is not None else None
    attempts: list[dict[str, Any]] = []
    stored_existing = _load_execution_by_key(db, workspace_id, idem_key)
    if stored_existing is not None and isinstance(stored_existing.get('attempts'), list):
        attempts = list(stored_existing['attempts'])
    last_error = None
    total_allowed = 1 + executor_mod.MAX_AUTO_RETRIES
    manual_added = False
    while len(attempts) < total_allowed or (manual_retry and not manual_added):
        if len(attempts) >= total_allowed:
            manual_added = True
        attempt = executor_mod.build_attempt(len(attempts) + 1, key, idem_key, 'attempted')
        try:
            result = executor_mod.default_transport(key, variant_text, subject, connection,
                                                    idem_key, simulate_failure=simulate_failure)
        except executor_mod.PublishTransportError as error:
            last_error = error.reason
            attempt = dict(attempt)
            attempt['outcome'] = 'failed'
            attempt['failure_reason'] = error.reason
            attempts = executor_mod.append_attempt(attempts, attempt)
            stored = _save_execution(db, workspace_id, slot['id'], key, idem_key, 'failed',
                                     attempt_count=len(attempts),
                                     max_auto_retries=executor_mod.MAX_AUTO_RETRIES,
                                     attempts=attempts, last_error=last_error)
            delivery = _load_or_init_delivery(db, slot, workspace_id, key)
            _save_delivery_attempt(db, delivery, workspace_id, 'failed',
                                   live_url=delivery.get('live_url'), reason=last_error,
                                   live_text_excerpt='')
            if executor_mod.attempts_exhausted(len(attempts)):
                break
            continue
        platform_post_id = result.get('platform_post_id')
        live_url = result.get('live_url')
        attempt = dict(attempt)
        attempt['outcome'] = 'posted'
        attempt['platform_post_id'] = platform_post_id
        attempt['live_url'] = live_url
        attempts = executor_mod.append_attempt(attempts, attempt)
        stored = _save_execution(db, workspace_id, slot['id'], key, idem_key, 'posted',
                                 platform_post_id=platform_post_id, live_url=live_url,
                                 attempt_count=len(attempts),
                                 max_auto_retries=executor_mod.MAX_AUTO_RETRIES,
                                 attempts=attempts, last_error=None)
        delivery = _load_or_init_delivery(db, slot, workspace_id, key)
        _save_delivery_attempt(db, delivery, workspace_id, 'posted', live_url=live_url,
                               live_text_excerpt='')
        if slot.get('run_id'):
            _advance_calendar_slots(db, slot['run_id'], workspace_id, 'exported')
        store.audit(db, slot.get('run_id'), 'publish_posted', actor, workspace_id)
        return {'status': 'posted', 'execution': _public_execution(stored),
                'reason': 'Posted at ' + (live_url or '') + '; handed off to verification.'}
    store.audit(db, slot.get('run_id'), 'publish_failed', actor, workspace_id)
    final = _load_execution_by_key(db, workspace_id, idem_key)
    return {'status': 'failed',
            'execution': _public_execution(final) if final is not None else None,
            'reason': last_error or 'Publish failed after bounded retries.'}


def _execute_ready_slot(db, slot_id, workspace_id, actor, simulate_failure=None):
    """Execute every selected channel of one Ready slot; refuse others."""
    slot = _load_slot(db, slot_id, workspace_id)
    if slot.get('schedule_state') != 'ready':
        raise HTTPException(409, 'Slot is not Ready; it needs approval before publishing.')
    channels = list(slot.get('selected_channels') or [])
    if not channels:
        raise HTTPException(422, 'Slot names no channels; select channels before execution.')
    executions: list[dict[str, Any]] = []
    failing: str | None = None
    reason: str | None = None
    paused = False
    posted_any = False
    for channel in channels:
        outcome = _execute_slot_channel(db, dict(slot), channel, workspace_id, actor,
                                        simulate_failure=simulate_failure)
        if outcome.get('execution') is not None:
            executions.append(outcome['execution'])
        status = outcome.get('status')
        if status == 'posted' or status == 'already_posted':
            posted_any = True
        elif status == 'paused_by_kill_switch':
            paused = True
            reason = outcome.get('reason')
        elif status in ('skipped_needs_approval', 'failed'):
            failing = outcome.get('failing_condition') or status
            reason = outcome.get('reason')
    refreshed = _load_slot(db, slot_id, workspace_id)
    if any(entry.get('status') == 'skipped_needs_approval' for entry in executions):
        skipped = True
    else:
        skipped = refreshed.get('schedule_state') != 'ready' and not posted_any and not paused
    return {'slot_id': slot_id, 'executed': posted_any, 'skipped': skipped,
            'paused': paused and not posted_any, 'failing_condition': failing,
            'reason': reason, 'executions': executions}


@app.get('/api/publish/status', response_model=PublishStatusOut)
def publish_status(as_of: str | None = None, actor: str = Depends(auth.actor)):
    """Executor status: kill switch, due and ready slots, recent executions."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        moment = _parse_execute_as_of(as_of)
        rows = db.execute(text('SELECT ' + _CALENDAR_PUBLIC_SELECT + ' FROM calendar_slots'
                               ' WHERE workspace_id=:ws ORDER BY slot_date, slot_type, id'),
                          {'ws': workspace_id}).mappings().all()
        due: list[dict[str, Any]] = []
        ready: list[dict[str, Any]] = []
        for raw in rows:
            slot = _public_calendar_slot(dict(raw))
            if slot.get('schedule_state') != 'ready':
                continue
            entry = {'slot_id': slot['id'], 'slot_date': slot['slot_date'],
                     'planned_time': slot.get('planned_time') or '09:00',
                     'channels': list(slot.get('selected_channels') or [])}
            ready.append(entry)
            if _slot_is_due(dict(raw), moment):
                due.append(entry)
        recent = db.execute(text('SELECT ' + _EXECUTION_PUBLIC_SELECT + ' FROM publish_executions'
                                  ' WHERE workspace_id=:ws ORDER BY updated_at DESC, id DESC LIMIT 50'),
                             {'ws': workspace_id}).mappings().all()
        return {'kill_switch': _publish_kill_switch(db, workspace_id),
                'due_slots': due, 'ready_slots': ready,
                'executions': [_public_execution(dict(entry)) for entry in recent]}


@app.post('/api/publish/kill-switch', response_model=KillSwitchOut)
def set_publish_kill_switch(body: KillSwitchIn, actor: str = Depends(auth.actor)):
    """Pause or resume all autonomous execution without touching slots or packs."""
    reason = (body.reason or '').strip() or None
    if reason is not None:
        for char in reason:
            code = ord(char)
            if code < 32 or code == 127:
                raise HTTPException(422, 'reason contains unsafe control characters')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        db.execute(text('INSERT INTO publish_executor_settings(workspace_id, kill_switch_paused,'
                        ' updated_at, updated_by, reason)'
                        ' VALUES (:ws, :paused, now(), :actor, :reason)'
                        ' ON CONFLICT (workspace_id) DO UPDATE SET'
                        ' kill_switch_paused=EXCLUDED.kill_switch_paused,'
                        ' updated_at=now(), updated_by=EXCLUDED.updated_by,'
                        ' reason=EXCLUDED.reason'),
                   {'ws': workspace_id, 'paused': bool(body.paused),
                    'actor': actor, 'reason': reason})
        store.audit(db, None, 'publish_kill_switch_paused' if body.paused else 'publish_kill_switch_resumed',
                    actor, workspace_id)
        return _publish_kill_switch(db, workspace_id)


@app.post('/api/publish/execute-due', response_model=ExecuteDueOut)
def execute_due_slots(body: ExecuteDueIn | None = None, actor: str = Depends(auth.actor)):
    """Autonomous scheduler tick: publish every due Ready slot, no per-post tap."""
    payload = body or ExecuteDueIn()
    simulate = payload.simulate_failure
    if simulate is not None and not isinstance(simulate, str):
        raise HTTPException(422, 'simulate_failure must be a string')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        moment = _parse_execute_as_of(payload.as_of)
        kill = _publish_kill_switch(db, workspace_id)
        rows = db.execute(text('SELECT ' + _CALENDAR_PUBLIC_SELECT + ' FROM calendar_slots'
                               ' WHERE workspace_id=:ws AND schedule_state=:state'
                               ' ORDER BY slot_date, slot_type, id'),
                          {'ws': workspace_id, 'state': 'ready'}).mappings().all()
        results: list[dict[str, Any]] = []
        executed: list[str] = []
        skipped: list[dict[str, Any]] = []
        for raw in rows:
            slot = dict(raw)
            if not _slot_is_due(slot, moment):
                continue
            outcome = _execute_ready_slot(db, slot['id'], workspace_id, actor,
                                          simulate_failure=simulate)
            results.append(outcome)
            if outcome['executed']:
                executed.append(slot['id'])
            else:
                skipped.append({'slot_id': slot['id'],
                                'failing_condition': outcome.get('failing_condition'),
                                'reason': outcome.get('reason')})
        return {'as_of': moment.isoformat(), 'paused': bool(kill['paused']),
                'executed_slots': executed, 'skipped_slots': skipped, 'results': results}


@app.post('/api/publish/slots/{slot_id}/execute', response_model=SlotExecuteResultOut)
def execute_publish_slot(slot_id: str, body: SlotExecuteIn | None = None,
                         actor: str = Depends(auth.actor)):
    """Execute one Ready slot under the exact Ready gate and retry rules."""
    payload = body or SlotExecuteIn()
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        try:
            outcome = _execute_ready_slot(db, slot_id, workspace_id, actor,
                                          simulate_failure=payload.simulate_failure)
        except HTTPException:
            raise
        return outcome


@app.post('/api/publish/slots/{slot_id}/retry', response_model=SlotExecuteResultOut)
def retry_publish_slot(slot_id: str, body: SlotExecuteIn | None = None,
                       actor: str = Depends(auth.actor)):
    """Owner-triggered manual retry after automatic retries are exhausted."""
    from launchcrew import publish_executor as executor_mod
    payload = body or SlotExecuteIn()
    from launchcrew import human_review
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        kill = _publish_kill_switch(db, workspace_id)
        if kill['paused']:
            raise HTTPException(409, 'Execution is paused by the owner kill switch.')
        slot = _load_slot(db, slot_id, workspace_id)
        channels = list(slot.get('selected_channels') or [])
        if not channels:
            raise HTTPException(422, 'Slot names no channels; select channels before retry.')
        retryable: list[str] = []
        for channel in channels:
            receipt = _receipt_for_slot(db, slot, workspace_id)
            try:
                binding = human_review.approval_binding(receipt) if isinstance(receipt, dict) else None
                digest = binding.get('digest') if isinstance(binding, dict) else None
            except Exception:
                digest = None
            key = executor_mod.idempotency_key(slot['id'], channel, digest)
            existing = _load_execution_by_key(db, workspace_id, key)
            if existing is not None and existing.get('status') == 'posted':
                continue
            retryable.append(channel)
        if not retryable:
            raise HTTPException(409, 'Nothing to retry; every channel already posted.')
        if slot.get('schedule_state') != 'ready':
            raise HTTPException(409, 'Slot is not Ready; it needs approval before retry.')
        executions: list[dict[str, Any]] = []
        failing: str | None = None
        reason: str | None = None
        posted_any = False
        for channel in retryable:
            outcome = _execute_slot_channel(db, dict(slot), channel, workspace_id, actor,
                                            simulate_failure=payload.simulate_failure,
                                            manual_retry=True)
            if outcome.get('execution') is not None:
                executions.append(outcome['execution'])
            if outcome.get('status') in ('posted', 'already_posted'):
                posted_any = True
            else:
                failing = outcome.get('failing_condition') or outcome.get('status')
                reason = outcome.get('reason')
        return {'slot_id': slot_id, 'executed': posted_any,
                'skipped': not posted_any, 'paused': False,
                'failing_condition': failing, 'reason': reason,
                'executions': executions}


# SC4 media library: upload once, format facts, Checker validation, and
# non-destructive channel-ready derivatives. One uploaded asset is reused
# across channels without re-upload; crops are stored alongside the
# original and the original is never overwritten.

class MediaAssetIn(Strict):
    filename: str = Field(max_length=200)
    mime_type: str | None = Field(default=None, max_length=200)
    width: int | None = Field(default=None, ge=1, le=16384)
    height: int | None = Field(default=None, ge=1, le=16384)
    duration_seconds: float | None = Field(default=None, ge=0)
    data_b64: str | None = Field(default=None, max_length=20000000)


class MediaAssetOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = ''
    filename: str = ''
    media_type: str = 'image'
    mime_type: str | None = None
    width: int = 0
    height: int = 0
    aspect_ratio: str = ''
    duration_seconds: float | None = None
    sha256_digest: str = ''
    derivatives: dict[str, Any] = Field(default_factory=dict)
    focal_point: dict[str, Any] | None = None
    format_facts: dict[str, Any] = Field(default_factory=dict)
    created_at: Any | None = None


class MediaDerivativeIn(Strict):
    derivative_key: str = Field(min_length=1, max_length=16)


class MediaFocalIn(Strict):
    focal_x: float | None = Field(default=None)
    focal_y: float | None = Field(default=None)
    derivative_key: str | None = Field(default=None, min_length=1, max_length=16)


class SlotMediaAttachIn(Strict):
    asset_id: str = Field(min_length=1, max_length=128)
    channels: list[str] | None = None
    use_original_without_derivative: bool = False


class SlotMediaAttachmentOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = ''
    slot_id: str | None = None
    asset_id: str = ''
    channels: list[str] = Field(default_factory=list)
    channel_derivatives: dict[str, Any] = Field(default_factory=dict)
    use_original_without_derivative: bool = False
    format_validation: dict[str, Any] = Field(default_factory=dict)
    asset: dict[str, Any] = Field(default_factory=dict)


class SlotMediaOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    slot_id: str = ''
    attached: list[SlotMediaAttachmentOut] = Field(default_factory=list)
    format_validation: dict[str, Any] = Field(default_factory=dict)


_MEDIA_PUBLIC_SELECT = ('id, workspace_id, filename, media_type, mime_type, width, height, '
                        'aspect_ratio, duration_seconds, sha256_digest, derivatives, focal_x, '
                        'focal_y, created_at')

_ATTACHMENT_PUBLIC_SELECT = ('id, workspace_id, asset_id, slot_id, run_id, channels, '
                             'channel_derivatives, use_original_without_derivative, '
                             'format_validation, created_at')


def _load_media_asset(db, asset_id, workspace_id):
    row = db.execute(text('SELECT ' + _MEDIA_PUBLIC_SELECT + ' FROM media_assets'
                          ' WHERE id=:id AND workspace_id=:ws'),
                     {'id': asset_id, 'ws': workspace_id}).mappings().first()
    if row is None:
        raise HTTPException(404, 'Media asset not found')
    return dict(row)


def _public_media_asset(row):
    from launchcrew import media_library as media_mod
    data = dict(row)
    created = data.get('created_at')
    if hasattr(created, 'isoformat'):
        data['created_at'] = created.isoformat()
    return media_mod.media_public_asset(data)


def _public_attachment(row, asset):
    data = dict(row)
    return {'id': data.get('id'), 'slot_id': data.get('slot_id'),
            'asset_id': data.get('asset_id'),
            'channels': list(data.get('channels') or []),
            'channel_derivatives': dict(data.get('channel_derivatives') or {}),
            'use_original_without_derivative': bool(data.get('use_original_without_derivative')),
            'format_validation': dict(data.get('format_validation') or {}),
            'asset': asset}


def _combined_slot_media_validation(attachments, slot_type):
    from launchcrew import media_library as media_mod
    reasons: list[str] = []
    checked: str | None = None
    for attachment in attachments:
        validation = attachment.get('format_validation')
        if not isinstance(validation, dict):
            continue
        if checked is None and isinstance(validation.get('checked_aspect_ratio'), str):
            checked = validation['checked_aspect_ratio']
        for reason in validation.get('reasons') or []:
            if isinstance(reason, str) and reason.strip() and reason not in reasons:
                reasons.append(reason)
    return {'passed': not reasons, 'reasons': reasons,
            'checked_aspect_ratio': checked,
            'required_aspect_ratio': media_mod.required_aspect_for_slot(slot_type)}


@app.post('/api/media/assets', response_model=MediaAssetOut, status_code=201)
def upload_media_asset(body: MediaAssetIn, actor: str = Depends(auth.actor)):
    """Upload one image or video once for reuse across channels.

    Parses dimensions and aspect from the payload header bytes (or the
    explicit width and height), records the format facts and the
    original digest, and generates the channel-ready crop derivatives
    alongside the original without touching it.
    """
    from launchcrew import media_library as media_mod
    try:
        validated = media_mod.validate_upload(body.filename, body.mime_type,
                                              body.width, body.height,
                                              body.duration_seconds, body.data_b64)
    except ValueError as error:
        raise HTTPException(422, str(error))
    data_b64 = body.data_b64.strip() if isinstance(body.data_b64, str) and body.data_b64.strip() else None
    asset_id = 'media_' + uuid4().hex
    stored = media_mod.build_asset(asset_id, validated, data_b64)
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        db.execute(text('INSERT INTO media_assets(id, workspace_id, filename, media_type, mime_type,'
                        ' width, height, aspect_ratio, duration_seconds, sha256_digest,'
                        ' original_data_b64, derivatives)'
                        ' VALUES (:id,:ws,:filename,:media_type,:mime,:width,:height,'
                        ':aspect,:duration,:digest,:data,CAST(:derivatives AS jsonb))'),
                   {'id': asset_id, 'ws': workspace_id, 'filename': stored['filename'],
                    'media_type': stored['media_type'], 'mime': stored['mime_type'],
                    'width': stored['width'], 'height': stored['height'],
                    'aspect': stored['aspect_ratio'], 'duration': stored['duration_seconds'],
                    'digest': stored['sha256_digest'], 'data': stored['original_data_b64'],
                    'derivatives': json.dumps(stored['derivatives'])})
        store.audit(db, None, 'media_asset_uploaded', actor, workspace_id)
        return _public_media_asset(_load_media_asset(db, asset_id, workspace_id))


@app.get('/api/media/assets', response_model=list[MediaAssetOut])
def list_media_assets(actor: str = Depends(auth.actor)):
    """List workspace media assets with format facts and derivatives."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        rows = db.execute(text('SELECT ' + _MEDIA_PUBLIC_SELECT + ' FROM media_assets'
                               ' WHERE workspace_id=:ws ORDER BY created_at, id'),
                          {'ws': workspace_id}).mappings().all()
        return [_public_media_asset(dict(row)) for row in rows]


@app.get('/api/media/assets/{asset_id}', response_model=MediaAssetOut)
def get_media_asset(asset_id: str, actor: str = Depends(auth.actor)):
    """Return one asset, proving the original facts sit intact beside derivatives."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return _public_media_asset(_load_media_asset(db, asset_id, workspace_id))


@app.post('/api/media/assets/{asset_id}/focal-point')
def set_media_focal_point(asset_id: str, body: MediaFocalIn,
                          actor: str = Depends(auth.actor)):
    """Set the owner focal point and recompute crops without touching the original."""
    from launchcrew import media_library as media_mod
    try:
        focal_x, focal_y = media_mod.normalize_focal_point(
            body.focal_x, body.focal_y)
    except ValueError as error:
        raise HTTPException(422, str(error))
    wanted = list(media_mod.DERIVATIVE_KEYS)
    if body.derivative_key is not None:
        key = body.derivative_key.strip()
        if media_mod._parse_aspect_key(key) is None or key not in media_mod.DERIVATIVE_KEYS:
            raise HTTPException(422, 'derivative_key must be one of 4:5, 1:1, 9:16, 16:9')
        wanted = [key]
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        stored = _load_media_asset(db, asset_id, workspace_id)
        before = (stored.get('width'), stored.get('height'),
                  stored.get('aspect_ratio'), stored.get('sha256_digest'))
        try:
            fresh = media_mod.build_focal_derivatives(
                stored['id'], stored['width'], stored['height'],
                stored['sha256_digest'], focal_x, focal_y, wanted)
        except ValueError as error:
            raise HTTPException(422, str(error))
        merged = dict(stored.get('derivatives')) if isinstance(stored.get('derivatives'), dict) else {}
        merged.update(fresh)
        db.execute(text('UPDATE media_assets SET focal_x=:fx, focal_y=:fy,'
                        ' derivatives=CAST(:derivatives AS jsonb)'
                        ' WHERE id=:id AND workspace_id=:ws'),
                   {'fx': focal_x, 'fy': focal_y,
                    'derivatives': json.dumps(merged),
                    'id': stored['id'], 'ws': workspace_id})
        stored = _load_media_asset(db, asset_id, workspace_id)
        after = (stored.get('width'), stored.get('height'),
                 stored.get('aspect_ratio'), stored.get('sha256_digest'))
        if before != after:
            raise HTTPException(500, 'Media original must never change when refocusing')
        recomputed = {key: stored['derivatives'][key] for key in wanted
                      if isinstance(stored.get('derivatives'), dict)
                      and isinstance(stored['derivatives'].get(key), dict)}
        return {'asset_id': stored['id'],
                'focal_point': {'x': focal_x, 'y': focal_y},
                'derivatives': recomputed}


@app.post('/api/media/assets/{asset_id}/derivatives')
def generate_media_derivative(asset_id: str, body: MediaDerivativeIn,
                              actor: str = Depends(auth.actor)):
    """Generate or retrieve one crop derivative without overwriting the original."""
    from launchcrew import media_library as media_mod
    key = (body.derivative_key or '').strip()
    if media_mod._parse_aspect_key(key) is None or key not in media_mod.DERIVATIVE_KEYS:
        raise HTTPException(422, 'derivative_key must be one of 4:5, 1:1, 9:16, 16:9')
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        stored = _load_media_asset(db, asset_id, workspace_id)
        before = (stored.get('width'), stored.get('height'),
                  stored.get('aspect_ratio'), stored.get('sha256_digest'))
        derivatives = stored.get('derivatives')
        record = derivatives.get(key) if isinstance(derivatives, dict) else None
        focal = media_mod.focal_point_for(stored)
        if (focal is not None
                and (not isinstance(record, dict)
                     or record.get('focal_point') != {'x': focal['x'],
                                                      'y': focal['y']})):
            fresh = media_mod.build_focal_derivatives(
                stored['id'], stored['width'], stored['height'],
                stored['sha256_digest'], focal['x'], focal['y'], [key])
            record = fresh.get(key)
            if not isinstance(record, dict):
                raise HTTPException(422, 'derivative_key must be one of 4:5, 1:1, 9:16, 16:9')
            merged = dict(derivatives) if isinstance(derivatives, dict) else {}
            merged[key] = record
            db.execute(text('UPDATE media_assets SET derivatives=CAST(:derivatives AS jsonb)'
                            ' WHERE id=:id AND workspace_id=:ws'),
                       {'derivatives': json.dumps(merged), 'id': stored['id'], 'ws': workspace_id})
            stored = _load_media_asset(db, asset_id, workspace_id)
        if not isinstance(record, dict):
            fresh = media_mod.build_derivatives(stored['id'], stored['width'],
                                                stored['height'], stored['sha256_digest'])
            record = fresh.get(key)
            if not isinstance(record, dict):
                raise HTTPException(422, 'derivative_key must be one of 4:5, 1:1, 9:16, 16:9')
            merged = dict(derivatives) if isinstance(derivatives, dict) else {}
            merged[key] = record
            db.execute(text('UPDATE media_assets SET derivatives=CAST(:derivatives AS jsonb)'
                            ' WHERE id=:id AND workspace_id=:ws'),
                       {'derivatives': json.dumps(merged), 'id': stored['id'], 'ws': workspace_id})
            stored = _load_media_asset(db, asset_id, workspace_id)
        after = (stored.get('width'), stored.get('height'),
                 stored.get('aspect_ratio'), stored.get('sha256_digest'))
        if before != after:
            raise HTTPException(500, 'Media original must never change when generating derivatives')
        return dict(record) if isinstance(record, dict) else record


@app.post('/api/calendar/slots/{slot_id}/media', response_model=SlotMediaAttachmentOut,
          status_code=201)
def attach_slot_media(slot_id: str, body: SlotMediaAttachIn,
                      actor: str = Depends(auth.actor)):
    """Attach one uploaded asset to a slot and channels without re-upload.

    Resolves each channel to its channel-ready derivative, runs the
    Checker media format and capability validation, records the
    attachment on the slot, and returns the per-channel mapping with
    the validation result.
    """
    from launchcrew import calendar as calendar_mod
    from launchcrew import media_library as media_mod
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        asset = _load_media_asset(db, body.asset_id.strip(), workspace_id)
        if body.channels is None:
            channels = list(slot.get('selected_channels') or [])
        else:
            try:
                channels = calendar_mod.normalize_channel_list(body.channels, 'channels')
            except ValueError as error:
                raise HTTPException(422, str(error))
        if not channels:
            raise HTTPException(422, 'channels must name at least one channel')
        use_original = bool(body.use_original_without_derivative)
        mapping = media_mod.resolve_channel_derivatives(asset, channels, use_original)
        validation = media_mod.validate_slot_media(asset, slot.get('slot_type'), channels,
                                                   mapping, use_original)
        attachment_id = 'matt_' + uuid4().hex
        db.execute(text('DELETE FROM media_attachments WHERE slot_id=:slot AND asset_id=:asset'
                        ' AND workspace_id=:ws'),
                   {'slot': slot['id'], 'asset': asset['id'], 'ws': workspace_id})
        db.execute(text('INSERT INTO media_attachments(id, workspace_id, asset_id, slot_id, run_id,'
                        ' channels, channel_derivatives, use_original_without_derivative,'
                        ' format_validation)'
                        ' VALUES (:id,:ws,:asset,:slot,:run,CAST(:channels AS jsonb),'
                        'CAST(:derivatives AS jsonb),:use_original,CAST(:validation AS jsonb))'),
                   {'id': attachment_id, 'ws': workspace_id, 'asset': asset['id'],
                    'slot': slot['id'], 'run': slot.get('run_id'),
                    'channels': json.dumps(channels), 'derivatives': json.dumps(mapping),
                    'use_original': use_original, 'validation': json.dumps(validation)})
        store.audit(db, slot.get('run_id'), 'slot_media_attached', actor, workspace_id)
        row = db.execute(text('SELECT ' + _ATTACHMENT_PUBLIC_SELECT + ' FROM media_attachments'
                              ' WHERE id=:id AND workspace_id=:ws'),
                         {'id': attachment_id, 'ws': workspace_id}).mappings().first()
        if row is None:
            raise HTTPException(500, 'Slot media was not stored')
        return _public_attachment(dict(row), _public_media_asset(asset))


@app.get('/api/calendar/slots/{slot_id}/media', response_model=SlotMediaOut)
def get_slot_media(slot_id: str, actor: str = Depends(auth.actor)):
    """Return attached media assets, per-channel derivatives, and format validation."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        slot = _load_slot(db, slot_id, workspace_id)
        rows = db.execute(text('SELECT ' + _ATTACHMENT_PUBLIC_SELECT + ' FROM media_attachments'
                               ' WHERE slot_id=:slot AND workspace_id=:ws ORDER BY created_at, id'),
                          {'slot': slot['id'], 'ws': workspace_id}).mappings().all()
        attached = []
        for row in rows:
            asset = _load_media_asset(db, dict(row)['asset_id'], workspace_id)
            attached.append(_public_attachment(dict(row), _public_media_asset(asset)))
        return {'slot_id': slot['id'], 'attached': attached,
                'format_validation': _combined_slot_media_validation(attached, slot.get('slot_type'))}


# SC5 viral format generator: metered credits failing closed at zero and
# owner media only. The owner uploads 3 to 10 screenshots or one screen
# recording plus the confirmed facts; each generation spends one visible
# credit and builds a carousel or short video pack that passes the
# Checker as a normal approval-bound pack. Every asset comes from the
# owner upload, never from a creator clip library.

class ViralCreditsOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    workspace_id: str = ''
    remaining_credits: int = 0
    total_used_credits: int = 0


class ViralCreditsSetIn(Strict):
    remaining_credits: StrictInt = Field(ge=0, le=1000000)


class ViralGenerateIn(Strict):
    media_mode: str | None = Field(default=None, max_length=32)
    screenshots: list[Any] | None = None
    screen_recording: Any | None = None
    asset_ids: list[str] | None = None
    confirmed_facts: str = Field(default='', max_length=10000)
    slot_id: str | None = Field(default=None, max_length=128)
    media_source: str | None = Field(default=None, max_length=64)


class ViralGenerationOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = ''
    workspace_id: str = ''
    output_format: str = ''
    media_mode: str = ''
    asset_ids: list[Any] = Field(default_factory=list)
    confirmed_facts: str = ''
    run_id: str | None = None
    slot_id: str | None = None
    credits_charged: int = 1
    remaining_credits_after: int = 0
    media_provenance: str = 'owner_upload_only'
    frames_or_scenes: list[Any] = Field(default_factory=list)
    checker_passed: bool = False
    approval_state: str = ''
    run_status: str = ''
    checker_decision: str = ''
    created_at: Any | None = None


_VIRAL_GENERATION_PUBLIC_SELECT = ('id, workspace_id, output_format, media_mode, asset_ids,'
                                   ' confirmed_facts, run_id, slot_id, credits_charged,'
                                   ' remaining_credits_after, media_provenance, frames_or_scenes,'
                                   ' checker_passed, approval_state, created_at')


def _ensure_viral_credits(db, workspace_id):
    from launchcrew import viral_generator as viral_mod
    db.execute(text('INSERT INTO viral_generation_credits(workspace_id, remaining_credits,'
                    ' total_used_credits) VALUES (:ws, :remaining, 0) ON CONFLICT DO NOTHING'),
               {'ws': workspace_id, 'remaining': viral_mod.DEFAULT_CREDITS})
    row = db.execute(text('SELECT workspace_id, remaining_credits, total_used_credits'
                          ' FROM viral_generation_credits WHERE workspace_id=:ws'),
                     {'ws': workspace_id}).mappings().first()
    if row is None:
        raise HTTPException(500, 'Viral generation credits were not stored')
    return dict(row)


def _public_viral_credits(row, workspace_id):
    return {'workspace_id': workspace_id,
            'remaining_credits': row.get('remaining_credits', 0),
            'total_used_credits': row.get('total_used_credits', 0)}


def _public_viral_generation(row):
    from launchcrew import viral_generator as viral_mod
    data = viral_mod.public_generation(dict(row))
    created = data.get('created_at')
    if hasattr(created, 'isoformat'):
        data['created_at'] = created.isoformat()
    return data


def _viral_inline_label(item, position, kind):
    if isinstance(item, dict):
        for key in ('filename', 'id', 'asset_id', 'label'):
            raw = item.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    if isinstance(item, str) and item.strip():
        return item.strip()
    return 'owner_%s_%d' % (kind, position)


@app.get('/api/viral-generator/credits', response_model=ViralCreditsOut)
def get_viral_credits(actor: str = Depends(auth.actor)):
    """Return the visible viral generation credit balance for the workspace."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        return _public_viral_credits(_ensure_viral_credits(db, workspace_id), workspace_id)


@app.post('/api/viral-generator/credits', response_model=ViralCreditsOut)
@app.put('/api/viral-generator/credits', response_model=ViralCreditsOut)
def set_viral_credits(body: ViralCreditsSetIn, actor: str = Depends(auth.actor)):
    """Set the workspace viral generation credit balance for owner and tests."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        _ensure_viral_credits(db, workspace_id)
        db.execute(text('UPDATE viral_generation_credits SET remaining_credits=:remaining,'
                        ' updated_at=now() WHERE workspace_id=:ws'),
                   {'remaining': body.remaining_credits, 'ws': workspace_id})
        store.audit(db, None, 'viral_credits_set', actor, workspace_id)
        row = db.execute(text('SELECT workspace_id, remaining_credits, total_used_credits'
                              ' FROM viral_generation_credits WHERE workspace_id=:ws'),
                         {'ws': workspace_id}).mappings().first()
        return _public_viral_credits(dict(row), workspace_id)


@app.post('/api/viral-generator/generate', response_model=ViralGenerationOut,
          status_code=201)
def generate_viral_pack(body: ViralGenerateIn, actor: str = Depends(auth.actor)):
    """Build one metered viral pack from owner media and confirmed facts.

    The credit gate runs before any pipeline or provider call: a zero
    balance refuses with 402 and never invokes the pipeline. Owner media
    only: foreign or library assets refuse with 422, as do wrong media
    counts and empty confirmed facts. One credit is charged only after
    the Checker pipeline produces the approval-bound pack.
    """
    from types import SimpleNamespace
    from launchcrew import viral_generator as viral_mod
    from backend import model_admission
    try:
        facts_text = viral_mod.normalize_confirmed_facts(body.confirmed_facts)
    except ValueError as error:
        raise HTTPException(422, str(error))
    screenshots = list(body.screenshots or [])
    recording = body.screen_recording
    has_recording = not (recording is None or (isinstance(recording, str)
                                               and not recording.strip()))
    try:
        mode = viral_mod.normalize_media_mode(
            body.media_mode, bool(screenshots or body.asset_ids), has_recording)
    except ValueError as error:
        raise HTTPException(422, str(error))
    try:
        viral_mod.validate_owner_media_source(body.media_source)
        for item in screenshots:
            viral_mod.validate_owner_item(item)
        if has_recording:
            viral_mod.validate_owner_item(recording)
    except ValueError as error:
        raise HTTPException(422, str(error))
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        assets = []
        for asset_id in (body.asset_ids or []):
            if not isinstance(asset_id, str) or not asset_id.strip():
                raise HTTPException(422, viral_mod.OWNER_MEDIA_ONLY_MESSAGE)
            try:
                viral_mod.validate_owner_item(asset_id.strip())
            except ValueError as error:
                raise HTTPException(422, str(error))
            stored = db.execute(text('SELECT ' + _MEDIA_PUBLIC_SELECT + ' FROM media_assets'
                                     ' WHERE id=:id AND workspace_id=:ws'),
                                {'id': asset_id.strip(), 'ws': workspace_id}).mappings().first()
            if stored is None:
                raise HTTPException(422, viral_mod.OWNER_MEDIA_ONLY_MESSAGE)
            assets.append(dict(stored))
        images = [entry for entry in assets if entry.get('media_type') == 'image']
        videos = [entry for entry in assets if entry.get('media_type') == 'video']
        slot_id = None
        if body.slot_id is not None and str(body.slot_id).strip():
            slot = _load_slot(db, str(body.slot_id).strip(), workspace_id)
            slot_id = slot['id']
        credits = _ensure_viral_credits(db, workspace_id)
        if viral_mod.credits_exhausted(credits.get('remaining_credits')):
            raise HTTPException(402, viral_mod.CREDITS_EXHAUSTED_MESSAGE)
        legacy, scout, maker, checker = load_stage_profiles(
            db, SimpleNamespace(agent_name='Maker', maker_name=None,
                                scout_name=None, checker_name=None), workspace_id)
    screenshot_count = len(screenshots) + len(images)
    recording_count = (1 if has_recording else 0) + len(videos)
    try:
        viral_mod.validate_counts(mode, screenshot_count, recording_count)
    except ValueError as error:
        raise HTTPException(422, str(error))
    output_format = viral_mod.output_format_for(mode)
    if mode == 'screenshots':
        labels = ([_viral_inline_label(item, index + 1, 'screenshot')
                   for index, item in enumerate(screenshots)]
                  + [entry['id'] for entry in images])
        frames_or_scenes = viral_mod.build_carousel_frames(labels, facts_text)
    else:
        if has_recording:
            label = _viral_inline_label(recording, 1, 'recording')
        else:
            label = videos[0]['id']
        frames_or_scenes = viral_mod.build_short_video_scenes(label, facts_text)
    format_raw = viral_mod.format_spec_for(mode, frames_or_scenes)
    product_facts = viral_mod.product_facts_for(facts_text)
    idea = viral_mod.idea_for(mode, facts_text)
    run_id = 'run_' + uuid4().hex
    generation_id = viral_mod.generation_id()
    factory = model_admission.admission_factory_for_run(store.engine(), run_id)
    try:
        receipt = adapter.execute(
            run_id, idea, legacy, False, memory_items=[], checker_profile='standard',
            scout_profile=scout, maker_profile=maker, checker_agent=checker,
            product_facts=product_facts, model_admission_factory=factory,
            waive_missing_core_facts=True, fact_library=None, format_spec=format_raw)
    except ValueError as error:
        raise HTTPException(422, str(error))
    check_v2 = receipt.get('checker_v2') if isinstance(receipt.get('checker_v2'), dict) else {}
    format_check = receipt.get('format_check') if isinstance(receipt.get('format_check'), dict) else {}
    blocked = check_v2.get('blocked_count', 1)
    checker_passed = bool(receipt.get('status') == 'completed' and blocked == 0
                          and format_check.get('passed', True) is True)
    stored_assets: list[Any] = [entry['id'] for entry in assets]
    stored_assets.extend(screenshots)
    if has_recording:
        stored_assets.append(recording)
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        locked = db.execute(text('SELECT remaining_credits, total_used_credits'
                                 ' FROM viral_generation_credits WHERE workspace_id=:ws'
                                 ' FOR UPDATE'),
                            {'ws': workspace_id}).mappings().first()
        if locked is None:
            locked = _ensure_viral_credits(db, workspace_id)
        else:
            locked = dict(locked)
        if viral_mod.credits_exhausted(locked.get('remaining_credits')):
            raise HTTPException(402, viral_mod.CREDITS_EXHAUSTED_MESSAGE)
        remaining_after = int(locked.get('remaining_credits', 0)) - viral_mod.CREDITS_PER_GENERATION
        if remaining_after < 0:
            raise HTTPException(402, viral_mod.CREDITS_EXHAUSTED_MESSAGE)
        save_run(db, receipt, 'Maker', actor, workspace_id)
        db.execute(text('UPDATE viral_generation_credits SET remaining_credits=:remaining,'
                        ' total_used_credits=total_used_credits+:charged, updated_at=now()'
                        ' WHERE workspace_id=:ws'),
                   {'remaining': remaining_after,
                    'charged': viral_mod.CREDITS_PER_GENERATION, 'ws': workspace_id})
        db.execute(text('INSERT INTO viral_generations(id, workspace_id, output_format, media_mode,'
                        ' asset_ids, confirmed_facts, run_id, slot_id, credits_charged,'
                        ' remaining_credits_after, media_provenance, frames_or_scenes,'
                        ' checker_passed, approval_state)'
                        ' VALUES (:id,:ws,:output_format,:media_mode,CAST(:asset_ids AS jsonb),'
                        ':facts,:run,:slot,:charged,:remaining,:provenance,'
                        'CAST(:frames AS jsonb),:passed,:approval)'),
                   {'id': generation_id, 'ws': workspace_id, 'output_format': output_format,
                    'media_mode': mode, 'asset_ids': json.dumps(stored_assets),
                    'facts': facts_text, 'run': run_id, 'slot': slot_id,
                    'charged': viral_mod.CREDITS_PER_GENERATION, 'remaining': remaining_after,
                    'provenance': viral_mod.MEDIA_PROVENANCE,
                    'frames': json.dumps(frames_or_scenes),
                    'passed': checker_passed,
                    'approval': receipt.get('approval_state', 'awaiting_human_approval')})
        store.audit(db, run_id, 'viral_generation_created', actor, workspace_id)
        row = db.execute(text('SELECT ' + _VIRAL_GENERATION_PUBLIC_SELECT
                              + ' FROM viral_generations WHERE id=:id AND workspace_id=:ws'),
                         {'id': generation_id, 'ws': workspace_id}).mappings().first()
        if row is None:
            raise HTTPException(500, 'Viral generation was not stored')
        public = _public_viral_generation(dict(row))
        public['run_status'] = receipt.get('status', '')
        public['checker_decision'] = 'pass' if blocked == 0 else 'fail'
        return public


class MediaCreativeIn(Strict):
    output_format: str | None = Field(default=None, max_length=32)
    confirmed_facts: str = Field(default='', max_length=10000)
    expected_revision: Any | None = None


class MediaCreativeOut(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = ''
    run_id: str = ''
    output_format: str = ''
    media_provenance: str = 'model_draft_unverified'
    pack: dict[str, Any] = Field(default_factory=dict)
    model_used: str = 'none'
    remaining_budget_micros: int = 0
    revision: int = 0


@app.post('/api/runs/{run_id}/media-creative', response_model=MediaCreativeOut,
          status_code=201)
def generate_media_creative(run_id: str, body: MediaCreativeIn,
                            actor: str = Depends(auth.actor)):
    """Draft one AI media creative pack for owner-shot media.

    The pack (scene scripts, hooks, voiceover lines, captions, shot
    guidance) is drafted by a single bounded model call and stored as
    draft provenance on the receipt. No pixels or audio are synthesized.
    Refusals: 422 for bad format or facts, 404 for a missing run, 409
    for a stale revision, 503 when the model key is not configured,
    402 when the model budget is zero. A failed or unparsable model
    call refuses with 422 and stores nothing.
    """
    import os
    from launchcrew import media_creative as creative_mod
    from launchcrew import human_review
    from backend import model_admission
    try:
        output_format = creative_mod.normalize_format(body.output_format)
        facts_text = creative_mod.normalize_facts(body.confirmed_facts)
    except ValueError as error:
        raise HTTPException(422, str(error))
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        receipt = get_receipt(db, run_id, workspace_id)
        if receipt is None:
            raise HTTPException(404, 'Run not found')
        _reject_when_running(receipt)
        ok, _ = human_review.valid_revision_context(receipt)
        if not ok:
            raise HTTPException(422, 'Media creative needs a reviewable revision')
        if body.expected_revision != human_review.current_revision(receipt):
            raise HTTPException(409, 'Media creative is stale; the draft changed')
        if not os.environ.get('META_API_KEY', '').strip():
            raise HTTPException(503, creative_mod.MODEL_NOT_CONFIGURED_MESSAGE)
        generation_id = 'mc_' + uuid4().hex
        factory = model_admission.admission_factory_for_run(
            store.engine(), run_id)
        try:
            admission = factory('MediaCreative', generation_id)
        except Exception:
            raise HTTPException(402, creative_mod.BUDGET_EXHAUSTED_MESSAGE)
        from launchcrew.spark import call_spark_strict_json
        try:
            result = call_spark_strict_json(
                creative_mod.system_prompt_for(output_format),
                creative_mod.user_prompt_for(output_format, facts_text),
                creative_mod.schema_hint_for(output_format),
                admission=admission)
        except Exception:
            raise HTTPException(422, creative_mod.MODEL_CALL_FAILED_MESSAGE)
        if not isinstance(result, dict) or result.get('mode') != 'spark':
            remaining = model_admission.budget_remaining_micros(store.engine())
            if not result.get('attempted') and remaining <= 0:
                raise HTTPException(402, creative_mod.BUDGET_EXHAUSTED_MESSAGE)
            raise HTTPException(422, creative_mod.MODEL_CALL_FAILED_MESSAGE)
        try:
            pack = creative_mod.parse_pack(result.get('raw_json'),
                                           output_format)
        except ValueError:
            raise HTTPException(422, creative_mod.MODEL_CALL_FAILED_MESSAGE)
        usage = result.get('usage') if isinstance(result.get('usage'), dict) else {}
        new_revision = int(receipt.get('revision', 0)) + 1
        entry = {'revision': new_revision,
                 'media_creative_event': 'media_creative_generated',
                 'media_creative_id': generation_id,
                 'output_format': output_format,
                 'actor': actor}
        history = list(receipt.get('revision_history', [])) + [entry]
        model_usage = dict(receipt.get('model_usage', {}))
        model_usage['spark_calls'] = int(model_usage.get('spark_calls', 0)) + 1
        for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            value = usage.get(name)
            if type(value) is int and value >= 0:
                model_usage[name] = int(model_usage.get(name, 0)) + value
        receipt['revision'] = new_revision
        receipt['revision_history'] = history
        receipt['model_usage'] = model_usage
        receipt['approval_state'] = 'pending_approval'
        receipt['approvals'] = []
        receipt['media_creative'] = {
            'id': generation_id,
            'output_format': output_format,
            'media_provenance': creative_mod.PROVENANCE,
            'pack': pack,
            'model_used': result.get('model_used', 'none'),
            'revision': new_revision,
        }
        updated = db.execute(
            text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state'
                 ' WHERE id=:id AND workspace_id=:ws'),
            {'receipt': json.dumps(receipt),
             'state': receipt['approval_state'], 'id': run_id,
             'ws': workspace_id})
        if updated.rowcount == 0:
            raise HTTPException(404, 'Run not found')
        db.execute(text('DELETE FROM approvals WHERE run_id=:id'),
                   {'id': run_id})
        store.audit(db, run_id, 'media_creative_generated', actor, workspace_id)
        remaining = model_admission.budget_remaining_micros(store.engine())
        return {'id': generation_id, 'run_id': run_id,
                'output_format': output_format,
                'media_provenance': creative_mod.PROVENANCE,
                'pack': pack,
                'model_used': result.get('model_used', 'none'),
                'remaining_budget_micros': remaining,
                'revision': new_revision}


# SC6 agent surfaces: workspace keys, agent REST API, hosted MCP server, skill.
# One backend backs four surfaces. The Web UI, REST API, hosted MCP
# server, and CLI resolve the same workspace_id (from the workspace key
# or the owner session) so they read and write the exact same state.


class AgentKeyCreateIn(Strict):
    label: str = Field(default='', max_length=120)
    scopes: list[str] | None = None
    role: str = Field(default='owner', min_length=1, max_length=16)


class AgentValidateIn(BaseModel):
    model_config = ConfigDict(extra='allow')
    slot_id: str | None = None
    slot_ids: list[str] | None = None
    schedule: dict[str, Any] | None = None


class AgentApplyIn(BaseModel):
    model_config = ConfigDict(extra='allow')
    schema_version: str | None = None
    ready_slots: list[Any] | None = None
    excluded_slots: list[Any] | None = None


class McpCallIn(BaseModel):
    model_config = ConfigDict(extra='allow')
    name: str = ''
    arguments: dict[str, Any] = Field(default_factory=dict)


def _raw_workspace_key(request: Request) -> str | None:
    header = request.headers.get('authorization', '')
    if header.lower().startswith('bearer '):
        token = header[7:].strip()
        if token:
            return token
    fallback = (request.headers.get('x-workspace-key') or '').strip()
    return fallback or None


def _agent_session_actor(request: Request) -> str | None:
    if not auth.enabled():
        return 'demo_placeholder'
    try:
        data = auth.load_session(request)
    except Exception:
        return None
    if not data or not data.get('actor'):
        return None
    return str(data['actor'])


def _agent_workspace(request: Request, db, scope: str) -> str:
    from launchcrew import agent_surfaces as surfaces_mod
    raw = _raw_workspace_key(request)
    if raw:
        row = db.execute(text('SELECT workspace_id, scopes, revoked, role FROM workspace_api_keys'
                              ' WHERE key_hash=:digest'),
                         {'digest': surfaces_mod.hash_key(raw)}).fetchone()
        granted = list(row[1]) if row is not None and isinstance(row[1], list) else []
        if row is None or bool(row[2]) or scope not in granted:
            raise HTTPException(401, 'invalid_or_revoked_workspace_key')
        try:
            allowed = surfaces_mod.scope_allowed_for_role(scope, row[3] or 'owner')
        except ValueError:
            raise HTTPException(401, 'invalid_or_revoked_workspace_key')
        if not allowed:
            raise HTTPException(403, 'insufficient_key_role')
        return str(row[0])
    actor = _agent_session_actor(request)
    if actor is None:
        raise HTTPException(401, 'invalid_or_revoked_workspace_key')
    return store.ensure_workspace_seeded(db, actor)


def _public_agent_key(row) -> dict[str, Any]:
    data = dict(row)
    created = data.get('created_at')
    if hasattr(created, 'isoformat'):
        data['created_at'] = created.isoformat()
    return {'id': data.get('id'), 'label': data.get('label', ''),
            'key_prefix': data.get('key_prefix', ''),
            'scopes': list(data.get('scopes') or []),
            'role': data.get('role') or 'owner',
            'revoked': bool(data.get('revoked', False)),
            'created_at': data.get('created_at')}


@app.post('/api/agent-surfaces/keys', status_code=201)
def create_workspace_key(body: AgentKeyCreateIn, actor: str = Depends(auth.actor)):
    """Create a workspace key for the caller workspace. The raw key is returned once."""
    from launchcrew import agent_surfaces as surfaces_mod
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        label = (body.label or '').strip()[:120]
        scopes = list(body.scopes) if body.scopes else list(surfaces_mod.DEFAULT_SCOPES)
        unknown = [scope for scope in scopes if scope not in surfaces_mod.DEFAULT_SCOPES]
        if unknown:
            raise HTTPException(422, 'Unknown workspace key scope: ' + ', '.join(unknown))
        try:
            role = surfaces_mod.normalize_key_role(body.role or 'owner')
        except ValueError as error:
            raise HTTPException(422, str(error))
        raw = surfaces_mod.generate_raw_key()
        key_id = surfaces_mod.new_key_id()
        db.execute(text('INSERT INTO workspace_api_keys(id, workspace_id, label, key_prefix,'
                        ' key_hash, scopes, revoked, role)'
                        ' VALUES (:id,:ws,:label,:prefix,:digest,CAST(:scopes AS jsonb),false,:role)'),
                   {'id': key_id, 'ws': workspace_id, 'label': label,
                    'prefix': surfaces_mod.key_prefix(raw),
                    'digest': surfaces_mod.hash_key(raw), 'scopes': json.dumps(scopes),
                    'role': role})
        store.audit(db, None, 'workspace_key_created', actor, workspace_id)
        row = db.execute(text('SELECT id, workspace_id, label, key_prefix, scopes, revoked, role, created_at'
                              ' FROM workspace_api_keys WHERE id=:id AND workspace_id=:ws'),
                         {'id': key_id, 'ws': workspace_id}).mappings().first()
        public = _public_agent_key(dict(row))
        public['workspace_id'] = workspace_id
        public['raw_key'] = raw
        return public


@app.get('/api/agent-surfaces/keys')
def list_workspace_keys(actor: str = Depends(auth.actor)):
    """List workspace keys without ever exposing raw key material."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        rows = db.execute(text('SELECT id, workspace_id, label, key_prefix, scopes, revoked, role, created_at'
                               ' FROM workspace_api_keys WHERE workspace_id=:ws'
                               ' ORDER BY created_at, id'),
                          {'ws': workspace_id}).mappings().all()
        return [_public_agent_key(dict(row)) for row in rows]


@app.post('/api/agent-surfaces/keys/{key_id}/revoke')
def revoke_workspace_key(key_id: str, actor: str = Depends(auth.actor)):
    """Revoke a workspace key. Revoked keys fail closed on every surface."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        result = db.execute(text('UPDATE workspace_api_keys SET revoked=true'
                                 ' WHERE id=:id AND workspace_id=:ws'),
                            {'id': key_id, 'ws': workspace_id})
        if result.rowcount == 0:
            raise HTTPException(404, 'Workspace key not found')
        store.audit(db, None, 'workspace_key_revoked', actor, workspace_id)
        row = db.execute(text('SELECT id, workspace_id, label, key_prefix, scopes, revoked, role, created_at'
                              ' FROM workspace_api_keys WHERE id=:id AND workspace_id=:ws'),
                         {'id': key_id, 'ws': workspace_id}).mappings().first()
        return _public_agent_key(dict(row))


_FALLBACK_SKILL_MARKDOWN = """# LaunchCrew SocialClaw

Validate then apply. Validate every slot with POST /api/agent/validate
(`launchcrew_validate`) before applying the export with POST /api/agent/apply.

Export the schedule with GET /api/calendar/schedule-export. It returns a
`schedule-export/v1` document. Apply it unchanged with
`launchcrew apply schedule-export.json`.

Every refusal names its reason. Resolve each failing condition, then
validate again. There is no override.

- `pack_not_approved`: the linked pack is not approved. Approve the run first.
- `format_check_failed`: the format check failed. Fix the named format reason first.
- `unapproved_channel_variants`: one or more selected channels are not approved.
- `invalid_or_revoked_workspace_key`: the key is missing, unknown, or revoked.
- `not_marked_ready`: the slot is not marked Ready. Mark it Ready after the gate passes.
"""


def _skill_markdown() -> str:
    path = adapter.ROOT / 'skills' / 'launchcrew-socialclaw' / 'SKILL.md'
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return _FALLBACK_SKILL_MARKDOWN


@app.get('/api/agent-surfaces/skill')
def get_agent_skill(actor: str = Depends(auth.actor)):
    """Serve the installable agent skill document with tools and refusal rules."""
    from launchcrew import agent_surfaces as surfaces_mod
    with store.connect() as db:
        store.ensure_workspace_seeded(db, actor)
        return {'name': surfaces_mod.SKILL_NAME,
                'version': surfaces_mod.SKILL_VERSION,
                'content_markdown': _skill_markdown(),
                'tools': surfaces_mod.skill_tools(),
                'refusal_rules': surfaces_mod.refusal_rules()}


def _agent_accounts(db, workspace_id) -> list[dict[str, Any]]:
    try:
        rows = db.execute(text('SELECT id, workspace_id, platform, account_handle, account_name,'
                               ' external_account_id, account_type, encrypted_token, scopes, scopes_plain,'
                               ' capabilities, status, connected_at, disconnected_at'
                               ' FROM social_connections WHERE workspace_id=:ws ORDER BY platform'),
                          {'ws': workspace_id}).mappings().all()
    except Exception:
        return []
    return [_social_row_to_public(dict(row)) for row in rows]


def _agent_capabilities(db, workspace_id) -> list[dict[str, Any]]:
    from launchcrew.format_library import list_channel_capabilities as _list_capabilities
    baseline = _list_capabilities()
    try:
        return _overlay_live_capabilities(db, workspace_id, baseline)
    except Exception:
        return baseline


def _validate_slot_ids(db, workspace_id, slot_ids: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for slot_id in slot_ids:
        row = db.execute(text('SELECT ' + _CALENDAR_PUBLIC_SELECT
                              + ' FROM calendar_slots WHERE id=:id AND workspace_id=:ws'),
                         {'id': slot_id, 'ws': workspace_id}).mappings().first()
        if row is None:
            results.append({'slot_id': slot_id, 'ready_eligible': False,
                            'failing_conditions': ['slot_not_found'],
                            'details': ['Slot not found in this workspace'],
                            'checks': {'pack_approved': False, 'format_passed': False,
                                       'variants_approved': False},
                            'unapproved_channels': [], 'format_reason': None})
            continue
        slot = dict(row)
        receipt = _receipt_for_slot(db, slot, workspace_id)
        evaluation = _evaluate_slot_ready(slot, receipt,
                                          _media_gate_reasons(db, slot['id'], workspace_id))
        results.append({'slot_id': slot_id, **evaluation})
    return results


def _apply_schedule_payload(db, workspace_id, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get('schema_version') != 'schedule-export/v1':
        raise HTTPException(422, 'schedule must use schema_version schedule-export/v1')
    ready = payload.get('ready_slots')
    if not isinstance(ready, list):
        raise HTTPException(422, 'schedule ready_slots must be a list')
    applied: list[str] = []
    refused: list[dict[str, Any]] = []
    for entry in ready:
        slot_id = entry.get('slot_id') if isinstance(entry, dict) else None
        if not slot_id or not isinstance(slot_id, str):
            refused.append({'slot_id': slot_id, 'failing_conditions': ['slot_not_found'],
                            'reasons': ['Schedule entry has no slot_id']})
            continue
        row = db.execute(text('SELECT ' + _CALENDAR_PUBLIC_SELECT
                              + ' FROM calendar_slots WHERE id=:id AND workspace_id=:ws'),
                         {'id': slot_id, 'ws': workspace_id}).mappings().first()
        if row is None:
            refused.append({'slot_id': slot_id, 'failing_conditions': ['slot_not_found'],
                            'reasons': ['Slot not found in this workspace']})
            continue
        slot = dict(row)
        receipt = _receipt_for_slot(db, slot, workspace_id)
        evaluation = _evaluate_slot_ready(slot, receipt,
                                          _media_gate_reasons(db, slot['id'], workspace_id))
        if not evaluation['ready_eligible']:
            refused.append({'slot_id': slot_id,
                            'failing_conditions': evaluation['failing_conditions'],
                            'reasons': evaluation['details']})
            continue
        db.execute(text("UPDATE calendar_slots SET schedule_state='ready', updated_at=now()"
                        ' WHERE id=:id AND workspace_id=:ws'),
                   {'id': slot_id, 'ws': workspace_id})
        store.audit(db, slot.get('run_id'), 'agent_schedule_applied', 'agent_apply', workspace_id)
        applied.append(slot_id)
    return {'schema_version': 'schedule-export/v1', 'applied_via': 'agent_apply',
            'applied_slot_ids': applied, 'refused_slots': refused,
            'ready_count': len(applied)}


@app.get('/api/agent/accounts')
def agent_accounts(request: Request):
    """Workspace social connections and platform status (same state as SC1)."""
    with store.connect() as db:
        workspace_id = _agent_workspace(request, db, 'accounts')
        return _agent_accounts(db, workspace_id)


@app.get('/api/agent/capabilities')
def agent_capabilities(request: Request):
    """Live plus baseline channel capabilities (same state as S2 and SC1)."""
    with store.connect() as db:
        workspace_id = _agent_workspace(request, db, 'capabilities')
        return _agent_capabilities(db, workspace_id)


@app.post('/api/agent/upload', status_code=201)
def agent_upload(body: MediaAssetIn, request: Request):
    """Upload a media asset into the workspace Media Library (same state as SC4)."""
    from launchcrew import media_library as media_mod
    try:
        validated = media_mod.validate_upload(body.filename, body.mime_type,
                                              body.width, body.height,
                                              body.duration_seconds, body.data_b64)
    except ValueError as error:
        raise HTTPException(422, str(error))
    data_b64 = body.data_b64.strip() if isinstance(body.data_b64, str) and body.data_b64.strip() else None
    asset_id = 'media_' + uuid4().hex
    stored = media_mod.build_asset(asset_id, validated, data_b64)
    with store.connect() as db:
        workspace_id = _agent_workspace(request, db, 'upload')
        db.execute(text('INSERT INTO media_assets(id, workspace_id, filename, media_type, mime_type,'
                        ' width, height, aspect_ratio, duration_seconds, sha256_digest,'
                        ' original_data_b64, derivatives)'
                        ' VALUES (:id,:ws,:filename,:media_type,:mime,:width,:height,'
                        ':aspect,:duration,:digest,:data,CAST(:derivatives AS jsonb))'),
                   {'id': asset_id, 'ws': workspace_id, 'filename': stored['filename'],
                    'media_type': stored['media_type'], 'mime': stored['mime_type'],
                    'width': stored['width'], 'height': stored['height'],
                    'aspect': stored['aspect_ratio'], 'duration': stored['duration_seconds'],
                    'digest': stored['sha256_digest'], 'data': stored['original_data_b64'],
                    'derivatives': json.dumps(stored['derivatives'])})
        store.audit(db, None, 'media_asset_uploaded', 'agent_apply', workspace_id)
        return _public_media_asset(_load_media_asset(db, asset_id, workspace_id))


@app.post('/api/agent/validate')
def agent_validate(body: AgentValidateIn, request: Request):
    """Validate slots with the exact S4 validate gate. Failures return 409 with Web UI reasons."""
    with store.connect() as db:
        workspace_id = _agent_workspace(request, db, 'validate')
        slot_ids: list[str] = []
        if isinstance(body.slot_id, str) and body.slot_id:
            slot_ids.append(body.slot_id)
        for entry in body.slot_ids or []:
            if isinstance(entry, str) and entry and entry not in slot_ids:
                slot_ids.append(entry)
        schedule = body.schedule if isinstance(body.schedule, dict) else None
        if schedule is not None:
            ready = schedule.get('ready_slots')
            if not isinstance(ready, list):
                raise HTTPException(422, 'schedule ready_slots must be a list')
            for entry in ready:
                slot_id = entry.get('slot_id') if isinstance(entry, dict) else None
                if isinstance(slot_id, str) and slot_id and slot_id not in slot_ids:
                    slot_ids.append(slot_id)
        if not slot_ids:
            raise HTTPException(422, 'slot_id is required')
        results = _validate_slot_ids(db, workspace_id, slot_ids)
        if len(results) == 1 and not results[0]['ready_eligible']:
            only = results[0]
            raise HTTPException(409, detail={'message': 'Slot is not ready; resolve every failing condition',
                                            'slot_id': only['slot_id'],
                                            'failing_conditions': only['failing_conditions'],
                                            'details': only['details'],
                                            'checks': only['checks'],
                                            'unapproved_channels': only['unapproved_channels'],
                                            'format_reason': only['format_reason']})
        return {'results': results,
                'refused': [item for item in results if not item['ready_eligible']]}


@app.post('/api/agent/apply')
def agent_apply(body: AgentApplyIn, request: Request):
    """Apply an exported schedule file unchanged. Every ready slot is revalidated first."""
    with store.connect() as db:
        workspace_id = _agent_workspace(request, db, 'apply')
        return _apply_schedule_payload(db, workspace_id, body.model_dump())


@app.get('/api/agent/runs/{run_id}/status')
def agent_run_status(run_id: str, request: Request):
    """Run status, approval state, and workspace schedule and publish status."""
    with store.connect() as db:
        workspace_id = _agent_workspace(request, db, 'run_status')
        row = db.execute(text('SELECT receipt FROM runs WHERE id=:id AND workspace_id=:ws'),
                         {'id': run_id, 'ws': workspace_id}).fetchone()
        if row is None:
            raise HTTPException(404, 'Run not found')
        receipt = row[0] if isinstance(row[0], dict) else {}
        counts = db.execute(text('SELECT schedule_state, COUNT(*) FROM calendar_slots'
                                 ' WHERE workspace_id=:ws GROUP BY schedule_state'),
                            {'ws': workspace_id}).all()
        schedule = {str(state): int(total) for state, total in counts}
        return {'run_id': run_id,
                'approval_state': receipt.get('approval_state'),
                'revision': receipt.get('revision'),
                'status': receipt.get('status'),
                'schedule': schedule,
                'publish': _publish_kill_switch(db, workspace_id)}


@app.get('/api/agent/status')
def agent_status(request: Request):
    """Workspace schedule and publish status across the shared calendar state."""
    with store.connect() as db:
        workspace_id = _agent_workspace(request, db, 'run_status')
        counts = db.execute(text('SELECT schedule_state, COUNT(*) FROM calendar_slots'
                                 ' WHERE workspace_id=:ws GROUP BY schedule_state'),
                            {'ws': workspace_id}).all()
        recent = db.execute(text('SELECT id, state FROM runs WHERE workspace_id=:ws'
                                 ' ORDER BY created_at DESC, id DESC LIMIT 20'),
                            {'ws': workspace_id}).mappings().all()
        return {'workspace_id': workspace_id,
                'schedule': {str(state): int(total) for state, total in counts},
                'recent_runs': [{'run_id': entry['id'],
                                 'approval_state': entry['state']} for entry in recent],
                'publish': _publish_kill_switch(db, workspace_id)}


@app.get('/api/mcp/tools')
def mcp_list_tools(request: Request):
    """List the six hosted MCP tools available to external agents."""
    from launchcrew import agent_surfaces as surfaces_mod
    with store.connect() as db:
        _agent_workspace(request, db, 'mcp')
        return {'tools': surfaces_mod.mcp_tools()}


@app.post('/api/mcp/call')
def mcp_call_tool(body: McpCallIn, request: Request):
    """Call one hosted MCP tool. Validate refusals return is_error with Web UI reasons."""
    from launchcrew import agent_surfaces as surfaces_mod
    name = (body.name or '').strip()
    arguments = body.arguments if isinstance(body.arguments, dict) else {}
    if name not in surfaces_mod.MCP_TOOL_NAMES:
        raise HTTPException(404, 'Unknown MCP tool: ' + name)
    with store.connect() as db:
        workspace_id = _agent_workspace(request, db, 'mcp')
        if name == 'launchcrew_accounts':
            return {'is_error': False, 'tool': name,
                    'connections': _agent_accounts(db, workspace_id)}
        if name == 'launchcrew_capabilities':
            return {'is_error': False, 'tool': name,
                    'capabilities': _agent_capabilities(db, workspace_id)}
        if name == 'launchcrew_upload':
            try:
                validated_input = MediaAssetIn(**{key: arguments.get(key) for key in
                                                  ('filename', 'mime_type', 'width', 'height',
                                                   'duration_seconds', 'data_b64')})
            except Exception as error:
                raise HTTPException(422, str(error))
            from launchcrew import media_library as media_mod
            try:
                validated = media_mod.validate_upload(validated_input.filename,
                                                      validated_input.mime_type,
                                                      validated_input.width,
                                                      validated_input.height,
                                                      validated_input.duration_seconds,
                                                      validated_input.data_b64)
            except ValueError as error:
                raise HTTPException(422, str(error))
            asset_id = 'media_' + uuid4().hex
            data_b64 = validated_input.data_b64
            if isinstance(data_b64, str) and not data_b64.strip():
                data_b64 = None
            stored = media_mod.build_asset(asset_id, validated, data_b64)
            db.execute(text('INSERT INTO media_assets(id, workspace_id, filename, media_type, mime_type,'
                            ' width, height, aspect_ratio, duration_seconds, sha256_digest,'
                            ' original_data_b64, derivatives)'
                            ' VALUES (:id,:ws,:filename,:media_type,:mime,:width,:height,'
                            ':aspect,:duration,:digest,:data,CAST(:derivatives AS jsonb))'),
                       {'id': asset_id, 'ws': workspace_id, 'filename': stored['filename'],
                        'media_type': stored['media_type'], 'mime': stored['mime_type'],
                        'width': stored['width'], 'height': stored['height'],
                        'aspect': stored['aspect_ratio'], 'duration': stored['duration_seconds'],
                        'digest': stored['sha256_digest'], 'data': stored['original_data_b64'],
                        'derivatives': json.dumps(stored['derivatives'])})
            store.audit(db, None, 'media_asset_uploaded', 'agent_apply', workspace_id)
            return {'is_error': False, 'tool': name,
                    'asset': _public_media_asset(_load_media_asset(db, asset_id, workspace_id))}
        if name == 'launchcrew_validate':
            slot_id = arguments.get('slot_id')
            if not isinstance(slot_id, str) or not slot_id:
                raise HTTPException(422, 'slot_id is required')
            results = _validate_slot_ids(db, workspace_id, [slot_id])
            only = results[0]
            if not only['ready_eligible']:
                return {'is_error': True, 'tool': name, 'slot_id': slot_id,
                        'failing_conditions': only['failing_conditions'],
                        'details': only['details'],
                        'reason': '; '.join(only['details']) if only['details'] else 'Slot is not ready',
                        'checks': only['checks'],
                        'unapproved_channels': only['unapproved_channels'],
                        'format_reason': only['format_reason']}
            return {'is_error': False, 'tool': name, **only}
        if name == 'launchcrew_apply':
            schedule = arguments.get('schedule')
            if not isinstance(schedule, dict):
                raise HTTPException(422, 'schedule must be a schedule-export/v1 document')
            result = _apply_schedule_payload(db, workspace_id, schedule)
            return {'is_error': False, 'tool': name, **result}
        run_id = arguments.get('run_id')
        if isinstance(run_id, str) and run_id:
            row = db.execute(text('SELECT receipt FROM runs WHERE id=:id AND workspace_id=:ws'),
                             {'id': run_id, 'ws': workspace_id}).fetchone()
            if row is None:
                return {'is_error': True, 'tool': name, 'run_id': run_id,
                        'reason': 'Run not found in this workspace'}
            receipt = row[0] if isinstance(row[0], dict) else {}
            return {'is_error': False, 'tool': name, 'run_id': run_id,
                    'approval_state': receipt.get('approval_state'),
                    'revision': receipt.get('revision'), 'status': receipt.get('status')}
        counts = db.execute(text('SELECT schedule_state, COUNT(*) FROM calendar_slots'
                                 ' WHERE workspace_id=:ws GROUP BY schedule_state'),
                            {'ws': workspace_id}).all()
        return {'is_error': False, 'tool': name, 'workspace_id': workspace_id,
                'schedule': {str(state): int(total) for state, total in counts},
                'publish': _publish_kill_switch(db, workspace_id)}


@app.get('/api/viral-generator/generations', response_model=list[ViralGenerationOut])
def list_viral_generations(actor: str = Depends(auth.actor)):
    """List workspace viral generations, newest first."""
    with store.connect() as db:
        workspace_id = store.ensure_workspace_seeded(db, actor)
        rows = db.execute(text('SELECT ' + _VIRAL_GENERATION_PUBLIC_SELECT
                               + ' FROM viral_generations WHERE workspace_id=:ws'
                               ' ORDER BY created_at DESC, id DESC'),
                          {'ws': workspace_id}).mappings().all()
        generations = []
        for row in rows:
            public = _public_viral_generation(dict(row))
            run_id = public.get('run_id')
            status = ''
            decision = ''
            if run_id:
                receipt_row = db.execute(text('SELECT receipt FROM runs WHERE id=:id'
                                              ' AND workspace_id=:ws'),
                                         {'id': run_id, 'ws': workspace_id}).fetchone()
                if receipt_row is not None and isinstance(receipt_row[0], dict):
                    receipt = receipt_row[0]
                    status = receipt.get('status', '')
                    check = receipt.get('checker_v2')
                    blocked = check.get('blocked_count') if isinstance(check, dict) else None
                    decision = 'pass' if blocked == 0 else ('fail' if blocked else '')
            public['run_status'] = status
            public['checker_decision'] = decision
            generations.append(public)
        return generations
