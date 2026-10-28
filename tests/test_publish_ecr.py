"""Controlled offline tests for the manual ECR publisher.

No test contacts AWS, Podman, the network, or a real registry. A fake
aws script and a fake podman script record real argv lines (and login
stdin byte counts, never secret values in argv) and return canned JSON
shaped like the actual AWS APIs, or canned digests through --digestfile.
The fake Podman validates the real argv shape: proven global storage
flags, login command options, and push command options with a digest
file. Push stdout stays empty to prove the helper never parses it.
Dry-run must make zero calls. Every refusal must happen before any
push, and ownership failures happen before any build. Any existing tag
for the requested SHA refuses the whole run before any build or push:
no overwrite and no replay. Success writes a manifest with only source
SHA, repo short name, and digest, after five matching readbacks.
Digest mismatch, unreadable digest file, or partial readback fails with
no new manifest, and a preexisting manifest is never deleted,
overwritten, or posed as a fresh receipt.
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
PUB_DOC = REPO / "docs" / "ecr-publication.md"

ACCOUNT = "111122223333"
REGION = "us-east-1"
STACK = "launchcrew-demo"
ROLE_ARN = "arn:aws:iam::111122223333:role/launchcrew-ecr-publisher"
GOOD_DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64
EXISTING_DIGEST = "sha256:" + "c" * 64
TOKEN_SENTINEL = "SENTINEL:PUBLISH:TOKEN:9f8e7d6c5b4a"
EMAIL_SENTINEL = "operator-private@example.com"
REGISTRY_SENTINEL = ACCOUNT + ".dkr.ecr." + REGION + ".amazonaws.com"

OFFICIAL_PINS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "aws-actions/configure-aws-credentials": "e1253824e5c10ff9df46874f81ed3ec929e19cfd",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}
PAREN_SENTINEL = "Abc123Xyz456Def789Ghi012Jkl345Mno678Pqr901Stu234Vwx567Yz890"

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
STACK_ID="arn:aws:cloudformation:us-east-1:ACCOUNT_PLACEHOLDER:stack/STACK_PLACEHOLDER/abcd1234efgh5678"
if [ "$1" = "sts" ] && [ "$2" = "get-caller-identity" ]; then
  case "$MODE" in
    caller_root)
      printf '{"Account":"ACCOUNT_PLACEHOLDER","Arn":"arn:aws:iam::ACCOUNT_PLACEHOLDER:root"}\\n' ;;
    caller_user)
      printf '{"Account":"ACCOUNT_PLACEHOLDER","Arn":"arn:aws:iam::ACCOUNT_PLACEHOLDER:user/someone"}\\n' ;;
    caller_account_mismatch)
      printf '{"Account":"999988887777","Arn":"arn:aws:sts::999988887777:assumed-role/other-role/session"}\\n' ;;
    caller_wrong_role)
      printf '{"Account":"ACCOUNT_PLACEHOLDER","Arn":"arn:aws:sts::ACCOUNT_PLACEHOLDER:assumed-role/other-role/session"}\\n' ;;
    caller_auth_fail)
      printf 'An error occurred (ExpiredToken) when calling the GetCallerIdentity operation: token=TOKEN_PLACEHOLDER arn:aws:iam::ACCOUNT_PLACEHOLDER:role/x REGISTRY_PLACEHOLDER mail=OPERATOR_EMAIL_PLACEHOLDER\\n' >&2
      exit 254 ;;
    sentinel_prefix)
      printf 'An error occurred (PAREN_PLACEHOLDER) leaked prefix then (ExpiredToken) when calling the GetCallerIdentity operation: token=TOKEN_PLACEHOLDER arn:aws:iam::ACCOUNT_PLACEHOLDER:role/x REGISTRY_PLACEHOLDER mail=OPERATOR_EMAIL_PLACEHOLDER\\n' >&2
      exit 254 ;;
    *) printf '{"Account":"ACCOUNT_PLACEHOLDER","Arn":"arn:aws:sts::ACCOUNT_PLACEHOLDER:assumed-role/launchcrew-ecr-publisher/TESTSESSION"}\\n' ;;
  esac
  exit 0
fi
if [ "$1" = "ecr" ] && [ "$2" = "get-login-password" ]; then
  if [ "$MODE" = "login_auth_fail" ]; then
    printf 'An error occurred (ExpiredToken) when calling the GetLoginPassword operation: token=TOKEN_PLACEHOLDER arn:aws:iam::ACCOUNT_PLACEHOLDER:role/x mail=OPERATOR_EMAIL_PLACEHOLDER\\n' >&2
    exit 254
  fi
  printf '%s\\n' "TOKEN_PLACEHOLDER"
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stacks" ]; then
  GOOD_STACK="\\"StackName\\":\\"STACK_PLACEHOLDER\\",\\"StackId\\":\\"$STACK_ID\\",\\"StackStatus\\":\\"UPDATE_COMPLETE\\",\\"Tags\\":[{\\"Key\\":\\"Project\\",\\"Value\\":\\"LaunchCrew\\"},{\\"Key\\":\\"Environment\\",\\"Value\\":\\"demo\\"}]"
  case "$MODE" in
    stacks_auth_fail)
      printf 'An error occurred (AccessDenied) when calling the DescribeStacks operation: not authorized token=TOKEN_PLACEHOLDER ACCOUNT_PLACEHOLDER\\n' >&2
      exit 254 ;;
    stacks_two)
      printf '{"Stacks":[{"StackName":"STACK_PLACEHOLDER","StackId":"%s","StackStatus":"UPDATE_COMPLETE","Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"}]},{"StackName":"STACK_PLACEHOLDER","StackId":"%s-2","StackStatus":"UPDATE_COMPLETE","Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"}]}]}\\n' "$STACK_ID" "$STACK_ID" ;;
    stacks_bad_status)
      printf '{"Stacks":[{"StackName":"STACK_PLACEHOLDER","StackId":"%s","StackStatus":"UPDATE_ROLLBACK_FAILED","Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"}]}]}\\n' "$STACK_ID" ;;
    stacks_wrong_id)
      printf '{"Stacks":[{"StackName":"STACK_PLACEHOLDER","StackId":"arn:aws:cloudformation:eu-west-1:999988887777:stack/STACK_PLACEHOLDER/abcd1234efgh5678","StackStatus":"UPDATE_COMPLETE","Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"}]}]}\\n' ;;
    stacks_tag_mismatch)
      printf '{"Stacks":[{"StackName":"STACK_PLACEHOLDER","StackId":"%s","StackStatus":"UPDATE_COMPLETE","Tags":[{"Key":"Project","Value":"Other"},{"Key":"Environment","Value":"demo"}]}]}\\n' "$STACK_ID" ;;
    stacks_tag_dup)
      printf '{"Stacks":[{"StackName":"STACK_PLACEHOLDER","StackId":"%s","StackStatus":"UPDATE_COMPLETE","Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Project","Value":"Other"},{"Key":"Environment","Value":"demo"}]}]}\\n' "$STACK_ID" ;;
    *) printf '{"Stacks":[{%s}]}\\n' "$GOOD_STACK" ;;
  esac
  exit 0
fi
if [ "$1" = "ce" ] && [ "$2" = "list-cost-allocation-tags" ]; then
  case "$*" in
    *"--tag-keys Project"*) ;;
    *) echo "fake-aws: CE call misses --tag-keys Project" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--type UserDefined"*) ;;
    *) echo "fake-aws: CE call misses --type UserDefined" >&2; exit 2 ;;
  esac
  case "$MODE" in
    ce_auth_fail)
      printf 'An error occurred (AccessDenied) when calling the ListCostAllocationTags operation: not authorized token=TOKEN_PLACEHOLDER ACCOUNT_PLACEHOLDER\\n' >&2
      exit 254 ;;
    ce_inactive)
      printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Inactive"}]}\\n' ;;
    ce_duplicate)
      printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Active"},{"TagKey":"Project","Type":"UserDefined","Status":"Active"}]}\\n' ;;
    ce_mixed)
      printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"AWSManaged","Status":"Active"}]}\\n' ;;
    ce_absent)
      printf '{"CostAllocationTags":[]}\\n' ;;
    ce_malformed)
      printf '{"CostAllocationTags":[{"TagKey":"Project"}]}\\n' ;;
    ce_legacy)
      printf '{"CostAllocationTagList":[{"TagKey":"Project","Type":"UserDefined","Status":"Active"}]}\\n' ;;
    *) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Active"}]}\\n' ;;
  esac
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stack-resources" ]; then
  RES() {
    printf '{"LogicalResourceId":"%s","PhysicalResourceId":"%s","ResourceType":"AWS::ECR::Repository","ResourceStatus":"%s","StackId":"%s","StackName":"STACK_PLACEHOLDER"}' "$1" "$2" "$3" "$STACK_ID"
  }
  if [ "$MODE" = "resources_auth_fail" ]; then
    printf 'An error occurred (AccessDenied) when calling the DescribeStackResources operation: not authorized token=TOKEN_PLACEHOLDER\\n' >&2
    exit 254
  fi
  R1="$(RES ApiEcrRepo launchcrew-api CREATE_COMPLETE)"
  R2="$(RES WebEcrRepo launchcrew-web CREATE_COMPLETE)"
  R3="$(RES WebProxyEcrRepo launchcrew-web-proxy CREATE_COMPLETE)"
  R4="$(RES MigrationEcrRepo launchcrew-migration CREATE_COMPLETE)"
  R5="$(RES BootstrapEcrRepo launchcrew-bootstrap CREATE_COMPLETE)"
  case "$MODE" in
    binding_mismatch) R4="$(RES MigrationEcrRepo launchcrew-migration-typo CREATE_COMPLETE)" ;;
    resources_dup) R5="$(RES ApiEcrRepo launchcrew-api CREATE_COMPLETE)" ;;
    resources_wrong_type) R4='{"LogicalResourceId":"MigrationEcrRepo","PhysicalResourceId":"launchcrew-migration","ResourceType":"AWS::ECS::Service","ResourceStatus":"CREATE_COMPLETE","StackId":"'"$STACK_ID"'","StackName":"STACK_PLACEHOLDER"}' ;;
    resources_wrong_status) R3="$(RES WebProxyEcrRepo launchcrew-web-proxy CREATE_IN_PROGRESS)" ;;
    resources_wrong_stack) R1='{"LogicalResourceId":"ApiEcrRepo","PhysicalResourceId":"launchcrew-api","ResourceType":"AWS::ECR::Repository","ResourceStatus":"CREATE_COMPLETE","StackId":"arn:aws:cloudformation:eu-west-1:999988887777:stack/STACK_PLACEHOLDER/abcd1234efgh5678","StackName":"STACK_PLACEHOLDER"}' ;;
  esac
  printf '{"StackResources":[%s,%s,%s,%s,%s]}\\n' "$R1" "$R2" "$R3" "$R4" "$R5"
  exit 0
fi
if [ "$1" = "ecr" ] && [ "$2" = "describe-repositories" ]; then
  NAME="$(repo_name "$@")"
  ARN="arn:aws:ecr:us-east-1:ACCOUNT_PLACEHOLDER:repository/$NAME"
  URI="ACCOUNT_PLACEHOLDER.dkr.ecr.us-east-1.amazonaws.com/$NAME"
  MUT="IMMUTABLE"
  EXTRA=""
  case "$MODE" in
    mutable_repo) MUT="MUTABLE" ;;
    repo_exclusion) EXTRA=',"imageTagMutabilityExclusion":"TAG_PREFIX"' ;;
    repo_registry_mismatch)
      ARN="arn:aws:ecr:us-east-1:999988887777:repository/$NAME"
      URI="999988887777.dkr.ecr.us-east-1.amazonaws.com/$NAME" ;;
    repo_bad_uri) URI="ACCOUNT_PLACEHOLDER.dkr.ecr.eu-west-1.amazonaws.com/$NAME" ;;
  esac
  if [ "$MODE" = "repo_registry_mismatch" ]; then
    printf '{"repositories":[{"repositoryName":"%s","repositoryArn":"%s","repositoryUri":"%s","registryId":"999988887777","imageTagMutability":"%s"%s}]}\\n' "$NAME" "$ARN" "$URI" "$MUT" "$EXTRA"
  else
    printf '{"repositories":[{"repositoryName":"%s","repositoryArn":"%s","repositoryUri":"%s","registryId":"ACCOUNT_PLACEHOLDER","imageTagMutability":"%s"%s}]}\\n' "$NAME" "$ARN" "$URI" "$MUT" "$EXTRA"
  fi
  exit 0
fi
if [ "$1" = "ecr" ] && [ "$2" = "list-tags-for-resource" ]; then
  case "$MODE" in
    repo_tags_mismatch)
      printf '{"tags":[{"Key":"Project","Value":"Other"},{"Key":"Environment","Value":"demo"}]}\\n' ;;
    repo_tags_lowercase)
      printf '{"tags":[{"key":"Project","value":"LaunchCrew"},{"key":"Environment","value":"demo"}]}\\n' ;;
    *) printf '{"tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"}]}\\n' ;;
  esac
  exit 0
fi
if [ "$1" = "ecr" ] && [ "$2" = "describe-images" ]; then
  NAME="$(repo_name "$@")"
  COUNT=0
  if [ -f "$COUNT_FILE" ]; then COUNT="$(cat "$COUNT_FILE")"; fi
  COUNT=$((COUNT + 1))
  printf '%s' "$COUNT" >"$COUNT_FILE"
  if [ "$COUNT" -le 5 ]; then
    case "$MODE" in
      existing_auth_fail)
        printf 'An error occurred (AccessDenied) when calling the DescribeImages operation: not authorized token=TOKEN_PLACEHOLDER ACCOUNT_PLACEHOLDER\\n' >&2
        exit 254 ;;
      conflict_tag)
        printf '{"imageDetails":[{"imageDigest":"EXISTING_PLACEHOLDER","imageTags":["deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"]}]}\\n'
        exit 0 ;;
      *)
        printf 'An error occurred (ImageNotFoundException) when calling the DescribeImages operation: tag absent\\n' >&2
        exit 254 ;;
    esac
  fi
  case "$MODE" in
    digest_mismatch)
      printf '{"imageDetails":[{"imageDigest":"OTHER_PLACEHOLDER"}]}\\n'
      exit 0 ;;
    partial_fail)
      if [ "$NAME" = "launchcrew-web" ]; then
        printf 'An error occurred (ImageNotFoundException) when calling the DescribeImages operation: tag absent token=TOKEN_PLACEHOLDER mail=OPERATOR_EMAIL_PLACEHOLDER\\n' >&2
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
LINE="$*"
printf '%s\\n' "$LINE" >>"$LOG"
case "$LINE" in
  *"$FAKE_TOKEN"*) echo "fake-podman: secret value in argv" >&2; exit 9 ;;
esac
CMD=""
for arg in "$@"; do
  case "$arg" in
    build|login|tag|push) CMD="$arg"; break ;;
  esac
done
check_global() {
  case "$LINE" in *"--storage-driver vfs"*) ;; *) echo "fake-podman: storage driver missing" >&2; exit 2 ;; esac
  case "$LINE" in *"--cgroup-manager cgroupfs"*) ;; *) echo "fake-podman: cgroup manager missing" >&2; exit 2 ;; esac
  case "$LINE" in *"--root "*) ;; *) echo "fake-podman: graph root missing" >&2; exit 2 ;; esac
  case "$LINE" in *"--runroot "*) ;; *) echo "fake-podman: runroot missing" >&2; exit 2 ;; esac
}
if [ "$CMD" = "build" ]; then
  check_global
  case "$LINE" in *"--format oci"*) ;; *) echo "fake-podman: build format wrong" >&2; exit 2 ;; esac
  case "$LINE" in *"-f containers/"*"-t localhost/"*) ;; *) echo "fake-podman: build file or tag wrong" >&2; exit 2 ;; esac
  exit 0
fi
if [ "$CMD" = "login" ]; then
  check_global
  AFTER="${LINE#*login}"
  case "$AFTER" in *"--authfile "*) ;; *) echo "fake-podman: login authfile misplaced" >&2; exit 2 ;; esac
  case "$AFTER" in *"--password-stdin"*) ;; *) echo "fake-podman: login stdin flag missing" >&2; exit 2 ;; esac
  case "$AFTER" in *"--username AWS"*) ;; *) echo "fake-podman: login user wrong" >&2; exit 2 ;; esac
  prev=""; authfile=""
  for arg in "$@"; do
    if [ "$prev" = "--authfile" ]; then authfile="$arg"; fi
    prev="$arg"
  done
  printf '%s\\n' "$authfile" >>"${FAKE_AUTHFILE_RECORD:-/dev/null}"
  BYTES="$(wc -c | tr -d '[:space:]')"
  printf 'STDIN_BYTES=%s\\n' "$BYTES" >>"$LOG"
  exit 0
fi
if [ "$CMD" = "tag" ]; then
  check_global
  exit 0
fi
if [ "$CMD" = "push" ]; then
  check_global
  AFTER="${LINE#*push}"
  case "$AFTER" in *"--authfile "*) ;; *) echo "fake-podman: push authfile misplaced" >&2; exit 2 ;; esac
  case "$AFTER" in *"--digestfile "*) ;; *) echo "fake-podman: push digestfile missing" >&2; exit 2 ;; esac
  case "$AFTER" in *"--retry 3"*) ;; *) echo "fake-podman: push retry missing" >&2; exit 2 ;; esac
  prev=""; digestfile=""
  for arg in "$@"; do
    if [ "$prev" = "--digestfile" ]; then digestfile="$arg"; fi
    prev="$arg"
  done
  if [ -z "$digestfile" ]; then echo "fake-podman: empty digestfile path" >&2; exit 2; fi
  if [ "$FAKE_PUSH_DIGEST_MODE" = "missing" ]; then exit 0; fi
  if [ "$FAKE_PUSH_DIGEST_MODE" = "invalid" ]; then printf 'not-a-digest\\n' >"$digestfile"; exit 0; fi
  printf '%s\\n' "${FAKE_PUSH_DIGEST:-DIGEST_PLACEHOLDER}" >"$digestfile"
  exit 0
fi
echo "fake-podman: unexpected call: $LINE" >&2
exit 2
"""


