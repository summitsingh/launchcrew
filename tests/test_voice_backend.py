"""Slice 3 voice backend contracts: validation, diff, invalidation, isolation.

All fixtures are synthetic style references. No real names, emails,
account IDs, photos, secrets, or personal data appear here. No network,
no live database, no credentials. Fake DB objects assert workspace
scoping; store.audit is patched to capture calls.
"""
import copy
import json
import unittest
from unittest.mock import patch

from backend import app as app_mod
from backend import store
from fastapi import HTTPException


def _examples():
    topics = ('garden layout', 'trail map', 'recipe card')
    return [{'input': 'Synthetic draft about %s' % t,
             'output': 'Synthetic revision about %s' % t} for t in topics]


def _voice_content(banned_terms=None):
    payload = {'examples': _examples()}
    if banned_terms is not None:
        payload['banned_terms'] = list(banned_terms)
    return payload


class _FakeMappings:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def first(self):
        return self._row

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, row=None, rows=None, fetch=None, rowcount=0):
        self._row = row
        self._rows = rows
        self._fetch = fetch
        self.rowcount = rowcount

    def mappings(self):
        return _FakeMappings(row=self._row, rows=self._rows)

    def fetchone(self):
        return self._fetch

    def all(self):
        return self._rows or []


class _FakeDB:
    """Minimal fake Connection recording SQL and enforcing workspace scope."""

    def __init__(self):
        self.memory = {}
        self.runs = []
        self.calls = []

    def execute(self, statement, params=None):
        params = dict(params or {})
        sql = str(statement)
        self.calls.append((sql, dict(params)))
        if 'FROM memory_items WHERE id=:id AND workspace_id=:ws' in sql and sql.strip().upper().startswith('SELECT'):
            row = self.memory.get((params.get('id'), params.get('ws')))
            return _FakeResult(row=row)
        if 'FROM runs WHERE id=:id AND workspace_id=:ws' in sql:
            for run_id, ws, receipt in self.runs:
                if run_id == params.get('id') and ws == params.get('ws'):
                    return _FakeResult(fetch=(receipt,))
            return _FakeResult(fetch=None)
        if "receipt->'voice_profile'->>'id'" in sql:
            matched = [(run_id, receipt) for run_id, ws, receipt in self.runs
                       if ws == params.get('ws')]
            return _FakeResult(rows=matched)
        if sql.strip().upper().startswith('UPDATE runs SET receipt'):
            updated = 0
            revised = json.loads(params.get('receipt', '{}'))
            for index, (run_id, ws, _receipt) in enumerate(list(self.runs)):
                if run_id == params.get('id') and ws == params.get('ws'):
                    self.runs[index] = (run_id, ws, revised)
                    updated = 1
            return _FakeResult(rowcount=updated)
        if sql.strip().upper().startswith('DELETE FROM approvals'):
            return _FakeResult(rowcount=1)
        return _FakeResult(rowcount=1)


def _memory_row(item_id, workspace, kind='voice_profile'):
    return {
        'id': item_id, 'kind': kind, 'title': 'Synthetic voice',
        'content': _voice_content(['harbor']),
        'source_run_id': None,
        'created_at': '2026-10-29T00:00:00+00:00',
        'updated_at': '2026-10-29T00:00:00+00:00',
        'workspace_id': workspace,
    }


def _receipt(run_id, voice_id=None, status='completed', approval_state='pending_approval'):
    receipt = {
        'run_id': run_id, 'idea': 'Synthetic garden brief', 'status': status,
        'approval_state': approval_state, 'approvals': [],
        'approved_revision': None, 'approval_binding': {'version': 'approval-binding/v1', 'digest': 'd' * 64},
        'revision': 0, 'audit': {'event_log': []},
        'maker_draft_v2': {'post': 'Synthetic post', 'email': 'Synthetic email', 'claims': []},
        'checker_v2': {'blocked_count': 0, 'verified_count': 0, 'blocked_claims': [],
                       'revision_instructions': [], 'claim_results': [],
                       'supported_count': 0, 'unsupported_count': 0, 'conflicts_count': 0},
    }
    if voice_id is not None:
        receipt['voice_profile'] = {
            'id': voice_id, 'title': 'Synthetic voice', 'version': 'voice/v1:testdigest1234',
            'digest': 'e' * 64, 'example_count': 3, 'banned_term_count': 1,
            'banned_terms': ['harbor'], 'notice': 'style references only',
        }
    return receipt


