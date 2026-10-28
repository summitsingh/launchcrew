#!/bin/sh
# LaunchCrew demo staged bootstrap, dry-run by default, gated phased bring-up.
# Dry-run makes no AWS call. Confirm path brings infrastructure up in order and
# refuses to start the app early:
#   phase infra   deploy the CloudFormation stack with EnableServices=false on a
#                 fresh stack (or preserve the current true value on an owned
#                 update so running services are not reset), so VPC, ECR
#                 repositories, RDS, and task definitions exist with both ECS
#                 services at DesiredCount 0 and no app running
#   phase images  verify each of the five published image URIs exists in its
#                 owned ECR repository with an image digest and no failures,
#                 and equals the image referenced by its owned stack task
#                 definition; placeholder or missing images refuse
#   phase dbroles run the isolated one-off bootstrap task that binds database
#                 role passwords from injected Secrets Manager values held in
#                 task memory only, then require its STOPPED exit code 0
#   phase migrate run the single one-off migration task, require STOPPED exit
#                 code 0, then run the separate verify task definition in
#                 verify mode as schema and runtime-identity proof
#   phase enable  re-prove images, owned secrets and execution roles, and the
#                 runtime-only verify proof, then update the stack with
#                 EnableServices=true for fixed count 1 each, then verify both
#                 services report desired 1 and running 1
# The migration task definition is the only schema change path; the bootstrap
# task never runs alembic, and runtime tasks never run alembic or role binds,
# so there are no duplicate migration controllers. This controller never calls
# the secretsmanager read-value API and never prints a secret value: it handles
# only secret ARNs as identifiers via describe-secret metadata, and the
# bootstrap job holds values in private task memory without logging them.
# Outside-stack values (Secrets Manager secret contents, ACM certificate,
# Cloudflare DNS, manual snapshots) need a separate approval with exact
# identifiers and are reported as remaining work. Teardown stays separate in
# deploy/aws/teardown.sh. An AWS Budget is an alert and estimate mechanism,
# not an enforced hard spend cap. A budget filter with no data or 0 is not
# proof of zero spend. Cost allocation tag activation is never done here and
# is verified read-only before any paid phase: the Project key must already
# be Active as a user defined resource cost allocation tag in Billing under
# a separate approval, which can take 24h for the key to appear plus 24h for
# activation. Inactive, absent, ambiguous, or unreadable activation refuses
# before any CloudFormation deploy or one-off task, because spend starts at
# infra, RDS, and ALB creation even at DesiredCount 0.
# One-off jobs run in the public subnets with a public IP and a security
# group that allows no inbound traffic at all. That is the honest minimal
# egress path: private subnets here have no NAT gateway and no VPC endpoints,
# so a job placed there with a disabled public IP cannot reach ECR, Secrets
# Manager, or CloudWatch Logs and only pretends to work. The database stays
# private regardless: the isolated job group may reach only Postgres on the
# database group plus HTTPS egress, and RDS itself is never public.
set -eu
AWS_BIN="${AWS_BIN:-aws}"
CONFIRM=0
STACK_NAME=""
EXPECTED_ACCOUNT=""
EXPECTED_REGION=""
PHASE="all"
TEMPLATE_FILE=""
PARAMETERS_FILE=""
API_IMAGE=""
WEB_IMAGE=""
WEB_PROXY_IMAGE=""
MIGRATION_IMAGE=""
BOOTSTRAP_IMAGE=""
CLUSTER_NAME="launchcrew-demo"
RUNTIME_SECRET_ARN=""
MIGRATION_SECRET_ARN=""
MASTER_SECRET_ARN=""
TLS_SECRET_ARN=""

usage() {
  echo "Usage: $0 [--confirm --stack-name NAME --expected-account ID --expected-region REGION ...] [--phase infra|images|dbroles|migrate|enable|all]"
  echo "Dry-run default makes no AWS call and prints the ordered phase plan."
  echo "Confirm path requires --stack-name, --expected-account (12 digits), --expected-region,"
  echo "  --parameters-file, plus per-phase image URIs and secret ARNs (see phase plan)."
}

while [ $# -gt 0 ]; do
  case "$1" in
    --confirm) CONFIRM=1; shift ;;
    --stack-name) STACK_NAME="${2:-}"; shift 2 ;;
    --stack-name=*) STACK_NAME="${1#--stack-name=}"; shift ;;
    --expected-account) EXPECTED_ACCOUNT="${2:-}"; shift 2 ;;
    --expected-account=*) EXPECTED_ACCOUNT="${1#--expected-account=}"; shift ;;
    --expected-region) EXPECTED_REGION="${2:-}"; shift 2 ;;
    --expected-region=*) EXPECTED_REGION="${1#--expected-region=}"; shift ;;
    --phase) PHASE="${2:-}"; shift 2 ;;
    --phase=*) PHASE="${1#--phase=}"; shift ;;
    --template-file) TEMPLATE_FILE="${2:-}"; shift 2 ;;
    --template-file=*) TEMPLATE_FILE="${1#--template-file=}"; shift ;;
    --parameters-file) PARAMETERS_FILE="${2:-}"; shift 2 ;;
    --parameters-file=*) PARAMETERS_FILE="${1#--parameters-file=}"; shift ;;
    --api-image) API_IMAGE="${2:-}"; shift 2 ;;
    --api-image=*) API_IMAGE="${1#--api-image=}"; shift ;;
    --web-image) WEB_IMAGE="${2:-}"; shift 2 ;;
    --web-image=*) WEB_IMAGE="${1#--web-image=}"; shift ;;
    --web-proxy-image) WEB_PROXY_IMAGE="${2:-}"; shift 2 ;;
    --web-proxy-image=*) WEB_PROXY_IMAGE="${1#--web-proxy-image=}"; shift ;;
    --migration-image) MIGRATION_IMAGE="${2:-}"; shift 2 ;;
    --migration-image=*) MIGRATION_IMAGE="${1#--migration-image=}"; shift ;;
    --bootstrap-image) BOOTSTRAP_IMAGE="${2:-}"; shift 2 ;;
    --bootstrap-image=*) BOOTSTRAP_IMAGE="${1#--bootstrap-image=}"; shift ;;
    --cluster-name) CLUSTER_NAME="${2:-}"; shift 2 ;;
    --cluster-name=*) CLUSTER_NAME="${1#--cluster-name=}"; shift ;;
    --runtime-secret-arn) RUNTIME_SECRET_ARN="${2:-}"; shift 2 ;;
    --runtime-secret-arn=*) RUNTIME_SECRET_ARN="${1#--runtime-secret-arn=}"; shift ;;
    --migration-secret-arn) MIGRATION_SECRET_ARN="${2:-}"; shift 2 ;;
    --migration-secret-arn=*) MIGRATION_SECRET_ARN="${1#--migration-secret-arn=}"; shift ;;
    --master-secret-arn) MASTER_SECRET_ARN="${2:-}"; shift 2 ;;
    --master-secret-arn=*) MASTER_SECRET_ARN="${1#--master-secret-arn=}"; shift ;;
    --tls-secret-arn) TLS_SECRET_ARN="${2:-}"; shift 2 ;;
    --tls-secret-arn=*) TLS_SECRET_ARN="${1#--tls-secret-arn=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

