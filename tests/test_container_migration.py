"""Static wiring for separate migration-before-API container startup.

Socket-free and offline only. Guards the regression behind the published
CI container failure where the API health check reset 60 times: a fresh
named volume has no schema, the runtime API image intentionally never
migrates, so the local Podman sequence must build the existing migration
image and run it once before the runtime API starts. Also guards that
the full browser verifier cannot omit a spec again by naming files.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PODMAN = ROOT / "scripts" / "podman-local.sh"
ENTRYPOINT = ROOT / "containers" / "api-entrypoint.sh"
API_IMAGE = ROOT / "containers" / "api.Containerfile"
MIGRATE_IMAGE = ROOT / "containers" / "migrate.Containerfile"
VERIFY = ROOT / "scripts" / "verify-release-candidate.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "verify.yml"
HARNESS = ROOT / "scripts" / "verify-container-path.py"


class MigrationBeforeApiTests(unittest.TestCase):
    def test_build_includes_migration_image(self):
        text = PODMAN.read_text(encoding="utf-8")
        self.assertIn("containers/migrate.Containerfile", text)
        self.assertIn("localhost/launchcrew-migrate:demo", text)

    def test_migration_runs_before_runtime_api(self):
        text = PODMAN.read_text(encoding="utf-8")
        migrate_pos = text.index("launchcrew-migrate")
        api_pos = text.index("--name launchcrew-api")
        self.assertLess(migrate_pos, api_pos)
        # The migration and the API must reach the same pod database.
        self.assertIn("DATABASE_URL=postgresql://postgres@127.0.0.1:5432/launchcrew", text)

    def test_migration_uses_explicit_local_db_mode(self):
        text = PODMAN.read_text(encoding="utf-8")
        self.assertIn("LAUNCHCREW_DB_TLS_MODE=local", text)
        migrate_line = next(line for line in text.splitlines() if "launchcrew-migrate" in line)
        self.assertNotIn("verify-full", migrate_line)

    def test_migration_failure_collects_diagnostics(self):
        text = PODMAN.read_text(encoding="utf-8")
        self.assertIn("migration failed", text)
        self.assertIn("diag", text)


class RuntimeNoDdlTests(unittest.TestCase):
    def test_api_entrypoint_never_migrates(self):
        text = ENTRYPOINT.read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertNotIn("alembic", lowered)
        self.assertNotIn("upgrade head", lowered)
        self.assertNotIn("create table", lowered)

    def test_api_image_starts_entrypoint_only(self):
        text = API_IMAGE.read_text(encoding="utf-8")
        self.assertIn('CMD ["/usr/local/bin/api-entrypoint.sh"]', text)
        self.assertNotIn("alembic upgrade", text.lower())
        self.assertNotIn("alembic,", text.lower())

    def test_migrate_image_only_migrates(self):
        text = MIGRATE_IMAGE.read_text(encoding="utf-8")
        self.assertIn('CMD ["/opt/venv/bin/alembic", "upgrade", "head"]', text)
        self.assertNotIn("uvicorn", text.lower())
        self.assertNotIn("server.js", text)


class VerifierGlobTests(unittest.TestCase):
    def test_browser_runs_full_glob_without_named_specs(self):
        text = VERIFY.read_text(encoding="utf-8")
        self.assertIn("pnpm --dir web test:e2e", text)
        self.assertNotIn("-- tests/e2e/", text)

    def test_memory_learned_spec_exists_for_glob(self):
        specs = sorted(path.name for path in (ROOT / "web" / "tests" / "e2e").glob("*.spec.ts"))
        self.assertIn("memory-learned.spec.ts", specs)
        self.assertIn("integration-acceptance.spec.ts", specs)
        self.assertIn("stage-selection.spec.ts", specs)
        self.assertIn("review.spec.ts", specs)


class ContainerDiagnosticsTests(unittest.TestCase):
    def test_ci_collects_sanitized_diagnostics(self):
        text = WORKFLOW.read_text(encoding="utf-8") + "\n" + PODMAN.read_text(encoding="utf-8")
        self.assertIn("diag", text)
        self.assertIn("container-diag.log", text)
        self.assertNotIn("podman inspect", text)
        self.assertNotIn("printenv", text)

    def test_cleanup_touches_only_owned_pod(self):
        script = PODMAN.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("p pod rm -f launchcrew-stack", script)
        self.assertNotIn("volume rm", script + workflow)
        self.assertNotIn("image rm", script + workflow)
        self.assertNotIn("system prune", script + workflow)
        self.assertNotIn("launchcrew-test-db", script)


class ContainerPathHarnessTests(unittest.TestCase):
    def test_harness_covers_gated_path_through_proxy(self):
        text = HARNESS.read_text(encoding="utf-8")
        self.assertIn("--api-base", text)
        self.assertIn("--web-base", text)
        self.assertIn("/api/runs/", text)
        self.assertIn("/approve", text)
        self.assertIn("/export", text)
        self.assertIn("422", text)
        self.assertIn("submit_attempted", text)

    def test_harness_uses_stdlib_only(self):
        text = HARNESS.read_text(encoding="utf-8")
        self.assertIn("urllib.request", text)
        self.assertNotIn("import requests", text)
        self.assertNotIn("os.environ", text)


if __name__ == "__main__":
    unittest.main()
