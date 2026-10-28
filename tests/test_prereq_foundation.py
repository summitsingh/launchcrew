"""Offline foundation and prereqs tests with a fake AWS fixture.

No test contacts AWS. The fake AWS script logs calls and returns canned
responses shaped like real APIs. Dry runs make zero calls. Confirm paths
verify caller, stack tags, StackId, CE Active, exact SNS subscription,
and expiry before any paid deploy, then handle pending CREATE_IN_PROGRESS
with a private receipt and bounded CNAME output, never secret values.
"""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

BOOTSTRAP = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "bootstrap.sh"
FOUNDATION_TEMPLATE = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "foundation.yaml"
PREREQS_TEMPLATE = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "prereqs.yaml"

ACCOUNT = "111122223333"
REGION = "us-east-1"
FOUNDATION_STACK = "launchcrew-foundation"
PREREQS_STACK = "launchcrew-prereqs"
FAKE_EMAIL = "owner" + "@" + "example.test"
TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCOUNT}:launchcrew-foundation-BudgetTopic-ABC123"
SUB_ARN = f"{TOPIC_ARN}:12345678-90ab-cdef-1234-567890abcdef"
SECRET_MASTER = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-master-AbCd01"
SECRET_RUNTIME = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-runtime-EfGh02"
SECRET_MIGRATION = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-migration-IjKl03"
SECRET_TLS = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-tls-MnOp04"
CERT_ARN = f"arn:aws:acm:{REGION}:{ACCOUNT}:certificate/12345678-90ab-cdef-1234-567890abcde1"
EXPECTED_DOMAIN = "launchcrew.summitsingh.com"
VALIDATION_NAME = "_abc123.acm-validations.aws"
VALIDATION_VALUE = "_def456.acm-validations.aws"

