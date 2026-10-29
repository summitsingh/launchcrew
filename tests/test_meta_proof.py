"""Offline meta proof CFN, controller, and loader checks. No AWS calls.

Fake AWS fixture returns canned metadata only. No real secret value is used;
loader tests use a synthetic test key labelled as test data.
"""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "aws" / "meta-proof.yaml"
PARAMS_EXAMPLE = ROOT / "deploy" / "aws" / "meta-proof.parameters.example.json"
WRAPPER = ROOT / "scripts" / "verify_live_meta.py"
LOADER = ROOT / "scripts" / "load_meta_secret.py"

ACCOUNT = "111122223333"
REGION = "us-east-1"
API_IMAGE = "111122223333.dkr.ecr.us-east-1.amazonaws.com/launchcrew-api:tag@sha256:abc123"
EXEC_ROLE = "arn:aws:iam::111122223333:role/launchcrew-demo-MetaProofExecutionRole"
TASK_ROLE = "arn:aws:iam::111122223333:role/launchcrew-demo-MetaProofTaskRole"
RUNTIME_ARN = "arn:aws:secretsmanager:us-east-1:111122223333:secret:launchcrew-runtime-abc"
META_ARN = "arn:aws:secretsmanager:us-east-1:111122223333:secret:launchcrew-demo-meta-key-abc"

FAKE_AWS = """#!/bin/sh
LOG="${FAKE_AWS_LOG:-/dev/null}"
STATE="${FAKE_STATE_DIR:-/tmp}"
printf '%s\\n' "$*" >>"$LOG"
MODE="${FAKE_MODE:-success}"
if [ "$1" = "sts" ] && [ "$2" = "get-caller-identity" ]; then
  if [ "$MODE" = "caller_mismatch" ]; then printf '999988887777\\n'; exit 0; fi
  printf '%s\\n' "${FAKE_CALLER:-111122223333}"
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-task-definition" ]; then
  IMAGE="__API_IMAGE__"
  if [ "$MODE" = "image_mismatch" ]; then IMAGE="other-image"; fi
  CMD='["/opt/venv/bin/python", "-m", "backend.live_meta_proof", "--live", "--mode", "spark"]'
  if [ "$MODE" = "command_mismatch" ]; then CMD='["other"]'; fi
  SECRETS='[{"name": "DATABASE_URL", "valueFrom": "__RUNTIME_ARN__:database-url::"}, {"name": "META_API_KEY", "valueFrom": "__META_ARN__:meta-api-key::"}]'
  if [ "$MODE" = "secrets_mismatch" ]; then SECRETS='[{"name": "DATABASE_URL", "valueFrom": "x"}]'; fi
  EXEC="__EXEC_ROLE__"
  TASK="__TASK_ROLE__"
  if [ "$MODE" = "role_mismatch" ]; then EXEC="other"; fi
  printf '{"taskDefinition": {"executionRoleArn": "%s", "taskRoleArn": "%s", "containerDefinitions": [{"image": "%s", "command": %s, "secrets": %s}]}}' "$EXEC" "$TASK" "$IMAGE" "$CMD" "$SECRETS"
  exit 0
fi
if [ "$1" = "ec2" ] && [ "$2" = "describe-security-groups" ]; then
  if [ "$MODE" = "sg_inbound" ]; then printf '[{"FromPort": 443}]\\n'; exit 0; fi
  printf '[]\\n'
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "run-task" ]; then
  TOKEN=""
  PREV=""
  for ARG in "$@"; do
    if [ "$PREV" = "--client-token" ]; then TOKEN="$ARG"; fi
    PREV="$ARG"
  done
  printf '%s' "$TOKEN" >"$STATE/token"
  printf '{"tasks": [{"taskArn": "arn:aws:ecs:us-east-1:111122223333:task/test-123"}]}'
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-tasks" ]; then
  TOKEN="$(cat "$STATE/token" 2>/dev/null || printf 'missing')"
  CODE=0
  if [ "$MODE" = "exit_nonzero" ]; then CODE=1; fi
  printf '{"tasks": [{"taskArn": "arn:aws:ecs:us-east-1:111122223333:task/test-123", "lastStatus": "STOPPED", "startedBy": "%s", "containers": [{"exitCode": %s}]}]}' "$TOKEN" "$CODE"
  exit 0
fi
if [ "$1" = "logs" ] && [ "$2" = "get-log-events" ]; then
  if [ "$MODE" = "no_pass" ]; then printf '{"events": [{"message": "nothing here"}]}'; exit 0; fi
  printf '{"events": [{"message": "SPARK PROOF PASS spark_calls 3 wonder 0 errors 0"}]}'
  exit 0
fi
if [ "$1" = "secretsmanager" ] && [ "$2" = "describe-secret" ]; then
  if [ "$MODE" = "secret_missing" ] && [ "${FAKE_DESCRIBE_COUNT:-0}" = "0" ]; then
    echo "Secrets Manager can not find the specified secret" >&2
    exit 254
  fi
  if [ "$MODE" = "tag_mismatch" ]; then
    printf '{"ARN": "__META_ARN__", "Name": "launchcrew-demo-meta-key", "Tags": [{"Key": "Project", "Value": "Other"}]}'
    exit 0
  fi
  printf '{"ARN": "__META_ARN__", "Name": "launchcrew-demo-meta-key", "Tags": [{"Key": "Project", "Value": "LaunchCrew"}, {"Key": "Environment", "Value": "demo"}], "VersionIdsToStages": {"v1": ["AWSCURRENT"]}}'
  exit 0
fi
if [ "$1" = "secretsmanager" ] && [ "$2" = "create-secret" ]; then
  printf '{"ARN": "__META_ARN__", "Name": "launchcrew-demo-meta-key"}'
  exit 0
fi
if [ "$1" = "secretsmanager" ] && [ "$2" = "put-secret-value" ]; then
  exit 0
fi
echo "fake-aws: unexpected call: $*" >&2
exit 2
""".replace("__API_IMAGE__", API_IMAGE).replace("__RUNTIME_ARN__", RUNTIME_ARN).replace(
    "__META_ARN__", META_ARN).replace("__EXEC_ROLE__", EXEC_ROLE).replace(
    "__TASK_ROLE__", TASK_ROLE)