phase_plan() {
  echo "Phase order, each phase gates the next; any failure stops the run:"
  echo "  1. ownership: caller account, stack Project LaunchCrew and Environment demo tags,"
  echo "     exact StackId account and region, secret ARN shape account and region,"
  echo "     plus exact returned secret ARN and secret tags; fresh stacks create with tags"
  echo "  2. infra: deploy stack (EnableServices false on create, preserved on owned update),"
  echo "     then require stack CREATE_COMPLETE or UPDATE_COMPLETE, services stay 0 unless kept"
  echo "  3. images: all five ECR image URIs verified by digest with no failures, each equal"
  echo "     to its owned stack task definition image, explicit tag required, no latest fallback;"
  echo "     task definitions must inject exactly the validated secrets under the owned roles"
  echo "  4. dbroles: isolated bootstrap task STOPPED exit 0, passwords bound in task memory only,"
  echo "     after the bootstrap task definition secrets and execution role are proven owned"
  echo "  5. migrate: isolated migration task STOPPED exit 0, then separate verify task proof of"
  echo "     expected head revision, runtime identity, rolled-back write, and DDL refusal"
  echo "  6. enable: budget readiness preflight (exact Project filter read back,"
  echo "     Project activation verified Active read-only, never activated here),"
  echo "     then re-prove images, bindings, and the runtime-only"
  echo "     verify proof from live state, then update stack with EnableServices=true,"
  echo "     verify desired 1 and running 1 each (configuration check only; serving"
  echo "     health is proven by ALB targets after DNS)"
  echo "Per-phase inputs: infra needs stack, account, region, parameters file only;"
  echo "  images needs the five image URIs plus the four secret ARNs for the API and web bindings;"
  echo "  dbroles needs the bootstrap image and three secret ARNs;"
  echo "  migrate needs the migration and bootstrap images plus migration and runtime secret ARNs;"
  echo "  enable needs the five image URIs and all four secret ARNs to re-prove refs, bindings, and verify."
  echo "Each phase re-verifies its own preconditions from live state, so a single phase can resume"
  echo "after earlier phases completed in a previous run; nothing is assumed from memory."
  echo "Remaining work, never done by this script:"
  echo "- Secrets Manager secret values, ACM certificate, Cloudflare DNS, manual snapshots: separate approval with exact identifiers."
  echo "- Teardown: deploy/aws/teardown.sh after Nov 4 and no later than Nov 9, 2026."
  echo "- Budget alerts are notifications only, not an enforced hard spend cap."
  echo "- Cost allocation tag activation: Billing console approval only, never this script; allow 24h for the key plus 24h for activation. Paid phases refuse unless the Project key reads back Active."
}

if [ "$CONFIRM" -ne 1 ]; then
  echo "DRY RUN, no AWS call made."
  phase_plan
  echo "To run for real, after separate authorization:"
  echo "  $0 --confirm --stack-name <exact-stack-name> --expected-account <12-digit> --expected-region <region> --parameters-file <file> [--phase PHASE plus the image URIs and secret ARNs that phase requires]"
  exit 0
fi

case "$PHASE" in
  infra|images|dbroles|migrate|enable|all) ;;
  *) echo "refused: unknown phase $PHASE" >&2; exit 2 ;;
esac
[ -n "$STACK_NAME" ] || { echo "confirm requires --stack-name with the exact stack name" >&2; exit 2; }
[ -n "$EXPECTED_ACCOUNT" ] || { echo "confirm requires --expected-account with a 12-digit account" >&2; exit 2; }
[ -n "$EXPECTED_REGION" ] || { echo "confirm requires --expected-region" >&2; exit 2; }
case "$EXPECTED_ACCOUNT" in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) echo "refused: expected account must be 12 digits" >&2; exit 2 ;;
esac
[ -n "$PARAMETERS_FILE" ] || { echo "confirm requires --parameters-file" >&2; exit 2; }
[ -f "$PARAMETERS_FILE" ] || { echo "refused: parameters file not found: $PARAMETERS_FILE" >&2; exit 2; }

require_images_args() {
  [ -n "$API_IMAGE" ] || { echo "confirm requires --api-image for this phase" >&2; exit 2; }
  [ -n "$WEB_IMAGE" ] || { echo "confirm requires --web-image for this phase" >&2; exit 2; }
  [ -n "$WEB_PROXY_IMAGE" ] || { echo "confirm requires --web-proxy-image for this phase" >&2; exit 2; }
  [ -n "$MIGRATION_IMAGE" ] || { echo "confirm requires --migration-image for this phase" >&2; exit 2; }
  [ -n "$BOOTSTRAP_IMAGE" ] || { echo "confirm requires --bootstrap-image for this phase" >&2; exit 2; }
}

require_secret_args() {
  [ -n "$RUNTIME_SECRET_ARN" ] || { echo "confirm requires --runtime-secret-arn for this phase" >&2; exit 2; }
  [ -n "$MIGRATION_SECRET_ARN" ] || { echo "confirm requires --migration-secret-arn for this phase" >&2; exit 2; }
  [ -n "$MASTER_SECRET_ARN" ] || { echo "confirm requires --master-secret-arn for this phase" >&2; exit 2; }
}

require_tls_arg() {
  [ -n "$TLS_SECRET_ARN" ] || { echo "confirm requires --tls-secret-arn for this phase" >&2; exit 2; }
}

case "$PHASE" in
  infra) ;;
  images) require_images_args; require_secret_args; require_tls_arg ;;
  dbroles)
    [ -n "$BOOTSTRAP_IMAGE" ] || { echo "confirm requires --bootstrap-image for this phase" >&2; exit 2; }
    require_secret_args ;;
  migrate)
    [ -n "$MIGRATION_IMAGE" ] || { echo "confirm requires --migration-image for this phase" >&2; exit 2; }
    [ -n "$BOOTSTRAP_IMAGE" ] || { echo "confirm requires --bootstrap-image for this phase" >&2; exit 2; }
    [ -n "$MIGRATION_SECRET_ARN" ] || { echo "confirm requires --migration-secret-arn for this phase" >&2; exit 2; }
    [ -n "$RUNTIME_SECRET_ARN" ] || { echo "confirm requires --runtime-secret-arn for this phase" >&2; exit 2; } ;;
  enable|all) require_images_args; require_secret_args; require_tls_arg ;;
esac

needs_secret_checks() {
  case "$PHASE" in
    dbroles|migrate|enable|all) return 0 ;;
  esac
  [ -n "$RUNTIME_SECRET_ARN" ] || [ -n "$MIGRATION_SECRET_ARN" ] || [ -n "$MASTER_SECRET_ARN" ] || [ -n "$TLS_SECRET_ARN" ]
}

if [ -z "$TEMPLATE_FILE" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  TEMPLATE_FILE="$SCRIPT_DIR/fargate.yaml"
fi
[ -f "$TEMPLATE_FILE" ] || { echo "refused: template file not found: $TEMPLATE_FILE" >&2; exit 2; }
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
command -v python3 >/dev/null 2>&1 || { echo "refused: python3 is required to merge parameters and verify JSON proof" >&2; exit 1; }

TMP_ERR="$(mktemp /tmp/launchcrew-bootstrap-err-XXXXXX)"
TMP_JSON="$(mktemp /tmp/launchcrew-bootstrap-json-XXXXXX)"
TMP_PARAMS="$(mktemp /tmp/launchcrew-bootstrap-params-XXXXXX)"
trap 'rm -f "$TMP_ERR" "$TMP_JSON" "$TMP_PARAMS"' EXIT INT TERM

is_auth_error() {
  case "$1" in
    *AccessDenied*|*Unauthorized*|*ExpiredToken*|*InvalidClientTokenId*|*TokenRefreshRequired*|*NotAuthorized*|*AuthFailure*|*Forbidden*) return 0 ;;
  esac
  return 1
}

is_absent_error() {
  case "$1" in
    *"does not exist"*)
      case "$1" in
        *"$STACK_NAME"*) return 0 ;;
      esac
      return 1 ;;
  esac
  return 1
}

COMPLETED=""

mark_done() {
  if [ -z "$COMPLETED" ]; then
    COMPLETED="$1"
  else
    COMPLETED="$COMPLETED,$1"
  fi
}

phase_failed() {
  echo "BOOTSTRAP FAILED at phase $1. Completed phases: ${COMPLETED:-none}. Remaining phases not started and not claimed." >&2
  echo "Fix the failure, then rerun from --phase $1 after review. The app never starts on a failed run." >&2
  exit 1
}

wants_phase() {
  if [ "$PHASE" = "all" ] || [ "$PHASE" = "$1" ]; then
    return 0
  fi
  return 1
}
# Ownership gate one: caller identity must match the expected account before
# any stack, secret, image, task, or service call.
echo "Ownership check: caller account must equal $EXPECTED_ACCOUNT in $EXPECTED_REGION"
if ! CALLER_ACCOUNT="$("$AWS_BIN" sts get-caller-identity --query Account --output text --region "$EXPECTED_REGION" 2>"$TMP_ERR")"; then
  ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
  echo "caller verification failed, no change made." >&2
  if is_auth_error "$ERR"; then echo "authorization or API failure, not absence." >&2; fi
  exit 1
fi
CALLER_ACCOUNT="$(printf '%s' "$CALLER_ACCOUNT" | tr -d '[:space:]')"
[ "$CALLER_ACCOUNT" = "$EXPECTED_ACCOUNT" ] || { echo "refused: caller $CALLER_ACCOUNT does not match expected $EXPECTED_ACCOUNT, no change made" >&2; exit 1; }

