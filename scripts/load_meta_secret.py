"""Private env to SecretsManager loader for the dedicated Meta product key.

Root runs this via an explicit private env file after review. The key value
comes only from the META_API_KEY process environment, never from CLI argv,
never from an operator file, never into logs or prompts. Output is metadata
only via describe-secret, never the read-value API. Guards require the exact
owned secret ARN shape plus expected account and region plus Project and
Environment tags. No new provider key and no new payment are made. The fifth
secret bills at the existing primary public price of 0.40 per secret month,
prorated, with no hard cap. Recovery uses a 7 day window with no force.
"""
import argparse
import json
import os
import subprocess
import sys


def _aws_bin():
    return os.environ.get("AWS_BIN", "aws")


def _run(args, input_text=None, timeout=60):
    return subprocess.run(
        [_aws_bin(), *args], input=input_text,
        capture_output=True, text=True, timeout=timeout)


def _parse_secret_arn(arn, expected_region, expected_account, secret_name):
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
    if not name_suffix or not secret_name:
        return None
    if not name_suffix.startswith(secret_name + "-"):
        return None
    if len(name_suffix) <= len(secret_name) + 1:
        return None
    return {"region": parts[3], "account": parts[4], "name": name_suffix}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Load Meta key to owned secret, metadata only.")
    parser.add_argument("--secret-arn", required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--expected-region", required=True)
    parser.add_argument("--secret-name", default="launchcrew-demo-meta-key")
    args = parser.parse_args(argv)
    key = os.environ.get("META_API_KEY", "")
    if not key.strip():
        print("loader refused: META_API_KEY missing from process environment",
              file=sys.stderr)
        return 1
    if _parse_secret_arn(args.secret_arn, args.expected_region,
                           args.expected_account, args.secret_name) is None:
        print("loader refused: secret ARN scope or name mismatch", file=sys.stderr)
        return 1
    caller = _run(["sts", "get-caller-identity", "--query", "Account",
                   "--output", "text", "--region", args.expected_region])
    if caller.returncode != 0 or caller.stdout.strip() != args.expected_account:
        print("loader refused: caller account mismatch", file=sys.stderr)
        return 1
    described = _run(["secretsmanager", "describe-secret",
                      "--secret-id", args.secret_arn,
                      "--region", args.expected_region])
    if described.returncode == 0:
        try:
            doc = json.loads(described.stdout or "{}")
        except Exception:
            print("loader refused: describe-secret shape invalid", file=sys.stderr)
            return 1
        if doc.get("ARN", "") != args.secret_arn:
            print("loader refused: returned ARN mismatch", file=sys.stderr)
            return 1
        if _parse_secret_arn(doc.get("ARN", ""), args.expected_region,
                             args.expected_account, args.secret_name) is None:
            print("loader refused: returned ARN scope invalid", file=sys.stderr)
            return 1
        if doc.get("Name", "") != args.secret_name:
            print("loader refused: secret name mismatch", file=sys.stderr)
            return 1
        tags = {entry.get("Key"): entry.get("Value")
                for entry in doc.get("Tags", []) if isinstance(entry, dict)}
        if tags.get("Project") != "LaunchCrew" or tags.get("Environment") != "demo":
            print("loader refused: secret tag mismatch", file=sys.stderr)
            return 1
        effective_arn = args.secret_arn
    else:
        detail = (described.stderr or "") + "\n" + (described.stdout or "")
        if "ResourceNotFoundException" not in detail and "ResourceNotFound" not in detail:
            print("loader refused: describe-secret ambiguous, zero mutations",
                  file=sys.stderr)
            return 1
        created = _run(["secretsmanager", "create-secret",
                        "--name", args.secret_name,
                        "--description", "LaunchCrew demo Meta product key, private",
                        "--tags",
                        "Key=Project,Value=LaunchCrew",
                        "Key=Environment,Value=demo",
                        "Key=TeardownBy,Value=2026-11-09",
                        "--region", args.expected_region])
        if created.returncode != 0:
            print("loader create-secret failed; no value logged", file=sys.stderr)
            return 1
        try:
            created_doc = json.loads(created.stdout or "{}")
        except Exception:
            print("loader create-secret shape invalid", file=sys.stderr)
            return 1
        generated = created_doc.get("ARN", "")
        if _parse_secret_arn(generated, args.expected_region,
                             args.expected_account, args.secret_name) is None:
            print("loader refused: created ARN invalid", file=sys.stderr)
            return 1
        readback = _run(["secretsmanager", "describe-secret",
                         "--secret-id", generated,
                         "--region", args.expected_region])
        if readback.returncode != 0:
            print("loader refused: created ARN readback failed", file=sys.stderr)
            return 1
        try:
            read_doc = json.loads(readback.stdout or "{}")
        except Exception:
            print("loader refused: created readback shape invalid", file=sys.stderr)
            return 1
        if read_doc.get("ARN", "") != generated:
            print("loader refused: created ARN readback mismatch", file=sys.stderr)
            return 1
        if read_doc.get("Name", "") != args.secret_name:
            print("loader refused: created name mismatch", file=sys.stderr)
            return 1
        tags = {entry.get("Key"): entry.get("Value")
                for entry in read_doc.get("Tags", []) if isinstance(entry, dict)}
        if tags.get("Project") != "LaunchCrew" or tags.get("Environment") != "demo":
            print("loader refused: created tag mismatch", file=sys.stderr)
            return 1
        effective_arn = generated
    secret_string = json.dumps({"meta-api-key": key})
    updated = _run(["secretsmanager", "put-secret-value",
                    "--secret-id", effective_arn,
                    "--secret-string", "file:///dev/stdin",
                    "--region", args.expected_region],
                   input_text=secret_string)
    if updated.returncode != 0:
        print("loader put-secret-value failed; no value logged", file=sys.stderr)
        return 1
    final = _run(["secretsmanager", "describe-secret",
                  "--secret-id", effective_arn,
                  "--region", args.expected_region])
    if final.returncode != 0:
        print("loader describe-secret readback failed", file=sys.stderr)
        return 1
    try:
        doc = json.loads(final.stdout or "{}")
    except Exception:
        print("loader describe-secret shape invalid", file=sys.stderr)
        return 1
    if doc.get("ARN", "") != effective_arn:
        print("loader refused: final ARN mismatch", file=sys.stderr)
        return 1
    if doc.get("Name", "") != args.secret_name:
        print("loader refused: final name mismatch", file=sys.stderr)
        return 1
    tags = {entry.get("Key"): entry.get("Value")
            for entry in doc.get("Tags", []) if isinstance(entry, dict)}
    if tags.get("Project") != "LaunchCrew" or tags.get("Environment") != "demo":
        print("loader refused: final tag mismatch", file=sys.stderr)
        return 1
    print("Meta secret loaded: metadata only, no value printed")
    print("ARN: " + str(doc.get("ARN", "owned-secret")))
    print("Name: " + str(doc.get("Name", args.secret_name)))
    print("VersionIdsToStages count: " + str(len(doc.get("VersionIdsToStages", {}))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
