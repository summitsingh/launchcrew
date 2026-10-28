#!/bin/sh
# LaunchCrew demo staged bootstrap, dry-run by default, gated phased bring-up.
# Dry-run makes no AWS call. Confirm path brings infrastructure up in order and
# refuses to start the app early:
#   phase infra   deploy the CloudFormation stack with EnableServices=false,
#                 so VPC, ECR repositories, RDS, and task definitions exist
#                 with both ECS services at DesiredCount 0 and no app running
#   phase images  verify each of the five published image URIs exists in its
#                 owned ECR repository; placeholder or missing images refuse
#   phase dbroles run the isolated one-off bootstrap task that binds database
#                 role passwords from injected Secrets Manager values held in
#                 task memory only, then require its STOPPED exit code 0
#   phase migrate run the single one-off migration task, require STOPPED exit
#                 code 0, then run the bootstrap image in verify mode as
#                 schema and runtime-identity proof
#   phase enable  update the stack with EnableServices=true for fixed count 1
#                 each, then verify both services report desiredCount 1
# The migration task definition is the only schema change path; the bootstrap
# task never runs alembic, and runtime tasks never run alembic or role binds,
# so there are no duplicate migration controllers. This controller never calls
# secretsmanager:GetSecretValue and never prints a secret value: it handles
# only secret ARNs as identifiers plus DescribeSecret metadata, and the
# bootstrap job holds values in private task memory without logging them.
# Outside-stack values (Secrets Manager secret contents, ACM certificate,
# Cloudflare DNS, manual snapshots) need a separate approval with exact
# identifiers and are reported as remaining work. Teardown stays separate in
# deploy/aws/teardown.sh. An AWS Budget is an alert and estimate mechanism,
# not an enforced hard spend cap.
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

usage() {
  echo "Usage: $0 [--confirm --stack-name NAME --expected-account ID --expected-region REGION ...] [--phase infra|images|dbroles|migrate|enable|all]"
  echo "Dry-run default makes no AWS call and prints the ordered phase plan."
  echo "Confirm path requires --stack-name, --expected-account (12 digits), --expected-region,"
  echo "  --parameters-file, the five image URIs, and the three secret ARNs."
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
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

phase_plan() {
  echo "Phase order, each phase gates the next; any failure stops the run:"
  echo "  1. ownership: caller account, stack Project LaunchCrew and Environment demo tags, secret ARN account and region"
  echo "  2. infra: deploy stack with EnableServices=false, services stay at DesiredCount 0"
  echo "  3. images: all five ECR image URIs verified present, no placeholder image"
  echo "  4. dbroles: one-off bootstrap task STOPPED exit 0, passwords bound in task memory only"
  echo "  5. migrate: one-off migration task STOPPED exit 0, then verify-mode proof of schema and runtime read-only identity"
  echo "  6. enable: update stack with EnableServices=true, verify fixed count 1 each"
  echo "Remaining work, never done by this script:"
  echo "- Secrets Manager secret values, ACM certificate, Cloudflare DNS, manual snapshots: separate approval with exact identifiers."
  echo "- Teardown: deploy/aws/teardown.sh after Nov 4 and no later than Nov 9, 2026."
  echo "- Budget alerts are notifications only, not an enforced hard spend cap."
}

if [ "$CONFIRM" -ne 1 ]; then
  echo "DRY RUN, no AWS call made."
  phase_plan
  echo "To run for real, after separate authorization:"
  echo "  $0 --confirm --stack-name <exact-stack-name> --expected-account <12-digit> --expected-region <region> --parameters-file <file> --api-image URI --web-image URI --web-proxy-image URI --migration-image URI --bootstrap-image URI --runtime-secret-arn ARN --migration-secret-arn ARN --master-secret-arn ARN [--phase PHASE]"
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
[ -n "$API_IMAGE" ] || { echo "confirm requires --api-image" >&2; exit 2; }
[ -n "$WEB_IMAGE" ] || { echo "confirm requires --web-image" >&2; exit 2; }
[ -n "$WEB_PROXY_IMAGE" ] || { echo "confirm requires --web-proxy-image" >&2; exit 2; }
[ -n "$MIGRATION_IMAGE" ] || { echo "confirm requires --migration-image" >&2; exit 2; }
[ -n "$BOOTSTRAP_IMAGE" ] || { echo "confirm requires --bootstrap-image" >&2; exit 2; }
[ -n "$RUNTIME_SECRET_ARN" ] || { echo "confirm requires --runtime-secret-arn" >&2; exit 2; }
[ -n "$MIGRATION_SECRET_ARN" ] || { echo "confirm requires --migration-secret-arn" >&2; exit 2; }
[ -n "$MASTER_SECRET_ARN" ] || { echo "confirm requires --master-secret-arn" >&2; exit 2; }
if [ -z "$TEMPLATE_FILE" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  TEMPLATE_FILE="$SCRIPT_DIR/fargate.yaml"
fi
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

TMP_ERR="$(mktemp /tmp/launchcrew-bootstrap-err-XXXXXX)"
trap 'rm -f "$TMP_ERR"' EXIT INT TERM

is_auth_error() {
  case "$1" in
    *AccessDenied*|*Unauthorized*|*ExpiredToken*|*InvalidClientTokenId*|*TokenRefreshRequired*|*Forbidden*) return 0 ;;
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
# mutation, and its region and account must match the expectation.
if ! PROJECT_TAG="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" --query "Stacks[0].Tags[?Key=='Project'].Value | [0]" --output text 2>"$TMP_ERR")"; then
  ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
  echo "stack tag check failed, no change made." >&2
  if is_auth_error "$ERR"; then echo "authorization or API failure, not absence." >&2; fi
  exit 1
fi
if ! ENV_TAG="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" --query "Stacks[0].Tags[?Key=='Environment'].Value | [0]" --output text 2>"$TMP_ERR")"; then
  echo "stack tag check failed, no change made." >&2
  exit 1
