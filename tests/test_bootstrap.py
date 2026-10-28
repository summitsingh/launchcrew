"""Offline staged-bootstrap tests with a fake AWS command fixture.

No test contacts AWS. The fake AWS script logs calls and returns canned
responses based on FAKE_MODE. Dry-run must make zero calls. Confirm path must
verify caller, stack tags, and secret ARN ownership before any mutation, must
order infra before images before dbroles before migrate before enable, must
require STOPPED exit 0 for one-off tasks with schema proof before enabling
fixed-count services, must refuse placeholder images, and must never call
GetSecretValue.
"""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

BOOTSTRAP = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "bootstrap.sh"
TEMPLATE = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "fargate.yaml"
PARAMS = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "parameters.example.json"

ACCOUNT = "111122223333"
REGION = "us-east-1"
STACK = "launchcrew-demo"
SECRET_RT = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-runtime-AbCdEf"
SECRET_MG = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-migration-GhIjKl"
SECRET_MASTER = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-master-MnOpQr"


def image(repo, tag="abc123"):
    return f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{repo}:{tag}"


FAKE_AWS = """#!/bin/sh
LOG="${FAKE_AWS_LOG:-/dev/null}"
printf '%s\\n' "$*" >>"$LOG"
MODE="${FAKE_MODE:-success}"
if [ "$1" = "sts" ] && [ "$2" = "get-caller-identity" ]; then
  printf '%s\\n' "${FAKE_CALLER:-111122223333}"
  exit 0
fi
if [ "$1" = "secretsmanager" ] && [ "$2" = "describe-secret" ]; then
  if [ "$MODE" = "secret_auth_fail" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeSecret operation: not authorized" >&2
    exit 254
  fi
  printf 'arn:aws:secretsmanager:us-east-1:111122223333:secret:launchcrew-x\\n'
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stacks" ]; then
  case "$*" in
    *Project*)
      if [ "$MODE" = "tag_mismatch" ]; then printf 'Other\\n'; exit 0; fi
      printf '%s\\n' "${FAKE_PROJECT:-LaunchCrew}"
      exit 0 ;;
    *Environment*)
      printf '%s\\n' "${FAKE_ENV:-demo}"
      exit 0 ;;
  esac
  echo "fake-aws: unexpected describe-stacks query" >&2
  exit 2
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stack-resource" ]; then
  case "$*" in
    *BootstrapTaskDefinition*) printf 'arn:aws:ecs:us-east-1:111122223333:task-definition/launchcrew-demo-bootstrap:1\\n'; exit 0 ;;
    *MigrationTaskDefinition*) printf 'arn:aws:ecs:us-east-1:111122223333:task-definition/launchcrew-demo-migration:1\\n'; exit 0 ;;
    *PrivateSubnetA*) printf 'subnet-aaa\\n'; exit 0 ;;
    *PrivateSubnetB*) printf 'subnet-bbb\\n'; exit 0 ;;
    *ApiSecurityGroup*) printf 'sg-ccc\\n'; exit 0 ;;
  esac
  echo "fake-aws: unexpected resource lookup: $*" >&2
  exit 2
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "deploy" ]; then
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "wait" ]; then
  exit 0
fi
if [ "$1" = "ecr" ] && [ "$2" = "batch-get-image" ]; then
  if [ "$MODE" = "image_missing" ]; then
    echo "An error occurred (ImageNotFoundException) when calling the BatchGetImage operation: image not found" >&2
    exit 254
  fi
  printf '{"imageManifest":"{}"}\\n'
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "run-task" ]; then
  COUNT_FILE="${FAKE_COUNT_FILE:-/dev/null}"
  n=0
  if [ -f "$COUNT_FILE" ]; then n="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"; fi
  n=$((n + 1))
  printf '%s' "$n" >"$COUNT_FILE" 2>/dev/null || true
  printf 'arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task%03d\\n' "$n"
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "wait" ]; then
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-tasks" ]; then
  COUNT_FILE="${FAKE_COUNT_FILE:-/dev/null}"
  n=0
  if [ -f "$COUNT_FILE" ]; then n="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"; fi
  if [ "$MODE" = "migrate_fail" ] && [ "$n" -ge 2 ]; then
    printf '1\\n'
    exit 0
  fi
  printf '0\\n'
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-services" ]; then
  if [ "$MODE" = "enable_wrong" ]; then printf '2\\n'; exit 0; fi
  printf '1\\n'
  exit 0
fi
echo "fake-aws: unexpected call: $*" >&2
exit 2
"""


