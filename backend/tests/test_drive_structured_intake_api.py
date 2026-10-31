"""Drive intake converts a shared file into per-field suggestions.

Source-only tests with fake OAuth exchange and fake Drive responses. No
provider network calls, no real credentials, no live Drive proof. All
states, tokens, file IDs, titles, and contents are synthetic.
"""
import json
from unittest.mock import patch

import pytest
from launchcrew import run
from launchcrew.import_suggestions import (
    STRUCTURED_FIELDS,
    parse_structured_import,
)
from test_drive_intake_api import (
    TEXT_MIME,
    FakeHeaders,
    FakeProvider,
    _full_grant,
    _use_provider,
    drive_env,  # noqa: F401  (shared Drive env fixture)
)

ACTOR = 'google:synthetic-drive-structured-01'
SUB = 'synthetic-drive-structured-01'
FIELD_TEXT = '\n'.join([
    'Full-grain leather tote',
    'Holds six card slots',
    'Compact size',
    '$49',
    'We stitch every seam.',
])
OTHER_TEXT = '\n'.join([
    'Sampleville bake stand',
    'Est. 2021',
])


@pytest.fixture(autouse=True)
def deterministic_pipeline():
    original = run.run_pipeline

    def offline(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return original(*args, **kwargs)

    with patch('launchcrew.run.run_pipeline', side_effect=offline):
        yield


def _provider(text):
    data = text.encode('utf-8')
    headers = FakeHeaders({'Content-Type': 'text/plain; charset=utf-8',
                           'Content-Length': str(len(data))})
    metadata = {'id': 'demo-file-01', 'name': 'Demo tote notes',
                'mimeType': TEXT_MIME, 'trashed': False}
    return FakeProvider(metadata=metadata, content=(data, headers, 200))


def _suggest(client, token, file_id='demo-file-01', active_digest=None, confirm_replace=False):
    body = {'file_id': file_id, 'drive_token': token}
    if active_digest is not None:
        body['active_digest'] = active_digest
    if confirm_replace:
        body['confirm_replace'] = True
    return client.post('/api/drive-import/suggestions', json=body)


def _assert_structured_drive(body, expected_text):
    assert body['status'] == 'unconfirmed'
    assert body['source'] == 'drive_file'
    assert body['product_fact_source'] == 'drive_file'
    assert body['selection_context'] == 'Drive file selection'
    assert isinstance(body['file_title'], str) and body['file_title']
    assert body['mime_type'] == TEXT_MIME
    assert body['replaced'] is False
    expected = parse_structured_import(expected_text, 'drive_file')
    assert body['proposal_digest'] == expected['proposal_digest']
    assert [(item['field'], item['text']) for item in body['field_suggestions']] == [
        (item['field'], item['text']) for item in expected['field_suggestions']
    ]
    for position, item in enumerate(body['field_suggestions']):
        assert item['status'] == 'unconfirmed'
        assert item['confirmed'] is False
        assert item['source'] == 'drive_file'
        assert item['product_fact_source'] == 'drive_file'
        assert item['field'] in STRUCTURED_FIELDS
        assert item['index'] == position
        assert set(item) == {'field', 'text', 'source', 'product_fact_source',
                             'status', 'confirmed', 'index'}
    blob = json.dumps(body).lower()
    assert 'synthetic-drive-token' not in blob
    assert 'demo-file-01' not in blob


def test_drive_payload_converts_to_same_per_field_schema(client, monkeypatch, drive_env):
    token = _full_grant(client, monkeypatch, ACTOR, SUB, token_str='synthetic-drive-token-s1')
    _use_provider(_provider(FIELD_TEXT))
    response = _suggest(client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_structured_drive(body, FIELD_TEXT)
    by_text = {item['text']: item['field'] for item in body['field_suggestions']}
    assert by_text == {
        'Full-grain leather tote': 'material',
        'Holds six card slots': 'contents',
        'Compact size': 'size',
        '$49': 'price',
        'We stitch every seam.': 'founder_note',
    }
    assert [item['text'] for item in body['suggestions']] == FIELD_TEXT.split('\n')


def test_drive_pending_proposal_preserved_on_new_import(client, monkeypatch, drive_env):
    token = _full_grant(client, monkeypatch, ACTOR, SUB, token_str='synthetic-drive-token-s2')
    _use_provider(_provider(FIELD_TEXT))
    first = _suggest(client, token)
    assert first.status_code == 200, first.text
    first_digest = first.json()['proposal_digest']

    token = _full_grant(client, monkeypatch, ACTOR, SUB, token_str='synthetic-drive-token-s3',
                        state='synthetic-drive-state-s3')
    _use_provider(_provider(OTHER_TEXT))
    conflict = _suggest(client, token, active_digest=first_digest)
    assert conflict.status_code == 409, conflict.text
    detail = conflict.json()['detail']
    assert 'pending' in detail['message'].lower()
    assert detail['active_digest'] == first_digest
    assert detail['proposal_digest'] != first_digest
    _assert_structured_drive(detail['proposal'], OTHER_TEXT)


def test_drive_confirmed_replacement_marks_replaced(client, monkeypatch, drive_env):
    token = _full_grant(client, monkeypatch, ACTOR, SUB, token_str='synthetic-drive-token-s4')
    _use_provider(_provider(FIELD_TEXT))
    first = _suggest(client, token)
    assert first.status_code == 200, first.text
    first_digest = first.json()['proposal_digest']

    token = _full_grant(client, monkeypatch, ACTOR, SUB, token_str='synthetic-drive-token-s5',
                        state='synthetic-drive-state-s5')
    _use_provider(_provider(OTHER_TEXT))
    replaced = _suggest(client, token, active_digest=first_digest, confirm_replace=True)
    assert replaced.status_code == 200, replaced.text
    body = replaced.json()
    assert body['replaced'] is True
    assert body['proposal_digest'] != first_digest
    _assert_structured_drive({**body, 'replaced': False}, OTHER_TEXT)


def test_drive_same_digest_reread_is_not_a_conflict(client, monkeypatch, drive_env):
    token = _full_grant(client, monkeypatch, ACTOR, SUB, token_str='synthetic-drive-token-s6')
    _use_provider(_provider(FIELD_TEXT))
    first = _suggest(client, token)
    assert first.status_code == 200, first.text
    first_digest = first.json()['proposal_digest']

    token = _full_grant(client, monkeypatch, ACTOR, SUB, token_str='synthetic-drive-token-s7',
                        state='synthetic-drive-state-s7')
    _use_provider(_provider(FIELD_TEXT))
    again = _suggest(client, token, active_digest=first_digest)
    assert again.status_code == 200, again.text
    assert again.json()['proposal_digest'] == first_digest
    assert again.json()['replaced'] is False