class VoiceContentValidationTests(unittest.TestCase):
    def test_valid_synthetic_content_passes(self):
        snap = app_mod._validate_voice_content(_voice_content(['harbor']))
        self.assertEqual(len(snap['examples']), 3)
        self.assertEqual(snap['banned_terms'], ['harbor'])

    def test_invalid_shapes_rejected_422(self):
        for bad in ({'examples': []},
                    {'examples': _examples(), 'banned_terms': 'not-a-list'},
                    {'examples': [{'input': 'x'}]},
                    'not-a-dict'):
            with self.subTest(bad=bad), self.assertRaises(HTTPException) as ctx:
                app_mod._validate_voice_content(bad)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn('Invalid voice profile', ctx.exception.detail)


class VoiceSummaryDiffTests(unittest.TestCase):
    def test_summary_handles_present_missing_malformed(self):
        self.assertEqual(app_mod._voice_summary(_receipt('r1', 'mem_v1')),
                         ('mem_v1', 'Synthetic voice', 'voice/v1:testdigest1234'))
        self.assertEqual(app_mod._voice_summary(_receipt('r2', None)), (None, None, None))
        self.assertEqual(app_mod._voice_summary({}), (None, None, None))
        self.assertEqual(app_mod._voice_summary({'voice_profile': 'bad'}), (None, None, None))
        self.assertEqual(app_mod._voice_summary(
            {'voice_profile': {'id': 123, 'title': 456, 'version': 789}}), (None, None, None))

    def test_diff_marks_voice_changed(self):
        same_a = _receipt('run_a', 'mem_v1')
        same_b = _receipt('run_b', 'mem_v1')
        same = app_mod.diff_receipts(same_a, same_b)
        self.assertFalse(same['voice_changed'])
        self.assertEqual(same['voice_id_a'], 'mem_v1')
        self.assertEqual(same['voice_version_b'], 'voice/v1:testdigest1234')
        other = _receipt('run_b', 'mem_v2')
        other['voice_profile']['version'] = 'voice/v1:otherdigest5678'
        changed = app_mod.diff_receipts(same_a, other)
        self.assertTrue(changed['voice_changed'])
        self.assertEqual(changed['voice_id_b'], 'mem_v2')
        missing = app_mod.diff_receipts(same_a, _receipt('run_b', None))
        self.assertTrue(missing['voice_changed'])
        self.assertIsNone(missing['voice_id_b'])

    def test_rundiff_model_accepts_voice_fields(self):
        diff = app_mod.diff_receipts(_receipt('run_a', 'mem_v1'), _receipt('run_b', 'mem_v2'))
        model = app_mod.RunDiff(**diff)
        self.assertTrue(model.voice_changed)
        self.assertEqual(model.voice_id_a, 'mem_v1')
        legacy = {k: v for k, v in diff.items() if not k.startswith('voice_')}
        fallback = app_mod.RunDiff(**legacy)
        self.assertFalse(fallback.voice_changed)
        self.assertIsNone(fallback.voice_id_a)


class VoiceWorkspaceIsolationTests(unittest.TestCase):
    def test_workspace_mapping_keeps_actors_separate(self):
        self.assertEqual(store.workspace_for_actor('demo_placeholder'), 'demo')
        self.assertEqual(store.workspace_for_actor(''), 'demo')
        self.assertEqual(store.workspace_for_actor(None), 'demo')
        self.assertEqual(store.workspace_for_actor('synthetic_actor_a'), 'synthetic_actor_a')
        self.assertNotEqual(store.workspace_for_actor('synthetic_actor_a'),
                            store.workspace_for_actor('synthetic_actor_b'))

    def test_memory_voice_denied_across_workspaces(self):
        db = _FakeDB()
        db.memory[('mem_voice_a', 'synthetic_actor_a')] = _memory_row('mem_voice_a', 'synthetic_actor_a')
        found = app_mod.memory_item(db, 'mem_voice_a', 'synthetic_actor_a')
        self.assertEqual(found['id'], 'mem_voice_a')
        with self.assertRaises(HTTPException) as ctx:
            app_mod.memory_item(db, 'mem_voice_a', 'synthetic_actor_b')
        self.assertEqual(ctx.exception.status_code, 404)
        sql, params = db.calls[-1]
        self.assertIn('workspace_id=:ws', sql)
        self.assertEqual(params['ws'], 'synthetic_actor_b')

    def test_run_receipt_denied_across_workspaces(self):
        db = _FakeDB()
        db.runs.append(('run_a', 'synthetic_actor_a', _receipt('run_a', 'mem_v1')))
        found = app_mod.get_receipt(db, 'run_a', 'synthetic_actor_a')
        self.assertEqual(found['run_id'], 'run_a')
        with self.assertRaises(HTTPException) as ctx:
            app_mod.get_receipt(db, 'run_a', 'synthetic_actor_b')
        self.assertEqual(ctx.exception.status_code, 404)

    def test_memory_selection_propagates_denial(self):
        db = _FakeDB()
        db.memory[('mem_voice_a', 'synthetic_actor_a')] = _memory_row('mem_voice_a', 'synthetic_actor_a')
        with self.assertRaises(HTTPException) as ctx:
            app_mod.load_memory_selection(db, ['mem_voice_a'], 'synthetic_actor_b')
        self.assertEqual(ctx.exception.status_code, 404)


