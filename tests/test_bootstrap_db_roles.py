"""Offline bootstrap database-role job tests with a fake database driver.

No test contacts a database or AWS. A stub psycopg module records statements
and returns canned rows, so bind ordering, parameterized passwords, exact
owned roles, privilege split, and redacted failures are proven without a live
secret. Static checks guard the source boundaries: secrets enter only through
environment memory, values are never printed, and TLS stays fail-closed.
"""
import contextlib
import importlib.util
import io
import os
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_db_roles.py"
SQL_FILE = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "db-roles.sql"

RT_PW = "s3ntinel-runtime-pw-9x"
MG_PW = "s3ntinel-migration-pw-9x"


def runtime_url():
    return f"postgresql://launchcrew_runtime:{RT_PW}@dbhost:5432/launchcrew?sslmode=verify-full"


def migration_url():
    return f"postgresql://launchcrew_migration:{MG_PW}@dbhost:5432/launchcrew?sslmode=verify-full"


class FakeError(Exception):
    def __init__(self, message, sqlstate=None):
        super().__init__(message)
        self.sqlstate = sqlstate


class FakeCursor:
    def __init__(self, state, user=None, dbname=None, conn=None):
        self.state = state
        self.user = user
        self.dbname = dbname
        self.conn = conn
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.state.statements.append((sql, params))
        lowered = sql.strip().lower()
        if "model_budget" in lowered or "model_calls" in lowered:
            if lowered.startswith(("insert into", "update ", "delete from")):
                if self.state.model_direct_allow:
                    self.rowcount = 1
                    return None
                raise FakeError("permission denied for model relation",
                                sqlstate=self.state.model_direct_sqlstate)
        if lowered.startswith("create database"):
            try:
                saw = self.conn.autocommit if self.conn is not None else None
            except Exception:
                saw = None
            self.state.create_saw_autocommit.append(saw)
            self.state.create_attempts += 1
            if self.state.fail_create:
                raise FakeError("simulated create failure",
                                sqlstate=self.state.create_sqlstate)
            self.state.database_owner = self.user
            self.rowcount = 0
            return None
        if self.state.fail_on_password and "with password" in lowered:
            raise FakeError("simulated password bind failure")
        if lowered.startswith("create table") and self.state.refuse_ddl:
            raise FakeError("permission denied for schema public",
                            sqlstate=self.state.ddl_sqlstate)
        if lowered.startswith("alter table") and self.state.refuse_ddl:
            raise FakeError("permission denied for schema public",
                            sqlstate=self.state.ddl_sqlstate)
        if lowered.startswith("drop table") and self.state.refuse_ddl:
            raise FakeError("permission denied for schema public",
                            sqlstate=self.state.ddl_sqlstate)
        if "pg_roles" in lowered and "rolname" in lowered:
            return None
        self.rowcount = 1
        return None

    def fetchone(self):
        sql, params = self.state.statements[-1]
        lowered = sql.strip().lower()
        if "model_budget" in lowered and "remaining_micros" in lowered:
            if self.state.model_budget_missing:
                return None
            return (self.state.model_budget_remaining,)
        if "pg_auth_members" in lowered:
            return (1,) if self.state.role_memberships else None
        if "pg_shdescription" in lowered:
            if self.state.role_comment is None:
                return None
            return (self.state.role_comment,)
        if "pg_namespace" in lowered and "nspowner" in lowered:
            if self.state.schema_owner is None:
                return None
            return (self.state.schema_owner,)
        if "pg_database" in lowered and "datdba" in lowered:
            if self.state.database_owner is None:
                return None
            return (self.state.database_owner,)
        if "pg_roles" in lowered and "rolname" in lowered:
            if lowered.startswith("select oid"):
                queried = params[0] if params else None
                if queried == "launchcrew_runtime":
                    return (self.state.runtime_oid,)
                if queried in self.state.role_rows:
                    row = self.state.role_rows[queried]
                    return (row[0],) if row else None
                return (self.state.runtime_oid,)
            queried = params[0] if params else None
            if queried in self.state.role_rows:
                return self.state.role_rows[queried]
            if self.state.roles_exist:
                return ("launchcrew_role", self.state.roles_superuser,
                        self.state.roles_login, self.state.role_createrole,
                        self.state.role_createdb, self.state.role_replication,
                        self.state.role_bypassrls)
            return None
        if lowered == "select session_user, current_user":
            if (self.dbname == "postgres"
                    and self.state.maintenance_spoof is not None):
                return self.state.maintenance_spoof
            if self.user in self.state.spoof_identity:
                return self.state.spoof_identity[self.user]
            return (self.user, self.user)
        if lowered == "select 1":
            return (1,)
        if "alembic_version" in lowered:
            if self.state.schema_present:
                return (self.state.schema_version,)
            return None
        if lowered == "select current_user":
            return (self.state.current_identity,)
        return None

    def fetchall(self):
        sql, params = self.state.statements[-1]
        lowered = sql.strip().lower()
        if "pg_auth_members" in lowered:
            queried = params[0] if params else None
            if queried in self.state.membership_map:
                return list(self.state.membership_map[queried])
            if self.state.role_memberships:
                return [("foreign_group", queried, "someone_else",
                         False, True, False, False, 16384)]
            return []
        if "pg_default_acl" in lowered:
            return list(self.state.model_default_acls)
        if "pg_class" in lowered:
            return list(self.state.inventory)
        if "pg_proc" in lowered:
            if "prosecdef" in lowered:
                return list(self.state.model_funcs)
            if "aclexplode" in lowered:
                func = params[-1] if params else None
                return list(self.state.model_func_acls.get(func, []))
            return list(self.state.function_inventory)
        return []


class FakeConn:
    def __init__(self, state, user=None, dbname=None):
        self.state = state
        self.user = user
        self.dbname = dbname
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self.state, self.user, self.dbname, self)

    def rollback(self):
        self.state.rollbacks += 1
        return None

    def commit(self):
        self.state.commits += 1
        return None

    def close(self):
        self.closed = True


