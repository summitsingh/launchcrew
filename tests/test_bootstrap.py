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
  SECRET_ID=""
  PREV=""
  for ARG in "$@"; do
    if [ "$PREV" = "--secret-id" ]; then SECRET_ID="$ARG"; fi
    PREV="$ARG"
  done
  case "$*" in
    *"--query ARN"*)
      if [ "$MODE" = "secret_arn_mismatch" ]; then
        printf 'arn:aws:secretsmanager:us-east-1:111122223333:secret:other-secret-ZzZzZz\\n'
        exit 0
      fi
      printf '%s\\n' "$SECRET_ID"
      exit 0 ;;
  esac
  case "$*" in
    *"Key=='Project'"*)
      if [ "$MODE" = "secret_tag_mismatch" ]; then printf 'Other\\n'; exit 0; fi
      printf '%s\\n' "${FAKE_PROJECT:-LaunchCrew}"
      exit 0 ;;
    *"Key=='Environment'"*)
      printf '%s\\n' "${FAKE_ENV:-demo}"
      exit 0 ;;
  esac
  echo "fake-aws: unexpected describe-secret query: $*" >&2
  exit 2
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stacks" ]; then
  if [ "$MODE" = "stack_auth" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeStacks operation: not authorized" >&2
    exit 254
  fi
  if [ "$MODE" = "stack_missing" ]; then
    echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id launchcrew-demo does not exist" >&2
    exit 254
  fi
  STATUS="CREATE_COMPLETE"
  PROJECT="${FAKE_PROJECT:-LaunchCrew}"
  STACKID="arn:aws:cloudformation:us-east-1:111122223333:stack/launchcrew-demo/abc123"
  if [ "$MODE" = "tag_mismatch" ]; then PROJECT="Other"; fi
  if [ "$MODE" = "status_bad" ]; then STATUS="UPDATE_ROLLBACK_FAILED"; fi
  if [ "$MODE" = "stack_id_mismatch" ]; then
    STACKID="arn:aws:cloudformation:us-east-1:999988887777:stack/launchcrew-demo/abc123"
  fi
  case "$*" in
    *"StackStatus"*) printf '%s\\n' "$STATUS"; exit 0 ;;
  esac
  printf '{"Stacks":[{"StackId":"%s","StackStatus":"%s","Tags":[{"Key":"Project","Value":"%s"},{"Key":"Environment","Value":"demo"}],"Parameters":[{"ParameterKey":"EnableServices","ParameterValue":"false"}]}]}\\n' "$STACKID" "$STATUS" "$PROJECT"
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stack-resource" ]; then
  case "$*" in
    *BootstrapTaskDefinition*) printf 'arn:aws:ecs:us-east-1:111122223333:task-definition/launchcrew-demo-bootstrap:1\\n'; exit 0 ;;
    *MigrationTaskDefinition*) printf 'arn:aws:ecs:us-east-1:111122223333:task-definition/launchcrew-demo-migration:1\\n'; exit 0 ;;
    *VerifyTaskDefinition*) printf 'arn:aws:ecs:us-east-1:111122223333:task-definition/launchcrew-demo-verify:1\\n'; exit 0 ;;
    *PublicSubnetA*) printf 'subnet-aaa\\n'; exit 0 ;;
    *PublicSubnetB*) printf 'subnet-bbb\\n'; exit 0 ;;
    *JobSecurityGroup*) printf 'sg-ccc\\n'; exit 0 ;;
  esac
  echo "fake-aws: unexpected resource lookup: $*" >&2
  exit 2
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "deploy" ]; then
  case "$*" in
    *"--parameter-file"*) echo "Unknown options: --parameter-file" >&2; exit 2 ;;
  esac
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "wait" ]; then
  if [ "$MODE" = "wait_fail" ]; then
    echo "Waiter encountered a terminal failure state" >&2
    exit 1
  fi
  exit 0
