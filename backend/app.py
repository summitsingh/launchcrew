"""Typed local demo API. No provider auth or outbound action endpoints."""
from contextlib import asynccontextmanager
import copy
import json
from typing import Literal
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from backend import adapter, store
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


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    yield


app = FastAPI(title='LaunchCrew', lifespan=lifespan)


@app.middleware('http')
async def local_requests(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': 'Cross-origin mutation refused'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.exception_handler(ValueError)
async def invalid(request, error):
    return JSONResponse({'detail': 'Validation failed'}, status_code=422)


@app.exception_handler(UniqueViolation)
async def conflict(request, error):
    return JSONResponse({'detail': 'Already exists'}, status_code=409)


@app.get('/api/health')
def health() -> dict:
    with store.connect() as db:
        db.execute('SELECT 1')
    return {'status': 'ok', 'auth': 'disabled_demo', 'approval_by': 'demo_placeholder'}


@app.get('/api/agents', response_model=list[Profile])
def list_agents():
    with store.connect() as db:
        return [r[0] for r in db.execute('SELECT profile FROM agents ORDER BY name')]


def get_profile(db, name):
    row = db.execute('SELECT profile FROM agents WHERE name=%s', (name.lower(),)).fetchone()
    if not row:
        raise HTTPException(404, 'Agent not found')
    return row[0]


@app.get('/api/agents/{name}', response_model=Profile)
def get_agent(name: str):
    with store.connect() as db:
        return get_profile(db, name)


@app.post('/api/agents', response_model=Profile, status_code=201)
def create_agent(profile: Profile):
    value = agents.validate(profile.model_dump())
    with store.connect() as db:
        db.execute('INSERT INTO agents(name,profile) VALUES (%s,%s)', (value['name'].lower(), Jsonb(value)))
        store.audit(db, None, 'agent_created')
    return value


@app.put('/api/agents/{name}', response_model=Profile)
def edit_agent(name: str, profile: Profile):
    value = agents.validate(profile.model_dump())
    with store.connect() as db:
        old = get_profile(db, name)
        if old['name'] != value['name']:
            raise ValueError('Clone to rename')
        db.execute('UPDATE agents SET profile=%s, updated_at=now() WHERE name=%s', (Jsonb(value), name.lower()))
        store.audit(db, None, 'agent_edited')
    return value


@app.post('/api/agents/{name}/clone', response_model=Profile, status_code=201)
def clone_agent(name: str, body: Clone):
    with store.connect() as db:
        profile = get_profile(db, name)
    profile['name'] = body.name
    return create_agent(Profile(**profile))


@app.post('/api/agents/{name}/preview')
def preview_agent(name: str, body: Idea) -> dict:
    with store.connect() as db:
        return adapter.preview(get_profile(db, name), body.idea)


@app.post('/api/runs', status_code=201)
def create_run(body: RunInput) -> dict:
    with store.connect() as db:
        profile = get_profile(db, body.agent_name)
    run_id = 'run_' + uuid4().hex
    receipt = adapter.execute(run_id, body.idea, profile, body.seed_unverified_claim)
    with store.connect() as db:
        db.execute('INSERT INTO runs(id,receipt,agent_name,state) VALUES (%s,%s,%s,%s)',
                   (run_id, Jsonb(receipt), body.agent_name.lower(), receipt['approval_state']))
        db.execute('INSERT INTO memory(run_id,facts) VALUES (%s,%s)',
                   (run_id, Jsonb(receipt.get('scout', {}).get('facts_used', []))))
        store.audit(db, run_id, 'run_created')
    return receipt


@app.get('/api/queue')
def queue() -> list[dict]:
    with store.connect() as db:
        return [r[0] for r in db.execute("SELECT receipt FROM runs ORDER BY (state='pending_approval') DESC, created_at, id")]


def get_receipt(db, run_id, lock=False):
    row = db.execute('SELECT receipt FROM runs WHERE id=%s' + (' FOR UPDATE' if lock else ''), (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Run not found')
    return row[0]


@app.get('/api/runs/{run_id}')
@app.get('/api/runs/{run_id}/receipt')
def get_run(run_id: str) -> dict:
    with store.connect() as db:
        return get_receipt(db, run_id)


@app.post('/api/runs/{run_id}/approve')
def approve(run_id: str, body: Empty) -> dict:
    with store.connect() as db:
        receipt = get_receipt(db, run_id, True)
        receipts.approve_receipt(receipt, 'demo_placeholder')
        db.execute('UPDATE runs SET receipt=%s,state=%s WHERE id=%s', (Jsonb(receipt), receipt['approval_state'], run_id))
        db.execute('INSERT INTO approvals(run_id,approved_by) VALUES (%s,%s)', (run_id, 'demo_placeholder'))
        store.audit(db, run_id, 'approved_for_export')
    return receipt


@app.post('/api/runs/{run_id}/export')
def export(run_id: str, body: Empty):
    with store.connect() as db:
        data = adapter.export_pack(get_receipt(db, run_id, True))
        store.audit(db, run_id, 'exported')
    return Response(data, media_type='application/json', headers={'Content-Disposition': 'attachment; filename="launchcrew-pack.json"'})
