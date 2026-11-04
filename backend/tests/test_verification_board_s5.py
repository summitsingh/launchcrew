"""S5 cross-post verification board on Postgres.

Deterministic fixtures only, no live model calls, no real fetching
(monkeypatched where a URL fetch is exercised). One row per channel
per slot carries a delivery state; verification compares live content
against the approved variant text (exact, trimmed-by-rule, mismatch);
every state change appends a timestamped attempt; verified rows feed
the outcome log.
"""
from unittest.mock import patch

import pytest
from fastapi.responses import Response

from backend import auth, store
from launchcrew import run as run_mod

IDEA = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram'
CHANNELS = ('x', 'linkedin', 'instagram', 'email', 'facebook', 'tiktok', 'shopify')
LIVE_URL = 'https://example.com/posts/launch-1'


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    pipeline = run_mod.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return pipeline(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def sign_in(client, monkeypatch, actor='google:verify-user-one'):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    response = Response()
    auth.save_session({'actor': actor}, response)
    opaque = response.headers['set-cookie'].split(';')[0].split('=', 1)[1]
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, opaque)


def new_run(client, **extra):
    response = client.post('/api/runs', json={'idea': IDEA, 'agent_name': 'Maker', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def current_revision(client, run_id):
    return client.get(f'/api/runs/{run_id}').json().get('revision', 0)


def approve_export(client, run_id):
    revision = current_revision(client, run_id)
    approved = client.post(f'/api/runs/{run_id}/approve', json={'expected_revision': revision})
    assert approved.status_code == 200, approved.text
    exported = client.post(f'/api/runs/{run_id}/export', json={'expected_revision': revision})
    assert exported.status_code == 200, exported.text
    return exported.json()


def new_slot(client, run_id):
    response = client.post('/api/calendar/slots',
                           json={'slot_date': '2026-11-03', 'slot_type': 'feed_post',
                                 'pillar': 'product', 'format': 'feed_post',
                                 'run_id': run_id})
    assert response.status_code == 201, response.text
    return response.json()


def ready_slot(client, run_id, channel):
    slot = new_slot(client, run_id)
    patched = client.patch(f'/api/calendar/slots/{slot["id"]}/schedule',
                           json={'selected_channels': [channel]})
    assert patched.status_code == 200, patched.text
    approved = client.post(f'/api/calendar/slots/{slot["id"]}/approve-channels',
                           json={'channels': [channel], 'expected_revision': current_revision(client, run_id)})
    assert approved.status_code == 200, approved.text
    return approved.json()


def valid_channel(client, run_id):
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    return next(channel for channel in CHANNELS
                if bundle[channel]['content_valid'] and bundle[channel]['text'])


def approved_text(client, run_id, channel):
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    entry = bundle[channel]
    return entry['text'], entry.get('subject') or ''


def mark_posted(client, slot_id, channel, **extra):
    body = {'live_url': LIVE_URL, 'verify_now': True}
    body.update(extra)
    response = client.post(f'/api/calendar/slots/{slot_id}/deliveries/{channel}/mark-posted',
                           json=body)
    assert response.status_code == 200, response.text
    return response.json()


def verify(client, slot_id, channel, **extra):
    response = client.post(f'/api/calendar/slots/{slot_id}/deliveries/{channel}/verify',
                           json=extra)
    assert response.status_code == 200, response.text
    return response.json()


def test_mark_posted_with_matching_text_verifies_exact(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = valid_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    text, subject = approved_text(client, run_id, channel)
    body = {'live_text': text}
    if subject:
        body['live_subject'] = subject
    delivery = mark_posted(client, slot['id'], channel, **body)
    assert delivery['slot_id'] == slot['id']
    assert delivery['channel'] == channel
    assert delivery['delivery_state'] == 'verified'
    assert delivery['match_kind'] == 'exact'
    assert delivery['differing_field'] is None
    assert delivery['live_url'] == LIVE_URL
    states = [attempt['state'] for attempt in delivery['attempts']]
    assert states == ['posted', 'verified']
    numbers = [attempt['attempt_number'] for attempt in delivery['attempts']]
    assert numbers == [1, 2]
    stamps = [attempt['timestamp'] for attempt in delivery['attempts']]
    assert all(stamp for stamp in stamps)
    assert stamps == sorted(stamps)
    reread = client.get('/api/calendar/slots?start_date=2026-11-01&end_date=2026-11-30')
    assert reread.status_code == 200, reread.text
    assert reread.json()[0]['status'] == 'verified'


def test_trimmed_by_rule_match_verifies():
    from launchcrew import channel_variants as channel_mod
    from launchcrew import verification_board as board_mod
    approved = ('Vegan leather wallets built for Austin commuters. '
                'Full grain texture that softens with every ride. '
                'Fits cards, cash, and a transit pass without bulk. '
                'Stitched to survive daily pannier duty for years. '
                'Free exchanges for sixty days when the fit is wrong. '
                'Tap through to meet the workshop behind each wallet.')
    assert len(approved) > 280
    trimmed = channel_mod.apply_channel_capability('x', approved)['text']
    assert trimmed and len(trimmed) <= 280 and trimmed != approved
    outcome = board_mod.compare_live_post_to_variant(approved, trimmed, channel='x')
    assert outcome['delivery_state'] == 'verified'
    assert outcome['match_kind'] == 'trimmed_by_rule'
    assert outcome['differing_field'] is None
    assert outcome['failure_reason'] is None
    dropped_middle = ' '.join(board_mod.excerpt(trimmed).split()[:-3]) + ' extra words here'
    mismatch = board_mod.compare_live_post_to_variant(approved, dropped_middle, channel='x')
    assert mismatch['delivery_state'] == 'failed'
    assert mismatch['match_kind'] == 'mismatch'


def test_pasted_url_with_differing_text_is_mismatch_naming_text(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = valid_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    text, _ = approved_text(client, run_id, channel)
    delivery = verify(client, slot['id'], channel,
                      live_url='https://example.com/posts/other',
                      live_text=text + ' Buy now, limited offer!')
    assert delivery['delivery_state'] == 'failed'
    assert delivery['match_kind'] == 'mismatch'
    assert delivery['differing_field'] == 'text'
    assert delivery['failure_reason'] == 'Live post mismatch on field: text'
    assert delivery['attempts'][-1]['state'] == 'failed'
    assert delivery['attempts'][-1]['match_kind'] == 'mismatch'


def test_subject_mismatch_names_subject(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = 'email'
    bundle = client.get(f'/api/runs/{run_id}/channel-variants').json()
    if not bundle['email']['content_valid'] or not bundle['email']['text']:
        pytest.skip('email variant needs revision for this fixture')
    slot = ready_slot(client, run_id, channel)
    text, _ = approved_text(client, run_id, channel)
    delivery = verify(client, slot['id'], channel, live_text=text,
                      live_subject='A totally different subject line')
    assert delivery['delivery_state'] == 'failed'
    assert delivery['match_kind'] == 'mismatch'
    assert delivery['differing_field'] == 'subject'
    assert 'subject' in (delivery['failure_reason'] or '')


def test_attempts_preserve_failed_then_verified_in_order(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = valid_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    text, subject = approved_text(client, run_id, channel)
    posted = client.post(f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/mark-posted',
                         json={'live_url': LIVE_URL})
    assert posted.status_code == 200, posted.text
    assert posted.json()['delivery_state'] == 'posted'
    failed = verify(client, slot['id'], channel, live_text='Something else entirely')
    assert failed['delivery_state'] == 'failed'
    good = {'live_text': text}
    if subject:
        good['live_subject'] = subject
    fixed = verify(client, slot['id'], channel, **good)
    assert fixed['delivery_state'] == 'verified'
    assert fixed['match_kind'] == 'exact'
    states = [attempt['state'] for attempt in fixed['attempts']]
    assert states == ['posted', 'failed', 'verified']
    assert [attempt['attempt_number'] for attempt in fixed['attempts']] == [1, 2, 3]
    stamps = [attempt['timestamp'] for attempt in fixed['attempts']]
    assert stamps == sorted(stamps)
    kinds = [attempt['match_kind'] for attempt in fixed['attempts']]
    assert kinds[1] == 'mismatch'
    assert kinds[2] == 'exact'


def test_fetch_live_url_meta_description_verifies(monkeypatch, client):
    from launchcrew import verification_board as board_mod
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = valid_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    text, _ = approved_text(client, run_id, channel)
    escaped = text.replace('&', '&amp;').replace('"', '&quot;')
    seen = {}

    def fake_fetch(url, timeout_seconds=10):
        seen['url'] = url
        return ('<html><head><meta property="og:description" content="' + escaped + '">'
                '</head><body>fallback body</body></html>', url)

    monkeypatch.setattr(board_mod, 'fetch_live_html', fake_fetch)
    delivery = verify(client, slot['id'], channel, live_url='https://example.com/posts/live')
    assert seen['url'] == 'https://example.com/posts/live'
    assert delivery['delivery_state'] == 'verified'
    assert delivery['match_kind'] == 'exact'


def test_local_url_fetch_refused_as_failed_attempt(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = valid_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    delivery = verify(client, slot['id'], channel, live_url='http://127.0.0.1:9/private-post')
    assert delivery['delivery_state'] == 'failed'
    assert delivery['match_kind'] == 'mismatch'
    assert delivery['attempts'][-1]['state'] == 'failed'


def test_owner_fail_records_reason_and_attempt(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = valid_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    response = client.post(f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/fail',
                           json={'reason': 'Post was taken down by the platform',
                                 'live_url': LIVE_URL})
    assert response.status_code == 200, response.text
    delivery = response.json()
    assert delivery['delivery_state'] == 'failed'
    assert delivery['failure_reason'] == 'Post was taken down by the platform'
    assert delivery['attempts'][-1]['state'] == 'failed'


def test_verified_row_logs_outcome_unverified_refused(client, monkeypatch):
    sign_in(client, monkeypatch)
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = valid_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    payload = {'posted_date': '2026-11-04', 'likes': 12, 'comments': 3,
               'clicks': 7, 'sales': 1, 'note': 'owner note for verified post'}
    refused = client.post(f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/outcomes',
                          json=payload)
    assert refused.status_code == 409, refused.text
    text, subject = approved_text(client, run_id, channel)
    good = {'live_text': text}
    if subject:
        good['live_subject'] = subject
    mark_posted(client, slot['id'], channel, **good)
    created = client.post(f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/outcomes',
                          json=payload)
    assert created.status_code == 201, created.text
    outcome = created.json()
    assert outcome['run_id'] == run_id
    assert outcome['note'] == 'owner note for verified post'
    assert outcome['provenance'] == 'self_reported'
    listed = client.get(f'/api/runs/{run_id}/outcomes')
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1


def test_board_lists_one_row_per_channel_per_slot(client):
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = valid_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    board = client.get('/api/calendar/verification-board')
    assert board.status_code == 200, board.text
    rows = [entry for entry in board.json() if entry['slot_id'] == slot['id']]
    assert len(rows) == 1
    assert rows[0]['channel'] == channel
    assert rows[0]['delivery_state'] == 'not_posted'
    assert rows[0]['attempts'] == []
    scoped = client.get('/api/calendar/verification-board', params={'slot_id': slot['id']})
    assert scoped.status_code == 200, scoped.text
    assert [entry['slot_id'] for entry in scoped.json()] == [slot['id']]
    text, subject = approved_text(client, run_id, channel)
    good = {'live_text': text}
    if subject:
        good['live_subject'] = subject
    mark_posted(client, slot['id'], channel, **good)
    reread = client.get('/api/calendar/verification-board', params={'slot_id': slot['id']})
    assert reread.status_code == 200, reread.text
    assert reread.json()[0]['delivery_state'] == 'verified'
    per_slot = client.get(f'/api/calendar/slots/{slot["id"]}/deliveries')
    assert per_slot.status_code == 200, per_slot.text
    assert per_slot.json()[0]['channel'] == channel


def test_verify_attempt_records_supplied_source_and_live_delivery(client):
    from launchcrew import verification_board as board_mod
    receipt = new_run(client)
    run_id = receipt['run_id']
    approve_export(client, run_id)
    channel = valid_channel(client, run_id)
    slot = ready_slot(client, run_id, channel)
    posted = client.post(f'/api/calendar/slots/{slot["id"]}/deliveries/{channel}/mark-posted',
                         json={'live_url': LIVE_URL})
    assert posted.status_code == 200, posted.text
    assert posted.json()['simulated'] is False
    assert posted.json()['attempts'][-1]['source'] is None
    text, subject = approved_text(client, run_id, channel)
    good = {'live_text': text}
    if subject:
        good['live_subject'] = subject
    fixed = verify(client, slot['id'], channel, **good)
    assert fixed['delivery_state'] == 'verified'
    assert fixed['attempts'][-1]['source'] == 'supplied'
    with pytest.raises(ValueError):
        board_mod.build_attempt('verified', source='owner-says-so')


def test_redirect_targets_face_the_same_fetch_rules():
    import urllib.request
    from launchcrew import verification_board as board_mod
    handler = board_mod._GuardedRedirectHandler()
    req = urllib.request.Request('https://example.com/start')
    for target in ('http://127.0.0.1/private-post',
                   'http://169.254.169.254/latest/meta-data/',
                   '\\\\169.254.169.254\\x',
                   'ftp://example.com/file',
                   'https://nonexistent.invalid/posts/x'):
        with pytest.raises(ValueError):
            handler.redirect_request(req, None, 302, 'Found', {}, target)
    follow = handler.redirect_request(req, None, 302, 'Found', {}, '/posts/next')
    assert follow.get_full_url() == 'https://example.com/posts/next'