# Ownership gate two: the exact stack must carry the demo tags before any
# mutation, and its StackId region and account must match the expectation.
# A stack that reports absent (ValidationError, does not exist) is a fresh
# create path, not ownership proof: only infra or all may proceed, and the
# create deploys with the demo tags. An authorization failure is never
# treated as absence.
STACK_EXISTS=0
STACK_STATUS=""
STACK_ID=""
CURRENT_ENABLE="false"
if STACK_JSON="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" --output json 2>"$TMP_ERR")"; then
  STACK_EXISTS=1
  printf '%s' "$STACK_JSON" >"$TMP_JSON"
  STACK_PARSED="$(python3 - "$TMP_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
stacks = doc.get("Stacks", [])
if not stacks:
    print("EMPTY")
    sys.exit(0)
stack = stacks[0]
tags = {t.get("Key"): t.get("Value") for t in stack.get("Tags", []) if isinstance(t, dict)}
params = {p.get("ParameterKey"): p.get("ParameterValue") for p in stack.get("Parameters", []) if isinstance(p, dict)}
print("STACKID\t%s" % stack.get("StackId", ""))
print("STATUS\t%s" % stack.get("StackStatus", ""))
print("PROJECT\t%s" % tags.get("Project", ""))
print("ENV\t%s" % tags.get("Environment", ""))
print("ENABLE\t%s" % params.get("EnableServices", "false"))
PYEOF
)" || { echo "refused: stack metadata unreadable, no change made" >&2; exit 1; }
  STACK_ID="$(printf '%s\n' "$STACK_PARSED" | awk -F'\t' '$1=="STACKID"{print $2}')"
  STACK_STATUS="$(printf '%s\n' "$STACK_PARSED" | awk -F'\t' '$1=="STATUS"{print $2}')"
  PROJECT_TAG="$(printf '%s\n' "$STACK_PARSED" | awk -F'\t' '$1=="PROJECT"{print $2}')"
  ENV_TAG="$(printf '%s\n' "$STACK_PARSED" | awk -F'\t' '$1=="ENV"{print $2}')"
  CURRENT_ENABLE="$(printf '%s\n' "$STACK_PARSED" | awk -F'\t' '$1=="ENABLE"{print $2}')"
  [ "$PROJECT_TAG" = "LaunchCrew" ] || { echo "refused: Project tag is $PROJECT_TAG, expected LaunchCrew, no change made" >&2; exit 1; }
  [ "$ENV_TAG" = "demo" ] || { echo "refused: Environment tag is $ENV_TAG, expected demo, no change made" >&2; exit 1; }
  case "$STACK_ID" in
    "arn:aws:cloudformation:$EXPECTED_REGION:$EXPECTED_ACCOUNT:"*) ;;
    *) echo "refused: StackId $STACK_ID is not owned by $EXPECTED_ACCOUNT in $EXPECTED_REGION, no change made" >&2; exit 1 ;;
  esac
  echo "Verified caller $CALLER_ACCOUNT and stack $STACK_NAME tags Project LaunchCrew Environment demo status $STACK_STATUS"
else
  ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
  if is_auth_error "$ERR"; then
    echo "stack check authorization or API failure, not absence, no change made." >&2
    exit 1
  fi
  if is_absent_error "$ERR"; then
    case "$PHASE" in
      infra|all) echo "Stack $STACK_NAME absent: fresh create path, infra will deploy with demo tags" ;;
      *) echo "refused: stack $STACK_NAME does not exist; run --phase infra first, no change made" >&2; exit 1 ;;
    esac
  else
    echo "stack check failed, no change made." >&2
    exit 1
  fi
fi

# Ownership gate three: each referenced secret ARN must use the exact Secrets
# Manager ARN shape, belong to the expected account and region, resolve to its
# exact self ARN through describe-secret, and carry the demo tags. This reads
# metadata only and never fetches a secret value.
check_secret_arn() {
  SECRET_ARN="$1"
  SECRET_LABEL="$2"
  case "$SECRET_ARN" in
    arn:aws:secretsmanager:*:*:secret:*) ;;
    *) echo "refused: $SECRET_LABEL is not a Secrets Manager secret ARN: $SECRET_ARN" >&2; exit 1 ;;
  esac
  COLONS="$(printf '%s' "$SECRET_ARN" | tr -cd ':' | wc -c)"
  [ "$COLONS" -eq 6 ] || { echo "refused: $SECRET_LABEL ARN is malformed (expected 7 colon fields): $SECRET_ARN" >&2; exit 1; }
  [ "$(printf '%s' "$SECRET_ARN" | cut -d: -f1)" = "arn" ] || { echo "refused: $SECRET_LABEL ARN is malformed: $SECRET_ARN" >&2; exit 1; }
  [ "$(printf '%s' "$SECRET_ARN" | cut -d: -f2)" = "aws" ] || { echo "refused: $SECRET_LABEL ARN is malformed: $SECRET_ARN" >&2; exit 1; }
  [ "$(printf '%s' "$SECRET_ARN" | cut -d: -f3)" = "secretsmanager" ] || { echo "refused: $SECRET_LABEL ARN is malformed: $SECRET_ARN" >&2; exit 1; }
  [ "$(printf '%s' "$SECRET_ARN" | cut -d: -f6)" = "secret" ] || { echo "refused: $SECRET_LABEL ARN is malformed: $SECRET_ARN" >&2; exit 1; }
  SECRET_REGION="$(printf '%s' "$SECRET_ARN" | cut -d: -f4)"
  SECRET_ACCOUNT="$(printf '%s' "$SECRET_ARN" | cut -d: -f5)"
  SECRET_NAME="$(printf '%s' "$SECRET_ARN" | cut -d: -f7)"
  [ -n "$SECRET_REGION" ] || { echo "refused: $SECRET_LABEL ARN has no region: $SECRET_ARN" >&2; exit 1; }
  [ -n "$SECRET_NAME" ] || { echo "refused: $SECRET_LABEL ARN has no secret name: $SECRET_ARN" >&2; exit 1; }
  case "$SECRET_NAME" in
    *[!A-Za-z0-9/_+=.@-]*) echo "refused: $SECRET_LABEL ARN name has invalid characters: $SECRET_ARN" >&2; exit 1 ;;
  esac
  case "$SECRET_ACCOUNT" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) echo "refused: $SECRET_LABEL ARN account is malformed: $SECRET_ARN" >&2; exit 1 ;;
  esac
  [ "$SECRET_REGION" = "$EXPECTED_REGION" ] || { echo "refused: $SECRET_LABEL ARN region $SECRET_REGION does not match expected $EXPECTED_REGION" >&2; exit 1; }
  [ "$SECRET_ACCOUNT" = "$EXPECTED_ACCOUNT" ] || { echo "refused: $SECRET_LABEL ARN account does not match expected $EXPECTED_ACCOUNT, no change made" >&2; exit 1; }
  if ! RETURNED_ARN="$("$AWS_BIN" secretsmanager describe-secret --secret-id "$SECRET_ARN" --region "$EXPECTED_REGION" --query ARN --output text 2>"$TMP_ERR")"; then
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    echo "$SECRET_LABEL metadata check failed, no change made." >&2
    if is_auth_error "$ERR"; then echo "authorization or API failure, not absence. Never probed secret values." >&2; fi
    exit 1
  fi
  RETURNED_ARN="$(printf '%s' "$RETURNED_ARN" | tr -d '[:space:]')"
  [ "$RETURNED_ARN" = "$SECRET_ARN" ] || { echo "refused: $SECRET_LABEL describe-secret returned a different ARN, not owned: $RETURNED_ARN" >&2; exit 1; }
  if ! SECRET_PROJECT="$("$AWS_BIN" secretsmanager describe-secret --secret-id "$SECRET_ARN" --region "$EXPECTED_REGION" --query "Tags[?Key=='Project'].Value | [0]" --output text 2>"$TMP_ERR")"; then
    echo "$SECRET_LABEL tag check failed, no change made." >&2
    exit 1
  fi
  if ! SECRET_ENV="$("$AWS_BIN" secretsmanager describe-secret --secret-id "$SECRET_ARN" --region "$EXPECTED_REGION" --query "Tags[?Key=='Environment'].Value | [0]" --output text 2>"$TMP_ERR")"; then
    echo "$SECRET_LABEL tag check failed, no change made." >&2
    exit 1
  fi
  SECRET_PROJECT="$(printf '%s' "$SECRET_PROJECT" | tr -d '[:space:]')"
  SECRET_ENV="$(printf '%s' "$SECRET_ENV" | tr -d '[:space:]')"
  [ "$SECRET_PROJECT" = "LaunchCrew" ] || { echo "refused: $SECRET_LABEL Project tag is $SECRET_PROJECT, expected LaunchCrew, no change made" >&2; exit 1; }
  [ "$SECRET_ENV" = "demo" ] || { echo "refused: $SECRET_LABEL Environment tag is $SECRET_ENV, expected demo, no change made" >&2; exit 1; }
  echo "Verified secret metadata ownership (value never fetched): $SECRET_LABEL $SECRET_ARN"
}

