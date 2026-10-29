"""Offline staged-bootstrap tests with a fake AWS command fixture.

No test contacts AWS. The fake AWS script logs calls and returns canned
responses based on FAKE_MODE. Dry-run must make zero calls. Confirm path must
verify caller, stack tags, and secret ARN ownership before any mutation, must
verify the owned foundation budget plus confirmed SNS subscription before any
paid phase, must order infra before images before init before material before
dbroles before migrate before enable, must require STOPPED exit 0 for one-off
tasks with schema proof before enabling fixed-count services, must refuse
placeholder images, and must never call GetSecretValue.
"""
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

BOOTSTRAP = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "bootstrap.sh"
TEMPLATE = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "fargate.yaml"
PARAMS = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "parameters.example.json"
FOUNDATION = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "foundation.yaml"

ACCOUNT = "111122223333"
REGION = "us-east-1"
STACK = "launchcrew-demo"
FOUNDATION_STACK = "launchcrew-foundation"
PREREQS_STACK = "launchcrew-prereqs"
SECRET_RT = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-runtime-AbCdEf"
SECRET_MG = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-migration-GhIjKl"
SECRET_MASTER = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-master-MnOpQr"
SECRET_TLS = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-tls-QrStUv"
TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCOUNT}:launchcrew-foundation-BudgetTopic-ABC123"
SUB_ARN = f"{TOPIC_ARN}:12345678-90ab-cdef-1234-567890abcdef"
CERT_ARN = f"arn:aws:acm:{REGION}:{ACCOUNT}:certificate/12345678-90ab-cdef-1234-567890abcde1"
DB_HOST = "launchcrew-demo.abc123.us-east-1.rds.amazonaws.com"
NOTIFY_EMAIL = "owner" + "@" + "example.test"


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
  DESCRIBE_STACK=""
  DESCRIBE_PREV=""
  for DESCRIBE_ARG in "$@"; do
    if [ "$DESCRIBE_PREV" = "--stack-name" ]; then DESCRIBE_STACK="$DESCRIBE_ARG"; fi
    DESCRIBE_PREV="$DESCRIBE_ARG"
  done
  case "$DESCRIBE_STACK" in
    launchcrew-foundation|launchcrew-prereqs)
      FOUND_STATUS="CREATE_COMPLETE"
      case "$*" in
        *"StackStatus"*) printf '%s\\n' "$FOUND_STATUS"; exit 0 ;;
      esac
      printf '{"Stacks":[{"StackId":"arn:aws:cloudformation:us-east-1:111122223333:stack/%s/abc123","StackStatus":"%s","Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"}]}]}\\n' "$DESCRIBE_STACK" "$FOUND_STATUS"
      exit 0 ;;
  esac
  if [ "$MODE" = "stack_auth" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeStacks operation: not authorized" >&2
    exit 254
  fi
  if [ "$MODE" = "stack_other_error" ]; then
    echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Rate exceeded" >&2
    exit 254
  fi
  if [ "$MODE" = "stack_missing" ]; then
    if [ -z "$FAKE_STACK_CREATED_FILE" ] || [ ! -f "$FAKE_STACK_CREATED_FILE" ]; then
      echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id launchcrew-demo does not exist" >&2
      exit 254
    fi
  fi
  STATUS="${FAKE_STACK_STATUS:-CREATE_COMPLETE}"
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
  ENABLE_VALUE="${FAKE_ENABLE:-false}"
  printf '{"Stacks":[{"StackId":"%s","StackStatus":"%s","Tags":[{"Key":"Project","Value":"%s"},{"Key":"Environment","Value":"demo"}],"Parameters":[{"ParameterKey":"AcmCertificateArn","ParameterValue":"%s"},{"ParameterKey":"ApiImageUri","ParameterValue":"%s"},{"ParameterKey":"EnableServices","ParameterValue":"%s"}]}]}\\n' "$STACKID" "$STATUS" "$PROJECT" "${FAKE_CERT_ARN:-arn:aws:acm:us-east-1:111122223333:certificate/12345678-90ab-cdef-1234-567890abcde1}" "${FAKE_API_IMAGE:-111122223333.dkr.ecr.us-east-1.amazonaws.com/launchcrew-api:abc123}" "$ENABLE_VALUE"
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "create-change-set" ]; then
  case "$*" in
    *"--use-previous-template"*|*"--template-file"*) ;;
    *) echo "fake-aws: change set must use previous template or template file" >&2; exit 2 ;;
  esac
  case "$*" in
    *"ParameterKey=EnableServices,ParameterValue=false"*) ;;
    *) echo "fake-aws: change set must set EnableServices=false" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--template-file"*)
      if [ "${FAKE_INFRA_CREATE:-ok}" = "exists" ]; then
        echo "An error occurred (AlreadyExistsException) when calling the CreateChangeSet operation: change set infra-006 exists" >&2
        exit 254
      fi ;;
  esac
  printf '{"Id":"arn:aws:cloudformation:us-east-1:111122223333:changeSet/changeset/abc123","StackId":"arn:aws:cloudformation:us-east-1:111122223333:stack/launchcrew-demo/abc123"}\\n'
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-change-set" ]; then
  case "$*" in
    *"--next-token"*) echo "fake-aws: unsupported --next-token rejected, use --cli-input-json NextToken" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--starting-token"*|*"--max-items"*) echo "fake-aws: high level pagination args rejected with --no-paginate" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--no-paginate"*) ;;
    *) echo "fake-aws: unbounded autopagination rejected, --no-paginate required" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--cli-input-json"*) ;;
    *) echo "fake-aws: --cli-input-json required" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--stack-name "*|*"--stack-name="*|*"--change-set-name "*|*"--change-set-name="*) echo "fake-aws: raw JSON required, flag filters refused" >&2; exit 2 ;;
  esac
  CS_INPUT_PATH=""
  CS_INPUT_PREV=""
  for CS_ARG in "$@"; do
    if [ "$CS_INPUT_PREV" = "--cli-input-json" ]; then CS_INPUT_PATH="$CS_ARG"; fi
    CS_INPUT_PREV="$CS_ARG"
  done
  case "$CS_INPUT_PATH" in
    file://*) CS_INPUT_PATH="${CS_INPUT_PATH#file://}" ;;
    *) echo "fake-aws: --cli-input-json must be file:// path" >&2; exit 2 ;;
  esac
  echo "INPUT_JSON_CHANGESET $(cat "$CS_INPUT_PATH" 2>/dev/null || echo MALFORMED)" >>"$LOG" 2>/dev/null || true
  CS_DECODED="$(python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); s=d.get("StackName",""); c=d.get("ChangeSetName",""); n=d.get("NextToken",""); nn=d.get("nextToken","__absent__"); bad="";
if s!="launchcrew-demo": bad="BAD_STACK";
elif not isinstance(c,str) or not c: bad="BAD_NAME";
elif nn!="__absent__": bad="BAD_CASE";
elif n is None: n="";
elif not isinstance(n,str): bad="MALFORMED_INPUT";
print(bad if bad else (c+"|"+n))' "$CS_INPUT_PATH" 2>/dev/null || echo MALFORMED_INPUT)"
  case "$CS_DECODED" in
    MALFORMED_INPUT|BAD_STACK|BAD_NAME|BAD_CASE) echo "fake-aws: invalid cli-input-json $CS_DECODED" >&2; exit 2 ;;
  esac
  CS_NAME="${CS_DECODED%%|*}"
  CS_TOKEN="${CS_DECODED#*|}"
  STACKID="arn:aws:cloudformation:us-east-1:111122223333:stack/launchcrew-demo/abc123"
  case "$CS_NAME" in
    *infra*)
      CS_MODE="${FAKE_INFRA_CHANGESET:-exact}"
      python3 - "$CS_NAME" "$CS_TOKEN" "$STACKID" "${FAKE_PARAMS_FILE:-}" "$CS_MODE" <<'PYEOF'
import json, sys
name, token, stack_id, params_file, mode = sys.argv[1:6]
TD = "tas" + "k-definition"
CSID = "arn:aws:cloudformation:us-east-1:111122223333:changeSet/%s/aaaabbbbccccddddeeeeffff00001111" % name
TAGS = [{"Key": "Project", "Value": "LaunchCrew"}, {"Key": "Environment", "Value": "demo"}]
CAPS = ["CAPABILITY_NAMED_IAM"]
API_SVC = "launchcrew-demo-ApiService-A1B2C3D4E5F6"
WEB_SVC = "launchcrew-demo-WebService-G7H8I9J0K1L2"
TASKDEFS = [("ApiTaskDefinition", "api"), ("WebTaskDefinition", "web"),
            ("MigrationTaskDefinition", "migration"), ("BootstrapTaskDefinition", "bootstrap"),
            ("VerifyTaskDefinition", "verify"), ("SdkInitTaskDefinition", "sdkinit"),
            ("SdkMaterialTaskDefinition", "sdkmaterial")]
def taskdef_change(logical, repo, replacement, detail_name, recre):
    return {"Type": "Resource", "ResourceChange": {
        "Action": "Modify", "LogicalResourceId": logical,
        "PhysicalResourceId": "arn:aws:ecs:us-east-1:111122223333:%s/launchcrew-demo-%s:1" % (TD, repo),
        "ResourceType": "AWS::ECS::TaskDefinition", "Replacement": replacement,
        "Scope": ["Properties"],
        "Details": [{"Target": {"Attribute": "Properties", "Name": detail_name,
                                "RequiresRecreation": recre},
                     "Evaluation": "Static", "ChangeSource": "DirectModification"}]}}
def svc_change(logical, physical):
    return {"Type": "Resource", "ResourceChange": {
        "Action": "Modify", "LogicalResourceId": logical,
        "PhysicalResourceId": physical, "ResourceType": "AWS::ECS::Service",
        "Replacement": "False", "Scope": ["Properties"],
        "Details": [{"Target": {"Attribute": "Properties", "Name": "TaskDefinition",
                                "RequiresRecreation": "Never"},
                     "Evaluation": "Static", "ChangeSource": "DirectModification"}]}}
def base(changes, params, status="CREATE_COMPLETE", exec_status="AVAILABLE",
         reason="", tags=None, token_out=""):
    doc = {"ChangeSetName": name, "ChangeSetId": CSID, "StackName": "launchcrew-demo",
           "StackId": stack_id, "Status": status, "ExecutionStatus": exec_status,
           "Changes": changes, "Parameters": params, "Tags": tags if tags is not None else TAGS,
           "Capabilities": CAPS}
    if reason:
        doc["StatusReason"] = reason
    if token_out:
        doc["NextToken"] = token_out
    return doc
def iparams():
    with open(params_file) as handle:
        doc = json.load(handle)
    if isinstance(doc, dict) and "Parameters" in doc:
        doc = doc["Parameters"]
    out = []
    for item in doc:
        if item.get("ParameterKey") == "EnableServices":
            continue
        out.append({"ParameterKey": item["ParameterKey"],
                    "ParameterValue": item["ParameterValue"], "UsePreviousValue": False})
    out.append({"ParameterKey": "EnableServices", "ParameterValue": "false",
                "UsePreviousValue": False})
    return out
FOREIGN_DB = {"Type": "Resource", "ResourceChange": {
    "Action": "Modify", "LogicalResourceId": "Database",
    "PhysicalResourceId": "launchcrew-demo-db", "ResourceType": "AWS::RDS::DBInstance",
    "Replacement": "False", "Scope": ["Properties"]}}
FULL = [taskdef_change(logical, repo, "True", "ContainerDefinitions", "Always")
        for logical, repo in TASKDEFS]
FULL += [svc_change("ApiService", API_SVC), svc_change("WebService", WEB_SVC)]
if mode == "malformed":
    print("not-json{{{")
elif mode == "empty":
    print(json.dumps(base([], [], status="FAILED", exec_status="UNAVAILABLE",
                             reason="The submitted information didn't contain changes. Submit different information to create a change set.")))
elif mode == "foreign":
    print(json.dumps(base([FOREIGN_DB], iparams())))
elif mode == "replacement":
    bad = dict(svc_change("ApiService", API_SVC))
    bad["ResourceChange"] = dict(bad["ResourceChange"], Replacement="True")
    print(json.dumps(base([bad, svc_change("WebService", WEB_SVC)], iparams())))
elif mode == "wrong_detail":
    bad = [taskdef_change("ApiTaskDefinition", "api", "True", "ExecutionRoleArn", "Always")]
    bad += [taskdef_change(logical, repo, "True", "ContainerDefinitions", "Always")
            for logical, repo in TASKDEFS[1:]]
    print(json.dumps(base(bad, iparams())))
elif mode == "missing_details":
    entry = taskdef_change("ApiTaskDefinition", "api", "True", "ContainerDefinitions", "Always")
    del entry["ResourceChange"]["Details"]
    rest = [taskdef_change(logical, repo, "True", "ContainerDefinitions", "Always")
            for logical, repo in TASKDEFS[1:]]
    print(json.dumps(base([entry] + rest, iparams())))
elif mode == "params_mismatch":
    params = iparams()
    for item in params:
        if item["ParameterKey"] == "EnableServices":
            item["ParameterValue"] = "true"
    print(json.dumps(base(FULL, params)))
elif mode == "tags_mismatch":
    print(json.dumps(base(FULL, iparams(), tags=[{"Key": "Project", "Value": "Other"}])))
elif mode == "wrong_id":
    doc = base(FULL, iparams())
    doc["ChangeSetId"] = "arn:aws:cloudformation:us-east-1:999988887777:changeSet/infra-006/aaaabbbbccccddddeeeeffff00001111"
    print(json.dumps(doc))
elif mode == "paginated_ok":
    if not token:
        print(json.dumps(base(FULL[:5], iparams(), token_out="page2")))
    else:
        print(json.dumps(base(FULL[5:], iparams())))
elif mode == "paginated_extra":
    if not token:
        print(json.dumps(base(FULL, iparams(), token_out="page2")))
    else:
        print(json.dumps(base([FOREIGN_DB], iparams())))
elif mode == "truncated":
    print(json.dumps(base(FULL[:1], iparams(), token_out="more")))
else:
    print(json.dumps(base(FULL, iparams())))
PYEOF
      exit 0 ;;
  esac
  CS_MODE="${FAKE_CHANGESET:-exact}"
  python3 - "$CS_NAME" "$CS_TOKEN" "$STACKID" "$CS_MODE" <<'PYEOF'
import json, sys
name, token, stack_id, mode = sys.argv[1:5]
CSID = "arn:aws:cloudformation:us-east-1:111122223333:changeSet/%s/aaaabbbbccccddddeeeeffff00001111" % name
TAGS = [{"Key": "Project", "Value": "LaunchCrew"}, {"Key": "Environment", "Value": "demo"}]
CAPS = ["CAPABILITY_NAMED_IAM"]
API_SVC = "launchcrew-demo-ApiService-A1B2C3D4E5F6"
WEB_SVC = "launchcrew-demo-WebService-G7H8I9J0K1L2"
def svc_change(logical, physical, detail_name="DesiredCount", replacement="False",
               scope=None, attr="Properties", recre="Never"):
    return {"Type": "Resource", "ResourceChange": {
        "Action": "Modify", "LogicalResourceId": logical,
        "PhysicalResourceId": physical, "ResourceType": "AWS::ECS::Service",
        "Replacement": replacement, "Scope": scope or ["Properties"],
        "Details": [{"Target": {"Attribute": attr, "Name": detail_name,
                                "RequiresRecreation": recre},
                     "Evaluation": "Static", "ChangeSource": "DirectModification"}]}}
def base(changes, params, status="CREATE_COMPLETE", exec_status="AVAILABLE",
         reason="", tags=None, token_out=""):
    doc = {"ChangeSetName": name, "ChangeSetId": CSID, "StackName": "launchcrew-demo",
           "StackId": stack_id, "Status": status, "ExecutionStatus": exec_status,
           "Changes": changes, "Parameters": params, "Tags": tags if tags is not None else TAGS,
           "Capabilities": CAPS}
    if reason:
        doc["StatusReason"] = reason
    if token_out:
        doc["NextToken"] = token_out
    return doc
QPARAMS = [{"ParameterKey": "AcmCertificateArn", "UsePreviousValue": True},
           {"ParameterKey": "ApiImageUri", "UsePreviousValue": True},
           {"ParameterKey": "EnableServices", "ParameterValue": "false",
            "UsePreviousValue": False}]
QEXACT = [svc_change("ApiService", API_SVC), svc_change("WebService", WEB_SVC)]
FOREIGN_DB = {"Type": "Resource", "ResourceChange": {
    "Action": "Modify", "LogicalResourceId": "Database",
    "PhysicalResourceId": "launchcrew-demo-db", "ResourceType": "AWS::RDS::DBInstance",
    "Replacement": "False", "Scope": ["Properties"]}}
if mode == "malformed":
    print("not-json{{{")
elif mode == "empty":
    print(json.dumps(base([], QPARAMS)))
elif mode == "foreign":
    print(json.dumps(base([FOREIGN_DB], QPARAMS)))
elif mode == "replacement":
    print(json.dumps(base([svc_change("ApiService", API_SVC, replacement="True"),
                           svc_change("WebService", WEB_SVC)], QPARAMS)))
elif mode == "status_failed":
    print(json.dumps(base([], QPARAMS, status="FAILED", exec_status="UNAVAILABLE",
                             reason="No updates are to be performed")))
elif mode == "wrong_detail":
    print(json.dumps(base([svc_change("ApiService", API_SVC, detail_name="TaskDefinition"),
                           svc_change("WebService", WEB_SVC)], QPARAMS)))
elif mode == "tags_scope":
    print(json.dumps(base([svc_change("ApiService", API_SVC, scope=["Tags"]),
                           svc_change("WebService", WEB_SVC)], QPARAMS)))
elif mode == "params_mismatch":
    bad_params = [{"ParameterKey": "AcmCertificateArn", "UsePreviousValue": True},
                  {"ParameterKey": "ApiImageUri", "UsePreviousValue": True},
                  {"ParameterKey": "EnableServices", "ParameterValue": "true",
                   "UsePreviousValue": False}]
    print(json.dumps(base(QEXACT, bad_params)))
