import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from launchcrew.facts import check_draft, load_facts
from launchcrew.receipts import export_receipt, load_receipt
from launchcrew.run import run_pipeline
from launchcrew.web import create_server
from scripts import verify_meta

ROOT = Path(__file__).resolve().parents[1]


class HardeningTests(unittest.TestCase):
    def test_sentence_guards(self):
        facts, _ = load_facts(ROOT / 'facts/demo_facts.json')
        for sentence in ('Perfect wallet', '$59', 'Designed in Texas and waterproof',
                         'best in Texas', '50', '2026-11-01', '49%', 'Launch January 12', '$49.99'):
            with self.subTest(sentence=sentence):
                self.assertTrue(check_draft(sentence, facts))
        for sentence in facts['approved_claims']:
            self.assertEqual(check_draft(sentence + '.', facts), [])
        wrong_price = check_draft('$59', facts)[0]
        self.assertEqual(wrong_price['reason'], 'Conflicting price value')
        self.assertEqual(wrong_price['verdict'], 'conflicts')
        self.assertEqual(wrong_price['evidence'], '$49')
        custom = {'approved_claims': ['$49.99', 'Perfect wallet'], 'sources': ['demo']}
        self.assertEqual(check_draft('$49.99. Perfect wallet.', custom), [])

    def test_partial_failure_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            facts = Path(directory) / 'bad.json'
            facts.write_text('{"Authorization": "FAKE_PRIVATE_TEST"}')
            out = Path(directory) / 'partial.json'
            with self.assertRaises(ValueError), patch.dict(os.environ, {'META_API_KEY': ''}):
                run_pipeline('Demo', facts, ROOT / 'agents', out)
            receipt = load_receipt(out)
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(receipt['audit']['stopped_reason'], 'load_facts')
            self.assertNotIn('Authorization', out.read_text())
            self.assertNotIn('FAKE_PRIVATE_TEST', out.read_text())
            with self.assertRaises(ValueError):
                export_receipt(receipt, Path(directory) / 'export.json')
            result = subprocess.run([sys.executable, '-m', 'launchcrew.run', '--idea', 'Demo',
                                     '--facts', str(facts), '--out', str(out)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.strip(), 'LaunchCrew stopped: ValueError')
            self.assertEqual(result.stdout, '')

    def test_mid_pipeline_failure_retains_only_completed_events(self):
        with tempfile.TemporaryDirectory() as directory, patch('launchcrew.run.make_draft', side_effect=RuntimeError('FAKE_PRIVATE_TEST')):
            out = Path(directory) / 'partial.json'
            with patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''}), self.assertRaises(RuntimeError):
                run_pipeline('Demo', ROOT / 'facts/demo_facts.json', ROOT / 'agents', out)
            receipt = load_receipt(out)
            self.assertEqual(receipt['completed_steps'], ['deterministic_checks', 'scout'])
            self.assertEqual(receipt['audit']['stopped_reason'], 'maker_draft_v1')
            self.assertNotIn('FAKE_PRIVATE_TEST', out.read_text())

    def test_final_block_writes_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch('launchcrew.run.check_pack', return_value={'blocked_count': 1}):
            out = Path(directory) / 'partial.json'
            with patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''}), self.assertRaises(ValueError):
                run_pipeline('Demo', ROOT / 'facts/demo_facts.json', ROOT / 'agents', out)
            self.assertEqual(load_receipt(out)['status'], 'failed')

    def test_verifier_requires_live_and_redacts(self):
        for key in ('', 'FAKE_PRIVATE_TEST'):
            with patch.dict(os.environ, {'META_API_KEY': key}), patch('launchcrew.spark.urlopen') as network:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(verify_meta.main([]), 0)
                network.assert_not_called()
                self.assertNotIn('FAKE_PRIVATE_TEST', output.getvalue())
        with patch.dict(os.environ, {'META_API_KEY': ''}), patch('launchcrew.spark.urlopen') as network:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify_meta.main(['--live']), 0)
            network.assert_not_called()

    def test_verifier_live_mock_checks_facts_and_usage(self):
        response = {'mode': 'spark', 'raw_json': {'facts_used': ['$49']}, 'usage': {'total_tokens': 12}}
        with patch.dict(os.environ, {'META_API_KEY': 'FAKE_PRIVATE_TEST'}), patch.object(verify_meta, 'call_spark_strict_json', return_value=response) as call:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(verify_meta.main(['--live']), 0)
            call.assert_called_once()
            self.assertIn('total_tokens: 12', output.getvalue())
            self.assertNotIn('FAKE_PRIVATE_TEST', output.getvalue())
            response['raw_json']['facts_used'] = ['Waterproof']
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify_meta.main(['--live']), 1)