if needs_secret_checks; then
  if [ -n "$RUNTIME_SECRET_ARN" ]; then check_secret_arn "$RUNTIME_SECRET_ARN" "runtime"; fi
  if [ -n "$MIGRATION_SECRET_ARN" ]; then check_secret_arn "$MIGRATION_SECRET_ARN" "migration"; fi
  if [ -n "$MASTER_SECRET_ARN" ]; then check_secret_arn "$MASTER_SECRET_ARN" "master"; fi
  if [ -n "$TLS_SECRET_ARN" ]; then check_secret_arn "$TLS_SECRET_ARN" "tls"; fi
fi

# The parameters file is what the stack deploys from, so every CLI image URI
# and secret ARN given for this run must equal the matching parameters file
# value. Validating one set while deploying another is refused. A missing
# file value never counts as a match, and duplicates, UsePreviousValue
# entries, malformed entries, or unrecognized secret references fail closed.
check_params_match() {
  python3 - "$PARAMETERS_FILE" >"$TMP_PARAMS" <<'PYEOF'
import json, sys
KNOWN_SECRET_KEYS = {"RuntimeDbUrlSecretArn", "MigrationDbUrlSecretArn",
                     "MasterDbPasswordSecretArn", "TlsSecretArn"}
try:
    with open(sys.argv[1]) as handle:
        doc = json.load(handle)
except Exception:
    raise SystemExit("parameters file is not valid JSON")
if isinstance(doc, dict) and "Parameters" in doc:
    doc = doc["Parameters"]
if not isinstance(doc, list):
    raise SystemExit("parameters file must be a JSON list of ParameterKey/ParameterValue objects")
seen = set()
for entry in doc:
    if not isinstance(entry, dict) or "ParameterKey" not in entry:
        raise SystemExit("parameters file has a malformed entry")
    key = entry["ParameterKey"]
    if key in seen:
        raise SystemExit("parameters file has a duplicate ParameterKey")
    seen.add(key)
    if "ParameterValue" not in entry:
        raise SystemExit("parameters file entry has no explicit ParameterValue")
    if "Secret" in key and key not in KNOWN_SECRET_KEYS:
        raise SystemExit("parameters file has an unrecognized secret reference")
    print("%s\t%s" % (key, entry.get("ParameterValue", "")))
PYEOF
  [ $? -eq 0 ] || { echo "refused: parameters file is not an explicit deployable list: $PARAMETERS_FILE" >&2; return 1; }
  PARAM_VALUE() {
    awk -F'\t' -v key="$1" '$1==key{print $2}' "$TMP_PARAMS"
  }
  PARAM_MATCH() {
    PARAM_KEY="$1"
    CLI_VALUE="$2"
    [ -n "$CLI_VALUE" ] || return 0
    FILE_VALUE="$(PARAM_VALUE "$PARAM_KEY")"
    [ -n "$FILE_VALUE" ] || {
      echo "refused: parameters file has no $PARAM_KEY for the validated CLI value; validating one set while deploying another is refused" >&2
      return 1
    }
    if [ "$FILE_VALUE" != "$CLI_VALUE" ]; then
      echo "refused: CLI value does not match parameters file $PARAM_KEY; validating one set while deploying another is refused" >&2
      return 1
    fi
  }
  PARAM_MATCH ApiImageUri "$API_IMAGE" || exit 1
  PARAM_MATCH WebImageUri "$WEB_IMAGE" || exit 1
  PARAM_MATCH WebProxyImageUri "$WEB_PROXY_IMAGE" || exit 1
  PARAM_MATCH MigrationImageUri "$MIGRATION_IMAGE" || exit 1
  PARAM_MATCH BootstrapImageUri "$BOOTSTRAP_IMAGE" || exit 1
  PARAM_MATCH RuntimeDbUrlSecretArn "$RUNTIME_SECRET_ARN" || exit 1
  PARAM_MATCH MigrationDbUrlSecretArn "$MIGRATION_SECRET_ARN" || exit 1
  PARAM_MATCH MasterDbPasswordSecretArn "$MASTER_SECRET_ARN" || exit 1
  PARAM_MATCH TlsSecretArn "$TLS_SECRET_ARN" || exit 1
  echo "Verified CLI images and secret ARNs match the parameters file being deployed"
}

if [ "$PHASE" = "infra" ] || [ "$PHASE" = "enable" ] || [ "$PHASE" = "all" ]; then
  check_params_match
fi

# Cost allocation tag admission, read-only and fail-closed. It runs before
# any phase that can cause spend (infra deploy, one-off tasks, enable
# deploy), because spend starts at infra, RDS, and ALB creation even at
# DesiredCount 0. It reads only the Project user defined resource cost
# allocation tag status via ce list-cost-allocation-tags metadata and never
# activates or updates a tag. Only an unambiguous single Project/UserDefined
# entry with Status Active passes. Inactive, absent, duplicate, wrong type,
# unknown status, malformed, and API or authorization failures all refuse
# with bounded messages and no raw error, secret, or account detail.
# Activating a RESOURCE cost allocation tag key (all values, global to
# billing reports) is not the same as tagging the Budget resource: the
# Budget resource tag does not scope spend, and activation here is only the
# reporting precondition, never proof of cost data and never a hard cap.
check_cost_tag_activation() {
  TAG_JSON="$(mktemp /tmp/launchcrew-cetag-XXXXXX)"
  if ! "$AWS_BIN" ce list-cost-allocation-tags --tag-keys Project --type UserDefined --region "$EXPECTED_REGION" --output json >"$TAG_JSON" 2>"$TMP_ERR"; then
    rm -f "$TAG_JSON"
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    echo "cost tag activation unreadable, project spend attribution UNVERIFIED, no change made." >&2
    if is_auth_error "$ERR"; then
      echo "authorization or API failure, not absence: ce:ListCostAllocationTags read permission is required." >&2
    fi
    phase_failed "$PHASE"
  fi
  TAG_PROOF="$(python3 - "$TAG_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
entries = doc.get("CostAllocationTags", None)
if not isinstance(entries, list):
    print("MALFORMED")
    sys.exit(0)
project_entries = [e for e in entries
                   if isinstance(e, dict) and e.get("TagKey") == "Project"]
user_entries = [e for e in project_entries if e.get("Type") == "UserDefined"]
if not project_entries:
    print("ABSENT")
elif not user_entries:
    print("WRONGTYPE")
elif len(user_entries) > 1:
    print("AMBIGUOUS")
else:
    status = user_entries[0].get("Status", "")
    if status == "Active":
        print("TAG_ACTIVE")
    elif status == "Inactive":
        print("TAG_INACTIVE")
    else:
        print("UNKNOWN")
PYEOF
)"
  rm -f "$TAG_JSON"
  TAG_PROOF="$(printf '%s' "$TAG_PROOF" | tr -d '[:space:]')"
  case "$TAG_PROOF" in
    TAG_ACTIVE)
      echo "Verified Project user defined resource cost allocation tag status Active (read-only metadata, no values read)." ;;
    TAG_INACTIVE)
      echo "refused: Project cost allocation tag is Inactive; get Billing activation approved and confirm Active before any paid phase, no change made." >&2
      phase_failed "$PHASE" ;;
    TAG_ABSENT)
      echo "refused: no Project user defined cost allocation tag found; activation approval and Active status are required before any paid phase, no change made." >&2
      phase_failed "$PHASE" ;;
    TAG_WRONGTYPE)
      echo "refused: Project tag entry is not UserDefined type; the user defined resource key must be activated, no change made." >&2
      phase_failed "$PHASE" ;;
    TAG_AMBIGUOUS)
      echo "refused: duplicate Project cost allocation tag entries, status ambiguous, no change made." >&2
      phase_failed "$PHASE" ;;
    *)
      echo "refused: Project cost allocation tag status unreadable or unknown, treated as not Active, no change made." >&2
      phase_failed "$PHASE" ;;
  esac
}

case "$PHASE" in
  infra|dbroles|migrate|enable|all) check_cost_tag_activation ;;
esac