class FakeDriverState:
    def __init__(self):
        self.statements = []
        self.roles_exist = False
        self.roles_superuser = False
        self.roles_login = True
        self.role_createrole = False
        self.role_createdb = False
        self.role_replication = False
        self.role_bypassrls = False
        self.role_comment = "launchcrew-managed"
        self.role_memberships = False
        self.role_rows = {}
        self.membership_map = {}
        self.inventory = []
        self.function_inventory = []
        self.schema_owner = "launchcrew_master"
        self.database_owner = "launchcrew_master"
        self.spoof_identity = {}
        self.fail_on_password = False
        self.refuse_ddl = True
        self.ddl_sqlstate = "42501"
        self.schema_present = True
        self.schema_version = "006"
        self.current_identity = "launchcrew_runtime"
        self.runtime_oid = 12345
        self.model_budget_remaining = 0
        self.model_budget_missing = False
        self.model_direct_allow = False
        self.model_direct_sqlstate = "42501"
        self.model_funcs = [
            ("model_finalize_call", True,
             ["search_path=public, pg_temp"]),
            ("model_no_direct", False,
             ["search_path=pg_catalog, pg_temp"]),
            ("model_reserve_call", True,
             ["search_path=public, pg_temp"]),
        ]
        self.model_func_acls = {
            "model_reserve_call": [(12345, "EXECUTE")],
            "model_finalize_call": [(12345, "EXECUTE")],
            "model_no_direct": [],
        }
        self.model_default_acls = []
        self.connect_count = 0
        self.connects = []
        self.fail_connect = False
        self.fail_maintenance = False
        self.maintenance_connect_sqlstate = None
        self.fail_app_master = False
        self.app_connect_sqlstate = None
        self.fail_create = False
        self.create_sqlstate = None
        self.maintenance_spoof = None
        self.create_saw_autocommit = []
        self.create_attempts = 0
        self.rollbacks = 0
        self.commits = 0
        self.used_client_cursor = False


class FakePsycopg:
    def __init__(self, state):
        self.state = state

    def connect(self, *args, **kwargs):
        self.state.connect_count += 1
        self.state.connect_kwargs = kwargs
        self.state.connect_args = args
        self.state.connects.append(dict(kwargs))
        if self.state.fail_connect:
            raise FakeError("could not connect")
        dbname = kwargs.get("dbname")
        user = kwargs.get("user")
        if dbname == "postgres" and self.state.fail_maintenance:
            raise FakeError("maintenance connect failed",
                            sqlstate=self.state.maintenance_connect_sqlstate)
        if (dbname == "launchcrew" and user == "launchcrew_master"
                and self.state.fail_app_master):
            raise FakeError("app connect failed",
                            sqlstate=self.state.app_connect_sqlstate)
        return FakeConn(self.state, user, dbname)

    def ClientCursor(self, conn):
        self.state.used_client_cursor = True
        return FakeCursor(self.state, conn.user, conn.dbname, conn)