class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('agents', 'facts'):
            shutil.copytree(ROOT / name, self.root / name)
        self.env = patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.server = create_server(port=0, root=self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read().decode()
        connection.close()
        return result

    def create_run(self):
        status, headers, _ = self.request('POST', '/run', urlencode({'idea': 'Vegan leather wallet, $49, for Austin commuters'}))
        self.assertEqual(status, 303)
        return headers['Location']

    def test_form_and_approval_export_flow(self):
        status, _, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        for label in ('Scout', 'Maker', 'Checker', 'Demo facts'):
            self.assertIn(label, body)
        path = self.create_run()
        self.assertEqual(self.request('GET', path)[0], 200)
        self.assertEqual(self.request('GET', path + '/export')[0], 403)
        self.assertEqual(self.request('POST', path + '/approve')[0], 200)
        self.assertEqual(self.request('POST', path + '/approve')[0], 400)
        status, headers, body = self.request('GET', path + '/export')
        self.assertEqual(status, 200)
        self.assertIn('attachment', headers['Content-Disposition'])
        receipt = json.loads(body)
        self.assertEqual(receipt['approval_state'], 'approved_for_export')
        self.assertEqual(receipt['approvals'][0]['approved_by'], 'web_human')
        self.assertFalse(receipt['summary']['submit_attempted'])
        self.assertEqual(self.request('GET', path + '/receipt.json')[0], 200)

    def test_blocked_or_failed_approval_refused(self):
        path = self.create_run()
        file = self.root / 'runs' / (path.rsplit('/', 1)[1] + '.json')
        receipt = load_receipt(file)
        receipt['checker_v2']['blocked_count'] = 1
        file.write_text(json.dumps(receipt))
        self.assertEqual(self.request('POST', path + '/approve')[0], 400)
        receipt['checker_v2']['blocked_count'] = 0
        receipt['status'] = 'failed'
        file.write_text(json.dumps(receipt))
        self.assertEqual(self.request('POST', path + '/approve')[0], 400)
        self.assertEqual(self.request('GET', path + '/export')[0], 403)

    def test_cross_origin_and_path_refused(self):
        self.assertEqual(self.request('POST', '/run', 'idea=demo', {'Origin': 'https://example.invalid'})[0], 403)
        self.assertEqual(self.request('GET', '/run/../../facts/demo_facts.json')[0], 404)


class InMemoryWebTests(WebTests):
    """Exercise real HTTP parsing and response serialization without OS sockets.

    These supplement the required localhost integration tests, never replace them.
    """
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('agents', 'facts'):
            shutil.copytree(ROOT / name, self.root / name)
        self.env = patch.dict(os.environ, {'META_API_KEY': '', 'META_WONDER_MODEL': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        with patch('launchcrew.web.HTTPServer') as server:
            create_server(root=self.root)
            self.handler = server.call_args.args[1]

    def request(self, method, path, body=None, headers=None):
        body = (body or '').encode()
        headers = {'Host': '127.0.0.1', 'Content-Length': str(len(body)), **(headers or {})}
        raw = method + ' ' + path + ' HTTP/1.0\r\n'
        raw += ''.join(k + ': ' + v + '\r\n' for k, v in headers.items())
        incoming = io.BytesIO(raw.encode() + b'\r\n' + body)
        outgoing = io.BytesIO()

        class Connection:
            def makefile(self, *args):
                return incoming

            def sendall(self, data):
                outgoing.write(data)

        self.handler(Connection(), ('127.0.0.1', 0), object())
        head, content = outgoing.getvalue().split(b'\r\n\r\n', 1)
        lines = head.decode().split('\r\n')
        response_headers = dict(line.split(': ', 1) for line in lines[1:])
        return int(lines[0].split()[1]), response_headers, content.decode()