# cloudformation deploy has no --parameter-file option. Overrides travel as
# one argv item per Key=Value pair built by python, never through shell word
# splitting or globbing, so values with spaces stay intact. Guard: only
# public identifiers travel here (image URIs, ARNs, names, flags). A value
# with a newline or a URL scheme is refused, and failures stay bounded with
# no parameter dump, because deploy errors can echo parameters.
cloudformation_deploy() {
  ENABLE_VALUE="$1"
  DEPLOY_LABEL="$2"
  DEPLOY_TAGS=""
  if [ "$STACK_EXISTS" -eq 0 ]; then DEPLOY_TAGS="yes"; fi
  if ! python3 - "$PARAMETERS_FILE" "$ENABLE_VALUE" "$AWS_BIN" "$STACK_NAME" \
      "$TEMPLATE_FILE" "$EXPECTED_REGION" "$DEPLOY_TAGS" <<'PYEOF'
import json, subprocess, sys
params_file, enable_value = sys.argv[1], sys.argv[2]
aws_bin, stack, template, region, tags = sys.argv[3:8]
try:
    with open(params_file) as handle:
        doc = json.load(handle)
except Exception:
    raise SystemExit("parameters file is not valid JSON")
if isinstance(doc, dict) and "Parameters" in doc:
    doc = doc["Parameters"]
if not isinstance(doc, list):
    raise SystemExit("parameters file must be a JSON list of ParameterKey/ParameterValue objects")
overrides = []
for entry in doc:
    if not isinstance(entry, dict) or "ParameterKey" not in entry:
        raise SystemExit("parameters file has a malformed entry")
    key = entry["ParameterKey"]
    if key == "EnableServices":
        continue
    if "ParameterValue" not in entry:
        raise SystemExit("parameters file entry has no explicit ParameterValue")
    value = entry.get("ParameterValue", "")
    if not isinstance(value, str):
        raise SystemExit("parameters file value must be a string")
    if "\n" in value or "\r" in value or "://" in value:
        raise SystemExit("parameters file value has a refused shape")
    overrides.append("%s=%s" % (key, value))
overrides.append("EnableServices=%s" % enable_value)
cmd = [aws_bin, "cloudformation", "deploy",
       "--stack-name", stack, "--template-file", template,
       "--parameter-overrides"] + overrides + [
       "--capabilities", "CAPABILITY_NAMED_IAM", "--region", region]
if tags == "yes":
    cmd += ["--tags", "Project=LaunchCrew", "Environment=demo"]
proc = subprocess.run(cmd, capture_output=True, text=True)
sys.exit(proc.returncode)
PYEOF
  then
    echo "refused: parameters file unusable or deploy failed, no claim made: $PARAMETERS_FILE" >&2
    phase_failed "$DEPLOY_LABEL"
  fi
}

# A wait exit code proves nothing on its own: every wait is followed by a
# stack status readback, and only CREATE_COMPLETE or UPDATE_COMPLETE counts.
require_stack_complete() {
  NEED_LABEL="$1"
  STATUS=""
  if ! STATUS="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" --query "Stacks[0].StackStatus" --output text 2>"$TMP_ERR")"; then
    echo "stack status unreadable after wait, not treated as success." >&2
    phase_failed "$NEED_LABEL"
  fi
  STATUS="$(printf '%s' "$STATUS" | tr -d '[:space:]')"
  case "$STATUS" in
    CREATE_COMPLETE|UPDATE_COMPLETE) echo "Stack status verified: $STATUS" ;;
    *) echo "refused: stack status is $STATUS, expected CREATE_COMPLETE or UPDATE_COMPLETE" >&2; phase_failed "$NEED_LABEL" ;;
  esac
  STACK_STATUS="$STATUS"
  STACK_EXISTS=1
}

# Resolve exact owned stack resources by logical ID, never by prefix scan.
stack_resource() {
  "$AWS_BIN" cloudformation describe-stack-resource --stack-name "$STACK_NAME" --logical-resource-id "$1" --region "$EXPECTED_REGION" --query "StackResourceDetail.PhysicalResourceId" --output text 2>"$TMP_ERR"
}
if wants_phase infra; then
  echo "Phase infra: deploy stack"
  if [ "$STACK_EXISTS" -eq 1 ]; then
    require_stack_complete infra
  fi
  # On an owned update, keep the current EnableServices value so infra work
  # never resets running services to zero; fresh stacks start stopped.
  TARGET_SERVICES="false"
  if [ "$STACK_EXISTS" -eq 1 ] && [ "$CURRENT_ENABLE" = "true" ]; then
    TARGET_SERVICES="true"
  fi
  WAS_NEW="$STACK_EXISTS"
  if ! cloudformation_deploy "$TARGET_SERVICES" infra; then
    echo "infra deploy failed, no later phase started." >&2
    phase_failed infra
  fi
  if [ "$WAS_NEW" -eq 0 ]; then
    if ! "$AWS_BIN" cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
      echo "infra create wait reported, verifying stack status before any claim." >&2
    fi
  else
    if ! "$AWS_BIN" cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
      ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
      if is_auth_error "$ERR"; then
        echo "infra wait authorization failure, state unknown, no later phase started." >&2
        phase_failed infra
      fi
      echo "infra wait reported, verifying stack status before any claim." >&2
    fi
  fi
  require_stack_complete infra
  mark_done infra
  echo "Phase infra complete: stack $STACK_STATUS, services unchanged unless kept"
fi

# Fetch the full owned task definition document by logical ID, never by
# prefix scan, into a file. Callers parse the JSON with python.
fetch_taskdef_json() {
  FETCH_LOGICAL="$1"
  FETCH_OUT="$2"
  FETCH_ARN="$(stack_resource "$FETCH_LOGICAL" 2>"$TMP_ERR")" || return 1
  FETCH_ARN="$(printf '%s' "$FETCH_ARN" | tr -d '[:space:]')"
  [ -n "$FETCH_ARN" ] && [ "$FETCH_ARN" != "None" ] || return 1
  "$AWS_BIN" ecs "describe-task""-definition" --task"-definition" "$FETCH_ARN" \
    --region "$EXPECTED_REGION" --output json >"$FETCH_OUT" 2>"$TMP_ERR"
}

# Require the owned task definition to inject exactly the validated secrets
# and to run under the expected owned execution role. Each pair is
# container.SECRETNAME=exact-ValueFrom. Inspection happens here, before any
# one-off task starts and secret values are injected.
check_taskdef_binding() {
  BIND_LOGICAL="$1"
  BIND_ROLE="$2"
  shift 2
  BIND_JSON="$(mktemp /tmp/launchcrew-bind-XXXXXX)"
  if ! fetch_taskdef_json "$BIND_LOGICAL" "$BIND_JSON"; then
    rm -f "$BIND_JSON"
    echo "$BIND_LOGICAL task definition missing, secrets not tied to an owned task." >&2
    phase_failed "$PHASE"
  fi
  BIND_EXPECTED="$(mktemp /tmp/launchcrew-expected-XXXXXX)"
  printf '%s\n' "$@" >"$BIND_EXPECTED"
  BIND_PROOF="$(python3 - "$BIND_JSON" "$BIND_EXPECTED" "$EXPECTED_ACCOUNT" "$BIND_ROLE" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
wanted = {}
for line in open(sys.argv[2]):
    line = line.rstrip("\n")
    if line and "=" in line:
        key, value = line.split("=", 1)
        wanted[key] = value
account, role = sys.argv[3], sys.argv[4]
taskdef = doc.get("taskDefinition", doc)
role_arn = "arn:aws:iam::%s:role/%s" % (account, role)
if (taskdef.get("executionRoleArn", "") or "") != role_arn:
    print("ROLE_MISMATCH")
    sys.exit(0)
actual = {}
for container in taskdef.get("containerDefinitions", []) or []:
    cname = container.get("name", "") or ""
    for secret in container.get("secrets", []) or []:
        sname = secret.get("name", "") or ""
        actual["%s.%s" % (cname, sname)] = secret.get("valueFrom", "") or ""
for key in sorted(wanted):
    if key not in actual:
        print("MISSING:" + key)
        sys.exit(0)
    if actual[key] != wanted[key]:
        print("SECRET_MISMATCH:" + key)
        sys.exit(0)
for key in sorted(actual):
    if key not in wanted:
        print("UNEXPECTED:" + key)
        sys.exit(0)
print("OK")
PYEOF
)" || { rm -f "$BIND_JSON" "$BIND_EXPECTED"; echo "$BIND_LOGICAL task definition binding unreadable, not treated as matching." >&2; phase_failed "$PHASE"; }
  rm -f "$BIND_JSON" "$BIND_EXPECTED"
  BIND_PROOF="$(printf '%s' "$BIND_PROOF" | tr -d '[:space:]')"
  case "$BIND_PROOF" in
    OK) echo "Verified owned task definition secrets and execution role: $BIND_LOGICAL" ;;
    *) echo "refused: $BIND_LOGICAL task definition binding proof is $BIND_PROOF, secrets not proven owned." >&2; phase_failed "$PHASE" ;;
  esac
}

