"""Postgres system of record. Each mutation and its audit commit together."""
import os
from pathlib import Path
import psycopg
from psycopg.types.json import Jsonb
from launchcrew import agents
from backend.adapter import ROOT


def connect():
    return psycopg.connect(os.environ['DATABASE_URL'])


def initialize():
    with connect() as db:
        db.execute((ROOT / 'db/001_init.sql').read_text())
        for profile in agents.list_agents(ROOT / 'agents'):
            db.execute('INSERT INTO agents(name,profile) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                       (profile['name'].lower(), Jsonb(profile)))


def audit(db, run_id, action):
    db.execute('INSERT INTO audit(run_id,action,actor) VALUES (%s,%s,%s)',
               (run_id, action, 'demo_placeholder'))
