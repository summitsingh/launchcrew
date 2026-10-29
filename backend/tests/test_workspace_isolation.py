"""Workspace isolation: two-user denial on real Postgres.

Uses the existing disposable PG/API harness. Two distinct simulated
authenticated actors prove independent same-name profiles, no cross-user
list visibility, 404 for foreign objects, async worker scoping, demo
quarantine, global budgets unchanged, and migration backfill. Public
Memory and Campaign responses never expose internal workspace_id under
Strict validation. Omitted-owner writes fail closed with no persistent
demo default. Composite child links deny cross-workspace parents at the
DB layer. All input/session/provenance data is synthetic. No provider
calls.
"""
import base64
import io
import json
import os
import time
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.responses import Response
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from backend import auth, store
from launchcrew import run

ACTOR_ONE = 'google:iso-user-one'
ACTOR_TWO = 'google:iso-user-two'
IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


@pytest.fixture(autouse=True)
def no_model_key(monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)


def _session_cookie(actor):
    response = Response()
    auth.save_session({'actor': actor}, response)
    return response.headers['set-cookie'].split(';')[0].split('=', 1)[1]


def _sign_in(client, monkeypatch, actor):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    opaque = _session_cookie(actor)
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque)
    return opaque


def _base_profile(name, personality='Custom personality'):
    return {
        'name': name,
        'role': 'Custom role for ' + name,
        'department': 'Growth',
        'personality': personality,
        'expertise': 'Custom expertise for ' + name,
        'decision_rules': ['Use facts file first'],
        'veto_scope': [],
        'tools_allowed': ['facts_file', 'spark_strict_json', 'receipt_log', 'claim_check'],
        'spend_limit': 0,
        'approval_level': 'approve_each',
        'examples': [],
    }