class BindJobTests(unittest.TestCase):
    def setUp(self):
        self.state = FakeDriverState()
        import sys
        sys.modules["psycopg"] = FakePsycopg(self.state)
        spec = importlib.util.spec_from_file_location("bootstrap_db_roles", str(SCRIPT))
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module._known_secrets.clear()
        self.tmp_root = Path(os.environ.get("TMPDIR", "/tmp"))
        self.bundle = self.tmp_root / "lc-test-ca-bundle.pem"
        self.bundle.write_text("test bundle", encoding="utf-8")
        self.addCleanup(lambda: self.bundle.unlink(missing_ok=True))
        self.env = {
            "LAUNCHCREW_DB_TLS_MODE": "verify-full",
            "DATABASE_SSL_ROOTCERT": str(self.bundle),
            "DB_HOST": "dbhost",
            "DB_PORT": "5432",
            "DB_NAME": "launchcrew",
            "DB_MASTER_USER": "launchcrew_master",
            "MASTER_DB_PASSWORD": "s3ntinel-master-pw-9x",
            "RUNTIME_DB_URL": runtime_url(),
            "MIGRATION_DB_URL": migration_url(),
            "RUNTIME_USER": "launchcrew_runtime",
            "MIGRATION_USER": "launchcrew_migration",
            "APP_SCHEMA": "public",
        }

    def run_main(self, mode, env_overrides=None):
        env = dict(self.env)
        if env_overrides:
            env.update(env_overrides)
        old = dict(os.environ)
        os.environ.update(env)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.module.main(["bootstrap_db_roles.py", mode])
        finally:
            os.environ.clear()
            os.environ.update(old)
        return code, out.getvalue()

    def sql_texts(self):
        return [sql for sql, _ in self.state.statements]

    def test_bind_success_reports_all_phases(self):
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        for phase in ("db-ensure", "password-binding", "schema-acls",
                      "runtime-grants", "default-privileges",
                      "BIND COMPLETE"):
            self.assertIn(phase, out)

    def test_bind_creates_missing_roles_with_login(self):
        code, _ = self.run_main("--bind")
        self.assertEqual(code, 0)
        creates = [sql for sql in self.sql_texts() if sql.startswith("CREATE ROLE")]
        self.assertEqual(len(creates), 2)
        for sql in creates:
            self.assertIn("WITH LOGIN", sql)

    def test_bind_skips_create_for_existing_roles(self):
        self.state.roles_exist = True
        code, _ = self.run_main("--bind")
        self.assertEqual(code, 0)
        creates = [sql for sql in self.sql_texts() if sql.startswith("CREATE ROLE")]
        self.assertEqual(creates, [])

    def test_passwords_only_as_parameters_never_in_sql(self):
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0)
        alters = [(sql, params) for sql, params in self.state.statements
                  if sql.startswith("ALTER ROLE")]
        self.assertEqual(len(alters), 2)
        for sql, params in alters:
            self.assertIn("WITH PASSWORD %s", sql)
            self.assertIsNotNone(params)
            self.assertEqual(len(params), 1)
        for sql in self.sql_texts():
            self.assertNotIn(RT_PW, sql)
            self.assertNotIn(MG_PW, sql)
        self.assertNotIn(RT_PW, out)
        self.assertNotIn(MG_PW, out)
        self.assertNotIn("s3ntinel-master-pw-9x", out)
        self.assertNotIn("postgresql://", out)

    def test_privilege_split_matches_db_roles(self):
        code, _ = self.run_main("--bind")
        self.assertEqual(code, 0)
        joined = "\n".join(self.sql_texts())
        for stmt in (
                "REVOKE CREATE ON SCHEMA",
                "GRANT USAGE ON SCHEMA",
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES",
                "GRANT USAGE, SELECT ON ALL SEQUENCES",
                "GRANT USAGE, CREATE ON SCHEMA",
                "ALTER DEFAULT PRIVILEGES FOR ROLE"):
            self.assertIn(stmt, joined)
        self.assertNotIn("GRANT ALL PRIVILEGES ON ALL TABLES", joined)
        self.assertNotIn("GRANT ALL PRIVILEGES ON ALL SEQUENCES", joined)
        sql_text = SQL_FILE.read_text(encoding="utf-8")
        for stmt in (
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES",
                "ALTER DEFAULT PRIVILEGES FOR ROLE :migration_user"):
            self.assertIn(stmt, sql_text)

    def test_bind_uses_master_then_migration_connections(self):
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        self.assertEqual(self.state.connect_count, 3)
        maint, first, second = self.state.connects
        self.assertEqual(maint.get("dbname"), "postgres")
        self.assertEqual(maint.get("user"), "launchcrew_master")
        self.assertEqual(maint.get("host"), "dbhost")
        self.assertEqual(maint.get("port"), 5432)
        self.assertEqual(maint.get("sslmode"), "verify-full")
        self.assertEqual(maint.get("sslrootcert"), str(self.bundle))
        self.assertEqual(first.get("user"), "launchcrew_master")
        self.assertEqual(first.get("dbname"), "launchcrew")
        self.assertEqual(first.get("sslmode"), "verify-full")
        self.assertEqual(first.get("sslrootcert"), str(self.bundle))
        self.assertEqual(second.get("user"), "launchcrew_migration")
        self.assertEqual(second.get("host"), "dbhost")
        self.assertEqual(second.get("port"), 5432)
        self.assertEqual(second.get("dbname"), "launchcrew")
        self.assertEqual(second.get("sslmode"), "verify-full")
        self.assertEqual(second.get("sslrootcert"), str(self.bundle))

    def test_runtime_never_gets_ddl(self):
        code, _ = self.run_main("--bind")
        self.assertEqual(code, 0)
        runtime_grants = [sql for sql in self.sql_texts()
                          if "launchcrew_runtime" in sql
                          and sql.strip().upper().startswith("GRANT")]
        for sql in runtime_grants:
            self.assertNotIn("TRUNCATE", sql)
            self.assertNotIn("REFERENCES", sql)
            self.assertNotIn("TRIGGER", sql)
            self.assertNotIn("CREATE ON SCHEMA", sql)

    def test_invalid_identifier_rejected_before_connect(self):
        code, out = self.run_main("--bind", {"RUNTIME_USER": "runtime;DROP"})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.state.connect_count, 0)
        self.assertIn("FAIL", out)

    def test_missing_tls_mode_fails_closed(self):
        code, out = self.run_main("--bind", {"LAUNCHCREW_DB_TLS_MODE": ""})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.state.connect_count, 0)

    def test_matching_runtime_migration_roles_refused(self):
        code, out = self.run_main("--bind", {"RUNTIME_USER": "launchcrew_migration"})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.state.connect_count, 0)
        self.assertIn("FAIL", out)

    def test_role_equal_to_master_refused(self):
        code, out = self.run_main("--bind", {"RUNTIME_USER": "launchcrew_master"})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.state.connect_count, 0)
        self.assertIn("FAIL", out)

    def test_existing_superuser_role_refused(self):
        self.state.roles_exist = True
        self.state.roles_superuser = True
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("role-safety", out)

    def test_existing_role_without_marker_refused(self):
        self.state.roles_exist = True
        self.state.role_comment = None
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("role-safety", out)
        self.assertIn("ownership marker", out)

    def test_existing_role_with_wrong_marker_refused(self):
        self.state.roles_exist = True
        self.state.role_comment = "other-project"
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("role-safety", out)

    def test_existing_role_with_memberships_refused(self):
        self.state.roles_exist = True
        self.state.role_memberships = True
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("role-safety", out)
        self.assertIn("memberships", out)

    def test_native_creator_membership_is_allowed(self):
        self.state.roles_exist = True
        native_runtime = [("launchcrew_runtime", "launchcrew_master",
                           "postgres", True, True, False, False, 10)]
        native_migration = [("launchcrew_migration", "launchcrew_master",
                             "postgres", True, True, False, False, 10)]
        self.state.membership_map = {
            "launchcrew_runtime": native_runtime,
            "launchcrew_migration": native_migration,
        }
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        alters = [(sql, params) for sql, params in self.state.statements
                  if sql.startswith("ALTER ROLE")]
        self.assertEqual(len(alters), 2)

    def test_changed_membership_options_are_refused(self):
        self.state.roles_exist = True
        variants = [
            ("launchcrew_runtime", "launchcrew_master", "postgres",
             True, False, False, False, 10),
            ("launchcrew_runtime", "launchcrew_master", "postgres",
             True, True, True, False, 10),
            ("launchcrew_runtime", "launchcrew_master", "postgres",
             True, True, False, True, 10),
        ]
        for row in variants:
            self.state.membership_map = {"launchcrew_runtime": [row],
                                         "launchcrew_migration": []}
            self.state.statements = []
            code, out = self.run_main("--bind")
            self.assertNotEqual(code, 0)
            self.assertIn("memberships", out)
            mutating = [sql for sql in self.sql_texts()
                        if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                           "COMMENT ON ROLE", "GRANT",
                                           "REVOKE"))]
            self.assertEqual(mutating, [])

    def test_foreign_grantor_and_reverse_memberships_refused(self):
        self.state.roles_exist = True
        variants = [
            [("launchcrew_runtime", "launchcrew_master", "intruder",
              False, True, False, False, 16384)],
            [("launchcrew_runtime", "launchcrew_master", "launchcrew_master",
              False, True, False, False, 16385)],
            [("other_group", "launchcrew_runtime", "postgres",
              True, True, False, False, 10)],
            [("launchcrew_runtime", "someone_else", "postgres",
              True, True, False, False, 10)],
        ]
        for rows in variants:
            self.state.membership_map = {"launchcrew_runtime": rows,
                                         "launchcrew_migration": []}
            self.state.statements = []
            self.state.commits = 0
            code, out = self.run_main("--bind")
            self.assertNotEqual(code, 0)
            self.assertIn("memberships", out)
            mutating = [sql for sql in self.sql_texts()
                        if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                           "COMMENT ON ROLE", "GRANT",
                                           "REVOKE"))]
            self.assertEqual(mutating, [])
            self.assertEqual(self.state.commits, 0)

    def test_second_bad_role_blocks_first_mutation(self):
        self.state.role_rows = {
            "launchcrew_runtime": None,
            "launchcrew_migration": ("launchcrew_migration", True, True,
                                     False, False, False, False),
        }
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("role-safety", out)
        creates = [sql for sql in self.sql_texts()
                   if sql.startswith("CREATE ROLE")]
        self.assertEqual(creates, [])

    def test_existing_role_with_bypassrls_refused(self):
        self.state.roles_exist = True
        self.state.role_bypassrls = True
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("role-safety", out)
        self.assertIn("BYPASSRLS", out)

    def test_password_failure_rolls_back_without_commit(self):
        self.state.fail_on_password = True
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("password-binding", out)
        self.assertEqual(self.state.commits, 0)
        self.assertGreater(self.state.rollbacks, 0)

    def test_migration_identity_mismatch_refused(self):
        self.state.spoof_identity = {
            "launchcrew_migration": ("postgres", "postgres")}
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("migration-identity", out)
        self.assertIn("password-binding,schema-acls", out)

    def test_unexpected_owner_refused_before_object_grants(self):
        self.state.inventory = [("evil_table", "r", "someone_else")]
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("unexpected owner", out)
        joined = "\n".join(self.sql_texts())
        self.assertNotIn("ON ALL TABLES", joined)
        self.assertNotIn("ON ALL SEQUENCES", joined)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)

    def test_migration_owned_objects_allow_grants(self):
        self.state.inventory = [("alembic_version", "r",
                                 "launchcrew_migration"),
                                ("items_id_seq", "S",
                                 "launchcrew_migration")]
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)

    def test_migration_owned_views_allow_grants(self):
        self.state.inventory = [
            ("owned_view", "v", "launchcrew_migration"),
            ("owned_matview", "m", "launchcrew_migration"),
            ("owned_foreign", "f", "launchcrew_migration"),
        ]
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)

    def test_bind_sets_function_defaults_global_public_revoke(self):
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        joined = "\n".join(self.sql_texts())
        self.assertIn("REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC", joined)
        self.assertNotIn("GRANT EXECUTE ON FUNCTIONS", joined)
        revokes = [sql for sql in self.sql_texts()
                   if "REVOKE EXECUTE ON FUNCTIONS" in sql]
        self.assertTrue(revokes)
        for sql in revokes:
            self.assertNotIn("IN SCHEMA", sql)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO",
                      joined)
        self.assertIn("GRANT USAGE, SELECT ON SEQUENCES TO", joined)

    def test_bind_applies_model_narrow_revokes_when_tables_exist(self):
        self.state.inventory = [("model_budget", "r",
                                 "launchcrew_migration"),
                                ("model_calls", "r",
                                 "launchcrew_migration")]
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        joined = "\n".join(self.sql_texts())
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES",
                      joined)
        revokes = [sql for sql in self.sql_texts()
                   if "model_budget" in sql or "model_calls" in sql]
        self.assertTrue(any("REVOKE INSERT, UPDATE, DELETE" in sql
                            for sql in revokes))
        for sql in revokes:
            if sql.strip().upper().startswith("REVOKE"):
                prefix = sql.split("ON TABLE")[0]
                self.assertNotIn("SELECT", prefix)
                self.assertIn("TRUNCATE", sql)

    def test_bind_skips_model_revokes_when_tables_absent(self):
        self.state.inventory = []
        self.state.function_inventory = []
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        self.assertIn("BIND COMPLETE", out)
        for sql in self.sql_texts():
            self.assertNotIn("model_budget", sql)
            self.assertNotIn("model_calls", sql)
            self.assertNotIn("model_reserve_call", sql)
            self.assertNotIn("model_finalize_call", sql)
            self.assertNotIn("model_no_direct", sql)

    def test_bind_grants_model_functions_when_exist(self):
        self.state.function_inventory = [
            ("model_reserve_call", "launchcrew_migration"),
            ("model_finalize_call", "launchcrew_migration"),
        ]
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        joined = "\n".join(self.sql_texts())
        self.assertIn("model_reserve_call", joined)
        self.assertIn("model_finalize_call", joined)
        self.assertIn("REVOKE EXECUTE ON FUNCTION", joined)
        self.assertIn("GRANT EXECUTE ON FUNCTION", joined)
        for sql in self.sql_texts():
            if "GRANT EXECUTE ON FUNCTION" in sql:
                self.assertNotIn("PUBLIC", sql)

    def test_bind_explicit_model_grants_without_blanket_default(self):
        self.state.function_inventory = [
            ("model_reserve_call", "launchcrew_migration"),
            ("model_finalize_call", "launchcrew_migration"),
        ]
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        joined = "\n".join(self.sql_texts())
        self.assertIn("GRANT EXECUTE ON FUNCTION", joined)
        self.assertIn("model_reserve_call", joined)
        self.assertIn("model_finalize_call", joined)
        self.assertNotIn("GRANT EXECUTE ON FUNCTIONS", joined)
        self.assertIn("REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC", joined)

    def test_bind_revokes_trigger_function_from_runtime(self):
        self.state.function_inventory = [("model_no_direct",
                                          "launchcrew_migration")]
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        trigger_sqls = [sql for sql in self.sql_texts()
                        if "model_no_direct" in sql]
        self.assertTrue(trigger_sqls)
        for sql in trigger_sqls:
            self.assertTrue(sql.strip().upper().startswith("REVOKE"))
        self.assertFalse(any("GRANT" in sql and "model_no_direct" in sql
                             for sql in self.sql_texts()))

    def test_bind_refuses_foreign_function_owner(self):
        self.state.function_inventory = [("model_reserve_call",
                                          "someone_else")]
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("unexpected owner", out)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)

    def test_model_acls_survive_repeated_bind(self):
        self.state.inventory = [("model_budget", "r",
                                 "launchcrew_migration"),
                                ("model_calls", "r",
                                 "launchcrew_migration")]
        self.state.function_inventory = [
            ("model_reserve_call", "launchcrew_migration"),
            ("model_finalize_call", "launchcrew_migration"),
            ("model_no_direct", "launchcrew_migration"),
        ]
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        self.assertTrue(any("model_budget" in sql
                            for sql in self.sql_texts()))
        self.state.statements = []
        self.state.commits = 0
        self.state.rollbacks = 0
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        self.assertIn("BIND COMPLETE", out)
        self.assertTrue(any("model_budget" in sql
                            for sql in self.sql_texts()))
        self.assertTrue(any("model_reserve_call" in sql
                            for sql in self.sql_texts()))

    def test_foreign_owned_view_refused_before_mutation(self):
        for kind in ("v", "m", "f"):
            self.state.inventory = [("evil_rel", kind, "someone_else")]
            self.state.statements = []
            self.state.commits = 0
            self.state.rollbacks = 0
            code, out = self.run_main("--bind")
            self.assertNotEqual(code, 0, msg=kind)
            self.assertIn("unexpected owner", out)
            mutating = [sql for sql in self.sql_texts()
                        if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                           "COMMENT ON ROLE", "GRANT",
                                           "REVOKE"))]
            self.assertEqual(mutating, [], msg=kind)
            self.assertEqual(self.state.commits, 0, msg=kind)

    def test_runtime_port_mismatch_refused_before_connect(self):
        bad = ("postgresql://launchcrew_runtime:%s@dbhost:55432/launchcrew"
               "?sslmode=verify-full" % RT_PW)
        code, out = self.run_main("--bind", {"RUNTIME_DB_URL": bad})
        self.assertNotEqual(code, 0)
        self.assertIn("FAIL", out)
        self.assertEqual(self.state.connect_count, 0)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)
        self.assertNotIn(RT_PW, out)
        self.assertNotIn("postgresql://", out)

    def test_migration_port_mismatch_refused_before_connect(self):
        bad = ("postgresql://launchcrew_migration:%s@dbhost:55432/launchcrew"
               "?sslmode=verify-full" % MG_PW)
        code, out = self.run_main("--bind", {"MIGRATION_DB_URL": bad})
        self.assertNotEqual(code, 0)
        self.assertIn("FAIL", out)
        self.assertEqual(self.state.connect_count, 0)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)
        self.assertNotIn(MG_PW, out)
        self.assertNotIn("postgresql://", out)

    def test_missing_schema_refused_before_writes(self):
        self.state.schema_owner = None
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("schema-safety", out)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)

    def test_unowned_schema_refused_before_writes(self):
        self.state.schema_owner = "someone_else"
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("schema-safety", out)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)

    def test_native_database_owner_schema_allowed_only_with_master_db(self):
        self.state.schema_owner = "pg_database_owner"
        self.state.database_owner = "launchcrew_master"
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        self.state.statements = []
        self.state.commits = 0
        self.state.schema_owner = "someone_else"
        self.state.database_owner = "launchcrew_master"
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("schema-safety", out)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)
        self.state.statements = []
        self.state.commits = 0
        self.state.schema_owner = "pg_database_owner"
        self.state.database_owner = "someone_else"
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("db-safety", out)
        self.assertIn("foreign owner", out)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)

    def test_foreign_superuser_grantor_is_refused(self):
        self.state.roles_exist = True
        evil = [("launchcrew_runtime", "launchcrew_master", "evil_super",
                 True, True, False, False, 16384)]
        self.state.membership_map = {"launchcrew_runtime": evil,
                                     "launchcrew_migration": []}
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("memberships", out)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)

    def test_rdsadmin_native_grantor_is_allowed(self):
        self.state.roles_exist = True
        native_runtime = [("launchcrew_runtime", "launchcrew_master",
                           "rdsadmin", True, True, False, False, 10)]
        native_migration = [("launchcrew_migration", "launchcrew_master",
                             "rdsadmin", True, True, False, False, 10)]
        self.state.membership_map = {
            "launchcrew_runtime": native_runtime,
            "launchcrew_migration": native_migration,
        }
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)

    def test_existing_role_with_createrole_refused(self):
        self.state.roles_exist = True
        self.state.role_createrole = True
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("role-safety", out)

    def test_existing_marked_safe_role_is_rebound(self):
        self.state.roles_exist = True
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        alters = [(sql, params) for sql, params in self.state.statements
                  if sql.startswith("ALTER ROLE")]
        self.assertEqual(len(alters), 2)

    def test_created_roles_carry_ownership_marker(self):
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        comments = [sql for sql in self.sql_texts()
                    if sql.startswith("COMMENT ON ROLE")]
        self.assertEqual(len(comments), 2)
        for sql in comments:
            self.assertIn("launchcrew-managed", sql)

    def test_percent_encoded_password_decoded_for_binding(self):
        encoded = "postgresql://launchcrew_runtime:p%40ss%3Aw0rd@dbhost:5432/launchcrew?sslmode=verify-full"
        code, out = self.run_main("--bind", {"RUNTIME_DB_URL": encoded})
        self.assertEqual(code, 0, msg=out)
        alters = [(sql, params) for sql, params in self.state.statements
                  if sql.startswith("ALTER ROLE")]
        self.assertEqual(len(alters), 2)
        self.assertIn("p@ss:w0rd", [params[0] for _, params in alters])
        self.assertNotIn("p@ss:w0rd", out)
        self.assertNotIn("p%40ss%3Aw0rd", out)

    def test_rerouting_query_refused_before_connect(self):
        bad = ("postgresql://launchcrew_runtime:%s@dbhost:5432/launchcrew"
               "?sslmode=verify-full&host=evil.example") % "pw"
        code, out = self.run_main("--bind", {"RUNTIME_DB_URL": bad})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.state.connect_count, 0)
        self.assertIn("FAIL", out)

    def test_ambient_pghost_refused_before_connect(self):
        code, out = self.run_main("--bind", {"PGHOST": "evil.example"})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.state.connect_count, 0)
        self.assertIn("FAIL", out)

    def test_password_binding_uses_client_side_cursor(self):
        code, _ = self.run_main("--bind")
        self.assertEqual(code, 0)
        self.assertTrue(self.state.used_client_cursor)

    def test_connect_failure_reports_no_secret(self):
        self.state.fail_connect = True
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("FAIL", out)
        self.assertNotIn(RT_PW, out)
        self.assertNotIn(MG_PW, out)
        self.assertNotIn("s3ntinel-master-pw-9x", out)

    def test_db_ensure_creates_missing_database(self):
        self.state.database_owner = None
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        self.assertIn("db-ensure ok", out)
        creates = [sql for sql in self.sql_texts()
                   if sql.startswith("CREATE DATABASE")]
        self.assertEqual(creates, ['CREATE DATABASE "launchcrew"'])
        self.assertEqual(self.state.create_attempts, 1)
        self.assertEqual(self.state.create_saw_autocommit, [True])
        self.assertEqual(self.state.connect_count, 3)
        maint, app, mig = self.state.connects
        self.assertEqual(maint.get("dbname"), "postgres")
        self.assertEqual(maint.get("user"), "launchcrew_master")
        self.assertEqual(maint.get("host"), "dbhost")
        self.assertEqual(maint.get("port"), 5432)
        self.assertEqual(maint.get("sslmode"), "verify-full")
        self.assertEqual(maint.get("sslrootcert"), str(self.bundle))
        self.assertEqual(app.get("dbname"), "launchcrew")
        self.assertEqual(app.get("user"), "launchcrew_master")
        self.assertEqual(mig.get("user"), "launchcrew_migration")
        for sql, params in self.state.statements:
            if "pg_database" in sql.lower() and "datdba" in sql.lower():
                self.assertEqual(params, ("launchcrew",))
        self.assertNotIn(RT_PW, out)
        self.assertNotIn(MG_PW, out)
        self.assertNotIn("s3ntinel-master-pw-9x", out)
        self.assertNotIn("postgresql://", out)

    def test_db_ensure_idempotent_rerun_skips_create(self):
        self.state.database_owner = None
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        self.assertEqual(self.state.create_attempts, 1)
        self.assertEqual(self.state.database_owner, "launchcrew_master")
        self.state.statements = []
        self.state.connects = []
        self.state.connect_count = 0
        self.state.create_attempts = 0
        self.state.create_saw_autocommit = []
        self.state.commits = 0
        self.state.rollbacks = 0
        code, out = self.run_main("--bind")
        self.assertEqual(code, 0, msg=out)
        creates = [sql for sql in self.sql_texts()
                   if sql.startswith("CREATE DATABASE")]
        self.assertEqual(creates, [])
        self.assertEqual(self.state.create_attempts, 0)
        self.assertEqual(self.state.connect_count, 3)
        self.assertIn("db-ensure ok", out)
        self.assertIn("BIND COMPLETE", out)

    def test_db_ensure_refuses_foreign_owner(self):
        self.state.database_owner = "someone_else"
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("db-safety", out)
        self.assertIn("foreign owner", out)
        creates = [sql for sql in self.sql_texts()
                   if sql.startswith("CREATE DATABASE")]
        self.assertEqual(creates, [])
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)
        self.assertEqual(self.state.connect_count, 1)
        self.assertEqual(self.state.connects[0].get("dbname"), "postgres")
        self.assertNotIn(RT_PW, out)
        self.assertNotIn(MG_PW, out)
        self.assertNotIn("s3ntinel-master-pw-9x", out)
        self.assertNotIn("postgresql://", out)

    def test_db_create_failure_is_terminal_without_resend(self):
        self.state.database_owner = None
        self.state.fail_create = True
        self.state.create_sqlstate = "42501"
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("db-create", out)
        self.assertIn("sqlstate=42501", out)
        self.assertNotIn("simulated create failure", out)
        self.assertNotIn(RT_PW, out)
        self.assertNotIn(MG_PW, out)
        self.assertNotIn("s3ntinel-master-pw-9x", out)
        self.assertNotIn("postgresql://", out)
        self.assertEqual(self.state.create_attempts, 1)
        creates = [sql for sql in self.sql_texts()
                   if sql.startswith("CREATE DATABASE")]
        self.assertEqual(len(creates), 1)
        self.assertEqual(self.state.connect_count, 1)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)
        self.assertNotIn("BIND COMPLETE", out)

    def test_maintenance_identity_mismatch_refused(self):
        self.state.maintenance_spoof = ("postgres", "postgres")
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("maintenance", out)
        self.assertIn("identity mismatch", out)
        creates = [sql for sql in self.sql_texts()
                   if sql.startswith("CREATE DATABASE")]
        self.assertEqual(creates, [])
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)
        self.assertEqual(self.state.connect_count, 1)

    def test_app_connect_failure_reports_sqlstate_without_secret(self):
        self.state.database_owner = "launchcrew_master"
        self.state.fail_app_master = True
        self.state.app_connect_sqlstate = "28P01"
        code, out = self.run_main("--bind")
        self.assertNotEqual(code, 0)
        self.assertIn("FAIL", out)
        self.assertIn("sqlstate=28P01", out)
        self.assertNotIn("app connect failed", out)
        self.assertNotIn(RT_PW, out)
        self.assertNotIn(MG_PW, out)
        self.assertNotIn("s3ntinel-master-pw-9x", out)
        self.assertNotIn("postgresql://", out)
        self.assertEqual(self.state.connect_count, 2)
        mutating = [sql for sql in self.sql_texts()
                    if sql.startswith(("CREATE ROLE", "ALTER ROLE",
                                       "COMMENT ON ROLE", "GRANT",
                                       "REVOKE"))]
        self.assertEqual(mutating, [])
        self.assertEqual(self.state.commits, 0)


