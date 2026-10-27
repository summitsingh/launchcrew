"""Pipeline seam checks for the recovered partial backend."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from backend import adapter


class AdapterTests(TestCase):
    def test_preview_has_no_writes_or_model_calls(self):
        profile = adapter.agents.load_agent('Maker', adapter.ROOT / 'agents')
        with patch.object(Path, 'write_text', side_effect=AssertionError('write')), patch('launchcrew.run.spark_for_agent', side_effect=AssertionError('model')):
            result = adapter.preview(profile, 'Demo wallet')
        self.assertFalse(result['model_called'])
        self.assertFalse(result['side_effects'])

    def test_execute_captures_receipt_and_retains_checker(self):
        profile = adapter.agents.load_agent('Maker', adapter.ROOT / 'agents')
        with patch('launchcrew.run.spark_for_agent', side_effect=AssertionError('model')), patch('launchcrew.run.wonder_synthesize_for_scout', side_effect=AssertionError('model')), patch('launchcrew.receipts.save_receipt', side_effect=AssertionError('run file')):
            result = adapter.execute('recovered_test', 'Demo wallet', profile, True)
        self.assertEqual(result['approval_state'], 'pending_approval')
        self.assertGreater(result['checker_v1']['blocked_count'], 0)
        self.assertEqual(result['checker_v2']['blocked_count'], 0)
        self.assertEqual(result['approvals'], [])