elif mode == "tags_mismatch":
    print(json.dumps(base(QEXACT, QPARAMS, tags=[{"Key": "Project", "Value": "Other"}])))
elif mode == "paginated_ok":
    if not token:
        print(json.dumps(base([svc_change("ApiService", API_SVC)], QPARAMS, token_out="page2")))
    else:
        print(json.dumps(base([svc_change("WebService", WEB_SVC)], QPARAMS)))
elif mode == "paginated_extra":
    if not token:
        print(json.dumps(base(QEXACT, QPARAMS, token_out="page2")))
    else:
        print(json.dumps(base([FOREIGN_DB], QPARAMS)))
elif mode == "truncated":
    print(json.dumps(base([svc_change("ApiService", API_SVC)], QPARAMS, token_out="more")))
else:
    print(json.dumps(base(QEXACT, QPARAMS)))
PYEOF
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "execute-change-set" ]; then
  case "$*" in
    *"changeSet/"*) ;;
    *) echo "fake-aws: execute must name the reviewed change set ID" >&2; exit 2 ;;
  esac
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "delete-change-set" ]; then
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stack-resource" ]; then
  RESOURCE_STACK=""
  RESOURCE_LOGICAL=""
  RESOURCE_PREV=""
  for RESOURCE_ARG in "$@"; do
    if [ "$RESOURCE_PREV" = "--stack-name" ]; then RESOURCE_STACK="$RESOURCE_ARG"; fi
    if [ "$RESOURCE_PREV" = "--logical-resource-id" ]; then RESOURCE_LOGICAL="$RESOURCE_ARG"; fi
    RESOURCE_PREV="$RESOURCE_ARG"
  done
  if [ "$RESOURCE_STACK" = "launchcrew-foundation" ] && [ "$RESOURCE_LOGICAL" = "BudgetTopic" ]; then
    printf '%s\\n' "${FAKE_TOPIC_ARN:-arn:aws:sns:us-east-1:111122223333:launchcrew-foundation-BudgetTopic-ABC123}"
    exit 0
  fi
  if [ "$RESOURCE_STACK" = "launchcrew-prereqs" ]; then
    case "$RESOURCE_LOGICAL" in
      MasterSecret) printf '%s\\n' "${FAKE_MASTER_ARN:-}"; exit 0 ;;
      RuntimeSecret) printf '%s\\n' "${FAKE_RT_ARN:-}"; exit 0 ;;
      MigrationSecret) printf '%s\\n' "${FAKE_MG_ARN:-}"; exit 0 ;;
      TlsSecret) printf '%s\\n' "${FAKE_TLS_ARN:-}"; exit 0 ;;
      DemoCertificate) printf '%s\\n' "${FAKE_CERT_ARN:-}"; exit 0 ;;
    esac
  fi
  case "$RESOURCE_LOGICAL" in
    ApiTaskDefinition) printf 'arn:aws:ecs:us-east-1:111122223333:task'"-definition"'/launchcrew-demo-api:1\\n'; exit 0 ;;
    WebTaskDefinition) printf 'arn:aws:ecs:us-east-1:111122223333:task'"-definition"'/launchcrew-demo-web:1\\n'; exit 0 ;;
    BootstrapTaskDefinition) printf 'arn:aws:ecs:us-east-1:111122223333:task'"-definition"'/launchcrew-demo-bootstrap:1\\n'; exit 0 ;;
    MigrationTaskDefinition) printf 'arn:aws:ecs:us-east-1:111122223333:task'"-definition"'/launchcrew-demo-migration:1\\n'; exit 0 ;;
    VerifyTaskDefinition) printf 'arn:aws:ecs:us-east-1:111122223333:task'"-definition"'/launchcrew-demo-verify:1\\n'; exit 0 ;;
    SdkInitTaskDefinition) printf 'arn:aws:ecs:us-east-1:111122223333:task'"-definition"'/launchcrew-demo-sdkinit:1\\n'; exit 0 ;;
    SdkMaterialTaskDefinition) printf 'arn:aws:ecs:us-east-1:111122223333:task'"-definition"'/launchcrew-demo-sdkmaterial:1\\n'; exit 0 ;;
    PublicSubnetA) printf 'subnet-aaa\\n'; exit 0 ;;
    PublicSubnetB) printf 'subnet-bbb\\n'; exit 0 ;;
    JobSecurityGroup) printf 'sg-ccc\\n'; exit 0 ;;
    Database) printf 'launchcrew-demo-db\\n'; exit 0 ;;
    ApiService) printf '%s\\n' "${FAKE_API_SERVICE:-launchcrew-demo-ApiService-A1B2C3D4E5F6}"; exit 0 ;;
    WebService) printf '%s\\n' "${FAKE_WEB_SERVICE:-launchcrew-demo-WebService-G7H8I9J0K1L2}"; exit 0 ;;
    ApiTargetGroup) printf '%s\\n' "${FAKE_API_TG:-arn:aws:elasticloadbalancing:us-east-1:111122223333:targetgroup/api-abcdef0123456789/0123456789abcdef}"; exit 0 ;;
    WebTargetGroup) printf '%s\\n' "${FAKE_WEB_TG:-arn:aws:elasticloadbalancing:us-east-1:111122223333:targetgroup/web-abcdef0123456789/0123456789abcdef}"; exit 0 ;;
    ApiExecutionRole|WebExecutionRole|MigrationExecutionRole|BootstrapExecutionRole|VerifyExecutionRole|SdkInitExecutionRole|SdkMaterialExecutionRole|ApiTaskRole|WebTaskRole|MigrationTaskRole|BootstrapTaskRole|VerifyTaskRole|SdkInitTaskRole|SdkMaterialTaskRole) printf '%s-physical\\n' "$RESOURCE_LOGICAL"; exit 0 ;;
  esac
  echo "fake-aws: unexpected resource lookup: $*" >&2
  exit 2
fi
if [ "$1" = "iam" ] && [ "$2" = "get-role" ]; then
  ROLE_NAME=""
  ROLE_PREV=""
  for ROLE_ARG in "$@"; do
    if [ "$ROLE_PREV" = "--role-name" ]; then ROLE_NAME="$ROLE_ARG"; fi
    ROLE_PREV="$ROLE_ARG"
  done
  printf 'arn:aws:iam::111122223333:role/%s\\n' "$ROLE_NAME"
  exit 0
fi
if [ "$1" = "rds" ] && [ "$2" = "describe-db-instances" ]; then
  printf '%s\\n' "${FAKE_DB_HOST:-launchcrew-demo.abc123.us-east-1.rds.amazonaws.com}"
  exit 0
fi
if [ "$1" = "budgets" ] && [ "$2" = "describe-notifications-for-budget" ]; then
  NOTIF_MODE="${FAKE_NOTIF:-exact}"
  if [ "$NOTIF_MODE" = "auth" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeNotificationsForBudget operation: not authorized" >&2
    exit 254
  fi
  if [ "$NOTIF_MODE" = "error" ]; then
    echo "An error occurred (ThrottlingException) when calling the DescribeNotificationsForBudget operation: Rate exceeded" >&2
    exit 254
  fi
  if [ "$NOTIF_MODE" = "malformed" ]; then printf 'not-json{{{\\n'; exit 0; fi
  case "$*" in
    *"--next-token"*) echo "fake-aws: unsupported --next-token rejected, use --cli-input-json NextToken" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--starting-token"*|*"--max-items"*) echo "fake-aws: high level pagination args rejected with --no-paginate" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--no-paginate"*) ;;
    *) echo "fake-aws: unbounded autopagination rejected, --no-paginate required" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--cli-input-json"*) ;;
    *) echo "fake-aws: --cli-input-json required" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--account-id"*|*"--budget-name"*) echo "fake-aws: raw JSON required, flag pagination refused" >&2; exit 2 ;;
  esac
  NOTIF_INPUT_PATH=""
  NOTIF_INPUT_PREV=""
  for NOTIF_ARG in "$@"; do
    if [ "$NOTIF_INPUT_PREV" = "--cli-input-json" ]; then NOTIF_INPUT_PATH="$NOTIF_ARG"; fi
    NOTIF_INPUT_PREV="$NOTIF_ARG"
  done
  case "$NOTIF_INPUT_PATH" in
    file://*) NOTIF_INPUT_PATH="${NOTIF_INPUT_PATH#file://}" ;;
    *) echo "fake-aws: --cli-input-json must be file:// path" >&2; exit 2 ;;
  esac
  echo "INPUT_JSON_NOTIF $(cat "$NOTIF_INPUT_PATH" 2>/dev/null || echo MALFORMED)" >>"$LOG" 2>/dev/null || true
  NOTIF_NEXT="$(python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); a=d.get("AccountId",""); b=d.get("BudgetName",""); m=d.get("MaxResults",None); n=d.get("NextToken",""); nn=d.get("nextToken","__absent__"); bad=""; 
if a!="111122223333": bad="BAD_ACCOUNT"; 
elif b!="launchcrew-demo": bad="BAD_BUDGET"; 
elif not isinstance(m,int) or m<=0 or m>10: bad="BAD_MAXRESULTS"; 
elif nn!="__absent__": bad="BAD_CASE"; 
elif n is None: n=""; 
elif not isinstance(n,str): bad="MALFORMED_INPUT"; 
print(bad if bad else n)' "$NOTIF_INPUT_PATH" 2>/dev/null || echo MALFORMED_INPUT)"
  case "$NOTIF_NEXT" in
    MALFORMED_INPUT|BAD_ACCOUNT|BAD_BUDGET|BAD_MAXRESULTS|BAD_CASE) echo "fake-aws: invalid cli-input-json $NOTIF_NEXT" >&2; exit 2 ;;
  esac
  if [ "$NOTIF_MODE" = "paginated_ok" ]; then
    if [ -z "$NOTIF_NEXT" ]; then
      printf '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"}],"NextToken":"page2"}\\n'
      exit 0
    fi
    printf '{"Notifications":[{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}\\n'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "paginated_extra" ]; then
    if [ -z "$NOTIF_NEXT" ]; then
      printf '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}],"NextToken":"page2"}\\n'
      exit 0
    fi
    printf '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":90,"ThresholdType":"PERCENTAGE"}]}\\n'
    exit 0
  fi
  if [ -n "$NOTIF_NEXT" ]; then
    printf '{"Notifications":[]}\\n'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "missing" ]; then
    printf '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"}]}\\n'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "wrong" ]; then
    printf '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":50,"ThresholdType":"PERCENTAGE"},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}\\n'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "duplicate" ]; then
    printf '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}\\n'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "missing_type" ]; then
    printf '%s' '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100}]}'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "absolute" ]; then
    printf '%s' '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"ABSOLUTE_VALUE"},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "absolute_short" ]; then
    printf '%s' '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"ABSOLUTE"},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "null_type" ]; then
    printf '%s' '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":null},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "unknown_type" ]; then
    printf '%s' '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"UNKNOWN"},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "empty_type" ]; then
    printf '%s' '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":""},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "extra" ]; then
    printf '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":90,"ThresholdType":"PERCENTAGE"}]}\\n'
    exit 0
  fi
  printf '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}\\n'
  exit 0
fi
if [ "$1" = "budgets" ] && [ "$2" = "describe-subscribers-for-notification" ]; then
  SUB_MODE="${FAKE_SUB:-exact}"
  if [ "$SUB_MODE" = "auth" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeSubscribersForNotification operation: not authorized" >&2
    exit 254
  fi
  if [ "$SUB_MODE" = "malformed" ]; then printf 'not-json{{{\\n'; exit 0; fi
  case "$*" in
    *"--next-token"*) echo "fake-aws: unsupported --next-token rejected, use --cli-input-json NextToken" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--starting-token"*|*"--max-items"*) echo "fake-aws: high level pagination args rejected with --no-paginate" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--no-paginate"*) ;;
    *) echo "fake-aws: unbounded autopagination rejected, --no-paginate required" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--cli-input-json"*) ;;
    *) echo "fake-aws: --cli-input-json required" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--account-id"*|*"--budget-name"*|*"--notification"*) echo "fake-aws: raw JSON required, flag pagination refused" >&2; exit 2 ;;
  esac
  SUB_TOPIC="${FAKE_TOPIC_ARN:-arn:aws:sns:us-east-1:111122223333:launchcrew-foundation-BudgetTopic-ABC123}"
  SUB_INPUT_PATH=""
  SUB_INPUT_PREV=""
  for SUB_ARG in "$@"; do
    if [ "$SUB_INPUT_PREV" = "--cli-input-json" ]; then SUB_INPUT_PATH="$SUB_ARG"; fi
    SUB_INPUT_PREV="$SUB_ARG"
  done
  case "$SUB_INPUT_PATH" in
    file://*) SUB_INPUT_PATH="${SUB_INPUT_PATH#file://}" ;;
    *) echo "fake-aws: --cli-input-json must be file:// path" >&2; exit 2 ;;
  esac
  echo "INPUT_JSON_SUB $(cat "$SUB_INPUT_PATH" 2>/dev/null || echo MALFORMED)" >>"$LOG" 2>/dev/null || true
  SUB_DECODED="$(python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); a=d.get("AccountId",""); b=d.get("BudgetName",""); m=d.get("MaxResults",None); n=d.get("NextToken",""); nn=d.get("nextToken","__absent__"); nt=d.get("Notification",None); bad=""; typ=""; 
if a!="111122223333": bad="BAD_ACCOUNT"; 
elif b!="launchcrew-demo": bad="BAD_BUDGET"; 
elif not isinstance(m,int) or m<=0 or m>10: bad="BAD_MAXRESULTS"; 
elif nn!="__absent__": bad="BAD_CASE"; 
elif not isinstance(nt,dict): bad="BAD_NOTIFICATION"; 
elif nt.get("ThresholdType","")!="PERCENTAGE": bad="BAD_THRESHOLD_TYPE"; 
elif n is None: n=""; 
elif not isinstance(n,str): bad="MALFORMED_INPUT"; 
else: typ=nt.get("NotificationType",""); 
print(bad if bad else (typ+"|"+n))' "$SUB_INPUT_PATH" 2>/dev/null || echo MALFORMED_INPUT)"
  case "$SUB_DECODED" in
    MALFORMED_INPUT|BAD_ACCOUNT|BAD_BUDGET|BAD_MAXRESULTS|BAD_CASE|BAD_NOTIFICATION|BAD_THRESHOLD_TYPE) echo "fake-aws: invalid cli-input-json $SUB_DECODED" >&2; exit 2 ;;
  esac
  SUB_IS_ACTUAL=0
  case "$SUB_DECODED" in
    ACTUAL\\|*) SUB_IS_ACTUAL=1 ;;
  esac
  SUB_NEXT_TOKEN="${SUB_DECODED#*|}"
  if [ -n "$SUB_NEXT_TOKEN" ]; then
    printf '%s' '{"Subscribers":[]}'
    exit 0
  fi
  if [ "$SUB_MODE" = "mismatch_actual" ] && [ "$SUB_IS_ACTUAL" -eq 1 ]; then
    printf '{"Subscribers":[{"SubscriptionType":"SNS","Address":"arn:aws:sns:us-east-1:111122223333:other-topic"}]}\\n'
    exit 0
  fi
  if [ "$SUB_MODE" = "mismatch_forecasted" ] && [ "$SUB_IS_ACTUAL" -eq 0 ]; then
    printf '{"Subscribers":[{"SubscriptionType":"EMAIL","Address":"%s"}]}\\n' "$SUB_TOPIC"
    exit 0
  fi
  if [ "$SUB_MODE" = "retargeted" ]; then
    printf '{"Subscribers":[{"SubscriptionType":"SNS","Address":"arn:aws:sns:us-east-1:111122223333:other-topic"}]}\\n'
    exit 0
  fi
  if [ "$SUB_MODE" = "duplicate" ]; then
    printf '{"Subscribers":[{"SubscriptionType":"SNS","Address":"%s"},{"SubscriptionType":"SNS","Address":"%s"}]}\\n' "$SUB_TOPIC" "$SUB_TOPIC"
    exit 0
  fi
  if [ "$SUB_MODE" = "empty" ]; then
    printf '{"Subscribers":[]}\\n'
    exit 0
  fi
  printf '{"Subscribers":[{"SubscriptionType":"SNS","Address":"%s"}]}\\n' "$SUB_TOPIC"
  exit 0
fi
if [ "$1" = "sns" ] && [ "$2" = "list-subscriptions-by-topic" ]; then
  SNS_MODE="${FAKE_SNS:-exact}"
  SNS_TOPIC="${FAKE_TOPIC_ARN:-arn:aws:sns:us-east-1:111122223333:launchcrew-foundation-BudgetTopic-ABC123}"
  SNS_EMAIL="${FAKE_NOTIFY_EMAIL:-}"
  [ -n "$SNS_EMAIL" ] || SNS_EMAIL=owner@"example.test"
  if [ "$SNS_MODE" = "auth" ]; then
    echo "An error occurred (AccessDenied) when calling the ListSubscriptionsByTopic operation: not authorized" >&2
    exit 254
  fi
  if [ "$SNS_MODE" = "pending" ]; then
    printf '{"Subscriptions":[{"Owner":"111122223333","Protocol":"email","Endpoint":"%s","TopicArn":"%s","SubscriptionArn":"PendingConfirmation"}]}\\n' "$SNS_EMAIL" "$SNS_TOPIC"
    exit 0
  fi
  printf '{"Subscriptions":[{"Owner":"111122223333","Protocol":"email","Endpoint":"%s","TopicArn":"%s","SubscriptionArn":"%s:12345678-90ab-cdef-1234-567890abcdef"}]}\\n' "$SNS_EMAIL" "$SNS_TOPIC" "$SNS_TOPIC"
  exit 0