class VoiceInvalidationTests(unittest.TestCase):
    def _seeded_db(self):
        db = _FakeDB()
        owned_match = _receipt('run_owned', 'mem_voice')
        owned_match['approvals'] = [{'approved_by': 'synthetic_actor_a', 'action': 'x',
                                     'timestamp': '2026-10-29T00:00:00+00:00', 'revision': 0}]
        owned_match['approval_state'] = 'approved_for_export'
        owned_match['approved_revision'] = 0
        db.runs.append(('run_owned', 'synthetic_actor_a', owned_match))
        db.runs.append(('run_other_voice', 'synthetic_actor_a', _receipt('run_other_voice', 'mem_other')))
        db.runs.append(('run_failed', 'synthetic_actor_a',
                        _receipt('run_failed', 'mem_voice', status='failed')))
        db.runs.append(('run_cross_actor', 'synthetic_actor_b', _receipt('run_cross_actor', 'mem_voice')))
        db.runs.append(('run_nondict', 'synthetic_actor_a', 'not-a-dict'))
        return db

    def test_edit_invalidates_only_matching_completed_run(self):
        db = self._seeded_db()
        before_other = copy.deepcopy([r for i, w, r in db.runs if i == 'run_other_voice'][0])
        before_cross = copy.deepcopy([r for i, w, r in db.runs if i == 'run_cross_actor'][0])
        with patch('backend.app.store.audit') as audit:
            app_mod._invalidate_voice_runs(db, 'synthetic_actor_a', 'mem_voice', 'synthetic_actor_a', 'edited')
        by_id = {run_id: receipt for run_id, _ws, receipt in db.runs}
        revised = by_id['run_owned']
        self.assertTrue(revised['voice_stale'])
        self.assertEqual(revised['approvals'], [])
        self.assertIsNone(revised['approved_revision'])
        self.assertIsNone(revised['approval_binding'])
        self.assertEqual(revised['approval_state'], 'pending_approval')
        events = revised['audit']['event_log']
        self.assertEqual(events[-1]['step'], 'voice_invalidated')
        self.assertIn('edited', events[-1]['action'])
        self.assertIn('new human revision check is required', events[-1]['action'].lower())
        self.assertEqual(events[-1]['voice_id'], 'mem_voice')
        self.assertEqual(by_id['run_other_voice'], before_other)
        self.assertEqual(by_id['run_cross_actor'], before_cross)
        self.assertEqual(by_id['run_failed']['approval_state'], 'pending_approval')
        selects = [c for c in db.calls if "receipt->'voice_profile'->>'id'" in c[0]]
        self.assertTrue(selects)
        self.assertEqual(selects[0][1]['ws'], 'synthetic_actor_a')
        self.assertEqual(selects[0][1]['vid'], 'mem_voice')
        updates = [c for c in db.calls if c[0].strip().upper().startswith('UPDATE runs SET receipt')]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][1]['ws'], 'synthetic_actor_a')
        self.assertEqual(updates[0][1]['id'], 'run_owned')
        deletes = [c for c in db.calls if c[0].strip().upper().startswith('DELETE FROM approvals')]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0][1]['id'], 'run_owned')
        audit.assert_called_once_with(db, 'run_owned', 'voice_invalidated',
                                      'synthetic_actor_a', 'synthetic_actor_a')

    def test_delete_action_wording_and_revision_clear(self):
        db = self._seeded_db()
        with patch('backend.app.store.audit'):
            app_mod._invalidate_voice_runs(db, 'synthetic_actor_a', 'mem_voice', 'synthetic_actor_a', 'deleted')
        by_id = {run_id: receipt for run_id, _ws, receipt in db.runs}
        self.assertIn('deleted', by_id['run_owned']['audit']['event_log'][-1]['action'])

    def test_malformed_rows_are_skipped(self):
        db = _FakeDB()
        db.runs.append(('run_bad_voice', 'synthetic_actor_a', {'run_id': 'run_bad_voice',
                                                               'status': 'completed',
                                                               'voice_profile': 'bad'}))
        db.runs.append(('run_null_voice', 'synthetic_actor_a', {'run_id': 'run_null_voice',
                                                                'status': 'completed'}))
        with patch('backend.app.store.audit') as audit:
            app_mod._invalidate_voice_runs(db, 'synthetic_actor_a', 'mem_voice', 'synthetic_actor_a', 'edited')
        updates = [c for c in db.calls if c[0].strip().upper().startswith('UPDATE runs SET receipt')]
        self.assertEqual(updates, [])
        audit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