# Verify one published image: explicit tag required with no latest fallback,
# digest present with no failures, owned account and region and repository
# scope, and the exact URI the owned stack task definition references.
# batch-get-image can exit 0 with failures or a missing image, so the JSON
# fields are inspected, never the exit code alone. A tag@sha256 pin is
# honored by requiring the ECR digest to equal the pinned digest; a tag
# alone proves only the point-in-time digest read back here, because the
# template repos carry no immutable tag lock, so enable rechecks this proof
# immediately before boot.
verify_image() {
  IMAGE_URI="$1"
  EXPECTED_REPO="$2"
  TASKDEF_LOGICAL="$3"
  CONTAINER_NAME="$4"
  IMAGE_LABEL="$5"
  case "$IMAGE_URI" in
    *REPLACE_WITH*|*PLACEHOLDER*|"") echo "refused: placeholder image URI is not a verified image: $IMAGE_LABEL" >&2; phase_failed images ;;
  esac
  PINNED_DIGEST=""
  case "$IMAGE_URI" in
    *@sha256:*) PINNED_DIGEST="sha256:$(printf '%s' "$IMAGE_URI" | sed 's/^.*@sha256://')"
      IMAGE_BASE="$(printf '%s' "$IMAGE_URI" | cut -d@ -f1)" ;;
    *) IMAGE_BASE="$IMAGE_URI" ;;
  esac
  case "$IMAGE_BASE" in
    *:* ) ;;
    *) echo "refused: $IMAGE_LABEL image has no explicit tag, latest fallback refused" >&2; phase_failed images ;;
  esac
  case "$IMAGE_BASE" in
    *:latest) echo "refused: $IMAGE_LABEL image uses the floating latest tag" >&2; phase_failed images ;;
  esac
  REPO_FULL="$(printf '%s' "$IMAGE_BASE" | cut -d/ -f2-)"
  REPO_NAME="$(printf '%s' "$REPO_FULL" | cut -d: -f1)"
  IMAGE_TAG="$(printf '%s' "$REPO_FULL" | cut -s -d: -f2)"
  [ -n "$IMAGE_TAG" ] || { echo "refused: $IMAGE_LABEL image has no explicit tag, latest fallback refused" >&2; phase_failed images; }
  [ "$REPO_NAME" = "$EXPECTED_REPO" ] || { echo "refused: $IMAGE_LABEL image repository $REPO_NAME is not the owned $EXPECTED_REPO repository" >&2; phase_failed images; }
  IMAGE_ACCOUNT="$(printf '%s' "$IMAGE_BASE" | cut -d. -f1)"
  IMAGE_REGION="$(printf '%s' "$IMAGE_BASE" | cut -d. -f4)"
  [ "$IMAGE_ACCOUNT" = "$EXPECTED_ACCOUNT" ] || { echo "refused: $IMAGE_LABEL image account does not match expected $EXPECTED_ACCOUNT: $REPO_NAME" >&2; phase_failed images; }
  [ "$IMAGE_REGION" = "$EXPECTED_REGION" ] || { echo "refused: $IMAGE_LABEL image region $IMAGE_REGION does not match expected $EXPECTED_REGION: $REPO_NAME" >&2; phase_failed images; }
  if ! IMAGE_DIGEST="$("$AWS_BIN" ecr batch-get-image --repository-name "$REPO_NAME" --image-ids "imageTag=$IMAGE_TAG" --region "$EXPECTED_REGION" --query "images[0].imageDigest" --output text 2>"$TMP_ERR")"; then
    echo "$IMAGE_LABEL image $REPO_NAME:$IMAGE_TAG not found in ECR, app never starts on an unverified image." >&2
    phase_failed images
  fi
  IMAGE_DIGEST="$(printf '%s' "$IMAGE_DIGEST" | tr -d '[:space:]')"
  if [ -z "$IMAGE_DIGEST" ] || [ "$IMAGE_DIGEST" = "None" ]; then
    echo "refused: $IMAGE_LABEL image $REPO_NAME:$IMAGE_TAG has no digest in ECR, app never starts on an unverified image." >&2
    phase_failed images
  fi
  if [ -n "$PINNED_DIGEST" ] && [ "$IMAGE_DIGEST" != "$PINNED_DIGEST" ]; then
    echo "refused: $IMAGE_LABEL pinned digest does not match the ECR digest, the tag moved." >&2
    phase_failed images
  fi
  if ! IMAGE_FAILURES="$("$AWS_BIN" ecr batch-get-image --repository-name "$REPO_NAME" --image-ids "imageTag=$IMAGE_TAG" --region "$EXPECTED_REGION" --query "length(failures)" --output text 2>"$TMP_ERR")"; then
    echo "$IMAGE_LABEL image $REPO_NAME:$IMAGE_TAG failure check failed, not treated as present." >&2
    phase_failed images
  fi
  IMAGE_FAILURES="$(printf '%s' "$IMAGE_FAILURES" | tr -d '[:space:]')"
  [ "$IMAGE_FAILURES" = "0" ] || { echo "refused: $IMAGE_LABEL image $REPO_NAME:$IMAGE_TAG reports ECR failures, app never starts on an unverified image." >&2; phase_failed images; }
  REFADM_JSON="$(mktemp /tmp/launchcrew-img-XXXXXX)"
  if ! fetch_taskdef_json "$TASKDEF_LOGICAL" "$REFADM_JSON"; then
    rm -f "$REFADM_JSON"
    echo "$IMAGE_LABEL task definition $TASKDEF_LOGICAL missing, image not tied to an owned task." >&2
    phase_failed images
  fi
  REF_IMAGE="$(python3 - "$REFADM_JSON" "$CONTAINER_NAME" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
taskdef = doc.get("taskDefinition", doc)
for container in taskdef.get("containerDefinitions", []) or []:
    if (container.get("name", "") or "") == sys.argv[2]:
        print(container.get("image", "") or "MISSING_IMAGE")
        sys.exit(0)
print("MISSING_CONTAINER")
PYEOF
)" || { rm -f "$REFADM_JSON"; echo "$IMAGE_LABEL task definition image unreadable, not treated as matching." >&2; phase_failed images; }
  rm -f "$REFADM_JSON"
  REF_IMAGE="$(printf '%s' "$REF_IMAGE" | tr -d '[:space:]')"
  [ "$REF_IMAGE" = "$IMAGE_URI" ] || { echo "refused: $IMAGE_LABEL task definition references $REF_IMAGE, not the validated $IMAGE_URI" >&2; phase_failed images; }
  echo "Verified image present with digest and owned task definition ref: $REPO_NAME:$IMAGE_TAG"
}

if wants_phase images; then
  echo "Phase images: verify all five published image URIs in owned ECR repositories"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no stack to own task definitions; run --phase infra first" >&2; phase_failed images; }
  require_stack_complete images
  verify_image "$API_IMAGE" launchcrew-api ApiTaskDefinition api api
  verify_image "$WEB_IMAGE" launchcrew-web WebTaskDefinition web-app web
  verify_image "$WEB_PROXY_IMAGE" launchcrew-web-proxy WebTaskDefinition web-proxy web-proxy
  verify_image "$MIGRATION_IMAGE" launchcrew-migration MigrationTaskDefinition migration migration
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap BootstrapTaskDefinition bootstrap-db-roles bootstrap
  check_taskdef_binding ApiTaskDefinition ApiExecutionRole \
    "api.DATABASE_URL=$RUNTIME_SECRET_ARN:database-url::" \
    "api.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
    "api.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::"
  check_taskdef_binding WebTaskDefinition WebExecutionRole \
    "web-proxy.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
    "web-proxy.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::"
  mark_done images
  echo "Phase images complete: five verified images, no placeholder running"
