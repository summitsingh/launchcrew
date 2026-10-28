#!/bin/sh
# LaunchCrew demo teardown, dry-run by default, gated stack delete only.
# Dry-run makes no AWS call. Confirm path requires an exact stack ARN plus
# expected account and region, then verifies caller identity and LaunchCrew
# demo tags before any destructive call. It deletes only the named stack via
# CloudFormation. It never deletes by prefix and never deletes shared or
# outside-stack resources. Outside-stack scope needs a separate approval and
# is reported as remaining work. AWS Budget is an alert and estimate
# mechanism, not an enforced hard spend cap. Cost and deployment approvals
# stay open user decisions. Teardown is required after Nov 4 and no later
# than Nov 9, 2026.
set -eu
AWS_BIN="${AWS_BIN:-aws}"
CONFIRM=0
STACK_ARN=""
EXPECTED_ACCOUNT=""
EXPECTED_REGION=""

usage() {
  echo "Usage: $0 [--confirm --stack-arn ARN --expected-account ID --expected-region REGION]"
  echo "Dry-run default makes no AWS call. Confirm path deletes only the exact stack ARN."
}

while [ $# -gt 0 ]; do
  case "$1" in
    --confirm) CONFIRM=1; shift ;;
    --stack-arn) STACK_ARN="${2:-}"; shift 2 ;;
    --stack-arn=*) STACK_ARN="${1#--stack-arn=}"; shift ;;
    --expected-account) EXPECTED_ACCOUNT="${2:-}"; shift 2 ;;
    --expected-account=*) EXPECTED_ACCOUNT="${1#--expected-account=}"; shift ;;
    --expected-region) EXPECTED_REGION="${2:-}"; shift 2 ;;
    --expected-region=*) EXPECTED_REGION="${1#--expected-region=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

remaining_scope() {
  echo "Remaining work, not deleted by this script:"
  echo "- Secrets Manager values passed as parameters (runtime, migration, TLS, master password): outside stack, separate approval with exact ARNs if cleanup is wanted."
  echo "- ACM certificate passed as AcmCertificateArn: outside stack, separate approval if cleanup is wanted."
  echo "- Cloudflare DNS record, only if created in a later authorized run: separate approval, exact record name required."
  echo "- Manual snapshots, images, or resources created outside the stack: separate approval with exact identifiers, never prefix deletion."
  echo "- Verify no recurring charges in Cost Explorer and Budgets console. Budget is alert only, not a hard cap."
}

if [ "$CONFIRM" -ne 1 ]; then
  echo "DRY RUN, no AWS call made."
  echo "Confirm path deletes only one exact CloudFormation stack ARN after caller and tag checks."
  echo "To run for real, after separate authorization:"
  echo "  $0 --confirm --stack-arn <exact-stack-arn> --expected-account <12-digit> --expected-region <region>"
  echo "Steps when confirmed: verify caller account, verify Project LaunchCrew and Environment demo tags, delete-stack, wait stack-delete-complete, verify terminal absence."
  echo "Terminal proof accepts describe-stacks not-found or a DELETE_COMPLETE record for the exact stack ID. A DELETE_COMPLETE record is then checked for DELETE_SKIPPED retained resources."
  echo "DELETE_SKIPPED or retained resources are reported as incomplete cleanup, distinct from complete resource cleanup."
  echo "No prefix deletion. No shared or outside-stack deletion."
  remaining_scope
  exit 0
fi

