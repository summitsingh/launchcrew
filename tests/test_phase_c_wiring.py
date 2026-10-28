"""Offline Phase C wiring tests with a fake AWS command fixture.

No test contacts AWS. The fake AWS script logs calls and returns canned
responses shaped like real APIs. These tests prove the coherent source
wiring: distinct SDK init and material verifier task definitions with an
explicit EntryPoint plus Command, exact metadata env with zero secret
injection, physical IAM role resolution for both execution and task roles,
controller ordering with staged resume, foundation-only budget ownership,
and ambiguous launch journaling with read-only recovery and no resend.
"""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

BOOTSTRAP = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "bootstrap.sh"

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
  SECRET_ID=""
  PREV=""
  for ARG in "$@"; do
    if [ "$PREV" = "--secret-id" ]; then SECRET_ID="$ARG"; fi
    PREV="$ARG"
  done
  case "$*" in
    *"--query ARN"*)
      printf '%s\\n' "$SECRET_ID"
      exit 0 ;;
  esac
  case "$*" in
    *"Key=='Project'"*)
      if [ "$MODE" = "secret_tag_mismatch" ]; then printf 'Other\\n'; exit 0; fi
      printf 'LaunchCrew\\n'
      exit 0 ;;
    *"Key=='Environment'"*)
      printf 'demo\\n'
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
  if [ "$DESCRIBE_STACK" = "launchcrew-foundation" ]; then
    if [ "${FAKE_FOUNDATION:-exists}" = "missing" ]; then
      echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id launchcrew-foundation does not exist" >&2
      exit 254
    fi
    case "$*" in
      *"StackStatus"*) printf 'CREATE_COMPLETE\\n'; exit 0 ;;
    esac
    printf '{"Stacks":[{"StackId":"arn:aws:cloudformation:us-east-1:111122223333:stack/launchcrew-foundation/abc123","StackStatus":"CREATE_COMPLETE","Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"}]}]}\\n'
    exit 0
  fi
  if [ "$DESCRIBE_STACK" = "launchcrew-prereqs" ]; then
    case "$*" in
      *"StackStatus"*) printf 'CREATE_COMPLETE\\n'; exit 0 ;;
    esac
    printf '{"Stacks":[{"StackId":"arn:aws:cloudformation:us-east-1:111122223333:stack/launchcrew-prereqs/abc123","StackStatus":"CREATE_COMPLETE","Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"}]}]}\\n'
    exit 0
  fi
  case "$*" in
    *"StackStatus"*) printf 'CREATE_COMPLETE\\n'; exit 0 ;;
  esac
  printf '{"Stacks":[{"StackId":"arn:aws:cloudformation:us-east-1:111122223333:stack/launchcrew-demo/abc123","StackStatus":"CREATE_COMPLETE","Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"}],"Parameters":[{"ParameterKey":"EnableServices","ParameterValue":"false"}]}]}\\n'
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
    ApiExecutionRole|WebExecutionRole|MigrationExecutionRole|BootstrapExecutionRole|VerifyExecutionRole|SdkInitExecutionRole|SdkMaterialExecutionRole|ApiTaskRole|WebTaskRole|MigrationTaskRole|BootstrapTaskRole|VerifyTaskRole|SdkInitTaskRole|SdkMaterialTaskRole) printf '%s-physical\\n' "$RESOURCE_LOGICAL"; exit 0 ;;
  esac
  echo "fake-aws: unexpected resource lookup: $*" >&2
  exit 2
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "deploy" ]; then
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "wait" ]; then
  exit 0
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
if [ "$1" = "ecr" ] && [ "$2" = "batch-get-image" ]; then
  case "$*" in
    *"imageDigest"*) printf 'sha256:abc123\\n'; exit 0 ;;
    *"failures"*) printf '0\\n'; exit 0 ;;
  esac
  printf '{"images":[{"imageDigest":"sha256:abc123"}],"failures":[]}\\n'
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "run-task" ]; then
  if [ -n "${FAKE_RUN_DELAY:-}" ]; then sleep "$FAKE_RUN_DELAY" 2>/dev/null || true; fi
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
  printf '%s|%s\\n' "$TASKARN" "$TASKDEF" >>"${FAKE_TASKDEF_FILE:-/dev/null}" 2>/dev/null || true
  if [ "${FAKE_RUN:-ok}" = "fail" ]; then
    echo "An error occurred (ClientException) when calling the RunTask operation: ambiguous transport failure" >&2
    exit 1
  fi
  printf '{"tasks":[{"taskArn":"%s"}],"failures":[]}\\n' "$TASKARN"
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "wait" ]; then
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
  for TOKEN_ARG in "$@"; do
    if [ "$LIST_INPUT_PREV" = "--cli-input-json" ]; then LIST_INPUT_PATH="$TOKEN_ARG"; fi
    LIST_INPUT_PREV="$TOKEN_ARG"
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
  TOKEN="$(printf '%s' "$LIST_DECODED" | cut -d'|' -f1)"
  DESIRED="$(printf '%s' "$LIST_DECODED" | cut -d'|' -f2)"
  LIST_NEXT="$(printf '%s' "$LIST_DECODED" | cut -d'|' -f3)"
  if [ -n "$TOKEN" ]; then printf '%s' "$TOKEN" >"${FAKE_TOKEN_FILE:-/dev/null}" 2>/dev/null || true; fi
  RECOVER_MODE="${FAKE_RECOVER:-none}"
  if [ -n "$DESIRED" ]; then
    if [ "$DESIRED" != "STOPPED" ]; then printf '{"taskArns":[]}\\n'; exit 0; fi
    if [ "$RECOVER_MODE" = "stopped_paginated" ]; then
      if [ -z "$LIST_NEXT" ]; then
        printf '%s' '{"taskArns":[],"nextToken":"page2"}'
        exit 0
      fi
      if [ "$LIST_NEXT" = "page2" ]; then
        ADOPT_ARN="arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task009"
        printf '%s' "$ADOPT_ARN" >"${FAKE_ADOPT_FILE:-/dev/null}" 2>/dev/null || true
        printf '%s' '{"taskArns":["arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task009"]}'
        exit 0
      fi
      printf '%s' '{"taskArns":[]}'
      exit 0
    fi
    if [ -n "$LIST_NEXT" ]; then printf '%s' '{"taskArns":[]}'; exit 0; fi
    if [ "$RECOVER_MODE" = "stopped_adopt" ]; then
      ADOPT_ARN="arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task009"
      printf '%s' "$ADOPT_ARN" >"${FAKE_ADOPT_FILE:-/dev/null}" 2>/dev/null || true
      printf '{"taskArns":["%s"]}\\n' "$ADOPT_ARN"
      exit 0
    fi
    if [ "$RECOVER_MODE" = "stopped_multiple" ]; then
      printf '{"taskArns":["arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task011","arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task012"]}\\n'
      exit 0
    fi
    if [ "$RECOVER_MODE" = "stopped_wrong" ]; then
      ADOPT_ARN="arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task013"
      printf '{"taskArns":["%s"]}\\n' "$ADOPT_ARN"
      exit 0
    fi
    if [ "$RECOVER_MODE" = "multiple" ]; then
      printf '{"taskArns":[]}\\n'
      exit 0
    fi
    printf '{"taskArns":[]}\\n'
    exit 0
  fi
  if [ "$RECOVER_MODE" = "running_paginated" ]; then
    if [ -z "$LIST_NEXT" ]; then
      printf '%s' '{"taskArns":[],"nextToken":"page2"}'
      exit 0
    fi
    if [ "$LIST_NEXT" = "page2" ]; then
      ADOPT_ARN="arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task001"
      printf '%s' "$ADOPT_ARN" >"${FAKE_ADOPT_FILE:-/dev/null}" 2>/dev/null || true
      printf '%s' '{"taskArns":["arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task001"]}'
      exit 0
    fi
    printf '%s' '{"taskArns":[]}'
    exit 0
  fi
  if [ -n "$LIST_NEXT" ]; then printf '{"taskArns":[]}\\n'; exit 0; fi
  if [ "$RECOVER_MODE" = "multiple" ]; then
    printf '{"taskArns":["arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task001","arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task002"]}\\n'
    exit 0
  fi
  if [ "$RECOVER_MODE" = "adopt" ] || [ "$RECOVER_MODE" = "wrong" ]; then
    ADOPT_ARN="arn:aws:ecs:us-east-1:111122223333:task/launchcrew-demo/task001"
    printf '%s' "$ADOPT_ARN" >"${FAKE_ADOPT_FILE:-/dev/null}" 2>/dev/null || true
    printf '{"taskArns":["%s"]}\\n' "$ADOPT_ARN"
    exit 0
  fi
  printf '{"taskArns":[]}\\n'
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-tasks" ]; then
  LAST="$(tail -n 1 "${FAKE_TASKDEF_FILE:-/dev/null}" 2>/dev/null || true)"
  TASKARN="${LAST%%|*}"
  TASKDEF="${LAST#*|}"
  WANT=""
  WANT_PREV=""
  for WANT_ARG in "$@"; do
    if [ "$WANT_PREV" = "--tasks" ]; then WANT="$WANT_ARG"; fi
    WANT_PREV="$WANT_ARG"
  done
  if [ -n "$WANT" ]; then TASKARN="$WANT"; fi
  if [ "${FAKE_RECOVER:-none}" = "wrong" ] || [ "${FAKE_RECOVER:-none}" = "stopped_wrong" ]; then
    TASKDEF='arn:aws:ecs:us-east-1:111122223333:task'"-definition"'/launchcrew-demo-other:9'
  fi
  case "$TASKDEF" in
    *launchcrew-demo-migration*) NAMES="migration" ;;
    *launchcrew-demo-sdkinit*) NAMES="sdk-init" ;;
    *launchcrew-demo-sdkmaterial*) NAMES="sdk-material" ;;
    *launchcrew-demo-verify*|*launchcrew-demo-bootstrap*) NAMES="bootstrap-db-roles" ;;
    *) NAMES="bootstrap-db-roles" ;;
  esac
  STARTED_BY=""
  if [ -n "${FAKE_TOKEN_FILE:-}" ] && [ -f "$FAKE_TOKEN_FILE" ]; then
    STARTED_BY="$(cat "$FAKE_TOKEN_FILE" 2>/dev/null || true)"
  fi
  CONTAINERS=""
  for NAME in $NAMES; do
    ENTRY="$(printf '{"name":"%s","lastStatus":"STOPPED","exitCode":0}' "$NAME")"
    if [ -z "$CONTAINERS" ]; then CONTAINERS="$ENTRY"; else CONTAINERS="$CONTAINERS,$ENTRY"; fi
  done
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
  SDK_CERT="${FAKE_CERT_ARN:-}"
  SDK_HOST="${FAKE_DB_HOST:-}"
  SDK_MODE="${FAKE_SDK:-exact}"
  EXEC_SUFFIX="-physical"
  if [ "$MODE" = "role_mismatch" ]; then EXEC_SUFFIX="-wrong"; fi
  if [ "$SDK_MODE" = "env" ]; then SDK_HOST="wrong-host.example.test"; fi
  ENTRY_JSON=',"entryPoint":["/opt/venv/bin/python","/app/scripts/populate_prereqs.py"]'
  if [ "$SDK_MODE" = "entrypoint" ]; then ENTRY_JSON=""; fi
  INJECT_JSON=""
  if [ "$SDK_MODE" = "injection" ]; then
    INJECT_JSON=',"secrets":[{"name":"DATABASE_URL","valueFrom":"SECRET-INJECTED"}]'
  fi
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
      SDK_COMMAND="--populate"
      if [ "$SDK_MODE" = "command" ]; then SDK_COMMAND="--bind"; fi
      printf '{"taskDefinition":{"executionRoleArn":"arn:aws:iam::111122223333:role/SdkInitExecutionRole%s","taskRoleArn":"arn:aws:iam::111122223333:role/SdkInitTaskRole%s","containerDefinitions":[{"name":"sdk-init","essential":true,"image":"%s"%s,"command":["%s"],"environment":[{"name":"LAUNCHCREW_EXPECTED_ACCOUNT","value":"111122223333"},{"name":"LAUNCHCREW_EXPECTED_REGION","value":"us-east-1"},{"name":"LAUNCHCREW_EXPECTED_ROLE","value":"SdkInitTaskRole-physical"},{"name":"LAUNCHCREW_MASTER_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_RUNTIME_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_MIGRATION_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_TLS_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_CERT_ARN","value":"%s"},{"name":"LAUNCHCREW_DB_HOST","value":"%s"},{"name":"LAUNCHCREW_DB_TLS_MODE","value":"verify-full"},{"name":"DATABASE_SSL_ROOTCERT","value":"/app/rds-ca-bundle.pem"}]%s}]}}\\n' "$EXEC_SUFFIX" "$EXEC_SUFFIX" "$IMG_BOOT" "$ENTRY_JSON" "$SDK_COMMAND" "$SEC_MASTER" "$SEC_RT" "$SEC_MG" "$SEC_TLS" "$SDK_CERT" "$SDK_HOST"
      exit 0 ;;
    *launchcrew-demo-sdkmaterial*)
      SDK_COMMAND="--verify-material"
      if [ "$SDK_MODE" = "command" ]; then SDK_COMMAND="--bind"; fi
      printf '{"taskDefinition":{"executionRoleArn":"arn:aws:iam::111122223333:role/SdkMaterialExecutionRole%s","taskRoleArn":"arn:aws:iam::111122223333:role/SdkMaterialTaskRole%s","containerDefinitions":[{"name":"sdk-material","essential":true,"image":"%s"%s,"command":["%s"],"environment":[{"name":"LAUNCHCREW_EXPECTED_ACCOUNT","value":"111122223333"},{"name":"LAUNCHCREW_EXPECTED_REGION","value":"us-east-1"},{"name":"LAUNCHCREW_EXPECTED_ROLE","value":"SdkMaterialTaskRole-physical"},{"name":"LAUNCHCREW_MASTER_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_RUNTIME_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_MIGRATION_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_TLS_SECRET_ARN","value":"%s"},{"name":"LAUNCHCREW_CERT_ARN","value":"%s"},{"name":"LAUNCHCREW_DB_HOST","value":"%s"},{"name":"LAUNCHCREW_DB_TLS_MODE","value":"verify-full"},{"name":"DATABASE_SSL_ROOTCERT","value":"/app/rds-ca-bundle.pem"}]%s}]}}\\n' "$EXEC_SUFFIX" "$EXEC_SUFFIX" "$IMG_BOOT" "$ENTRY_JSON" "$SDK_COMMAND" "$SEC_MASTER" "$SEC_RT" "$SEC_MG" "$SEC_TLS" "$SDK_CERT" "$SDK_HOST"
      exit 0 ;;
    *) echo "fake-aws: unexpected describe task definition: $*" >&2; exit 2 ;;
  esac
  exit 0
