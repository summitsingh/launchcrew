"""Waitlist API regressions on Postgres (Gap 11).

POST /api/waitlist validates input, stores each signup exactly once,
and treats a repeat email as an idempotent duplicate (HTTP 200 with
duplicate=true) instead of storing twice. GET /api/waitlist retrieves
stored signups oldest first. The Checker path stays unmetered: no
credits, no gating on the checking route.
"""
from sqlalchemy import text

from backend import store


def _clean(db):
    db.execute(text('DELETE FROM waitlist_signups'))


def test_waitlist_accepts_valid_signup(client, test_engine):
    with test_engine.begin() as db:
        _clean(db)
    response = client.post('/api/waitlist', json={'email': 'Founder@Example.com ', 'interest': 'launch updates', 'tier': 'pro'})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['email'] == 'founder@example.com'
    assert body['interest'] == 'launch updates'
    assert body['tier'] == 'pro'
    assert body['duplicate'] is False
    assert body['id']
    assert body['created_at']


def test_waitlist_rejects_invalid_email(client, test_engine):
    with test_engine.begin() as db:
        _clean(db)
    for bad in ['', 'not-an-email', 'a@b', 'a @b.com', 'x' * 250 + '@y.com']:
        response = client.post('/api/waitlist', json={'email': bad, 'tier': 'free'})
        assert response.status_code == 422, (bad, response.text)


def test_waitlist_rejects_invalid_tier(client, test_engine):
    with test_engine.begin() as db:
        _clean(db)
    response = client.post('/api/waitlist', json={'email': 'ok@example.com', 'tier': 'enterprise'})
    assert response.status_code == 422, response.text


def test_waitlist_duplicate_is_idempotent(client, test_engine):
    with test_engine.begin() as db:
        _clean(db)
    first = client.post('/api/waitlist', json={'email': 'repeat@example.com', 'tier': 'team'})
    assert first.status_code == 201, first.text
    second = client.post('/api/waitlist', json={'email': ' Repeat@Example.com', 'tier': 'free'})
    assert second.status_code == 200, second.text
    body = second.json()
    assert body['duplicate'] is True
    assert body['id'] == first.json()['id']
    assert body['email'] == 'repeat@example.com'
    with store.connect() as db:
        count = db.execute(text("SELECT COUNT(*) FROM waitlist_signups WHERE email='repeat@example.com'")).scalar()
    assert count == 1


def test_waitlist_retrieval_lists_oldest_first(client, test_engine):
    with test_engine.begin() as db:
        _clean(db)
    for address in ('c@example.com', 'a@example.com', 'b@example.com'):
        response = client.post('/api/waitlist', json={'email': address, 'tier': 'free'})
        assert response.status_code == 201, response.text
    response = client.get('/api/waitlist')
    assert response.status_code == 200, response.text
    emails = [row['email'] for row in response.json()]
    assert emails == ['c@example.com', 'a@example.com', 'b@example.com']


def test_waitlist_does_not_gate_checker(client, test_engine):
    with test_engine.begin() as db:
        _clean(db)
    response = client.post('/api/runs', json={'idea': 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram', 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt['checker_v1'] is not None
    assert 'blocked_count' in receipt['checker_v1']
