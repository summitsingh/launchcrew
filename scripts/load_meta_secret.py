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
    prefix = "arn:aws:secretsmanager:%s:%s:secret/%s" % (
        args.expected_region, args.expected_account, args.secret_name)
    if not args.secret_arn.startswith(prefix):
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
    exists = described.returncode == 0
    if exists:
        try:
            doc = json.loads(described.stdout or "{}")
        except Exception:
            print("loader refused: describe-secret shape invalid", file=sys.stderr)
            return 1
        if doc.get("ARN", "") != args.secret_arn:
            print("loader refused: returned ARN mismatch", file=sys.stderr)
            return 1
        tags = {entry.get("Key"): entry.get("Value")
                for entry in doc.get("Tags", []) if isinstance(entry, dict)}
        if tags.get("Project") != "LaunchCrew" or tags.get("Environment") != "demo":
            print("loader refused: secret tag mismatch", file=sys.stderr)
            return 1
    else:
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
            doc = json.loads(created.stdout or "{}")
        except Exception:
            print("loader create-secret shape invalid", file=sys.stderr)
            return 1
        if doc.get("ARN", "") != args.secret_arn and not args.secret_arn.startswith(
                "arn:aws:secretsmanager:%s:%s:secret/%s-" % (
                    args.expected_region, args.expected_account, args.secret_name)):
            print("loader refused: created ARN mismatch", file=sys.stderr)
            return 1
    payload = json.dumps({"SecretId": args.secret_arn,
                          "SecretString": json.dumps({"meta-api-key": key})})
    updated = _run(["secretsmanager", "put-secret-value",
                    "--cli-input-json", "file:///dev/stdin",
                    "--region", args.expected_region],
                   input_text=payload)
    if updated.returncode != 0:
        print("loader put-secret-value failed; no value logged", file=sys.stderr)
        return 1
    final = _run(["secretsmanager", "describe-secret",
                  "--secret-id", args.secret_arn,
                  "--region", args.expected_region])
    if final.returncode != 0:
        print("loader describe-secret readback failed", file=sys.stderr)
        return 1
    try:
        doc = json.loads(final.stdout or "{}")
    except Exception:
        print("loader describe-secret shape invalid", file=sys.stderr)
        return 1
    print("Meta secret loaded: metadata only, no value printed")
    print("ARN: " + str(doc.get("ARN", "owned-secret")))
    print("Name: " + str(doc.get("Name", args.secret_name)))
    print("VersionIdsToStages count: " + str(len(doc.get("VersionIdsToStages", {}))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