fi
if [ "$1" = "acm" ] && [ "$2" = "describe-certificate" ]; then
  CERT_MODE="${FAKE_CERT:-issued}"
  CERT_ARN_VALUE="${FAKE_CERT_ARN:-arn:aws:acm:us-east-1:111122223333:certificate/12345678-90ab-cdef-1234-567890abcde1}"
  CERT_STATUS="ISSUED"
  if [ "$CERT_MODE" = "pending" ]; then CERT_STATUS="PENDING_VALIDATION"; fi
  if [ "$CERT_MODE" = "wrong" ]; then CERT_STATUS="EXPIRED"; fi
  printf '{"Certificate":{"CertificateArn":"%s","DomainName":"launchcrew.summitsingh.com","SubjectAlternativeNames":["launchcrew.summitsingh.com"],"Status":"%s","Type":"AMAZON_ISSUED","Options":{"Export":"ENABLED"}}}\\n' "$CERT_ARN_VALUE" "$CERT_STATUS"
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "list-tasks" ]; then
  case "$*" in
    *"--next-token"*) echo "fake-aws: unsupported --next-token rejected, use --cli-input-json nextToken" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--starting-token"*|*"--max-items"*) echo "fake-aws: high level pagination args rejected with --no-paginate" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--no-paginate"*) ;;
    *) echo "fake-aws: unbounded autopagination rejected, --no-paginate required" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--cli-input-json"*) ;;
    *) echo "fake-aws: --cli-input-json required" >&2; exit 2 ;;
  esac
  case "$*" in
    *"--cluster "*|*"--cluster="*|*"--started-by"*|*"--desired-status"*) echo "fake-aws: raw JSON required, flag filters refused" >&2; exit 2 ;;
  esac
  LIST_INPUT_PATH=""
  LIST_INPUT_PREV=""
  for LIST_ARG in "$@"; do
    if [ "$LIST_INPUT_PREV" = "--cli-input-json" ]; then LIST_INPUT_PATH="$LIST_ARG"; fi
    LIST_INPUT_PREV="$LIST_ARG"
  done
  case "$LIST_INPUT_PATH" in
    file://*) LIST_INPUT_PATH="${LIST_INPUT_PATH#file://}" ;;
    *) echo "fake-aws: --cli-input-json must be file:// path" >&2; exit 2 ;;
  esac
  echo "INPUT_JSON_LIST $(cat "$LIST_INPUT_PATH" 2>/dev/null || echo MALFORMED)" >>"$LOG" 2>/dev/null || true
  LIST_DECODED="$(python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); c=d.get("cluster",""); s=d.get("startedBy",""); w=d.get("desiredStatus",""); m=d.get("maxResults",None); n=d.get("nextToken",""); nn=d.get("NextToken","__absent__"); bad=""; 
if c!="launchcrew-demo": bad="BAD_CLUSTER"; 
elif s and w: bad="COMBINED"; 
elif not isinstance(m,int) or m<=0 or m>10: bad="BAD_MAXRESULTS"; 
elif nn!="__absent__": bad="BAD_CASE"; 
elif n is None: n=""; 
elif not isinstance(n,str): bad="MALFORMED_INPUT"; 
print(bad if bad else (s+"|"+w+"|"+n))' "$LIST_INPUT_PATH" 2>/dev/null || echo MALFORMED_INPUT)"
  case "$LIST_DECODED" in
    MALFORMED_INPUT|BAD_CLUSTER|BAD_MAXRESULTS|BAD_CASE) echo "fake-aws: invalid cli-input-json $LIST_DECODED" >&2; exit 2 ;;
    COMBINED) echo "An error occurred (InvalidParameterException) when calling the ListTasks operation: startedBy and desiredStatus cannot be combined" >&2; exit 254 ;;
  esac
  LIST_TOKEN="$(printf '%s' "$LIST_DECODED" | cut -d'|' -f1)"
  LIST_DESIRED="$(printf '%s' "$LIST_DECODED" | cut -d'|' -f2)"
  LIST_NEXT="$(printf '%s' "$LIST_DECODED" | cut -d'|' -f3)"
  if [ -n "$LIST_TOKEN" ]; then printf '%s' "$LIST_TOKEN" >"${FAKE_TOKEN_FILE:-/dev/null}" 2>/dev/null || true; fi
  if [ -n "$LIST_NEXT" ]; then printf '%s' '{"taskArns":[]}'; exit 0; fi
  printf '%s' '{"taskArns":[]}'
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "deploy" ]; then
  case "$*" in
    *"--parameter-file"*) echo "Unknown options: --parameter-file" >&2; exit 2 ;;
  esac
  if [ -n "$FAKE_STACK_CREATED_FILE" ]; then : >"$FAKE_STACK_CREATED_FILE" 2>/dev/null || true; fi
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
    *"imageId.imageDigest"*)
      if [ "$MODE" = "image_digest_none" ]; then printf 'None\\n'; exit 0; fi
      printf 'sha256:abc123\\n'; exit 0 ;;
    *"imageDigest"*)
      printf 'None\\n'; exit 0 ;;
    *"failures"*)
      if [ "$MODE" = "image_failures" ]; then printf '1\\n'; exit 0; fi
      printf '0\\n'; exit 0 ;;
  esac
  printf '{"images":[{"imageId":{"imageDigest":"sha256:abc123","imageTag":"abc123"}}],"failures":[]}\\n'
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "run-task" ]; then
  COUNT_FILE="${FAKE_COUNT_FILE:-/dev/null}"
  n=0
  if [ -f "$COUNT_FILE" ]; then n="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"; fi
  n=$((n + 1))
  printf '%s' "$n" >"$COUNT_FILE" 2>/dev/null || true
  TASKDEF=""
  RUN_TOKEN=""
  PREV=""
  for ARG in "$@"; do
    if [ "$PREV" = "--task""-definition" ]; then TASKDEF="$ARG"; fi
    if [ "$PREV" = "--started-by" ]; then RUN_TOKEN="$ARG"; fi
    PREV="$ARG"
  done
  if [ -n "$RUN_TOKEN" ]; then printf '%s' "$RUN_TOKEN" >"${FAKE_TOKEN_FILE:-/dev/null}" 2>/dev/null || true; fi
  TASKARN="$(printf 'arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task%03d' "$n")"
  printf '%s|%s|%s\\n' "$TASKARN" "$TASKDEF" "$RUN_TOKEN" >>"${FAKE_TASKDEF_FILE:-/dev/null}" 2>/dev/null || true
  if [ "$MODE" = "runtask_empty" ]; then printf '{"tasks":[],"failures":[]}\\n'; exit 0; fi
  if [ "$MODE" = "runtask_failures" ]; then printf '{"tasks":[],"failures":[{"arn":"x","reason":"FAIL"}]}\\n'; exit 0; fi
  printf '{"tasks":[{"taskArn":"%s"}],"failures":[]}\\n' "$TASKARN"
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
  REQUESTED=""
  REQUESTED_PREV=""
  for REQUESTED_ARG in "$@"; do
    if [ "$REQUESTED_PREV" = "--tasks" ]; then REQUESTED="$REQUESTED_ARG"; fi
    REQUESTED_PREV="$REQUESTED_ARG"
  done
  TASK_LINE=""
  if [ -n "$REQUESTED" ] && [ -n "${FAKE_TASKDEF_FILE:-}" ] && [ -f "$FAKE_TASKDEF_FILE" ]; then
    TASK_LINE="$(grep -F "$REQUESTED|" "$FAKE_TASKDEF_FILE" 2>/dev/null | tail -n 1 || true)"
  fi
  if [ -z "$TASK_LINE" ]; then
    TASK_LINE="$(tail -n 1 "${FAKE_TASKDEF_FILE:-/dev/null}" 2>/dev/null || true)"
  fi
  TASKARN="$(printf '%s' "$TASK_LINE" | cut -d'|' -f1)"
  TASKDEF="$(printf '%s' "$TASK_LINE" | cut -d'|' -f2)"
  LINE_TOKEN="$(printf '%s' "$TASK_LINE" | cut -s -d'|' -f3)"
  EXIT0=0
  case "$TASKDEF" in
    *migration*) if [ "$MODE" = "migrate_fail" ]; then EXIT0=1; fi ;;
    *verify*) if [ "$MODE" = "verify_fail" ]; then EXIT0=1; fi ;;
  esac
  case "$TASKDEF" in
    *launchcrew-demo-api*) NAMES="api" ;;
    *launchcrew-demo-web*) NAMES="web-app web-proxy" ;;
    *launchcrew-demo-migration*) NAMES="migration" ;;
    *launchcrew-demo-sdkinit*) NAMES="sdk-init" ;;
    *launchcrew-demo-sdkmaterial*) NAMES="sdk-material" ;;
    *) NAMES="bootstrap-db-roles" ;;
  esac
  CONTAINERS=""
  for NAME in $NAMES; do
    ENTRY="$(printf '{"name":"%s","lastStatus":"STOPPED","exitCode":%s}' "$NAME" "$EXIT0")"
    if [ -z "$CONTAINERS" ]; then CONTAINERS="$ENTRY"; else CONTAINERS="$CONTAINERS,$ENTRY"; fi
  done
  STARTED_BY="$LINE_TOKEN"
  if [ -z "$STARTED_BY" ] && [ -n "${FAKE_TOKEN_FILE:-}" ] && [ -f "$FAKE_TOKEN_FILE" ]; then
    STARTED_BY="$(cat "$FAKE_TOKEN_FILE" 2>/dev/null || true)"
  fi
  if [ -n "$STARTED_BY" ]; then
    printf '{"tasks":[{"taskArn":"%s","clusterArn":"arn:aws:ecs:us-east-1:111122223333:cluster/launchcrew-demo","taskDefinitionArn":"%s","lastStatus":"STOPPED","startedBy":"%s","containers":[%s]}],"failures":[]}\\n' "$TASKARN" "$TASKDEF" "$STARTED_BY" "$CONTAINERS"
  else
    printf '{"tasks":[{"taskArn":"%s","clusterArn":"arn:aws:ecs:us-east-1:111122223333:cluster/launchcrew-demo","taskDefinitionArn":"%s","lastStatus":"STOPPED","containers":[%s]}],"failures":[]}\\n' "$TASKARN" "$TASKDEF" "$CONTAINERS"
  fi
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-task""-definition" ]; then
  TASKDEF=""
  PREV=""
  for ARG in "$@"; do
    if [ "$PREV" = "--task""-definition" ]; then TASKDEF="$ARG"; fi
    PREV="$ARG"
  done
  IMG_API="${FAKE_API_IMAGE:-}"
  IMG_WEB="${FAKE_WEB_IMAGE:-}"
  IMG_PROXY="${FAKE_WEB_PROXY_IMAGE:-}"
  IMG_MIG="${FAKE_MIGRATION_IMAGE:-}"
  IMG_BOOT="${FAKE_BOOTSTRAP_IMAGE:-}"
  SEC_RT="${FAKE_RT_ARN:-}"
  SEC_MG="${FAKE_MG_ARN:-}"
  SEC_MASTER="${FAKE_MASTER_ARN:-}"
  SEC_TLS="${FAKE_TLS_ARN:-}"
  if [ "$MODE" = "taskdef_image_mismatch" ]; then
    IMG_API="111122223333.dkr.ecr.us-east-1.amazonaws.com/wrong-repo:bad"
    IMG_WEB="111122223333.dkr.ecr.us-east-1.amazonaws.com/wrong-repo:bad"
    IMG_PROXY="111122223333.dkr.ecr.us-east-1.amazonaws.com/wrong-repo:bad"
    IMG_MIG="111122223333.dkr.ecr.us-east-1.amazonaws.com/wrong-repo:bad"
    IMG_BOOT="111122223333.dkr.ecr.us-east-1.amazonaws.com/wrong-repo:bad"
  fi
  if [ "$MODE" = "taskdef_flip" ] && grep -q "EnableServices=true" "$LOG" 2>/dev/null; then
    IMG_API="111122223333.dkr.ecr.us-east-1.amazonaws.com/launchcrew-api:tampered"
    IMG_WEB="111122223333.dkr.ecr.us-east-1.amazonaws.com/launchcrew-web:tampered"
    IMG_PROXY="111122223333.dkr.ecr.us-east-1.amazonaws.com/launchcrew-web-proxy:tampered"
    IMG_MIG="111122223333.dkr.ecr.us-east-1.amazonaws.com/launchcrew-migration:tampered"
    IMG_BOOT="111122223333.dkr.ecr.us-east-1.amazonaws.com/launchcrew-bootstrap:tampered"
  fi
  if [ "$MODE" = "taskdef_secret_mismatch" ]; then
    SEC_RT="arn:aws:secretsmanager:us-east-1:111122223333:secret:other-secret-ZzZzZz"
    SEC_MG="arn:aws:secretsmanager:us-east-1:111122223333:secret:other-secret-ZzZzZz"
    SEC_MASTER="arn:aws:secretsmanager:us-east-1:111122223333:secret:other-secret-ZzZzZz"
    SEC_TLS="arn:aws:secretsmanager:us-east-1:111122223333:secret:other-secret-ZzZzZz"
  fi
  EXEC_SUFFIX="-physical"
  if [ "$MODE" = "role_mismatch" ]; then EXEC_SUFFIX="-wrong"; fi
  case "$TASKDEF" in
    *launchcrew-demo-api*)
      printf '{"taskDefinition":{"executionRoleArn":"arn:aws:iam::111122223333:role/ApiExecutionRole%s","taskRoleArn":"arn:aws:iam::111122223333:role/ApiTaskRole%s","containerDefinitions":[{"name":"api","essential":true,"image":"%s","secrets":[{"name":"DATABASE_URL","valueFrom":"%s:database-url::"},{"name":"TLS_CERT_B64","valueFrom":"%s:tls-cert-b64::"},{"name":"TLS_KEY_B64","valueFrom":"%s:tls-key-b64::"}]}]}}\\n' "$EXEC_SUFFIX" "$EXEC_SUFFIX" "$IMG_API" "$SEC_RT" "$SEC_TLS" "$SEC_TLS"
      exit 0 ;;
    *launchcrew-demo-web*)
      printf '{"taskDefinition":{"executionRoleArn":"arn:aws:iam::111122223333:role/WebExecutionRole%s","taskRoleArn":"arn:aws:iam::111122223333:role/WebTaskRole%s","containerDefinitions":[{"name":"web-app","essential":true,"image":"%s","secrets":[]},{"name":"web-proxy","essential":true,"image":"%s","secrets":[{"name":"TLS_CERT_B64","valueFrom":"%s:tls-cert-b64::"},{"name":"TLS_KEY_B64","valueFrom":"%s:tls-key-b64::"}]}]}}\\n' "$EXEC_SUFFIX" "$EXEC_SUFFIX" "$IMG_WEB" "$IMG_PROXY" "$SEC_TLS" "$SEC_TLS"
      exit 0 ;;
    *launchcrew-demo-migration*)
      printf '{"taskDefinition":{"executionRoleArn":"arn:aws:iam::111122223333:role/MigrationExecutionRole%s","taskRoleArn":"arn:aws:iam::111122223333:role/MigrationTaskRole%s","containerDefinitions":[{"name":"migration","essential":true,"image":"%s","secrets":[{"name":"DATABASE_URL","valueFrom":"%s:database-url::"}]}]}}\\n' "$EXEC_SUFFIX" "$EXEC_SUFFIX" "$IMG_MIG" "$SEC_MG"
      exit 0 ;;
    *launchcrew-demo-bootstrap*)
      printf '{"taskDefinition":{"executionRoleArn":"arn:aws:iam::111122223333:role/BootstrapExecutionRole%s","taskRoleArn":"arn:aws:iam::111122223333:role/BootstrapTaskRole%s","containerDefinitions":[{"name":"bootstrap-db-roles","essential":true,"image":"%s","secrets":[{"name":"MASTER_DB_PASSWORD","valueFrom":"%s:password::"},{"name":"RUNTIME_DB_URL","valueFrom":"%s:database-url::"},{"name":"MIGRATION_DB_URL","valueFrom":"%s:database-url::"}]}]}}\\n' "$EXEC_SUFFIX" "$EXEC_SUFFIX" "$IMG_BOOT" "$SEC_MASTER" "$SEC_RT" "$SEC_MG"
      exit 0 ;;
    *launchcrew-demo-verify*)
      printf '{"taskDefinition":{"executionRoleArn":"arn:aws:iam::111122223333:role/VerifyExecutionRole%s","taskRoleArn":"arn:aws:iam::111122223333:role/VerifyTaskRole%s","containerDefinitions":[{"name":"bootstrap-db-roles","essential":true,"image":"%s","secrets":[{"name":"RUNTIME_DB_URL","valueFrom":"%s:database-url::"}]}]}}\\n' "$EXEC_SUFFIX" "$EXEC_SUFFIX" "$IMG_BOOT" "$SEC_RT"
      exit 0 ;;
    *launchcrew-demo-sdkinit*)
      SDK_CERT="${FAKE_CERT_ARN:-}"
      SDK_HOST="${FAKE_DB_HOST:-}"
      printf '{"taskDefinition":{"executionRoleArn":"arn:aws:iam::111122223333:role/SdkInitExecutionRole%s","taskRoleArn":"arn:aws:iam::111122223333:role/SdkInitTaskRole%s","containerDefinitions":[{"name":"sdk-init","essential":true,"image":"%s","entryPoint":["/opt/venv/bin/python","/app/scripts/populate_prereqs.py"],"command":["--populate"],"environment":[{"name":"LAUNCHCREW_EXPECTED_ACCOUNT","value":"111122223333"},{"name":"LAUNCHCREW_EXPECTED_REGION","value":"us-east-1"},{"name":"LAUNCHCREW_EXPECTED_ROLE","value":"SdkInitTaskRole-physical"},{"name":"LAUNCHCREW_MASTER_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_RUNTIME_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_MIGRATION_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_TLS_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_CERT_ARN","value":"%s"},{"name":"LAUNCHCREW_DB_HOST","value":"%s"},{"name":"LAUNCHCREW_DB_TLS_MODE","value":"verify-full"},{"name":"DATABASE_SSL_ROOTCERT","value":"/app/rds-ca-bundle.pem"}]}]}}\\n' "$EXEC_SUFFIX" "$EXEC_SUFFIX" "$IMG_BOOT" "$SEC_MASTER" "$SEC_RT" "$SEC_MG" "$SEC_TLS" "$SDK_CERT" "$SDK_HOST"
      exit 0 ;;
    *launchcrew-demo-sdkmaterial*)
      SDK_CERT="${FAKE_CERT_ARN:-}"
      SDK_HOST="${FAKE_DB_HOST:-}"
      printf '{"taskDefinition":{"executionRoleArn":"arn:aws:iam::111122223333:role/SdkMaterialExecutionRole%s","taskRoleArn":"arn:aws:iam::111122223333:role/SdkMaterialTaskRole%s","containerDefinitions":[{"name":"sdk-material","essential":true,"image":"%s","entryPoint":["/opt/venv/bin/python","/app/scripts/populate_prereqs.py"],"command":["--verify-material"],"environment":[{"name":"LAUNCHCREW_EXPECTED_ACCOUNT","value":"111122223333"},{"name":"LAUNCHCREW_EXPECTED_REGION","value":"us-east-1"},{"name":"LAUNCHCREW_EXPECTED_ROLE","value":"SdkMaterialTaskRole-physical"},{"name":"LAUNCHCREW_MASTER_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_RUNTIME_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_MIGRATION_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_TLS_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_CERT_ARN","value":"%s"},{"name":"LAUNCHCREW_DB_HOST","value":"%s"},{"name":"LAUNCHCREW_DB_TLS_MODE","value":"verify-full"},{"name":"DATABASE_SSL_ROOTCERT","value":"/app/rds-ca-bundle.pem"}]}]}}\\n' "$EXEC_SUFFIX" "$EXEC_SUFFIX" "$IMG_BOOT" "$SEC_MASTER" "$SEC_RT" "$SEC_MG" "$SEC_TLS" "$SDK_CERT" "$SDK_HOST"
      exit 0 ;;
    *) echo "fake-aws: unexpected describe task definition: $*" >&2; exit 2 ;;
  esac
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-services" ]; then
  SVC_ARG=""
  SVC_PREV=""
  for SVC_ITEM in "$@"; do
    if [ "$SVC_PREV" = "--services" ]; then SVC_ARG="$SVC_ITEM"; fi
    SVC_PREV="$SVC_ITEM"
  done
  OWNED_API="${FAKE_API_SERVICE:-launchcrew-demo-ApiService-A1B2C3D4E5F6}"
  OWNED_WEB="${FAKE_WEB_SERVICE:-launchcrew-demo-WebService-G7H8I9J0K1L2}"
  SVC_MODE="${FAKE_SERVICE:-auto}"
  if [ "$SVC_MODE" = "auto" ]; then
    if grep -q "EnableServices=true" "$LOG" 2>/dev/null; then SVC_MODE="ok"; else SVC_MODE="stopped"; fi
  fi
  if [ "$MODE" = "enable_wrong" ]; then
    if grep -q "EnableServices=true" "$LOG" 2>/dev/null; then SVC_MODE="desired2"; else SVC_MODE="stopped"; fi
  fi
  case "$SVC_ARG" in
    "$OWNED_API"|"$OWNED_WEB") ;;
    *) printf '{"services":[],"failures":[{"arn":"arn:aws:ecs:us-east-1:111122223333:service/launchcrew-demo/%s","reason":"MISSING"}]}\\n' "$SVC_ARG"; exit 0 ;;
  esac
  SVC_NAME="$SVC_ARG"
  SVC_ARN="arn:aws:ecs:us-east-1:111122223333:service/launchcrew-demo/$SVC_NAME"
  SVC_CLUSTER="arn:aws:ecs:us-east-1:111122223333:cluster/launchcrew-demo"
  SVC_STATUS="ACTIVE"
  SVC_DESIRED=1
  SVC_RUNNING=1
  SVC_PENDING=0
  if [ "$SVC_MODE" = "malformed" ]; then printf 'not-json{{{\\n'; exit 0; fi
  if [ "$SVC_MODE" = "empty" ]; then printf '{"services":[],"failures":[]}\\n' "$SVC_ARN"; exit 0; fi
  if [ "$SVC_MODE" = "duplicate" ]; then printf '{"services":[{"serviceArn":"%s","serviceName":"%s","clusterArn":"%s","status":"ACTIVE","desiredCount":1,"runningCount":1,"pendingCount":0},{"serviceArn":"%s","serviceName":"%s","clusterArn":"%s","status":"ACTIVE","desiredCount":1,"runningCount":1,"pendingCount":0}],"failures":[]}\\n' "$SVC_ARN" "$SVC_NAME" "$SVC_CLUSTER" "$SVC_ARN" "$SVC_NAME" "$SVC_CLUSTER"; exit 0; fi
  if [ "$SVC_MODE" = "wrong" ]; then SVC_NAME="other-service"; SVC_ARN="arn:aws:ecs:us-east-1:111122223333:service/launchcrew-demo/other-service"; fi
  if [ "$SVC_MODE" = "wrong_cluster" ]; then SVC_CLUSTER="arn:aws:ecs:us-east-1:111122223333:cluster/other-cluster"; fi
  if [ "$SVC_MODE" = "inactive" ]; then SVC_STATUS="DRAINING"; fi
  if [ "$SVC_MODE" = "desired" ]; then SVC_DESIRED=0; fi
  if [ "$SVC_MODE" = "desired2" ]; then SVC_DESIRED=2; SVC_RUNNING=0; fi
  if [ "$SVC_MODE" = "running" ]; then SVC_RUNNING=0; fi
  if [ "$SVC_MODE" = "pending" ]; then SVC_PENDING=1; fi
  if [ "$SVC_MODE" = "stopped" ]; then SVC_DESIRED=0; SVC_RUNNING=0; SVC_PENDING=0; fi
  if [ "$SVC_MODE" = "failures" ]; then printf '{"services":[{"serviceArn":"%s","serviceName":"%s","clusterArn":"%s","status":"%s","desiredCount":%s,"runningCount":%s,"pendingCount":%s}],"failures":[{"arn":"%s","reason":"FAIL"}]}\\n' "$SVC_ARN" "$SVC_NAME" "$SVC_CLUSTER" "$SVC_STATUS" "$SVC_DESIRED" "$SVC_RUNNING" "$SVC_PENDING" "$SVC_ARN"; exit 0; fi
  printf '{"services":[{"serviceArn":"%s","serviceName":"%s","clusterArn":"%s","status":"%s","desiredCount":%s,"runningCount":%s,"pendingCount":%s}],"failures":[]}\\n' "$SVC_ARN" "$SVC_NAME" "$SVC_CLUSTER" "$SVC_STATUS" "$SVC_DESIRED" "$SVC_RUNNING" "$SVC_PENDING"
  exit 0