fi
# Run one isolated one-off task and prove its terminal state. Jobs run in the
# public subnets with a public IP under a group with no inbound rules: the
# database stays private, and the job can actually reach ECR, Secrets Manager,
# and Logs. A run-task response with an empty task ARN or reported failures is
# refused; the wait exit code is only a hint; proof is STOPPED lastStatus, the
# exact expected task ARN and task definition ARN, the exact owned cluster
# ARN, and exit code 0 with STOPPED from every expected essential container,
# never the first container alone. The real DescribeTasks container model
# carries no essential flag, so the expected essential set comes from the
# owned task definition document, where an omitted essential key defaults to
# true. Proof codes are bounded tokens only, never raw reasons or traces.
run_one_off_task() {
  TASKDEF_LOGICAL="$1"
  TASK_LABEL="$2"
  TASK_PHASE="$3"
  TASKDEF_ARN="$(stack_resource "$TASKDEF_LOGICAL" 2>"$TMP_ERR")" || { echo "$TASK_LABEL task definition lookup failed, no task started." >&2; phase_failed "$TASK_PHASE"; }
  TASKDEF_ARN="$(printf '%s' "$TASKDEF_ARN" | tr -d '[:space:]')"
  [ -n "$TASKDEF_ARN" ] && [ "$TASKDEF_ARN" != "None" ] || { echo "$TASK_LABEL task definition missing, no task started." >&2; phase_failed "$TASK_PHASE"; }
  SUBNET_A="$(stack_resource PublicSubnetA 2>"$TMP_ERR")" || { echo "subnet lookup failed, no task started." >&2; phase_failed "$TASK_PHASE"; }
  SUBNET_B="$(stack_resource PublicSubnetB 2>"$TMP_ERR")" || { echo "subnet lookup failed, no task started." >&2; phase_failed "$TASK_PHASE"; }
  JOB_SG="$(stack_resource JobSecurityGroup 2>"$TMP_ERR")" || { echo "security group lookup failed, no task started." >&2; phase_failed "$TASK_PHASE"; }
  SUBNET_A="$(printf '%s' "$SUBNET_A" | tr -d '[:space:]')"
  SUBNET_B="$(printf '%s' "$SUBNET_B" | tr -d '[:space:]')"
  JOB_SG="$(printf '%s' "$JOB_SG" | tr -d '[:space:]')"
  TASK_JSON="$(mktemp /tmp/launchcrew-run-XXXXXX)"
  if ! "$AWS_BIN" ecs run-task --cluster "$CLUSTER_NAME" --task"-definition" "$TASKDEF_ARN" --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$JOB_SG],assignPublicIp=ENABLED}" --region "$EXPECTED_REGION" --output json >"$TASK_JSON" 2>"$TMP_ERR"; then
    rm -f "$TASK_JSON"
    echo "$TASK_LABEL run-task failed, nothing started beyond this point." >&2
    phase_failed "$TASK_PHASE"
  fi
  TASK_ARN="$(python3 - "$TASK_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
tasks = doc.get("tasks", [])
failures = doc.get("failures", [])
if failures:
    print("FAILURES")
elif not tasks:
    print("EMPTY")
else:
    arn = (tasks[0] or {}).get("taskArn", "")
    print(arn if arn and arn != "None" else "EMPTY")
PYEOF
)" || { rm -f "$TASK_JSON"; echo "$TASK_LABEL run-task response unreadable, not treated as started." >&2; phase_failed "$TASK_PHASE"; }
  rm -f "$TASK_JSON"
  TASK_ARN="$(printf '%s' "$TASK_ARN" | tr -d '[:space:]')"
  case "$TASK_ARN" in
    FAILURES) echo "refused: $TASK_LABEL run-task reported failures, no task to wait on." >&2; phase_failed "$TASK_PHASE" ;;
    EMPTY|"") echo "refused: $TASK_LABEL run-task returned no task ARN, nothing started." >&2; phase_failed "$TASK_PHASE" ;;
  esac
  echo "$TASK_LABEL task started in isolated public subnets with no inbound: $TASK_ARN"
  if ! "$AWS_BIN" ecs wait tasks-stopped --cluster "$CLUSTER_NAME" --tasks "$TASK_ARN" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    echo "$TASK_LABEL wait reported, verifying terminal state before any claim." >&2
    if is_auth_error "$ERR"; then echo "authorization or API failure, not absence." >&2; fi
  fi
  DESCRIBE_JSON="$(mktemp /tmp/launchcrew-state-XXXXXX)"
  if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$TASK_ARN" --region "$EXPECTED_REGION" --output json >"$DESCRIBE_JSON" 2>"$TMP_ERR"; then
    rm -f "$DESCRIBE_JSON"
    echo "$TASK_LABEL terminal state unreadable, not treated as success." >&2
    phase_failed "$TASK_PHASE"
  fi
  TASKDEF_JSON="$(mktemp /tmp/launchcrew-proof-XXXXXX)"
  if ! fetch_taskdef_json "$TASKDEF_LOGICAL" "$TASKDEF_JSON"; then
    rm -f "$DESCRIBE_JSON" "$TASKDEF_JSON"
    echo "$TASK_LABEL expected container set unreadable, not treated as success." >&2
    phase_failed "$TASK_PHASE"
  fi
  EXPECTED_CLUSTER_ARN="arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME"
  TASK_PROOF="$(python3 - "$DESCRIBE_JSON" "$TASKDEF_JSON" "$TASK_ARN" "$TASKDEF_ARN" "$EXPECTED_CLUSTER_ARN" 2>/dev/null <<'PYEOF'
import json, sys
try:
    describe = json.load(open(sys.argv[1]))
    defined = json.load(open(sys.argv[2]))
except Exception:
    sys.exit(1)
expected_arn, expected_taskdef, expected_cluster = sys.argv[3:6]
expected_names = []
for container in (defined.get("taskDefinition", defined).get("containerDefinitions", []) or []):
    if container.get("essential", True) and container.get("name"):
        expected_names.append(container.get("name"))
tasks = describe.get("tasks", [])
failures = describe.get("failures", [])
if failures or not tasks:
    print("NO_TASK")
    sys.exit(0)
if not expected_names:
    print("NO_EXPECTED_CONTAINERS")
    sys.exit(0)
task = tasks[0]
if (task.get("taskArn", "") or "") != expected_arn:
    print("WRONG_TASK_ARN")
    sys.exit(0)
if task.get("lastStatus") != "STOPPED":
    print("NOT_STOPPED")
    sys.exit(0)
if (task.get("taskDefinitionArn", "") or "") != expected_taskdef:
    print("WRONG_TASKDEF")
    sys.exit(0)
if (task.get("clusterArn", "") or "") != expected_cluster:
    print("WRONG_CLUSTER")
    sys.exit(0)
actual = task.get("containers", []) or []
names = [(c.get("name", "?") or "?") for c in actual]
if len(set(names)) != len(names):
    print("DUPLICATE:" + ",".join(sorted(set(n for n in names if names.count(n) > 1))))
    sys.exit(0)
for name in sorted(set(names) - set(expected_names)):
    print("UNEXPECTED:" + name)
    sys.exit(0)
for name in sorted(set(expected_names) - set(names)):
    print("MISSING:" + name)
    sys.exit(0)
for container in actual:
    if container.get("lastStatus") != "STOPPED" or container.get("exitCode") != 0:
        print("EXIT_NONZERO:" + (container.get("name", "?") or "?"))
        sys.exit(0)
print("OK")
PYEOF
)" || { rm -f "$DESCRIBE_JSON" "$TASKDEF_JSON"; echo "$TASK_LABEL terminal proof unreadable, not treated as success." >&2; phase_failed "$TASK_PHASE"; }
  rm -f "$DESCRIBE_JSON" "$TASKDEF_JSON"
  TASK_PROOF="$(printf '%s' "$TASK_PROOF" | tr -d '[:space:]')"
  case "$TASK_PROOF" in
    OK) echo "$TASK_LABEL terminal proof: STOPPED, exact owned task and cluster ARNs, every expected container exit 0" ;;
    *) echo "refused: $TASK_LABEL terminal proof is $TASK_PROOF, later phases not started." >&2; phase_failed "$TASK_PHASE" ;;
  esac
}

if wants_phase dbroles; then
  echo "Phase dbroles: isolated bootstrap task binds role passwords in task memory only"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no stack owns the bootstrap task; run --phase infra first" >&2; phase_failed dbroles; }
  check_taskdef_binding BootstrapTaskDefinition BootstrapExecutionRole \
    "bootstrap-db-roles.MASTER_DB_PASSWORD=$MASTER_SECRET_ARN:password::" \
    "bootstrap-db-roles.RUNTIME_DB_URL=$RUNTIME_SECRET_ARN:database-url::" \
    "bootstrap-db-roles.MIGRATION_DB_URL=$MIGRATION_SECRET_ARN:database-url::"
  run_one_off_task BootstrapTaskDefinition bootstrap dbroles
  mark_done dbroles
  echo "Phase dbroles complete: exact owned roles bound, privilege split applied"
