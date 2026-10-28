"""Controlled offline tests for the manual ECR publisher.

No test contacts AWS, Podman, the network, or a real registry. A fake
aws script and a fake podman script log real argv lines (and login
stdin byte counts, never secret values in argv) and return canned JSON
or digests based on FAKE_MODE. Dry-run must make zero calls. Every
refusal must happen before any push. A conflicting tag refuses before
any push unless the existing digest provably equals the local digest
(safe replay). Success writes a manifest with only source SHA, repo
short name, and digest, after five matching readbacks. Digest mismatch
or partial readback fails with no manifest.
"""
import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "scripts" / "publish-ecr.sh"
WORKFLOW = REPO / ".github" / "workflows" / "publish-ecr.yml"
ROLE_TEMPLATE = REPO / "deploy" / "aws" / "publisher-role.yaml"
FARGATE = REPO / "deploy" / "aws" / "fargate.yaml"

ACCOUNT = "111122223333"
REGION = "us-east-1"
STACK = "launchcrew-demo"
ROLE_ARN = "arn:aws:iam::111122223333:role/launchcrew-ecr-publisher"
GOOD_DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64
EXISTING_DIGEST = "sha256:" + "c" * 64
TOKEN_SENTINEL = "SENTINEL:PUBLISH:TOKEN:9f8e7d6c5b4a"