class VerifyJobTests(BindJobTests):
    def test_verify_proves_read_schema_and_ddl_refusal(self):
        code, out = self.run_main("--verify")
        self.assertEqual(code, 0, msg=out)
        for marker in ("verify-read ok", "verify-schema ok",
                       "verify-identity ok", "verify-write ok",
                       "verify-runtime-no-create ok",
                       "verify-runtime-no-alter ok",
                       "verify-runtime-no-drop ok",
                       "verify-model-budget-zero ok",
                       "verify-model-no-direct ok",
                       "verify-model-functions ok",
                       "verify-model-defaults ok",
                       "VERIFY COMPLETE"):
            self.assertIn(marker, out)
        self.assertIn("revision=006", out)

    def test_verify_fails_when_runtime_can_write(self):
        self.state.refuse_ddl = False
        code, _ = self.run_main("--verify")
        self.assertNotEqual(code, 0)

    def test_verify_fails_without_schema_row(self):
        self.state.schema_present = False
        code, _ = self.run_main("--verify")
        self.assertNotEqual(code, 0)

    def test_verify_refuses_wrong_head(self):
        self.state.schema_version = "004"
        code, _ = self.run_main("--verify")
        self.assertNotEqual(code, 0)

    def test_verify_refuses_nonzero_model_budget(self):
        self.state.model_budget_remaining = 4000000
        code, out = self.run_main("--verify")
        self.assertNotEqual(code, 0)
        self.assertIn("verify-model-budget-zero", out)

    def test_verify_refuses_direct_model_write(self):
        self.state.model_direct_allow = True
        code, out = self.run_main("--verify")
        self.assertNotEqual(code, 0)
        self.assertIn("verify-model-no-direct", out)

    def test_verify_refuses_public_function_grant(self):
        self.state.model_func_acls["model_reserve_call"] = [
            (0, "EXECUTE"), (12345, "EXECUTE")]
        code, out = self.run_main("--verify")
        self.assertNotEqual(code, 0)
        self.assertIn("verify-model-functions", out)

    def test_verify_refuses_missing_runtime_function_grant(self):
        self.state.model_func_acls["model_finalize_call"] = []
        code, out = self.run_main("--verify")
        self.assertNotEqual(code, 0)
        self.assertIn("verify-model-functions", out)

    def test_verify_refuses_future_default_grant(self):
        self.state.model_default_acls = [(12345, "EXECUTE")]
        code, out = self.run_main("--verify")
        self.assertNotEqual(code, 0)
        self.assertIn("verify-model-defaults", out)

    def test_verify_refuses_wrong_identity(self):
        self.state.current_identity = "postgres"
        code, _ = self.run_main("--verify")
        self.assertNotEqual(code, 0)

    def test_verify_refuses_non_permission_ddl_error(self):
        self.state.ddl_sqlstate = "42P01"
        code, out = self.run_main("--verify")
        self.assertNotEqual(code, 0)
        self.assertIn("not a permission refusal", out)

    def test_verify_never_commits(self):
        code, out = self.run_main("--verify")
        self.assertEqual(code, 0, msg=out)
        self.assertEqual(self.state.commits, 0)
        self.assertGreater(self.state.rollbacks, 0)

    def test_verify_works_without_master_or_migration_env(self):
        code, out = self.run_main("--verify", {"MASTER_DB_PASSWORD": "",
                                               "MIGRATION_DB_URL": "",
                                               "DB_MASTER_USER": ""})
        self.assertEqual(code, 0, msg=out)

    def test_verify_requires_verify_full_url(self):
        bad = "postgresql://launchcrew_runtime:pw@dbhost:5432/launchcrew?sslmode=require"
        code, _ = self.run_main("--verify", {"RUNTIME_DB_URL": bad})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.state.connect_count, 0)


class StaticBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_no_argv_secrets_no_file_passwords(self):
        self.assertIn("--bind", self.text)
        self.assertIn("--verify", self.text)
        self.assertNotIn("sys.argv[2]", self.text)
        self.assertNotIn("argparse", self.text)
        self.assertNotIn("open(", self.text.replace("spec_from_file_location", ""))

    def test_redaction_and_identifier_guards_present(self):
        self.assertIn("_redact", self.text)
        self.assertIn("_known_secrets", self.text)
        self.assertIn("a-z_][a-z0-9_]", self.text)
        self.assertIn("LAUNCHCREW_DB_TLS_MODE", self.text)
        self.assertIn("DATABASE_SSL_ROOTCERT", self.text)

    def test_verify_mode_never_uses_master_or_migration(self):
        verify_start = self.text.index("def do_verify")
        verify_body = self.text[verify_start:]
        self.assertNotIn("MASTER_DB_PASSWORD", verify_body)
        self.assertNotIn("MIGRATION_DB_URL", verify_body)
        self.assertNotIn("alembic upgrade", verify_body.lower())

    def test_password_binding_uses_client_side_cursor(self):
        self.assertIn("ClientCursor", self.text)

    def test_binding_comment_states_memory_only_literal(self):
        self.assertNotIn("never interpolated into SQL text", self.text)
        self.assertIn("in this process memory only", self.text)

    def test_existing_role_takeover_guards_present(self):
        self.assertIn("MANAGED_COMMENT", self.text)
        self.assertIn("pg_shdescription", self.text)
        self.assertIn("pg_auth_members", self.text)
        self.assertIn("rolcreaterole", self.text)
        self.assertIn("rolbypassrls", self.text)
        self.assertIn("inherit_option", self.text)
        self.assertIn("set_option", self.text)
        self.assertIn("ownership marker", self.text)

    def test_native_grantor_schema_and_port_guards_present(self):
        self.assertIn("NATIVE_BOOTSTRAP_OID", self.text)
        self.assertIn("m.grantor", self.text)
        self.assertIn("pg_database_owner", self.text)
        self.assertIn("schema-safety", self.text)
        self.assertIn("port does not match DB_PORT", self.text)
        self.assertIn("'v', 'm', 'f'", self.text)

    def test_verify_mode_never_commits(self):
        verify_start = self.text.index("def do_verify")
        verify_body = self.text[verify_start:]
        self.assertNotIn(".commit(", verify_body)

    def test_verify_checks_exact_head_and_sqlstate(self):
        self.assertIn("EXPECTED_HEAD", self.text)
        self.assertIn("42501", self.text)

    def test_db_ensure_guards_present(self):
        self.assertIn("MAINTENANCE_DB", self.text)
        self.assertIn("CREATE DATABASE", self.text)
        self.assertIn("db-ensure", self.text)
        self.assertIn("db-safety", self.text)
        self.assertIn("db-create", self.text)
        self.assertIn("foreign owner", self.text)
        self.assertIn("autocommit = True", self.text)
        self.assertIn("42P04", self.text)
        self.assertIn("_error_detail", self.text)
        self.assertIn("sqlstate=", self.text)

    def test_model_narrow_guards_present(self):
        self.assertIn("MODEL_TABLES", self.text)
        self.assertIn("model_budget", self.text)
        self.assertIn("model_calls", self.text)
        self.assertIn("MODEL_RESERVE_FUNC", self.text)
        self.assertIn("MODEL_FINALIZE_FUNC", self.text)
        self.assertIn("MODEL_TRIGGER_FUNC", self.text)
        self.assertIn("REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC", self.text)
        self.assertNotIn("GRANT EXECUTE ON FUNCTIONS TO", self.text)
        self.assertIn("GRANT EXECUTE ON FUNCTION", self.text)
        self.assertIn("_function_owners", self.text)
        self.assertIn("pg_proc", self.text)