FAKE_AWS = """#!/bin/sh
LOG="${FAKE_AWS_LOG:-/dev/null}"
printf '%s\\n' "$*" >>"$LOG"
MODE="${FAKE_MODE:-success}"
if [ "$1" = "sts" ] && [ "$2" = "get-caller-identity" ]; then
  printf '%s\\n' "${FAKE_CALLER:-111122223333}"
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
    inactive) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Inactive"}]}\\n'; exit 0 ;;
    absent) printf '{"CostAllocationTags":[]}\\n'; exit 0 ;;
    duplicate) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Active"},{"TagKey":"Project","Type":"UserDefined","Status":"Inactive"}]}\\n'; exit 0 ;;
    wrongtype) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"AWSGenerated","Status":"Active"}]}\\n'; exit 0 ;;
    mixed) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Active"},{"TagKey":"Project","Type":"AWSGenerated","Status":"Active"}]}\\n'; exit 0 ;;
    nonobject) printf '[{"TagKey":"Project","Type":"UserDefined","Status":"Active"}]\\n'; exit 0 ;;
    unknown) printf '{"CostAllocationTags":[{"TagKey":"Project","Type":"UserDefined","Status":"Pending"}]}\\n'; exit 0 ;;
    *) echo "fake-aws: unknown FAKE_CE: $CE_MODE" >&2; exit 2 ;;
  esac
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
    *) echo "fake-aws: unknown FAKE_BUDGET: $BUDGET_MODE" >&2; exit 2 ;;
  esac
  printf '{"Budget":{"BudgetName":"launchcrew-demo","BudgetType":"COST","TimeUnit":"MONTHLY","FilterExpression":%s}}\\n' "$FILTER"
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
  NOTIF_TOPIC="${FAKE_TOPIC_ARN:-arn:aws:sns:us-east-1:111122223333:launchcrew-foundation-BudgetTopic-ABC123}"
  if [ "$NOTIF_MODE" = "missing" ]; then
    printf '{"NotificationsWithSubscribers":[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"SNS","Address":"%s"}]}]}\\n' "$NOTIF_TOPIC"
    exit 0
  fi
  if [ "$NOTIF_MODE" = "wrong" ]; then
    printf '{"NotificationsWithSubscribers":[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":50,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"SNS","Address":"%s"}]},{"Notification":{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"SNS","Address":"%s"}]}]}\\n' "$NOTIF_TOPIC" "$NOTIF_TOPIC"
    exit 0
  fi
  printf '{"NotificationsWithSubscribers":[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"SNS","Address":"%s"}]},{"Notification":{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"SNS","Address":"%s"}]}]}\\n' "$NOTIF_TOPIC" "$NOTIF_TOPIC"
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stacks" ]; then
  STACK=""
  PREV=""
  for ARG in "$@"; do
    if [ "$PREV" = "--stack-name" ]; then STACK="$ARG"; fi
    PREV="$ARG"
  done
  if [ "$MODE" = "stack_auth" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeStacks operation: not authorized" >&2
    exit 254
  fi
  if [ "$MODE" = "stack_other_error" ]; then
    echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Rate exceeded" >&2
    exit 254
  fi
  if [ "$STACK" = "launchcrew-foundation" ]; then
    if [ "$MODE" = "foundation_missing" ]; then
      if [ -z "$FAKE_FOUNDATION_CREATED_FILE" ] || [ ! -f "$FAKE_FOUNDATION_CREATED_FILE" ]; then
        echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id launchcrew-foundation does not exist" >&2
        exit 254
      fi
    fi
    STATUS="${FAKE_FOUNDATION_STATUS:-CREATE_COMPLETE}"
    PROJECT="${FAKE_PROJECT:-LaunchCrew}"
    STACKID="arn:aws:cloudformation:us-east-1:111122223333:stack/launchcrew-foundation/abc123"
    if [ "$MODE" = "tag_mismatch" ]; then PROJECT="Other"; fi
    if [ "$MODE" = "stack_id_mismatch" ]; then
      STACKID="arn:aws:cloudformation:us-east-1:999988887777:stack/launchcrew-foundation/abc123"
    fi
    case "$*" in
      *"StackStatus"*) printf '%s\\n' "$STATUS"; exit 0 ;;
    esac
    printf '{"Stacks":[{"StackId":"%s","StackStatus":"%s","Tags":[{"Key":"Project","Value":"%s"},{"Key":"Environment","Value":"demo"}]}]}\\n' "$STACKID" "$STATUS" "$PROJECT"
    exit 0
  fi
  if [ "$STACK" = "launchcrew-prereqs" ]; then
    if [ "$MODE" = "prereqs_missing" ]; then
      if [ -z "$FAKE_PREREQS_CREATED_FILE" ] || [ ! -f "$FAKE_PREREQS_CREATED_FILE" ]; then
        echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id launchcrew-prereqs does not exist" >&2
        exit 254
      fi
    fi
    STATUS="${FAKE_PREREQS_STATUS:-CREATE_COMPLETE}"
    PROJECT="${FAKE_PROJECT:-LaunchCrew}"
    STACKID="arn:aws:cloudformation:us-east-1:111122223333:stack/launchcrew-prereqs/def456"
    if [ "$MODE" = "tag_mismatch" ]; then PROJECT="Other"; fi
    if [ "$MODE" = "prereqs_id_mismatch" ]; then
      STACKID="arn:aws:cloudformation:us-east-1:999988887777:stack/launchcrew-prereqs/def456"
    fi
    case "$*" in
      *"StackStatus"*) printf '%s\\n' "$STATUS"; exit 0 ;;
    esac
    printf '{"Stacks":[{"StackId":"%s","StackStatus":"%s","Tags":[{"Key":"Project","Value":"%s"},{"Key":"Environment","Value":"demo"}]}]}\\n' "$STACKID" "$STATUS" "$PROJECT"
    exit 0
  fi
  echo "fake-aws: unexpected describe-stacks stack: $STACK" >&2
  exit 2
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "describe-stack-resource" ]; then
  LOGICAL=""
  PREV=""
  for ARG in "$@"; do
    if [ "$PREV" = "--logical-resource-id" ]; then LOGICAL="$ARG"; fi
    PREV="$ARG"
  done
  if [ "${FAKE_RESOURCE_MISSING:-0}" = "1" ]; then
    case "$LOGICAL" in
      MasterSecret|RuntimeSecret|MigrationSecret|TlsSecret|DemoCertificate)
        printf 'None\\n'
        exit 0 ;;
    esac
  fi
  if [ "$MODE" = "topic_mismatch" ] && [ "$LOGICAL" = "BudgetTopic" ]; then
    printf 'arn:aws:sns:us-east-1:999988887777:other-topic\\n'
    exit 0
  fi
  if [ "$MODE" = "secret_arn_mismatch" ]; then
    printf 'arn:aws:secretsmanager:us-east-1:111122223333:secret:other-secret-ZzZzZz\\n'
    exit 0
  fi
  if [ "$MODE" = "cert_arn_mismatch" ] && [ "$LOGICAL" = "DemoCertificate" ]; then
    printf 'arn:aws:acm:eu-west-1:111122223333:certificate/00000000-0000-0000-0000-000000000000\\n'
    exit 0
  fi
  case "$LOGICAL" in
    BudgetTopic) printf '%s\\n' "${FAKE_TOPIC_ARN:-arn:aws:sns:us-east-1:111122223333:launchcrew-foundation-BudgetTopic-ABC123}"; exit 0 ;;
    MasterSecret) printf '%s\\n' "${FAKE_MASTER_ARN:-arn:aws:secretsmanager:us-east-1:111122223333:secret:launchcrew-master-AbCd01}"; exit 0 ;;
    RuntimeSecret) printf '%s\\n' "${FAKE_RUNTIME_ARN:-arn:aws:secretsmanager:us-east-1:111122223333:secret:launchcrew-runtime-EfGh02}"; exit 0 ;;
    MigrationSecret) printf '%s\\n' "${FAKE_MIGRATION_ARN:-arn:aws:secretsmanager:us-east-1:111122223333:secret:launchcrew-migration-IjKl03}"; exit 0 ;;
    TlsSecret) printf '%s\\n' "${FAKE_TLS_ARN:-arn:aws:secretsmanager:us-east-1:111122223333:secret:launchcrew-tls-MnOp04}"; exit 0 ;;
    DemoCertificate) printf '%s\\n' "${FAKE_CERT_ARN:-arn:aws:acm:us-east-1:111122223333:certificate/12345678-90ab-cdef-1234-567890abcde1}"; exit 0 ;;
  esac
  echo "fake-aws: unexpected resource lookup: $*" >&2
  exit 2
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "deploy" ]; then
  case "$*" in
    *"--parameter-file"*) echo "Unknown options: --parameter-file" >&2; exit 2 ;;
  esac
  if [ -n "$FAKE_FOUNDATION_CREATED_FILE" ]; then : >"$FAKE_FOUNDATION_CREATED_FILE" 2>/dev/null || true; fi
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "create-stack" ]; then
  case "$*" in
    *"Project=LaunchCrew"*) echo "fake-aws: create-stack tags must use Key=Project,Value=LaunchCrew shape, not Project=LaunchCrew" >&2; exit 2 ;;
  esac
  case "$*" in
    *"Environment=demo"*) echo "fake-aws: create-stack tags must use Key=Environment,Value=demo shape, not Environment=demo" >&2; exit 2 ;;
  esac
  case "$*" in
    *"Key=Project,Value=LaunchCrew"*) ;;
    *) echo "fake-aws: create-stack missing Key=Project,Value=LaunchCrew" >&2; exit 2 ;;
  esac
  case "$*" in
    *"Key=Environment,Value=demo"*) ;;
    *) echo "fake-aws: create-stack missing Key=Environment,Value=demo" >&2; exit 2 ;;
  esac
  if [ -n "$FAKE_PREREQS_CREATED_FILE" ]; then : >"$FAKE_PREREQS_CREATED_FILE" 2>/dev/null || true; fi
  printf '{"StackId":"arn:aws:cloudformation:us-east-1:111122223333:stack/launchcrew-prereqs/def456"}\\n'
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "update-stack" ]; then
  if [ "${FAKE_NO_UPDATES:-0}" = "1" ]; then
    echo "An error occurred (ValidationError) when calling the UpdateStack operation: No updates to be performed." >&2
    exit 254
  fi
  exit 0
fi
if [ "$1" = "cloudformation" ] && [ "$2" = "wait" ]; then
  if [ "$MODE" = "wait_fail" ]; then
    echo "Waiter encountered a terminal failure state" >&2
    exit 1
  fi
  exit 0
fi
if [ "$1" = "sns" ] && [ "$2" = "list-subscriptions-by-topic" ]; then
  SNS_MODE="${FAKE_SNS:-exact}"
  EXPECTED="${FAKE_EXPECTED_EMAIL:-}"
  TOPIC="${FAKE_TOPIC_ARN:-arn:aws:sns:us-east-1:111122223333:launchcrew-foundation-BudgetTopic-ABC123}"
  SUB="${FAKE_SUB_ARN:-arn:aws:sns:us-east-1:111122223333:launchcrew-foundation-BudgetTopic-ABC123:12345678-90ab-cdef-1234-567890abcdef}"
  if [ "$SNS_MODE" = "auth" ]; then
    echo "An error occurred (AccessDenied) when calling the ListSubscriptionsByTopic operation: not authorized" >&2
    exit 254
  fi
  if [ "$SNS_MODE" = "error" ]; then
    echo "An error occurred (ThrottlingException) when calling the ListSubscriptionsByTopic operation: Rate exceeded" >&2
    exit 254
  fi
  if [ "$SNS_MODE" = "malformed" ]; then printf 'not-json{{{\\n'; exit 0; fi
  case "$SNS_MODE" in
    exact) printf '{"Subscriptions":[{"Endpoint":"%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"%s","Owner":"111122223333"}]}\\n' "$EXPECTED" "$TOPIC" "$SUB"; exit 0 ;;
    pending) printf '{"Subscriptions":[{"Endpoint":"%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"PendingConfirmation","Owner":"111122223333"}]}\\n' "$EXPECTED" "$TOPIC"; exit 0 ;;
    empty) printf '{"Subscriptions":[]}\\n'; exit 0 ;;
    wrong_email) printf '{"Subscriptions":[{"Endpoint":"wrong-%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"%s","Owner":"111122223333"}]}\\n' "$EXPECTED" "$TOPIC" "$SUB"; exit 0 ;;
    wrong_protocol) printf '{"Subscriptions":[{"Endpoint":"%s","Protocol":"sms","TopicArn":"%s","SubscriptionArn":"%s","Owner":"111122223333"}]}\\n' "$EXPECTED" "$TOPIC" "$SUB"; exit 0 ;;
    wrong_topic) printf '{"Subscriptions":[{"Endpoint":"%s","Protocol":"email","TopicArn":"arn:aws:sns:us-east-1:111122223333:other-topic","SubscriptionArn":"%s","Owner":"111122223333"}]}\\n' "$EXPECTED" "$SUB"; exit 0 ;;
    wrong_owner) printf '{"Subscriptions":[{"Endpoint":"%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"%s","Owner":"999988887777"}]}\\n' "$EXPECTED" "$TOPIC" "$SUB"; exit 0 ;;
    duplicate) printf '{"Subscriptions":[{"Endpoint":"%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"%s","Owner":"111122223333"},{"Endpoint":"%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"%s","Owner":"111122223333"}]}\\n' "$EXPECTED" "$TOPIC" "$SUB" "$EXPECTED" "$TOPIC" "$SUB"; exit 0 ;;
    ambiguous) printf '{"Subscriptions":[{"Endpoint":"%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"%s","Owner":"111122223333"},{"Endpoint":"wrong-%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"%s","Owner":"111122223333"}]}\\n' "$EXPECTED" "$TOPIC" "$SUB" "$EXPECTED" "$TOPIC" "$SUB"; exit 0 ;;
    pending_extra) printf '{"Subscriptions":[{"Endpoint":"%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"%s","Owner":"111122223333"},{"Endpoint":"%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"PendingConfirmation","Owner":"111122223333"}]}\\n' "$EXPECTED" "$TOPIC" "$SUB" "$EXPECTED" "$TOPIC"; exit 0 ;;
    unconfirmed) printf '{"Subscriptions":[{"Endpoint":"%s","Protocol":"email","TopicArn":"%s","SubscriptionArn":"PendingConfirmation","Owner":"111122223333"}]}\\n' "$EXPECTED" "$TOPIC"; exit 0 ;;
    *) echo "fake-aws: unknown FAKE_SNS: $SNS_MODE" >&2; exit 2 ;;
  esac
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
      if [ "$MODE" = "secret_return_mismatch" ]; then
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
if [ "$1" = "acm" ] && [ "$2" = "describe-certificate" ]; then
  CERT_MODE="${FAKE_CERT:-issued}"
  DOMAIN="launchcrew.summitsingh.com"
  CERTARN="${FAKE_CERT_ARN:-cert}"
  if [ "$CERT_MODE" = "auth" ]; then
    echo "An error occurred (AccessDenied) when calling the DescribeCertificate operation: not authorized" >&2
    exit 254
  fi
  case "$CERT_MODE" in
    issued) printf '{"Certificate":{"CertificateArn":"%s","DomainName":"%s","SubjectAlternativeNames":["%s"],"Type":"AMAZON_ISSUED","Options":{"Export":"ENABLED","CertificateTransparencyLoggingPreference":"ENABLED"},"Status":"ISSUED","DomainValidationOptions":[{"DomainName":"%s","ValidationDomain":"%s","ValidationStatus":"SUCCESS","ValidationMethod":"DNS","ResourceRecord":{"Name":"_abc123.acm-validations.aws","Type":"CNAME","Value":"_def456.acm-validations.aws"}}]}}\\n' "$CERTARN" "$DOMAIN" "$DOMAIN" "$DOMAIN" "$DOMAIN"; exit 0 ;;
    pending) printf '{"Certificate":{"CertificateArn":"%s","DomainName":"%s","SubjectAlternativeNames":["%s"],"Type":"AMAZON_ISSUED","Options":{"Export":"ENABLED","CertificateTransparencyLoggingPreference":"ENABLED"},"Status":"PENDING_VALIDATION","DomainValidationOptions":[{"DomainName":"%s","ValidationDomain":"%s","ValidationStatus":"PENDING_VALIDATION","ValidationMethod":"DNS","ResourceRecord":{"Name":"_abc123.acm-validations.aws","Type":"CNAME","Value":"_def456.acm-validations.aws"}}]}}\\n' "$CERTARN" "$DOMAIN" "$DOMAIN" "$DOMAIN" "$DOMAIN"; exit 0 ;;
    wrong_domain) printf '{"Certificate":{"CertificateArn":"%s","DomainName":"other.example.test","SubjectAlternativeNames":["other.example.test"],"Type":"AMAZON_ISSUED","Options":{"Export":"ENABLED","CertificateTransparencyLoggingPreference":"ENABLED"},"Status":"ISSUED","DomainValidationOptions":[{"DomainName":"other.example.test","ValidationDomain":"other.example.test","ValidationStatus":"SUCCESS","ValidationMethod":"DNS","ResourceRecord":{"Name":"_abc123.acm-validations.aws","Type":"CNAME","Value":"_def456.acm-validations.aws"}}]}}\\n' "$CERTARN"; exit 0 ;;
    failed) printf '{"Certificate":{"CertificateArn":"%s","DomainName":"%s","SubjectAlternativeNames":["%s"],"Type":"AMAZON_ISSUED","Options":{"Export":"ENABLED","CertificateTransparencyLoggingPreference":"ENABLED"},"Status":"FAILED","DomainValidationOptions":[{"DomainName":"%s","ValidationDomain":"%s","ValidationStatus":"FAILED","ValidationMethod":"DNS"}]}}\\n' "$CERTARN" "$DOMAIN" "$DOMAIN" "$DOMAIN" "$DOMAIN"; exit 0 ;;
    export_disabled) printf '{"Certificate":{"CertificateArn":"%s","DomainName":"%s","SubjectAlternativeNames":["%s"],"Type":"AMAZON_ISSUED","Options":{"Export":"DISABLED","CertificateTransparencyLoggingPreference":"ENABLED"},"Status":"ISSUED","DomainValidationOptions":[{"DomainName":"%s","ValidationDomain":"%s","ValidationStatus":"SUCCESS","ValidationMethod":"DNS","ResourceRecord":{"Name":"_abc123.acm-validations.aws","Type":"CNAME","Value":"_def456.acm-validations.aws"}}]}}\\n' "$CERTARN" "$DOMAIN" "$DOMAIN" "$DOMAIN" "$DOMAIN"; exit 0 ;;
    san_extra) printf '{"Certificate":{"CertificateArn":"%s","DomainName":"%s","SubjectAlternativeNames":["%s","other.example.test"],"Type":"AMAZON_ISSUED","Options":{"Export":"ENABLED","CertificateTransparencyLoggingPreference":"ENABLED"},"Status":"ISSUED","DomainValidationOptions":[{"DomainName":"%s","ValidationDomain":"%s","ValidationStatus":"SUCCESS","ValidationMethod":"DNS","ResourceRecord":{"Name":"_abc123.acm-validations.aws","Type":"CNAME","Value":"_def456.acm-validations.aws"}}]}}\\n' "$CERTARN" "$DOMAIN" "$DOMAIN" "$DOMAIN" "$DOMAIN"; exit 0 ;;
    record_missing) printf '{"Certificate":{"CertificateArn":"%s","DomainName":"%s","SubjectAlternativeNames":["%s"],"Type":"AMAZON_ISSUED","Options":{"Export":"ENABLED","CertificateTransparencyLoggingPreference":"ENABLED"},"Status":"PENDING_VALIDATION","DomainValidationOptions":[{"DomainName":"%s","ValidationDomain":"%s","ValidationStatus":"PENDING_VALIDATION","ValidationMethod":"DNS"}]}}\\n' "$CERTARN" "$DOMAIN" "$DOMAIN" "$DOMAIN" "$DOMAIN"; exit 0 ;;
    *) echo "fake-aws: unknown FAKE_CERT: $CERT_MODE" >&2; exit 2 ;;
  esac
fi
if [ "$1" = "acm" ] && [ "$2" = "list-tags-for-certificate" ]; then
  if [ "$MODE" = "cert_tag_mismatch" ]; then
    printf '{"Tags":[{"Key":"Project","Value":"Other"},{"Key":"Environment","Value":"demo"}]}\\n'
    exit 0
  fi
  printf '{"Tags":[{"Key":"Project","Value":"LaunchCrew"},{"Key":"Environment","Value":"demo"},{"Key":"TeardownBy","Value":"2026-11-09"}]}\\n'
  exit 0
fi
echo "fake-aws: unexpected call: $*" >&2
exit 2
"""


