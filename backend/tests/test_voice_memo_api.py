"""Voice memo API on Postgres: attach transcript, bump revision.

Deterministic fixtures only, no audio decoding, no model calls.
Uses only the existing ``test_engine`` and ``client`` fixtures.
"""
from unittest.mock import patch


def make_run(client):
    response = client.post('/api/runs', json={'idea': 'Voice memo probe',
                                              'agent_name': 'Maker'})
    assert response.status_code == 201, response.text
    body = response.json()
    return body['run_id'], body['revision']


def offline():
    from launchcrew import run as run_mod
    pipeline = run_mod.run_pipeline

    def quiet(*args, **kwargs):
        kwargs.update(model_enabled=False, visual_verifier=None)
        return pipeline(*args, **kwargs)

    return patch('launchcrew.run.run_pipeline', side_effect=quiet)


def test_attach_bumps_revision_and_resets_approval(client):
    with offline():
        run_id, revision = make_run(client)
    response = client.post(f'/api/runs/{run_id}/voice-memo',
                           json={'transcript_text': '  Launch the wallet  ',
                                 'expected_revision': revision})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['media_provenance'] == 'voice_transcript'
    assert body['transcript'] == 'Launch the wallet'
    assert body['revision'] == revision + 1
    reread = client.get(f'/api/runs/{run_id}').json()
    assert reread['voice_memo']['transcript'] == 'Launch the wallet'
    assert reread['revision_history'][-1]['voice_memo_event'] == 'voice_memo_attached'
    assert reread['approval_state'] == 'pending_approval'
    assert reread['approvals'] == []


def test_bad_text_missing_and_stale_refuse(client):
    with offline():
        run_id, revision = make_run(client)
    empty = client.post(f'/api/runs/{run_id}/voice-memo',
                        json={'transcript_text': '   ', 'expected_revision': revision})
    assert empty.status_code == 422, empty.text
    missing = client.post('/api/runs/run_missing/voice-memo',
                          json={'transcript_text': 'Hello', 'expected_revision': 0})
    assert missing.status_code == 404, missing.text
    stale = client.post(f'/api/runs/{run_id}/voice-memo',
                        json={'transcript_text': 'Hello', 'expected_revision': 99})
    assert stale.status_code == 409, stale.text