fi
if [ "$1" = "budgets" ] && [ "$2" = "describe-budget" ]; then
  BUDGET_MODE="${FAKE_BUDGET:-exact}"
  if [ "$BUDGET_MODE" = "auth" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeBudget operation: not authorized" >&2
    exit 254
  fi
  if [ "$BUDGET_MODE" = "error" ]; then
    echo "An error occurred (ThrottlingException) when calling the DescribeBudget operation: Rate exceeded" >&2
    exit 254
  fi
  if [ "$BUDGET_MODE" = "malformed" ]; then printf 'not-json{{{\\n'; exit 0; fi
  FILTER='{"Tags":{"Key":"Project","Values":["LaunchCrew"],"MatchOptions":["EQUALS"]}}'
  case "$BUDGET_MODE" in
    exact) ;;
    unfiltered) FILTER='{"Dimensions":{"Key":"SERVICE","Values":["Amazon Elastic Compute Cloud"]}}' ;;
    wrongtag) FILTER='{"Tags":{"Key":"Project","Values":["Prod"],"MatchOptions":["EQUALS"]}}' ;;
    multi) FILTER='{"Tags":{"Key":"Project","Values":["LaunchCrew","Prod"],"MatchOptions":["EQUALS"]}}' ;;
    broad) FILTER='{"Tags":{"Key":"Project","Values":["LaunchCrew"],"MatchOptions":["EQUALS","CONTAINS"]}}' ;;
    orexpr) FILTER='{"Or":[{"Tags":{"Key":"Project","Values":["LaunchCrew"],"MatchOptions":["EQUALS"]}},{"Tags":{"Key":"Project","Values":["Prod"],"MatchOptions":["EQUALS"]}}]}' ;;
    legacy) printf '{"Budget":{"BudgetName":"launchcrew-demo","CostFilters":{"TagKeyValue":["user:Project$LaunchCrew"]},"FilterExpression":%s}}\\n' "$FILTER"; exit 0 ;;
    *) echo "fake-aws: unknown FAKE_BUDGET: $BUDGET_MODE" >&2; exit 2 ;;
  esac
  printf '{"Budget":{"BudgetName":"launchcrew-demo","BudgetType":"COST","TimeUnit":"MONTHLY","FilterExpression":%s}}\\n' "$FILTER"
  exit 0
fi
if [ "$1" = "ce" ] && [ "$2" = "list-cost-allocation-tags" ]; then
  CE_MODE="${FAKE_CE:-active}"
  if [ "$CE_MODE" = "auth" ]; then
    echo "An error occurred (AccessDenied) when calling the ListCostAllocationTags operation: not authorized" >&2
    exit 254
  fi
  if [ "$CE_MODE" = "error" ]; then
    echo "An error occurred (ThrottlingException) when calling the ListCostAllocationTags operation: Rate exceeded" >&2
    exit 254
  fi
  if [ "$CE_MODE" = "malformed" ]; then printf 'not-json{{{\\n'; exit 0; fi
  case "$CE_MODE" in
    active) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Active"}]}\\n'; exit 0 ;;
    inactive) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Inactive"},{"TagKey":"Status","Type":"AWSGenerated","Status":"Active"}]}\\n'; exit 0 ;;
    absent) printf '{"CostAllocationTags":[{"TagKey":"Status","Type":"AWSGenerated","Status":"Active"}]}\\n'; exit 0 ;;
    duplicate) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Active"},{"TagKey":"Project","Type":"UserDefined","Status":"Inactive"}]}\\n'; exit 0 ;;
    wrongtype) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"AWSGenerated","Status":"Active"}]}\\n'; exit 0 ;;
    mixed) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Active"},{"TagKey":"Project","Type":"AWSGenerated","Status":"Active"}]}\\n'; exit 0 ;;
    nonobject) printf '[{"TagKey":"Project","Type":"UserDefined","Status":"Active"}]\\n'; exit 0 ;;
    unknown) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Pending"}]}\\n'; exit 0 ;;
    *) echo "fake-aws: unknown FAKE_CE: $CE_MODE" >&2; exit 2 ;;
  esac