fi
if [ "$1" = "ecr" ] && [ "$2" = "batch-get-image" ]; then
  if [ "$MODE" = "image_missing" ]; then
    echo "An error occurred (ImageNotFoundException) when calling the BatchGetImage operation: image not found" >&2
    exit 254
  fi
  case "$*" in
    *"imageDigest"*)
      if [ "$MODE" = "image_digest_none" ]; then printf 'None\\n'; exit 0; fi
      printf 'sha256:abc123\\n'; exit 0 ;;
    *"failures"*)
      if [ "$MODE" = "image_failures" ]; then printf '1\\n'; exit 0; fi
      printf '0\\n'; exit 0 ;;
  esac
  printf '{"images":[{"imageDigest":"sha256:abc123"}],"failures":[]}\\n'
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "run-task" ]; then
  COUNT_FILE="${FAKE_COUNT_FILE:-/dev/null}"
  n=0
  if [ -f "$COUNT_FILE" ]; then n="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"; fi
  n=$((n + 1))
  printf '%s' "$n" >"$COUNT_FILE" 2>/dev/null || true
  TASKDEF=""
  PREV=""
  for ARG in "$@"; do
    if [ "$PREV" = "--task-definition" ]; then TASKDEF="$ARG"; fi
    PREV="$ARG"
  done
  printf '%s\\n' "$TASKDEF" >>"${FAKE_TASKDEF_FILE:-/dev/null}" 2>/dev/null || true
  if [ "$MODE" = "runtask_empty" ]; then printf '{"tasks":[],"failures":[]}\\n'; exit 0; fi
  if [ "$MODE" = "runtask_failures" ]; then printf '{"tasks":[],"failures":[{"arn":"x","reason":"FAIL"}]}\\n'; exit 0; fi
  printf '{"tasks":[{"taskArn":"arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task%03d"}],"failures":[]}\\n' "$n"
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "wait" ]; then
  if [ "$MODE" = "wait_fail" ]; then
    echo "Waiter encountered a terminal failure state" >&2
    exit 1
  fi
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-tasks" ]; then
  TASKDEF="$(tail -n 1 "${FAKE_TASKDEF_FILE:-/dev/null}" 2>/dev/null || true)"
  EXIT0=0
  if [ "$MODE" = "migrate_fail" ]; then
    case "$TASKDEF" in *migration*) EXIT0=1 ;; esac
  fi
  printf '{"tasks":[{"taskArn":"arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task001","clusterArn":"arn:aws:ecs:us-east-1:111122223333:cluster/launchcrew-demo","taskDefinitionArn":"%s","lastStatus":"STOPPED","containers":[{"name":"c1","essential":true,"lastStatus":"STOPPED","exitCode":%d},{"name":"c2","essential":true,"lastStatus":"STOPPED","exitCode":0}]}],"failures":[]}\\n' "$TASKDEF" "$EXIT0"
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-task-definition" ]; then
  if [ "$MODE" = "taskdef_image_mismatch" ]; then
    printf '111122223333.dkr.ecr.us-east-1.amazonaws.com/wrong-repo:bad\\n'
    exit 0
  fi
  case "$*" in
    *"name=='api'"*) printf '%s\\n' "$FAKE_API_IMAGE" ;;
    *"name=='web-app'"*) printf '%s\\n' "$FAKE_WEB_IMAGE" ;;
    *"name=='web-proxy'"*) printf '%s\\n' "$FAKE_WEB_PROXY_IMAGE" ;;
    *"name=='migration'"*) printf '%s\\n' "$FAKE_MIGRATION_IMAGE" ;;
    *"name=='bootstrap-db-roles'"*) printf '%s\\n' "$FAKE_BOOTSTRAP_IMAGE" ;;
    *) echo "fake-aws: unexpected describe-task-definition: $*" >&2; exit 2 ;;
  esac
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-services" ]; then
  if [ "$MODE" = "enable_wrong" ]; then printf '2\\t0\\n'; exit 0; fi
  printf '1\\t1\\n'; exit 0
