"""Offline readiness-gate tests: no DB, no network, no credentials."""

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launchcrew import readiness, run

ROOT = Path(__file__).resolve().parents[1]


def _approved_receipt(tmpdir):
    path = Path(tmpdir) / 'demo.json'
    with patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''}):
        return run.run_pipeline('Demo wallet', ROOT / 'facts/demo_facts.json',
                                ROOT / 'agents', path, True, False)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_approved_receipt_is_ready(self):
        receipt = _approved_receipt(self.temp.name)
        summary = readiness.readiness_of(receipt)
        self.assertEqual(summary['facts']['status'], 'pass')
        self.assertEqual(summary['facts']['confirmed_count'],
                         len(receipt['product_facts']['confirmed_claims']))
        self.assertIsNone(summary['facts']['reason'])
        self.assertEqual(summary['checker']['status'], 'pass')
        self.assertEqual(summary['checker']['blocked_count'], 0)
        self.assertEqual(summary['checker']['verified_count'],
                         receipt['checker_v2']['verified_count'])
        self.assertIsNone(summary['checker']['reason'])
        self.assertEqual(summary['approval']['status'], 'current')
        self.assertTrue(summary['approval']['bound'])
        self.assertEqual(summary['approval']['reason'], '')
        self.assertEqual(summary['photo']['status'], 'pass')
        self.assertEqual(summary['photo']['state'], 'no_photo')
        self.assertEqual(summary['export']['status'], 'pass')
        self.assertTrue(summary['export']['exportable'])
        self.assertIsNone(summary['export']['reason'])
        self.assertTrue(summary['ready'])

    def test_facts_gate_fails_closed(self):
        receipt = _approved_receipt(self.temp.name)
        missing = copy.deepcopy(receipt)
        del missing['product_facts']
        summary = readiness.readiness_of(missing)
        self.assertEqual(summary['facts']['status'], 'blocked')
        self.assertEqual(summary['facts']['confirmed_count'], 0)
        self.assertEqual(summary['facts']['reason'],
                         'Approval binding requires product-facts provenance')
        self.assertFalse(summary['ready'])
        wrong_type = copy.deepcopy(receipt)
        wrong_type['product_facts']['confirmed_claims'] = 'not-a-list'
        summary = readiness.readiness_of(wrong_type)
        self.assertEqual(summary['facts']['status'], 'blocked')
        self.assertEqual(summary['facts']['reason'], 'Confirmed claims must be a list')
        self.assertFalse(summary['ready'])
        empty = copy.deepcopy(receipt)
        empty['product_facts']['confirmed_claims'] = []
        summary = readiness.readiness_of(empty)
        self.assertEqual(summary['facts']['status'], 'blocked')
        self.assertEqual(summary['facts']['confirmed_count'], 0)
        self.assertEqual(summary['facts']['reason'],
                         'Run has no verified fact snapshot to recheck against')
        self.assertFalse(summary['ready'])

    def test_checker_gate_reports_verdict_summary(self):
        receipt = _approved_receipt(self.temp.name)
        blocked = copy.deepcopy(receipt)
        blocked['checker_v2']['blocked_count'] = 1
        summary = readiness.readiness_of(blocked)
        self.assertEqual(summary['checker']['status'], 'blocked')
        self.assertEqual(summary['checker']['blocked_count'], 1)
        self.assertEqual(summary['checker']['reason'],
                         'Approval requires a clean final check')
        self.assertFalse(summary['ready'])
        missing = copy.deepcopy(receipt)
        del missing['checker_v2']
        summary = readiness.readiness_of(missing)
        self.assertEqual(summary['checker']['status'], 'blocked')
        self.assertEqual(summary['checker']['reason'],
                         'Approval binding requires a Checker result')
        self.assertFalse(summary['ready'])
        malformed = copy.deepcopy(receipt)
        malformed['checker_v2']['blocked_count'] = True
        summary = readiness.readiness_of(malformed)
        self.assertEqual(summary['checker']['status'], 'blocked')
        self.assertEqual(summary['checker']['reason'],
                         'Run has no complete draft context to revise')
        self.assertFalse(summary['ready'])

    def test_approval_gate_current_and_stale(self):
        receipt = _approved_receipt(self.temp.name)
        self.assertEqual(readiness.readiness_of(receipt)['approval']['status'], 'current')
        tampered = copy.deepcopy(receipt)
        tampered['approval_binding']['digest'] = '0' * 64
        summary = readiness.readiness_of(tampered)
        self.assertEqual(summary['approval']['status'], 'stale')
        self.assertFalse(summary['approval']['bound'])
        self.assertIn('binding', summary['approval']['reason'].lower())
        self.assertFalse(summary['ready'])
        historical = copy.deepcopy(receipt)
        historical['approval_binding'] = None
        summary = readiness.readiness_of(historical)
        self.assertEqual(summary['approval']['status'], 'stale')
        self.assertEqual(summary['approval']['reason'],
                         'Approval binding missing; historical approvals require a new approval')
        self.assertFalse(summary['ready'])

    def test_photo_gate_states(self):
        receipt = _approved_receipt(self.temp.name)
        pending = copy.deepcopy(receipt)
        pending['photo_status'] = {'state': 'requested_unchecked', 'label': None,
                                   'reason': 'not_run: x',
                                   'policy_version': 'photo-geometry/v1',
                                   'revision': 0, 'actor': '', 'checked_at': ''}
        summary = readiness.readiness_of(pending)
        self.assertEqual(summary['photo']['status'], 'blocked')
        self.assertEqual(summary['photo']['state'], 'requested_unchecked')
        self.assertEqual(summary['photo']['reason'],
                         'Photo blocks approval and export (not_run: x); '
                         'remove the photo or check a better one')
        self.assertFalse(summary['ready'])
        detected = copy.deepcopy(receipt)
        detected['photo_status'] = {'state': 'checked', 'label': 'detected',
                                    'reason': 'clear_single',
                                    'policy_version': 'photo-geometry/v1',
                                    'revision': 0, 'actor': 'a', 'checked_at': 't'}
        summary = readiness.readiness_of(detected)
        self.assertEqual(summary['photo']['status'], 'pass')
        self.assertEqual(summary['photo']['state'], 'checked')
        unknown = copy.deepcopy(receipt)
        unknown['photo_status'] = {'state': 'mystery', 'label': 'detected',
                                   'reason': 'x', 'policy_version': 'photo-geometry/v1',
                                   'revision': 0, 'actor': '', 'checked_at': ''}
        summary = readiness.readiness_of(unknown)
        self.assertEqual(summary['photo']['status'], 'blocked')
        self.assertFalse(summary['ready'])

    def test_export_gate_state(self):
        receipt = _approved_receipt(self.temp.name)
        self.assertEqual(readiness.readiness_of(receipt)['export'],
                         {'status': 'pass', 'exportable': True, 'reason': None})
        pending = copy.deepcopy(receipt)
        pending['approval_state'] = 'pending_approval'
        summary = readiness.readiness_of(pending)
        self.assertEqual(summary['export']['status'], 'blocked')
        self.assertFalse(summary['export']['exportable'])
        self.assertEqual(summary['export']['reason'],
                         'Export requires approval of the latest revision and a clean final check')
        self.assertFalse(summary['ready'])

    def test_missing_keys_fail_closed_without_raising(self):
        for bad in ({}, {'status': 'completed'}):
            summary = readiness.readiness_of(bad)
            self.assertEqual(summary['facts']['status'], 'blocked')
            self.assertEqual(summary['checker']['status'], 'blocked')
            self.assertEqual(summary['approval']['status'], 'stale')
            self.assertEqual(summary['export']['status'], 'blocked')
            self.assertFalse(summary['ready'])
        # Absent photo status keeps the no-photo legacy default, which
        # passes on its own; every other gate still fails closed.
        self.assertEqual(readiness.readiness_of({})['photo']['state'], 'no_photo')
        for bad in (None, []):
            summary = readiness.readiness_of(bad)
            self.assertEqual(summary['facts']['status'], 'blocked')
            self.assertEqual(summary['checker']['status'], 'blocked')
            self.assertEqual(summary['approval']['status'], 'stale')
            self.assertEqual(summary['photo']['status'], 'blocked')
            self.assertEqual(summary['export']['status'], 'blocked')
            self.assertFalse(summary['ready'])

    def test_readiness_does_not_mutate_receipt(self):
        receipt = _approved_receipt(self.temp.name)
        before = copy.deepcopy(receipt)
        readiness.readiness_of(receipt)
        self.assertEqual(receipt, before)


if __name__ == '__main__':
    unittest.main()