def _render_fake(template):
    return (template
            .replace("ACCOUNT_PLACEHOLDER", ACCOUNT)
            .replace("STACK_PLACEHOLDER", STACK)
            .replace("TOKEN_PLACEHOLDER", TOKEN_SENTINEL)
            .replace("DIGEST_PLACEHOLDER", GOOD_DIGEST)
            .replace("OTHER_PLACEHOLDER", OTHER_DIGEST)
            .replace("EXISTING_PLACEHOLDER", EXISTING_DIGEST)
            .replace("REGISTRY_PLACEHOLDER", REGISTRY_SENTINEL)
            .replace("OPERATOR_EMAIL_PLACEHOLDER", EMAIL_SENTINEL)
            .replace("PAREN_PLACEHOLDER", PAREN_SENTINEL))


class PublishEcrTests(unittest.TestCase):
    @staticmethod
    def _make_fixture(base):
        fix = Path(base) / "fixture"
        fix.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=str(fix), check=True,
                       capture_output=True, text=True)
        (fix / "app.txt").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.txt"], cwd=str(fix), check=True,
                       capture_output=True, text=True)
        subprocess.run(
            ["git", "-c", "user.email=fixture@example.com",
             "-c", "user.name=fixture", "-c", "commit.gpgsign=false",
             "commit", "-qm", "fixture"],
            cwd=str(fix), check=True, capture_output=True, text=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(fix), check=True,
            capture_output=True, text=True).stdout.strip()
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", sha],
            cwd=str(fix), check=True, capture_output=True, text=True)
        return fix, sha

    def run_helper(self, args, mode="success", extra_env=None, dirty=False,
                   preexisting_manifest=None, push_digest_mode="good"):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fixture, fixture_sha = self._make_fixture(tmp_path)
            if dirty:
                (fixture / "untracked-build-src.txt").write_text(
                    "untracked\n", encoding="utf-8")
            fake_aws = tmp_path / "fake-aws"
            fake_aws.write_text(_render_fake(FAKE_AWS), encoding="utf-8")
            fake_aws.chmod(fake_aws.stat().st_mode | stat.S_IXUSR
                           | stat.S_IXGRP | stat.S_IXOTH)
            fake_podman = tmp_path / "fake-podman"
            fake_podman.write_text(_render_fake(FAKE_PODMAN), encoding="utf-8")
            fake_podman.chmod(fake_podman.stat().st_mode | stat.S_IXUSR
                              | stat.S_IXGRP | stat.S_IXOTH)
            aws_log = tmp_path / "aws.log"
            podman_log = tmp_path / "podman.log"
            authfile_record = tmp_path / "authfiles.log"
            aws_log.write_text("", encoding="utf-8")
            podman_log.write_text("", encoding="utf-8")
            authfile_record.write_text("", encoding="utf-8")
            (tmp_path / "describe_count").write_text("0", encoding="utf-8")
            manifest = tmp_path / "manifest.json"
            if preexisting_manifest is not None:
                manifest.write_text(preexisting_manifest, encoding="utf-8")
            env = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                        "AWS_SESSION_TOKEN", "GITHUB_REPOSITORY", "GITHUB_REF",
                        "SOURCE_SHA", "EXPECTED_AWS_ACCOUNT_ID",
                        "EXPECTED_REGION", "PUBLISHER_ROLE_ARN",
                        "STACK_NAME", "EXPECTED_REPO", "EXPECTED_REF",
                        "MANIFEST", "GIT_DIR", "GIT_WORK_TREE"):
                env.pop(key, None)
            env["AWS_BIN"] = str(fake_aws)
            env["PODMAN_BIN"] = str(fake_podman)
            env["FAKE_AWS_LOG"] = str(aws_log)
            env["FAKE_PODMAN_LOG"] = str(podman_log)
            env["FAKE_AUTHFILE_RECORD"] = str(authfile_record)
            env["FAKE_AWS_STATE"] = str(tmp_path)
            env["FAKE_MODE"] = mode
            env["FAKE_TOKEN"] = TOKEN_SENTINEL
            env["FAKE_LOCAL_DIGEST"] = GOOD_DIGEST
            env["FAKE_PUSH_DIGEST"] = GOOD_DIGEST
            env["FAKE_PUSH_DIGEST_MODE"] = push_digest_mode
            env["GITHUB_REPOSITORY"] = "summitsingh/launchcrew"
            env["GITHUB_REF"] = "refs/heads/main"
            env["SOURCE_SHA"] = fixture_sha
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
                env=env, cwd=str(fixture), check=False)
            aws_calls = [line for line in aws_log.read_text(
                encoding="utf-8").splitlines() if line.strip()]
            podman_calls = [line for line in podman_log.read_text(
                encoding="utf-8").splitlines() if line.strip()]
            authfiles = [line for line in authfile_record.read_text(
                encoding="utf-8").splitlines() if line.strip()]
            manifest_text = (manifest.read_text(encoding="utf-8")
                             if manifest.exists() else None)
            return (result, aws_calls, podman_calls, authfiles,
                    manifest_text, fixture_sha)

    def assert_zero_calls(self, aws_calls, podman_calls):
        self.assertEqual(aws_calls, [])
        self.assertEqual(podman_calls, [])

    def assert_no_push(self, podman_calls):
        pushes = [call for call in podman_calls if " push " in f" {call} "]
        self.assertEqual(pushes, [])

    def assert_no_leak(self, combined):
        self.assertNotIn(TOKEN_SENTINEL, combined)
        self.assertNotIn(ACCOUNT, combined)
        self.assertNotIn("arn:aws", combined)
        self.assertNotIn(REGISTRY_SENTINEL, combined)
        self.assertNotIn(EMAIL_SENTINEL, combined)

    def test_dry_run_makes_zero_calls(self):
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper([])
        self.assertEqual(result.returncode, 0)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("no AWS call", result.stdout)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_confirm_requires_valid_sha_shape(self):
        for bad in ("xyz", "a" * 39, "A" * 40, ""):
            result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
                ["--confirm"], extra_env={"SOURCE_SHA": bad})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refused", result.stderr)
            self.assert_zero_calls(aws_calls, podman_calls)
            self.assertIsNone(manifest_text)

    def test_sha_mismatch_refused_before_any_call(self):
        with tempfile.TemporaryDirectory() as probe:
            _, probe_sha = self._make_fixture(Path(probe))
        tampered = probe_sha[:-1] + ("b" if probe_sha[-1] == "a" else "a")
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], extra_env={"SOURCE_SHA": tampered})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_wrong_branch_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], extra_env={"GITHUB_REF": "refs/heads/feature"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_wrong_repo_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], extra_env={"GITHUB_REPOSITORY": "someone/else"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_missing_github_context_refused(self):
        for drop in ({"GITHUB_REPOSITORY": ""}, {"GITHUB_REF": ""}):
            result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
                ["--confirm"], extra_env=drop)
            self.assertNotEqual(result.returncode, 0, drop)
            self.assertIn("refused", result.stderr, drop)
            self.assert_zero_calls(aws_calls, podman_calls)
            self.assertIsNone(manifest_text)

    def test_dirty_fixture_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], dirty=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_role_account_mismatch_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], extra_env={"EXPECTED_AWS_ACCOUNT_ID": "999988887777"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_role_arn_malformed_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], extra_env={"PUBLISHER_ROLE_ARN": "not-an-arn"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_region_refused_before_any_call(self):
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm", "--expected-region", "eu-west-1"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertIsNone(manifest_text)

    def test_preexisting_manifest_refused_and_preserved(self):
        stale = '{"source_sha": "0"}\n'
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], preexisting_manifest=stale)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assert_zero_calls(aws_calls, podman_calls)
        self.assertEqual(manifest_text, stale)

    def test_caller_root_refused_with_no_push(self):
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="caller_root")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assertTrue(any("get-caller-identity" in call for call in aws_calls))
        self.assert_no_push(podman_calls)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_caller_user_wrong_role_and_account_mismatch_refused(self):
        for mode in ("caller_user", "caller_wrong_role", "caller_account_mismatch"):
            result, _, podman_calls, _, manifest_text, _ = self.run_helper(
                ["--confirm"], mode=mode)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn("refused", result.stderr, mode)
            self.assert_no_push(podman_calls)
            self.assertIsNone(manifest_text)

    def test_caller_auth_failure_sanitized(self):
        result, _, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="caller_auth_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("refused", combined)
        self.assert_no_leak(combined)
        self.assert_no_push(podman_calls)
        self.assertIsNone(manifest_text)

    def test_parenthesized_sentinel_prefix_never_leaks(self):
        result, _, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="sentinel_prefix")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("refused", combined)
        self.assertNotIn(PAREN_SENTINEL, combined)
        self.assert_no_leak(combined)
        self.assert_no_push(podman_calls)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)
        self.assertTrue(
            "(ExpiredToken)" in combined or "(unknown)" in combined,
            combined)

    def test_stack_tag_mismatch_refused_with_no_push(self):
        result, _, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="stacks_tag_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_no_push(podman_calls)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_stack_identity_strict_refused(self):
        for mode in ("stacks_two", "stacks_bad_status", "stacks_wrong_id",
                     "stacks_tag_dup", "stacks_auth_fail"):
            result, _, podman_calls, _, manifest_text, _ = self.run_helper(
                ["--confirm"], mode=mode)
            self.assertNotEqual(result.returncode, 0, mode)
            combined = result.stdout + result.stderr
            self.assertIn("refused", combined, mode)
            self.assert_no_leak(combined)
            self.assertEqual(podman_calls, [], mode)
            self.assertIsNone(manifest_text)

    def test_ce_inactive_refused_before_any_build(self):
        result, _, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="ce_inactive")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assert_no_push(podman_calls)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_ce_strictness_refused(self):
        for mode in ("ce_duplicate", "ce_mixed", "ce_absent", "ce_malformed",
                     "ce_legacy", "ce_auth_fail"):
            result, _, podman_calls, _, manifest_text, _ = self.run_helper(
                ["--confirm"], mode=mode)
            self.assertNotEqual(result.returncode, 0, mode)
            combined = result.stdout + result.stderr
            self.assertIn("refused", combined, mode)
            self.assert_no_leak(combined)
            self.assertEqual(podman_calls, [], mode)
            self.assertIsNone(manifest_text)

    def test_binding_mismatch_refused_before_any_build(self):
        result, _, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="binding_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_resource_strictness_refused(self):
        for mode in ("resources_dup", "resources_wrong_type",
                     "resources_wrong_status", "resources_wrong_stack",
                     "resources_auth_fail"):
            result, _, podman_calls, _, manifest_text, _ = self.run_helper(
                ["--confirm"], mode=mode)
            self.assertNotEqual(result.returncode, 0, mode)
            combined = result.stdout + result.stderr
            self.assertIn("refused", combined, mode)
            self.assert_no_leak(combined)
            self.assertEqual(podman_calls, [], mode)
            self.assertIsNone(manifest_text)

    def test_mutable_repo_refused_before_any_build(self):
        result, _, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="mutable_repo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_repo_identity_strict_refused(self):
        for mode in ("repo_exclusion", "repo_registry_mismatch", "repo_bad_uri",
                     "repo_tags_mismatch", "repo_tags_lowercase"):
            result, _, podman_calls, _, manifest_text, _ = self.run_helper(
                ["--confirm"], mode=mode)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn("refused", result.stderr, mode)
            self.assertEqual(podman_calls, [], mode)
            self.assertIsNone(manifest_text)

    def test_conflict_tag_refused_before_any_push(self):
        result, aws_calls, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="conflict_tag")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflicting tag", result.stderr)
        self.assertTrue(any("describe-images" in call for call in aws_calls))
        self.assert_no_push(podman_calls)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_existing_state_auth_failure_is_not_absence(self):
        result, _, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="existing_auth_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("refused", combined)
        self.assert_no_leak(combined)
        self.assert_no_push(podman_calls)
        self.assertEqual(podman_calls, [])
        self.assertIsNone(manifest_text)

    def test_login_failure_with_podman_zero_still_fails_sanitized(self):
        result, _, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="login_auth_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("registry login failed", combined)
        self.assert_no_leak(combined)
        self.assert_no_push(podman_calls)
        self.assertIsNone(manifest_text)

    def test_success_writes_manifest_with_five_matching_digests(self):
        result, _, podman_calls, authfiles, manifest_text, fixture_sha = self.run_helper(
            ["--confirm"], mode="success")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv_calls = [call for call in podman_calls
                      if not call.startswith("STDIN_BYTES=")]
        for call in argv_calls:
            self.assertIn("--storage-driver vfs", call)
            self.assertIn("--cgroup-manager cgroupfs", call)
            self.assertIn("--root ", call)
            self.assertIn("--runroot ", call)
        builds = [call for call in podman_calls if " build " in f" {call} "]
        self.assertEqual(len(builds), 6)
        self.assertTrue(any("containers/db.Containerfile" in call for call in builds))
        self.assertFalse(any(" image " in f" {call} " for call in podman_calls))
        pushes = [call for call in podman_calls if " push " in f" {call} "]
        self.assertEqual(len(pushes), 5)
        for call in pushes:
            self.assertIn("--digestfile ", call)
            self.assertIn("--authfile ", call)
            self.assertIn("--retry 3", call)
            self.assertNotIn("launchcrew-db", call)
            self.assertNotIn("latest", call)
        logins = [call for call in podman_calls if " login " in f" {call} "]
        self.assertEqual(len(logins), 1)
        self.assertIn("--password-stdin", logins[0])
        self.assertIn("--authfile ", logins[0])
        self.assertNotIn(TOKEN_SENTINEL, " ".join(podman_calls))
        self.assertTrue(any(line.startswith("STDIN_BYTES=") and line != "STDIN_BYTES=0"
                            for line in podman_calls))
        self.assertIsNotNone(manifest_text)
        manifest = json.loads(manifest_text)
        self.assertEqual(manifest["source_sha"], fixture_sha)
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
        combined = result.stdout + result.stderr
        self.assertIn("confirmed publication", combined)
        self.assert_no_leak(combined)
        for authfile in authfiles:
            self.assertFalse(Path(authfile).exists(),
                             "private auth file must be cleaned up")

    def test_missing_or_invalid_digestfile_fails_with_no_manifest(self):
        for digest_mode in ("missing", "invalid"):
            result, _, podman_calls, _, manifest_text, _ = self.run_helper(
                ["--confirm"], mode="success", push_digest_mode=digest_mode)
            self.assertNotEqual(result.returncode, 0, digest_mode)
            combined = result.stdout + result.stderr
            self.assertIn("pushed digest unreadable", combined, digest_mode)
            self.assert_no_leak(combined)
            self.assertIsNone(manifest_text, digest_mode)
            self.assertNotIn("confirmed publication", combined, digest_mode)

    def test_digest_mismatch_fails_with_no_manifest(self):
        result, _, _, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="digest_mismatch")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("mismatch", combined)
        self.assert_no_leak(combined)
        self.assertIsNone(manifest_text)
        self.assertNotIn("confirmed publication", combined)

    def test_partial_readback_fails_with_no_manifest(self):
        result, _, podman_calls, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="partial_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("partial", combined)
        self.assert_no_leak(combined)
        pushes = [call for call in podman_calls if " push " in f" {call} "]
        self.assertEqual(len(pushes), 5)
        self.assertIsNone(manifest_text)
        self.assertNotIn("confirmed publication", combined)

    def test_failure_preserves_preexisting_manifest(self):
        stale = '{"source_sha": "stale", "images": []}\n'
        result, _, _, _, manifest_text, _ = self.run_helper(
            ["--confirm"], mode="digest_mismatch",
            preexisting_manifest=stale)
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("already exists", combined)
        self.assertEqual(manifest_text, stale)
        self.assertNotIn("confirmed publication", combined)

    def test_role_template_is_least_privilege(self):
        text = ROLE_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(
            "token.actions.githubusercontent.com:sub: "
            "repo:summitsingh@400621/launchcrew@1436365964:ref:refs/heads/main",
            text)
        self.assertIn("token.actions.githubusercontent.com:aud: sts.amazonaws.com", text)
        self.assertIn("StringEquals", text)
        self.assertIn("MaxSessionDuration: 3600", text)
        items = re.findall(r"^\s*-\s*(\S+)", text, re.M)
        scalars = re.findall(r"^\s*Action:\s*(\S+)\s*$", text, re.M)
        items = items + scalars
        for action in ("ecr:PutImage", "ecr:UploadLayerPart", "ecr:BatchGetImage",
                       "ecr:DescribeImages", "ecr:ListTagsForResource",
                       "ecr:GetAuthorizationToken", "ce:ListCostAllocationTags",
                       "cloudformation:DescribeStacks",
                       "cloudformation:DescribeStackResources",
                       "sts:AssumeRoleWithWebIdentity"):
            self.assertIn(action, items, action)
        self.assertNotIn("sts:AssumeRole", items)
        for item in items:
            self.assertFalse(item.startswith("iam:"), item)
            self.assertFalse(item.startswith("secretsmanager:"), item)
            self.assertFalse(item.startswith("ecs:"), item)
            self.assertFalse(item.startswith("s3:"), item)
        for forbidden in ("cloudformation:CreateStack",
                          "cloudformation:UpdateStack",
                          "cloudformation:DeleteStack",
                          "ecr:BatchDeleteImage", "ecr:DeleteRepository"):
            self.assertNotIn(forbidden, items)
        self.assertNotIn("AWS::IAM::OIDCProvider", text)
        self.assertIn(
            "AllowedPattern: "
            "'arn:aws:iam::[0-9]{12}:oidc-provider/"
            "token.actions.githubusercontent.com'",
            text)
        for repo in ("launchcrew-api", "launchcrew-web", "launchcrew-web-proxy",
                     "launchcrew-migration", "launchcrew-bootstrap"):
            self.assertIn(f"repository/{repo}", text)
        star_resources = len(re.findall(r"^\s*Resource:\s*'\*'\s*$", text, re.M))
        self.assertEqual(star_resources, 2)
        self.assertIn("launchcrew-demo", text)

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
        self.assertIn("persist-credentials: false", text)
        uses = re.findall(
            r"uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([0-9A-Za-z]+)", text)
        self.assertEqual(len(uses), 3)
        mapping = dict(uses)
        self.assertEqual(mapping, OFFICIAL_PINS)
        for sha in mapping.values():
            self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, sha)
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

    def test_publication_doc_states_honest_boundaries(self):
        text = PUB_DOC.read_text(encoding="utf-8")
        self.assertIn("temporary action-managed environment credentials", text)
        self.assertIn("no step outputs", text)
        self.assertIn("no persistent profiles", text)
        self.assertIn("reversible credential storage", text)
        self.assertIn("same signed-in account", text)
        self.assertIn("any existing tag", text)
        self.assertNotIn("no exported credentials", text)


if __name__ == "__main__":
    unittest.main()
