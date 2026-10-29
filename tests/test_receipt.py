import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from launchcrew import agents, spark
from launchcrew.receipts import REQUIRED_FIELDS, export_receipt, load_receipt
from launchcrew.run import run_pipeline
from launchcrew.wonder import wonder_synthesize_for_scout

ROOT = Path(__file__).resolve().parents[1]


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        old = agents.AGENTS_DIR
        self.addCleanup(setattr, agents, 'AGENTS_DIR', old)

    def run_demo(self, approve=False, seed=False):
        path = Path(self.temp.name) / 'demo.json'
        receipt = run_pipeline('Demo wallet', ROOT / 'facts/demo_facts.json', ROOT / 'agents', path, approve, seed)
        self.assertEqual(receipt, load_receipt(path))
        return receipt

    def test_pending_receipt_schema(self):
        receipt = self.run_demo()
        self.assertTrue(REQUIRED_FIELDS <= receipt.keys())
        self.assertFalse(receipt['summary']['submit_attempted'])
        self.assertFalse(receipt['summary']['submit_completed'])
        self.assertEqual(receipt['approval_state'], 'pending_approval')
        self.assertEqual(receipt['approvals'], [])
        self.assertEqual(receipt['visual_verification']['method'], 'not_run')
        self.assertEqual(receipt['model_usage']['spark_calls'], 0)
        with self.assertRaises(ValueError):
            export_receipt(receipt, Path(self.temp.name) / 'export.json')

    def test_seed_revision_and_approval(self):
        from launchcrew import human_review
        receipt = self.run_demo(False, True)
        self.assertEqual(receipt['checker_v1']['blocked_claims'], [{'claim': 'best in Texas', 'reason': 'Claim not found in facts file'}])
        self.assertEqual(receipt['checker_v2']['blocked_count'], 0)
        self.assertNotIn('best in Texas', json.dumps(receipt['maker_draft_v2']))
        self.assertTrue(receipt['summary']['revised'])
        self.assertEqual(receipt['approval_state'], 'pending_approval')
        # Bound approval happens after the receipt is prepared, so the
        # approval event follows receipt instead of preceding it.
        receipt = human_review.approve_current(receipt, 'demo_human')
        self.assertEqual(receipt['approval_state'], 'approved_for_export')
        self.assertEqual(receipt['approvals'][0]['approved_by'], 'demo_human')
        self.assertEqual(receipt['approval_binding']['version'],
                         human_review.APPROVAL_BINDING_VERSION)
        export_receipt(receipt, Path(self.temp.name) / 'export.json')
        steps = [e['step'] for e in receipt['audit']['event_log']]
        self.assertEqual(steps, ['deterministic_checks', 'scout', 'maker_draft_v1', 'checker_v1', 'maker_draft_v2', 'checker_v2', 'receipt', 'approval'])

    def test_cli_approve_binds_and_exports(self):
        import copy
        from launchcrew import human_review
        from launchcrew.receipts import create_receipt
        receipt = self.run_demo(True, False)
        self.assertEqual(receipt['approval_state'], 'approved_for_export')
        self.assertEqual(receipt['approvals'][0]['approved_by'], 'demo_human')
        self.assertEqual(receipt['approved_revision'], 0)
        binding = receipt.get('approval_binding')
        self.assertIsInstance(binding, dict)
        self.assertEqual(binding['version'], human_review.APPROVAL_BINDING_VERSION)
        self.assertEqual(len(binding['digest']), 64)
        self.assertEqual(receipt['approvals'][0]['binding_version'], binding['version'])
        self.assertEqual(receipt['approvals'][0]['binding_digest'], binding['digest'])
        self.assertTrue(human_review.exportable(receipt))
        self.assertEqual(receipt['mode'], 'demo_no_submit')
        self.assertFalse(receipt['summary']['submit_attempted'])
        self.assertFalse(receipt['summary']['submit_completed'])
        self.assertEqual(receipt['model_usage']['spark_calls'], 0)
        self.assertEqual(receipt['model_usage']['model_used'], 'none')
        out = Path(self.temp.name) / 'bound.json'
        export_receipt(receipt, out)
        exported = load_receipt(out)
        self.assertEqual(exported['exported_revision'], 0)
        self.assertEqual(exported['exported_draft']['post'], receipt['maker_draft_v2']['post'])
        self.assertEqual(exported['exported_draft']['email'], receipt['maker_draft_v2']['email'])
        steps = [e['step'] for e in receipt['audit']['event_log']]
        self.assertEqual(steps, ['deterministic_checks', 'scout', 'maker_draft_v1', 'checker_v1', 'maker_draft_v2', 'checker_v2', 'receipt', 'approval'])
        direct = create_receipt('probe', 'idea', receipt['scout'], receipt['maker_draft_v1'],
                                receipt['checker_v1'], receipt['maker_draft_v2'], receipt['checker_v2'],
                                [], receipt['model_usage'], True)
        self.assertEqual(direct['approval_state'], 'pending_approval')
        self.assertEqual(direct['approvals'], [])
        self.assertFalse(human_review.exportable(direct))
        historical = copy.deepcopy(receipt)
        historical['approval_binding'] = None
        historical['approvals'][-1].pop('binding_version', None)
        historical['approvals'][-1].pop('binding_digest', None)
        self.assertFalse(human_review.exportable(historical))
        with self.assertRaises(ValueError):
            export_receipt(historical, Path(self.temp.name) / 'historical.json')
        with self.assertRaisesRegex(ValueError, 'not pending approval'):
            human_review.approve_current(historical, 'demo_human', 0)
        revised = human_review.apply_revision(
            historical, 'Vegan leather wallet. Designed in Texas.',
            'For Austin commuters. $49.', 'demo_human', 0)
        self.assertEqual(revised['approval_state'], 'pending_approval')
        reapproved = human_review.approve_current(revised, 'demo_human', 1)
        self.assertTrue(human_review.exportable(reapproved))
        export_receipt(reapproved, Path(self.temp.name) / 'reapproved.json')

    def test_no_key_never_calls_network(self):
        with patch.object(spark, 'urlopen') as network:
            self.assertEqual(spark.call_spark_strict_json('a', 'b', {})['mode'], 'deterministic_fallback')
            self.assertIsNone(wonder_synthesize_for_scout('demo', lambda: None))
            network.assert_not_called()

    def test_transport_json_and_error_redaction(self):
        with patch.dict(os.environ, {'META_API_KEY': 'ENV_PLACEHOLDER'}):
            response = io.StringIO(json.dumps({'choices': [{'message': {'content': '{"facts_used": []}'}}]}))
            with patch.object(spark, 'urlopen', return_value=contextlib.closing(response)) as network:
                result = spark.call_spark_strict_json('system', 'demo', {'facts_used': []})
                self.assertEqual(result['mode'], 'spark')
                self.assertEqual(network.call_args.kwargs['timeout'], 30)
                payload = json.loads(network.call_args.args[0].data)
                self.assertEqual(payload['response_format']['type'], 'json_schema')
                self.assertTrue(payload['response_format']['json_schema']['strict'])
                self.assertEqual(payload['response_format']['json_schema']['schema']['required'], ['facts_used'])
            with patch.object(spark, 'urlopen', side_effect=ValueError('ENV_PLACEHOLDER')):
                result = spark.call_spark_strict_json('system', 'demo', {'facts_used': []})
                self.assertEqual(result['error_type'], 'ValueError')
                self.assertNotIn('ENV_PLACEHOLDER', json.dumps(result))

    def test_model_facts_filtered(self):
        synthesis = {'mode': 'spark', 'model_used': 'placeholder', 'attempted': True,
                     'raw_json': {'facts_used': ['best in Texas'], 'risks': []}}
        with patch.dict(os.environ, {'META_API_KEY': 'ENV_PLACEHOLDER'}), patch(
                'launchcrew.run.spark_for_agent', side_effect=[synthesis,
                    {'mode': 'deterministic_fallback', 'attempted': False},
                    {'mode': 'deterministic_fallback', 'attempted': False}]):
            receipt = self.run_demo()
        self.assertFalse(receipt['scout']['facts_used'][-1]['verified'])
        self.assertNotIn('best in Texas', receipt['maker_draft_v1']['claims'])
