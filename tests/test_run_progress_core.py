"""Offline core proofs for incremental stage receipts.

No database, no network, no credentials. These prove the pipeline
itself emits one honest callback per real stage boundary, in pipeline
order, and that a barrier before a later stage holds that stage while
earlier completions are already recorded.
"""
import os
import threading
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from launchcrew import run
from launchcrew.receipts import pending_receipt

ROOT = Path(__file__).resolve().parents[1]
ORDER = ['deterministic_checks', 'scout', 'maker_draft_v1', 'checker_v1',
         'maker_draft_v2', 'checker_v2', 'receipt']


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''})
        env.start()
        self.addCleanup(env.stop)

    def run_demo(self, **kwargs):
        path = Path(self.temp.name) / 'demo.json'
        kwargs.setdefault('progress', None)
        return run.run_pipeline('Demo wallet', ROOT / 'facts/demo_facts.json',
                                ROOT / 'agents', path, **kwargs), path

    def test_progress_follows_real_stage_order(self):
        seen = []
        receipt, _ = self.run_demo(progress=lambda event: seen.append(event))
        completed = [event['stage'] for event in seen if event['state'] == 'completed']
        self.assertEqual(completed, ORDER)
        started = [event['stage'] for event in seen if event['state'] == 'started']
        self.assertEqual(started, ORDER)
        for event in seen:
            self.assertTrue(event['timestamp'])
            self.assertTrue(event['profile'])
            for value in event['evidence'].values():
                self.assertIsInstance(value, (bool, int, float, str, type(None)))
        final = [event for event in seen if event['stage'] == 'checker_v2' and event['state'] == 'completed'][0]
        self.assertEqual(final['evidence']['blocked_count'], receipt['checker_v2']['blocked_count'])

    def test_barrier_holds_later_stage_after_earlier_completion(self):
        seen = []
        lock = threading.Lock()
        release = threading.Event()

        def gate(stage):
            if stage == 'maker_draft_v1':
                self.assertTrue(release.wait(timeout=30.0))

        def progress(event):
            with lock:
                seen.append(event)

        holder = {}
        worker = threading.Thread(
            target=lambda: holder.setdefault(
                'receipt', run.run_pipeline('Demo wallet', ROOT / 'facts/demo_facts.json',
                                            ROOT / 'agents', Path(self.temp.name) / 'demo.json',
                                            progress=progress, stage_gate=gate)),
            daemon=True)
        worker.start()
        deadline = time.time() + 30.0
        while time.time() < deadline:
            with lock:
                done = [event['stage'] for event in seen if event['state'] == 'completed']
            if 'scout' in done:
                break
            time.sleep(0.02)
        with lock:
            done = [event['stage'] for event in seen if event['state'] == 'completed']
        self.assertIn('scout', done)
        self.assertNotIn('maker_draft_v1', done)
        release.set()
        worker.join(timeout=30.0)
        self.assertFalse(worker.is_alive())
        with lock:
            done = [event['stage'] for event in seen if event['state'] == 'completed']
        self.assertEqual(done, ORDER)

    def test_gate_failure_writes_failed_receipt(self):
        written = []

        def gate(stage):
            if stage == 'checker_v1':
                raise RuntimeError('Simulated checker outage')

        with self.assertRaises(RuntimeError):
            self.run_demo(progress=lambda event: None, stage_gate=gate,
                          receipt_writer=lambda receipt, path: written.append(receipt))
        self.assertEqual(len(written), 1)
        failure = written[0]
        self.assertEqual(failure['status'], 'failed')
        self.assertIn('scout', failure['completed_steps'])
        self.assertIn('maker_draft_v1', failure['completed_steps'])
        self.assertEqual(failure['audit']['stopped_reason'], 'checker_v1')


class PendingReceiptTests(unittest.TestCase):
    def test_pending_receipt_is_not_approvable(self):
        pending = pending_receipt('run_demo', 'Demo wallet', {'scout': 'Scout'})
        self.assertEqual(pending['status'], 'running')
        self.assertEqual(pending['approval_state'], 'pending_approval')
        self.assertIsNone(pending['maker_draft_v2'])
        self.assertIsNone(pending['checker_v2'])
        self.assertIsNone(pending['scout'])
        self.assertEqual(pending['approvals'], [])


if __name__ == '__main__':
    unittest.main()