VERIFY_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify-db-roles.sh"


def _split_acl_entry(entry):
    text = str(entry)
    left = text.rsplit("/", 1)[0]
    grantee, _, privs = left.partition("=")
    if grantee == "":
        return None, privs
    return grantee, privs


def _has_public_priv(entries, wanted):
    for entry in entries or []:
        grantee, privs = _split_acl_entry(entry)
        if grantee is None and any(code in privs for code in wanted):
            return True
    return False


def _named_privs(entries, role):
    for entry in entries or []:
        grantee, privs = _split_acl_entry(entry)
        if grantee == role:
            return privs
    return ""


class VerifyDbRolesAclProofTests(unittest.TestCase):
    def setUp(self):
        self.text = VERIFY_SCRIPT.read_text(encoding="utf-8")

    def test_no_lax_public_substring_checks(self):
        for lax in ('"=X" in acl', '"=x" in acl', '"=r" in acl',
                    '"=a" in acl', '"=w" in acl', '"=d" in acl',
                    '"=X" in facl', "rt_name in acl",
                    "rt_name not in facl", '%s=X" % rt_name'):
            self.assertNotIn(lax, self.text)

    def test_uses_aclexplode_with_coalesce_default(self):
        self.assertIn("aclexplode(coalesce(p.proacl", self.text)
        self.assertIn("aclexplode(coalesce(c.relacl", self.text)
        self.assertIn("acldefault(%s, p.proowner)", self.text)
        self.assertIn("acldefault(%s, c.relowner)", self.text)
        self.assertIn('("f",', self.text)
        self.assertIn('("r",', self.text)
        self.assertIn("e.grantee", self.text)
        self.assertIn("e.privilege_type", self.text)
        self.assertIn("int(g) == 0", self.text)
        self.assertIn("int(rt_oid)", self.text)
        self.assertIn("SELECT oid FROM pg_roles WHERE rolname", self.text)

    def test_preserves_fail_closed_markers(self):
        for marker in ("PUBLIC execute present",
                       "PUBLIC table access present",
                       "runtime EXECUTE missing",
                       "runtime SELECT missing",
                       "runtime write present",
                       "future function scope wrong",
                       "trigger guard must not grant runtime"):
            self.assertIn(marker, self.text)


