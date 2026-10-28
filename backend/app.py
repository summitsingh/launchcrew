"""Typed FastAPI demo API over the preserved Python pipeline."""
from contextlib import asynccontextmanager
import json
from datetime import datetime
from typing import Literal, Any
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
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
    memory_ids: list[str] = []
    checker_profile: Literal['standard', 'strict'] = 'standard'


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
    memory_used: list[dict[str, Any]] = []
    checker_profile: str = 'standard'
    campaign_day: int | None = None
    campaign_brief: str | None = None
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


def load_memory_selection(db, memory_ids):
    items = []
    for item_id in (memory_ids or []):
        items.append(memory_item(db, item_id))
    return items


@app.post('/api/runs', response_model=Receipt, status_code=201)
def create_run(body: RunInput, actor: str = Depends(auth.actor)):
    with store.connect() as db:
        profile = get_profile(db, body.agent_name)
        items = load_memory_selection(db, body.memory_ids)
    run_id = 'run_' + uuid4().hex
    receipt = adapter.execute(run_id, body.idea, profile, body.seed_unverified_claim,
                              memory_items=items, checker_profile=body.checker_profile)
    with store.connect() as db:
        save_run(db, receipt, body.agent_name, actor)
    return receipt


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
        receipt = get_receipt(db, run_id, True)
        if receipt['approval_state'] != 'approved_for_export':
            raise HTTPException(409, 'Learning requires explicit run approval')
        content = ({'idea': receipt['idea'], 'post': receipt['maker_draft_v2']['post'], 'email': receipt['maker_draft_v2']['email']}
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


def diff_receipts(a, b):
    result = {'run_a_id': a['run_id'], 'run_b_id': b['run_id'],
              'same_idea': a.get('idea') == b.get('idea'), 'idea': a.get('idea', ''),
              'approval_state_changed': a['approval_state'] != b['approval_state'],
              'checker_profile_a': a.get('checker_profile'), 'checker_profile_b': b.get('checker_profile'),
              'checker_profile_changed': a.get('checker_profile') != b.get('checker_profile'),
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
        angle, brief, _claim = CAMPAIGN_BRIEF_BY_DAY.get(day, ('', '', ''))
        result['days'].append({'day': day, 'run_id': receipt['run_id'], 'approval_state': receipt['approval_state'],
                               'status': receipt['status'], 'checker_v2_blocked_count': (receipt.get('checker_v2') or {}).get('blocked_count'),
                               'idea': receipt.get('idea', ''), 'angle': angle, 'brief': brief,
                               'draft_v2_post': (receipt.get('maker_draft_v2') or {}).get('post')})
    return result


@app.post('/api/campaigns', response_model=CampaignOut, status_code=201)
def create_campaign(body: RunInput, actor: str = Depends(auth.actor)):
    campaign_id = 'camp_' + uuid4().hex
    with store.connect() as db:
        profile = get_profile(db, body.agent_name)
        items = load_memory_selection(db, body.memory_ids)
        db.execute(text('INSERT INTO campaigns(id,idea,agent_name) VALUES (:id,:idea,:agent)'),
                   {'id': campaign_id, 'idea': body.idea, 'agent': body.agent_name})
        for day in range(1, 8):
            angle, brief, brief_claim = CAMPAIGN_BRIEF_BY_DAY[day]
            run_id = 'run_' + uuid4().hex
            receipt = adapter.execute(run_id, body.idea, profile, body.seed_unverified_claim,
                                      memory_items=items, checker_profile=body.checker_profile,
                                      brief=brief, campaign_day=day, extra_claims=[brief_claim])
            save_run(db, receipt, body.agent_name, actor)
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
def approve_campaign_day(campaign_id: str, day: int, body: Empty, actor: str = Depends(auth.actor)):
    return approve(campaign_run(campaign_id, day), body, actor)


@app.post('/api/campaigns/{campaign_id}/days/{day}/export', response_model=Receipt)
def export_campaign_day(campaign_id: str, day: int, body: Empty, actor: str = Depends(auth.actor)):
    return export(campaign_run(campaign_id, day), body, actor)