fi
if [ "$1" = "elbv2" ] && [ "$2" = "describe-target-health" ]; then
  TG_MODE="${FAKE_TG_HEALTH:-drained}"
  TG_ARN_ARG=""
  TG_PREV=""
  for TG_ARG in "$@"; do
    if [ "$TG_PREV" = "--target-group-arn" ]; then TG_ARN_ARG="$TG_ARG"; fi
    TG_PREV="$TG_ARG"
  done
  case "$TG_ARN_ARG" in
    arn:aws:elasticloadbalancing:us-east-1:111122223333:targetgroup/*) ;;
    *) echo "fake-aws: unexpected target group arn: $TG_ARN_ARG" >&2; exit 2 ;;
  esac
  if [ "$TG_MODE" = "malformed" ]; then printf 'not-json{{{\\n'; exit 0; fi
  if [ "$TG_MODE" = "in_flight" ]; then printf '{"TargetHealthDescriptions":[{"Target":{"Id":"10.42.1.10","Port":8443},"HealthCheckPort":"8443","TargetHealth":{"State":"healthy"}}]}\\n'; exit 0; fi
  if [ "$TG_MODE" = "draining" ]; then printf '{"TargetHealthDescriptions":[{"Target":{"Id":"10.42.1.10","Port":8443},"HealthCheckPort":"8443","TargetHealth":{"State":"draining","Reason":"Target.DeregistrationInProgress"}}]}\\n'; exit 0; fi
  if [ "$TG_MODE" = "unknown" ]; then printf '{"TargetHealthDescriptions":[{"Target":{"Id":"10.42.1.10","Port":8443},"HealthCheckPort":"8443","TargetHealth":{"State":"weird"}}]}\\n'; exit 0; fi
  if [ "$TG_MODE" = "unused" ]; then printf '{"TargetHealthDescriptions":[{"Target":{"Id":"10.42.1.10","Port":8443},"HealthCheckPort":"8443","TargetHealth":{"State":"unused","Reason":"Target.NotRegistered"}}]}\\n'; exit 0; fi
  printf '{"TargetHealthDescriptions":[]}\\n'
  exit 0
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
        "--tls-secret-arn": "TlsSecretArn",
    }
    IMAGE_ENV = {
        "--api-image": "FAKE_API_IMAGE",
        "--web-image": "FAKE_WEB_IMAGE",
        "--web-proxy-image": "FAKE_WEB_PROXY_IMAGE",
        "--migration-image": "FAKE_MIGRATION_IMAGE",
        "--bootstrap-image": "FAKE_BOOTSTRAP_IMAGE",
    }
    SECRET_ENV = {
        "--runtime-secret-arn": "FAKE_RT_ARN",
        "--migration-secret-arn": "FAKE_MG_ARN",
        "--master-secret-arn": "FAKE_MASTER_ARN",
        "--tls-secret-arn": "FAKE_TLS_ARN",
    }

    def run_bootstrap(self, args, mode="success", extra_env=None,
                      params_overrides=None, params_raw=None,
                      foundation_params_raw=None, shared_dir=None):
        import json as _json
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            log = Path(tmp) / "calls.log"
            log.write_text("", encoding="utf-8")
            if shared_dir is None:
                count = Path(tmp) / "count"
                count.write_text("0", encoding="utf-8")
                taskdefs = Path(tmp) / "taskdefs"
                taskdefs.write_text("", encoding="utf-8")
                token_file = Path(tmp) / "token"
                token_file.write_text("", encoding="utf-8")
                created = Path(tmp) / "created"
                journals = Path(tmp) / "journals"
                journals.mkdir(mode=0o700)
                journals.chmod(0o700)
            else:
                shared = Path(shared_dir)
                shared.mkdir(parents=True, exist_ok=True)
                count = shared / "count"
                if not count.exists():
                    count.write_text("0", encoding="utf-8")
                taskdefs = shared / "taskdefs"
                if not taskdefs.exists():
                    taskdefs.write_text("", encoding="utf-8")
                token_file = shared / "token"
                if not token_file.exists():
                    token_file.write_text("", encoding="utf-8")
                created = shared / "created"
                journals = shared / "journals"
                if not journals.exists():
                    journals.mkdir(mode=0o700)
                journals.chmod(0o700)
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
            if "AcmCertificateArn" not in given:
                given["AcmCertificateArn"] = CERT_ARN
            if params_overrides:
                given.update(params_overrides)
            params = Path(tmp) / "params.json"
            if params_raw is None:
                params.write_text(_json.dumps(
                    [{"ParameterKey": key, "ParameterValue": value}
                     for key, value in sorted(given.items())]), encoding="utf-8")
            else:
                params.write_text(params_raw, encoding="utf-8")
            foundation_params = Path(tmp) / "foundation-params.json"
            if foundation_params_raw is None:
                foundation_params.write_text(_json.dumps(
                    [{"ParameterKey": "BudgetLimitUsd", "ParameterValue": "45"},
                     {"ParameterKey": "BudgetNotifyEmail",
                      "ParameterValue": NOTIFY_EMAIL}]), encoding="utf-8")
            else:
                foundation_params.write_text(foundation_params_raw,
                                             encoding="utf-8")
            env = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                env.pop(key, None)
            env["AWS_BIN"] = str(fake)
            env["FAKE_AWS_LOG"] = str(log)
            env["FAKE_MODE"] = mode
            env["FAKE_COUNT_FILE"] = str(count)
            env["FAKE_TASKDEF_FILE"] = str(taskdefs)
            env["FAKE_TOKEN_FILE"] = str(token_file)
            env["FAKE_STACK_CREATED_FILE"] = str(created)
            env["FAKE_PARAMS_FILE"] = str(params)
            env["FAKE_CERT_ARN"] = CERT_ARN
            env["FAKE_DB_HOST"] = DB_HOST
            env["FAKE_TOPIC_ARN"] = TOPIC_ARN
            env["FAKE_NOTIFY_EMAIL"] = NOTIFY_EMAIL
            for table in (self.IMAGE_ENV, self.SECRET_ENV):
                for flag, name in table.items():
                    for pos, item in enumerate(items):
                        if item == flag and pos + 1 < len(items):
                            env[name] = items[pos + 1]
            if extra_env:
                env.update(extra_env)
            full = list(args)
            if "--parameters-file" not in full:
                full += ["--parameters-file", str(params)]
            if "--foundation-stack-name" not in full and "--confirm" in full:
                full += ["--foundation-stack-name", FOUNDATION_STACK,
                         "--foundation-parameters-file", str(foundation_params),
                         "--prereqs-stack-name", PREREQS_STACK,
                         "--launch-journal-dir", str(journals)]
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
            "--tls-secret-arn": SECRET_TLS,
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

    def run_enable_with_priors(self, shared_tmp, enable_extra_env=None,
                               release="head006-testabc"):
        base = self.base_args()
        material_args = [*base, "--phase", "material",
                         "--release-generation", release]
        result_mat, _ = self.run_bootstrap(
            material_args, shared_dir=shared_tmp)
        self.assertEqual(result_mat.returncode, 0,
                         msg=result_mat.stdout + result_mat.stderr)
        migrate_args = [*base, "--phase", "migrate",
                        "--release-generation", release]
        result_mig, _ = self.run_bootstrap(
            migrate_args, shared_dir=shared_tmp)
        self.assertEqual(result_mig.returncode, 0,
                         msg=result_mig.stdout + result_mig.stderr)
        enable_args = [*base, "--phase", "enable",
                       "--release-generation", release]
        return self.run_bootstrap(
            enable_args, extra_env=enable_extra_env,
            shared_dir=shared_tmp)


class DryRunTests(BootstrapHarness):
    def test_dry_run_makes_zero_calls(self):
        result, calls = self.run_bootstrap([])
        self.assertEqual(result.returncode, 0)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("no AWS call", result.stdout)
        self.assertEqual(calls, [])

    def test_dry_run_lists_ordered_phases(self):
        result, _ = self.run_bootstrap([])
        for phase in ("infra", "images", "init", "material", "dbroles",
                      "migrate", "enable"):
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
        joined = " ".join(calls)
        self.assertNotIn("get-secret-value", joined)
        self.assertNotIn("GetSecretValue", joined)
        self.assertNotIn("get_secret_value", joined)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

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
            [*self.minimal_infra_args(), "--phase", "infra"], mode="stack_missing",
            extra_env={"FAKE_RT_ARN": SECRET_RT, "FAKE_MG_ARN": SECRET_MG,
                       "FAKE_MASTER_ARN": SECRET_MASTER, "FAKE_TLS_ARN": SECRET_TLS},
            params_overrides={"RuntimeDbUrlSecretArn": SECRET_RT,
                              "MigrationDbUrlSecretArn": SECRET_MG,
                              "MasterDbPasswordSecretArn": SECRET_MASTER,
                              "TlsSecretArn": SECRET_TLS})
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
        infra_exec = next(i for i, call in enumerate(calls)
                          if "execute-change-set" in call and "infra-006" in call)
        first_run = next(i for i, call in enumerate(calls) if "run-task" in call)
        deploy_true = next(i for i, call in enumerate(calls)
                           if "deploy " in call and "EnableServices=true" in call)
        self.assertLess(infra_exec, first_run)
        self.assertLess(first_run, deploy_true)
        self.assertFalse(any("deploy " in call and "EnableServices=false" in call
                             for call in calls))
        run_tasks = [call for call in calls if "run-task" in call]
        self.assertEqual(len(run_tasks), 5)
        taskdef_order = []
        for call in run_tasks:
            for logical in ("sdkinit", "sdkmaterial", "bootstrap",
                            "migration", "verify"):
                if f"launchcrew-demo-{logical}" in call:
                    taskdef_order.append(logical)
        self.assertEqual(taskdef_order,
                         ["sdkinit", "sdkmaterial", "bootstrap",
                          "migration", "verify"])

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
        combined = result.stdout + result.stderr
        self.assertIn("ambiguous", combined)
        self.assertIn("empty remains AMBIGUOUS", combined)
        self.assertNotIn("confirms zero tasks", combined)
        self.assertNotIn("nothing started with token", combined)
        self.assertIn("No automatic resend", combined)
        self.assertIn("no new token from absence", combined)
        self.assertTrue(any("list-tasks" in call for call in calls))
        self.assertTrue(any("--no-paginate" in call and "list-tasks" in call for call in calls))
        self.assertTrue(any("--cli-input-json" in call and "list-tasks" in call for call in calls))
        self.assertFalse(any("--next-token" in call for call in calls))
        self.assertFalse(any("--starting-token" in call for call in calls))
        self.assertFalse(any("--started-by" in call for call in calls if "list-tasks" in call))
        self.assertFalse(any("--desired-status" in call for call in calls if "list-tasks" in call))
        decoded = [call for call in calls if "INPUT_JSON_LIST" in call]
        self.assertTrue(any("desiredStatus" in call and "STOPPED" in call for call in decoded))
        self.assertTrue(any("startedBy" in call for call in decoded))
        self.assertFalse(any("startedBy" in call and "desiredStatus" in call for call in decoded))
        runs = [call for call in calls if "run-task" in call]
        self.assertEqual(len(runs), 1)
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_enable_alone_refuses_without_priors_and_launches_nothing(self):
        result, calls = self.run_bootstrap([*self.base_args(), "--phase", "enable"])
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("needs prior", combined)
        self.assertIn("No new launch", combined)
        self.assertNotIn("BOOTSTRAP COMPLETE", result.stdout)
        self.assertFalse(any("run-task" in call for call in calls))
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_enable_with_priors_succeeds_with_no_new_tasks(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            result, calls = self.run_enable_with_priors(shared_tmp)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP COMPLETE", result.stdout)
        self.assertIn("Enable precheck", result.stdout)
        self.assertIn("no new run-task", result.stdout + result.stderr)
        self.assertFalse(any("run-task" in call for call in calls))
        self.assertTrue(any("EnableServices=true" in call for call in calls))
        self.assertIn("BOOTSTRAP COMPLETE phases requested: enable", result.stdout)

    def test_infra_alone_needs_no_images_or_secrets(self):
        result, calls = self.run_bootstrap(
            [*self.minimal_infra_args(), "--phase", "infra"],
            extra_env={"FAKE_RT_ARN": SECRET_RT, "FAKE_MG_ARN": SECRET_MG,
                       "FAKE_MASTER_ARN": SECRET_MASTER, "FAKE_TLS_ARN": SECRET_TLS},
            params_overrides={"RuntimeDbUrlSecretArn": SECRET_RT,
                              "MigrationDbUrlSecretArn": SECRET_MG,
                              "MasterDbPasswordSecretArn": SECRET_MASTER,
                              "TlsSecretArn": SECRET_TLS})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Prereqs ready", result.stdout + result.stderr)
        self.assertTrue(any("execute-change-set" in call and "changeSet/infra-006/" in call
                            for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_single_phase_does_not_enable(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "migrate"])
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_enable_refuses_when_prior_verify_unresolved(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            base = self.base_args()
            release = "head006-testabc"
            result_mat, _ = self.run_bootstrap(
                [*base, "--phase", "material",
                 "--release-generation", release],
                shared_dir=shared_tmp)
            self.assertEqual(result_mat.returncode, 0,
                             msg=result_mat.stdout + result_mat.stderr)
            result_mig, _ = self.run_bootstrap(
                [*base, "--phase", "migrate",
                 "--release-generation", release],
                mode="verify_fail", shared_dir=shared_tmp)
            self.assertNotEqual(result_mig.returncode, 0)
            result, calls = self.run_bootstrap(
                [*base, "--phase", "enable",
                 "--release-generation", release],
                shared_dir=shared_tmp)
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("not complete", combined)
        self.assertIn("No new launch", combined)
        self.assertNotIn("BOOTSTRAP COMPLETE", result.stdout)
        self.assertFalse(any("run-task" in call for call in calls))
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_enable_refuses_on_image_drift(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "enable"], mode="taskdef_image_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("task definition references", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))

    def test_enable_refuses_on_missing_image(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "enable"], mode="image_missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_enable_refuses_on_binding_drift(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "enable"], mode="taskdef_secret_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("binding proof", result.stdout + result.stderr)
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_enable_refuses_when_own_deploy_moves_images(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            result, calls = self.run_enable_with_priors(
                shared_tmp, enable_extra_env={"FAKE_MODE": "taskdef_flip"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("changed during enable", combined)
        self.assertTrue(any("EnableServices=true" in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))
        self.assertNotIn("BOOTSTRAP COMPLETE", result.stdout)

    def test_stack_other_validation_error_is_not_absence(self):
        result, calls = self.run_bootstrap(
            [*self.minimal_infra_args(), "--phase", "infra"], mode="stack_other_error")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no change made", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))

    def test_latest_tag_refused(self):
        result, calls = self.run_bootstrap(
            self.base_args(**{"--api-image": image("launchcrew-api", tag="latest")}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("latest", result.stdout + result.stderr)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_params_duplicate_refused(self):
        import json as _json
        entries = self.params_entries()
        entries.append({"ParameterKey": "ApiImageUri",
                        "ParameterValue": entries[0]["ParameterValue"]})
        result, calls = self.run_bootstrap(
            self.base_args(), params_raw=_json.dumps(entries))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_params_use_previous_value_refused(self):
        import json as _json
        entries = [entry for entry in self.params_entries()
                   if entry["ParameterKey"] != "ApiImageUri"]
        entries.append({"ParameterKey": "ApiImageUri", "UsePreviousValue": True})
        result, calls = self.run_bootstrap(
            self.base_args(), params_raw=_json.dumps(entries))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no explicit ParameterValue", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_params_missing_value_refused_when_cli_given(self):
        import json as _json
        entries = [entry for entry in self.params_entries()
                   if entry["ParameterKey"] != "BootstrapImageUri"]
        result, calls = self.run_bootstrap(
            self.base_args(), params_raw=_json.dumps(entries))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has no BootstrapImageUri", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_params_unknown_secret_refused(self):
        import json as _json
        entries = self.params_entries()
        entries.append({"ParameterKey": "EvilSecretArn", "ParameterValue": "x"})
        result, calls = self.run_bootstrap(
            self.base_args(), params_raw=_json.dumps(entries))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrecognized secret reference", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def params_entries(self):
        flat = self.base_args()
        items = {}
        index = 1
        while index < len(flat):
            key = flat[index]
            if key in self.PARAM_KEYS and index + 1 < len(flat):
                items[self.PARAM_KEYS[key]] = flat[index + 1]
                index += 2
            else:
                index += 1
        return [{"ParameterKey": key, "ParameterValue": value}
                for key, value in sorted(items.items())]


class EnableServiceProofTests(BootstrapHarness):
    API_PHYSICAL = "launchcrew-demo-ApiService-A1B2C3D4E5F6"
    WEB_PHYSICAL = "launchcrew-demo-WebService-G7H8I9J0K1L2"

    def test_enable_uses_owned_physical_service_ids(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            result, calls = self.run_enable_with_priors(shared_tmp)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP COMPLETE", result.stdout)
        self.assertIn("desiredCount 1", result.stdout)
        self.assertIn("pendingCount 0", result.stdout)
        self.assertIn("ACTIVE", result.stdout)
        self.assertTrue(any("describe-stack-resource" in call and "ApiService" in call
                           for call in calls))
        self.assertTrue(any("describe-stack-resource" in call and "WebService" in call
                           for call in calls))
        svc_calls = [call for call in calls if "describe-services" in call]
        self.assertEqual(len(svc_calls), 2)
        for call in svc_calls:
            self.assertIn("--cluster launchcrew-demo", call)
            self.assertIn("--output json", call)
            self.assertNotIn("--query services[0]", call)
        joined = " ".join(svc_calls)
        self.assertIn(self.API_PHYSICAL, joined)
        self.assertIn(self.WEB_PHYSICAL, joined)
        self.assertNotIn("launchcrew-demo-api", joined)
        self.assertNotIn("launchcrew-demo-web", joined)

    def test_enable_refuses_service_proof_failures(self):
        cases = {
            "empty": "EMPTY",
            "failures": "FAILURES",
            "inactive": "NOT_ACTIVE",
            "desired": "DESIRED_",
            "running": "RUNNING_",
            "pending": "PENDING_",
            "wrong": "WRONG_SERVICE",
            "duplicate": "DUPLICATE",
            "malformed": "MALFORMED",
            "wrong_cluster": "WRONG_CLUSTER",
        }
        with tempfile.TemporaryDirectory() as shared_tmp:
            base = self.base_args()
            release = "head006-testabc"
            result_mat, _ = self.run_bootstrap(
                [*base, "--phase", "material",
                 "--release-generation", release],
                shared_dir=shared_tmp)
            self.assertEqual(result_mat.returncode, 0,
                             msg=result_mat.stdout + result_mat.stderr)
            result_mig, _ = self.run_bootstrap(
                [*base, "--phase", "migrate",
                 "--release-generation", release],
                shared_dir=shared_tmp)
            self.assertEqual(result_mig.returncode, 0,
                             msg=result_mig.stdout + result_mig.stderr)
            for mode, token in cases.items():
                with self.subTest(mode=mode):
                    result, calls = self.run_bootstrap(
                        [*base, "--phase", "enable",
                         "--release-generation", release],
                        extra_env={"FAKE_SERVICE": mode},
                        shared_dir=shared_tmp)
                    self.assertNotEqual(result.returncode, 0, msg=mode)
                    combined = result.stdout + result.stderr
                    self.assertIn("refused", combined, msg=mode)
                    self.assertIn(token, combined, msg=mode)
                    self.assertNotIn("BOOTSTRAP COMPLETE", result.stdout, msg=mode)
                    self.assertTrue(any("describe-services" in call for call in calls),
                                    msg=mode)

    def test_enable_refuses_missing_service_identity(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            result, _ = self.run_enable_with_priors(
                shared_tmp, enable_extra_env={"FAKE_API_SERVICE": "None"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("owned identifier missing", combined)
        self.assertNotIn("BOOTSTRAP COMPLETE", result.stdout)

    def test_describe_services_fixture_shapes(self):
        import json as _json
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            env = dict(os.environ)
            env["FAKE_MODE"] = "success"
            env["FAKE_SERVICE"] = "ok"
            proc = subprocess.run(
                [str(fake), "ecs", "describe-services",
                 "--cluster", "launchcrew-demo",
                 "--services", "launchcrew-demo-api",
                 "--region", REGION, "--output", "json"],
                capture_output=True, text=True, env=env, check=False)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            doc = _json.loads(proc.stdout)
            self.assertEqual(doc["services"], [])
            self.assertTrue(doc["failures"])
            self.assertEqual(doc["failures"][0]["reason"], "MISSING")
            for physical in (self.API_PHYSICAL, self.WEB_PHYSICAL):
                proc = subprocess.run(
                    [str(fake), "ecs", "describe-services",
                     "--cluster", "launchcrew-demo",
                     "--services", physical,
                     "--region", REGION, "--output", "json"],
                    capture_output=True, text=True, env=env, check=False)
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                doc = _json.loads(proc.stdout)
                self.assertEqual(doc["failures"], [])
                self.assertEqual(len(doc["services"]), 1)
                svc = doc["services"][0]
                self.assertEqual(svc["serviceName"], physical)
                self.assertEqual(
                    svc["serviceArn"],
                    f"arn:aws:ecs:{REGION}:{ACCOUNT}:service/launchcrew-demo/{physical}")
                self.assertEqual(
                    svc["clusterArn"],
                    f"arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/launchcrew-demo")
                self.assertEqual(svc["status"], "ACTIVE")
                self.assertEqual(svc["desiredCount"], 1)
                self.assertEqual(svc["runningCount"], 1)
                self.assertEqual(svc["pendingCount"], 0)


class CostTagAdmissionTests(BootstrapHarness):
    REFUSAL_TOKENS = {
        "inactive": "Inactive",
        "absent": "no Project",
        "error": "UNVERIFIED",
        "auth": "ce:ListCostAllocationTags",
        "duplicate": "duplicate",
        "mixed": "duplicate",
        "wrongtype": "not UserDefined",
        "malformed": "not Active",
        "nonobject": "not Active",
        "unknown": "not Active",
    }

    def test_active_ce_passes_infra_with_scoped_query(self):
        result, calls = self.run_bootstrap(
            [*self.minimal_infra_args(), "--phase", "infra"],
            extra_env={"FAKE_RT_ARN": SECRET_RT, "FAKE_MG_ARN": SECRET_MG,
                       "FAKE_MASTER_ARN": SECRET_MASTER, "FAKE_TLS_ARN": SECRET_TLS},
            params_overrides={"RuntimeDbUrlSecretArn": SECRET_RT,
                              "MigrationDbUrlSecretArn": SECRET_MG,
                              "MasterDbPasswordSecretArn": SECRET_MASTER,
                              "TlsSecretArn": SECRET_TLS})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        ce_calls = [call for call in calls if "list-cost-allocation-tags" in call]
        self.assertEqual(len(ce_calls), 1)
        self.assertIn("--tag-keys Project", ce_calls[0])
        self.assertIn("--type UserDefined", ce_calls[0])
        self.assertIn(REGION, ce_calls[0])
        self.assertIn("status Active", result.stdout)
        self.assertTrue(any("execute-change-set" in call for call in calls))

    def test_inactive_ce_refuses_full_run_before_any_paid_call(self):
        result, calls = self.run_bootstrap(
            self.base_args(), extra_env={"FAKE_CE": "inactive"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Inactive", result.stdout + result.stderr)
        self.assertTrue(any("list-cost-allocation-tags" in call for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))
        self.assertNotIn("BOOTSTRAP COMPLETE", result.stdout)

    def test_bad_ce_modes_all_refuse_infra_without_deploy(self):
        for ce_mode, token in self.REFUSAL_TOKENS.items():
            with self.subTest(ce_mode=ce_mode):
                result, calls = self.run_bootstrap(
                    [*self.minimal_infra_args(), "--phase", "infra"],
                    extra_env={"FAKE_CE": ce_mode})
                self.assertNotEqual(result.returncode, 0, msg=ce_mode)
                self.assertIn(token, result.stdout + result.stderr, msg=ce_mode)
                self.assertTrue(
                    any("list-cost-allocation-tags" in call for call in calls),
                    msg=ce_mode)
                self.assertFalse(
                    any("deploy " in call for call in calls), msg=ce_mode)
                self.assertFalse(
                    any("run-task" in call for call in calls), msg=ce_mode)

    def test_inactive_ce_refuses_each_paid_phase(self):
        paid = [
            [*self.minimal_infra_args(), "--phase", "infra"],
            [*self.base_args(), "--phase", "init"],
            [*self.base_args(), "--phase", "material"],
            [*self.base_args(), "--phase", "dbroles"],
            [*self.base_args(), "--phase", "migrate"],
            [*self.base_args(), "--phase", "enable"],
        ]
        for argv in paid:
            with self.subTest(phase=argv[-1]):
                result, calls = self.run_bootstrap(
                    argv, extra_env={"FAKE_CE": "inactive"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Inactive", result.stdout + result.stderr)
                self.assertFalse(any("deploy " in call for call in calls))
                self.assertFalse(any("run-task" in call for call in calls))

    def test_inactive_ce_blocks_budget_readback_on_enable(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "enable"],
            extra_env={"FAKE_CE": "inactive"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("describe-budget" in call for call in calls))
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_ce_never_activates_and_reads_no_values(self):
        code = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("ce list-cost-allocation-tags", code)
        self.assertNotIn("update-cost-allocation-tags", code.lower())
        self.assertNotIn("UpdateCostAllocationTags", code)

    def test_readonly_calls_carry_no_secret_values(self):
        result, calls = self.run_bootstrap(self.base_args())
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        for call in calls:
            if "list-cost-allocation-tags" in call or "describe-budget" in call:
                self.assertNotIn(":secret:", call)
                self.assertNotIn("get-secret-value", call.lower())


class BudgetFilterTests(BootstrapHarness):
    REFUSAL_MODES = ("unfiltered", "wrongtag", "multi", "broad",
                     "orexpr", "legacy", "malformed", "error", "auth")

    def test_exact_filter_passes_enable_readback(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            result, calls = self.run_enable_with_priors(shared_tmp)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertTrue(any("describe-budget" in call for call in calls))
        self.assertIn("EQUALS only", result.stdout)
        self.assertTrue(any("EnableServices=true" in call for call in calls))

    def test_inexact_filters_all_refuse_enable(self):
        for budget_mode in self.REFUSAL_MODES:
            with self.subTest(budget_mode=budget_mode):
                result, calls = self.run_bootstrap(
                    [*self.base_args(), "--phase", "enable"],
                    extra_env={"FAKE_BUDGET": budget_mode})
                self.assertNotEqual(result.returncode, 0, msg=budget_mode)
                combined = result.stdout + result.stderr
                self.assertIn("UNVERIFIED", combined, msg=budget_mode)
                self.assertTrue(
                    any("describe-budget" in call for call in calls),
                    msg=budget_mode)
                self.assertFalse(
                    any("EnableServices=true" in call for call in calls),
                    msg=budget_mode)
                self.assertFalse(
                    any("run-task" in call for call in calls), msg=budget_mode)

    def test_budget_auth_reports_permission_not_absence(self):
        result, _ = self.run_bootstrap(
            [*self.base_args(), "--phase", "enable"],
            extra_env={"FAKE_BUDGET": "auth"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("budgets:DescribeBudget", result.stdout + result.stderr)

    def test_budget_refusal_carries_no_secret_or_account_detail(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "enable"],
            extra_env={"FAKE_BUDGET": "multi"})
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UNVERIFIED", combined)
        self.assertIn("lacks the exact", result.stderr)
        refusal_lines = [line for line in result.stderr.splitlines()
                         if "Budget" in line or "UNVERIFIED" in line]
        self.assertTrue(refusal_lines)
        refusal_text = "\n".join(refusal_lines)
        self.assertNotIn("get-secret-value", refusal_text.lower())
        self.assertNotIn("GetSecretValue", refusal_text)
        self.assertNotIn("get_secret_value", refusal_text)
        self.assertNotIn("get-secret-value", combined.lower())
        self.assertNotIn("GetSecretValue", combined)
        self.assertNotIn("get_secret_value", combined)
        self.assertFalse(any("get-secret-value" in call.lower()
                             for call in calls))
        self.assertIn("Ownership check", combined)
        self.assertIn("Verified secret metadata ownership", combined)


class FixtureJsonTests(BootstrapHarness):
    def test_describe_tasks_fixture_emits_valid_json(self):
        import json as _json
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            taskdefs = Path(tmp) / "taskdefs"
            taskdefs.write_text(
                "arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task001"
                "|arn:aws:ecs:us-east-1:111122223333:tas" "k-definition/launchcrew-demo-bootstrap:1\n",
                encoding="utf-8")
            env = dict(os.environ)
            env["FAKE_TASKDEF_FILE"] = str(taskdefs)
            env["FAKE_MODE"] = "success"
            proc = subprocess.run(
                [str(fake), "ecs", "describe-tasks"],
                capture_output=True, text=True, env=env, check=False)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            doc = _json.loads(proc.stdout)
            tasks = doc.get("tasks", [])
            self.assertEqual(len(tasks), 1)
            containers = tasks[0].get("containers", [])
            self.assertTrue(containers)
            for container in containers:
                self.assertIn("name", container)
                self.assertEqual(container.get("lastStatus"), "STOPPED")
                self.assertEqual(container.get("exitCode"), 0)
            names = sorted(container["name"] for container in containers)
            self.assertIn("bootstrap-db-roles", names)


def _fargate_resource_names(text):
    start = text.index("\nResources:\n")
    try:
        end = text.index("\nOutputs:\n", start)
        scope = text[start:end]
    except ValueError:
        scope = text[start:]
    names = []
    for line in scope.splitlines():
        match = re.match(r"^  ([A-Za-z0-9]+):\s*$", line)
        if match:
            names.append(match.group(1))
    return names


def _fargate_resource_block(text, name):
    start = text.index(f"\n  {name}:")
    rest = text[start + 1:]
    lines = rest.splitlines()
    block = [lines[0]]
    for line in lines[1:]:
        if re.match(r"^  [A-Za-z0-9]", line):
            break
        if re.match(r"^[A-Za-z]", line):
            break
        block.append(line)
    return "\n".join(block)


def _fargate_depends_on(block):
    deps = []
    lines = block.splitlines()
    for idx, line in enumerate(lines):
        match = re.match(r"^\s*DependsOn:\s*(.*?)\s*$", line)
        if not match:
            continue
        value = match.group(1).strip()
        if value:
            if value.startswith("["):
                inner = value[1:value.index("]")] if "]" in value else value[1:]
                for part in inner.split(","):
                    part = part.strip()
                    if part:
                        deps.append(part)
            else:
                deps.append(value)
        else:
            for following in lines[idx + 1:]:
                item = re.match(r"^\s*-\s*([A-Za-z0-9]+)\s*$", following)
                if item:
                    deps.append(item.group(1))
                    continue
                if re.match(r"^\s*$", following):
                    continue
                break
    return deps


def _fargate_ref_targets(block):
    targets = set(re.findall(r"!Ref\s+([A-Za-z0-9:]+)", block))
    for target in re.findall(r"!GetAtt\s+([A-Za-z0-9:\.\[\]]+)", block):
        targets.add(target.split(".")[0].strip("[] "))
    for target in re.findall(r"\$\{([A-Za-z0-9]+)", block):
        targets.add(target)
    return targets


def _fargate_dependency_graph(text):
    names = set(_fargate_resource_names(text))
    graph = {}
    for name in names:
        block = _fargate_resource_block(text, name)
        deps = {dep for dep in _fargate_depends_on(block) if dep in names}
        for target in _fargate_ref_targets(block):
            if target in names:
                deps.add(target)
        graph[name] = deps
    return graph


def _fargate_reachable(graph, start, goal):
    seen = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        for nxt in graph.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def _fargate_cycle_path(graph):
    visiting = set()
    done = set()
    trail = []

    def visit(node):
        if node in done:
            return None
        if node in visiting:
            return trail[trail.index(node):] + [node]
        visiting.add(node)
        trail.append(node)
        for nxt in sorted(graph.get(node, ())):
            hit = visit(nxt)
            if hit:
                return hit
        trail.pop()
        visiting.remove(node)
        done.add(node)
        return None

    for node in sorted(graph):
        hit = visit(node)
        if hit:
            return hit
    return None


class TemplateStagingTests(unittest.TestCase):
    def setUp(self):
        self.text = TEMPLATE.read_text(encoding="utf-8")
        self.example = PARAMS.read_text(encoding="utf-8")
        self.foundation = FOUNDATION.read_text(encoding="utf-8")
        root = TEMPLATE.parents[2]
        self.bootstrap_sh = (root / "deploy" / "aws" / "bootstrap.sh").read_text(encoding="utf-8")
        self.controller = (root / "containers" / "bootstrap-db.Containerfile").read_text(encoding="utf-8")

    def test_services_default_to_zero_until_enabled(self):
        self.assertIn("Default: 'false'", self.text)
        self.assertIn("DesiredCount: !If [ServicesEnabled, 1, 0]", self.text)
        self.assertNotIn("DesiredCount: 1", self.text)

    def test_services_wait_for_listener_association(self):
        graph = _fargate_dependency_graph(self.text)
        self.assertIn("HttpsListener", graph.get("WebService", set()))
        self.assertIn("ApiListenerRule", graph.get("ApiService", set()))
        self.assertTrue(_fargate_reachable(graph, "ApiService", "HttpsListener"))
        self.assertTrue(_fargate_reachable(graph, "ApiService", "LoadBalancer"))
        self.assertTrue(_fargate_reachable(graph, "WebService", "LoadBalancer"))
        rule = _fargate_resource_block(self.text, "ApiListenerRule")
        self.assertIn("!Ref HttpsListener", rule)
        self.assertIn("!Ref ApiTargetGroup", rule)
        listener = _fargate_resource_block(self.text, "HttpsListener")
        self.assertIn("!Ref WebTargetGroup", listener)
        self.assertIn("!Ref LoadBalancer", listener)
        api = _fargate_resource_block(self.text, "ApiService")
        for ref in ("!Ref Cluster", "!Ref ApiTaskDefinition",
                    "!Ref ApiTargetGroup", "!Ref ApiSecurityGroup",
                    "!Ref PublicSubnetA", "!Ref PublicSubnetB"):
            self.assertIn(ref, api)
        web = _fargate_resource_block(self.text, "WebService")
        for ref in ("!Ref Cluster", "!Ref WebTaskDefinition",
                    "!Ref WebTargetGroup", "!Ref WebSecurityGroup",
                    "!Ref PublicSubnetA", "!Ref PublicSubnetB"):
            self.assertIn(ref, web)
        self.assertIn("DesiredCount: !If [ServicesEnabled, 1, 0]", api)
        self.assertIn("DesiredCount: !If [ServicesEnabled, 1, 0]", web)

    def test_service_listener_dependencies_add_no_cycle(self):
        graph = _fargate_dependency_graph(self.text)
        self.assertIsNone(_fargate_cycle_path(graph))
        self.assertFalse(_fargate_reachable(graph, "HttpsListener", "WebService"))
        self.assertFalse(_fargate_reachable(graph, "ApiListenerRule", "ApiService"))
        self.assertFalse(_fargate_reachable(graph, "HttpsListener", "ApiService"))

    def test_no_autoscaling_controller(self):
        self.assertNotIn("ApplicationAutoScaling", self.text)
        self.assertNotIn("ScalingPolicy", self.text)
        self.assertNotIn("ScalableTarget", self.text)

    def test_budget_alerts_configured_not_empty(self):
        self.assertNotIn("NotificationsWithSubscribers: []", self.foundation)
        self.assertIn("BudgetNotifyConfigured", self.foundation)
        self.assertIn("NotificationType: ACTUAL", self.foundation)
        self.assertIn("Threshold: 80", self.foundation)
        self.assertIn("NotificationType: FORECASTED", self.foundation)
        self.assertIn("Threshold: 100", self.foundation)
        self.assertNotIn("NotificationState", self.foundation)
        self.assertIn("BudgetTopic", self.foundation)
        self.assertIn("Protocol: email", self.foundation)

    def test_app_stack_owns_no_budget_or_topic(self):
        for token in ("DemoBudget", "BudgetTopic", "BudgetTopicPolicy",
                      "BudgetEmailSubscription", "BudgetLimitUsd",
                      "BudgetNotifyEmail", "BudgetNotifyConfigured"):
            self.assertNotIn(token, self.text)
        for resource in ("AWS::Budgets::Budget", "AWS::SNS::Topic",
                         "AWS::SNS::Subscription", "AWS::SNS::TopicPolicy"):
            self.assertNotIn(resource, self.text)
        self.assertIn("DemoBudget", self.foundation)
        self.assertIn("BudgetTopic", self.foundation)

    def test_execution_roles_are_split_and_least_scope(self):
        for role in ("ApiExecutionRole", "WebExecutionRole",
                     "MigrationExecutionRole", "BootstrapExecutionRole",
                     "VerifyExecutionRole", "SdkInitExecutionRole",
                     "SdkMaterialExecutionRole"):
            self.assertIn(role, self.text)
        exec_start = self.text.index("ApiExecutionRole:")
        exec_roles = self.text[exec_start:self.text.index("ApiTaskRole:")]
        self.assertEqual(exec_roles.count("secretsmanager:GetSecretValue"), 5)
        self.assertIn("api-execution-secrets-only", self.text)
        self.assertIn("verify-execution-secrets-only", self.text)
        self.assertIn("AmazonECSTaskExecutionRolePolicy", self.text)
        self.assertNotIn("secretsmanager:PutSecretValue", exec_roles)
        sdk_exec_start = self.text.index("SdkInitExecutionRole:")
        sdk_exec = self.text[sdk_exec_start:self.text.index("SdkInitTaskRole:")]
        self.assertNotIn("secretsmanager:GetSecretValue", sdk_exec)
        self.assertNotIn("secretsmanager:PutSecretValue", sdk_exec)
        self.assertNotIn("Resource: '*'", self.text)
        self.assertNotIn('Resource: "*"', self.text)

    def test_task_roles_carry_no_secret_fetch(self):
        for role in ("ApiTaskRole", "WebTaskRole", "MigrationTaskRole",
                     "BootstrapTaskRole", "VerifyTaskRole"):
            self.assertIn(role, self.text)
        classic_start = self.text.index("ApiTaskRole:")
        classic_roles = self.text[classic_start:self.text.index("SdkInitExecutionRole:")]
        self.assertNotIn("secretsmanager:GetSecretValue", classic_roles)
        self.assertNotIn("secretsmanager:PutSecretValue", classic_roles)

    def test_sdk_task_roles_are_scoped_no_wildcards(self):
        for role in ("SdkInitTaskRole", "SdkMaterialTaskRole"):
            self.assertIn(role, self.text)
        sdk_roles = self.text[self.text.index("SdkInitTaskRole:"):]
        sdk_roles = sdk_roles[:sdk_roles.index("ApiTaskDefinition:")]
        self.assertIn("secretsmanager:DescribeSecret", sdk_roles)
        self.assertIn("secretsmanager:GetSecretValue", sdk_roles)
        self.assertIn("secretsmanager:PutSecretValue", sdk_roles)
        self.assertIn("acm:DescribeCertificate", sdk_roles)
        self.assertIn("acm:ExportCertificate", sdk_roles)
        material = self.text[self.text.index("SdkMaterialTaskRole:"):]
        material = material[:material.index("ApiTaskDefinition:")]
        self.assertNotIn("secretsmanager:PutSecretValue", material)
        self.assertNotIn("acm:ExportCertificate", material)
        self.assertNotIn("MasterDbPasswordSecretArn", material)

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
        next_resource = verify_body.find("\n  SdkInitTaskDefinition:")
        verify_body = verify_body[:next_resource]
        self.assertIn("RUNTIME_DB_URL", verify_body)
        self.assertIn("'--verify'", verify_body)
        self.assertNotIn("MASTER_DB_PASSWORD", verify_body)
        self.assertNotIn("MIGRATION_DB_URL", verify_body)

    def test_sdk_tasks_use_explicit_entrypoint_and_command(self):
        for logical, container, flag in (
                ("SdkInitTaskDefinition", "sdk-init", "'--populate'"),
                ("SdkMaterialTaskDefinition", "sdk-material",
                 "'--verify-material'")):
            self.assertIn(logical, self.text)
            self.assertIn(container, self.text)
            self.assertIn(flag, self.text)
        self.assertIn(
            "EntryPoint: [/opt/venv/bin/python, /app/scripts/populate_prereqs.py]",
            self.text)
        sdk_start = self.text.index("SdkInitTaskDefinition:")
        sdk_body = self.text[sdk_start:self.text.index("\n  LoadBalancer:")]
        self.assertNotIn("Secrets:", sdk_body)
        self.assertIn("LAUNCHCREW_EXPECTED_ROLE, Value: !Ref SdkInitTaskRole",
                      sdk_body)
        self.assertIn("LAUNCHCREW_DB_HOST, Value: !GetAtt Database.Endpoint.Address",
                      sdk_body)

    def test_budget_topic_allows_only_budgets_publish(self):
        self.assertIn("BudgetTopicPolicy", self.foundation)
        self.assertIn("budgets.amazonaws.com", self.foundation)
        self.assertIn("aws:SourceAccount", self.foundation)
        self.assertIn("aws:SourceArn", self.foundation)

    def test_parameters_example_matches_template(self):
        import json as _json
        example_keys = {entry["ParameterKey"]
                        for entry in _json.loads(self.example)}
        self.assertEqual(example_keys,
                         {"AcmCertificateArn", "ApiImageUri", "WebImageUri",
                          "WebProxyImageUri", "MigrationImageUri",
                          "BootstrapImageUri", "RuntimeDbUrlSecretArn",
                          "MigrationDbUrlSecretArn", "TlsSecretArn",
                          "MasterDbPasswordSecretArn", "DatabaseUsername",
                          "EnableServices"})
        for key in ("BootstrapImageUri", "EnableServices"):
            self.assertIn(key, self.example)
        self.assertNotIn("BudgetLimitUsd", self.example)
        self.assertNotIn("BudgetNotifyEmail", self.example)
        self.assertIn('"false"', self.example)

    def test_bootstrap_image_pins_ca_bundle(self):
        self.assertIn("RDS_CA_SHA256=b1711d12bae51838581281e23b6cb97b1074016873b4dafc80ed14002462dd77", self.controller)
        self.assertIn("USER 10001:10001", self.controller)
        code_lines = [line for line in self.controller.splitlines()
                      if not line.strip().startswith("#")]
        self.assertNotIn("alembic", "\n".join(code_lines).lower())

    def test_job_egress_needs_no_inbound(self):
        db_inline = self.text[self.text.index("DbSecurityGroup:"):self.text.index("JobSecurityGroup:")]
        self.assertNotIn("JobSecurityGroup", db_inline)
        self.assertNotIn("SecurityGroupEgress", db_inline)
        self.assertIn("SourceSecurityGroupId: !Ref ApiSecurityGroup", db_inline)
        job_inline = self.text[self.text.index("JobSecurityGroup:"):self.text.index("DbJobIngress:")]
        self.assertNotIn("SecurityGroupIngress", job_inline)
        self.assertIn("SecurityGroupEgress", job_inline)
        self.assertNotIn("DbSecurityGroup", job_inline)
        self.assertIn("FromPort: 443", job_inline)
        standalone = self.text[self.text.index("DbJobIngress:"):self.text.index("ApiEcrRepo:")]
        self.assertIn("Type: AWS::EC2::SecurityGroupIngress", standalone)
        self.assertIn("Type: AWS::EC2::SecurityGroupEgress", standalone)
        self.assertIn("GroupId: !Ref DbSecurityGroup", standalone)
        self.assertIn("GroupId: !Ref JobSecurityGroup", standalone)
        self.assertIn("SourceSecurityGroupId: !Ref JobSecurityGroup", standalone)
        self.assertIn("DestinationSecurityGroupId: !Ref DbSecurityGroup", standalone)
        self.assertIn("FromPort: 5432", standalone)
        self.assertIn("ToPort: 5432", standalone)
        self.assertNotIn("CidrIp", standalone)
        self.assertNotIn("SourceSecurityGroupId: !Ref ApiSecurityGroup", standalone)

    def test_controller_never_fetches_secret_values(self):
        self.assertIn("describe-secret", self.bootstrap_sh)
        code_lines = [line for line in self.bootstrap_sh.splitlines()
                      if not line.strip().startswith("#")]
        code = "\n".join(code_lines)
        self.assertIn("describe-secret", code)
        self.assertNotIn("get-secret-value", code.lower())
        self.assertIn("value never fetched", self.bootstrap_sh)


class BudgetSubscriberProofTests(BootstrapHarness):
    def test_actual_subscriber_mismatch_refuses(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "enable"],
            extra_env={"FAKE_SUB": "mismatch_actual"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("ACTUAL_80", combined)
        self.assertIn("ACTUAL 80 plus FORECASTED 100", combined)
        self.assertIn("UNVERIFIED", combined)
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_subscriber_auth_unreadable_refuses(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_SUB": "auth"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("subscribers unreadable", combined)
        self.assertIn("DescribeSubscribersForNotification", combined)
        self.assertFalse(any("run-task" in call for call in calls))


class JournalPrivateDirTests(BootstrapHarness):
    def test_tmp_mode_unchanged_after_private_run(self):
        before = stat.S_IMODE(os.stat("/tmp").st_mode)
        result, calls = self.run_bootstrap([*self.base_args(), "--phase", "init"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        after = stat.S_IMODE(os.stat("/tmp").st_mode)
        self.assertEqual(before, after)
        self.assertFalse(any("--launch-journal-dir /tmp" in call for call in calls))

    def test_default_journal_is_persistent_private_not_tmp(self):
        code = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertNotIn('LAUNCH_JOURNAL_DIR:-/tmp', code)
        self.assertIn('.local/launch-journals', code)
        self.assertIn('BOOTSTRAP_SCRIPT_DIR', code)
        self.assertIn('shared root', code)
        self.assertIn('JOURNAL_CREATED', code)
        self.assertIn('st_uid', code)

    def test_shared_tmp_journal_refused_without_chmod(self):
        code = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('/tmp|/tmp/', code)
        self.assertIn('dedicated private directory', code)


class BudgetPaginationTests(BootstrapHarness):
    def test_notifications_paginate_two_pages_with_raw_json(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_NOTIF": "paginated_ok"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        notif_calls = [call for call in calls if "describe-notifications-for-budget" in call]
        self.assertEqual(len(notif_calls), 2)
        for call in notif_calls:
            self.assertIn("--no-paginate", call)
            self.assertIn("--cli-input-json", call)
            self.assertNotIn("--next-token", call)
            self.assertNotIn("--starting-token", call)
            self.assertNotIn("--account-id", call)
        decoded = [call for call in calls if "INPUT_JSON_NOTIF" in call]
        self.assertEqual(len(decoded), 2)
        self.assertIn("AccountId", decoded[0])
        self.assertIn("launchcrew-demo", decoded[0])
        self.assertIn("MaxResults", decoded[0])
        self.assertNotIn("NextToken", decoded[0])
        self.assertIn("page2", decoded[1])
        self.assertIn("MaxResults", decoded[1])
        sub_calls = [call for call in calls if "describe-subscribers-for-notification" in call]
        self.assertEqual(len(sub_calls), 2)
        for call in sub_calls:
            self.assertIn("--no-paginate", call)
            self.assertIn("--cli-input-json", call)
            self.assertNotIn("--next-token", call)
        sub_decoded = [call for call in calls if "INPUT_JSON_SUB" in call]
        self.assertEqual(len(sub_decoded), 2)
        for entry in sub_decoded:
            self.assertIn("PERCENTAGE", entry)
            self.assertIn("AccountId", entry)

    def test_controller_rejects_unsupported_next_token_surface(self):
        code = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertNotIn("--next-token", code)
        self.assertNotIn("--starting-token", code)
        self.assertIn("--no-paginate", code)
        self.assertIn("--cli-input-json", code)
        self.assertIn("describe-change-set --cli-input-json", code)
        self.assertIn('"NextToken"', code)
        self.assertIn('"nextToken"', code)
        self.assertIn('"MaxResults"', code)
        self.assertIn('"maxResults"', code)


class OptionalThresholdTypeTests(BootstrapHarness):
    def test_missing_threshold_type_allowed(self):
        # Omitted ThresholdType means implicit percentage and passes the
        # paid gates. Infra exercises the same notification check as enable
        # but needs no prior one-off journals, so fail-closed enable priors
        # stay out of this threshold compatibility proof.
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_NOTIF": "missing_type"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP COMPLETE", result.stdout)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_explicit_bad_threshold_types_refused(self):
        for mode in ("absolute", "absolute_short", "null_type", "unknown_type", "empty_type"):
            with self.subTest(mode=mode):
                result, calls = self.run_bootstrap(
                    [*self.base_args(), "--phase", "enable"],
                    extra_env={"FAKE_NOTIF": mode})
                self.assertNotEqual(result.returncode, 0, msg=mode)
                combined = result.stdout + result.stderr
                self.assertIn("UNVERIFIED", combined, msg=mode)
                self.assertFalse(any("EnableServices=true" in call for call in calls), msg=mode)
                self.assertFalse(any("run-task" in call for call in calls), msg=mode)


class CloudformationTagsTests(BootstrapHarness):
    def test_infra_update_on_owned_stack_passes_demo_tags(self):
        result, calls = self.run_bootstrap(
            [*self.minimal_infra_args(), "--phase", "infra"],
            extra_env={"FAKE_RT_ARN": SECRET_RT, "FAKE_MG_ARN": SECRET_MG,
                       "FAKE_MASTER_ARN": SECRET_MASTER, "FAKE_TLS_ARN": SECRET_TLS},
            params_overrides={"RuntimeDbUrlSecretArn": SECRET_RT,
                              "MigrationDbUrlSecretArn": SECRET_MG,
                              "MasterDbPasswordSecretArn": SECRET_MASTER,
                              "TlsSecretArn": SECRET_TLS})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        creates = [call for call in calls if "create-change-set" in call]
        self.assertTrue(creates)
        for call in creates:
            self.assertIn("--tags", call)
            self.assertIn("Project", call)
            self.assertIn("LaunchCrew", call)
            self.assertIn("Environment", call)
            self.assertIn("demo", call)
        self.assertTrue(any("execute-change-set" in call and "changeSet/infra-006/" in call
                            for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))

    def test_enable_update_passes_demo_tags(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            result, calls = self.run_enable_with_priors(shared_tmp)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        deploys = [call for call in calls if "deploy " in call]
        self.assertTrue(deploys)
        for call in deploys:
            self.assertIn("--tags", call)
            self.assertIn("Project=LaunchCrew", call)
            self.assertIn("Environment=demo", call)

    def test_full_run_all_deploys_pass_demo_tags(self):
        result, calls = self.run_bootstrap(self.base_args())
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        deploys = [call for call in calls if "deploy " in call]
        self.assertEqual(len(deploys), 1)
        for call in deploys:
            self.assertIn("--tags", call)
            self.assertIn("Project=LaunchCrew", call)
            self.assertIn("Environment=demo", call)
        creates = [call for call in calls if "create-change-set" in call]
        self.assertEqual(len(creates), 1)
        for call in creates:
            self.assertIn("--tags", call)
            self.assertIn("LaunchCrew", call)
            self.assertIn("demo", call)


class ImageDigestShapeTests(BootstrapHarness):
    def test_images_phase_uses_actual_digest_shape_for_five_repos(self):
        result, calls = self.run_bootstrap([*self.base_args(), "--phase", "images"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        batch_calls = [call for call in calls if "batch-get-image" in call]
        self.assertTrue(batch_calls)
        digest_calls = [call for call in batch_calls if "imageDigest" in call]
        self.assertTrue(digest_calls)
        for call in digest_calls:
            self.assertIn("imageId.imageDigest", call)
        for repo in ("launchcrew-api", "launchcrew-web", "launchcrew-web-proxy",
                     "launchcrew-migration", "launchcrew-bootstrap"):
            self.assertTrue(any(repo in call for call in batch_calls), msg=repo)
        failures_calls = [call for call in batch_calls if "failures" in call]
        self.assertTrue(failures_calls)

    def test_pinned_digest_mismatch_refused_as_moved(self):
        pinned = image("launchcrew-api") + "@sha256:" + "0" * 64
        result, _ = self.run_bootstrap(
            [*self.base_args(**{"--api-image": pinned}), "--phase", "images"])
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("pinned digest", combined)
        self.assertIn("tag moved", combined)

    def test_pinned_digest_match_passes(self):
        pinned = image("launchcrew-api") + "@sha256:abc123"
        result, _ = self.run_bootstrap(
            [*self.base_args(**{"--api-image": pinned}), "--phase", "images"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_missing_image_refused_in_images_phase(self):
        result, _ = self.run_bootstrap(
            [*self.base_args(), "--phase", "images"], mode="image_missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stdout + result.stderr)

    def test_failures_rejected_in_images_phase(self):
        result, _ = self.run_bootstrap(
            [*self.base_args(), "--phase", "images"], mode="image_failures")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failures", result.stdout + result.stderr)

    def test_missing_digest_rejected_in_images_phase(self):
        result, _ = self.run_bootstrap(
            [*self.base_args(), "--phase", "images"], mode="image_digest_none")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no digest", result.stdout + result.stderr)

    def test_fake_reflects_actual_batch_get_image_shape(self):
        import json as _json
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            env = dict(os.environ)
            env["FAKE_MODE"] = "success"
            proc = subprocess.run(
                [str(fake), "ecr", "batch-get-image",
                 "--repository-name", "launchcrew-api",
                 "--image-ids", "imageTag=abc123"],
                capture_output=True, text=True, env=env, check=False)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            doc = _json.loads(proc.stdout)
            self.assertEqual(doc["failures"], [])
            self.assertIn("imageId", doc["images"][0])
            self.assertEqual(doc["images"][0]["imageId"]["imageDigest"],
                             "sha256:abc123")
            self.assertNotIn("imageDigest", doc["images"][0])
            proc = subprocess.run(
                [str(fake), "ecr", "batch-get-image",
                 "--repository-name", "launchcrew-api",
                 "--image-ids", "imageTag=abc123",
                 "--query", "images[0].imageId.imageDigest",
                 "--output", "text"],
                capture_output=True, text=True, env=env, check=False)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertEqual(proc.stdout.strip(), "sha256:abc123")
            proc = subprocess.run(
                [str(fake), "ecr", "batch-get-image",
                 "--repository-name", "launchcrew-api",
                 "--image-ids", "imageTag=abc123",
                 "--query", "images[0].imageDigest",
                 "--output", "text"],
                capture_output=True, text=True, env=env, check=False)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertEqual(proc.stdout.strip(), "None")


class QuiesceTests(BootstrapHarness):
    STACK_ID = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{STACK}/abc123"

    def quiesce_args(self, confirm=None):
        args = self.base_args()
        args += ["--phase", "quiesce"]
        if confirm is None:
            args += ["--quiesce-confirm", self.STACK_ID]
        elif confirm != "":
            args += ["--quiesce-confirm", confirm]
        args += ["--release-generation", "head006-testabc"]
        return args

    def test_infra_refuses_when_services_true(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_ENABLE": "true"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("EnableServices=true", combined)
        self.assertIn("quiesce", combined)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_all_refuses_when_services_true(self):
        result, calls = self.run_bootstrap(
            self.base_args(), extra_env={"FAKE_ENABLE": "true"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("quiesce", combined)
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_quiesce_requires_explicit_confirm(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "quiesce",
             "--release-generation", "head006-testabc"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("quiesce-confirm", result.stdout + result.stderr)
        self.assertEqual(calls, [])

    def quiesce_env(self, changeset="exact", tg="drained"):
        return {"FAKE_ENABLE": "true",
                "FAKE_STACK_STATUS": "UPDATE_COMPLETE",
                "FAKE_SERVICE": "stopped",
                "FAKE_CHANGESET": changeset,
                "FAKE_TG_HEALTH": tg}

    def test_quiesce_success_with_real_change_set_shape(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(), extra_env=self.quiesce_env())
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP COMPLETE", result.stdout)
        joined = " ".join(calls)
        self.assertIn("create-change-set", joined)
        self.assertIn("--use-previous-template", joined)
        self.assertIn("ParameterKey=EnableServices,ParameterValue=false", joined)
        self.assertIn("describe-change-set", joined)
        self.assertIn("describe-services", joined)
        self.assertIn("describe-target-health", joined)
        executes = [call for call in calls if "execute-change-set" in call]
        self.assertEqual(len(executes), 1)
        self.assertIn("changeSet/quiesce-006/", executes[0])
        describes = [call for call in calls if "describe-change-set" in call]
        self.assertTrue(describes)
        for call in describes:
            self.assertIn("--no-paginate", call)
            self.assertIn("--cli-input-json", call)
            self.assertNotIn("--change-set-name", call)
            self.assertNotIn("--stack-name", call)
        self.assertFalse(any("run-task" in call for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("delete-change-set" in call for call in calls))
        self.assertIn("UPDATE_COMPLETE", result.stdout)
        self.assertIn("0/0/0", result.stdout + result.stderr)
        self.assertIn("drained", result.stdout + result.stderr)
        self.assertIn("exact Project LaunchCrew plus Environment demo preserved",
                      result.stdout + result.stderr)

    def test_quiesce_refuses_foreign_resource_change(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(), extra_env=self.quiesce_env("foreign"))
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("FOREIGN_Database", combined)
        self.assertIn("preserved for inspection", combined)
        self.assertFalse(any("delete-change-set" in call for call in calls))
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_quiesce_refuses_replacement_change(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(),
            extra_env={"FAKE_ENABLE": "true",
                       "FAKE_STACK_STATUS": "UPDATE_COMPLETE",
                       "FAKE_SERVICE": "stopped",
                       "FAKE_CHANGESET": "replacement"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REPLACEMENT", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_quiesce_refuses_empty_change_set(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(),
            extra_env={"FAKE_ENABLE": "true",
                       "FAKE_STACK_STATUS": "UPDATE_COMPLETE",
                       "FAKE_SERVICE": "stopped",
                       "FAKE_CHANGESET": "empty"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EMPTY", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_quiesce_refuses_wrong_confirm(self):
        wrong = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{STACK}/wrong123"
        result, calls = self.run_bootstrap(
            self.quiesce_args(confirm=wrong),
            extra_env={"FAKE_ENABLE": "true",
                       "FAKE_STACK_STATUS": "UPDATE_COMPLETE",
                       "FAKE_SERVICE": "stopped"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("StackId", result.stdout + result.stderr)
        self.assertFalse(any("create-change-set" in call for call in calls))
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_quiesce_already_stopped_makes_no_change(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(),
            extra_env={"FAKE_ENABLE": "false",
                       "FAKE_STACK_STATUS": "UPDATE_COMPLETE",
                       "FAKE_SERVICE": "stopped"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("already stopped", result.stdout + result.stderr)
        self.assertFalse(any("create-change-set" in call for call in calls))
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_quiesce_refuses_non_desired_count_detail(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(), extra_env=self.quiesce_env("wrong_detail"))
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("DETAIL_ApiService_NAME_TaskDefinition", combined)
        self.assertFalse(any("execute-change-set" in call for call in calls))
        self.assertFalse(any("delete-change-set" in call for call in calls))

    def test_quiesce_refuses_tags_scope_change(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(), extra_env=self.quiesce_env("tags_scope"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SCOPE_ApiService_Tags", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_quiesce_refuses_parameter_mismatch(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(), extra_env=self.quiesce_env("params_mismatch"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PARAMS_VALUE_EnableServices", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_quiesce_refuses_tag_mismatch(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(), extra_env=self.quiesce_env("tags_mismatch"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("TAGS_MISMATCH", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_quiesce_reviews_every_page_before_execute(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(), extra_env=self.quiesce_env("paginated_ok"))
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        describes = [call for call in calls if "describe-change-set" in call]
        self.assertEqual(len(describes), 2)
        decoded = [call for call in calls if "INPUT_JSON_CHANGESET" in call]
        self.assertEqual(len(decoded), 2)
        self.assertIn("page2", decoded[1])
        executes = [call for call in calls if "execute-change-set" in call]
        self.assertEqual(len(executes), 1)
        self.assertIn("changeSet/quiesce-006/", executes[0])

    def test_quiesce_refuses_extra_change_on_later_page(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(), extra_env=self.quiesce_env("paginated_extra"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FOREIGN_Database", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_quiesce_refuses_truncated_pages(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(), extra_env=self.quiesce_env("truncated"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unreviewed pages", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_quiesce_refuses_in_flight_targets(self):
        for tg_mode, token in (("in_flight", "IN_FLIGHT_healthy"),
                               ("draining", "IN_FLIGHT_draining"),
                               ("unknown", "IN_FLIGHT_weird")):
            with self.subTest(tg_mode=tg_mode):
                result, calls = self.run_bootstrap(
                    self.quiesce_args(),
                    extra_env=self.quiesce_env("exact", tg_mode))
                self.assertNotEqual(result.returncode, 0, msg=tg_mode)
                combined = result.stdout + result.stderr
                self.assertIn(token, combined, msg=tg_mode)
                self.assertIn("no in-flight targets", combined, msg=tg_mode)
                self.assertTrue(any("execute-change-set" in call for call in calls),
                                msg=tg_mode)
                self.assertTrue(any("describe-target-health" in call
                                    for call in calls), msg=tg_mode)
                self.assertNotIn("BOOTSTRAP COMPLETE", result.stdout, msg=tg_mode)

    def test_quiesce_accepts_unused_targets_as_drained(self):
        result, calls = self.run_bootstrap(
            self.quiesce_args(), extra_env=self.quiesce_env("exact", "unused"))
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("drained", result.stdout + result.stderr)

    def test_quiesce_refuses_foreign_target_group(self):
        foreign = ("arn:aws:elasticloadbalancing:us-east-1:999988887777:"
                   "targetgroup/api-abcdef0123456789/0123456789abcdef")
        result, calls = self.run_bootstrap(
            self.quiesce_args(),
            extra_env={**self.quiesce_env(), "FAKE_API_TG": foreign})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("foreign or malformed", combined)
        self.assertNotIn("BOOTSTRAP COMPLETE", result.stdout)

    def test_release_generation_required_in_journal_code(self):
        code = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("RELEASE_GEN", code)
        self.assertIn("LEGACY_ACTIVE_FILE", code)
        self.assertIn("head006", code)
        self.assertIn("legacy predecessor", code)
        self.assertIn("reconcile_prior_generations", code)


class InfraDiffGuardTests(BootstrapHarness):
    def test_infra_update_executes_reviewed_change_set_id(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        joined = " ".join(calls)
        self.assertIn("create-change-set", joined)
        self.assertIn("--template-file", joined)
        self.assertIn("infra-006", joined)
        self.assertIn("describe-change-set", joined)
        self.assertIn("describe-services", joined)
        executes = [call for call in calls if "execute-change-set" in call]
        self.assertEqual(len(executes), 1)
        self.assertIn("changeSet/infra-006/", executes[0])
        describes = [call for call in calls if "describe-change-set" in call]
        self.assertTrue(describes)
        for call in describes:
            self.assertIn("--no-paginate", call)
            self.assertIn("--cli-input-json", call)
            self.assertNotIn("--change-set-name", call)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("delete-change-set" in call for call in calls))
        self.assertIn("review passed", result.stdout + result.stderr)
        self.assertIn("same reviewed change set ID", result.stdout + result.stderr)
        self.assertFalse(any("run-task" in call for call in calls))

    def test_infra_allows_taskdef_replacement_for_image_updates(self):
        # The exact fixture carries Replacement True on all seven owned task
        # definitions with ContainerDefinitions details, which is the only
        # lawful replacement shape; success here proves it is accepted.
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP COMPLETE", result.stdout)

    def test_infra_refuses_foreign_db_change(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "foreign"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("FOREIGN_Database", combined)
        self.assertIn("preserved for inspection", combined)
        self.assertFalse(any("delete-change-set" in call for call in calls))
        self.assertFalse(any("execute-change-set" in call for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_infra_refuses_service_replacement_change(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "replacement"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REPLACEMENT_ApiService_True", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))

    def test_infra_refuses_non_image_taskdef_detail(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "wrong_detail"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("DETAIL_ApiTaskDefinition_NAME_ExecutionRoleArn", combined)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_infra_refuses_missing_details(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "missing_details"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DETAILS_ApiTaskDefinition_MISSING",
                      result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_infra_refuses_parameter_mismatch(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "params_mismatch"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PARAMS_VALUE_EnableServices", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_infra_refuses_tag_mismatch(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "tags_mismatch"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("TAGS_MISMATCH", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_infra_refuses_foreign_change_set_id(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "wrong_id"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ID_MISMATCH", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_infra_reviews_every_page_before_execute(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "paginated_ok"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        describes = [call for call in calls if "describe-change-set" in call]
        self.assertEqual(len(describes), 2)
        decoded = [call for call in calls if "INPUT_JSON_CHANGESET" in call]
        self.assertEqual(len(decoded), 2)
        self.assertIn("page2", decoded[1])
        executes = [call for call in calls if "execute-change-set" in call]
        self.assertEqual(len(executes), 1)
        self.assertIn("changeSet/infra-006/", executes[0])

    def test_infra_refuses_extra_change_on_later_page(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "paginated_extra"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FOREIGN_Database", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_infra_refuses_truncated_pages(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "truncated"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unreviewed pages", result.stdout + result.stderr)
        self.assertFalse(any("execute-change-set" in call for call in calls))

    def test_infra_refuses_when_services_running(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_SERVICE": "ok"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("DESIRED_1", combined)
        self.assertFalse(any("create-change-set" in call for call in calls))
        self.assertFalse(any("execute-change-set" in call for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_infra_never_deletes_existing_change_set(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CREATE": "exists"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("never deleted or replaced", combined)
        self.assertFalse(any("delete-change-set" in call for call in calls))
        self.assertFalse(any("execute-change-set" in call for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))

    def test_infra_no_changes_skips_execute_without_deploy(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_INFRA_CHANGESET": "empty"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("already current", result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP COMPLETE", result.stdout)
        self.assertFalse(any("execute-change-set" in call for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))


class LegacyJournalTests(BootstrapHarness):
    LEGACY_TOKEN = "lc-" + "a" * 30
    LEGACY_TASK = ("arn:aws:ecs:us-east-1:111122223333:"
                   "task/launchcrew-demo/legacy001")
    LEGACY_TASKDEF = ("arn:aws:ecs:us-east-1:111122223333:task"
                      "-definition/"
                      "launchcrew-demo-sdkmaterial:1")

    def write_legacy(self, journals, outcome="complete"):
        import json as _json
        legacy = journals / f"launchcrew-{STACK}-material-sdk-material-active.json"
        doc = {
            "version": 1,
            "stack": STACK,
            "phase": "material",
            "label": "sdk-material",
            "taskdef_logical": "SdkMaterialTaskDefinition",
            "taskdef_arn": self.LEGACY_TASKDEF,
            "cluster": STACK,
            "client_token": self.LEGACY_TOKEN,
            "config_digest": "0" * 32,
            "region": REGION,
            "account": ACCOUNT,
            "outcome": outcome,
            "task_arn": self.LEGACY_TASK if outcome == "complete" else "",
            "updated_utc": "2026-01-01T00:00:00Z",
        }
        legacy.write_text(_json.dumps(doc), encoding="utf-8")
        legacy.chmod(0o600)
        return legacy

    def test_new_generation_reconciles_legacy_and_preserves_it(self):
        import json as _json
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared = Path(shared_tmp)
            journals = shared / "journals"
            journals.mkdir(mode=0o700)
            journals.chmod(0o700)
            legacy = self.write_legacy(journals, outcome="complete")
            before = legacy.read_text(encoding="utf-8")
            taskdefs = shared / "taskdefs"
            taskdefs.write_text(
                f"{self.LEGACY_TASK}|{self.LEGACY_TASKDEF}|{self.LEGACY_TOKEN}\n",
                encoding="utf-8")
            (shared / "count").write_text("10", encoding="utf-8")
            (shared / "token").write_text("", encoding="utf-8")
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "material",
                 "--release-generation", "head006-testabc"],
                shared_dir=shared_tmp)
            self.assertEqual(result.returncode, 0,
                             msg=result.stdout + result.stderr)
            self.assertIn("legacy predecessor reconciled",
                          result.stdout + result.stderr)
            self.assertTrue(legacy.exists())
            self.assertEqual(legacy.read_text(encoding="utf-8"), before)
            self.assertEqual(oct(legacy.stat().st_mode & 0o777), "0o600")
            new_file = journals / (f"launchcrew-{STACK}-material-sdk-material-"
                                   "head006-testabc-active.json")
            self.assertTrue(new_file.exists())
            new_doc = _json.loads(new_file.read_text(encoding="utf-8"))
            self.assertEqual(new_doc.get("outcome"), "complete")
            self.assertEqual(new_doc.get("release_generation"), "head006-testabc")
            self.assertEqual(new_doc.get("target_head"), "006")
            self.assertEqual(new_doc.get("predecessor_task_arn"), self.LEGACY_TASK)
            self.assertEqual(new_doc.get("predecessor_outcome"), "complete")
            runs = [call for call in calls if "run-task" in call]
            self.assertEqual(len(runs), 1)
            describes = [call for call in calls if "describe-tasks" in call]
            self.assertGreaterEqual(len(describes), 2)

    def test_unresolved_legacy_blocks_new_launch_without_overwrite(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared = Path(shared_tmp)
            journals = shared / "journals"
            journals.mkdir(mode=0o700)
            journals.chmod(0o700)
            legacy = self.write_legacy(journals, outcome="started")
            before = legacy.read_text(encoding="utf-8")
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "material",
                 "--release-generation", "head006-testabc"],
                shared_dir=shared_tmp)
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("legacy generation is started", combined)
            self.assertIn("no new launch", combined)
            self.assertFalse(any("run-task" in call for call in calls))
            self.assertTrue(legacy.exists())
            self.assertEqual(legacy.read_text(encoding="utf-8"), before)
            new_file = journals / (f"launchcrew-{STACK}-material-sdk-material-"
                                   "head006-testabc-active.json")
            self.assertFalse(new_file.exists())


class CrossGenerationJournalTests(BootstrapHarness):
    STACK_ID = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{STACK}/abc123"
    PRIOR_TOKEN = "lc-" + "b" * 30
    PRIOR_TASK = ("arn:aws:ecs:us-east-1:111122223333:"
                  "task/launchcrew-demo/prior001")
    PRIOR_TASKDEF = ("arn:aws:ecs:us-east-1:111122223333:task"
                     "-definition/launchcrew-demo-sdkmaterial:1")
    MIG_TASKDEF = ("arn:aws:ecs:us-east-1:111122223333:task"
                   "-definition/launchcrew-demo-migration:1")

    def write_prior(self, journals, phase="material", label="sdk-material",
                    logical="SdkMaterialTaskDefinition", taskdef=None,
                    generation="head006-old0000", outcome="complete",
                    archived=False, **overrides):
        import json as _json
        taskdef = taskdef if taskdef is not None else self.PRIOR_TASKDEF
        if archived:
            name = (f"launchcrew-{STACK}-{phase}-{label}-{generation}-"
                    f"complete-{self.PRIOR_TOKEN}.json")
        else:
            name = (f"launchcrew-{STACK}-{phase}-{label}-{generation}-"
                    "active.json")
        path = journals / name
        doc = {
            "version": 2,
            "stack": STACK,
            "phase": phase,
            "label": label,
            "taskdef_logical": logical,
            "taskdef_arn": taskdef,
            "cluster": STACK,
            "client_token": self.PRIOR_TOKEN,
            "config_digest": "1" * 32,
            "region": REGION,
            "account": ACCOUNT,
            "outcome": outcome,
            "task_arn": self.PRIOR_TASK if outcome == "complete" else "",
            "release_generation": generation,
            "source_sha": "old0000",
            "target_head": "006",
            "stack_id": self.STACK_ID,
            "predecessor_task_arn": "",
            "predecessor_outcome": "none",
            "updated_utc": "2026-01-01T00:00:00Z",
        }
        doc.update(overrides)
        path.write_text(_json.dumps(doc), encoding="utf-8")
        path.chmod(0o600)
        return path

    def seed_live_prior(self, shared):
        (shared / "taskdefs").write_text(
            f"{self.PRIOR_TASK}|{self.PRIOR_TASKDEF}|{self.PRIOR_TOKEN}\n",
            encoding="utf-8")
        (shared / "count").write_text("10", encoding="utf-8")
        (shared / "token").write_text("", encoding="utf-8")

    def fresh_shared(self, shared_tmp):
        shared = Path(shared_tmp)
        journals = shared / "journals"
        journals.mkdir(mode=0o700)
        journals.chmod(0o700)
        return shared, journals

    def test_new_generation_blocked_by_pending_prior_generation(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared, journals = self.fresh_shared(shared_tmp)
            prior = self.write_prior(journals, outcome="started")
            before = prior.read_text(encoding="utf-8")
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "material",
                 "--release-generation", "head006-new1111"],
                shared_dir=shared_tmp)
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("UNRESOLVED", combined)
            self.assertIn("no new launch", combined)
            self.assertFalse(any("run-task" in call for call in calls))
            self.assertTrue(prior.exists())
            self.assertEqual(prior.read_text(encoding="utf-8"), before)
            new_file = journals / (f"launchcrew-{STACK}-material-sdk-material-"
                                   "head006-new1111-active.json")
            self.assertFalse(new_file.exists())

    def test_mutating_label_blocked_by_pending_prior_generation(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared, journals = self.fresh_shared(shared_tmp)
            prior = self.write_prior(
                journals, phase="migrate", label="migration",
                logical="MigrationTaskDefinition", taskdef=self.MIG_TASKDEF,
                outcome="started")
            before = prior.read_text(encoding="utf-8")
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "migrate",
                 "--release-generation", "head006-new1111"],
                shared_dir=shared_tmp)
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("UNRESOLVED", combined)
            self.assertIn("no new launch", combined)
            self.assertFalse(any("run-task" in call for call in calls))
            self.assertEqual(prior.read_text(encoding="utf-8"), before)

    def test_new_generation_proceeds_after_complete_prior_generation(self):
        import json as _json
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared, journals = self.fresh_shared(shared_tmp)
            prior = self.write_prior(journals, outcome="complete")
            before = prior.read_text(encoding="utf-8")
            self.seed_live_prior(shared)
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "material",
                 "--release-generation", "head006-new1111"],
                shared_dir=shared_tmp)
            self.assertEqual(result.returncode, 0,
                             msg=result.stdout + result.stderr)
            self.assertIn("prior generation head006-old0000 reconciled",
                          result.stdout + result.stderr)
            self.assertEqual(prior.read_text(encoding="utf-8"), before)
            self.assertEqual(oct(prior.stat().st_mode & 0o777), "0o600")
            new_file = journals / (f"launchcrew-{STACK}-material-sdk-material-"
                                   "head006-new1111-active.json")
            new_doc = _json.loads(new_file.read_text(encoding="utf-8"))
            self.assertEqual(new_doc.get("outcome"), "complete")
            self.assertEqual(new_doc.get("release_generation"), "head006-new1111")
            runs = [call for call in calls if "run-task" in call]
            self.assertEqual(len(runs), 1)

    def test_prior_generation_live_mismatch_blocks_new_launch(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared, journals = self.fresh_shared(shared_tmp)
            prior = self.write_prior(journals, outcome="complete")
            (shared / "taskdefs").write_text(
                f"{self.PRIOR_TASK}|{self.PRIOR_TASKDEF}|lc-{'c' * 30}\n",
                encoding="utf-8")
            (shared / "count").write_text("10", encoding="utf-8")
            (shared / "token").write_text("", encoding="utf-8")
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "material",
                 "--release-generation", "head006-new1111"],
                shared_dir=shared_tmp)
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("WRONG_TOKEN", combined)
            self.assertIn("no new", combined)
            self.assertFalse(any("run-task" in call for call in calls))
            self.assertTrue(prior.exists())

    def test_malformed_prior_record_blocks_new_launch(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared, journals = self.fresh_shared(shared_tmp)
            prior = journals / (f"launchcrew-{STACK}-material-sdk-material-"
                                "head006-old0000-active.json")
            prior.write_text("{not-json", encoding="utf-8")
            prior.chmod(0o600)
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "material",
                 "--release-generation", "head006-new1111"],
                shared_dir=shared_tmp)
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("UNREADABLE", combined)
            self.assertIn("no new launch", combined)
            self.assertFalse(any("run-task" in call for call in calls))

    def test_foreign_prior_record_blocks_new_launch(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared, journals = self.fresh_shared(shared_tmp)
            self.write_prior(journals, outcome="complete", account="999988887777")
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "material",
                 "--release-generation", "head006-new1111"],
                shared_dir=shared_tmp)
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("ACCOUNT_MISMATCH", combined)
            self.assertFalse(any("run-task" in call for call in calls))

    def test_conflicting_target_head_blocks_new_launch(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared, journals = self.fresh_shared(shared_tmp)
            self.write_prior(journals, outcome="complete", target_head="005")
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "material",
                 "--release-generation", "head006-new1111"],
                shared_dir=shared_tmp)
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("HEAD_MISMATCH", combined)
            self.assertFalse(any("run-task" in call for call in calls))

    def test_archived_prior_record_must_be_complete(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared, journals = self.fresh_shared(shared_tmp)
            self.write_prior(journals, outcome="started", archived=True)
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "material",
                 "--release-generation", "head006-new1111"],
                shared_dir=shared_tmp)
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("UNRESOLVED", combined)
            self.assertFalse(any("run-task" in call for call in calls))

    def test_unknown_journal_file_blocks_new_launch(self):
        with tempfile.TemporaryDirectory() as shared_tmp:
            shared, journals = self.fresh_shared(shared_tmp)
            stray = journals / (f"launchcrew-{STACK}-material-sdk-material-"
                                "head006-old0000-weird.json")
            stray.write_text("{}", encoding="utf-8")
            stray.chmod(0o600)
            result, calls = self.run_bootstrap(
                [*self.base_args(), "--phase", "material",
                 "--release-generation", "head006-new1111"],
                shared_dir=shared_tmp)
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("UNKNOWN_FILE", combined)
            self.assertFalse(any("run-task" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