[ -n "$STACK_ARN" ] || { echo "confirm requires --stack-arn with an exact stack ARN" >&2; exit 2; }
[ -n "$EXPECTED_ACCOUNT" ] || { echo "confirm requires --expected-account with a 12-digit account" >&2; exit 2; }
[ -n "$EXPECTED_REGION" ] || { echo "confirm requires --expected-region" >&2; exit 2; }
case "$EXPECTED_ACCOUNT" in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) echo "refused: expected account must be 12 digits" >&2; exit 2 ;;
esac
case "$STACK_ARN" in
  arn:aws:cloudformation:*:*:stack/*/*) ;;
  *) echo "refused: stack ARN must be an exact CloudFormation stack ARN" >&2; exit 2 ;;
esac
ARN_REGION="$(printf '%s' "$STACK_ARN" | cut -d: -f4)"
ARN_ACCOUNT="$(printf '%s' "$STACK_ARN" | cut -d: -f5)"
[ "$ARN_REGION" = "$EXPECTED_REGION" ] || { echo "refused: ARN region $ARN_REGION does not match expected $EXPECTED_REGION" >&2; exit 1; }
[ "$ARN_ACCOUNT" = "$EXPECTED_ACCOUNT" ] || { echo "refused: ARN account $ARN_ACCOUNT does not match expected $EXPECTED_ACCOUNT" >&2; exit 1; }
if [ -n "${AWS_REGION:-}" ] && [ "$AWS_REGION" != "$EXPECTED_REGION" ]; then
  echo "refused: AWS_REGION $AWS_REGION does not match expected $EXPECTED_REGION" >&2; exit 1
fi
if [ -n "${AWS_DEFAULT_REGION:-}" ] && [ "$AWS_DEFAULT_REGION" != "$EXPECTED_REGION" ]; then
  echo "refused: AWS_DEFAULT_REGION $AWS_DEFAULT_REGION does not match expected $EXPECTED_REGION" >&2; exit 1
fi
case "$AWS_BIN" in
  */*) [ -x "$AWS_BIN" ] || { echo "AWS command not executable: $AWS_BIN" >&2; exit 1; } ;;
  *) command -v "$AWS_BIN" >/dev/null 2>&1 || { echo "AWS command not found: $AWS_BIN" >&2; exit 1; } ;;
esac

TMP_ERR="$(mktemp /tmp/launchcrew-teardown-err-XXXXXX)"
trap 'rm -f "$TMP_ERR"' EXIT INT TERM

is_not_found() {
  case "$1" in *ValidationError*"does not exist"*) return 0 ;; esac
  return 1
}

is_auth_error() {
  case "$1" in
    *AccessDenied*|*Unauthorized*|*ExpiredToken*|*InvalidClientTokenId*|*TokenRefreshRequired*|*Forbidden*) return 0 ;;
  esac
  return 1
}

echo "Confirm path for exact stack ARN: $STACK_ARN"
echo "Expected account $EXPECTED_ACCOUNT region $EXPECTED_REGION"

if ! CALLER_ACCOUNT="$("$AWS_BIN" sts get-caller-identity --query Account --output text --region "$EXPECTED_REGION" 2>"$TMP_ERR")"; then
  ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
  echo "caller verification failed, no destructive call made: $ERR" >&2
  if is_auth_error "$ERR"; then echo "authorization or API failure, not absence" >&2; fi
  exit 1
fi
CALLER_ACCOUNT="$(printf '%s' "$CALLER_ACCOUNT" | tr -d '[:space:]')"
[ "$CALLER_ACCOUNT" = "$EXPECTED_ACCOUNT" ] || { echo "refused: caller $CALLER_ACCOUNT does not match expected $EXPECTED_ACCOUNT, no destructive call made" >&2; exit 1; }

if ! PROJECT_TAG="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_ARN" --region "$EXPECTED_REGION" --query "Stacks[0].Tags[?Key=='Project'].Value | [0]" --output text 2>"$TMP_ERR")"; then
  ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
  if is_not_found "$ERR"; then
    echo "Stack already absent, no deletion performed: $STACK_ARN"
    remaining_scope
    exit 0
  fi
  echo "stack tag check failed, no destructive call made: $ERR" >&2
  if is_auth_error "$ERR"; then echo "authorization or API failure, not absence" >&2; fi
  exit 1
fi
if ! ENV_TAG="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_ARN" --region "$EXPECTED_REGION" --query "Stacks[0].Tags[?Key=='Environment'].Value | [0]" --output text 2>"$TMP_ERR")"; then
  ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
  if is_not_found "$ERR"; then
    echo "Stack already absent, no deletion performed: $STACK_ARN"
    remaining_scope
    exit 0
  fi
  echo "stack tag check failed, no destructive call made: $ERR" >&2
  if is_auth_error "$ERR"; then echo "authorization or API failure, not absence" >&2; fi
  exit 1
