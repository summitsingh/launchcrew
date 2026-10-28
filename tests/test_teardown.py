"""Offline teardown tests with a fake AWS command fixture.

No test contacts AWS. The fake AWS script logs calls and returns canned
responses based on FAKE_MODE. Dry-run must make zero calls. Confirm path
must refuse account or tag mismatch before any delete, must verify terminal
absence via authoritative not-found or a DELETE_COMPLETE record for the
exact stack ID, must distinguish DELETE_SKIPPED retained resources from
complete cleanup, and must never treat auth or API failure as absence.
"""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

TEARDOWN = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "teardown.sh"
ACCOUNT = "111122223333"
REGION = "us-east-1"
ARN = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/launchcrew-demo/abc12345"

FAKE_AWS = """#!/bin/sh
LOG="${FAKE_AWS_LOG:-/dev/null}"
printf '%s\\n' "$*" >>"$LOG"
MODE="${FAKE_MODE:-success}"
if [ "$1" = "sts" ] && [ "$2" = "get-caller-identity" ]; then
  if [ "$MODE" = "caller_auth_fail" ]; then
    echo "An error occurred (ExpiredToken) when calling the GetCallerIdentity operation: token expired" >&2
    exit 254
  fi
  printf '%s\\n' "${FAKE_CALLER:-111122223333}"
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stack-resources" ]; then
  case "$MODE" in
    delete_skipped)
      printf 'RetainedBucket\\n'; exit 0 ;;
    resources_auth_fail)
      echo "An error occurred (AccessDenied) when calling the DescribeStackResources operation: not authorized" >&2
      exit 254 ;;
    resources_not_found)
      echo "An error occurred (ValidationError) when calling the DescribeStackResources operation: Stack with id test does not exist" >&2
      exit 254 ;;
    *) printf 'None\\n'; exit 0 ;;
  esac
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stacks" ]; then
  case "$*" in
    *StackStatus*)
      case "$MODE" in
        verify_auth_fail)
          echo "An error occurred (AccessDenied) when calling the DescribeStacks operation: not authorized" >&2
          exit 254 ;;
        still_present) printf 'DELETE_FAILED\\n'; exit 0 ;;
        delete_complete) printf 'DELETE_COMPLETE\\n'; exit 0 ;;
        delete_skipped) printf 'DELETE_COMPLETE\\n'; exit 0 ;;
        resources_auth_fail) printf 'DELETE_COMPLETE\\n'; exit 0 ;;
        resources_not_found) printf 'DELETE_COMPLETE\\n'; exit 0 ;;
        *) echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id test does not exist" >&2; exit 254 ;;
      esac ;;
    *Project*)
      if [ "$MODE" = "describe_auth_fail" ]; then
        echo "An error occurred (AccessDenied) when calling the DescribeStacks operation: not authorized" >&2
        exit 254
      fi
      if [ "$MODE" = "tag_mismatch" ]; then printf 'Other\\n'; exit 0; fi
      printf '%s\\n' "${FAKE_PROJECT:-LaunchCrew}"
      exit 0 ;;
    *Environment*)
      if [ "$MODE" = "describe_auth_fail" ]; then
        echo "An error occurred (AccessDenied) when calling the DescribeStacks operation: not authorized" >&2
        exit 254
      fi
      printf '%s\\n' "${FAKE_ENV:-demo}"
      exit 0 ;;
  esac
  echo "fake-aws: unexpected describe query" >&2
  exit 2
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "delete-stack" ]; then
  if [ "$MODE" = "delete_auth_fail" ]; then
    echo "An error occurred (AccessDenied) when calling the DeleteStack operation: not authorized" >&2
    exit 254
  fi
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "wait" ]; then
  exit 0
fi
echo "fake-aws: unexpected call: $*" >&2
exit 2
"""