class PrereqHarness(unittest.TestCase):
    def run_phase(self, args, mode="success", extra_env=None,
                  foundation_email=None, prereqs_status=None,
                  foundation_status=None):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            log = Path(tmp) / "calls.log"
            log.write_text("", encoding="utf-8")
            foundation_created = Path(tmp) / "foundation-created"
            prereqs_created = Path(tmp) / "prereqs-created"
            email = FAKE_EMAIL if foundation_email is None else foundation_email
            params = Path(tmp) / "foundation-params.json"
            params.write_text(json.dumps([
                {"ParameterKey": "BudgetLimitUsd", "ParameterValue": "45"},
                {"ParameterKey": "BudgetNotifyEmail", "ParameterValue": email},
            ]), encoding="utf-8")
            receipt = Path(tmp) / "dns-receipt.json"
            env = dict(os.environ)
            for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                        "AWS_SESSION_TOKEN", "LAUNCHCREW_TODAY"):
                env.pop(key, None)
            env["AWS_BIN"] = str(fake)
            env["FAKE_AWS_LOG"] = str(log)
            env["FAKE_MODE"] = mode
            env["FAKE_FOUNDATION_CREATED_FILE"] = str(foundation_created)
            env["FAKE_PREREQS_CREATED_FILE"] = str(prereqs_created)
            env["FAKE_EXPECTED_EMAIL"] = email
            env["FAKE_TOPIC_ARN"] = TOPIC_ARN
            env["FAKE_SUB_ARN"] = SUB_ARN
            env["FAKE_MASTER_ARN"] = SECRET_MASTER
            env["FAKE_RUNTIME_ARN"] = SECRET_RUNTIME
            env["FAKE_MIGRATION_ARN"] = SECRET_MIGRATION
            env["FAKE_TLS_ARN"] = SECRET_TLS
            env["FAKE_CERT_ARN"] = CERT_ARN
            if prereqs_status is not None:
                env["FAKE_PREREQS_STATUS"] = prereqs_status
            if foundation_status is not None:
                env["FAKE_FOUNDATION_STATUS"] = foundation_status
            if extra_env:
                env.update(extra_env)
            full = list(args)
            if "--foundation-parameters-file" not in full and "--phase" in full:
                idx = full.index("--phase")
                if idx + 1 < len(full) and full[idx + 1] in ("foundation", "prereqs"):
                    full += ["--foundation-parameters-file", str(params)]
            if "--dns-receipt-file" not in full and "--phase" in full:
                idx = full.index("--phase")
                if idx + 1 < len(full) and full[idx + 1] == "prereqs":
                    full += ["--dns-receipt-file", str(receipt)]
            result = subprocess.run(
                [str(BOOTSTRAP), *full], capture_output=True, text=True,
                env=env, check=False)
            calls = [line for line in log.read_text(encoding="utf-8").splitlines()
                     if line.strip()]
            receipt_data = None
            receipt_mode = None
            if receipt.exists():
                receipt_mode = oct(receipt.stat().st_mode & 0o777)
                try:
                    receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
                except Exception:
                    receipt_data = {"_raw": receipt.read_text(encoding="utf-8")}
            return result, calls, receipt_data, receipt_mode

    def foundation_args(self, **overrides):
        args = {
            "--foundation-stack-name": FOUNDATION_STACK,
            "--expected-account": ACCOUNT,
            "--expected-region": REGION,
        }
        args.update(overrides)
        flat = ["--confirm"]
        for key, value in args.items():
            flat += [key, value]
        return [*flat, "--phase", "foundation"]

    def prereqs_args(self, **overrides):
        args = {
            "--prereqs-stack-name": PREREQS_STACK,
            "--foundation-stack-name": FOUNDATION_STACK,
            "--expected-account": ACCOUNT,
            "--expected-region": REGION,
        }
        args.update(overrides)
        flat = ["--confirm"]
        for key, value in args.items():
            flat += [key, value]
        return [*flat, "--phase", "prereqs"]