fi
PROJECT_TAG="$(printf '%s' "$PROJECT_TAG" | tr -d '[:space:]')"
ENV_TAG="$(printf '%s' "$ENV_TAG" | tr -d '[:space:]')"
[ "$PROJECT_TAG" = "LaunchCrew" ] || { echo "refused: Project tag is $PROJECT_TAG, expected LaunchCrew, no destructive call made" >&2; exit 1; }
[ "$ENV_TAG" = "demo" ] || { echo "refused: Environment tag is $ENV_TAG, expected demo, no destructive call made" >&2; exit 1; }
echo "Verified caller $CALLER_ACCOUNT and tags Project LaunchCrew Environment demo"

if ! "$AWS_BIN" cloudformation delete-stack --stack-name "$STACK_ARN" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
  ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
  if is_not_found "$ERR"; then
    echo "Stack already absent, no deletion performed: $STACK_ARN"
    remaining_scope
    exit 0
  fi
  echo "delete-stack failed: $ERR" >&2
  if is_auth_error "$ERR"; then echo "authorization or API failure, not absence" >&2; fi
  exit 1
fi
echo "delete-stack accepted, waiting for stack-delete-complete"

if ! "$AWS_BIN" cloudformation wait stack-delete-complete --stack-name "$STACK_ARN" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
  ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
  echo "wait reported failure, verifying terminal state before any claim: $ERR" >&2
fi

if STACK_STATUS="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_ARN" --region "$EXPECTED_REGION" --query "Stacks[0].StackStatus" --output text 2>"$TMP_ERR")"; then
  STACK_STATUS="$(printf '%s' "$STACK_STATUS" | tr -d '[:space:]')"
  if [ "$STACK_STATUS" = "DELETE_COMPLETE" ]; then
    echo "Stack deleted, verified by DELETE_COMPLETE status for exact stack ID: $STACK_ARN"
    if SKIPPED="$("$AWS_BIN" cloudformation describe-stack-resources --stack-name "$STACK_ARN" --region "$EXPECTED_REGION" --query "StackResources[?ResourceStatus=='DELETE_SKIPPED'].LogicalResourceId" --output text 2>"$TMP_ERR")"; then
      SKIPPED_TRIMMED="$(printf '%s' "$SKIPPED" | tr -d '[:space:]')"
      if [ -n "$SKIPPED_TRIMMED" ] && [ "$SKIPPED_TRIMMED" != "None" ]; then
        echo "DELETE_SKIPPED retained resources remain, not complete cleanup: $SKIPPED" >&2
        echo "Inspect the exact stack ARN for retained resources. No prefix deletion is attempted." >&2
        remaining_scope
        exit 1
      fi
      echo "No DELETE_SKIPPED resources. Complete resource cleanup for stack scope."
      remaining_scope
      exit 0
    else
      ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
      if is_not_found "$ERR"; then
        echo "No DELETE_SKIPPED resources. Complete resource cleanup for stack scope."
        remaining_scope
        exit 0
      fi
      echo "retained resource check failed, complete cleanup not proven: $ERR" >&2
      if is_auth_error "$ERR"; then echo "authorization or API failure, not absence" >&2; fi
      remaining_scope
      exit 1
    fi
  fi
  echo "stack still present with status $STACK_STATUS, cleanup incomplete" >&2
  echo "Inspect the exact stack ARN in the console for retained resources. No prefix deletion is attempted." >&2
  remaining_scope
  exit 1
else
  ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
  if is_not_found "$ERR"; then
    echo "Stack absent, verified by describe-stacks not-found: $STACK_ARN"
    echo "No DELETE_SKIPPED resources. Complete resource cleanup for stack scope."
    remaining_scope
    exit 0
  fi
  echo "terminal verification failed, stack absence not proven: $ERR" >&2
  if is_auth_error "$ERR"; then echo "authorization or API failure, not absence" >&2; fi
  remaining_scope
  exit 1
fi
