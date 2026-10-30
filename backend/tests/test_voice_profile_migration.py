"""Voice profile migration 006->007 on real Postgres.

Behavioral proof only, no string-only assertions. Uses disposable
schemas on the existing test Postgres, like the workspace backfill
transition test. Proves fresh upgrade allows voice_profile, legacy
rows survive, invalid kinds still fail, and downgrade refuses while
voice rows exist but succeeds once they are removed.
"""
import json
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from backend import store


def _examples():
    topics = ('garden layout', 'trail map', 'recipe card')
    return [{'input': 'Synthetic draft about %s' % topic,
             'output': 'Synthetic revision about %s' % topic} for topic in topics]


def _voice_content():
    return {'examples': _examples(), 'banned_terms': ['harbor']}


def _mem_id(prefix):
    return 'mem_%s_%s' % (prefix, uuid4().hex[:12])


def _alembic_version(db):
    with db.begin() as connection:
        return connection.execute(text('SELECT version_num FROM alembic_version')).scalar()


def test_migration_006_to_007_allows_voice_and_refuses_unsafe_downgrade():
    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+psycopg://', 1)
    admin = create_engine(url)
    schema = 'test_voice007_' + uuid4().hex[:16]
    with admin.begin() as connection:
        connection.execute(text('CREATE SCHEMA ' + schema))
    db = create_engine(url, connect_args={'options': '-csearch_path=' + schema})
    original = store.engine
    store.engine = lambda: db
    try:
        command.upgrade(Config('alembic.ini'), '006')
        assert _alembic_version(db) == '006'
        legacy_ids = []
        with db.begin() as connection:
            for kind in ('brand_fact', 'profile', 'approval_example', 'blocked_rule'):
                mem_id = _mem_id(kind)
                legacy_ids.append(mem_id)
                connection.execute(
                    text('INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id)'
                         ' VALUES (:id,:kind,:title,CAST(:content AS jsonb),NULL,:ws)'),
                    {'id': mem_id, 'kind': kind, 'title': 'Legacy %s' % kind,
                     'content': json.dumps({'claim': 'Legacy claim for %s' % kind}), 'ws': 'demo'})
        with pytest.raises(IntegrityError):
            with db.begin() as connection:
                connection.execute(
                    text('INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id)'
                         ' VALUES (:id,:kind,:title,CAST(:content AS jsonb),NULL,:ws)'),
                    {'id': _mem_id('voice'), 'kind': 'voice_profile', 'title': 'Synthetic voice',
                     'content': json.dumps(_voice_content()), 'ws': 'demo'})
        command.upgrade(Config('alembic.ini'), 'head')
        assert _alembic_version(db) == '007'
        with db.begin() as connection:
            for mem_id in legacy_ids:
                assert connection.execute(
                    text('SELECT kind FROM memory_items WHERE id=:id'), {'id': mem_id}).scalar() is not None
            voice_id = _mem_id('voice')
            connection.execute(
                text('INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id)'
                     ' VALUES (:id,:kind,:title,CAST(:content AS jsonb),NULL,:ws)'),
                {'id': voice_id, 'kind': 'voice_profile', 'title': 'Synthetic voice',
                 'content': json.dumps(_voice_content()), 'ws': 'demo'})
            assert connection.execute(
                text('SELECT kind FROM memory_items WHERE id=:id'), {'id': voice_id}).scalar() == 'voice_profile'
            for kind in ('brand_fact', 'profile', 'approval_example', 'blocked_rule'):
                mem_id = _mem_id('still_' + kind)
                connection.execute(
                    text('INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id)'
                         ' VALUES (:id,:kind,:title,CAST(:content AS jsonb),NULL,:ws)'),
                    {'id': mem_id, 'kind': kind, 'title': 'Still %s' % kind,
                     'content': json.dumps({'claim': 'x'}), 'ws': 'demo'})
                assert connection.execute(
                    text('SELECT kind FROM memory_items WHERE id=:id'), {'id': mem_id}).scalar() == kind
        with pytest.raises(IntegrityError):
            with db.begin() as connection:
                connection.execute(
                    text('INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id)'
                         ' VALUES (:id,:kind,:title,CAST(:content AS jsonb),NULL,:ws)'),
                    {'id': _mem_id('bad'), 'kind': 'not_a_kind', 'title': 'Bad',
                     'content': json.dumps({'claim': 'x'}), 'ws': 'demo'})
        with pytest.raises(Exception):
            command.downgrade(Config('alembic.ini'), '006')
        assert _alembic_version(db) == '007'
        with db.begin() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM memory_items WHERE kind='voice_profile'")).scalar() >= 1
        with db.begin() as connection:
            connection.execute(text("DELETE FROM memory_items WHERE kind='voice_profile'"))
        command.downgrade(Config('alembic.ini'), '006')
        assert _alembic_version(db) == '006'
        with pytest.raises(IntegrityError):
            with db.begin() as connection:
                connection.execute(
                    text('INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id)'
                         ' VALUES (:id,:kind,:title,CAST(:content AS jsonb),NULL,:ws)'),
                    {'id': _mem_id('voice2'), 'kind': 'voice_profile', 'title': 'Synthetic voice',
                     'content': json.dumps(_voice_content()), 'ws': 'demo'})
        with db.begin() as connection:
            for mem_id in legacy_ids:
                assert connection.execute(
                    text('SELECT kind FROM memory_items WHERE id=:id'), {'id': mem_id}).scalar() is not None
        command.upgrade(Config('alembic.ini'), 'head')
        assert _alembic_version(db) == '007'
        with db.begin() as connection:
            voice_id = _mem_id('voice3')
            connection.execute(
                text('INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id)'
                     ' VALUES (:id,:kind,:title,CAST(:content AS jsonb),NULL,:ws)'),
                {'id': voice_id, 'kind': 'voice_profile', 'title': 'Synthetic voice',
                 'content': json.dumps(_voice_content()), 'ws': 'demo'})
            assert connection.execute(
                text('SELECT kind FROM memory_items WHERE id=:id'), {'id': voice_id}).scalar() == 'voice_profile'
    finally:
        store.engine = original
        db.dispose()
        with admin.begin() as connection:
            connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        admin.dispose()


def test_migration_fresh_empty_006_to_007_allows_voice():
    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+psycopg://', 1)
    admin = create_engine(url)
    schema = 'test_voice007e_' + uuid4().hex[:16]
    with admin.begin() as connection:
        connection.execute(text('CREATE SCHEMA ' + schema))
    db = create_engine(url, connect_args={'options': '-csearch_path=' + schema})
    original = store.engine
    store.engine = lambda: db
    try:
        command.upgrade(Config('alembic.ini'), '006')
        command.upgrade(Config('alembic.ini'), 'head')
        assert _alembic_version(db) == '007'
        with db.begin() as connection:
            voice_id = _mem_id('voice')
            connection.execute(
                text('INSERT INTO memory_items(id,kind,title,content,source_run_id,workspace_id)'
                     ' VALUES (:id,:kind,:title,CAST(:content AS jsonb),NULL,:ws)'),
                {'id': voice_id, 'kind': 'voice_profile', 'title': 'Synthetic voice',
                 'content': json.dumps(_voice_content()), 'ws': 'demo'})
            row = connection.execute(
                text('SELECT kind, title FROM memory_items WHERE id=:id'), {'id': voice_id}).mappings().first()
            assert row['kind'] == 'voice_profile'
            assert row['title'] == 'Synthetic voice'
    finally:
        store.engine = original
        db.dispose()
        with admin.begin() as connection:
            connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        admin.dispose()