FAKE_AWS = """#!/bin/sh
LOG="${FAKE_AWS_LOG:-/dev/null}"
printf '%s\\n' "$*" >>"$LOG"
MODE="${FAKE_MODE:-success}"
STATE_DIR="${FAKE_AWS_STATE:-/tmp}"
COUNT_FILE="$STATE_DIR/describe_count"
repo_name() {
  prev=""
  for arg in "$@"; do
    if [ "$prev" = "--repository-names" ] || [ "$prev" = "--repository-name" ]; then
      printf '%s' "$arg"
      return 0
    fi
    prev="$arg"
  done
}
if [ "$1" = "sts" ] && [ "$2" = "get-caller-identity" ]; then
  case "$MODE" in
    caller_root)
      printf '{"Account":"ACCOUNT_PLACEHOLDER","Arn":"arn:aws:iam::ACCOUNT_PLACEHOLDER:root"}\\n' ;;
    caller_user)
      printf '{"Account":"ACCOUNT_PLACEHOLDER","Arn":"arn:aws:iam::ACCOUNT_PLACEHOLDER:user/someone"}\\n' ;;
    caller_account_mismatch)
      printf '{"Account":"999988887777","Arn":"arn:aws:iam::999988887777:role/other-role/session"}\\n' ;;
    caller_auth_fail)
      echo "An error occurred (ExpiredToken) when calling the GetCallerIdentity operation: token expired" >&2
      exit 254 ;;
    *) printf '{"Account":"ACCOUNT_PLACEHOLDER","Arn":"arn:aws:iam::ACCOUNT_PLACEHOLDER:role/launchcrew-ecr-publisher/session"}\\n' ;;
  esac
  exit 0
fi
if [ "$1" = "ecr" ] && [ "$2" = "get-login-password" ]; then
  printf '%s\\n' "${FAKE_TOKEN:-TOKEN_PLACEHOLDER}"
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stacks" ]; then
  if [ "$MODE" = "stacks_auth_fail" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeStacks operation: not authorized" >&2
    exit 254
  fi
  if [ "$MODE" = "tag_mismatch" ]; then
    printf '{"Stacks":[{"StackName":"STACK_PLACEHOLDER","Tags":[{"Key":"Project","Value":"Other"},{"Key":"Environment","Value":"demo"}]}]}\\n'
    exit 0
  fi
  printf '{"Stacks":[{"StackName":"STACK_PLACEHOLDER","Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"}]}]}\\n'
  exit 0
fi
if [ "$1" = "ce" ] && [ "$2" = "list-cost-allocation-tags" ]; then
  if [ "$MODE" = "ce_auth_fail" ]; then
    echo "An error occurred (AccessDenied) when calling the ListCostAllocationTags operation: not authorized" >&2
    exit 254
  fi
  if [ "$MODE" = "ce_inactive" ]; then
    printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Inactive"}]}\\n'
    exit 0
  fi
  printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Active"}]}\\n'
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stack-resources" ]; then
  if [ "$MODE" = "resources_auth_fail" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeStackResources operation: not authorized" >&2
    exit 254
  fi
  if [ "$MODE" = "binding_mismatch" ]; then
    printf '{"StackResources":[{"LogicalResourceId":"ApiEcrRepo","PhysicalResourceId":"launchcrew-api"},{"LogicalResourceId":"WebEcrRepo","PhysicalResourceId":"launchcrew-web"},{"LogicalResourceId":"WebProxyEcrRepo","PhysicalResourceId":"launchcrew-web-proxy"},{"LogicalResourceId":"MigrationEcrRepo","PhysicalResourceId":"launchcrew-migration-typo"},{"LogicalResourceId":"BootstrapEcrRepo","PhysicalResourceId":"launchcrew-bootstrap"}]}\\n'
    exit 0
  fi
  printf '{"StackResources":[{"LogicalResourceId":"ApiEcrRepo","PhysicalResourceId":"launchcrew-api"},{"LogicalResourceId":"WebEcrRepo","PhysicalResourceId":"launchcrew-web"},{"LogicalResourceId":"WebProxyEcrRepo","PhysicalResourceId":"launchcrew-web-proxy"},{"LogicalResourceId":"MigrationEcrRepo","PhysicalResourceId":"launchcrew-migration"},{"LogicalResourceId":"BootstrapEcrRepo","PhysicalResourceId":"launchcrew-bootstrap"}]}\\n'
  exit 0
fi
if [ "$1" = "ecr" ] && [ "$2" = "describe-repositories" ]; then
  NAME="$(repo_name "$@")"
  if [ "$MODE" = "mutable_repo" ]; then
    printf '{"repositories":[{"repositoryName":"%s","imageTagMutability":"MUTABLE"}]}\\n' "$NAME"
    exit 0
  fi
  printf '{"repositories":[{"repositoryName":"%s","imageTagMutability":"IMMUTABLE"}]}\\n' "$NAME"
  exit 0
fi
if [ "$1" = "ecr" ] && [ "$2" = "describe-images" ]; then
  NAME="$(repo_name "$@")"
  COUNT=0
  if [ -f "$COUNT_FILE" ]; then COUNT="$(cat "$COUNT_FILE")"; fi
  COUNT=$((COUNT + 1))
  printf '%s' "$COUNT" >"$COUNT_FILE"
  if [ "$MODE" = "existing_auth_fail" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeImages operation: not authorized" >&2
    exit 254
  fi
  if [ "$COUNT" -le 5 ]; then
    case "$MODE" in
      conflict_tag)
        printf '{"imageDetails":[{"imageDigest":"EXISTING_PLACEHOLDER"}]}\\n'
        exit 0 ;;
      replay_tag)
        printf '{"imageDetails":[{"imageDigest":"DIGEST_PLACEHOLDER"}]}\\n'
        exit 0 ;;
      *)
        echo "An error occurred (ImageNotFoundException) when calling the DescribeImages operation: tag absent" >&2
        exit 254 ;;
    esac
  fi
  case "$MODE" in
    digest_mismatch)
      printf '{"imageDetails":[{"imageDigest":"OTHER_PLACEHOLDER"}]}\\n'
      exit 0 ;;
    partial_fail)
      if [ "$NAME" = "launchcrew-web" ]; then
        echo "An error occurred (ImageNotFoundException) when calling the DescribeImages operation: tag absent" >&2
        exit 254
      fi
      printf '{"imageDetails":[{"imageDigest":"DIGEST_PLACEHOLDER"}]}\\n'
      exit 0 ;;
    *)
      printf '{"imageDetails":[{"imageDigest":"DIGEST_PLACEHOLDER"}]}\\n'
      exit 0 ;;
  esac
fi
echo "fake-aws: unexpected call: $*" >&2
exit 2
"""

FAKE_PODMAN = """#!/bin/sh
LOG="${FAKE_PODMAN_LOG:-/dev/null}"
printf '%s\\n' "$*" >>"$LOG"
if [ "$1" = "--authfile" ]; then
  if [ "$3" = "login" ]; then
    printf '%s\\n' "$2" >>"${FAKE_AUTHFILE_RECORD:-/dev/null}"
    BYTES="$(wc -c | tr -d ' ')"
    printf 'STDIN_BYTES=%s\\n' "$BYTES" >>"$LOG"
    exit 0
  fi
  if [ "$3" = "push" ]; then
    printf 'Copying blob\\nWriting manifest\\ndigest: %s\\n' "${FAKE_PUSH_DIGEST:-DIGEST_PLACEHOLDER}"
    exit 0
  fi
fi
case "$1" in
  build) exit 0 ;;
  tag) exit 0 ;;
  image) printf '%s\\n' "${FAKE_LOCAL_DIGEST:-DIGEST_PLACEHOLDER}"; exit 0 ;;
esac
echo "fake-podman: unexpected call: $*" >&2
exit 2
"""