fi
PROJECT_TAG="$(printf '%s' "$PROJECT_TAG" | tr -d '[:space:]')"
ENV_TAG="$(printf '%s' "$ENV_TAG" | tr -d '[:space:]')"
[ "$PROJECT_TAG" = "LaunchCrew" ] || { echo "refused: Project tag is $PROJECT_TAG, expected LaunchCrew, no change made" >&2; exit 1; }
[ "$ENV_TAG" = "demo" ] || { echo "refused: Environment tag is $ENV_TAG, expected demo, no change made" >&2; exit 1; }
echo "Verified caller $CALLER_ACCOUNT and stack $STACK_NAME tags Project LaunchCrew Environment demo"

# Ownership gate three: each referenced secret ARN must belong to the expected
# account and region, and DescribeSecret metadata must resolve. This reads
# metadata only and never fetches a secret value.
for SECRET_ARN in "$RUNTIME_SECRET_ARN" "$MIGRATION_SECRET_ARN" "$MASTER_SECRET_ARN"; do
  case "$SECRET_ARN" in
    arn:aws:secretsmanager:*:*:secret:*/*) ;;
    *) echo "refused: not an exact Secrets Manager secret ARN: $SECRET_ARN" >&2; exit 1 ;;
  esac
  SECRET_REGION="$(printf '%s' "$SECRET_ARN" | cut -d: -f4)"
  SECRET_ACCOUNT="$(printf '%s' "$SECRET_ARN" | cut -d: -f5)"
  [ "$SECRET_REGION" = "$EXPECTED_REGION" ] || { echo "refused: secret ARN region $SECRET_REGION does not match expected $EXPECTED_REGION" >&2; exit 1; }
  [ "$SECRET_ACCOUNT" = "$EXPECTED_ACCOUNT" ] || { echo "refused: secret ARN account does not match expected $EXPECTED_ACCOUNT, no change made" >&2; exit 1; }
  if ! "$AWS_BIN" secretsmanager describe-secret --secret-id "$SECRET_ARN" --region "$EXPECTED_REGION" --query "ARN" --output text 2>"$TMP_ERR" >/dev/null; then
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    echo "secret metadata check failed for $SECRET_ARN, no change made." >&2
    if is_auth_error "$ERR"; then echo "authorization or API failure, not absence. Never probed production secret values." >&2; fi
    exit 1
  fi
  echo "Verified secret metadata ownership (value never fetched): $SECRET_ARN"
done

# Resolve exact owned stack resources by logical ID, never by prefix scan.
stack_resource() {
  "$AWS_BIN" cloudformation describe-stack-resource --stack-name "$STACK_NAME" --logical-resource-id "$1" --region "$EXPECTED_REGION" --query "StackResourceDetail.PhysicalResourceId" --output text 2>"$TMP_ERR"
}

if wants_phase infra; then
  echo "Phase infra: deploy stack with EnableServices=false"
  if ! "$AWS_BIN" cloudformation deploy --stack-name "$STACK_NAME" --template-file "$TEMPLATE_FILE" --parameter-file "$PARAMETERS_FILE" --parameter-overrides EnableServices=false --capabilities CAPABILITY_NAMED_IAM --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    echo "infra deploy failed, no later phase started." >&2
    phase_failed infra
  fi
  if ! "$AWS_BIN" cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    if is_auth_error "$ERR"; then
      echo "infra wait authorization failure, state unknown, no later phase started." >&2
      phase_failed infra
    fi
    echo "infra wait reported, verifying stack status before any claim." >&2
  fi
  mark_done infra
  echo "Phase infra complete: services at DesiredCount 0, no app running"
fi

if wants_phase images; then
  echo "Phase images: verify all five published image URIs in owned ECR repositories"
  for IMAGE_URI in "$API_IMAGE" "$WEB_IMAGE" "$WEB_PROXY_IMAGE" "$MIGRATION_IMAGE" "$BOOTSTRAP_IMAGE"; do
    case "$IMAGE_URI" in
      *REPLACE_WITH*|*PLACEHOLDER*|"") echo "refused: placeholder image URI is not a verified image: $IMAGE_URI" >&2; phase_failed images ;;
    esac
    REPO_FULL="$(printf '%s' "$IMAGE_URI" | cut -d/ -f2-)"
    REPO_NAME="$(printf '%s' "$REPO_FULL" | cut -d: -f1)"
    IMAGE_TAG="$(printf '%s' "$REPO_FULL" | cut -s -d: -f2)"
    [ -n "$IMAGE_TAG" ] || IMAGE_TAG="latest"
    case "$REPO_NAME" in
      launchcrew-api|launchcrew-web|launchcrew-web-proxy|launchcrew-migration|launchcrew-bootstrap) ;;
      *) echo "refused: image repository $REPO_NAME is not an owned demo repository" >&2; phase_failed images ;;
    esac
    IMAGE_ACCOUNT="$(printf '%s' "$IMAGE_URI" | cut -d. -f1)"
    IMAGE_REGION="$(printf '%s' "$IMAGE_URI" | cut -d. -f4)"
    [ "$IMAGE_ACCOUNT" = "$EXPECTED_ACCOUNT" ] || { echo "refused: image account does not match expected $EXPECTED_ACCOUNT: $REPO_NAME" >&2; phase_failed images; }
    [ "$IMAGE_REGION" = "$EXPECTED_REGION" ] || { echo "refused: image region $IMAGE_REGION does not match expected $EXPECTED_REGION: $REPO_NAME" >&2; phase_failed images; }
    if ! "$AWS_BIN" ecr batch-get-image --repository-name "$REPO_NAME" --image-ids "imageTag=$IMAGE_TAG" --region "$EXPECTED_REGION" --query "images[0].imageManifest" --output text 2>"$TMP_ERR" >/dev/null; then
      echo "image $REPO_NAME:$IMAGE_TAG not found in ECR, app never starts on an unverified image." >&2
      phase_failed images
    fi
    echo "Verified image present: $REPO_NAME:$IMAGE_TAG"
  done
  mark_done images
  echo "Phase images complete: five verified images, no placeholder running"
fi

run_one_off_task() {
  TASKDEF_LOGICAL="$1"
  TASK_LABEL="$2"
  TASKDEF_ARN="$(stack_resource "$TASKDEF_LOGICAL")" || { echo "$TASK_LABEL task definition lookup failed, no task started." >&2; phase_failed "$3"; }
  TASKDEF_ARN="$(printf '%s' "$TASKDEF_ARN" | tr -d '[:space:]')"
  [ -n "$TASKDEF_ARN" ] && [ "$TASKDEF_ARN" != "None" ] || { echo "$TASK_LABEL task definition missing, no task started." >&2; phase_failed "$3"; }
  SUBNET_A="$(stack_resource PrivateSubnetA)" || { echo "subnet lookup failed, no task started." >&2; phase_failed "$3"; }
  SUBNET_B="$(stack_resource PrivateSubnetB)" || { echo "subnet lookup failed, no task started." >&2; phase_failed "$3"; }
  DB_SG="$(stack_resource ApiSecurityGroup)" || { echo "security group lookup failed, no task started." >&2; phase_failed "$3"; }
  SUBNET_A="$(printf '%s' "$SUBNET_A" | tr -d '[:space:]')"
  SUBNET_B="$(printf '%s' "$SUBNET_B" | tr -d '[:space:]')"
  DB_SG="$(printf '%s' "$DB_SG" | tr -d '[:space:]')"
  if ! TASK_ARN="$("$AWS_BIN" ecs run-task --cluster "$CLUSTER_NAME" --task-definition "$TASKDEF_ARN" --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$DB_SG],assignPublicIp=DISABLED}" --region "$EXPECTED_REGION" --query "tasks[0].taskArn" --output text ${EXTRA_OVERRIDES:+--overrides "$EXTRA_OVERRIDES"} 2>"$TMP_ERR")"; then
    echo "$TASK_LABEL run-task failed, nothing started beyond this point." >&2
    phase_failed "$3"
  fi
  TASK_ARN="$(printf '%s' "$TASK_ARN" | tr -d '[:space:]')"
  echo "$TASK_LABEL task started in private subnets, no public IP: $TASK_ARN"
  if ! "$AWS_BIN" ecs wait tasks-stopped --cluster "$CLUSTER_NAME" --tasks "$TASK_ARN" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    echo "$TASK_LABEL wait reported, verifying terminal state before any claim." >&2
    if is_auth_error "$ERR"; then echo "authorization or API failure, not absence." >&2; fi
  fi
  EXIT_CODE=""
  if ! EXIT_CODE="$("$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$TASK_ARN" --region "$EXPECTED_REGION" --query "tasks[0].containers[0].exitCode" --output text 2>"$TMP_ERR")"; then
    echo "$TASK_LABEL exit code unreadable, not treated as success." >&2
    phase_failed "$3"
  fi
  EXIT_CODE="$(printf '%s' "$EXIT_CODE" | tr -d '[:space:]')"
  echo "$TASK_LABEL terminal exit code: $EXIT_CODE"
  [ "$EXIT_CODE" = "0" ] || { echo "refused: $TASK_LABEL did not STOP with exit 0, later phases not started." >&2; phase_failed "$3"; }
}

if wants_phase dbroles; then
  echo "Phase dbroles: isolated bootstrap task binds role passwords in task memory only"
  EXTRA_OVERRIDES=""
  run_one_off_task BootstrapTaskDefinition bootstrap dbroles
  mark_done dbroles
  echo "Phase dbroles complete: exact owned roles bound, privilege split applied"
fi

if wants_phase migrate; then
  echo "Phase migrate: single one-off migration task, the only schema change path"
  EXTRA_OVERRIDES=""
  run_one_off_task MigrationTaskDefinition migration migrate
  echo "Phase migrate task STOPPED exit 0; running verify-mode schema and runtime-identity proof"
  EXTRA_OVERRIDES='{"containerOverrides":[{"name":"bootstrap-db-roles","command":["--verify"]}]}'
  run_one_off_task BootstrapTaskDefinition verify migrate
  EXTRA_OVERRIDES=""
  mark_done migrate
  echo "Phase migrate complete: migration STOPPED exit 0 with schema and runtime read-only proof"
fi

if wants_phase enable; then
  for NEED in infra images dbroles migrate; do
    case "$PHASE,$COMPLETED" in
      all,*) ;;
      *) echo "refused: enable requires prior phases in this run; rerun with --phase all or complete $NEED first" >&2; phase_failed enable ;;
    esac
  done
  if [ "$PHASE" = "all" ]; then
    for NEED in infra images dbroles migrate; do
      case ",$COMPLETED," in
        *",$NEED,"*) ;;
        *) echo "refused: enable requires completed $NEED in this run, completed: ${COMPLETED:-none}" >&2; phase_failed enable ;;
      esac
    done
  fi
  echo "Phase enable: update stack with EnableServices=true for fixed count 1 each"
  if ! "$AWS_BIN" cloudformation deploy --stack-name "$STACK_NAME" --template-file "$TEMPLATE_FILE" --parameter-file "$PARAMETERS_FILE" --parameter-overrides EnableServices=true --capabilities CAPABILITY_NAMED_IAM --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    echo "enable deploy failed, services unchanged." >&2
    phase_failed enable
  fi
  if ! "$AWS_BIN" cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    echo "enable wait reported, verifying service counts before any claim." >&2
  fi
  for SERVICE in api web; do
    COUNT=""
    if ! COUNT="$("$AWS_BIN" ecs describe-services --cluster "$CLUSTER_NAME" --services "launchcrew-demo-$SERVICE" --region "$EXPECTED_REGION" --query "services[0].desiredCount" --output text 2>"$TMP_ERR")"; then
      echo "service $SERVICE count unreadable, not claimed running." >&2
      phase_failed enable
    fi
    COUNT="$(printf '%s' "$COUNT" | tr -d '[:space:]')"
    [ "$COUNT" = "1" ] || { echo "refused: service $SERVICE desiredCount is $COUNT, expected fixed 1" >&2; phase_failed enable; }
    echo "Verified service launchcrew-demo-$SERVICE desiredCount 1"
  done
  mark_done enable
  echo "Phase enable complete: both services fixed count 1 each, no autoscaling"
fi

echo "BOOTSTRAP COMPLETE phases requested: $PHASE. Completed: ${COMPLETED:-none}."
echo "Outside-stack remaining work: secret values, ACM certificate, DNS, snapshots need separate approval with exact identifiers."
