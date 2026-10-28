from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.scan_repo import CHECKS, scan_repo


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/scan_repo.py'


class ScanTests(unittest.TestCase):
    def scan_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.txt'
            path.write_text(text, encoding='utf-8')
            result = subprocess.run([sys.executable, str(SCRIPT), directory],
                                    capture_output=True, text=True, check=False)
        return result

    def test_clean_file_passes(self):
        result = self.scan_text('LaunchCrew demo data, approval plus export only.\n')
        self.assertEqual(result.returncode, 0)
        self.assertIn('Scan result: pass', result.stdout)

    def test_em_dash_fails(self):
        result = self.scan_text('Demo ' + chr(0x2014) + ' content')
        self.assertEqual(result.returncode, 1)
        self.assertIn('sample.txt:1: em_dash', result.stdout)

    def test_legacy_brand_fails(self):
        result = self.scan_text('cOmPaNy' + ' oS')
        self.assertEqual(result.returncode, 1)
        self.assertIn('sample.txt:1: legacy_brand', result.stdout)

    def test_fake_secret_fails_without_value_output(self):
        # Fake token prefixes and values, assembled only for temporary fixtures.
        for prefix in ('AK' + 'IA', 'gh' + 'p_', 'gh' + 'o_', 's' + 'k-'):
            with self.subTest(prefix_type=prefix[:2]):
                value = prefix + 'FAKE_TEST_ONLY'
                result = self.scan_text(value)
                self.assertEqual(result.returncode, 1)
                self.assertIn('sample.txt: secret', result.stdout)
                self.assertNotIn(value, result.stdout + result.stderr)

    def test_sensitive_patterns_and_redaction(self):
        # All fixtures are synthetic, fake contact and assignment data only.
        cases = {
            'email': 'demo' + '@' + 'example.invalid',
            'phone': '(' + '202' + ') ' + '555' + '-' + '0123',
            'street_address': '123' + ' Example Street',
            'secret': 'DEMO_API_KEY' + ' = ' + 'FAKE_TEST_ONLY_VALUE_12345',
            'personal_name': 'Summit' + ' Singh',
        }
        for check, value in cases.items():
            with self.subTest(check=check):
                result = self.scan_text(value)
                self.assertEqual(result.returncode, 1)
                self.assertIn('sample.txt: ' + check, result.stdout)
                self.assertNotIn(value, result.stdout + result.stderr)

    def test_us_phone_formats(self):
        digits = '202' + '555' + '0123'
        for value in (digits, '+1 ' + digits, '202' + '-555' + '-0123',
                      '202' + '.555' + '.0123', '202' + ' 555' + ' 0123'):
            with self.subTest(format_length=len(value)):
                self.assertIsNotNone(CHECKS['phone'].search(value))

    def test_exclusions_and_copied_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('.git', '__pycache__'):
                (root / name).mkdir()
                (root / name / 'ignored.txt').write_text(chr(0x2014), encoding='utf-8')
            self.assertEqual(scan_repo(root), [])
            (root / 'copy.py').write_text(
                '# Allowlist: ' + 'Summit' + ' Singh, ' + 'summit' + 'singh',
                encoding='utf-8')
            self.assertEqual([hit[1] for hit in scan_repo(root)], ['personal_name'])

    def test_missing_root_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            findings = scan_repo(Path(directory) / 'missing')
            self.assertEqual([hit[1] for hit in findings], ['read_error'])

    def test_scan_script_path_exemption(self):
        script = SCRIPT
        self.assertNotIn('summit' + 'singh', script.read_text().lower())
        self.assertNotIn('summit' + ' singh', script.read_text().lower())
        self.assertEqual(scan_repo(script.parent), [])
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / 'scan_repo.py'
            copied.write_text('summit' + 'singh')
            self.assertEqual([r[1] for r in scan_repo(directory)], ['personal_name'])

    def test_package_versions_are_not_email_addresses(self):
        for value in ('pnpm@10.20.0', 'react@19.1.4', '@tanstack/react-query@5.90.5'):
            self.assertIsNone(CHECKS['email'].search(value))
        self.assertIsNotNone(CHECKS['email'].search('demo' + '@' + 'example.invalid'))

    def test_dependency_cache_excluded_source_still_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'node_modules').mkdir()
            (root / 'node_modules' / 'vendor.txt').write_text(chr(0x2014))
            (root / 'app.py').write_text(chr(0x2014))
            findings = scan_repo(root)
            self.assertEqual([(p.name, kind) for p, kind, _ in findings], [('app.py', 'em_dash')])