class BootstrapHarness(unittest.TestCase):
    def run_bootstrap(self, args, mode="success", extra_env=None):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            log = Path(tmp) / "calls.log"
            log.write_text("", encoding="utf-8")
            params = Path(tmp) / "params.json"
            params.write_text("[]", encoding="utf-8")
            count = Path(tmp) / "count"
            count.write_text("0", encoding="utf-8")
            env = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                env.pop(key, None)
            env["AWS_BIN"] = str(fake)
            env["FAKE_AWS_LOG"] = str(log)
            env["FAKE_MODE"] = mode
            env["FAKE_COUNT_FILE"] = str(count)
            if extra_env:
                env.update(extra_env)
            full = list(args)
            if "--parameters-file" not in full:
                full += ["--parameters-file", str(params)]
            result = subprocess.run(
                [str(BOOTSTRAP), *full], capture_output=True, text=True,
                env=env, check=False)
            calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
            return result, calls

    def base_args(self, **overrides):
        args = {
            "--stack-name": STACK,
            "--expected-account": ACCOUNT,
            "--expected-region": REGION,
            "--api-image": image("launchcrew-api"),
            "--web-image": image("launchcrew-web"),
            "--web-proxy-image": image("launchcrew-web-proxy"),
            "--migration-image": image("launchcrew-migration"),
            "--bootstrap-image": image("launchcrew-bootstrap"),
            "--runtime-secret-arn": SECRET_RT,
            "--migration-secret-arn": SECRET_MG,
            "--master-secret-arn": SECRET_MASTER,
        }
        args.update(overrides)
        flat = []
        for key, value in args.items():
            flat += [key, value]
        return ["--confirm", *flat]


class DryRunTests(BootstrapHarness):
    def test_dry_run_makes_zero_calls(self):
        result, calls = self.run_bootstrap([])
        self.assertEqual(result.returncode, 0)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("no AWS call", result.stdout)
        self.assertEqual(calls, [])

    def test_dry_run_lists_ordered_phases(self):
        result, _ = self.run_bootstrap([])
        for phase in ("infra", "images", "dbroles", "migrate", "enable"):
            self.assertIn(phase, result.stdout)


