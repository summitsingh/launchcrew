"""Static wiring for the disposable candidate verifier.

Socket-free and offline only. Guards the two settings that caused the
browser run to fail saves with 403 while direct API health passed:

- the frontend build must bake API_URL from the isolated API port, and the
  Next rewrite must read that same env value;
- the disposable API must trust exactly the isolated web origin via
  PUBLIC_BASE_URL, never a wildcard and never a disabled check.

Foreign-origin refusal itself stays covered by backend/tests/test_api.py.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'verify-release-candidate.sh'
NEXT_CONFIG = ROOT / 'web' / 'next.config.ts'
APP = ROOT / 'backend' / 'app.py'


class VerifierOriginTests(unittest.TestCase):
    def test_build_bakes_isolated_api_url(self):
        text = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('EXPECTED_API_URL="http://127.0.0.1:$API_PORT"', text)
        self.assertIn('API_URL="$EXPECTED_API_URL" pnpm --dir web build', text)
        config = NEXT_CONFIG.read_text(encoding='utf-8')
        self.assertIn('process.env.API_URL', config)
        self.assertIn('/api/:path*', config)

    def test_backend_trusts_exact_isolated_web_origin(self):
        text = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('EXPECTED_WEB_URL="http://127.0.0.1:$WEB_PORT"', text)
        self.assertIn('PUBLIC_BASE_URL="$EXPECTED_WEB_URL"', text)
        self.assertNotIn('PUBLIC_BASE_URL="*"', text)
        self.assertNotIn("PUBLIC_BASE_URL='*'", text)

    def test_origin_check_not_disabled(self):
        app = APP.read_text(encoding='utf-8')
        self.assertIn('Cross-origin mutation refused', app)
        script = SCRIPT.read_text(encoding='utf-8')
        self.assertNotIn('AUTH_ENABLED=true', script)


if __name__ == '__main__':
    unittest.main()
