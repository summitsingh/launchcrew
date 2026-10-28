"""Typed FastAPI demo API over the preserved Python pipeline."""
from contextlib import asynccontextmanager
import json
from typing import Literal, Any
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from backend import adapter, store, auth
from launchcrew import agents, receipts


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
    agent_name: str
    seed_unverified_claim: bool = False


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
    approved_by: str
    action: str
    timestamp: str


class Receipt(BaseModel):
    model_config = ConfigDict(extra='allow')
    run_id: str
    idea: str = ''
    status: str
    approval_state: Literal['pending_approval', 'approved_for_export']
    approvals: list[Approval]
    maker_draft_v1: Draft | None = None
    maker_draft_v2: Draft | None = None
    checker_v1: Check | None = None
    checker_v2: Check | None = None
    summary: dict[str, Any]
    audit: dict[str, Any]


class Preview(BaseModel):
    dry_run: bool
    profile: Profile
    sample_idea: str
    first_action: str
    model_called: bool
    side_effects: bool


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


@app.post('/api/runs', response_model=Receipt, status_code=201)
def create_run(body: RunInput, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        profile = get_profile(db, body.agent_name)
    run_id = 'run_' + uuid4().hex
    receipt = adapter.execute(run_id, body.idea, profile, body.seed_unverified_claim)
    with store.connect() as db:
        db.execute(text('INSERT INTO runs(id,receipt,agent_name,state) VALUES (:id,CAST(:receipt AS jsonb),:agent,:state)'),
                   {'id': run_id, 'receipt': json.dumps(receipt), 'agent': body.agent_name.lower(), 'state': receipt['approval_state']})
        db.execute(text('INSERT INTO memory(run_id,facts) VALUES (:id,CAST(:facts AS jsonb))'), {'id': run_id, 'facts': json.dumps(receipt.get('scout', {}).get('facts_used', []))})
        store.audit(db, run_id, 'run_created', actor)
    return receipt


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


@app.post('/api/runs/{run_id}/approve', response_model=Receipt)
def approve(run_id: str, body: Empty, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        receipt = get_receipt(db, run_id, True)
        receipts.approve_receipt(receipt, actor)
        db.execute(text('UPDATE runs SET receipt=CAST(:receipt AS jsonb),state=:state WHERE id=:id'), {'receipt': json.dumps(receipt), 'state': receipt['approval_state'], 'id': run_id})
        db.execute(text('INSERT INTO approvals(run_id,approved_by) VALUES (:id,:actor)'), {'id': run_id, 'actor': actor})
        store.audit(db, run_id, 'approved_for_export', actor)
    return receipt


@app.post('/api/runs/{run_id}/export', response_model=Receipt)
def export(run_id: str, body: Empty, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        data = json.loads(adapter.export_pack(get_receipt(db, run_id, True)))
        store.audit(db, run_id, 'exported', actor)
    return JSONResponse(data, headers={'Content-Disposition': 'attachment; filename="launchcrew-pack.json"'})