class AclSemanticsTests(unittest.TestCase):
    RT = "lc_bind_runtime"

    def test_named_execute_is_not_public(self):
        entries = ["lc_bind_runtime=X/postgres"]
        self.assertIn("=X", " ".join(entries))
        self.assertFalse(_has_public_priv(entries, ("X",)))
        self.assertIn("X", _named_privs(entries, self.RT))

    def test_genuine_public_execute_is_caught(self):
        self.assertTrue(_has_public_priv(["=X/postgres"], ("X",)))
        mixed = ["lc_bind_runtime=X/postgres", "=X/postgres"]
        self.assertTrue(_has_public_priv(mixed, ("X",)))
        self.assertIn("X", _named_privs(mixed, self.RT))

    def test_grantor_name_is_not_grantee(self):
        entries = ["=X/lc_bind_runtime"]
        self.assertTrue(_has_public_priv(entries, ("X",)))
        self.assertEqual("", _named_privs(entries, self.RT))

    def test_named_table_select_is_not_public(self):
        entries = ["lc_bind_runtime=r/postgres"]
        for code in ("r", "a", "w", "d"):
            self.assertFalse(_has_public_priv(entries, (code,)))
        self.assertIn("r", _named_privs(entries, self.RT))

    def test_genuine_public_table_access_is_caught(self):
        for code, entry in (("r", "=r/postgres"), ("a", "=a/postgres"),
                            ("w", "=w/postgres"), ("d", "=d/postgres")):
            with self.subTest(code=code):
                self.assertTrue(_has_public_priv([entry], (code,)))
        named = ["lc_bind_runtime=arwd/postgres"]
        for code in ("r", "a", "w", "d"):
            self.assertFalse(_has_public_priv(named, (code,)))
        privs = _named_privs(named, self.RT)
        self.assertIn("r", privs)
        self.assertTrue(any(b in privs for b in ("a", "w", "d")))

    def test_trigger_guard_grantor_substring_is_not_grant(self):
        entries = ["=X/lc_bind_runtime"]
        self.assertIn(self.RT, " ".join(entries))
        self.assertEqual("", _named_privs(entries, self.RT))

    def test_future_scope_denies_public_and_runtime_execute(self):
        owner_only = ["postgres=X/postgres"]
        runtime_grant = ["lc_bind_runtime=X/lc_bind_migration"]
        public = ["=X/lc_bind_migration"]
        self.assertFalse(_has_public_priv(owner_only, ("X",)))
        self.assertEqual("", _named_privs(owner_only, self.RT))
        self.assertIn("X", _named_privs(runtime_grant, self.RT))
        self.assertFalse(_has_public_priv(runtime_grant, ("X",)))
        self.assertTrue(_has_public_priv(public, ("X",)))


