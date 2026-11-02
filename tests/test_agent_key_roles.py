"""Seat key role coverage: pure role and scope matrix only.

No DB, no network. Stdlib unittest.
"""

import unittest

from launchcrew import agent_surfaces as surfaces_mod


class RoleTests(unittest.TestCase):
    def test_roles(self):
        self.assertEqual(surfaces_mod.KEY_ROLES, ('owner', 'editor', 'viewer'))
        for role in surfaces_mod.KEY_ROLES:
            self.assertEqual(surfaces_mod.normalize_key_role(role), role)
        self.assertEqual(surfaces_mod.normalize_key_role('  editor  '), 'editor')

    def test_invalid_roles_raise(self):
        for bad in ('admin', '', None, 0, True, ['viewer']):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    surfaces_mod.normalize_key_role(bad)


class ScopeMatrixTests(unittest.TestCase):
    def test_viewer_is_read_only(self):
        for scope in surfaces_mod.READ_SCOPES:
            with self.subTest(scope=scope):
                self.assertTrue(surfaces_mod.scope_allowed_for_role(scope, 'viewer'))
        for scope in surfaces_mod.WRITE_SCOPES:
            with self.subTest(scope=scope):
                self.assertFalse(surfaces_mod.scope_allowed_for_role(scope, 'viewer'))

    def test_editor_and_owner_keep_all_scopes(self):
        for role in ('editor', 'owner'):
            for scope in surfaces_mod.DEFAULT_SCOPES:
                with self.subTest(role=role, scope=scope):
                    self.assertTrue(surfaces_mod.scope_allowed_for_role(scope, role))

    def test_unknown_scope_never_allowed(self):
        for role in surfaces_mod.KEY_ROLES:
            self.assertFalse(surfaces_mod.scope_allowed_for_role('nope', role))

    def test_bad_role_raises(self):
        with self.assertRaises(ValueError):
            surfaces_mod.scope_allowed_for_role('accounts', 'admin')


if __name__ == '__main__':
    unittest.main()
