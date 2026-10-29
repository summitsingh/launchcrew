"""Host wrapper for bounded live Meta proof plus ECS Spark controller.

Host SAM proof delegates in-process to backend.live_meta_proof with no port
binding and no live HTTP without explicit --live. Host Spark live is refused
by default; actual Spark proof runs as a private ECS one-off via --launch-ecs
using the exact deployed API image digest and the actual RDS runtime identity,
plus a separate public HTTPS browser flow. No AWS photo asset transfer occurs.

Controller uses a distinct one-shot meta-proof launch label plus a durable
host journal written before RunTask. The journal prohibits resend and crash
relaunch. Task binding is verified from live state before launch: exact API
image, Python task command, runtime DB plus Meta secrets only, narrow
execution role, empty task role, owned JobSG with no inbound, and owned
network plus cluster scope. One task only, no ALB, no service, no restart.
Terminal proof needs STOPPED exit 0 from the proof container plus an explicit
in-task SPARK PROOF PASS marker covering RDS readback. Exit 0 alone is not
proof. Any ambiguity ends with no automatic resend.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXPECTED_COMMAND = ["/opt/venv/bin/python", "-m", "backend.live_meta_proof",
                    "--live", "--mode", "spark"]
PASS_MARKER = "SPARK PROOF PASS"


def _aws_bin():
    return os.environ.get("AWS_BIN", "aws")


def _run_aws(args, timeout=60):
    completed = subprocess.run(
        [_aws_bin(), *args], capture_output=True, text=True, timeout=timeout)
    return completed


def _journal_dir(base):
    target = Path(base)
    target.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target, 0o700)
    except OSError:
        pass
    return target


def _write_journal(path, record):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def launch_ecs(args):
    journal_root = _journal_dir(args.journal_dir)
    journal_file = journal_root / "meta-proof-launch.json"
    if journal_file.exists():
        print("meta-proof launch journal exists; resend and crash relaunch refused",
              file=sys.stderr)
        return 1
    for name in ("cluster", "task_def", "subnet_a", "subnet_b", "job_sg",
                 "expected_account", "expected_region", "api_image",
                 "execution_role", "task_role",
                 "runtime_secret_arn", "meta_secret_arn"):
        if not getattr(args, name, ""):
            print("meta-proof launch missing required arg: " + name, file=sys.stderr)
            return 1
    if "@sha256:" not in args.api_image:
        print("meta-proof launch needs exact API image digest pin", file=sys.stderr)
        return 1
    for arn_name in ("runtime_secret_arn", "meta_secret_arn"):
        arn = getattr(args, arn_name)
        if not arn.startswith("arn:aws:secretsmanager:%s:%s:secret/" % (
                args.expected_region, args.expected_account)):
            print("meta-proof launch secret ARN scope mismatch: " + arn_name,
                  file=sys.stderr)
            return 1
    caller = _run_aws(["sts", "get-caller-identity", "--query", "Account",
                       "--output", "text", "--region", args.expected_region])
    if caller.returncode != 0 or caller.stdout.strip() != args.expected_account:
        print("meta-proof launch caller account mismatch; no run attempted",
              file=sys.stderr)
        return 1
    described = _run_aws(["ecs", "describe-task-definition",
                          "--task-definition", args.task_def,
                          "--region", args.expected_region])
    if described.returncode != 0:
        print("meta-proof launch task definition read failed; no run attempted",
              file=sys.stderr)
        return 1
    try:
        doc = json.loads(described.stdout or "{}")
        definition = doc.get("taskDefinition", doc)
        containers = definition.get("containerDefinitions", [])
        if len(containers) != 1:
            print("meta-proof launch needs exactly one container", file=sys.stderr)
            return 1
        container = containers[0]
        if container.get("image") != args.api_image:
            print("meta-proof launch image mismatch; no run attempted", file=sys.stderr)
            return 1
        if container.get("command") != EXPECTED_COMMAND:
            print("meta-proof launch command mismatch; no run attempted", file=sys.stderr)
            return 1
        if "entryPoint" in container and container.get("entryPoint"):
            print("meta-proof launch must not override entrypoint", file=sys.stderr)
            return 1
        secrets = container.get("secrets", [])
        names = sorted(entry.get("name", "") for entry in secrets)
        if names != ["DATABASE_URL", "META_API_KEY"]:
            print("meta-proof launch secrets must be runtime DB plus Meta only",
                  file=sys.stderr)
            return 1
        values = {entry.get("name"): entry.get("valueFrom", "") for entry in secrets}
        if args.runtime_secret_arn not in values.get("DATABASE_URL", ""):
            print("meta-proof launch runtime secret binding mismatch", file=sys.stderr)
            return 1
        if args.meta_secret_arn not in values.get("META_API_KEY", ""):
            print("meta-proof launch Meta secret binding mismatch", file=sys.stderr)
            return 1
        if definition.get("executionRoleArn") != args.execution_role:
            print("meta-proof launch execution role mismatch", file=sys.stderr)
            return 1
        if definition.get("taskRoleArn") != args.task_role:
            print("meta-proof launch task role mismatch", file=sys.stderr)
            return 1
    except SystemExit:
        raise
    except Exception:
        print("meta-proof launch task definition shape invalid", file=sys.stderr)
        return 1
    sg_in = _run_aws(["ec2", "describe-security-groups", "--group-ids", args.job_sg,
                      "--query", "SecurityGroups[0].IpPermissions", "--output", "json",
                      "--region", args.expected_region])
    if sg_in.returncode != 0:
        print("meta-proof launch JobSG read failed; no run attempted", file=sys.stderr)
        return 1
    try:
        perms = json.loads(sg_in.stdout or "[]")
    except Exception:
        perms = None
    if perms != []:
        print("meta-proof launch JobSG must carry no inbound", file=sys.stderr)
        return 1
    token = "meta-proof-" + uuid.uuid4().hex[:16]
    record = {"label": "meta-proof", "token": token,
              "account": args.expected_account, "region": args.expected_region,
              "cluster": args.cluster, "task_def": args.task_def,
              "api_image": args.api_image, "status": "launched"}
    _write_journal(journal_file, record)
    print("meta-proof launch journal written before run-task")
    network = ("awsvpcConfiguration={subnets=[%s,%s],securityGroups=[%s],"
               "assignPublicIp=ENABLED}" % (args.subnet_a, args.subnet_b, args.job_sg))
    launched = _run_aws(["ecs", "run-task", "--cluster", args.cluster,
                         "--task-definition", args.task_def,
                         "--launch-type", "FARGATE",
                         "--network-configuration", network,
                         "--client-token", token, "--started-by", token,
                         "--region", args.expected_region])
    if launched.returncode != 0:
        print("meta-proof run-task failed; launch ambiguous, no resend attempted",
              file=sys.stderr)
        return 1
    try:
        payload = json.loads(launched.stdout or "{}")
        tasks = payload.get("tasks", [])
        task_arn = tasks[0].get("taskArn", "") if tasks else ""
    except Exception:
        task_arn = ""
    if not task_arn:
        print("meta-proof run-task response empty; launch ambiguous, no resend",
              file=sys.stderr)
        return 1
    deadline = time.monotonic() + 600
    stopped = None
    while time.monotonic() < deadline:
        checked = _run_aws(["ecs", "describe-tasks", "--cluster", args.cluster,
                            "--tasks", task_arn, "--region", args.expected_region])
        if checked.returncode != 0:
            print("meta-proof task read failed; outcome unknown, no resend",
                  file=sys.stderr)
            return 1
        try:
            tasks = json.loads(checked.stdout or "{}").get("tasks", [])
            stopped = tasks[0] if tasks else None
        except Exception:
            stopped = None
        if stopped is None:
            print("meta-proof task missing; outcome unknown, no resend", file=sys.stderr)
            return 1
        if stopped.get("lastStatus") == "STOPPED":
            break
        time.sleep(10)
    if stopped is None or stopped.get("lastStatus") != "STOPPED":
        print("meta-proof task did not stop in bound; outcome unknown, no resend",
              file=sys.stderr)
        return 1
    if stopped.get("startedBy", "") != token:
        print("meta-proof task token mismatch; proof refused", file=sys.stderr)
        return 1
    containers = stopped.get("containers", [])
    if len(containers) != 1 or containers[0].get("exitCode") != 0:
        print("meta-proof container exit was not 0; proof refused", file=sys.stderr)
        return 1
    logs = _run_aws(["logs", "get-log-events",
                     "--log-group-name", args.log_group,
                     "--log-stream-name", args.log_stream,
                     "--limit", "100", "--region", args.expected_region])
    if logs.returncode != 0:
        print("meta-proof log read failed; exit 0 alone is not proof", file=sys.stderr)
        return 1
    try:
        events = json.loads(logs.stdout or "{}").get("events", [])
        text = "\n".join(event.get("message", "") for event in events)
    except Exception:
        text = ""
    if PASS_MARKER not in text or "spark_calls 3" not in text:
        print("meta-proof PASS marker missing; exit 0 alone is not proof",
              file=sys.stderr)
        return 1
    record["status"] = "verified"
    record["task_arn"] = task_arn
    _write_journal(journal_file, record)
    print("META PROOF ECS VERIFIED task stopped exit 0 plus in-task PASS marker")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Host live proof wrapper and ECS controller.")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--mode", choices=["spark", "sam", "all"], default="sam")
    parser.add_argument("--latch-file", default="")
    parser.add_argument("--launch-ecs", action="store_true")
    parser.add_argument("--cluster", default="")
    parser.add_argument("--task-def", default="")
    parser.add_argument("--subnet-a", default="")
    parser.add_argument("--subnet-b", default="")
    parser.add_argument("--job-sg", default="")
    parser.add_argument("--expected-account", default="")
    parser.add_argument("--expected-region", default="")
    parser.add_argument("--api-image", default="")
    parser.add_argument("--execution-role", default="")
    parser.add_argument("--task-role", default="")
    parser.add_argument("--runtime-secret-arn", default="")
    parser.add_argument("--meta-secret-arn", default="")
    parser.add_argument("--log-group", default="/launchcrew/demo/meta-proof")
    parser.add_argument("--log-stream", default="")
    parser.add_argument("--journal-dir", default=".local/meta-proof-launch")
    args = parser.parse_args(argv)
    if args.launch_ecs:
        return launch_ecs(args)
    if args.mode in ("spark", "all") and args.live:
        if os.environ.get("LAUNCHCREW_ALLOW_HOST_SPARK_LIVE", "") != "1":
            print("Spark live proof must run in private ECS one-off, not host. Use --launch-ecs.")
            return 1
    from backend import live_meta_proof
    forward = []
    if args.live:
        forward.append("--live")
    forward += ["--mode", args.mode]
    if args.latch_file:
        forward += ["--latch-file", args.latch_file]
    return live_meta_proof.main(forward)


if __name__ == "__main__":
    raise SystemExit(main())