fi
echo "fake-aws: unexpected call: $*" >&2
exit 2
"""



class BootstrapHarness(unittest.TestCase):
    PARAM_KEYS = {
        "--api-image": "ApiImageUri",
        "--web-image": "WebImageUri",
        "--web-proxy-image": "WebProxyImageUri",
        "--migration-image": "MigrationImageUri",
        "--bootstrap-image": "BootstrapImageUri",
        "--runtime-secret-arn": "RuntimeDbUrlSecretArn",
        "--migration-secret-arn": "MigrationDbUrlSecretArn",
        "--master-secret-arn": "MasterDbPasswordSecretArn",
    }
    IMAGE_ENV = {
        "--api-image": "FAKE_API_IMAGE",
        "--web-image": "FAKE_WEB_IMAGE",
        "--web-proxy-image": "FAKE_WEB_PROXY_IMAGE",
        "--migration-image": "FAKE_MIGRATION_IMAGE",
        "--bootstrap-image": "FAKE_BOOTSTRAP_IMAGE",
    }

    def run_bootstrap(self, args, mode="success", extra_env=None,
                      params_overrides=None):
        import json as _json
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            log = Path(tmp) / "calls.log"
            log.write_text("", encoding="utf-8")
            count = Path(tmp) / "count"
            count.write_text("0", encoding="utf-8")
            taskdefs = Path(tmp) / "taskdefs"
            taskdefs.write_text("", encoding="utf-8")
            given = {}
            items = list(args)
            index = 0
            while index < len(items):
                key = items[index]
                if key in self.PARAM_KEYS and index + 1 < len(items):
                    given[self.PARAM_KEYS[key]] = items[index + 1]
                    index += 2
                else:
                    index += 1
            if params_overrides:
                given.update(params_overrides)
            params = Path(tmp) / "params.json"
            params.write_text(_json.dumps(
                [{"ParameterKey": key, "ParameterValue": value}
                 for key, value in sorted(given.items())]), encoding="utf-8")
            env = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                env.pop(key, None)
            env["AWS_BIN"] = str(fake)
            env["FAKE_AWS_LOG"] = str(log)
            env["FAKE_MODE"] = mode
            env["FAKE_COUNT_FILE"] = str(count)
            env["FAKE_TASKDEF_FILE"] = str(taskdefs)
            for flag, name in self.IMAGE_ENV.items():
                for pos, item in enumerate(items):
                    if item == flag and pos + 1 < len(items):
                        env[name] = items[pos + 1]
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

    def minimal_infra_args(self):
        return ["--confirm",
                "--stack-name", STACK,
                "--expected-account", ACCOUNT,
                "--expected-region", REGION]


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

    def test_slash_free_secret_arn_is_accepted(self):
        result, _ = self.run_bootstrap(self.base_args())
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_malformed_secret_arn_refused(self):
        bad = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:"
        result, calls = self.run_bootstrap(self.base_args(**{"--runtime-secret-arn": bad}))
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused", result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_returned_secret_arn_mismatch_refused(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="secret_arn_mismatch")
        self.assertEqual(result.returncode, 1)
        self.assertIn("different ARN", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_secret_tag_mismatch_refused(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="secret_tag_mismatch")
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused", result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_stack_id_account_mismatch_refused(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="stack_id_mismatch")
        self.assertEqual(result.returncode, 1)
        self.assertIn("StackId", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_stack_auth_failure_is_not_absence(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="stack_auth")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("authorization or API failure, not absence", combined)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_missing_stack_allows_fresh_infra_create(self):
        result, calls = self.run_bootstrap(
            [*self.minimal_infra_args(), "--phase", "infra"], mode="stack_missing")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("fresh create", combined)
        self.assertTrue(any("deploy " in call and "--tags" in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_missing_stack_refuses_enable(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "enable"], mode="stack_missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not exist", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))


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
        self.assertIn("terminal proof is EXIT_NONZERO", combined)
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

    def test_deploy_never_uses_parameter_file_option(self):
        result, calls = self.run_bootstrap(self.base_args())
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any("--parameter-file" in call for call in calls))

    def test_params_mismatch_refused(self):
        result, calls = self.run_bootstrap(
            self.base_args(), params_overrides={"ApiImageUri": image("launchcrew-api-tampered")})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validating one set", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_wait_failure_still_requires_stack_status(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="wait_fail")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP COMPLETE", result.stdout)

    def test_bad_status_refused_despite_wait_success(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="status_bad")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stack status is", result.stdout + result.stderr)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_ecr_failure_field_refused(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="image_failures")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failures", result.stdout + result.stderr)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_ecr_missing_digest_refused(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="image_digest_none")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no digest", result.stdout + result.stderr)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_image_without_tag_refused(self):
        untagged = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/launchcrew-api"
        result, calls = self.run_bootstrap(
            self.base_args(**{"--api-image": untagged}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit tag", result.stdout + result.stderr)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_taskdef_image_mismatch_refused(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="taskdef_image_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("task definition references", result.stdout + result.stderr)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_runtask_failure_refused(self):
        result, calls = self.run_bootstrap(self.base_args(), mode="runtask_failures")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run-task reported failures", result.stdout + result.stderr)
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_enable_alone_resumes_without_prior_phases(self):
        result, calls = self.run_bootstrap([*self.base_args(), "--phase", "enable"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP COMPLETE", result.stdout)
        self.assertTrue(any("EnableServices=true" in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_infra_alone_needs_no_images_or_secrets(self):
        result, calls = self.run_bootstrap([*self.minimal_infra_args(), "--phase", "infra"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertTrue(any("deploy " in call and "EnableServices=false" in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_single_phase_does_not_enable(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "migrate"])
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any("EnableServices=true" in call for call in calls))


class TemplateStagingTests(unittest.TestCase):
    def setUp(self):
        self.text = TEMPLATE.read_text(encoding="utf-8")
        self.example = PARAMS.read_text(encoding="utf-8")
        root = TEMPLATE.parents[2]
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

    def test_execution_roles_are_split_and_least_scope(self):
        for role in ("ApiExecutionRole", "WebExecutionRole",
                     "MigrationExecutionRole", "BootstrapExecutionRole",
                     "VerifyExecutionRole"):
            self.assertIn(role, self.text)
        self.assertEqual(self.text.count("secretsmanager:GetSecretValue"), 5)
        self.assertIn("api-execution-secrets-only", self.text)
        self.assertIn("verify-execution-secrets-only", self.text)
        self.assertIn("AmazonECSTaskExecutionRolePolicy", self.text)
        self.assertNotIn("secretsmanager:PutSecretValue", self.text)
        self.assertNotIn("Resource: '*'", self.text)
        self.assertNotIn('Resource: "*"', self.text)

    def test_task_roles_carry_no_secret_fetch(self):
        for role in ("ApiTaskRole", "WebTaskRole", "MigrationTaskRole",
                     "BootstrapTaskRole", "VerifyTaskRole"):
            self.assertIn(role, self.text)
        task_start = self.text.index("ApiTaskRole:")
        task_roles = self.text[task_start:]
        self.assertNotIn("secretsmanager:GetSecretValue", task_roles)

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
        self.assertIn("assignPublicIp=ENABLED", self.bootstrap_sh)
        self.assertIn("PublicSubnetA", self.bootstrap_sh)
        self.assertIn("JobSecurityGroup", self.bootstrap_sh)
        self.assertNotIn("assignPublicIp=DISABLED", self.bootstrap_sh)

    def test_verify_task_is_runtime_url_only(self):
        self.assertIn("VerifyTaskDefinition", self.text)
        verify_start = self.text.index("VerifyTaskDefinition:")
        verify_body = self.text[verify_start:]
        next_resource = verify_body.find("\n  LoadBalancer:")
        verify_body = verify_body[:next_resource]
        self.assertIn("RUNTIME_DB_URL", verify_body)
        self.assertIn("'--verify'", verify_body)
        self.assertNotIn("MASTER_DB_PASSWORD", verify_body)
        self.assertNotIn("MIGRATION_DB_URL", verify_body)

    def test_budget_topic_allows_only_budgets_publish(self):
        self.assertIn("BudgetTopicPolicy", self.text)
        self.assertIn("budgets.amazonaws.com", self.text)
        self.assertIn("aws:SourceAccount", self.text)
        self.assertIn("aws:SourceArn", self.text)

    def test_parameters_example_matches_template(self):
        for key in ("BootstrapImageUri", "EnableServices", "BudgetNotifyEmail"):
            self.assertIn(key, self.example)
        self.assertIn('"false"', self.example)

    def test_bootstrap_image_pins_ca_bundle(self):
        self.assertIn("RDS_CA_SHA256=b1711d12bae51838581281e23b6cb97b1074016873b4dafc80ed14002462dd77", self.controller)
        self.assertIn("USER 10001:10001", self.controller)
        code_lines = [line for line in self.controller.splitlines()
                      if not line.strip().startswith("#")]
        self.assertNotIn("alembic", "\n".join(code_lines).lower())

    def test_job_egress_needs_no_inbound(self):
        job_start = self.text.index("JobSecurityGroup:")
        job_body = self.text[job_start:]
        next_resource = job_body.find("\n  ApiEcrRepo:")
        job_body = job_body[:next_resource]
        self.assertNotIn("SecurityGroupIngress", job_body)
        self.assertIn("SecurityGroupEgress", job_body)
        self.assertIn("DbSecurityGroup", job_body)

    def test_controller_never_fetches_secret_values(self):
        self.assertIn("describe-secret", self.bootstrap_sh)
        code_lines = [line for line in self.bootstrap_sh.splitlines()
                      if not line.strip().startswith("#")]
        code = "\n".join(code_lines)
        self.assertIn("describe-secret", code)
        self.assertNotIn("get-secret-value", code.lower())
        self.assertIn("value never fetched", self.bootstrap_sh)


if __name__ == "__main__":
    unittest.main()
