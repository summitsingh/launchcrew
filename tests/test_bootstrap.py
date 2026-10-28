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
  STATUS="CREATE_COMPLETE"
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
  printf '{"Stacks":[{"StackId":"%s","StackStatus":"%s","Tags":[{"Key":"Project","Value":"%s"},{"Key":"Environment","Value":"demo"}],"Parameters":[{"ParameterKey":"EnableServices","ParameterValue":"false"}]}]}\\n' "$STACKID" "$STATUS" "$PROJECT"
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
  NOTIF_NEXT=""
  NOTIF_PREV=""
  for NOTIF_ARG in "$@"; do
    if [ "$NOTIF_PREV" = "--next-token" ]; then NOTIF_NEXT="$NOTIF_ARG"; fi
    NOTIF_PREV="$NOTIF_ARG"
  done
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
  SUB_TOPIC="${FAKE_TOPIC_ARN:-arn:aws:sns:us-east-1:111122223333:launchcrew-foundation-BudgetTopic-ABC123}"
  SUB_IS_ACTUAL=0
  case "$*" in
    *ACTUAL*) SUB_IS_ACTUAL=1 ;;
  esac
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
  LIST_TOKEN=""
  LIST_DESIRED=""
  LIST_PREV=""
  for LIST_ARG in "$@"; do
    if [ "$LIST_PREV" = "--started-by" ]; then LIST_TOKEN="$LIST_ARG"; fi
    if [ "$LIST_PREV" = "--desired-status" ]; then LIST_DESIRED="$LIST_ARG"; fi
    LIST_PREV="$LIST_ARG"
  done
  if [ -n "$LIST_TOKEN" ] && [ -n "$LIST_DESIRED" ]; then
    echo "An error occurred (InvalidParameterException) when calling the ListTasks operation: startedBy and desiredStatus cannot be combined" >&2
    exit 254
  fi
  if [ -n "$LIST_TOKEN" ]; then printf '%s' "$LIST_TOKEN" >"${FAKE_TOKEN_FILE:-/dev/null}" 2>/dev/null || true; fi
  printf '{"taskArns":[]}\\n'
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
    *"imageDigest"*)
      if [ "$MODE" = "image_digest_none" ]; then printf 'None\\n'; exit 0; fi
      printf 'sha256:abc123\\n'; exit 0 ;;
    *"failures"*)
      if [ "$MODE" = "image_failures" ]; then printf '1\\n'; exit 0; fi
      printf '0\\n'; exit 0 ;;
  esac
  printf '{"images":[{"imageDigest":"sha256:abc123"}],"failures":[]}\\n'
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
  printf '%s|%s\\n' "$TASKARN" "$TASKDEF" >>"${FAKE_TASKDEF_FILE:-/dev/null}" 2>/dev/null || true
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
  LAST="$(tail -n 1 "${FAKE_TASKDEF_FILE:-/dev/null}" 2>/dev/null || true)"
  TASKARN="${LAST%%|*}"
  TASKDEF="${LAST#*|}"
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
  STARTED_BY=""
  if [ -n "${FAKE_TOKEN_FILE:-}" ] && [ -f "$FAKE_TOKEN_FILE" ]; then
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
  if [ "$MODE" = "enable_wrong" ]; then printf '2\\t0\\n'; exit 0; fi
  printf '1\\t1\\n'; exit 0
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
                      foundation_params_raw=None):
        import json as _json
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
            created = Path(tmp) / "created"
            journals = Path(tmp) / "journals"
            journals.mkdir()
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
            [*self.minimal_infra_args(), "--phase", "infra"], mode="stack_missing")
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
        deploy_false = next(i for i, call in enumerate(calls)
                            if "deploy " in call and "EnableServices=false" in call)
        first_run = next(i for i, call in enumerate(calls) if "run-task" in call)
        deploy_true = next(i for i, call in enumerate(calls)
                           if "deploy " in call and "EnableServices=true" in call)
        self.assertLess(deploy_false, first_run)
        self.assertLess(first_run, deploy_true)
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
        self.assertTrue(any("--desired-status STOPPED" in call for call in calls))
        self.assertFalse(any("--started-by" in call and "--desired-status" in call for call in calls))
        runs = [call for call in calls if "run-task" in call]
        self.assertEqual(len(runs), 1)
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_enable_alone_reproves_images_bindings_and_verify(self):
        result, calls = self.run_bootstrap([*self.base_args(), "--phase", "enable"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP COMPLETE", result.stdout)
        joined = " ".join(calls)
        self.assertIn("EnableServices=true", joined)
        self.assertIn("batch-get-image", joined)
        self.assertIn("launchcrew-demo-verify", joined)
        self.assertIn("launchcrew-demo-sdkmaterial", joined)
        self.assertNotIn("launchcrew-demo-migration:1 --launch-type", joined)
        self.assertNotIn("launchcrew-demo-bootstrap:1 --launch-type", joined)
        self.assertNotIn("launchcrew-demo-sdkinit:1 --launch-type", joined)
        runs = [call for call in calls if "run-task" in call]
        self.assertEqual(len(runs), 2)
        material_run = next(i for i, call in enumerate(runs)
                            if "launchcrew-demo-sdkmaterial" in call)
        verify_run = next(i for i, call in enumerate(runs)
                          if "launchcrew-demo-verify" in call)
        self.assertLess(material_run, verify_run)

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
        self.assertTrue(any("deploy " in call and "EnableServices=false" in call for call in calls))
        self.assertFalse(any("run-task" in call for call in calls))

    def test_single_phase_does_not_enable(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "migrate"])
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any("EnableServices=true" in call for call in calls))

    def test_enable_refuses_when_verify_proof_fails(self):
        result, calls = self.run_bootstrap(
            [*self.base_args(), "--phase", "enable"], mode="verify_fail")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("EXIT_NONZERO", combined)
        self.assertFalse(any("EnableServices=true" in call for call in calls))
        self.assertNotIn("BOOTSTRAP COMPLETE", result.stdout)

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
            [*self.minimal_infra_args(), "--phase", "infra"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        ce_calls = [call for call in calls if "list-cost-allocation-tags" in call]
        self.assertEqual(len(ce_calls), 1)
        self.assertIn("--tag-keys Project", ce_calls[0])
        self.assertIn("--type UserDefined", ce_calls[0])
        self.assertIn(REGION, ce_calls[0])
        self.assertIn("status Active", result.stdout)
        self.assertTrue(any("deploy " in call for call in calls))

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
        result, calls = self.run_bootstrap([*self.base_args(), "--phase", "enable"])
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
        self.assertIn("owns no budget", self.text)

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


if __name__ == "__main__":
    unittest.main()