class TeardownTests(unittest.TestCase):
    def run_teardown(self, args, mode="success", extra_env=None):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            log = Path(tmp) / "calls.log"
            log.write_text("", encoding="utf-8")
            env = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                env.pop(key, None)
            env["AWS_BIN"] = str(fake)
            env["FAKE_AWS_LOG"] = str(log)
            env["FAKE_MODE"] = mode
            if extra_env:
                env.update(extra_env)
            result = subprocess.run(
                [str(TEARDOWN), *args], capture_output=True, text=True,
                env=env, check=False)
            calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
            return result, calls

    def test_dry_run_makes_zero_calls(self):
        result, calls = self.run_teardown([])
        self.assertEqual(result.returncode, 0)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("no AWS call", result.stdout)
        self.assertEqual(calls, [])

    def test_confirm_requires_exact_args(self):
        result, calls = self.run_teardown(["--confirm"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_arn_account_mismatch_refused_before_any_call(self):
        result, calls = self.run_teardown([
            "--confirm", "--stack-arn", ARN,
            "--expected-account", "999988887777",
            "--expected-region", REGION])
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused", result.stderr)
        self.assertEqual(calls, [])

    def test_caller_mismatch_refused_with_no_delete(self):
        result, calls = self.run_teardown([
            "--confirm", "--stack-arn", ARN,
            "--expected-account", ACCOUNT, "--expected-region", REGION],
            extra_env={"FAKE_CALLER": "999988887777"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused", result.stderr)
        self.assertTrue(any("get-caller-identity" in call for call in calls))
        self.assertFalse(any("delete-stack" in call for call in calls))

    def test_tag_mismatch_refused_with_no_delete(self):
        result, calls = self.run_teardown([
            "--confirm", "--stack-arn", ARN,
            "--expected-account", ACCOUNT, "--expected-region", REGION],
            mode="tag_mismatch")
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused", result.stderr)
        self.assertFalse(any("delete-stack" in call for call in calls))

    def test_success_verified_by_authoritative_not_found(self):
        result, calls = self.run_teardown([
            "--confirm", "--stack-arn", ARN,
            "--expected-account", ACCOUNT, "--expected-region", REGION],
            mode="success")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Stack absent, verified", result.stdout)
        self.assertIn("Remaining work", result.stdout)
        self.assertTrue(any("delete-stack" in call for call in calls))
        self.assertTrue(any("wait" in call for call in calls))

    def test_describe_auth_failure_is_not_absence(self):
        result, calls = self.run_teardown([
            "--confirm", "--stack-arn", ARN,
            "--expected-account", ACCOUNT, "--expected-region", REGION],
            mode="describe_auth_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("authorization or API failure, not absence", combined)
        self.assertNotIn("Stack absent, verified", combined)
        self.assertFalse(any("delete-stack" in call for call in calls))

    def test_verify_auth_failure_is_not_absence(self):
        result, _ = self.run_teardown([
            "--confirm", "--stack-arn", ARN,
            "--expected-account", ACCOUNT, "--expected-region", REGION],
            mode="verify_auth_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("authorization or API failure, not absence", combined)
        self.assertIn("absence not proven", combined)
        self.assertNotIn("Stack absent, verified", combined)

    def test_delete_complete_record_verified_with_no_skipped(self):
        result, calls = self.run_teardown([
            "--confirm", "--stack-arn", ARN,
            "--expected-account", ACCOUNT, "--expected-region", REGION],
            mode="delete_complete")
        self.assertEqual(result.returncode, 0)
        self.assertIn("DELETE_COMPLETE", result.stdout)
        self.assertIn("Complete resource cleanup", result.stdout)
        self.assertIn("Remaining work", result.stdout)
        self.assertTrue(any("describe-stack-resources" in call for call in calls))

    def test_delete_skipped_distinguished_from_complete_cleanup(self):
        result, _ = self.run_teardown([
            "--confirm", "--stack-arn", ARN,
            "--expected-account", ACCOUNT, "--expected-region", REGION],
            mode="delete_skipped")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("DELETE_SKIPPED", combined)
        self.assertIn("not complete cleanup", combined)
        self.assertNotIn("Complete resource cleanup", combined)

    def test_resources_auth_failure_is_not_complete(self):
        result, _ = self.run_teardown([
            "--confirm", "--stack-arn", ARN,
            "--expected-account", ACCOUNT, "--expected-region", REGION],
            mode="resources_auth_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("authorization or API failure, not absence", combined)
        self.assertIn("complete cleanup not proven", combined)
        self.assertNotIn("Complete resource cleanup", combined)

    def test_resources_not_found_after_delete_complete_is_complete(self):
        result, _ = self.run_teardown([
            "--confirm", "--stack-arn", ARN,
            "--expected-account", ACCOUNT, "--expected-region", REGION],
            mode="resources_not_found")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Complete resource cleanup", result.stdout)


if __name__ == "__main__":
    unittest.main()
