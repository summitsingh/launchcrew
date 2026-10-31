"""M3 acceptance: campaign weeks build from the campaign's own confirmed facts.

Deterministic fixtures only, no live model calls, no credentials.
A custom-facts campaign must produce seven distinct brief texts built
from its own confirmed product facts with zero bundled demo-template
facts. Demo mode (no product_facts) keeps the bundled demo week.
"""

from unittest.mock import patch

import pytest

from backend import app as app_module
from launchcrew import run

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'

DEMO_MARKERS = [
    '100% vegan PU leather',
    'Designed in Texas',
    '$49',
    'Vegan leather wallet',
    'For Austin commuters',
    'Austin commuters',
    'launch on Instagram',
]

NEW_ANGLES = [
    'Build in public milestone',
    'Customer problem story',
    'Before and after',
    'Objection answer',
    'Founder lesson',
]


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def field(value, confirmed, source='owner'):
    return {'value': value, 'confirmed': confirmed, 'source': source}


def owner_payload(**extra):
    return {'idea': IDEA, 'agent_name': 'Maker',
            'product_facts': {'material': field('Full-grain leather', True),
                              'contents': field('Six card slots', True),
                              'size': field('Bifold compact', True),
                              'price': field('$129', True),
                              **extra}}


FULL_CONFIRMED = ['Full-grain leather', 'Six card slots', 'Bifold compact', '$129']


def test_new_angles_are_selectable_alongside_existing():
    assert len(app_module.CAMPAIGN_ANGLES) == 12
    for angle in NEW_ANGLES:
        assert angle in app_module.CAMPAIGN_ANGLES
    for angle in ('Origin story', 'Material and craft', 'Launch offer'):
        assert angle in app_module.CAMPAIGN_ANGLES


def test_owner_week_builds_seven_distinct_briefs_from_confirmed_facts(client):
    response = client.post('/api/campaigns', json=owner_payload())
    assert response.status_code == 201, response.text
    week = response.json()
    assert [day['day'] for day in week['days']] == list(range(1, 8))
    briefs = [day['brief'] for day in week['days']]
    assert len(set(briefs)) == 7
    assert len({day['angle'] for day in week['days']}) == 7
    for brief in briefs:
        assert len(brief) < 140
    for marker in DEMO_MARKERS:
        for brief in briefs:
            assert marker not in brief, (marker, brief)
    for day in week['days']:
        assert any(claim in day['brief'] for claim in FULL_CONFIRMED)
        receipt = client.get('/api/runs/' + day['run_id']).json()
        assert receipt['status'] == 'completed'
        assert receipt['campaign_day'] == day['day']
        assert receipt['campaign_brief'] == day['brief']
        assert receipt['product_facts']['mode'] == 'owner_input'
        assert receipt['checker_v2']['blocked_count'] == 0
    for day in week['days']:
        post = client.get('/api/runs/' + day['run_id']).json()['maker_draft_v2']['post']
        assert 'Full-grain leather' in post
        assert '$129' in post
        for marker in DEMO_MARKERS:
            assert marker not in post, (marker, post)


def test_owner_week_honors_selected_angles(client):
    selected = ['Origin story'] + NEW_ANGLES + ['Launch offer']
    assert len(selected) == 7
    payload = owner_payload()
    payload['angles'] = selected
    response = client.post('/api/campaigns', json=payload)
    assert response.status_code == 201, response.text
    week = response.json()
    assert [day['angle'] for day in week['days']] == selected
    assert len({day['brief'] for day in week['days']}) == 7


def test_owner_week_rejects_unknown_or_duplicate_angles(client):
    payload = owner_payload()
    payload['angles'] = ['Origin story'] * 7
    assert client.post('/api/campaigns', json=payload).status_code == 422
    payload['angles'] = ['Origin story', 'Material and craft', 'Commuter use',
                         'Styling', 'Care and durability', 'Social proof',
                         'Not a real angle']
    assert client.post('/api/campaigns', json=payload).status_code == 422
    payload['angles'] = ['Origin story']
    assert client.post('/api/campaigns', json=payload).status_code == 422


def test_demo_week_unchanged_without_product_facts(client):
    response = client.post('/api/campaigns', json={'idea': IDEA, 'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    week = response.json()
    assert week['days'][0]['angle'] == 'Origin story'
    assert week['days'][6]['angle'] == 'Launch offer'
    assert len({day['brief'] for day in week['days']}) == 7