fi
if [ "$1" = "ecs" ] && [ "$2" = "describe-services" ]; then
  printf '1\\t1\\n'; exit 0
fi
if [ "$1" = "budgets" ] && [ "$2" = "describe-budget" ]; then
  BUDGET_MODE="${FAKE_BUDGET:-exact}"
  if [ "$BUDGET_MODE" = "auth" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeBudget operation: not authorized" >&2
    exit 254
  fi
  if [ "$BUDGET_MODE" = "malformed" ]; then printf 'not-json{{{\\n'; exit 0; fi
  FILTER='{"Tags":{"Key":"Project","Values":["LaunchCrew"],"MatchOptions":["EQUALS"]}}'
  if [ "$BUDGET_MODE" = "wrongtag" ]; then
    FILTER='{"Tags":{"Key":"Project","Values":["Prod"],"MatchOptions":["EQUALS"]}}'
  fi
  printf '{"Budget":{"BudgetName":"launchcrew-demo","BudgetType":"COST","TimeUnit":"MONTHLY","FilterExpression":%s}}\\n' "$FILTER"
  exit 0
fi
if [ "$1" = "budgets" ] && [ "$2" = "describe-notifications-for-budget" ]; then
  NOTIF_MODE="${FAKE_NOTIF:-exact}"
  if [ "$NOTIF_MODE" = "auth" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeNotificationsForBudget operation: not authorized" >&2
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
  if [ "$NOTIF_MODE" = "null_type" ]; then
    printf '%s' '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":null},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}'
    exit 0
  fi
  if [ "$NOTIF_MODE" = "unknown_type" ]; then
    printf '%s' '{"Notifications":[{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"UNKNOWN"},{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"}]}'
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
    ACTUAL\|*) SUB_IS_ACTUAL=1 ;;
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
  printf '{"Certificate":{"CertificateArn":"%s","DomainName":"launchcrew.summitsingh.com","SubjectAlternativeNames":["launchcrew.summitsingh.com"],"Status":"%s","Type":"AMAZON_ISSUED","Options":{"Export":"ENABLED"}}}\\n' "$CERT_ARN_VALUE" "$CERT_STATUS"
  exit 0
fi
if [ "$1" = "ce" ] && [ "$2" = "list-cost-allocation-tags" ]; then
  printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Active"}]}\\n'; exit 0
fi
echo "fake-aws: unexpected call: $*" >&2
exit 2
"""


class PhaseCHarness(unittest.TestCase):
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

    def run_phase(self, args, extra_env=None, params_overrides=None):
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
            token_file = Path(tmp) / "token"
            adopt_file = Path(tmp) / "adopt"
            journals = Path(tmp) / "journals"
            journals.mkdir()
            given = {"AcmCertificateArn": CERT_ARN}
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
            params.write_text(json.dumps(
                [{"ParameterKey": key, "ParameterValue": value}
                 for key, value in sorted(given.items())]), encoding="utf-8")
            foundation_params = Path(tmp) / "foundation-params.json"
            foundation_params.write_text(json.dumps(
                [{"ParameterKey": "BudgetLimitUsd", "ParameterValue": "45"},
                 {"ParameterKey": "BudgetNotifyEmail",
                  "ParameterValue": NOTIFY_EMAIL}]), encoding="utf-8")
            env = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                        "AWS_SESSION_TOKEN"):
                env.pop(key, None)
            env["AWS_BIN"] = str(fake)
            env["FAKE_AWS_LOG"] = str(log)
            env["FAKE_COUNT_FILE"] = str(count)
            env["FAKE_TASKDEF_FILE"] = str(taskdefs)
            env["FAKE_TOKEN_FILE"] = str(token_file)
            env["FAKE_ADOPT_FILE"] = str(adopt_file)
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
            full = list(args) + [
                "--parameters-file", str(params),
                "--foundation-stack-name", FOUNDATION_STACK,
                "--foundation-parameters-file", str(foundation_params),
                "--prereqs-stack-name", PREREQS_STACK,
                "--launch-journal-dir", str(journals),
            ]
            result = subprocess.run(
                [str(BOOTSTRAP), *full], capture_output=True, text=True,
                env=env, check=False)
            calls = [line for line in log.read_text(encoding="utf-8").splitlines()
                     if line.strip()]
            journal_docs = {}
            for entry in sorted(journals.iterdir()):
                if entry.is_file() and entry.suffix == ".json":
                    journal_docs[entry.name] = {
                        "mode": stat.S_IMODE(entry.stat().st_mode),
                        "doc": json.loads(entry.read_text(encoding="utf-8")),
                    }
            return result, calls, journal_docs

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

    def run_calls(self, calls):
        return [call for call in calls if "run-task" in call]


class SdkTaskShapeTests(PhaseCHarness):
    def test_init_proves_entrypoint_command_env_and_zero_injection(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"])
        self.assertEqual(result.returncode, 0,
                         msg=result.stdout + result.stderr)
        self.assertIn("EntryPoint, Command, env, roles, zero secret injection",
                      result.stdout)
        self.assertTrue(any("get-role" in call for call in calls))
        self.assertTrue(any("describe-db-instances" in call for call in calls))
        runs = self.run_calls(calls)
        self.assertEqual(len(runs), 1)
        self.assertIn("launchcrew-demo-sdkinit", runs[0])
        self.assertIn("--client-token", runs[0])
        self.assertIn("--started-by", runs[0])

    def test_default_entrypoint_refused_before_run(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_SDK": "entrypoint"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ENTRYPOINT_MISMATCH", result.stdout + result.stderr)
        self.assertEqual(self.run_calls(calls), [])
        self.assertEqual(journals, {})

    def test_binder_command_refused_before_run(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_SDK": "command"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("COMMAND_MISMATCH", result.stdout + result.stderr)
        self.assertEqual(self.run_calls(calls), [])

    def test_secret_injection_refused_before_run(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_SDK": "injection"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_INJECTION_REFUSED", result.stdout + result.stderr)
        self.assertEqual(self.run_calls(calls), [])

    def test_env_drift_refused_before_run(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "material"],
            extra_env={"FAKE_SDK": "env"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ENV_MISMATCH", result.stdout + result.stderr)
        self.assertEqual(self.run_calls(calls), [])

    def test_material_uses_verify_material_command(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "material"])
        self.assertEqual(result.returncode, 0,
                         msg=result.stdout + result.stderr)
        self.assertIn("zero Put and zero Export", result.stdout)
        runs = self.run_calls(calls)
        self.assertEqual(len(runs), 1)
        self.assertIn("launchcrew-demo-sdkmaterial", runs[0])


class PhysicalRoleTests(PhaseCHarness):
    def test_physical_role_mismatch_refuses_before_run(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "dbroles"],
            extra_env={"FAKE_MODE": "role_mismatch"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EXEC_ROLE_MISMATCH", result.stdout + result.stderr)
        self.assertEqual(self.run_calls(calls), [])
        self.assertEqual(journals, {})

    def test_roles_resolve_via_get_role_with_physical_name(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "dbroles"])
        self.assertEqual(result.returncode, 0,
                         msg=result.stdout + result.stderr)
        get_roles = [call for call in calls if "get-role" in call]
        self.assertTrue(get_roles)
        self.assertTrue(any("BootstrapExecutionRole-physical" in call
                            for call in get_roles))
        self.assertTrue(any("BootstrapTaskRole-physical" in call
                            for call in get_roles))
        self.assertFalse(any("--role-name BootstrapExecutionRole " in call
                             for call in get_roles))

    def test_ownership_fails_before_any_run_or_journal(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_MODE": "secret_tag_mismatch"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused", result.stderr)
        self.assertEqual(self.run_calls(calls), [])
        self.assertEqual(journals, {})
        self.assertFalse(any("list-tasks" in call for call in calls))


class ControllerOrderTests(PhaseCHarness):
    def test_all_orders_init_material_before_binder(self):
        result, calls, _ = self.run_phase(self.base_args())
        self.assertEqual(result.returncode, 0,
                         msg=result.stdout + result.stderr)
        self.assertIn("Prereqs ready", result.stdout)
        self.assertIn("Paid gates verified", result.stdout)
        runs = self.run_calls(calls)
        order = []
        for call in runs:
            for logical in ("sdkinit", "sdkmaterial", "bootstrap",
                            "migration", "verify"):
                if f"launchcrew-demo-{logical}" in call:
                    order.append(logical)
        self.assertEqual(order, ["sdkinit", "sdkmaterial", "bootstrap",
                                 "migration", "verify"])

    def test_staged_resume_each_phase_reverifies(self):
        for phase in ("init", "material", "dbroles"):
            with self.subTest(phase=phase):
                result, calls, _ = self.run_phase(
                    [*self.base_args(), "--phase", phase])
                self.assertEqual(result.returncode, 0,
                                 msg=result.stdout + result.stderr)
                self.assertIn("Paid gates verified", result.stdout)
                self.assertEqual(len(self.run_calls(calls)), 1)

    def test_standalone_enable_runs_only_readonly_verifies(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "enable"])
        self.assertEqual(result.returncode, 0,
                         msg=result.stdout + result.stderr)
        runs = self.run_calls(calls)
        self.assertEqual(len(runs), 2)
        self.assertIn("launchcrew-demo-sdkmaterial", runs[0])
        self.assertIn("launchcrew-demo-verify", runs[1])
        joined = " ".join(calls)
        self.assertNotIn("launchcrew-demo-sdkinit:1 --launch-type", joined)
        self.assertNotIn("launchcrew-demo-migration:1 --launch-type", joined)
        self.assertNotIn("launchcrew-demo-bootstrap:1 --launch-type", joined)
        self.assertNotIn("put-secret-value", joined)
        self.assertNotIn("export-certificate", joined)
        self.assertNotIn("GetSecretValue", joined)

    def test_pending_cert_stops_all_without_ready_claim(self):
        result, calls, _ = self.run_phase(
            self.base_args(), extra_env={"FAKE_CERT": "pending"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("PENDING", combined)
        self.assertIn("No ready claim", combined)
        self.assertNotIn("Prereqs ready", result.stdout)
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertEqual(self.run_calls(calls), [])


class FoundationBudgetTests(PhaseCHarness):
    def test_missing_foundation_refuses_paid_phase(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_FOUNDATION": "missing"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foundation stack absent",
                      result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))

    def test_wrong_alert_threshold_refuses_with_no_deploy_or_run(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "enable"],
            extra_env={"FAKE_NOTIF": "wrong"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("ACTUAL 80 plus FORECASTED 100", combined)
        self.assertIn("UNVERIFIED", combined)
        self.assertFalse(any("EnableServices=true" in call for call in calls))
        self.assertEqual(self.run_calls(calls), [])

    def test_pending_sns_refuses_paid_phase(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_SNS": "pending"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no confirmed exact",
                      result.stdout + result.stderr)
        self.assertEqual(self.run_calls(calls), [])

    def test_app_params_with_budget_keys_refused(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "infra"],
            params_overrides={"BudgetLimitUsd": "45"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foundation-owned budget key",
                      result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))


class AmbiguousLaunchTests(PhaseCHarness):
    def test_empty_remains_ambiguous_with_no_resend(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_RUN": "fail", "FAKE_RECOVER": "none"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("ambiguous", combined)
        self.assertIn("empty remains AMBIGUOUS", combined)
        self.assertNotIn("confirms zero tasks", combined)
        self.assertNotIn("nothing started with token", combined)
        self.assertIn("No automatic resend", combined)
        self.assertIn("no new token from absence", combined)
        self.assertNotIn("nothing started beyond this point", combined)
        self.assertEqual(len(self.run_calls(calls)), 1)
        self.assertTrue(any("list-tasks" in call for call in calls))
        self.assertTrue(any("--no-paginate" in call and "list-tasks" in call for call in calls))
        self.assertTrue(any("--cli-input-json" in call and "list-tasks" in call for call in calls))
        self.assertFalse(any("--next-token" in call for call in calls))
        decoded = [call for call in calls if "INPUT_JSON_LIST" in call]
        self.assertTrue(any("desiredStatus" in call and "STOPPED" in call for call in decoded))
        self.assertTrue(any("startedBy" in call for call in decoded))
        self.assertFalse(any("startedBy" in call and "desiredStatus" in call for call in decoded))
        self.assertEqual(len(journals), 1)
        doc = next(iter(journals.values()))["doc"]
        self.assertEqual(doc["outcome"], "ambiguous_empty")
        self.assertEqual(doc["phase"], "init")

    def test_single_verified_task_adopted_with_no_resend(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_RUN": "fail", "FAKE_RECOVER": "adopt"})
        self.assertEqual(result.returncode, 0,
                         msg=result.stdout + result.stderr)
        self.assertIn("adopted for terminal proof", result.stdout)
        self.assertEqual(len(self.run_calls(calls)), 1)
        self.assertEqual(len(journals), 1)
        doc = next(iter(journals.values()))["doc"]
        self.assertEqual(doc["outcome"], "complete")
        self.assertTrue(doc["task_arn"])

    def test_multiple_tasks_stop_without_terminal_claim(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_RUN": "fail", "FAKE_RECOVER": "multiple"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("ambiguous", combined)
        self.assertIn("No automatic resend", combined)
        self.assertNotIn("terminal proof", combined)
        self.assertEqual(len(self.run_calls(calls)), 1)
        doc = next(iter(journals.values()))["doc"]
        self.assertEqual(doc["outcome"], "ambiguous_multiple")

    def test_wrong_identity_stops_without_adoption(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_RUN": "fail", "FAKE_RECOVER": "wrong"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("WRONG_TASKDEF", combined)
        self.assertIn("No automatic resend", combined)
        self.assertEqual(len(self.run_calls(calls)), 1)
        doc = next(iter(journals.values()))["doc"]
        self.assertEqual(doc["outcome"], "ambiguous_unconfirmed")

    def test_journal_is_mode_600_metadata_only(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"])
        self.assertEqual(result.returncode, 0,
                         msg=result.stdout + result.stderr)
        self.assertEqual(len(journals), 1)
        entry = next(iter(journals.values()))
        self.assertEqual(entry["mode"], 0o600)
        doc = entry["doc"]
        for key in ("version", "stack", "phase", "label",
                    "taskdef_logical", "taskdef_arn", "cluster",
                    "client_token", "config_digest", "region", "account",
                    "outcome", "task_arn"):
            self.assertIn(key, doc)
        self.assertEqual(doc["outcome"], "complete")
        self.assertTrue(doc["client_token"].startswith("lc-"))
        self.assertTrue(doc["config_digest"])
        blob = json.dumps(doc)
        self.assertNotIn(":secret:", blob)
        self.assertNotIn("password", blob.lower())
        self.assertNotIn("database-url", blob.lower())
        self.assertNotIn("tls-cert", blob.lower())
        calls_blob = " ".join(calls)
        self.assertNotIn("GetSecretValue", calls_blob)
        self.assertNotIn("PutSecretValue", calls_blob)
        self.assertNotIn("ExportCertificate", calls_blob)


class BudgetSubscriberTests(PhaseCHarness):
    def test_actual_subscriber_mismatch_refuses(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "enable"],
            extra_env={"FAKE_SUB": "mismatch_actual"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("ACTUAL_80", combined)
        self.assertIn("ACTUAL 80 plus FORECASTED 100", combined)
        self.assertIn("UNVERIFIED", combined)
        self.assertFalse(any("EnableServices=true" in call for call in calls))
        self.assertEqual(self.run_calls(calls), [])

    def test_forecasted_subscriber_mismatch_refuses(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "enable"],
            extra_env={"FAKE_SUB": "mismatch_forecasted"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("FORECASTED_100", combined)
        self.assertIn("ACTUAL 80 plus FORECASTED 100", combined)
        self.assertIn("UNVERIFIED", combined)
        self.assertEqual(self.run_calls(calls), [])

    def test_subscriber_auth_unreadable_refuses(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_SUB": "auth"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("subscribers unreadable", combined)
        self.assertIn("UNVERIFIED", combined)
        self.assertIn("DescribeSubscribersForNotification", combined)
        self.assertEqual(self.run_calls(calls), [])

    def test_subscriber_malformed_refuses(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_SUB": "malformed"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("subscribers unreadable", combined)
        self.assertIn("UNVERIFIED", combined)
        self.assertEqual(self.run_calls(calls), [])

    def test_duplicate_notification_refuses(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "enable"],
            extra_env={"FAKE_NOTIF": "duplicate"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("ACTUAL 80 plus FORECASTED 100", combined)
        self.assertIn("UNVERIFIED", combined)
        self.assertEqual(self.run_calls(calls), [])

    def test_paginated_ok_passes_with_two_subscriber_calls(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_NOTIF": "paginated_ok"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        subs = [call for call in calls if "describe-subscribers-for-notification" in call]
        self.assertEqual(len(subs), 2)
        self.assertTrue(all("--cli-input-json" in call for call in subs))
        self.assertTrue(all("--no-paginate" in call for call in subs))
        self.assertFalse(any("--next-token" in call for call in calls))
        notifs = [call for call in calls if "describe-notifications-for-budget" in call]
        self.assertEqual(len(notifs), 2)
        decoded = [call for call in calls if "INPUT_JSON_NOTIF" in call]
        self.assertEqual(len(decoded), 2)
        self.assertNotIn("NextToken", decoded[0])
        self.assertIn("page2", decoded[1])


class StoppedRecoveryTests(PhaseCHarness):
    def test_stopped_candidate_adopted_with_no_resend(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_RUN": "fail", "FAKE_RECOVER": "stopped_adopt"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("adopted for terminal proof", result.stdout)
        self.assertEqual(len(self.run_calls(calls)), 1)
        self.assertTrue(any("--no-paginate" in call and "list-tasks" in call for call in calls))
        self.assertFalse(any("--next-token" in call for call in calls))
        decoded = [call for call in calls if "INPUT_JSON_LIST" in call]
        self.assertTrue(any("desiredStatus" in call and "STOPPED" in call for call in decoded))
        self.assertFalse(any("startedBy" in call and "desiredStatus" in call for call in decoded))
        doc = next(iter(journals.values()))["doc"]
        self.assertEqual(doc["outcome"], "complete")

    def test_stopped_multiple_refuses(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_RUN": "fail", "FAKE_RECOVER": "stopped_multiple"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("ambiguous", combined)
        self.assertIn("No automatic resend", combined)
        self.assertEqual(len(self.run_calls(calls)), 1)
        doc = next(iter(journals.values()))["doc"]
        self.assertEqual(doc["outcome"], "ambiguous_multiple")

    def test_stopped_wrong_refuses_without_adoption(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_RUN": "fail", "FAKE_RECOVER": "stopped_wrong"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("ambiguous", combined)
        self.assertIn("No automatic resend", combined)
        self.assertEqual(len(self.run_calls(calls)), 1)
        doc = next(iter(journals.values()))["doc"]
        self.assertIn(doc["outcome"], ("ambiguous_empty", "ambiguous_unconfirmed"))


class CrashResumeTests(PhaseCHarness):
    def run_twice(self, phase, first_env, second_env, corrupt=None):
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
            token_file = Path(tmp) / "token"
            adopt_file = Path(tmp) / "adopt"
            journals = Path(tmp) / "journals"
            journals.mkdir()
            given = {"AcmCertificateArn": CERT_ARN}
            for flag, key in self.PARAM_KEYS.items():
                for pos, item in enumerate(self.base_args()):
                    if item == flag and pos + 1 < len(self.base_args()):
                        given[key] = self.base_args()[pos + 1]
            params = Path(tmp) / "params.json"
            params.write_text(json.dumps(
                [{"ParameterKey": k, "ParameterValue": v} for k, v in sorted(given.items())]),
                encoding="utf-8")
            foundation_params = Path(tmp) / "foundation-params.json"
            foundation_params.write_text(json.dumps(
                [{"ParameterKey": "BudgetLimitUsd", "ParameterValue": "45"},
                 {"ParameterKey": "BudgetNotifyEmail", "ParameterValue": NOTIFY_EMAIL}]),
                encoding="utf-8")
            env_base = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                env_base.pop(key, None)
            env_base["AWS_BIN"] = str(fake)
            env_base["FAKE_AWS_LOG"] = str(log)
            env_base["FAKE_COUNT_FILE"] = str(count)
            env_base["FAKE_TASKDEF_FILE"] = str(taskdefs)
            env_base["FAKE_TOKEN_FILE"] = str(token_file)
            env_base["FAKE_ADOPT_FILE"] = str(adopt_file)
            env_base["FAKE_CERT_ARN"] = CERT_ARN
            env_base["FAKE_DB_HOST"] = DB_HOST
            env_base["FAKE_TOPIC_ARN"] = TOPIC_ARN
            env_base["FAKE_NOTIFY_EMAIL"] = NOTIFY_EMAIL
            base = self.base_args()
            for table in (self.IMAGE_ENV, self.SECRET_ENV):
                for flag, name in table.items():
                    for pos, item in enumerate(base):
                        if item == flag and pos + 1 < len(base):
                            env_base[name] = base[pos + 1]
            full = [*base, "--phase", phase,
                    "--parameters-file", str(params),
                    "--foundation-stack-name", FOUNDATION_STACK,
                    "--foundation-parameters-file", str(foundation_params),
                    "--prereqs-stack-name", PREREQS_STACK,
                    "--launch-journal-dir", str(journals)]
            env1 = dict(env_base)
            env1.update(first_env or {})
            result1 = subprocess.run([str(BOOTSTRAP), *full], capture_output=True,
                                     text=True, env=env1, check=False)
            if corrupt is not None:
                corrupt(journals)
            env2 = dict(env_base)
            env2.update(second_env or {})
            result2 = subprocess.run([str(BOOTSTRAP), *full], capture_output=True,
                                     text=True, env=env2, check=False)
            calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
            total_runs = int(count.read_text(encoding="utf-8").strip() or "0")
            journal_docs = {}
            for entry in sorted(journals.iterdir()):
                if entry.is_file() and entry.suffix == ".json":
                    journal_docs[entry.name] = {
                        "mode": stat.S_IMODE(entry.stat().st_mode),
                        "doc": json.loads(entry.read_text(encoding="utf-8")),
                    }
            dir_mode = stat.S_IMODE(journals.stat().st_mode)
            temps = [entry.name for entry in journals.iterdir() if entry.name.startswith(".launch-journal-")]
            return result1, result2, calls, journal_docs, total_runs, dir_mode, temps

    def test_ambiguous_reentry_adopts_with_one_total_run(self):
        result1, result2, calls, journals, total, dir_mode, temps = self.run_twice(
            "init", {"FAKE_RUN": "fail", "FAKE_RECOVER": "none"},
            {"FAKE_RUN": "ok", "FAKE_RECOVER": "adopt"})
        self.assertNotEqual(result1.returncode, 0)
        self.assertEqual(result2.returncode, 0, msg=result2.stdout + result2.stderr)
        self.assertEqual(total, 1)
        self.assertIn("adopted for terminal proof", result2.stdout + result1.stdout)
        self.assertEqual(dir_mode, 0o700)
        self.assertEqual(temps, [])
        docs = [entry["doc"] for entry in journals.values() if entry["doc"].get("outcome") == "complete"]
        self.assertEqual(len(docs), 1)

    def test_success_reentry_preserves_one_shot_with_one_total_run(self):
        result1, result2, calls, journals, total, dir_mode, temps = self.run_twice(
            "init", {"FAKE_RUN": "ok"}, {"FAKE_RUN": "ok"})
        self.assertEqual(result1.returncode, 0, msg=result1.stdout + result1.stderr)
        self.assertEqual(result2.returncode, 0, msg=result2.stdout + result2.stderr)
        self.assertEqual(total, 1)
        self.assertIn("already complete", result2.stdout + result2.stderr)
        self.assertIn("no new run-task", result2.stdout + result2.stderr)

    def test_stopped_reentry_adopts_with_one_total_run(self):
        result1, result2, calls, journals, total, dir_mode, temps = self.run_twice(
            "init", {"FAKE_RUN": "fail", "FAKE_RECOVER": "none"},
            {"FAKE_RUN": "ok", "FAKE_RECOVER": "stopped_adopt"})
        self.assertNotEqual(result1.returncode, 0)
        self.assertEqual(result2.returncode, 0, msg=result2.stdout + result2.stderr)
        self.assertEqual(total, 1)

    def test_empty_reentry_remains_ambiguous_with_one_total_run(self):
        result1, result2, calls, journals, total, dir_mode, temps = self.run_twice(
            "init", {"FAKE_RUN": "fail", "FAKE_RECOVER": "none"},
            {"FAKE_RUN": "ok", "FAKE_RECOVER": "none"})
        self.assertNotEqual(result1.returncode, 0)
        self.assertNotEqual(result2.returncode, 0)
        combined = result2.stdout + result2.stderr
        self.assertIn("empty remains AMBIGUOUS", combined)
        self.assertEqual(total, 1)

    def test_changed_taskdef_refuses_without_new_run(self):
        other = 'arn:aws:ecs:us-east-1:111122223333:task'"-definition"'/launchcrew-demo-other:9'
        def corrupt(journals):
            for entry in journals.iterdir():
                if entry.is_file() and entry.name.endswith("-active.json"):
                    doc = json.loads(entry.read_text(encoding="utf-8"))
                    doc["taskdef_arn"] = other
                    entry.write_text(json.dumps(doc), encoding="utf-8")
                    entry.chmod(0o600)
        result1, result2, calls, journals, total, dir_mode, temps = self.run_twice(
            "init", {"FAKE_RUN": "ok"}, {"FAKE_RUN": "ok"}, corrupt=corrupt)
        self.assertEqual(result1.returncode, 0)
        self.assertNotEqual(result2.returncode, 0)
        combined = result2.stdout + result2.stderr
        self.assertIn("TASKDEF_MISMATCH", combined)
        self.assertIn("never auto fresh", combined)
        self.assertEqual(total, 1)


class StandalonePrereqTests(PhaseCHarness):
    def test_standalone_infra_pending_cert_stops_without_deploy(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "infra"],
            extra_env={"FAKE_CERT": "pending"})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("PENDING", combined)
        self.assertIn("No ready claim", combined)
        self.assertFalse(any("deploy " in call for call in calls))

    def test_standalone_infra_cert_mismatch_stops_without_deploy(self):
        other_cert = "arn:aws:acm:us-east-1:111122223333:certificate/ffffffff-ffff-ffff-ffff-ffffffffffff"
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "infra"],
            params_overrides={"AcmCertificateArn": other_cert})
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("AcmCertificateArn", combined)
        self.assertIn("cert B", combined)
        self.assertFalse(any("deploy " in call for call in calls))

    def test_standalone_infra_each_secret_mismatch_stops_without_deploy(self):
        other = "arn:aws:secretsmanager:us-east-1:111122223333:secret:other-secret-ZzZzZz"
        for key in ("RuntimeDbUrlSecretArn", "MigrationDbUrlSecretArn",
                    "MasterDbPasswordSecretArn", "TlsSecretArn"):
            with self.subTest(key=key):
                result, calls, _ = self.run_phase(
                    [*self.base_args(), "--phase", "infra"],
                    params_overrides={key: other})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("owned prereq ref", result.stdout + result.stderr)
                self.assertFalse(any("deploy " in call for call in calls))

    def test_standalone_infra_happy_owned_chain_passes(self):
        result, calls, _ = self.run_phase([*self.base_args(), "--phase", "infra"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Prereqs ready", result.stdout)
        self.assertTrue(any("deploy " in call and "EnableServices=false" in call for call in calls))


class ConcurrentOperationLockTests(PhaseCHarness):
    def test_two_invocations_same_dir_one_total_run(self):
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
            token_file = Path(tmp) / "token"
            token_file.write_text("", encoding="utf-8")
            adopt_file = Path(tmp) / "adopt"
            adopt_file.write_text("", encoding="utf-8")
            journals = Path(tmp) / "journals"
            journals.mkdir()
            given = {"AcmCertificateArn": CERT_ARN}
            base = self.base_args()
            for flag, key in self.PARAM_KEYS.items():
                for pos, item in enumerate(base):
                    if item == flag and pos + 1 < len(base):
                        given[key] = base[pos + 1]
            params = Path(tmp) / "params.json"
            params.write_text(json.dumps(
                [{"ParameterKey": k, "ParameterValue": v} for k, v in sorted(given.items())]),
                encoding="utf-8")
            foundation_params = Path(tmp) / "foundation-params.json"
            foundation_params.write_text(json.dumps(
                [{"ParameterKey": "BudgetLimitUsd", "ParameterValue": "45"},
                 {"ParameterKey": "BudgetNotifyEmail", "ParameterValue": NOTIFY_EMAIL}]),
                encoding="utf-8")
            env_base = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                env_base.pop(key, None)
            env_base["AWS_BIN"] = str(fake)
            env_base["FAKE_AWS_LOG"] = str(log)
            env_base["FAKE_COUNT_FILE"] = str(count)
            env_base["FAKE_TASKDEF_FILE"] = str(taskdefs)
            env_base["FAKE_TOKEN_FILE"] = str(token_file)
            env_base["FAKE_ADOPT_FILE"] = str(adopt_file)
            env_base["FAKE_CERT_ARN"] = CERT_ARN
            env_base["FAKE_DB_HOST"] = DB_HOST
            env_base["FAKE_TOPIC_ARN"] = TOPIC_ARN
            env_base["FAKE_NOTIFY_EMAIL"] = NOTIFY_EMAIL
            env_base["FAKE_RUN"] = "ok"
            env_base["FAKE_RUN_DELAY"] = "2"
            for table in (self.IMAGE_ENV, self.SECRET_ENV):
                for flag, name in table.items():
                    for pos, item in enumerate(base):
                        if item == flag and pos + 1 < len(base):
                            env_base[name] = base[pos + 1]
            full = [*base, "--phase", "init",
                    "--parameters-file", str(params),
                    "--foundation-stack-name", FOUNDATION_STACK,
                    "--foundation-parameters-file", str(foundation_params),
                    "--prereqs-stack-name", PREREQS_STACK,
                    "--launch-journal-dir", str(journals)]
            proc1 = subprocess.Popen(
                [str(BOOTSTRAP), *full], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=dict(env_base))
            proc2 = subprocess.Popen(
                [str(BOOTSTRAP), *full], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=dict(env_base))
            try:
                out1, err1 = proc1.communicate(timeout=90)
                out2, err2 = proc2.communicate(timeout=90)
            except subprocess.TimeoutExpired:
                proc1.kill()
                proc2.kill()
                raise
            calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
            runs = [call for call in calls if "run-task" in call]
            self.assertEqual(len(runs), 1)
            taskdef_lines = [line for line in taskdefs.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(taskdef_lines), 1)
            docs = {}
            for entry in sorted(journals.iterdir()):
                if entry.is_file() and entry.suffix == ".json":
                    docs[entry.name] = {
                        "mode": stat.S_IMODE(entry.stat().st_mode),
                        "doc": json.loads(entry.read_text(encoding="utf-8")),
                    }
            self.assertEqual(len(docs), 1)
            entry = next(iter(docs.values()))
            self.assertEqual(entry["mode"], 0o600)
            self.assertEqual(entry["doc"]["outcome"], "complete")
            self.assertTrue(entry["doc"]["client_token"].startswith("lc-"))
            locks = [e for e in journals.iterdir() if e.name.endswith(".lock")]
            self.assertEqual(locks, [])
            self.assertTrue(proc1.returncode == 0 or proc2.returncode == 0)


class EcsPaginationTests(PhaseCHarness):
    def test_running_paginated_two_pages_with_token_forwarding(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_RUN": "fail", "FAKE_RECOVER": "running_paginated"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("adopted for terminal proof", result.stdout)
        self.assertEqual(len(self.run_calls(calls)), 1)
        lists = [call for call in calls if "list-tasks" in call]
        self.assertGreaterEqual(len(lists), 3)
        for call in lists:
            self.assertIn("--no-paginate", call)
            self.assertIn("--cli-input-json", call)
            self.assertNotIn("--next-token", call)
        decoded = [call for call in calls if "INPUT_JSON_LIST" in call]
        self.assertGreaterEqual(len(decoded), 3)
        self.assertTrue(any("nextToken" in call and "page2" in call for call in decoded))
        self.assertFalse(any("NextToken" in call for call in decoded))
        for entry in decoded:
            self.assertIn("launchcrew-demo", entry)
            self.assertIn("maxResults", entry)

    def test_stopped_paginated_two_pages_with_adoption(self):
        result, calls, journals = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_RUN": "fail", "FAKE_RECOVER": "stopped_paginated"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("adopted for terminal proof", result.stdout)
        self.assertEqual(len(self.run_calls(calls)), 1)
        decoded = [call for call in calls if "INPUT_JSON_LIST" in call]
        self.assertTrue(any("desiredStatus" in call and "STOPPED" in call for call in decoded))
        self.assertTrue(any("nextToken" in call and "page2" in call for call in decoded))
        self.assertFalse(any("startedBy" in call and "desiredStatus" in call for call in decoded))
        doc = next(iter(journals.values()))["doc"]
        self.assertEqual(doc["outcome"], "complete")


class OptionalThresholdTypeTests(PhaseCHarness):
    def test_missing_threshold_type_allowed(self):
        result, calls, _ = self.run_phase(
            [*self.base_args(), "--phase", "init"],
            extra_env={"FAKE_NOTIF": "missing_type"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_explicit_bad_threshold_types_refused(self):
        for mode in ("absolute", "null_type", "unknown_type"):
            with self.subTest(mode=mode):
                result, calls, _ = self.run_phase(
                    [*self.base_args(), "--phase", "init"],
                    extra_env={"FAKE_NOTIF": mode})
                self.assertNotEqual(result.returncode, 0, msg=mode)
                self.assertIn("UNVERIFIED", result.stdout + result.stderr, msg=mode)
                self.assertEqual(self.run_calls(calls), [], msg=mode)


class OperationLockSourceTests(PhaseCHarness):
    def test_exclusive_lock_present_with_owned_release(self):
        code = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("acquire_operation_lock", code)
        self.assertIn("release_operation_lock", code)
        self.assertIn(".lock", code)
        self.assertIn("stale", code)
        self.assertIn("bounded wait", code)
        self.assertIn("JOURNAL_CREATED", code)
        self.assertNotIn("--next-token", code)


if __name__ == "__main__":
    unittest.main()