class TemplateTests(unittest.TestCase):
    def test_meta_proof_template_shape(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("MetaProofTaskDefinition:", text)
        self.assertIn("MetaProofExecutionRole:", text)
        self.assertIn("MetaProofTaskRole:", text)
        self.assertIn("MetaProofLogGroup:", text)
        self.assertIn("/launchcrew/demo/meta-proof", text)
        self.assertIn("RetentionInDays: 7", text)
        self.assertIn("backend.live_meta_proof", text)
        self.assertIn("--live", text)
        self.assertIn("--mode", text)
        self.assertIn("DATABASE_URL", text)
        self.assertIn("META_API_KEY", text)
        self.assertIn("meta-api-key", text)
        self.assertNotIn("MasterDb", text)
        self.assertNotIn("MigrationDb", text)
        self.assertNotIn("TlsSecret", text)
        self.assertNotIn("AWS::ElasticLoadBalancingV2", text)
        self.assertNotIn("AWS::ECS::Service", text)
        self.assertNotIn(" ", text)
        self.assertNotIn(" ", text)
        task_role = text[text.index("MetaProofTaskRole:"):text.index("MetaProofTaskDefinition:")]
        self.assertNotIn("GetSecretValue", task_role)
        self.assertNotIn(" ", TEMPLATE.read_text(encoding="utf-8"))

    def test_params_example_matches_template(self):
        example = json.loads(PARAMS_EXAMPLE.read_text(encoding="utf-8"))
        keys = {entry["ParameterKey"] for entry in example}
        self.assertEqual(keys, {"ApiImageUri", "RuntimeDbUrlSecretArn", "MetaSecretArn",
                                "ClusterName", "SubnetA", "SubnetB", "JobSecurityGroupId"})
        for entry in example:
            self.assertIn("REPLACE_WITH", entry["ParameterValue"])
            self.assertNotIn("111122223333", entry["ParameterValue"])


class ControllerTests(unittest.TestCase):
    def run_wrapper(self, args, mode="success", extra_env=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = tmp_path / "fake-aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            log = tmp_path / "calls.log"
            log.write_text("", encoding="utf-8")
            state = tmp_path / "state"
            state.mkdir()
            env = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                env.pop(key, None)
            env["AWS_BIN"] = str(fake)
            env["FAKE_AWS_LOG"] = str(log)
            env["FAKE_STATE_DIR"] = str(state)
            env["FAKE_MODE"] = mode
            env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "pycache")
            if extra_env:
                env.update(extra_env)
            journal = tmp_path / "journal"
            full = ["--launch-ecs", "--cluster", "owned-cluster",
                    "--task-def", "owned-taskdef",
                    "--subnet-a", "subnet-aaa", "--subnet-b", "subnet-bbb",
                    "--job-sg", "sg-123",
                    "--expected-account", ACCOUNT, "--expected-region", REGION,
                    "--api-image", API_IMAGE,
                    "--execution-role", EXEC_ROLE, "--task-role", TASK_ROLE,
                    "--runtime-secret-arn", RUNTIME_ARN, "--meta-secret-arn", META_ARN,
                    "--log-stream", "test-stream",
                    "--journal-dir", str(journal), *args]
            result = subprocess.run(
                [os.environ.get("PYTHON_BIN", "python3"), str(WRAPPER), *full],
                capture_output=True, text=True, env=env, check=False)
            calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
            return result, calls, journal

    def test_success_verified(self):
        result, calls, journal = self.run_wrapper([])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VERIFIED", result.stdout)
        self.assertTrue(any("run-task" in call for call in calls))
        self.assertTrue((journal / "meta-proof-launch.json").exists())
        record = json.loads((journal / "meta-proof-launch.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "verified")
        self.assertTrue(record["token"].startswith("meta-proof-"))

    def test_journal_blocks_resend(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            journal = tmp_path / "journal"
            journal.mkdir()
            (journal / "meta-proof-launch.json").write_text("{}", encoding="utf-8")
            env = dict(os.environ)
            env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "pycache")
            result = subprocess.run(
                [os.environ.get("PYTHON_BIN", "python3"), str(WRAPPER),
                 "--launch-ecs", "--journal-dir", str(journal)],
                capture_output=True, text=True, env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refused", result.stderr)

    def test_caller_mismatch_makes_no_run(self):
        result, calls, _ = self.run_wrapper([], mode="caller_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_image_mismatch_makes_no_run(self):
        result, calls, _ = self.run_wrapper([], mode="image_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_sg_inbound_makes_no_run(self):
        result, calls, _ = self.run_wrapper([], mode="sg_inbound")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_missing_pass_marker_refused(self):
        result, _, _ = self.run_wrapper([], mode="no_pass")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("alone is not proof", result.stderr)

    def test_exit_nonzero_refused(self):
        result, _, _ = self.run_wrapper([], mode="exit_nonzero")
        self.assertNotEqual(result.returncode, 0)


class LoaderTests(unittest.TestCase):
    def run_loader(self, args, mode="success", key="test-synthetic-key-not-real"):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = tmp_path / "fake-aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            log = tmp_path / "calls.log"
            log.write_text("", encoding="utf-8")
            state = tmp_path / "state"
            state.mkdir()
            env = dict(os.environ)
            for name in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                         "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                env.pop(name, None)
            env["AWS_BIN"] = str(fake)
            env["FAKE_AWS_LOG"] = str(log)
            env["FAKE_STATE_DIR"] = str(state)
            env["FAKE_MODE"] = mode
            env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "pycache")
            if key is not None:
                env["META_API_KEY"] = key
            else:
                env.pop("META_API_KEY", None)
            full = ["--secret-arn", META_ARN, "--expected-account", ACCOUNT,
                    "--expected-region", REGION, *args]
            result = subprocess.run(
                [os.environ.get("PYTHON_BIN", "python3"), str(LOADER), *full],
                capture_output=True, text=True, env=env, check=False)
            calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
            return result, calls

    def test_success_metadata_only_no_value(self):
        result, calls = self.run_loader([])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("metadata only", result.stdout)
        self.assertNotIn("test-synthetic-key-not-real", result.stdout + result.stderr)
        for call in calls:
            self.assertNotIn("test-synthetic-key-not-real", call)
        self.assertTrue(any("put-secret-value" in call for call in calls))
        self.assertFalse(any("get-secret-value" in call for call in calls))

    def test_missing_key_refused(self):
        result, calls = self.run_loader([], key=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_tag_mismatch_refused(self):
        result, calls = self.run_loader([], mode="tag_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("put-secret-value" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