def _new_run(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _new_memory(client, kind='brand_fact', title='Iso fact', content=None):
    response = client.post('/api/memory', json={
        'kind': kind, 'title': title, 'content': content or {'claim': 'Iso claim'}})
    assert response.status_code == 201, response.text
    return response.json()


def _png_data_uri():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (32, 16), (200, 30, 30)).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def _wait_completed(client, run_id, timeout=30.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        steps = client.get(f'/api/runs/{run_id}/steps')
        receipt = client.get(f'/api/runs/{run_id}/receipt')
        assert steps.status_code == 200, steps.text
        assert receipt.status_code == 200, receipt.text
        last = (steps.json(), receipt.json())
        if last[1]['status'] == 'completed':
            return last
        time.sleep(0.05)
    raise AssertionError('Timed out waiting for run ' + run_id + ': ' + repr(last))


def test_same_name_profiles_independent(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    one = client.post('/api/agents', json=_base_profile('IsoMaker', 'Personality one'))
    assert one.status_code == 201, one.text
    _sign_in(client, monkeypatch, ACTOR_TWO)
    two = client.post('/api/agents', json=_base_profile('IsoMaker', 'Personality two'))
    assert two.status_code == 201, two.text
    assert client.get('/api/agents/IsoMaker').json()['personality'] == 'Personality two'
    _sign_in(client, monkeypatch, ACTOR_ONE)
    assert client.get('/api/agents/IsoMaker').json()['personality'] == 'Personality one'
    edited = dict(one.json())
    edited['personality'] = 'Personality one edited'
    assert client.put('/api/agents/IsoMaker', json=edited).status_code == 200
    _sign_in(client, monkeypatch, ACTOR_TWO)
    assert client.get('/api/agents/IsoMaker').json()['personality'] == 'Personality two'
    with store.connect() as db:
        rows = db.execute(
            text("SELECT workspace_id, profile->>'personality' FROM agents "
                 "WHERE name='isomaker' ORDER BY workspace_id")).all()
    assert (ACTOR_ONE, 'Personality one edited') in rows
    assert (ACTOR_TWO, 'Personality two') in rows


def test_no_cross_user_list_visibility(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    mem_id = _new_memory(client)['id']
    campaign_id = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'}).json()['id']
    assert client.get('/api/queue').json() != []
    _sign_in(client, monkeypatch, ACTOR_TWO)
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []
    assert client.get('/api/campaigns').json() == []
    assert run_id not in {r['run_id'] for r in client.get('/api/queue').json()}
    assert mem_id not in {m['id'] for m in client.get('/api/memory').json()}
    assert campaign_id not in {c['id'] for c in client.get('/api/campaigns').json()}


def test_foreign_run_denied_across_mutations(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_id = _new_run(client)['run_id']
    assert client.get(f'/api/runs/{run_id}').status_code == 200
    _sign_in(client, monkeypatch, ACTOR_TWO)
    assert client.get(f'/api/runs/{run_id}').status_code == 404
    assert client.get(f'/api/runs/{run_id}/receipt').status_code == 404
    assert client.get(f'/api/runs/{run_id}/steps').status_code == 404
    assert client.post(f'/api/runs/{run_id}/revise',
                       json={'post': 'x', 'email': 'y', 'base_revision': 0}).status_code == 404
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 404
    assert client.post(f'/api/runs/{run_id}/export', json={}).status_code == 404
    assert client.post(f'/api/runs/{run_id}/photo-check',
                       json={'image_data_uri': _png_data_uri(), 'expected_revision': 0}).status_code == 404
    assert client.request('DELETE', f'/api/runs/{run_id}/photo',
                          json={'expected_revision': 0}).status_code == 404


def test_foreign_memory_denied_and_selection_blocked(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    item = _new_memory(client, title='Owner fact')
    run_id = _new_run(client)['run_id']
    assert client.post(f'/api/runs/{run_id}/approve', json={}).status_code == 200
    _sign_in(client, monkeypatch, ACTOR_TWO)
    assert client.get('/api/memory/' + item['id']).status_code == 404
    assert client.put('/api/memory/' + item['id'],
                      json={'title': 'Hijack', 'content': {}}).status_code == 404
    assert client.delete('/api/memory/' + item['id']).status_code == 404
    assert client.post('/api/runs', json={
        'idea': IDEA, 'agent_name': 'Maker', 'memory_ids': [item['id']]}).status_code == 404
    assert client.post(f'/api/memory/from-run/{run_id}',
                       json={'kind': 'blocked_rule'}).status_code == 404


def test_replay_requires_both_sides_owned(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    own_a = _new_run(client)['run_id']
    own_b = _new_run(client)['run_id']
    assert client.get(f'/api/runs/{own_a}/diff/{own_b}').status_code == 200
    _sign_in(client, monkeypatch, ACTOR_TWO)
    foreign = _new_run(client)['run_id']
    assert client.get(f'/api/runs/{foreign}/diff/{own_a}').status_code == 404
    assert client.get(f'/api/runs/{own_a}/diff/{foreign}').status_code == 404
    _sign_in(client, monkeypatch, ACTOR_ONE)
    assert client.get(f'/api/runs/{own_a}/diff/{foreign}').status_code == 404


def test_foreign_campaign_and_days_denied(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    week = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'}).json()
    campaign_id = week['id']
    day_run = week['days'][0]['run_id']
    _sign_in(client, monkeypatch, ACTOR_TWO)
    assert client.get('/api/campaigns/' + campaign_id).status_code == 404
    assert client.get(f'/api/runs/{day_run}').status_code == 404
    assert client.post(f'/api/campaigns/{campaign_id}/days/1/approve', json={}).status_code == 404
    assert client.post(f'/api/campaigns/{campaign_id}/days/1/export', json={}).status_code == 404


def test_async_worker_scoped_completion(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    response = client.post('/api/runs/async', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 202, response.text
    run_id = response.json()['run_id']
    steps, receipt = _wait_completed(client, run_id)
    assert receipt['approval_state'] == 'pending_approval'
    assert 'receipt' in [row['stage'] for row in steps['steps'] if row['state'] == 'completed']
    _sign_in(client, monkeypatch, ACTOR_TWO)
    assert client.get(f'/api/runs/{run_id}').status_code == 404
    assert client.get(f'/api/runs/{run_id}/steps').status_code == 404
    assert client.get('/api/queue').json() == []
    with store.connect() as db:
        owner = db.execute(text('SELECT workspace_id FROM runs WHERE id=:id'),
                           {'id': run_id}).scalar()
        assert owner == ACTOR_ONE


def test_demo_quarantine_and_own_defaults(client, monkeypatch):
    demo_run = _new_run(client)['run_id']
    demo_mem = _new_memory(client, title='Demo fact')['id']
    demo_campaign = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'}).json()['id']
    demo_profile = client.post('/api/agents', json=_base_profile('DemoOnly', 'Demo personality'))
    assert demo_profile.status_code == 201
    _sign_in(client, monkeypatch, ACTOR_ONE)
    assert client.get('/api/queue').json() == []
    assert client.get('/api/memory').json() == []
    assert client.get('/api/campaigns').json() == []
    assert client.get(f'/api/runs/{demo_run}').status_code == 404
    assert client.get('/api/memory/' + demo_mem).status_code == 404
    assert client.get('/api/campaigns/' + demo_campaign).status_code == 404
    assert client.get('/api/agents/DemoOnly').status_code == 404
    names = {profile['name'] for profile in client.get('/api/agents').json()}
    assert {'Scout', 'Maker', 'Checker'} <= names
    owned = _new_run(client)['run_id']
    assert client.get(f'/api/runs/{owned}').status_code == 200
    monkeypatch.setenv('AUTH_ENABLED', 'false')
    client.cookies.clear()
    assert demo_run in {r['run_id'] for r in client.get('/api/queue').json()}
    assert client.get(f'/api/runs/{demo_run}').status_code == 200


def test_global_budgets_unchanged(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    _new_run(client)
    _new_memory(client)
    client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'})
    with store.connect() as db:
        sam = db.execute(text("SELECT remaining_images FROM sam_budget WHERE id='global'")).scalar()
        model = db.execute(text("SELECT remaining_micros FROM model_budget WHERE id='global'")).scalar()
    assert sam == 0
    assert model == 0


def test_migration_backfill_demo_ownership(client, monkeypatch):
    demo_run = _new_run(client)['run_id']
    demo_mem = _new_memory(client)['id']
    demo_campaign = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'}).json()['id']
    _sign_in(client, monkeypatch, ACTOR_ONE)
    owned_run = _new_run(client)['run_id']
    owned_mem = _new_memory(client)['id']
    with store.connect() as db:
        workspaces = {row[0] for row in db.execute(text('SELECT id FROM workspaces')).all()}
        assert 'demo' in workspaces
        assert ACTOR_ONE in workspaces
        assert db.execute(text('SELECT workspace_id FROM runs WHERE id=:id'),
                          {'id': demo_run}).scalar() == 'demo'
        assert db.execute(text('SELECT workspace_id FROM runs WHERE id=:id'),
                          {'id': owned_run}).scalar() == ACTOR_ONE
        assert db.execute(text('SELECT workspace_id FROM memory_items WHERE id=:id'),
                          {'id': demo_mem}).scalar() == 'demo'
        assert db.execute(text('SELECT workspace_id FROM memory_items WHERE id=:id'),
                          {'id': owned_mem}).scalar() == ACTOR_ONE
        assert db.execute(text('SELECT workspace_id FROM campaigns WHERE id=:id'),
                          {'id': demo_campaign}).scalar() == 'demo'
        assert db.execute(text("SELECT count(*) FROM agents WHERE workspace_id='demo'")).scalar() >= 3
        assert db.execute(text('SELECT count(*) FROM agents WHERE workspace_id=:ws'),
                          {'ws': ACTOR_ONE}).scalar() >= 3


_MEMORY_PUBLIC_KEYS = {'id', 'kind', 'title', 'content', 'source_run_id', 'created_at', 'updated_at'}
_CAMPAIGN_PUBLIC_KEYS = {'id', 'idea', 'agent_name', 'created_at', 'days'}


def _assert_no_workspace(obj):
    if isinstance(obj, dict):
        assert 'workspace_id' not in obj
        for value in obj.values():
            _assert_no_workspace(value)
    elif isinstance(obj, list):
        for value in obj:
            _assert_no_workspace(value)


def test_memory_create_read_hides_workspace_two_users(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    created = _new_memory(client, title='One fact')
    assert set(created) == _MEMORY_PUBLIC_KEYS
    _assert_no_workspace(created)
    listed = client.get('/api/memory').json()
    assert len(listed) == 1 and set(listed[0]) == _MEMORY_PUBLIC_KEYS
    _assert_no_workspace(listed)
    fetched = client.get('/api/memory/' + created['id']).json()
    assert fetched == created
    edited = client.put('/api/memory/' + created['id'],
                        json={'title': 'One fact edited', 'content': {'claim': 'Iso claim'}}).json()
    assert set(edited) == _MEMORY_PUBLIC_KEYS and edited['title'] == 'One fact edited'
    _assert_no_workspace(edited)
    _sign_in(client, monkeypatch, ACTOR_TWO)
    assert client.get('/api/memory').json() == []
    assert client.get('/api/memory/' + created['id']).status_code == 404
    assert client.put('/api/memory/' + created['id'],
                      json={'title': 'Hijack', 'content': {}}).status_code == 404
    assert client.delete('/api/memory/' + created['id']).status_code == 404
    other = _new_memory(client, title='One fact')
    assert other['id'] != created['id'] and set(other) == _MEMORY_PUBLIC_KEYS
    _assert_no_workspace(other)
    assert [item['id'] for item in client.get('/api/memory').json()] == [other['id']]
    _sign_in(client, monkeypatch, ACTOR_ONE)
    assert [item['id'] for item in client.get('/api/memory').json()] == [created['id']]


def test_campaign_create_read_hides_workspace_two_users(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    created = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert created.status_code == 201, created.text
    week = created.json()
    assert set(week) == _CAMPAIGN_PUBLIC_KEYS
    _assert_no_workspace(week)
    assert len(week['days']) == 7
    listed = client.get('/api/campaigns').json()
    assert listed == [week]
    _assert_no_workspace(listed)
    fetched = client.get('/api/campaigns/' + week['id']).json()
    assert fetched == week
    campaign_id = week['id']
    day_run = week['days'][0]['run_id']
    _sign_in(client, monkeypatch, ACTOR_TWO)
    assert client.get('/api/campaigns').json() == []
    assert client.get('/api/campaigns/' + campaign_id).status_code == 404
    assert client.get(f'/api/runs/{day_run}').status_code == 404
    assert client.post(f'/api/campaigns/{campaign_id}/days/1/approve', json={}).status_code == 404
    assert client.post(f'/api/campaigns/{campaign_id}/days/1/export', json={}).status_code == 404
    other = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'}).json()
    assert other['id'] != campaign_id and set(other) == _CAMPAIGN_PUBLIC_KEYS
    _assert_no_workspace(other)
    assert [row['id'] for row in client.get('/api/campaigns').json()] == [other['id']]
    _sign_in(client, monkeypatch, ACTOR_ONE)
    assert [row['id'] for row in client.get('/api/campaigns').json()] == [campaign_id]


def test_omitted_workspace_fails_closed_no_demo_default(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    owned_run = _new_run(client)['run_id']
    with store.connect() as db:
        db.execute(text("INSERT INTO campaigns(id,idea,agent_name,workspace_id) VALUES ('camp_empty_omit', :idea, 'Maker', :ws)"),
                   {'idea': IDEA, 'ws': ACTOR_ONE})
    with store.connect() as db:
        defaults = db.execute(text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND column_name = 'workspace_id' "
            "AND column_default IS NOT NULL")).scalars().all()
    assert defaults == []
    profile = json.dumps(_base_profile('NoDefault', 'No default personality'))
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            db.execute(text("INSERT INTO agents(name,profile) VALUES ('nodefault', CAST(:p AS jsonb))"),
                       {'p': profile})
    with store.connect() as db:
        assert db.execute(text("SELECT count(*) FROM agents WHERE name='nodefault'")).scalar() == 0
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            db.execute(text("INSERT INTO runs(id,receipt,agent_name,state) VALUES ('run_nodefault', CAST(:r AS jsonb), 'maker', 'pending_approval')"),
                       {'r': json.dumps({'run_id': 'run_nodefault'})})
    with store.connect() as db:
        assert db.execute(text("SELECT count(*) FROM runs WHERE id='run_nodefault'")).scalar() == 0
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            db.execute(text("INSERT INTO memory_items(id,kind,title,content) VALUES ('mem_nodefault','brand_fact','No default',CAST(:c AS jsonb))"),
                       {'c': json.dumps({'claim': 'No default'})})
    with store.connect() as db:
        assert db.execute(text("SELECT count(*) FROM memory_items WHERE id='mem_nodefault'")).scalar() == 0
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            db.execute(text("INSERT INTO campaigns(id,idea,agent_name) VALUES ('camp_nodefault', :idea, 'Maker')"),
                       {'idea': IDEA})
    with store.connect() as db:
        assert db.execute(text("SELECT count(*) FROM campaigns WHERE id='camp_nodefault'")).scalar() == 0
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            db.execute(text("INSERT INTO audit(run_id,action,actor) VALUES (:run,'nodefault_probe',:actor)"),
                       {'run': owned_run, 'actor': ACTOR_ONE})
    with store.connect() as db:
        assert db.execute(text("SELECT count(*) FROM audit WHERE action='nodefault_probe'")).scalar() == 0
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            db.execute(text("INSERT INTO campaign_days(campaign_id,day,run_id) VALUES ('camp_empty_omit',1,:run)"),
                       {'run': owned_run})
    with store.connect() as db:
        assert db.execute(text("SELECT count(*) FROM campaign_days WHERE campaign_id='camp_empty_omit'")).scalar() == 0


def test_composite_child_links_deny_cross_workspace(client, monkeypatch):
    _sign_in(client, monkeypatch, ACTOR_ONE)
    run_one = _new_run(client)['run_id']
    _sign_in(client, monkeypatch, ACTOR_TWO)
    run_two = _new_run(client)['run_id']
    with store.connect() as db:
        db.execute(text("INSERT INTO campaigns(id,idea,agent_name,workspace_id) VALUES ('camp_empty_cross', :idea, 'Maker', :ws)"),
                   {'idea': IDEA, 'ws': ACTOR_TWO})
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            db.execute(text("INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id) VALUES ('mem_cross','brand_fact','Cross',CAST(:c AS jsonb),:run,:ws)"),
                       {'c': json.dumps({'claim': 'Cross'}), 'run': run_one, 'ws': ACTOR_TWO})
    with store.connect() as db:
        assert db.execute(text("SELECT count(*) FROM memory_items WHERE id='mem_cross'")).scalar() == 0
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            db.execute(text("INSERT INTO audit(run_id,action,actor,workspace_id) VALUES (:run,'cross_probe',:actor,:ws)"),
                       {'run': run_one, 'actor': ACTOR_TWO, 'ws': ACTOR_TWO})
    with store.connect() as db:
        assert db.execute(text("SELECT count(*) FROM audit WHERE action='cross_probe'")).scalar() == 0
    with pytest.raises(IntegrityError):
        with store.connect() as db:
            db.execute(text("INSERT INTO campaign_days(campaign_id,day,run_id,workspace_id) VALUES ('camp_empty_cross',1,:run,:ws)"),
                       {'run': run_one, 'ws': ACTOR_TWO})
    with store.connect() as db:
        assert db.execute(text("SELECT count(*) FROM campaign_days WHERE campaign_id='camp_empty_cross'")).scalar() == 0
    with store.connect() as db:
        db.execute(text("INSERT INTO campaign_days(campaign_id,day,run_id,workspace_id) VALUES ('camp_empty_cross',1,:run,:ws)"),
                   {'run': run_two, 'ws': ACTOR_TWO})
        assert db.execute(text("SELECT workspace_id FROM campaign_days WHERE campaign_id='camp_empty_cross'")).scalar() == ACTOR_TWO
    with store.connect() as db:
        db.execute(text("INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id) VALUES ('mem_nullok','brand_fact','Null ok',CAST(:c AS jsonb),NULL,:ws)"),
                   {'c': json.dumps({'claim': 'Null ok'}), 'ws': ACTOR_TWO})
        assert db.execute(text("SELECT workspace_id FROM memory_items WHERE id='mem_nullok'")).scalar() == ACTOR_TWO
        db.execute(text("INSERT INTO audit(run_id,action,actor,workspace_id) VALUES (NULL,'null_ok',:actor,:ws)"),
                   {'actor': ACTOR_TWO, 'ws': ACTOR_TWO})
        assert db.execute(text("SELECT count(*) FROM audit WHERE action='null_ok'")).scalar() == 1


def test_migration_005_to_006_backfill_transition():
    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+psycopg://', 1)
    admin = create_engine(url)
    schema = 'test_trans_' + uuid4().hex[:16]
    with admin.begin() as connection:
        connection.execute(text('CREATE SCHEMA ' + schema))
    db = create_engine(url, connect_args={'options': '-csearch_path=' + schema})
    original = store.engine
    store.engine = lambda: db
    try:
        command.upgrade(Config('alembic.ini'), '005')
        legacy_run = {'run_id': 'run_legacy', 'status': 'completed', 'approval_state': 'pending_approval'}
        with db.begin() as connection:
            connection.execute(text("INSERT INTO agents(name,profile) VALUES ('maker', CAST(:p AS jsonb))"),
                               {'p': json.dumps({'name': 'Maker'})})
            connection.execute(text("INSERT INTO runs(id,receipt,agent_name,state) VALUES ('run_legacy', CAST(:r AS jsonb), 'maker', 'pending_approval')"),
                               {'r': json.dumps(legacy_run)})
            connection.execute(text("INSERT INTO memory_items(id,kind,title,content,source_run_id) VALUES ('mem_legacy','brand_fact','Legacy',CAST(:c AS jsonb),'run_legacy')"),
                               {'c': json.dumps({'claim': 'Legacy claim'})})
            connection.execute(text("INSERT INTO campaigns(id,idea,agent_name) VALUES ('camp_legacy', :idea, 'Maker')"),
                               {'idea': IDEA})
            connection.execute(text("INSERT INTO campaign_days(campaign_id,day,run_id) VALUES ('camp_legacy',1,'run_legacy')"))
            connection.execute(text("INSERT INTO audit(run_id,action,actor) VALUES ('run_legacy','legacy_probe','demo_placeholder')"))
        command.upgrade(Config('alembic.ini'), 'head')
        with db.begin() as connection:
            assert connection.execute(text("SELECT id FROM workspaces WHERE id='demo'")).scalar() == 'demo'
            assert connection.execute(text("SELECT workspace_id FROM agents WHERE name='maker'")).scalar() == 'demo'
            assert connection.execute(text("SELECT workspace_id FROM runs WHERE id='run_legacy'")).scalar() == 'demo'
            assert connection.execute(text("SELECT workspace_id FROM memory_items WHERE id='mem_legacy'")).scalar() == 'demo'
            assert connection.execute(text("SELECT workspace_id FROM campaigns WHERE id='camp_legacy'")).scalar() == 'demo'
            assert connection.execute(text("SELECT workspace_id FROM campaign_days WHERE campaign_id='camp_legacy'")).scalar() == 'demo'
            assert connection.execute(text("SELECT workspace_id FROM audit WHERE action='legacy_probe'")).scalar() == 'demo'
            assert connection.execute(text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND column_name = 'workspace_id' "
                "AND column_default IS NOT NULL")).scalar() == 0
            constraints = {row[0] for row in connection.execute(text(
                "SELECT conname FROM pg_constraint WHERE conname IN "
                "('memory_items_source_workspace_fkey','audit_run_workspace_fkey',"
                "'campaign_days_campaign_workspace_fkey','campaign_days_run_workspace_fkey',"
                "'runs_id_workspace_unique','campaigns_id_workspace_unique')")).all()}
            assert constraints == {'memory_items_source_workspace_fkey', 'audit_run_workspace_fkey',
                                   'campaign_days_campaign_workspace_fkey', 'campaign_days_run_workspace_fkey',
                                   'runs_id_workspace_unique', 'campaigns_id_workspace_unique'}
    finally:
        store.engine = original
        db.dispose()
        with admin.begin() as connection:
            connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        admin.dispose()
