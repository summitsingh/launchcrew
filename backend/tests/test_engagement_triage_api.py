"""Engagement triage API on Postgres: log, filter, staged handling.

Deterministic fixtures only, no live platform calls, nothing is ever
sent. Uses only the existing ``test_engine`` and ``client`` fixtures.
"""


def log_item(client, **extra):
    body = {'platform': 'instagram', 'kind': 'comment',
            'external_ref': 'post_1', 'author_handle': 'owner',
            'text': 'When does this restock?'}
    body.update(extra)
    response = client.post('/api/engagement/items', json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_log_classifies_and_filters(client):
    question = log_item(client)
    assert question['triage'] == 'question'
    assert question['reply_status'] == 'none'
    complaint = log_item(client, platform='tiktok', external_ref='vid_9',
                         text='Arrived broken, want a refund')
    assert complaint['triage'] == 'complaint'
    spam = log_item(client, platform='x', external_ref='post_7',
                    text='Free money crypto, click here')
    assert spam['triage'] == 'spam_risk'
    assert [item['id'] for item in client.get('/api/engagement/items').json()] == \
        [question['id'], complaint['id'], spam['id']]
    filtered = client.get('/api/engagement/items',
                          params={'triage': 'complaint'}).json()
    assert [item['id'] for item in filtered] == [complaint['id']]
    assert client.get('/api/engagement/items',
                      params={'triage': 'nope'}).status_code == 422


def test_duplicate_ref_and_bad_input_refuse(client):
    log_item(client)
    dup = client.post('/api/engagement/items',
                      json={'platform': 'instagram', 'kind': 'comment',
                            'external_ref': 'post_1', 'author_handle': 'owner',
                            'text': 'Another note'})
    assert dup.status_code == 409, dup.text
    unknown = client.post('/api/engagement/items',
                          json={'platform': 'myspace', 'kind': 'comment',
                                'external_ref': 'post_2', 'author_handle': 'owner',
                                'text': 'Hello'})
    assert unknown.status_code == 422, unknown.text
    bad_kind = client.post('/api/engagement/items',
                           json={'platform': 'instagram', 'kind': 'email',
                                 'external_ref': 'post_3', 'author_handle': 'owner',
                                 'text': 'Hello'})
    assert bad_kind.status_code == 422, bad_kind.text
    missing = client.post('/api/engagement/items/eng_missing/suggest')
    assert missing.status_code == 404, missing.text


def test_staged_reply_flow(client):
    item = log_item(client)
    suggested = client.post(f'/api/engagement/items/{item["id"]}/suggest')
    assert suggested.status_code == 200, suggested.text
    assert suggested.json()['reply_status'] == 'draft'
    assert 'owner' in suggested.json()['reply_draft']
    early_handle = client.post(f'/api/engagement/items/{item["id"]}/handle')
    assert early_handle.status_code == 422, early_handle.text
    approved = client.post(f'/api/engagement/items/{item["id"]}/approve')
    assert approved.status_code == 200, approved.text
    assert approved.json()['reply_status'] == 'approved'
    handled = client.post(f'/api/engagement/items/{item["id"]}/handle')
    assert handled.status_code == 200, handled.text
    assert handled.json()['reply_status'] == 'handled'


def test_spam_risk_gets_no_draft(client):
    item = log_item(client, platform='x', external_ref='spam_1',
                    text='Free money crypto, click here')
    refused = client.post(f'/api/engagement/items/{item["id"]}/suggest')
    assert refused.status_code == 422, refused.text
    approve = client.post(f'/api/engagement/items/{item["id"]}/approve')
    assert approve.status_code == 422, approve.text


def test_dm_kind_supported(client):
    item = log_item(client, kind='dm', external_ref='dm_1',
                    text='Love this, amazing quality')
    assert item['kind'] == 'dm'
    assert item['triage'] == 'praise'
