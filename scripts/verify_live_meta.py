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


def _parse_secret_arn(arn, expected_region, expected_account):
    if not isinstance(arn, str):
        return None
    parts = arn.split(":")
    if len(parts) != 7:
        return None
    if parts[0] != "arn" or parts[1] != "aws" or parts[2] != "secretsmanager":
        return None
    if parts[3] != expected_region or parts[4] != expected_account:
        return None
    if parts[5] != "secret":
        return None
    name_suffix = parts[6]
    if not name_suffix or "-" not in name_suffix:
        return None
    base, suffix = name_suffix.rsplit("-", 1)
    if not base or not suffix:
        return None
    return {"region": parts[3], "account": parts[4], "name": name_suffix}


def _journal_dir(base):
    target = Path(base)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _reserve_journal(path, record):
    target = Path(path)
    try:
        fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        try:
            target.unlink()
        except OSError:
            pass
        return False
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return True


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


def _update_journal_verified(path, token, task_arn):
    target = Path(path)
    try:
        current = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(current, dict) or current.get("token", "") != token:
        return False
    if current.get("label", "") != "meta-proof":
        return False
    current["status"] = "verified"
    current["task_arn"] = task_arn
    _write_journal(target, current)
    return True


def _task_id_from_arn(task_arn):
    if not isinstance(task_arn, str) or not task_arn:
        return ""
    if ":task/" not in task_arn:
        return ""
    task_id = task_arn.rsplit("/", 1)[-1].strip()
    if not task_id or "/" in task_id or " " in task_id:
        return ""
    return task_id


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
        if _parse_secret_arn(arn, args.expected_region, args.expected_account) is None:
            print("meta-proof launch secret ARN scope mismatch: " + arn_name,
                  file=sys.stderr)
            return 1
    if args.runtime_secret_arn == args.meta_secret_arn:
        print("meta-proof launch runtime and Meta secrets must differ",
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
        if values.get("DATABASE_URL", "") != args.runtime_secret_arn + ":database-url::":
            print("meta-proof launch runtime secret binding mismatch", file=sys.stderr)
            return 1
        if values.get("META_API_KEY", "") != args.meta_secret_arn + ":meta-api-key::":
            print("meta-proof launch Meta secret binding mismatch", file=sys.stderr)
            return 1
        if definition.get("executionRoleArn") != args.execution_role:
            print("meta-proof launch execution role mismatch", file=sys.stderr)
            return 1
        if definition.get("taskRoleArn") != args.task_role:
            print("meta-proof launch task role mismatch", file=sys.stderr)
            return 1
        if args.execution_role == args.task_role:
            print("meta-proof launch execution and task roles must differ",
                  file=sys.stderr)
            return 1
        log_config = container.get("logConfiguration", {})
        log_options = log_config.get("options", {}) if isinstance(log_config, dict) else {}
        log_group = log_options.get("awslogs-group", "") if isinstance(log_options, dict) else ""
        log_prefix = log_options.get("awslogs-stream-prefix", "") if isinstance(log_options, dict) else ""
        log_driver = log_config.get("logDriver", "") if isinstance(log_config, dict) else ""
        container_name = container.get("name", "")
        if log_driver != "awslogs" or log_group != "/launchcrew/demo/meta-proof":
            print("meta-proof launch log group mismatch; no run attempted",
                  file=sys.stderr)
            return 1
        if log_prefix != "meta-proof" or container_name != "meta-proof":
            print("meta-proof launch log stream identity mismatch; no run attempted",
                  file=sys.stderr)
            return 1
        if args.log_group and args.log_group != log_group:
            print("meta-proof launch caller log group mismatch; proof refused",
                  file=sys.stderr)
            return 1
    except SystemExit:
        raise
    except Exception:
        print("meta-proof launch task definition shape invalid", file=sys.stderr)
        return 1
    if not args.subnet_a.startswith("subnet-") or not args.subnet_b.startswith("subnet-"):
        print("meta-proof launch subnets must be owned subnet ids; no run attempted",
              file=sys.stderr)
        return 1
    if not args.job_sg.startswith("sg-"):
        print("meta-proof launch JobSG must be an owned security group id; no run attempted",
              file=sys.stderr)
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
    if not _reserve_journal(journal_file, record):
        print("meta-proof launch journal exists; resend and crash relaunch refused",
              file=sys.stderr)
        return 1
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
    if stopped.get("taskArn", "") != task_arn:
        print("meta-proof task ARN mismatch; proof refused", file=sys.stderr)
        return 1
    containers = stopped.get("containers", [])
    if len(containers) != 1 or containers[0].get("exitCode") != 0:
        print("meta-proof container exit was not 0; proof refused", file=sys.stderr)
        return 1
    if containers[0].get("name", "meta-proof") != "meta-proof":
        print("meta-proof container identity mismatch; proof refused", file=sys.stderr)
        return 1
    task_id = _task_id_from_arn(task_arn)
    if not task_id:
        print("meta-proof task identity invalid; proof refused", file=sys.stderr)
        return 1
    expected_stream = "meta-proof/meta-proof/" + task_id
    if args.log_stream and args.log_stream != expected_stream:
        print("meta-proof log stream does not match launched task; proof refused",
              file=sys.stderr)
        return 1
    logs = _run_aws(["logs", "get-log-events",
                     "--log-group-name", "/launchcrew/demo/meta-proof",
                     "--log-stream-name", expected_stream,
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
    if not _update_journal_verified(journal_file, token, task_arn):
        print("meta-proof journal verify update refused", file=sys.stderr)
        return 1
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