def _input_arg_names(argnames, argmodes):
    all_names = list(argnames or [])
    if argmodes is None:
        return all_names
    modes = list(argmodes or [])
    return [nm for nm, md in zip(all_names, modes)
            if str(md).lower() in ("i", "b", "v")]


def _has_forbidden_input(argnames, argmodes):
    text = " ".join(str(v) for v in _input_arg_names(argnames, argmodes)).lower()
    return any(key in text for key in ("amount", "micros", "debit",
                                       "refill", "grant"))


def _parse_search_path(entry):
    text = str(entry)
    if not text.startswith("search_path="):
        return None
    raw = text.split("=", 1)[1]
    return [part.strip().strip('"').strip() for part in raw.split(",")]


class VerifyDbRolesModelProofTests(unittest.TestCase):
    def setUp(self):
        self.text = VERIFY_SCRIPT.read_text(encoding="utf-8")

    def test_input_filter_uses_proargmodes(self):
        self.assertIn("p.proargnames, p.proargmodes", self.text)
        self.assertIn("argmodes is None", self.text)
        self.assertIn('("i", "b", "v")', self.text)
        self.assertIn("in_names", self.text)
        self.assertNotIn('args = " ".join(str(v) for v in (argnames or []))',
                         self.text)
        self.assertIn("function accepts a debit amount", self.text)

    def test_search_path_is_per_function_exact(self):
        self.assertIn('if proname == "model_no_direct"', self.text)
        self.assertIn('elif proname in ("model_reserve_call", "model_finalize_call")',
                      self.text)
        self.assertIn('want_path = ["pg_catalog", "pg_temp"]', self.text)
        self.assertIn('want_path = [schema, "pg_temp"]', self.text)
        self.assertIn("got_paths[0] != want_path", self.text)
        self.assertIn("len(got_paths) != 1", self.text)
        self.assertNotIn('endswith("pg_temp")', self.text)
        self.assertIn("search_path not pinned with pg_temp last", self.text)

    def test_preserves_model_negatives(self):
        for marker in ("function owner mismatch",
                       "reserve and finalize must be SECURITY DEFINER",
                       "trigger guard must not be SECURITY DEFINER",
                       "refill function present",
                       "function accepts a debit amount",
                       "runtime EXECUTE missing"):
            self.assertIn(marker, self.text)


class ModelProofSemanticsTests(unittest.TestCase):
    def test_out_table_column_does_not_trigger(self):
        names = ["p_run_id", "p_stage", "id", "reservation_micros"]
        modes = ["i", "i", "o", "o"]
        self.assertEqual(_input_arg_names(names, modes),
                         ["p_run_id", "p_stage"])
        self.assertFalse(_has_forbidden_input(names, modes))

    def test_null_modes_treats_all_as_input(self):
        self.assertEqual(_input_arg_names(["p_debit_amount"], None),
                         ["p_debit_amount"])
        self.assertTrue(_has_forbidden_input(["p_debit_amount"], None))
        self.assertTrue(_has_forbidden_input(["p_grant_micros"], None))

    def test_inout_and_variadic_are_input(self):
        names = ["p_refill_note", "p_extra", "reservation_micros"]
        modes = ["b", "v", "o"]
        self.assertEqual(_input_arg_names(names, modes),
                         ["p_refill_note", "p_extra"])
        self.assertTrue(_has_forbidden_input(names, modes))
        self.assertFalse(_has_forbidden_input(["ok_in", "reservation_micros"],
                                              ["i", "t"]))

    def test_search_path_parsing_is_exact(self):
        self.assertEqual(_parse_search_path("search_path=pg_catalog, pg_temp"),
                         ["pg_catalog", "pg_temp"])
        self.assertEqual(_parse_search_path('search_path="public", pg_temp'),
                         ["public", "pg_temp"])
        self.assertNotEqual(_parse_search_path("search_path=public, pg_temp, pg_extra"),
                            ["public", "pg_temp"])
        self.assertNotEqual(_parse_search_path("search_path=pg_temp, public"),
                            ["public", "pg_temp"])
        self.assertIsNone(_parse_search_path("work_mem=4096"))


class SqlFileFunctionDefaultTests(unittest.TestCase):
    def setUp(self):
        self.text = SQL_FILE.read_text(encoding="utf-8")

    def test_global_public_revoke_without_blanket_runtime_grant(self):
        self.assertIn(
            "ALTER DEFAULT PRIVILEGES FOR ROLE :migration_user "
            "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC", self.text)
        self.assertNotIn("GRANT EXECUTE ON FUNCTIONS", self.text)

    def test_table_sequence_defaults_retained(self):
        self.assertIn(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES", self.text)
        self.assertIn(
            "GRANT USAGE, SELECT ON ALL SEQUENCES", self.text)
        self.assertIn("ALTER DEFAULT PRIVILEGES FOR ROLE :migration_user",
                      self.text)


class VerifyFutureFunctionProofTests(unittest.TestCase):
    def setUp(self):
        self.text = VERIFY_SCRIPT.read_text(encoding="utf-8")

    def test_future_proof_denies_public_and_runtime(self):
        self.assertIn("SECURITY DEFINER", self.text)
        self.assertIn("if ff_public or ff_runtime:", self.text)
        self.assertNotIn("or not ff_runtime", self.text)
        self.assertIn("future function scope wrong", self.text)

    def test_static_forbids_blanket_function_grant(self):
        self.assertIn("missing global function PUBLIC revoke", self.text)
        self.assertIn("blanket future function runtime grant must be absent",
                      self.text)
        self.assertNotIn("missing per-schema function runtime grant",
                         self.text)

    def test_verify_completion_requires_both_signals(self):
        self.assertIn('*"VERIFY COMPLETE"*', self.text)
        self.assertIn('*"revision=006"*', self.text)
        self.assertIn("missed VERIFY COMPLETE", self.text)
        self.assertIn("missed revision=006", self.text)
        self.assertNotIn('*"VERIFY COMPLETE"*|*"revision=006"*', self.text)


if __name__ == "__main__":
    unittest.main()