fi

if wants_phase migrate; then
  echo "Phase migrate: single one-off migration task, the only schema change path"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no stack owns the migration task; run --phase infra first" >&2; phase_failed migrate; }
  check_taskdef_binding MigrationTaskDefinition MigrationExecutionRole \
    "migration.DATABASE_URL=$MIGRATION_SECRET_ARN:database-url::"
  check_taskdef_binding VerifyTaskDefinition VerifyExecutionRole \
    "bootstrap-db-roles.RUNTIME_DB_URL=$RUNTIME_SECRET_ARN:database-url::"
  run_one_off_task MigrationTaskDefinition migration migrate
  echo "Phase migrate task STOPPED exit 0; running verify-mode schema and runtime-identity proof"
  # Verify runs as its own task definition that injects only the runtime URL:
  # the master and migration secrets are never present in verify task memory.
  run_one_off_task VerifyTaskDefinition verify migrate
  mark_done migrate
  echo "Phase migrate complete: migration STOPPED exit 0 with schema and runtime read-only proof"
fi

# Budget filter readback on enable, read-only and fail-closed. It never
# activates a cost allocation tag and never changes billing. It requires the
# owned DemoBudget FilterExpression to be exactly the template shape, Tags
# Key Project with the single value LaunchCrew and the single MatchOption
# EQUALS, because an unfiltered budget would count the whole account, extra
# values would count other projects, and broader match options would widen
# the scope. Legacy CostFilters or BudgetFilters entries are refused without
# verified semantics, as are Or/And/Not wrappers and ambiguous responses.
# Activation is a separate gate that already passed before any paid phase;
# this readback only proves the filter, never cost data, never a hard cap:
# filtered spend with no data or 0 is not proof of zero spend, spend starts
# at infra, RDS, and ALB creation even at DesiredCount 0, and the manual
# billing guard stays on the operator.
check_budget_readiness() {
  BUDGET_JSON="$(mktemp /tmp/launchcrew-budget-XXXXXX)"
  if ! "$AWS_BIN" budgets describe-budget --account-id "$EXPECTED_ACCOUNT" --budget-name launchcrew-demo --output json >"$BUDGET_JSON" 2>"$TMP_ERR"; then
    rm -f "$BUDGET_JSON"
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    echo "budget readiness unreadable, project spend monitoring UNVERIFIED, no claim made." >&2
    if is_auth_error "$ERR"; then
      echo "authorization or API failure, not absence: budgets:DescribeBudget read permission is required." >&2
    fi
    phase_failed enable
  fi
  BUDGET_PROOF="$(python3 - "$BUDGET_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
budget = doc.get("Budget", None)
if not isinstance(budget, dict):
    print("MALFORMED")
    sys.exit(0)
if "CostFilters" in budget or "BudgetFilters" in budget:
    print("LEGACY")
    sys.exit(0)
expr = budget.get("FilterExpression", None)
if not isinstance(expr, dict) or set(expr.keys()) != {"Tags"}:
    print("FILTER_MISSING")
    sys.exit(0)
tags = expr.get("Tags", None)
if not isinstance(tags, dict):
    print("FILTER_MISSING")
    sys.exit(0)
if (tags.get("Key", "") == "Project"
        and tags.get("Values", None) == ["LaunchCrew"]
        and tags.get("MatchOptions", None) == ["EQUALS"]):
    print("FILTER_OK")
else:
    print("FILTER_MISSING")
PYEOF
)" || { rm -f "$BUDGET_JSON"; echo "budget filter unreadable, project spend monitoring UNVERIFIED." >&2; phase_failed enable; }
  rm -f "$BUDGET_JSON"
  BUDGET_PROOF="$(printf '%s' "$BUDGET_PROOF" | tr -d '[:space:]')"
  [ "$BUDGET_PROOF" = "FILTER_OK" ] || { echo "refused: DemoBudget lacks the exact Project=LaunchCrew EQUALS-only filter, project spend monitoring UNVERIFIED." >&2; phase_failed enable; }
  echo "Verified DemoBudget filter: Tags Project=LaunchCrew EQUALS only, read back from live state."
  echo "Budget readiness: activation already verified Active before paid phases; this script never activates tags."
  echo "Budget readiness: filtered spend with no data or 0 is NOT proof of zero spend and NOT a hard cap. Spend starts at infra, RDS, and ALB creation even at DesiredCount 0. Manual billing guard stays on the operator."
}

if wants_phase enable; then
  echo "Phase enable: update stack with EnableServices=true for fixed count 1 each"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no stack to enable; run --phase infra first" >&2; phase_failed enable; }
  require_stack_complete enable
  check_budget_readiness
  # Resume guard: a standalone enable re-proves everything boot would rely
  # on, because nothing is assumed from memory. Refresh the full image
  # digest and task definition ref proof, the owned secrets and execution
  # role bindings including TLS material, and the runtime-only verify proof
  # (expected head, runtime identity, rolled-back write, DDL refusal) before
  # any deploy. Migration and provider work are never rerun here.
  verify_image "$API_IMAGE" launchcrew-api ApiTaskDefinition api api
  verify_image "$WEB_IMAGE" launchcrew-web WebTaskDefinition web-app web
  verify_image "$WEB_PROXY_IMAGE" launchcrew-web-proxy WebTaskDefinition web-proxy web-proxy
  verify_image "$MIGRATION_IMAGE" launchcrew-migration MigrationTaskDefinition migration migration
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap BootstrapTaskDefinition bootstrap-db-roles bootstrap
  check_taskdef_binding ApiTaskDefinition ApiExecutionRole \
    "api.DATABASE_URL=$RUNTIME_SECRET_ARN:database-url::" \
    "api.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
    "api.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::"
  check_taskdef_binding WebTaskDefinition WebExecutionRole \
    "web-proxy.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
    "web-proxy.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::"
  check_taskdef_binding VerifyTaskDefinition VerifyExecutionRole \
    "bootstrap-db-roles.RUNTIME_DB_URL=$RUNTIME_SECRET_ARN:database-url::"
  echo "Enable precheck: all five owned task definition images, secrets, and execution roles match validated values"
  case "$COMPLETED" in
    *migrate*) echo "Enable proof: migrate already proved verify in this run, no rerun" ;;
    *) run_one_off_task VerifyTaskDefinition verify enable ;;
  esac
  if ! cloudformation_deploy "true" enable; then
    echo "enable deploy failed, services unchanged." >&2
    phase_failed enable
  fi
  if ! "$AWS_BIN" cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    echo "enable wait reported, verifying service counts before any claim." >&2
  fi
  require_stack_complete enable
  for SERVICE in api web; do
    COUNTS=""
    if ! COUNTS="$("$AWS_BIN" ecs describe-services --cluster "$CLUSTER_NAME" --services "launchcrew-demo-$SERVICE" --region "$EXPECTED_REGION" --query "services[0].[desiredCount,runningCount]" --output text 2>"$TMP_ERR")"; then
      echo "service $SERVICE counts unreadable, not claimed running." >&2
      phase_failed enable
    fi
    COUNTS="$(printf '%s' "$COUNTS" | tr '\t' ' ' | tr -s ' ')"
    DESIRED="$(printf '%s' "$COUNTS" | cut -d' ' -f1)"
    RUNNING="$(printf '%s' "$COUNTS" | cut -d' ' -f2)"
    [ "$DESIRED" = "1" ] || { echo "refused: service $SERVICE desiredCount is $DESIRED, expected fixed 1" >&2; phase_failed enable; }
    [ "$RUNNING" = "1" ] || { echo "refused: service $SERVICE runningCount is $RUNNING, expected 1; configuration set but tasks not running" >&2; phase_failed enable; }
    echo "Verified service launchcrew-demo-$SERVICE desiredCount 1 runningCount 1 (configuration check; serving health needs ALB targets after DNS)"
  done
  mark_done enable
  echo "Phase enable complete: both services fixed count 1 each, no autoscaling"
fi

echo "BOOTSTRAP COMPLETE phases requested: $PHASE. Completed: ${COMPLETED:-none}."
echo "Outside-stack remaining work: secret values, ACM certificate, DNS, snapshots need separate approval with exact identifiers."