def _head_sha():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        cwd=str(REPO), check=True)
    return result.stdout.strip()


def _flip_last_char(sha):
    last = sha[-1]
    return sha[:-1] + ("b" if last == "a" else "a")


def _render_fake(template):
    return (template
            .replace("ACCOUNT_PLACEHOLDER", ACCOUNT)
            .replace("STACK_PLACEHOLDER", STACK)
            .replace("TOKEN_PLACEHOLDER", TOKEN_SENTINEL)
            .replace("DIGEST_PLACEHOLDER", GOOD_DIGEST)
            .replace("OTHER_PLACEHOLDER", OTHER_DIGEST)
            .replace("EXISTING_PLACEHOLDER", EXISTING_DIGEST))


class PublishEcrTests(unittest.TestCase):
    def run_helper(self, args, mode="success", extra_env=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_aws = tmp_path / "fake-aws"
            fake_aws.write_text(_render_fake(FAKE_AWS), encoding="utf-8")
            fake_aws.chmod(fake_aws.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            fake_podman = tmp_path / "fake-podman"
            fake_podman.write_text(_render_fake(FAKE_PODMAN), encoding="utf-8")
            fake_podman.chmod(fake_podman.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            aws_log = tmp_path / "aws.log"
            podman_log = tmp_path / "podman.log"
            authfile_record = tmp_path / "authfiles.log"
            aws_log.write_text("", encoding="utf-8")
            podman_log.write_text("", encoding="utf-8")
            authfile_record.write_text("", encoding="utf-8")
            (tmp_path / "describe_count").write_text("0", encoding="utf-8")
            manifest = tmp_path / "manifest.json"
            env = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                        "AWS_SESSION_TOKEN", "GITHUB_REPOSITORY", "GITHUB_REF",
                        "SOURCE_SHA", "EXPECTED_AWS_ACCOUNT_ID",
                        "EXPECTED_REGION", "PUBLISHER_ROLE_ARN",
                        "STACK_NAME", "EXPECTED_REPO", "EXPECTED_REF",
                        "MANIFEST"):
                env.pop(key, None)
            env["AWS_BIN"] = str(fake_aws)
            env["PODMAN_BIN"] = str(fake_podman)
            env["FAKE_AWS_LOG"] = str(aws_log)
            env["FAKE_PODMAN_LOG"] = str(podman_log)
            env["FAKE_AUTHFILE_RECORD"] = str(authfile_record)
            env["FAKE_AWS_STATE"] = tmp
            env["FAKE_MODE"] = mode
            env["FAKE_TOKEN"] = TOKEN_SENTINEL
            env["FAKE_LOCAL_DIGEST"] = GOOD_DIGEST
            env["FAKE_PUSH_DIGEST"] = GOOD_DIGEST
            env["GITHUB_REPOSITORY"] = "summitsingh/launchcrew"
            env["GITHUB_REF"] = "refs/heads/main"
            env["SOURCE_SHA"] = _head_sha()
            env["EXPECTED_AWS_ACCOUNT_ID"] = ACCOUNT
            env["EXPECTED_REGION"] = REGION
            env["PUBLISHER_ROLE_ARN"] = ROLE_ARN
            env["STACK_NAME"] = STACK
            if extra_env:
                env.update(extra_env)
            full_args = list(args)
            if "--manifest" not in full_args and not any(
                    a.startswith("--manifest=") for a in full_args):
                full_args += ["--manifest", str(manifest)]
            result = subprocess.run(
                [str(HELPER), *full_args], capture_output=True, text=True,
                env=env, cwd=str(REPO), check=False)
            aws_calls = [line for line in aws_log.read_text(encoding="utf-8").splitlines() if line.strip()]
            podman_calls = [line for line in podman_log.read_text(encoding="utf-8").splitlines() if line.strip()]
            authfiles = [line for line in authfile_record.read_text(encoding="utf-8").splitlines() if line.strip()]
            manifest_text = manifest.read_text(encoding="utf-8") if manifest.exists() else None
            return result, aws_calls, podman_calls, authfiles, manifest_text

    def assert_zero_calls(self, aws_calls, podman_calls):
        self.assertEqual(aws_calls, [])
        self.assertEqual(podman_calls, [])

    def assert_no_push(self, podman_calls):
        pushes = [call for call in podman_calls if " push " in f" {call} "]
        self.assertEqual(pushes, [])

    def test_dry_run_makes_zero_calls(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper([])
        self.assertEqual(result.returncode, 0)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("no AWS call", result.stdout)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_confirm_requires_valid_sha_shape(self):
        for bad in ("xyz", "a" * 39, "A" * 40, ""):
            result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
                ["--confirm"], extra_env={"SOURCE_SHA": bad})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refused", result.stderr)
            self.assert_zero_calls(aws_calls, podman_calls)
            self.assertIsNone(manifest_text)

    def test_sha_mismatch_refused_before_any_call(self):
        tampered = _flip_last_char(_head_sha())
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], extra_env={"SOURCE_SHA": tampered})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_wrong_branch_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], extra_env={"GITHUB_REF": "refs/heads/feature"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_wrong_repo_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], extra_env={"GITHUB_REPOSITORY": "someone/else"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_role_account_mismatch_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], extra_env={"EXPECTED_AWS_ACCOUNT_ID": "999988887777"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_role_arn_malformed_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], extra_env={"PUBLISHER_ROLE_ARN": "not-an-arn"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_region_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm", "--expected-region", "eu-west-1"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_caller_root_refused_with_no_push(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], mode="caller_root")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assertTrue(any("get-caller-identity" in call for call in aws_calls))
        self.assert_no_push(podman_calls)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_caller_user_and_account_mismatch_refused(self):
        for mode in ("caller_user", "caller_account_mismatch"):
            result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
                ["--confirm"], mode=mode)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn("refused", result.stderr, mode)
            self.assert_no_push(podman_calls, )
            self.assertIsNone(manifest_text, )

    def test_stack_tag_mismatch_refused_with_no_push(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], mode="tag_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_no_push(podman_calls)
        self.assertIsNone(manifest_text)

    def test_ce_inactive_refused_before_any_build(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], mode="ce_inactive")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_no_push(podman_calls)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_binding_mismatch_refused_before_any_build(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], mode="binding_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_mutable_repo_refused_before_any_build(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], mode="mutable_repo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_conflict_tag_refused_before_any_push(self):
        result, aws_calls, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], mode="conflict_tag")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflicting tag", result.stderr)
        builds = [call for call in podman_calls if call.startswith("build ")]
        self.assertEqual(len(builds), 6)
        self.assert_no_push(podman_calls)
        self.assertIsNone(manifest_text)

    def test_existing_state_auth_failure_is_not_absence(self):
        result, _, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], mode="existing_auth_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("refused", combined)
        self.assert_no_push(podman_calls)
        self.assertIsNone(manifest_text)

    def test_success_writes_manifest_with_five_matching_digests(self):
        result, _, podman_calls, authfiles, manifest_text = self.run_helper(
            ["--confirm"], mode="success")
        self.assertEqual(result.returncode, 0, result.stderr)
        builds = [call for call in podman_calls if call.startswith("build ")]
        self.assertEqual(len(builds), 6)
        self.assertTrue(any("containers/db.Containerfile" in call for call in builds))
        pushes = [call for call in podman_calls if " push " in f" {call} "]
        self.assertEqual(len(pushes), 5)
        for call in pushes:
            self.assertNotIn("launchcrew-db", call)
            self.assertNotIn("latest", call)
        logins = [call for call in podman_calls if " login " in f" {call} "]
        self.assertEqual(len(logins), 1)
        self.assertIn("--password-stdin", logins[0])
        self.assertNotIn(TOKEN_SENTINEL, " ".join(podman_calls))
        self.assertTrue(any(line.startswith("STDIN_BYTES=") and line != "STDIN_BYTES=0"
                            for line in podman_calls))
        self.assertIsNotNone(manifest_text)
        manifest = json.loads(manifest_text)
        self.assertEqual(manifest["source_sha"], _head_sha())
        self.assertEqual(len(manifest["images"]), 5)
        self.assertEqual(
            [image["repository"] for image in manifest["images"]],
            ["launchcrew-api", "launchcrew-web", "launchcrew-web-proxy",
             "launchcrew-migration", "launchcrew-bootstrap"])
        for image in manifest["images"]:
            self.assertEqual(image["digest"], GOOD_DIGEST)
            self.assertEqual(set(image), {"repository", "digest"})
        self.assertNotIn(ACCOUNT, manifest_text)
        self.assertNotIn(TOKEN_SENTINEL, manifest_text)
        self.assertNotIn(TOKEN_SENTINEL, result.stdout + result.stderr)
        for authfile in authfiles:
            self.assertFalse(Path(authfile).exists(),
                             "private auth file must be cleaned up")

    def test_safe_replay_skips_push_but_still_manifests(self):
        result, _, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], mode="replay_tag")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_no_push(podman_calls)
        self.assertIsNotNone(manifest_text)
        manifest = json.loads(manifest_text)
        for image in manifest["images"]:
            self.assertEqual(image["digest"], GOOD_DIGEST)

    def test_digest_mismatch_fails_with_no_manifest(self):
        result, _, _, _, manifest_text = self.run_helper(
            ["--confirm"], mode="digest_mismatch")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("mismatch", combined)
        self.assertIsNone(manifest_text)
        self.assertNotIn(TOKEN_SENTINEL, combined)

    def test_partial_readback_fails_with_no_manifest(self):
        result, _, podman_calls, _, manifest_text = self.run_helper(
            ["--confirm"], mode="partial_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("partial", combined)
        pushes = [call for call in podman_calls if " push " in f" {call} "]
        self.assertEqual(len(pushes), 5)
        self.assertIsNone(manifest_text)
        self.assertNotIn(TOKEN_SENTINEL, combined)

    def test_role_template_is_least_privilege(self):
        text = ROLE_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(
            "token.actions.githubusercontent.com:sub: "
            "repo:summitsingh@400621/launchcrew@1436365964:ref:refs/heads/main",
            text)
        self.assertIn("token.actions.githubusercontent.com:aud: sts.amazonaws.com", text)
        self.assertIn("MaxSessionDuration: 3600", text)
        for repo in ("launchcrew-api", "launchcrew-web", "launchcrew-web-proxy",
                     "launchcrew-migration", "launchcrew-bootstrap"):
            self.assertIn(f"repository/{repo}", text)
        for action in ("ecr:PutImage", "ecr:UploadLayerPart", "ecr:BatchGetImage",
                       "ecr:DescribeImages", "ecr:ListTagsForResource",
                       "ecr:GetAuthorizationToken", "ce:ListCostAllocationTags",
                       "cloudformation:DescribeStacks",
                       "cloudformation:DescribeStackResources"):
            self.assertIn(action, text)
        for forbidden in ("iam:", "PassRole", "secretsmanager:", "ecs:",
                          "s3:", "cloudformation:CreateStack",
                          "cloudformation:UpdateStack", "cloudformation:DeleteStack",
                          "sts:AssumeRole", "ecr:BatchDeleteImage", "ecr:DeleteRepository"):
            self.assertNotIn(forbidden, text)
        self.assertNotIn("AWS::IAM::OIDCProvider", text)
        self.assertIn("launchcrew-demo", text)
        self.assertNotIn("Environment: production", text)

    def test_workflow_is_manual_only_with_pinned_actions(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", text)
        for forbidden in ("push:", "pull_request", "pull_request_target",
                          "schedule:", "workflow_run:", "workflow_call:"):
            self.assertNotIn(forbidden, text)
        self.assertIn("summitsingh/launchcrew", text)
        self.assertIn("refs/heads/main", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("timeout-minutes:", text)
        self.assertIn("id-token: write", text)
        self.assertIn("contents: read", text)
        for pinned in ("11d5960a326750d58380738e36bfabf77265a",
                       "e1253824e5c10ff9df46874f81ed3ec929e19cfd",
                       "ea165f8d65b6e75b540449e92b4886f43607fa02"):
            self.assertIn(pinned, text)
        self.assertIn("secrets.ECR_PUBLISH_EXPECTED_ACCOUNT_ID", text)
        self.assertIn("secrets.ECR_PUBLISHER_ROLE_ARN", text)
        self.assertIn("mask-aws-account-id: true", text)
        self.assertIn("role-duration-seconds: 900", text)
        self.assertIn("output-credentials: false", text)
        self.assertIn("unset-current-credentials: true", text)
        self.assertIn("scripts/publish-ecr.sh --confirm", text)
        run_blocks = re.findall(r"run: \|(.*?)(?=\n      - |\n\w|\Z)", text, re.S)
        for block in run_blocks:
            self.assertNotIn("${{ inputs.", block)
            self.assertNotIn("${{ secrets.", block)

    def test_fargate_repos_are_immutable(self):
        text = FARGATE.read_text(encoding="utf-8")
        self.assertEqual(text.count("ImageTagMutability: IMMUTABLE"), 5)
        self.assertNotIn("ImageTagMutability: MUTABLE", text)
        self.assertNotIn("MUTABLE_WITH_EXCLUSION", text)


if __name__ == "__main__":
    unittest.main()