class OwnershipTests(BootstrapHarness):
    def test_caller_mismatch_refused_before_mutation(self):
        result, calls = self.run_bootstrap(
            self.base_args(), extra_env={"FAKE_CALLER": "999988887777"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused", result.stderr)
        self.assertTrue(any("get-caller-identity" in call for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_tag_mismatch_refused_with_no_task(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="tag_mismatch")
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused", result.stderr)
        self.assertFalse(any("run-task" in call for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))

    def test_secret_region_mismatch_refused_without_metadata_call(self):
        bad = f"arn:aws:secretsmanager:eu-west-1:{ACCOUNT}:secret:launchcrew-runtime-Xx"
        result, calls = self.run_bootstrap(self.base_args(**{"--runtime-secret-arn": bad}))
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused", result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_secret_auth_failure_is_not_absence(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="secret_auth_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("authorization or API failure", combined)
        self.assertIn("Never probed production secret values", combined)
        self.assertFalse(any("GetSecretValue" in call for call in calls))


class PhaseOrderingTests(BootstrapHarness):
    def test_full_run_orders_infra_before_tasks_before_enable(self):
        result, calls = self.run_bootstrap(self.base_args())
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP COMPLETE", result.stdout)
        deploy_false = next(i for i, call in enumerate(calls)
                            if "deploy " in call and "EnableServices=false" in call)
        first_run = next(i for i, call in enumerate(calls) if "run-task" in call)
        deploy_true = next(i for i, call in enumerate(calls)
                           if "deploy " in call and "EnableServices=true" in call)
        self.assertLess(deploy_false, first_run)
        self.assertLess(first_run, deploy_true)
        run_tasks = [call for call in calls if "run-task" in call]
        self.assertEqual(len(run_tasks), 3)

    def test_enable_verifies_fixed_count_one_each(self):
        result, calls = self.run_bootstrap(self.base_args())
        self.assertEqual(result.returncode, 0)
        self.assertIn("desiredCount 1", result.stdout)
        self.assertTrue(any("describe-services" in call for call in calls))

    def test_migration_nonzero_exit_blocks_enable(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="migrate_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("did not STOP with exit 0", combined)
        self.assertFalse(any("EnableServices=true" in call for call in calls))
        self.assertNotIn("BOOTSTRAP COMPLETE", result.stdout)

    def test_placeholder_image_refused_with_no_task(self):
        result, calls = self.run_bootstrap(
            self.base_args(**{"--bootstrap-image": "REPLACE_WITH_ECR_BOOTSTRAP_IMAGE_URI"}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("placeholder", result.stderr)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_image_from_unowned_repo_refused(self):
        result, calls = self.run_bootstrap(
            self.base_args(**{"--api-image": image("other-project-api")}))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_missing_image_refused_with_no_task(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="image_missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_no_get_secret_value_in_any_call(self):
        result, calls = self.run_bootstrap(self.base_args())
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any("GetSecretValue" in call for call in calls))

    def test_enable_refuses_wrong_count(self):
        result, _ = self.run_bootstrap(self.base_args(), mode="enable_wrong")
        self.assertNotEqual(result.returncode, 0)

    def test_single_phase_does_not_enable(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "migrate"])
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any("EnableServices=true" in call for call in calls))


class TemplateStagingTests(unittest.TestCase):
    def setUp(self):
        self.text = TEMPLATE.read_text(encoding="utf-8")
        self.example = PARAMS.read_text(encoding="utf-8")
        root = TEMPLATE.parents[1]
        self.bootstrap_sh = (root / "deploy" / "aws" / "bootstrap.sh").read_text(encoding="utf-8")
        self.controller = (root / "containers" / "bootstrap-db.Containerfile").read_text(encoding="utf-8")

    def test_services_default_to_zero_until_enabled(self):
        self.assertIn("Default: 'false'", self.text)
        self.assertIn("DesiredCount: !If [ServicesEnabled, 1, 0]", self.text)
        self.assertNotIn("DesiredCount: 1", self.text)

    def test_no_autoscaling_controller(self):
        self.assertNotIn("ApplicationAutoScaling", self.text)
        self.assertNotIn("ScalingPolicy", self.text)
        self.assertNotIn("ScalableTarget", self.text)

    def test_budget_alerts_configured_not_empty(self):
        self.assertNotIn("NotificationsWithSubscribers: []", self.text)
        self.assertIn("BudgetNotifyConfigured", self.text)
        self.assertIn("NotificationType: ACTUAL", self.text)
        self.assertIn("Threshold: 80", self.text)
        self.assertIn("NotificationType: FORECASTED", self.text)
        self.assertIn("BudgetTopic", self.text)
        self.assertIn("Protocol: email", self.text)

    def test_bootstrap_role_is_least_privilege(self):
        self.assertIn("BootstrapTaskRole", self.text)
        self.assertIn("bootstrap-db-roles-only", self.text)
        self.assertIn("secretsmanager:GetSecretValue", self.text)
        self.assertNotIn("secretsmanager:PutSecretValue", self.text)
        self.assertNotIn("Resource: '*'", self.text)
        self.assertNotIn('Resource: "*"', self.text)

    def test_bootstrap_task_uses_verify_full_and_pinned_bundle(self):
        self.assertIn("BootstrapTaskDefinition", self.text)
        self.assertIn("BootstrapImageUri", self.text)
        self.assertIn("LAUNCHCREW_DB_TLS_MODE, Value: verify-full", self.text)
        self.assertIn("DATABASE_SSL_ROOTCERT, Value: /app/rds-ca-bundle.pem", self.text)
        self.assertIn("launchcrew_runtime", self.text)
        self.assertIn("launchcrew_migration", self.text)

    def test_migration_stays_only_schema_path(self):
        self.assertIn("MigrationTaskDefinition", self.text)
        self.assertNotIn("ALTER ROLE", self.text)
        self.assertIn("assignPublicIp=DISABLED", self.bootstrap_sh)

    def test_parameters_example_matches_template(self):
        for key in ("BootstrapImageUri", "EnableServices", "BudgetNotifyEmail"):
            self.assertIn(key, self.example)
        self.assertIn('"false"', self.example)

    def test_bootstrap_image_pins_ca_bundle(self):
        self.assertIn("RDS_CA_SHA256=b1711d12bae51838581281e23b6cb97b1074016873b4dafc80ed14002462dd77", self.controller)
        self.assertIn("USER 10001:10001", self.controller)
        self.assertNotIn("alembic", self.controller.lower())

    def test_controller_never_fetches_secret_values(self):
        self.assertIn("describe-secret", self.bootstrap_sh)
        self.assertNotIn("GetSecretValue", self.bootstrap_sh)
        self.assertIn("value never fetched", self.bootstrap_sh)


if __name__ == "__main__":
    unittest.main()