class DryRunTests(PrereqHarness):
    def test_foundation_dry_run_zero_calls(self):
        result, calls, _, _ = self.run_phase(
            ["--phase", "foundation",
             "--foundation-stack-name", FOUNDATION_STACK,
             "--expected-account", ACCOUNT,
             "--expected-region", REGION])
        self.assertEqual(result.returncode, 0)
        self.assertIn("DRY RUN", result.stdout)
        self.assertEqual(calls, [])

    def test_prereqs_dry_run_zero_calls(self):
        result, calls, _, _ = self.run_phase(
            ["--phase", "prereqs",
             "--prereqs-stack-name", PREREQS_STACK,
             "--foundation-stack-name", FOUNDATION_STACK,
             "--expected-account", ACCOUNT,
             "--expected-region", REGION])
        self.assertEqual(result.returncode, 0)
        self.assertIn("DRY RUN", result.stdout)
        self.assertEqual(calls, [])

    def test_all_never_runs_prereq_phases(self):
        code = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('if [ "$PHASE" = "foundation" ]', code)
        self.assertIn('if [ "$PHASE" = "prereqs" ]', code)


class OwnershipTests(PrereqHarness):
    def test_caller_mismatch_refused_before_deploy(self):
        result, calls, _, _ = self.run_phase(
            self.foundation_args(), extra_env={"FAKE_CALLER": "999988887777"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused", result.stderr)
        self.assertTrue(any("get-caller-identity" in call for call in calls))
        self.assertFalse(any("deploy " in call for call in calls))
        self.assertFalse(any("create-stack" in call for call in calls))

    def test_foundation_tag_mismatch_refused(self):
        result, calls, _, _ = self.run_phase(
            self.foundation_args(), mode="tag_mismatch")
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused", result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))

    def test_foundation_stack_id_mismatch_refused(self):
        result, calls, _, _ = self.run_phase(
            self.foundation_args(), mode="stack_id_mismatch")
        self.assertEqual(result.returncode, 1)
        self.assertIn("StackId", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))

    def test_prereqs_stack_id_mismatch_refused(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), mode="prereqs_id_mismatch")
        self.assertEqual(result.returncode, 1)
        self.assertIn("StackId", result.stdout + result.stderr)
        self.assertFalse(any("create-stack" in call for call in calls))
        self.assertFalse(any("update-stack" in call for call in calls))

    def test_foundation_incomplete_blocks_prereqs(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), foundation_status="CREATE_IN_PROGRESS")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CREATE_COMPLETE or UPDATE_COMPLETE",
                      result.stdout + result.stderr)
        self.assertFalse(any("create-stack" in call for call in calls))
        self.assertFalse(any("update-stack" in call for call in calls))

    def test_stack_auth_is_not_absence(self):
        result, calls, _, _ = self.run_phase(
            self.foundation_args(), mode="stack_auth")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authorization or API failure, not absence",
                      result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))

    def test_broad_validation_error_is_not_absence(self):
        result, calls, _, _ = self.run_phase(
            self.foundation_args(), mode="stack_other_error")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no change made", result.stdout + result.stderr)
        self.assertFalse(any("deploy " in call for call in calls))


