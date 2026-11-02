"""Dropbox connector coverage: closed gate shape, names only.

Pure stdlib unittest for the domain module plus Postgres API tests
for the status and refusal routes. No network on any path; the
authorize and callback routes refuse before any transport exists.
"""

import unittest

from launchcrew import dropbox_import as dropbox_mod


class DomainTests(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(dropbox_mod.MODULE_VERSION, "dropbox-import/v1")
        self.assertEqual(dropbox_mod.CALLBACK_PATH, "/api/dropbox-import/callback")
        self.assertEqual(list(dropbox_mod.SETUP_NAMES),
                         ["DROPBOX_CLIENT_ID", "DROPBOX_CLIENT_SECRET", "PUBLIC_BASE_URL"])

    def test_unconfigured_by_default(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            for name in dropbox_mod.SETUP_NAMES:
                os.environ.pop(name, None)
            self.assertFalse(dropbox_mod.dropbox_configured())
            status = dropbox_mod.status_dict()
            self.assertFalse(status["available"])
            self.assertFalse(status["configured"])
            self.assertFalse(status["live_verified"])
            self.assertEqual(status["reason"], "dropbox_not_configured")
            missing = dropbox_mod.missing_setup_names()
            for name in dropbox_mod.SETUP_NAMES:
                self.assertIn(name, missing)

    def test_configured_state_never_leaks_values(self):
        import json
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"DROPBOX_CLIENT_ID": "fixture-id",
                                     "DROPBOX_CLIENT_SECRET": "fixture-secret"}):
            self.assertTrue(dropbox_mod.dropbox_configured())
            text = json.dumps(dropbox_mod.status_dict())
            self.assertNotIn("fixture-id", text)
            self.assertNotIn("fixture-secret", text)

    def test_callback_uri_shape(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://example.invalid"}):
            self.assertEqual(dropbox_mod.callback_uri(),
                             "https://example.invalid/api/dropbox-import/callback")


if __name__ == "__main__":
    unittest.main()