class ExpiryTests(PrereqHarness):
    def test_expired_refuses_with_zero_calls(self):
        result, calls, _, _ = self.run_phase(
            self.foundation_args(),
            extra_env={"LAUNCHCREW_TODAY": "2026-11-10"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expired after 2026-11-09", result.stdout + result.stderr)
        self.assertIn("never a billing stop", result.stdout + result.stderr)
        self.assertEqual(calls, [])

    def test_deadline_day_passes(self):
        result, _, _, _ = self.run_phase(
            self.foundation_args(),
            extra_env={"LAUNCHCREW_TODAY": "2026-11-09"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_prereqs_expired_refuses_before_paid(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(),
            extra_env={"LAUNCHCREW_TODAY": "2026-11-10"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])


class CostTagTests(PrereqHarness):
    REFUSALS = ("inactive", "absent", "duplicate", "wrongtype", "mixed",
                "malformed", "nonobject", "unknown", "auth", "error")

    def test_inactive_ce_refuses_foundation(self):
        result, calls, _, _ = self.run_phase(
            self.foundation_args(), extra_env={"FAKE_CE": "inactive"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("deploy " in call for call in calls))

    def test_bad_ce_modes_refuse_prereqs(self):
        for ce_mode in self.REFUSALS:
            with self.subTest(ce_mode=ce_mode):
                result, calls, _, _ = self.run_phase(
                    self.prereqs_args(), extra_env={"FAKE_CE": ce_mode})
                self.assertNotEqual(result.returncode, 0, msg=ce_mode)
                self.assertFalse(
                    any("create-stack" in call for call in calls),
                    msg=ce_mode)
                self.assertFalse(
                    any("update-stack" in call for call in calls),
                    msg=ce_mode)


class SnsExactGateTests(PrereqHarness):
    def test_exact_confirmed_passes_to_paid(self):
        result, calls, _, _ = self.run_phase(self.prereqs_args())
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("exact confirmed", result.stdout)
        self.assertTrue(any("list-subscriptions-by-topic" in call
                            for call in calls))

    def test_pending_blocks_before_paid(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_SNS": "pending"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no confirmed exact", result.stdout + result.stderr)
        self.assertFalse(any("create-stack" in call for call in calls))
        self.assertFalse(any("update-stack" in call for call in calls))

    def test_empty_blocks_before_paid(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_SNS": "empty"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("create-stack" in call for call in calls))

    def test_wrong_recipient_blocks(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_SNS": "wrong_email"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("create-stack" in call for call in calls))

    def test_wrong_protocol_blocks(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_SNS": "wrong_protocol"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("create-stack" in call for call in calls))

    def test_wrong_topic_blocks(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_SNS": "wrong_topic"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("create-stack" in call for call in calls))

    def test_duplicate_blocks_as_ambiguous(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_SNS": "duplicate"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate", result.stdout + result.stderr)
        self.assertFalse(any("create-stack" in call for call in calls))

    def test_ambiguous_extra_confirmed_blocks(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_SNS": "ambiguous"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stdout + result.stderr)
        self.assertFalse(any("create-stack" in call for call in calls))

    def test_wrong_owner_blocks(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_SNS": "wrong_owner"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("create-stack" in call for call in calls))
        self.assertFalse(any("update-stack" in call for call in calls))

    def test_pending_extra_blocks_as_ambiguous(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_SNS": "pending_extra"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stdout + result.stderr)
        self.assertFalse(any("create-stack" in call for call in calls))
        self.assertFalse(any("update-stack" in call for call in calls))

    def test_empty_email_blocks(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), foundation_email="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty", result.stdout + result.stderr)
        self.assertFalse(any("create-stack" in call for call in calls))

    def test_sns_auth_reports_permission(self):
        result, _, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_SNS": "auth"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authorization or API failure",
                      result.stdout + result.stderr)

    def test_topic_owner_mismatch_blocks(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), mode="topic_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("create-stack" in call for call in calls))

    def test_email_never_in_output(self):
        result, _, _, _ = self.run_phase(self.prereqs_args())
        combined = result.stdout + result.stderr
        self.assertNotIn(FAKE_EMAIL, combined)


class FoundationDeployTests(PrereqHarness):
    def test_fresh_foundation_deploys_with_tags(self):
        result, calls, _, _ = self.run_phase(
            self.foundation_args(), mode="foundation_missing")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertTrue(any("deploy " in call and "--tags" in call
                            for call in calls))

    def test_foundation_budget_filter_refused(self):
        result, calls, _, _ = self.run_phase(
            self.foundation_args(), extra_env={"FAKE_BUDGET": "unfiltered"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UNVERIFIED", result.stdout + result.stderr)

    def test_prereqs_budget_filter_required(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_BUDGET": "unfiltered"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UNVERIFIED", result.stdout + result.stderr)
        self.assertFalse(any("create-stack" in call for call in calls))
        self.assertFalse(any("update-stack" in call for call in calls))

    def test_foundation_never_uses_parameter_file_option(self):
        result, calls, _, _ = self.run_phase(self.foundation_args())
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertFalse(any("--parameter-file" in call for call in calls))


class PrereqsPendingTests(PrereqHarness):
    def test_pending_yields_staged_receipt_without_issuance_claim(self):
        result, calls, receipt, mode = self.run_phase(
            self.prereqs_args(), mode="prereqs_missing",
            prereqs_status="CREATE_IN_PROGRESS",
            extra_env={"FAKE_CERT": "pending"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("PENDING_VALIDATION", result.stdout)
        self.assertIn("expected", result.stdout)
        self.assertIn(VALIDATION_NAME, result.stdout)
        self.assertIn(VALIDATION_VALUE, result.stdout)
        self.assertNotIn("Prereqs ready", result.stdout)
        self.assertIsNotNone(receipt)
        self.assertEqual(mode, "0o600")
        self.assertEqual(receipt.get("certificate_status"), "PENDING_VALIDATION")
        self.assertEqual(receipt.get("validation_name"), VALIDATION_NAME)
        self.assertEqual(receipt.get("validation_value"), VALIDATION_VALUE)
        self.assertIn("secrets", receipt)
        blob = json.dumps(receipt)
        self.assertNotIn(FAKE_EMAIL, blob)
        self.assertNotIn("password", blob.lower())

    def test_issued_ready_writes_complete_receipt(self):
        result, _, receipt, mode = self.run_phase(
            self.prereqs_args(), mode="prereqs_missing",
            prereqs_status="CREATE_COMPLETE",
            extra_env={"FAKE_CERT": "issued"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Prereqs ready", result.stdout)
        self.assertEqual(mode, "0o600")
        self.assertEqual(receipt.get("certificate_status"), "ISSUED")

    def test_wrong_domain_refused(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_CERT": "wrong_domain"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("domain mismatch", result.stdout + result.stderr)

    def test_failed_cert_refused(self):
        result, _, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_CERT": "failed"})
        self.assertNotEqual(result.returncode, 0)

    def test_cert_account_mismatch_refused(self):
        result, _, _, _ = self.run_phase(
            self.prereqs_args(), mode="cert_arn_mismatch")
        self.assertNotEqual(result.returncode, 0)

    def test_export_disabled_refused(self):
        result, _, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_CERT": "export_disabled"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("export mismatch", result.stdout + result.stderr)

    def test_san_extra_refused(self):
        result, _, _, _ = self.run_phase(
            self.prereqs_args(), extra_env={"FAKE_CERT": "san_extra"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SAN mismatch", result.stdout + result.stderr)

    def test_inprogress_observes_without_update(self):
        result, calls, receipt, _ = self.run_phase(
            self.prereqs_args(), prereqs_status="CREATE_IN_PROGRESS",
            extra_env={"FAKE_CERT": "pending"})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertFalse(any("update-stack" in call for call in calls))
        self.assertFalse(any("create-stack" in call for call in calls))
        self.assertIn("observing only", result.stdout)
        self.assertIsNotNone(receipt)

    def test_record_missing_resumes_readonly(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), mode="prereqs_missing",
            prereqs_status="CREATE_IN_PROGRESS",
            extra_env={"FAKE_CERT": "record_missing"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("resume read-only", result.stdout + result.stderr)
        self.assertFalse(any("update-stack" in call for call in calls))
        creates = [call for call in calls if "create-stack" in call]
        self.assertEqual(len(creates), 1)

    def test_resource_missing_resumes_readonly(self):
        result, calls, _, _ = self.run_phase(
            self.prereqs_args(), mode="prereqs_missing",
            prereqs_status="CREATE_IN_PROGRESS",
            extra_env={"FAKE_RESOURCE_MISSING": "1", "FAKE_CERT": "pending"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("resume read-only", result.stdout + result.stderr)
        self.assertFalse(any("update-stack" in call for call in calls))
        creates = [call for call in calls if "create-stack" in call]
        self.assertEqual(len(creates), 1)

    def test_no_get_secret_value_in_any_call(self):
        result, calls, _, _ = self.run_phase(self.prereqs_args())
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        joined = " ".join(calls)
        self.assertNotIn("GetSecretValue", joined)
        self.assertNotIn("get-secret-value", joined.lower())
        self.assertNotIn("PutSecretValue", joined)
        self.assertNotIn("ExportCertificate", joined)


if __name__ == "__main__":
    unittest.main()

