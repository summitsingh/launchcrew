#!/bin/sh
# LaunchCrew demo staged bootstrap, dry-run by default, gated phased bring-up.
# Dry-run makes no AWS call. Confirm path brings infrastructure up in order and
# refuses to start the app early:
#   phase infra   deploy the CloudFormation stack with EnableServices=false on a
#                 fresh stack (owned updates refuse while EnableServices=true
#                 so task definitions and images are never updated under
#                 running services; run explicit phase quiesce first), so VPC,
#                 ECR repositories, RDS, and task definitions exist with both
#                 ECS services at DesiredCount 0 and no app running
#   phase quiesce safe maintenance to stop the owned app before an update:
#                 verify exact stack ownership, identity, and tags, review a
#                 bounded change set built from the existing deployed template
#                 and all existing parameter values except EnableServices=false
#                 whose only intended service effect is ApiService and WebService
#                 DesiredCount to 0, execute only on explicit operator confirm,
#                 then require UPDATE_COMPLETE plus both services 0/0/0 with
#                 unchanged old task definition and image identity. Fail closed
#                 on drift, empty or ambiguous data, or any other resource change.
#                 Never part of phase all; run explicitly before infra on a live stack.
#   phase images  verify each of the five published image URIs exists in its
#                 owned ECR repository with an image digest and no failures,
#                 and equals the image referenced by its owned stack task
#                 definition; placeholder or missing images refuse
#   phase init    run the isolated SDK populate task on the verified bootstrap
#                 image with explicit EntryPoint to populate_prereqs.py and
#                 Command --populate, after infra plus published image proof
#                 and before any binder, then require its STOPPED exit code 0
#   phase material run the isolated SDK material verify task with explicit
#                 EntryPoint to populate_prereqs.py and Command
#                 --verify-material, read-only with zero Put and zero Export,
#                 after init and before binder and enable
#   phase dbroles run the isolated one-off bootstrap task that binds database
#                 role passwords from injected Secrets Manager values held in
#                 task memory only, then require its STOPPED exit code 0
#   phase migrate run the single one-off migration task, require STOPPED exit
#                 code 0, then run the separate verify task definition in
#                 verify mode as schema and runtime-identity proof
#   phase enable  re-prove images, owned secrets and execution roles, plus the
#                 read-only material verify and the runtime-only verify proof,
#                 then update the stack with EnableServices=true for fixed
#                 count 1 each, then verify both owned physical services report
#                 ACTIVE desired 1 running 1 pending 0 with no failures.
#                 Standalone enable never populates, exports, binds, or migrates.
#   phase all     full readiness chain: owned foundation COMPLETE plus exact
#                 confirmed SNS gate, owned prereqs ISSUED plus owned secret
#                 metadata, then infra, images, init, material, dbroles,
#                 migrate, enable in order. Already issued owned stacks verify
#                 by readback; a PENDING_VALIDATION cert stops as PENDING, not
#                 ready, with no ready claim.
# Explicit prereq deploy phases (foundation and prereqs) remain explicit only
# for creation; all verifies their readiness read-only and never deploys them:
#   phase foundation deploy the foundation stack with Project filtered Budget
#                 plus SNS topic, policy, and conditional email subscription,
#                 then report subscription status with no paid Secrets yet.
#                 Foundation owns the exact budget name launchcrew-demo; the
#                 app stack owns no budget and no SNS topic.
#   phase prereqs enforce the exact SNS gate plus CE Active plus expiry guard,
#                 then deploy four Secrets plus the exportable ACM cert, with
#                 staged CREATE_IN_PROGRESS pending yielding a private DNS
#                 receipt and a public CNAME operator step
# The migration task definition is the only schema change path; the bootstrap
# task never runs alembic, and runtime tasks never run alembic or role binds,
# so there are no duplicate migration controllers. This controller never calls
# the secretsmanager read-value API and never prints a secret value: it handles
# only secret ARNs as identifiers via describe-secret metadata, and the
# bootstrap job holds values in private task memory without logging them.
# The SDK jobs read values only inside their own task roles; the controller
# verifies their task definitions carry metadata env only with zero injected
# Secrets entries. Outside-stack values (Secrets Manager secret contents, ACM
# certificate, Cloudflare DNS, manual snapshots) need a separate approval with
# exact identifiers and are reported as remaining work. Teardown stays
# separate in deploy/aws/teardown.sh. An AWS Budget is an alert and estimate
# mechanism, not an enforced hard spend cap. A budget filter with no data or 0
# is not proof of zero spend. Cost allocation tag activation is never done
# here and is verified read-only before any paid phase: the Project key must
# already be Active as a user defined resource cost allocation tag in Billing
# under a separate approval, which can take 24h for the key to appear plus 24h
# for activation. Inactive, absent, ambiguous, or unreadable activation
# refuses before any CloudFormation deploy or one-off task, because spend
# starts at infra, RDS, and ALB creation even at DesiredCount 0. Every paid
# phase also verifies the owned foundation stack tags and COMPLETE status,
# the exact foundation budget filter plus alert thresholds, the exact
# confirmed SNS subscription, and the Nov 9 source expiry guard.
# One-off jobs run in the public subnets with a public IP and a security
# group that allows no inbound traffic at all. That is the honest minimal
# egress path: private subnets here have no NAT gateway and no VPC endpoints,
# so a job placed there with a disabled public IP cannot reach ECR, Secrets
# Manager, or CloudWatch Logs and only pretends to work. The database stays
# private regardless: the isolated job group may reach only Postgres on the
# database group plus HTTPS egress, and RDS itself is never public.
# Each one-off launch writes a private mode 600 metadata-only journal before
# the run-task call, uses a bounded client token with no automatic resend,
# and recovers ambiguously failed launches read-only before any rerun.
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
FOUNDATION_STACK_NAME=""
PREREQS_STACK_NAME=""
FOUNDATION_TEMPLATE_FILE=""
PREREQS_TEMPLATE_FILE=""
FOUNDATION_PARAMETERS_FILE=""
DNS_RECEIPT_FILE=""
LAUNCH_JOURNAL_DIR="${LAUNCH_JOURNAL_DIR:-}"
QUIESCE_CONFIRM="${QUIESCE_CONFIRM:-}"
SOURCE_SHA="${SOURCE_SHA:-}"
RELEASE_GEN="${RELEASE_GEN:-}"
TARGET_DB_HEAD="006"
# Empty journal default resolves inside run_one_off_task to a dedicated
# persistent private directory under the ignored .local tree derived from the
# script root, never shared /tmp. An explicit --launch-journal-dir still
# overrides. Release generation defaults to head006 plus the source Git SHA
# short hash when available; an explicit --release-generation still overrides
# for tests. Old one-shot journals are never deleted, renamed, or overwritten;
# a new generation uses a distinct path and must reconcile any prior token.

usage() {
  echo "Usage: $0 [--confirm --stack-name NAME --expected-account ID --expected-region REGION ...] [--phase infra|images|init|material|dbroles|migrate|enable|all|foundation|prereqs|quiesce]"
  echo "Dry-run default makes no AWS call and prints the ordered phase plan."
  echo "Confirm path requires --stack-name, --expected-account (12 digits), --expected-region,"
  echo "  --parameters-file, plus per-phase image URIs and secret ARNs (see phase plan)."
  echo "Paid phases (infra, init, material, dbroles, migrate, enable, all, quiesce) also need"
  echo "  --foundation-stack-name plus --foundation-parameters-file for the owned budget gate."
  echo "  --phase all additionally needs --prereqs-stack-name for the ISSUED readback."
  echo "Explicit prereq deploy phases remain explicit only for creation:"
  echo "  --phase foundation needs --foundation-stack-name plus --foundation-parameters-file"
  echo "  --phase prereqs needs --prereqs-stack-name plus --foundation-stack-name plus --foundation-parameters-file plus --dns-receipt-file"
  echo "  --phase quiesce needs --stack-name plus --expected-account plus --expected-region plus"
  echo "  --quiesce-confirm <exact-StackId> plus --foundation-stack-name plus --foundation-parameters-file"
  echo "  plus --prereqs-stack-name; it never runs as part of --phase all."
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
    --foundation-stack-name) FOUNDATION_STACK_NAME="${2:-}"; shift 2 ;;
    --foundation-stack-name=*) FOUNDATION_STACK_NAME="${1#--foundation-stack-name=}"; shift ;;
    --prereqs-stack-name) PREREQS_STACK_NAME="${2:-}"; shift 2 ;;
    --prereqs-stack-name=*) PREREQS_STACK_NAME="${1#--prereqs-stack-name=}"; shift ;;
    --foundation-template-file) FOUNDATION_TEMPLATE_FILE="${2:-}"; shift 2 ;;
    --foundation-template-file=*) FOUNDATION_TEMPLATE_FILE="${1#--foundation-template-file=}"; shift ;;
    --prereqs-template-file) PREREQS_TEMPLATE_FILE="${2:-}"; shift 2 ;;
    --prereqs-template-file=*) PREREQS_TEMPLATE_FILE="${1#--prereqs-template-file=}"; shift ;;
    --foundation-parameters-file) FOUNDATION_PARAMETERS_FILE="${2:-}"; shift 2 ;;
    --foundation-parameters-file=*) FOUNDATION_PARAMETERS_FILE="${1#--foundation-parameters-file=}"; shift ;;
    --dns-receipt-file) DNS_RECEIPT_FILE="${2:-}"; shift 2 ;;
    --dns-receipt-file=*) DNS_RECEIPT_FILE="${1#--dns-receipt-file=}"; shift ;;
    --launch-journal-dir) LAUNCH_JOURNAL_DIR="${2:-}"; shift 2 ;;
    --launch-journal-dir=*) LAUNCH_JOURNAL_DIR="${1#--launch-journal-dir=}"; shift ;;
    --quiesce-confirm) QUIESCE_CONFIRM="${2:-}"; shift 2 ;;
    --quiesce-confirm=*) QUIESCE_CONFIRM="${1#--quiesce-confirm=}"; shift ;;
    --source-sha) SOURCE_SHA="${2:-}"; shift 2 ;;
    --source-sha=*) SOURCE_SHA="${1#--source-sha=}"; shift ;;
    --release-generation) RELEASE_GEN="${2:-}"; shift 2 ;;
    --release-generation=*) RELEASE_GEN="${1#--release-generation=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

phase_plan() {
  echo "Phase order, each phase gates the next; any failure stops the run:"
  echo "  0. paid gates: owned foundation COMPLETE plus exact budget filter and alert"
  echo "     thresholds plus exact confirmed SNS subscription, Project Active, expiry;"
  echo "     all additionally verifies owned prereqs ISSUED plus secret metadata"
  echo "  1. ownership: caller account, stack Project LaunchCrew and Environment demo tags,"
  echo "     exact StackId account and region, secret ARN shape account and region,"
  echo "     plus exact returned secret ARN and secret tags; fresh stacks create with tags"
  echo "  2. infra: deploy stack with EnableServices false; owned updates refuse while"
  echo "     EnableServices is true so images are never updated under running services;"
  echo "     run explicit phase quiesce first, then require CREATE_COMPLETE or UPDATE_COMPLETE"
  echo "  2a. quiesce: explicit safe maintenance only, never part of all; verify exact owned"
  echo "     stack identity and tags, review a bounded change set from the existing template"
  echo "     with only ApiService and WebService to DesiredCount 0, execute only on explicit"
  echo "     --quiesce-confirm StackId, then require UPDATE_COMPLETE plus 0/0/0 with unchanged images"
  echo "  3. images: all five ECR image URIs verified by digest with no failures, each equal"
  echo "     to its owned stack task definition image, explicit tag required, no latest fallback;"
  echo "     task definitions must inject exactly the validated secrets under the owned roles"
  echo "  4. init: isolated SDK populate task on the verified bootstrap image with explicit"
  echo "     EntryPoint to populate_prereqs.py and Command --populate, STOPPED exit 0,"
  echo "     after the SDK task definition image, env, roles, and zero secret injection proof"
  echo "  5. material: isolated SDK material verify task with explicit EntryPoint and"
  echo "     Command --verify-material, read-only with zero Put and zero Export, STOPPED exit 0"
  echo "  6. dbroles: isolated bootstrap task STOPPED exit 0, passwords bound in task memory only,"
  echo "     after the bootstrap task definition secrets and owned roles are proven"
  echo "  7. migrate: isolated migration task STOPPED exit 0, then separate verify task proof of"
  echo "     expected head revision, runtime identity, rolled-back write, and DDL refusal"
  echo "  8. enable: foundation budget readiness preflight (exact Project filter plus alert"
  echo "     thresholds read back, Project activation verified Active read-only, never"
  echo "     activated here), then re-prove images, bindings, the read-only material"
  echo "     verify and the runtime-only verify proof from live state, then update stack"
  echo "     with EnableServices=true, verify owned services ACTIVE desired 1 running 1"
  echo "     pending 0 each (configuration check only; serving health is proven by"
  echo "     ALB targets after DNS). Standalone"
  echo "     enable never populates, exports, binds, or migrates."
  echo "Per-phase inputs: infra needs stack, account, region, parameters file plus foundation gate args;"
  echo "  images needs the five image URIs plus the four secret ARNs for the API and web bindings;"
  echo "  init and material need the bootstrap image plus all four secret ARNs plus foundation gate args;"
  echo "  dbroles needs the bootstrap image and three secret ARNs plus foundation gate args;"
  echo "  migrate needs the migration and bootstrap images plus migration and runtime secret ARNs plus foundation gate args;"
  echo "  enable needs the five image URIs and all four secret ARNs to re-prove refs, bindings, and verify."
  echo "  all needs everything enable needs plus --foundation-stack-name, --prereqs-stack-name,"
  echo "  and --foundation-parameters-file for the readiness chain."
  echo "Each phase re-verifies its own preconditions from live state, so a single phase can resume"
  echo "after earlier phases completed in a previous run; nothing is assumed from memory."
  echo "Explicit prereq deploy phases remain explicit only for creation; all verifies readiness read-only:"
  echo "  foundation: deploy Budget plus SNS with Project filter, report subscription status, no paid Secrets yet;"
  echo "     foundation owns the exact budget name, the app stack owns no budget"
  echo "  prereqs: exact SNS gate plus CE Active plus expiry guard, then deploy four Secrets plus exportable ACM,"
  echo "     staged CREATE_IN_PROGRESS pending yields private DNS receipt and public CNAME operator step"
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
  infra|images|init|material|dbroles|migrate|enable|all|foundation|prereqs|quiesce) ;;
  *) echo "refused: unknown phase $PHASE" >&2; exit 2 ;;
esac
[ -n "$EXPECTED_ACCOUNT" ] || { echo "confirm requires --expected-account with a 12-digit account" >&2; exit 2; }
[ -n "$EXPECTED_REGION" ] || { echo "confirm requires --expected-region" >&2; exit 2; }
case "$EXPECTED_ACCOUNT" in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) echo "refused: expected account must be 12 digits" >&2; exit 2 ;;
esac
require_foundation_gate_args() {
  [ -n "$FOUNDATION_STACK_NAME" ] || { echo "confirm requires --foundation-stack-name for the owned budget gate" >&2; exit 2; }
  [ -n "$FOUNDATION_PARAMETERS_FILE" ] || { echo "confirm requires --foundation-parameters-file for the approved notify value" >&2; exit 2; }
  [ -f "$FOUNDATION_PARAMETERS_FILE" ] || { echo "refused: foundation parameters file not found: $FOUNDATION_PARAMETERS_FILE" >&2; exit 2; }
}
case "$PHASE" in
  foundation)
    [ -n "$FOUNDATION_STACK_NAME" ] || { echo "confirm requires --foundation-stack-name with the exact foundation stack name" >&2; exit 2; }
    [ -n "$FOUNDATION_PARAMETERS_FILE" ] || { echo "confirm requires --foundation-parameters-file" >&2; exit 2; }
    [ -f "$FOUNDATION_PARAMETERS_FILE" ] || { echo "refused: foundation parameters file not found: $FOUNDATION_PARAMETERS_FILE" >&2; exit 2; } ;;
  prereqs)
    [ -n "$PREREQS_STACK_NAME" ] || { echo "confirm requires --prereqs-stack-name with the exact prereqs stack name" >&2; exit 2; }
    [ -n "$FOUNDATION_STACK_NAME" ] || { echo "confirm requires --foundation-stack-name for the exact SNS gate" >&2; exit 2; }
    [ -n "$FOUNDATION_PARAMETERS_FILE" ] || { echo "confirm requires --foundation-parameters-file for the approved notify value" >&2; exit 2; }
    [ -f "$FOUNDATION_PARAMETERS_FILE" ] || { echo "refused: foundation parameters file not found: $FOUNDATION_PARAMETERS_FILE" >&2; exit 2; }
    [ -n "$DNS_RECEIPT_FILE" ] || { echo "confirm requires --dns-receipt-file for the private validation receipt" >&2; exit 2; } ;;
  all)
    [ -n "$STACK_NAME" ] || { echo "confirm requires --stack-name with the exact stack name" >&2; exit 2; }
    [ -n "$PARAMETERS_FILE" ] || { echo "confirm requires --parameters-file" >&2; exit 2; }
    [ -f "$PARAMETERS_FILE" ] || { echo "refused: parameters file not found: $PARAMETERS_FILE" >&2; exit 2; }
    require_foundation_gate_args
    [ -n "$PREREQS_STACK_NAME" ] || { echo "confirm requires --prereqs-stack-name for the ISSUED readback" >&2; exit 2; } ;;
  quiesce)
    [ -n "$STACK_NAME" ] || { echo "confirm requires --stack-name with the exact stack name" >&2; exit 2; }
    [ -n "$QUIESCE_CONFIRM" ] || { echo "confirm requires --quiesce-confirm with the exact StackId for explicit maintenance" >&2; exit 2; }
    require_foundation_gate_args
    [ -n "$PREREQS_STACK_NAME" ] || { echo "confirm requires --prereqs-stack-name for the ISSUED readback" >&2; exit 2; } ;;
  infra|init|material|dbroles|migrate|enable)
    [ -n "$STACK_NAME" ] || { echo "confirm requires --stack-name with the exact stack name" >&2; exit 2; }
    [ -n "$PARAMETERS_FILE" ] || { echo "confirm requires --parameters-file" >&2; exit 2; }
    [ -f "$PARAMETERS_FILE" ] || { echo "refused: parameters file not found: $PARAMETERS_FILE" >&2; exit 2; }
    require_foundation_gate_args
    [ -n "$PREREQS_STACK_NAME" ] || { echo "confirm requires --prereqs-stack-name for the ISSUED readback" >&2; exit 2; } ;;
  *)
    [ -n "$STACK_NAME" ] || { echo "confirm requires --stack-name with the exact stack name" >&2; exit 2; }
    [ -n "$PARAMETERS_FILE" ] || { echo "confirm requires --parameters-file" >&2; exit 2; }
    [ -f "$PARAMETERS_FILE" ] || { echo "refused: parameters file not found: $PARAMETERS_FILE" >&2; exit 2; } ;;
esac

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
  infra|quiesce) ;;
  foundation|prereqs) ;;
  images) require_images_args; require_secret_args; require_tls_arg ;;
  init|material)
    [ -n "$BOOTSTRAP_IMAGE" ] || { echo "confirm requires --bootstrap-image for this phase" >&2; exit 2; }
    require_secret_args; require_tls_arg ;;
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
    init|material|dbroles|migrate|enable|all) return 0 ;;
  esac
  [ -n "$RUNTIME_SECRET_ARN" ] || [ -n "$MIGRATION_SECRET_ARN" ] || [ -n "$MASTER_SECRET_ARN" ] || [ -n "$TLS_SECRET_ARN" ]
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
case "$PHASE" in
  foundation)
    if [ -z "$FOUNDATION_TEMPLATE_FILE" ]; then FOUNDATION_TEMPLATE_FILE="$SCRIPT_DIR/foundation.yaml"; fi
    [ -f "$FOUNDATION_TEMPLATE_FILE" ] || { echo "refused: foundation template file not found: $FOUNDATION_TEMPLATE_FILE" >&2; exit 2; } ;;
  prereqs)
    if [ -z "$PREREQS_TEMPLATE_FILE" ]; then PREREQS_TEMPLATE_FILE="$SCRIPT_DIR/prereqs.yaml"; fi
    [ -f "$PREREQS_TEMPLATE_FILE" ] || { echo "refused: prereqs template file not found: $PREREQS_TEMPLATE_FILE" >&2; exit 2; }
    if [ -z "$FOUNDATION_TEMPLATE_FILE" ]; then FOUNDATION_TEMPLATE_FILE="$SCRIPT_DIR/foundation.yaml"; fi ;;
  *)
    if [ -z "$TEMPLATE_FILE" ]; then TEMPLATE_FILE="$SCRIPT_DIR/fargate.yaml"; fi
    [ -f "$TEMPLATE_FILE" ] || { echo "refused: template file not found: $TEMPLATE_FILE" >&2; exit 2; } ;;
esac
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

OPERATION_LOCK_DIR=""
OPERATION_LOCK_OWNER_FILE=""
OPERATION_LOCK_OWNED=0

release_operation_lock() {
  if [ "${OPERATION_LOCK_OWNED:-0}" -eq 1 ] && [ -n "${OPERATION_LOCK_DIR:-}" ] && [ -n "${OPERATION_LOCK_OWNER_FILE:-}" ]; then
    if [ -f "$OPERATION_LOCK_OWNER_FILE" ]; then
      OWNER_PID="$(cat "$OPERATION_LOCK_OWNER_FILE" 2>/dev/null | tr -d '[:space:]' || echo "")"
      if [ "$OWNER_PID" = "$$" ]; then
        rm -f "$OPERATION_LOCK_OWNER_FILE" 2>/dev/null || true
        rmdir "$OPERATION_LOCK_DIR" 2>/dev/null || true
      fi
    fi
  fi
  OPERATION_LOCK_DIR=""
  OPERATION_LOCK_OWNER_FILE=""
  OPERATION_LOCK_OWNED=0
}

bootstrap_cleanup() {
  release_operation_lock 2>/dev/null || true
  rm -f "$TMP_ERR" "$TMP_JSON" "$TMP_PARAMS" 2>/dev/null || true
}

acquire_operation_lock() {
  OPERATION_LOCK_DIR="$LAUNCH_JOURNAL_DIR/launchcrew-$STACK_NAME-$TASK_PHASE-$TASK_LABEL.lock"
  OPERATION_LOCK_OWNER_FILE="$OPERATION_LOCK_DIR/owner"
  OPERATION_LOCK_OWNED=0
  if [ -L "$OPERATION_LOCK_DIR" ]; then
    echo "$TASK_LABEL operation lock is a symlink, no launch attempted. Inspect $OPERATION_LOCK_DIR." >&2
    phase_failed "$TASK_PHASE"
  fi
  if [ -e "$OPERATION_LOCK_DIR" ] && [ ! -d "$OPERATION_LOCK_DIR" ]; then
    echo "$TASK_LABEL operation lock path exists as a file, no launch attempted. Inspect $OPERATION_LOCK_DIR." >&2
    phase_failed "$TASK_PHASE"
  fi
  LOCK_ATTEMPTS=0
  while [ "$LOCK_ATTEMPTS" -lt 30 ]; do
    if mkdir "$OPERATION_LOCK_DIR" 2>/dev/null; then
      if ! (umask 077; printf '%s' "$$" >"$OPERATION_LOCK_OWNER_FILE" 2>/dev/null); then
        rmdir "$OPERATION_LOCK_DIR" 2>/dev/null || true
        echo "$TASK_LABEL operation lock owner write failed, no launch attempted." >&2
        phase_failed "$TASK_PHASE"
      fi
      chmod 600 "$OPERATION_LOCK_OWNER_FILE" 2>/dev/null || true
      OPERATION_LOCK_OWNED=1
      return 0
    fi
    if [ -d "$OPERATION_LOCK_DIR" ]; then
      if [ -f "$OPERATION_LOCK_OWNER_FILE" ]; then
        LOCK_PID="$(cat "$OPERATION_LOCK_OWNER_FILE" 2>/dev/null | tr -d '[:space:]' || echo "")"
        case "$LOCK_PID" in
          ''|*[!0-9]*) LOCK_PID="" ;;
        esac
        if [ -n "$LOCK_PID" ]; then
          if kill -0 "$LOCK_PID" 2>/dev/null; then
            LOCK_ATTEMPTS=$((LOCK_ATTEMPTS + 1))
            sleep 1 2>/dev/null || sleep 1
            continue
          else
            if [ -f "$ACTIVE_FILE" ] && [ ! -L "$ACTIVE_FILE" ]; then
              echo "$TASK_LABEL operation lock is stale (owner $LOCK_PID dead), prior record exists, manual reconciliation required with no new launch. Inspect $ACTIVE_FILE and $OPERATION_LOCK_DIR." >&2
            else
              echo "$TASK_LABEL operation lock is stale (owner $LOCK_PID dead) with no prior record, launch is ambiguous with no new run. Manual cleanup required. Inspect $OPERATION_LOCK_DIR." >&2
            fi
            phase_failed "$TASK_PHASE"
          fi
        else
          echo "$TASK_LABEL operation lock owner unreadable, no launch attempted. Inspect $OPERATION_LOCK_DIR." >&2
          phase_failed "$TASK_PHASE"
        fi
      else
        LOCK_ATTEMPTS=$((LOCK_ATTEMPTS + 1))
        sleep 1 2>/dev/null || sleep 1
        continue
      fi
    else
      LOCK_ATTEMPTS=$((LOCK_ATTEMPTS + 1))
      continue
    fi
  done
  echo "$TASK_LABEL operation lock held after bounded wait, no new launch to avoid duplicate run-task. Rerun after holder completes. Inspect $OPERATION_LOCK_DIR." >&2
  phase_failed "$TASK_PHASE"
}

TMP_ERR="$(mktemp /tmp/launchcrew-bootstrap-err-XXXXXX)"
TMP_JSON="$(mktemp /tmp/launchcrew-bootstrap-json-XXXXXX)"
TMP_PARAMS="$(mktemp /tmp/launchcrew-bootstrap-params-XXXXXX)"
trap bootstrap_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

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

is_absent_for_stack() {
  case "$1" in
    *"does not exist"*)
      case "$1" in
        *"$2"*) return 0 ;;
      esac
      return 1 ;;
  esac
  return 1
}

check_prereq_expiry() {
  TODAY_VALUE=""
  if [ -n "${LAUNCHCREW_TODAY:-}" ] && [ -n "${FAKE_MODE:-}" ]; then
    TODAY_VALUE="$LAUNCHCREW_TODAY"
  else
    TODAY_VALUE="$(date -u +%F 2>/dev/null || echo "")"
  fi
  case "$TODAY_VALUE" in
    ????-??-??) ;;
    *) echo "refused: expiry guard date unreadable, no change made" >&2; phase_failed "$PHASE" ;;
  esac
  if [ "$TODAY_VALUE" \> "2026-11-09" ]; then
    echo "refused: prereq provisioning expired after 2026-11-09 as a source guard only, never a billing stop, no change made" >&2
    phase_failed "$PHASE"
  fi
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
case "$PHASE" in
  infra|init|material|dbroles|migrate|enable|all|foundation|prereqs|quiesce) check_prereq_expiry ;;
esac
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

# Ownership gate two: the exact app stack must carry the demo tags before
# any mutation, and its StackId region and account must match the
# expectation. Skipped for explicit foundation and prereqs phases, which
# own separate stacks with their own gates below. A stack that reports
# absent (ValidationError, does not exist) is a fresh create path, not
# ownership proof: only infra or all may proceed, and the create deploys
# with the demo tags. An authorization failure is never treated as
# absence.
STACK_EXISTS=0
STACK_STATUS=""
STACK_ID=""
CURRENT_ENABLE="false"
if [ "$PHASE" != "foundation" ] && [ "$PHASE" != "prereqs" ]; then
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
MOVED_BUDGET_KEYS = {"BudgetLimitUsd", "BudgetNotifyEmail"}
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
    if key in MOVED_BUDGET_KEYS:
        raise SystemExit("parameters file carries a foundation-owned budget key")
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

case "$PHASE" in
  infra|init|material|dbroles|migrate|enable|all) check_params_match ;;
esac

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
try:
    if not isinstance(doc, dict):
        print("MALFORMED")
        sys.exit(0)
    entries = doc.get("CostAllocationTags", None)
    if not isinstance(entries, list):
        print("MALFORMED")
        sys.exit(0)
    project_entries = [e for e in entries
                       if isinstance(e, dict) and e.get("TagKey") == "Project"]
    if not project_entries:
        print("TAG_ABSENT")
        sys.exit(0)
    if len(project_entries) > 1:
        print("TAG_AMBIGUOUS")
        sys.exit(0)
    if project_entries[0].get("Type") != "UserDefined":
        print("TAG_WRONGTYPE")
        sys.exit(0)
    status = project_entries[0].get("Status", "")
    if status == "Active":
        print("TAG_ACTIVE")
    elif status == "Inactive":
        print("TAG_INACTIVE")
    else:
        print("UNKNOWN")
except Exception:
    print("MALFORMED")
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
  infra|init|material|dbroles|migrate|enable|all|foundation|prereqs|quiesce) check_cost_tag_activation ;;
esac

# Release generation for the head006 rollout. A new intentional release uses a
# distinct durable generation bound to the source Git SHA and the target DB
# head, plus the exact owned StackId, task definition, and config digest at
# launch time. Old one-shot journals are never deleted, renamed, or
# overwritten; the new generation uses a distinct active path and must
# reconcile any prior token to STOPPED with all essential exits 0 before any
# new launch. An empty new path never proves absence.
resolve_release_generation() {
  if [ -n "$RELEASE_GEN" ]; then
    case "$RELEASE_GEN" in
      *[!A-Za-z0-9_.-]*) echo "refused: release generation has invalid characters: $RELEASE_GEN" >&2; exit 2 ;;
    esac
    case "$RELEASE_GEN" in
      *head006*|*006*) ;;
      *) echo "refused: release generation must name the target head006: $RELEASE_GEN" >&2; exit 2 ;;
    esac
    return 0
  fi
  SHA_SHORT=""
  if [ -n "$SOURCE_SHA" ]; then
    case "$SOURCE_SHA" in
      *[!0-9a-fA-F]*) echo "refused: source SHA must be hex: $SOURCE_SHA" >&2; exit 2 ;;
    esac
    SHA_LEN="$(printf '%s' "$SOURCE_SHA" | wc -c)"
    if [ "$SHA_LEN" -lt 7 ] || [ "$SHA_LEN" -gt 41 ]; then
      echo "refused: source SHA must be 7 to 40 hex chars" >&2; exit 2
    fi
    SHA_SHORT="$(printf '%s' "$SOURCE_SHA" | cut -c1-7)"
  else
    if command -v git >/dev/null 2>&1 && [ -n "${SCRIPT_DIR:-}" ]; then
      SHA_SHORT="$(git -C "$SCRIPT_DIR" rev-parse --short=7 HEAD 2>/dev/null | tr -d '[:space:]' || true)"
    fi
    case "$SHA_SHORT" in
      ""|*[!0-9a-fA-F]*) SHA_SHORT="unknown" ;;
    esac
  fi
  RELEASE_GEN="head006-$SHA_SHORT"
}

resolve_release_generation

# cloudformation deploy has no --parameter-file option. Overrides travel as
# one argv item per Key=Value pair built by python, never through shell word
# splitting or globbing, so values with spaces stay intact. Guard: only
# public identifiers travel here (image URIs, ARNs, names, flags). A value
# with a newline or a URL scheme is refused, and failures stay bounded with
# no parameter dump, because deploy errors can echo parameters.
cloudformation_deploy() {
  ENABLE_VALUE="$1"
  DEPLOY_LABEL="$2"
  # Every deploy passes the exact demo tags. CloudFormation clears stack
  # tags to [] on UPDATE when --tags is omitted, so updates must repeat
  # the owned Project and Environment tags, not only fresh creates.
  DEPLOY_TAGS="yes"
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
    if key in ("BudgetLimitUsd", "BudgetNotifyEmail"):
        raise SystemExit("parameters file carries a foundation-owned budget key")
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

# Phase A prereq helpers, additive and explicit only. Legacy all never calls
# these. All ownership uses exact account, region, stack, and tag checks with
# exact API errors only. No secret value ever appears in argv, files, or logs.
prereq_stack_resource() {
  "$AWS_BIN" cloudformation describe-stack-resource --stack-name "$1" --logical-resource-id "$2" --region "$EXPECTED_REGION" --query "StackResourceDetail.PhysicalResourceId" --output text 2>"$TMP_ERR"
}

observe_prereq_resource() {
  OBSERVE_STACK="$1"
  OBSERVE_LOGICAL="$2"
  OBSERVE_TRY=1
  while [ "$OBSERVE_TRY" -le 5 ]; do
    if OBSERVE_VALUE="$(prereq_stack_resource "$OBSERVE_STACK" "$OBSERVE_LOGICAL" 2>"$TMP_ERR")"; then
      OBSERVE_VALUE="$(printf '%s' "$OBSERVE_VALUE" | tr -d '[:space:]')"
      if [ -n "$OBSERVE_VALUE" ] && [ "$OBSERVE_VALUE" != "None" ]; then
        printf '%s' "$OBSERVE_VALUE"
        return 0
      fi
    fi
    if [ "$OBSERVE_TRY" -eq 5 ]; then
      break
    fi
    sleep 2 2>/dev/null || true
    OBSERVE_TRY=$((OBSERVE_TRY + 1))
  done
  return 1
}

FOUNDATION_EXISTS=0
FOUNDATION_STATUS=""
FOUNDATION_ID=""
PREREQS_EXISTS=0
PREREQS_STATUS=""
PREREQS_ID=""

check_foundation_stack() {
  if FOUNDATION_JSON="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$FOUNDATION_STACK_NAME" --region "$EXPECTED_REGION" --output json 2>"$TMP_ERR")"; then
    FOUNDATION_EXISTS=1
    printf '%s' "$FOUNDATION_JSON" >"$TMP_JSON"
    FOUNDATION_PARSED="$(python3 - "$TMP_JSON" 2>/dev/null <<'PYEOF'
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
print("STACKID\t%s" % stack.get("StackId", ""))
print("STATUS\t%s" % stack.get("StackStatus", ""))
print("PROJECT\t%s" % tags.get("Project", ""))
print("ENV\t%s" % tags.get("Environment", ""))
PYEOF
)" || { echo "refused: foundation stack metadata unreadable, no change made" >&2; exit 1; }
    FOUNDATION_ID="$(printf '%s\n' "$FOUNDATION_PARSED" | awk -F'\t' '$1=="STACKID"{print $2}')"
    FOUNDATION_STATUS="$(printf '%s\n' "$FOUNDATION_PARSED" | awk -F'\t' '$1=="STATUS"{print $2}')"
    FOUNDATION_PROJECT="$(printf '%s\n' "$FOUNDATION_PARSED" | awk -F'\t' '$1=="PROJECT"{print $2}')"
    FOUNDATION_ENV="$(printf '%s\n' "$FOUNDATION_PARSED" | awk -F'\t' '$1=="ENV"{print $2}')"
    [ "$FOUNDATION_PROJECT" = "LaunchCrew" ] || { echo "refused: foundation Project tag mismatch, expected LaunchCrew, no change made" >&2; exit 1; }
    [ "$FOUNDATION_ENV" = "demo" ] || { echo "refused: foundation Environment tag mismatch, expected demo, no change made" >&2; exit 1; }
    case "$FOUNDATION_ID" in
      "arn:aws:cloudformation:$EXPECTED_REGION:$EXPECTED_ACCOUNT:"*) ;;
      *) echo "refused: foundation StackId is not owned by the expected account in the expected region, no change made" >&2; exit 1 ;;
    esac
    echo "Verified foundation stack tags Project LaunchCrew Environment demo status $FOUNDATION_STATUS"
  else
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    if is_auth_error "$ERR"; then
      echo "foundation stack check authorization or API failure, not absence, no change made." >&2
      exit 1
    fi
    if is_absent_for_stack "$ERR" "$FOUNDATION_STACK_NAME"; then
      FOUNDATION_EXISTS=0
      echo "Foundation stack absent: fresh create path, foundation will deploy with demo tags"
    else
      echo "foundation stack check failed, no change made." >&2
      exit 1
    fi
  fi
}

check_prereqs_stack() {
  if PREREQS_JSON="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$PREREQS_STACK_NAME" --region "$EXPECTED_REGION" --output json 2>"$TMP_ERR")"; then
    PREREQS_EXISTS=1
    printf '%s' "$PREREQS_JSON" >"$TMP_JSON"
    PREREQS_PARSED="$(python3 - "$TMP_JSON" 2>/dev/null <<'PYEOF'
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
print("STACKID\t%s" % stack.get("StackId", ""))
print("STATUS\t%s" % stack.get("StackStatus", ""))
print("PROJECT\t%s" % tags.get("Project", ""))
print("ENV\t%s" % tags.get("Environment", ""))
PYEOF
)" || { echo "refused: prereqs stack metadata unreadable, no change made" >&2; exit 1; }
    PREREQS_ID="$(printf '%s\n' "$PREREQS_PARSED" | awk -F'\t' '$1=="STACKID"{print $2}')"
    PREREQS_STATUS="$(printf '%s\n' "$PREREQS_PARSED" | awk -F'\t' '$1=="STATUS"{print $2}')"
    PREREQS_PROJECT="$(printf '%s\n' "$PREREQS_PARSED" | awk -F'\t' '$1=="PROJECT"{print $2}')"
    PREREQS_ENV="$(printf '%s\n' "$PREREQS_PARSED" | awk -F'\t' '$1=="ENV"{print $2}')"
    [ "$PREREQS_PROJECT" = "LaunchCrew" ] || { echo "refused: prereqs Project tag mismatch, expected LaunchCrew, no change made" >&2; exit 1; }
    [ "$PREREQS_ENV" = "demo" ] || { echo "refused: prereqs Environment tag mismatch, expected demo, no change made" >&2; exit 1; }
    case "$PREREQS_ID" in
      "arn:aws:cloudformation:$EXPECTED_REGION:$EXPECTED_ACCOUNT:"*) ;;
      *) echo "refused: prereqs StackId is not owned by the expected account in the expected region, no change made" >&2; exit 1 ;;
    esac
    echo "Verified prereqs stack tags Project LaunchCrew Environment demo status $PREREQS_STATUS"
  else
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    if is_auth_error "$ERR"; then
      echo "prereqs stack check authorization or API failure, not absence, no change made." >&2
      exit 1
    fi
    if is_absent_for_stack "$ERR" "$PREREQS_STACK_NAME"; then
      PREREQS_EXISTS=0
      echo "Prereqs stack absent: fresh create path, prereqs will deploy with demo tags"
    else
      echo "prereqs stack check failed, no change made." >&2
      exit 1
    fi
  fi
}

foundation_deploy() {
  DEPLOY_TAGS=""
  if [ "$FOUNDATION_EXISTS" -eq 0 ]; then DEPLOY_TAGS="yes"; fi
  if ! python3 - "$FOUNDATION_PARAMETERS_FILE" "$AWS_BIN" "$FOUNDATION_STACK_NAME" \
      "$FOUNDATION_TEMPLATE_FILE" "$EXPECTED_REGION" "$DEPLOY_TAGS" <<'PYEOF'
import json, subprocess, sys
params_file = sys.argv[1]
aws_bin, stack, template, region, tags = sys.argv[2:7]
try:
    with open(params_file) as handle:
        doc = json.load(handle)
except Exception:
    raise SystemExit("parameters file is not valid JSON")
if isinstance(doc, dict) and "Parameters" in doc:
    doc = doc["Parameters"]
if not isinstance(doc, list):
    raise SystemExit("parameters file must be a JSON list")
seen = set()
overrides = []
for entry in doc:
    if not isinstance(entry, dict) or "ParameterKey" not in entry:
        raise SystemExit("parameters file has a malformed entry")
    key = entry["ParameterKey"]
    if key in seen:
        raise SystemExit("parameters file has a duplicate ParameterKey")
    seen.add(key)
    if key not in ("BudgetLimitUsd", "BudgetNotifyEmail"):
        raise SystemExit("foundation parameters file has an unrecognized key")
    if "ParameterValue" not in entry:
        raise SystemExit("parameters file entry has no explicit ParameterValue")
    value = entry.get("ParameterValue", "")
    if not isinstance(value, str):
        raise SystemExit("parameters file value must be a string")
    if "\n" in value or "\r" in value or "://" in value:
        raise SystemExit("parameters file value has a refused shape")
    overrides.append("%s=%s" % (key, value))
if "BudgetLimitUsd" not in seen or "BudgetNotifyEmail" not in seen:
    raise SystemExit("foundation parameters file must carry BudgetLimitUsd and BudgetNotifyEmail")
cmd = [aws_bin, "cloudformation", "deploy",
       "--stack-name", stack, "--template-file", template,
       "--parameter-overrides"] + overrides + ["--region", region]
if tags == "yes":
    cmd += ["--tags", "Project=LaunchCrew", "Environment=demo"]
proc = subprocess.run(cmd, capture_output=True, text=True)
sys.exit(proc.returncode)
PYEOF
  then
    echo "refused: foundation parameters file unusable or deploy failed, no claim made" >&2
    phase_failed foundation
  fi
}

require_foundation_complete() {
  if ! FOUNDATION_STATUS_NOW="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$FOUNDATION_STACK_NAME" --region "$EXPECTED_REGION" --query "Stacks[0].StackStatus" --output text 2>"$TMP_ERR")"; then
    echo "foundation stack status unreadable after wait, not treated as success." >&2
    phase_failed foundation
  fi
  FOUNDATION_STATUS_NOW="$(printf '%s' "$FOUNDATION_STATUS_NOW" | tr -d '[:space:]')"
  case "$FOUNDATION_STATUS_NOW" in
    CREATE_COMPLETE|UPDATE_COMPLETE) echo "Foundation stack status verified: $FOUNDATION_STATUS_NOW" ;;
    *) echo "refused: foundation stack status is $FOUNDATION_STATUS_NOW, expected CREATE_COMPLETE or UPDATE_COMPLETE" >&2; phase_failed foundation ;;
  esac
  FOUNDATION_STATUS="$FOUNDATION_STATUS_NOW"
  FOUNDATION_EXISTS=1
}

check_foundation_budget_filter() {
  BUDGET_JSON="$(mktemp /tmp/launchcrew-fbudget-XXXXXX)"
  if ! "$AWS_BIN" budgets describe-budget --account-id "$EXPECTED_ACCOUNT" --budget-name launchcrew-demo --output json >"$BUDGET_JSON" 2>"$TMP_ERR"; then
    rm -f "$BUDGET_JSON"
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    echo "foundation budget unreadable, project spend monitoring UNVERIFIED, no claim made." >&2
    if is_auth_error "$ERR"; then
      echo "authorization or API failure, not absence: budgets:DescribeBudget read permission is required." >&2
    fi
    phase_failed "$PHASE"
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
)" || { rm -f "$BUDGET_JSON"; echo "foundation budget filter unreadable, project spend monitoring UNVERIFIED." >&2; phase_failed "$PHASE"; }
  rm -f "$BUDGET_JSON"
  BUDGET_PROOF="$(printf '%s' "$BUDGET_PROOF" | tr -d '[:space:]')"
  [ "$BUDGET_PROOF" = "FILTER_OK" ] || { echo "refused: foundation DemoBudget lacks the exact Project=LaunchCrew EQUALS-only filter, project spend monitoring UNVERIFIED." >&2; phase_failed "$PHASE"; }
  echo "Verified foundation DemoBudget filter: Tags Project=LaunchCrew EQUALS only, read back from live state."
}

# Foundation budget alert readback, read-only and fail-closed. It uses the
# actual Budgets APIs: DescribeNotificationsForBudget returns a Notifications
# array, then DescribeSubscribersForNotification returns a Subscribers array
# for each validated notification. Pagination is raw API with --no-paginate
# plus --cli-input-json carrying exact UpperCamel members AccountId,
# BudgetName, Notification, MaxResults, NextToken; each call is one API call
# so the outer page bound is honest. It requires exactly ACTUAL GREATER_THAN
# 80 and FORECASTED GREATER_THAN 100 with ThresholdType PERCENTAGE or omitted
# (optional omitted means implicit percentage for a healthy budget), each
# subscribed once to the owned foundation topic via SNS. Subscriber lookup
# always uses explicit PERCENTAGE. Explicit null, ABSOLUTE, ABSOLUTE_VALUE,
# empty, or unknown ThresholdType refuses. Missing, extra, duplicate,
# retargeted, paginated overflow, or unreadable notifications or subscribers
# refuse. Alerts are notifications only, never a hard cap. No budget change.
check_foundation_notifications() {
  NOTIF_TOPIC="$(prereq_stack_resource "$FOUNDATION_STACK_NAME" BudgetTopic 2>"$TMP_ERR")" || { echo "foundation topic lookup failed, project spend monitoring UNVERIFIED." >&2; phase_failed "$PHASE"; }
  NOTIF_TOPIC="$(printf '%s' "$NOTIF_TOPIC" | tr -d '[:space:]')"
  [ -n "$NOTIF_TOPIC" ] && [ "$NOTIF_TOPIC" != "None" ] || { echo "refused: foundation topic ARN missing, project spend monitoring UNVERIFIED." >&2; phase_failed "$PHASE"; }
  NOTIF_PAGE="$(mktemp /tmp/launchcrew-fnotif-XXXXXX)"
  NOTIF_COLLECTED="$(mktemp /tmp/launchcrew-fnotif-all-XXXXXX)"
  NOTIF_INPUT="$(mktemp /tmp/launchcrew-fnotif-in-XXXXXX)"
  printf '[]' >"$NOTIF_COLLECTED"
  NOTIF_NEXT=""
  NOTIF_PAGES=0
  while [ "$NOTIF_PAGES" -lt 5 ]; do
    NOTIF_PAGES=$((NOTIF_PAGES + 1))
    if ! python3 - "$NOTIF_INPUT" "$EXPECTED_ACCOUNT" "$NOTIF_NEXT" 2>/dev/null <<'PYEOF'
import json, sys
path, account, token = sys.argv[1:4]
doc = {"AccountId": account, "BudgetName": "launchcrew-demo", "MaxResults": 10}
if token and token != "END" and token != "None":
    doc["NextToken"] = token
with open(path, "w", encoding="utf-8") as out:
    json.dump(doc, out)
PYEOF
    then
      rm -f "$NOTIF_PAGE" "$NOTIF_COLLECTED" "$NOTIF_INPUT"
      echo "foundation budget notifications input unreadable, project spend monitoring UNVERIFIED, no claim made." >&2
      phase_failed "$PHASE"
    fi
    if ! "$AWS_BIN" budgets describe-notifications-for-budget --cli-input-json "file://$NOTIF_INPUT" --no-paginate --output json >"$NOTIF_PAGE" 2>"$TMP_ERR"; then
      rm -f "$NOTIF_PAGE" "$NOTIF_COLLECTED" "$NOTIF_INPUT"
      ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
      echo "foundation budget notifications unreadable, project spend monitoring UNVERIFIED, no claim made." >&2
      if is_auth_error "$ERR"; then
        echo "authorization or API failure, not absence: budgets:DescribeNotificationsForBudget read permission is required." >&2
      fi
      phase_failed "$PHASE"
    fi
    NOTIF_NEXT="$(python3 - "$NOTIF_PAGE" "$NOTIF_COLLECTED" 2>/dev/null <<'PYEOF'
import json, sys
page_file, collected_file = sys.argv[1:3]
try:
    page = json.load(open(page_file))
    collected = json.load(open(collected_file))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(page, dict) or not isinstance(collected, list):
    print("MALFORMED")
    sys.exit(0)
items = page.get("Notifications", None)
if not isinstance(items, list):
    print("MALFORMED")
    sys.exit(0)
for entry in items:
    if not isinstance(entry, dict):
        print("MALFORMED")
        sys.exit(0)
    collected.append(entry)
if len(collected) > 10:
    print("TOO_MANY")
    sys.exit(0)
try:
    with open(collected_file, "w", encoding="utf-8") as out:
        json.dump(collected, out)
except Exception:
    print("MALFORMED")
    sys.exit(0)
if "nextToken" in page:
    print("MALFORMED")
    sys.exit(0)
nxt = page.get("NextToken", "")
if nxt is None or nxt == "None":
    nxt = ""
if not isinstance(nxt, str):
    print("MALFORMED")
    sys.exit(0)
nxt = nxt.strip()
print("END" if not nxt else nxt)
PYEOF
)" || NOTIF_NEXT="MALFORMED"
    NOTIF_NEXT="$(printf '%s' "$NOTIF_NEXT" | tr -d '[:space:]')"
    if [ "$NOTIF_NEXT" = "MALFORMED" ]; then
      rm -f "$NOTIF_PAGE" "$NOTIF_COLLECTED" "$NOTIF_INPUT"
      echo "foundation budget notifications unreadable, project spend monitoring UNVERIFIED, no claim made." >&2
      phase_failed "$PHASE"
    fi
    if [ "$NOTIF_NEXT" = "TOO_MANY" ]; then
      rm -f "$NOTIF_PAGE" "$NOTIF_COLLECTED" "$NOTIF_INPUT"
      echo "refused: foundation budget notifications exceed bounded count, expected ACTUAL 80 plus FORECASTED 100 to the owned topic, project spend monitoring UNVERIFIED." >&2
      phase_failed "$PHASE"
    fi
    if [ -z "$NOTIF_NEXT" ] || [ "$NOTIF_NEXT" = "END" ] || [ "$NOTIF_NEXT" = "None" ]; then
      break
    fi
  done
  if [ -n "$NOTIF_NEXT" ] && [ "$NOTIF_NEXT" != "END" ] && [ "$NOTIF_NEXT" != "None" ]; then
    rm -f "$NOTIF_PAGE" "$NOTIF_COLLECTED" "$NOTIF_INPUT"
    echo "refused: foundation budget notifications exceed bounded pages, expected ACTUAL 80 plus FORECASTED 100 to the owned topic, project spend monitoring UNVERIFIED." >&2
    phase_failed "$PHASE"
  fi
  rm -f "$NOTIF_PAGE" "$NOTIF_INPUT"
  NOTIF_PROOF="$(python3 - "$NOTIF_COLLECTED" 2>/dev/null <<'PYEOF'
import json, sys
try:
    entries = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(entries, list):
    print("MALFORMED")
    sys.exit(0)
want = {
    ("ACTUAL", "GREATER_THAN", 80, "PERCENTAGE"),
    ("FORECASTED", "GREATER_THAN", 100, "PERCENTAGE"),
}
seen = set()
for note in entries:
    if not isinstance(note, dict):
        print("MALFORMED")
        sys.exit(0)
    try:
        threshold = note.get("Threshold", None)
        if isinstance(threshold, float) and threshold.is_integer():
            threshold = int(threshold)
        if "ThresholdType" not in note:
            ttype = "PERCENTAGE"
        else:
            ttype = note.get("ThresholdType", None)
            if ttype is None or not isinstance(ttype, str) or ttype != "PERCENTAGE":
                print("NOTIFICATION_MISMATCH")
                sys.exit(0)
        key = (note.get("NotificationType", ""), note.get("ComparisonOperator", ""),
               threshold, ttype)
    except SystemExit:
        raise
    except Exception:
        print("MALFORMED")
        sys.exit(0)
    if key not in want or key in seen:
        print("NOTIFICATION_MISMATCH")
        sys.exit(0)
    seen.add(key)
if seen == want:
    print("NOTIFICATIONS_OK")
else:
    print("NOTIFICATION_MISMATCH")
PYEOF
)" || { rm -f "$NOTIF_COLLECTED"; echo "foundation budget notifications unreadable, project spend monitoring UNVERIFIED." >&2; phase_failed "$PHASE"; }
  rm -f "$NOTIF_COLLECTED"
  NOTIF_PROOF="$(printf '%s' "$NOTIF_PROOF" | tr -d '[:space:]')"
  [ "$NOTIF_PROOF" = "NOTIFICATIONS_OK" ] || { echo "refused: foundation budget notifications are not exactly ACTUAL 80 plus FORECASTED 100 to the owned topic, project spend monitoring UNVERIFIED." >&2; phase_failed "$PHASE"; }
  NOTIF_ACTUAL_JSON='{"ComparisonOperator":"GREATER_THAN","NotificationType":"ACTUAL","Threshold":80,"ThresholdType":"PERCENTAGE"}'
  NOTIF_FORECAST_JSON='{"ComparisonOperator":"GREATER_THAN","NotificationType":"FORECASTED","Threshold":100,"ThresholdType":"PERCENTAGE"}'
  for NOTIF_LABEL in "ACTUAL_80" "FORECASTED_100"; do
    if [ "$NOTIF_LABEL" = "ACTUAL_80" ]; then
      NOTIF_ARG="$NOTIF_ACTUAL_JSON"
    else
      NOTIF_ARG="$NOTIF_FORECAST_JSON"
    fi
    SUB_PAGE="$(mktemp /tmp/launchcrew-fsub-XXXXXX)"
    SUB_COLLECTED="$(mktemp /tmp/launchcrew-fsub-all-XXXXXX)"
    SUB_INPUT="$(mktemp /tmp/launchcrew-fsub-in-XXXXXX)"
    printf '[]' >"$SUB_COLLECTED"
    SUB_NEXT=""
    SUB_PAGES=0
    while [ "$SUB_PAGES" -lt 5 ]; do
      SUB_PAGES=$((SUB_PAGES + 1))
      if ! python3 - "$SUB_INPUT" "$EXPECTED_ACCOUNT" "$NOTIF_ARG" "$SUB_NEXT" 2>/dev/null <<'PYEOF'
import json, sys
path, account, notif_arg, token = sys.argv[1:5]
try:
    notif = json.loads(notif_arg)
except Exception:
    sys.exit(1)
doc = {"AccountId": account, "BudgetName": "launchcrew-demo", "Notification": notif, "MaxResults": 10}
if token and token != "END" and token != "None":
    doc["NextToken"] = token
with open(path, "w", encoding="utf-8") as out:
    json.dump(doc, out)
PYEOF
      then
        rm -f "$SUB_PAGE" "$SUB_COLLECTED" "$SUB_INPUT"
        echo "foundation budget $NOTIF_LABEL subscribers input unreadable, project spend monitoring UNVERIFIED, no claim made." >&2
        phase_failed "$PHASE"
      fi
      if ! "$AWS_BIN" budgets describe-subscribers-for-notification --cli-input-json "file://$SUB_INPUT" --no-paginate --output json >"$SUB_PAGE" 2>"$TMP_ERR"; then
        rm -f "$SUB_PAGE" "$SUB_COLLECTED" "$SUB_INPUT"
        ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
        echo "foundation budget $NOTIF_LABEL subscribers unreadable, project spend monitoring UNVERIFIED, no claim made." >&2
        if is_auth_error "$ERR"; then
          echo "authorization or API failure, not absence: budgets:DescribeSubscribersForNotification read permission is required." >&2
        fi
        phase_failed "$PHASE"
      fi
      SUB_NEXT="$(python3 - "$SUB_PAGE" "$SUB_COLLECTED" 2>/dev/null <<'PYEOF'
import json, sys
page_file, collected_file = sys.argv[1:3]
try:
    page = json.load(open(page_file))
    collected = json.load(open(collected_file))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(page, dict) or not isinstance(collected, list):
    print("MALFORMED")
    sys.exit(0)
items = page.get("Subscribers", None)
if not isinstance(items, list):
    print("MALFORMED")
    sys.exit(0)
for entry in items:
    if not isinstance(entry, dict):
        print("MALFORMED")
        sys.exit(0)
    collected.append(entry)
if len(collected) > 10:
    print("TOO_MANY")
    sys.exit(0)
try:
    with open(collected_file, "w", encoding="utf-8") as out:
        json.dump(collected, out)
except Exception:
    print("MALFORMED")
    sys.exit(0)
if "nextToken" in page:
    print("MALFORMED")
    sys.exit(0)
nxt = page.get("NextToken", "")
if nxt is None or nxt == "None":
    nxt = ""
if not isinstance(nxt, str):
    print("MALFORMED")
    sys.exit(0)
nxt = nxt.strip()
print("END" if not nxt else nxt)
PYEOF
)" || SUB_NEXT="MALFORMED"
      SUB_NEXT="$(printf '%s' "$SUB_NEXT" | tr -d '[:space:]')"
      if [ "$SUB_NEXT" = "MALFORMED" ]; then
        rm -f "$SUB_PAGE" "$SUB_COLLECTED" "$SUB_INPUT"
        echo "foundation budget $NOTIF_LABEL subscribers unreadable, project spend monitoring UNVERIFIED, no claim made." >&2
        phase_failed "$PHASE"
      fi
      if [ "$SUB_NEXT" = "TOO_MANY" ]; then
        rm -f "$SUB_PAGE" "$SUB_COLLECTED" "$SUB_INPUT"
        echo "refused: foundation budget $NOTIF_LABEL has too many subscribers, expected ACTUAL 80 plus FORECASTED 100 to the owned topic, project spend monitoring UNVERIFIED." >&2
        phase_failed "$PHASE"
      fi
      if [ -z "$SUB_NEXT" ] || [ "$SUB_NEXT" = "END" ] || [ "$SUB_NEXT" = "None" ]; then
        break
      fi
    done
    if [ -n "$SUB_NEXT" ] && [ "$SUB_NEXT" != "END" ] && [ "$SUB_NEXT" != "None" ]; then
      rm -f "$SUB_PAGE" "$SUB_COLLECTED" "$SUB_INPUT"
      echo "refused: foundation budget $NOTIF_LABEL subscribers exceed bounded pages, expected ACTUAL 80 plus FORECASTED 100 to the owned topic, project spend monitoring UNVERIFIED." >&2
      phase_failed "$PHASE"
    fi
    rm -f "$SUB_PAGE" "$SUB_INPUT"
    SUB_PROOF="$(python3 - "$SUB_COLLECTED" "$NOTIF_TOPIC" 2>/dev/null <<'PYEOF'
import json, sys
collected_file, expected_topic = sys.argv[1:3]
try:
    subs = json.load(open(collected_file))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(subs, list):
    print("MALFORMED")
    sys.exit(0)
if len(subs) != 1:
    print("SUBSCRIBER_MISMATCH")
    sys.exit(0)
sub = subs[0]
if not isinstance(sub, dict):
    print("MALFORMED")
    sys.exit(0)
if sub.get("SubscriptionType", "") != "SNS" or sub.get("Address", "") != expected_topic:
    print("SUBSCRIBER_MISMATCH")
    sys.exit(0)
print("SUBSCRIBERS_OK")
PYEOF
)" || { rm -f "$SUB_COLLECTED"; echo "foundation budget $NOTIF_LABEL subscribers unreadable, project spend monitoring UNVERIFIED." >&2; phase_failed "$PHASE"; }
    rm -f "$SUB_COLLECTED"
    SUB_PROOF="$(printf '%s' "$SUB_PROOF" | tr -d '[:space:]')"
    [ "$SUB_PROOF" = "SUBSCRIBERS_OK" ] || { echo "refused: foundation budget $NOTIF_LABEL subscriber is not exactly the owned SNS topic, expected ACTUAL 80 plus FORECASTED 100 to the owned topic, project spend monitoring UNVERIFIED." >&2; phase_failed "$PHASE"; }
  done
  echo "Verified foundation budget alerts: ACTUAL 80 plus FORECASTED 100 to the owned topic, notifications only, never a hard cap."
}

check_foundation_params() {
  if ! python3 - "$FOUNDATION_PARAMETERS_FILE" <<'PYEOF'
import json, sys
params_file = sys.argv[1]
try:
    with open(params_file) as handle:
        doc = json.load(handle)
except Exception:
    raise SystemExit("parameters file is not valid JSON")
if isinstance(doc, dict) and "Parameters" in doc:
    doc = doc["Parameters"]
if not isinstance(doc, list):
    raise SystemExit("parameters file must be a JSON list")
seen = set()
values = {}
for entry in doc:
    if not isinstance(entry, dict) or "ParameterKey" not in entry:
        raise SystemExit("parameters file has a malformed entry")
    key = entry["ParameterKey"]
    if key in seen:
        raise SystemExit("parameters file has a duplicate ParameterKey")
    seen.add(key)
    if key not in ("BudgetLimitUsd", "BudgetNotifyEmail"):
        raise SystemExit("foundation parameters file has an unrecognized key")
    if "ParameterValue" not in entry:
        raise SystemExit("parameters file entry has no explicit ParameterValue")
    value = entry.get("ParameterValue", "")
    if not isinstance(value, str):
        raise SystemExit("parameters file value must be a string")
    if "\n" in value or "\r" in value or "://" in value:
        raise SystemExit("parameters file value has a refused shape")
    values[key] = value
if "BudgetLimitUsd" not in seen or "BudgetNotifyEmail" not in seen:
    raise SystemExit("foundation parameters file must carry BudgetLimitUsd and BudgetNotifyEmail")
limit = values.get("BudgetLimitUsd", "")
if not limit or "REPLACE_WITH" in limit:
    raise SystemExit("BudgetLimitUsd is empty or unreplaced")
try:
    amount = float(limit)
except Exception:
    raise SystemExit("BudgetLimitUsd is not numeric")
if amount <= 0:
    raise SystemExit("BudgetLimitUsd must be greater than zero")
notify = values.get("BudgetNotifyEmail", "")
if "REPLACE_WITH" in notify:
    raise SystemExit("BudgetNotifyEmail is unreplaced")
PYEOF
  then
    echo "refused: foundation parameters file invalid, empty, malformed, or duplicate, no paid prereqs started." >&2
    phase_failed "$PHASE"
  fi
}

check_sns_exact_gate() {
  TOPIC_ARN="$(prereq_stack_resource "$FOUNDATION_STACK_NAME" BudgetTopic 2>"$TMP_ERR")" || { echo "foundation topic lookup failed, no paid phase started." >&2; phase_failed "$PHASE"; }
  TOPIC_ARN="$(printf '%s' "$TOPIC_ARN" | tr -d '[:space:]')"
  [ -n "$TOPIC_ARN" ] && [ "$TOPIC_ARN" != "None" ] || { echo "refused: foundation topic ARN missing, no paid phase started." >&2; phase_failed "$PHASE"; }
  case "$TOPIC_ARN" in
    arn:aws:sns:*:*:*) ;;
    *) echo "refused: foundation topic ARN is malformed, no paid phase started." >&2; phase_failed "$PHASE" ;;
  esac
  TOPIC_COLONS="$(printf '%s' "$TOPIC_ARN" | tr -cd ':' | wc -c)"
  [ "$TOPIC_COLONS" -eq 5 ] || { echo "refused: foundation topic ARN is malformed, no paid phase started." >&2; phase_failed "$PHASE"; }
  [ "$(printf '%s' "$TOPIC_ARN" | cut -d: -f3)" = "sns" ] || { echo "refused: foundation topic ARN is malformed, no paid phase started." >&2; phase_failed "$PHASE"; }
  TOPIC_REGION="$(printf '%s' "$TOPIC_ARN" | cut -d: -f4)"
  TOPIC_ACCOUNT="$(printf '%s' "$TOPIC_ARN" | cut -d: -f5)"
  [ "$TOPIC_REGION" = "$EXPECTED_REGION" ] || { echo "refused: foundation topic region mismatch, no paid phase started." >&2; phase_failed "$PHASE"; }
  [ "$TOPIC_ACCOUNT" = "$EXPECTED_ACCOUNT" ] || { echo "refused: foundation topic account mismatch, no paid phase started." >&2; phase_failed "$PHASE"; }
  SNS_JSON="$(mktemp /tmp/launchcrew-sns-XXXXXX)"
  if ! "$AWS_BIN" sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN" --region "$EXPECTED_REGION" --output json >"$SNS_JSON" 2>"$TMP_ERR"; then
    rm -f "$SNS_JSON"
    ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
    echo "SNS subscription read failed, no paid phase started." >&2
    if is_auth_error "$ERR"; then echo "authorization or API failure, not absence." >&2; fi
    phase_failed "$PHASE"
  fi
  SNS_PROOF="$(python3 - "$SNS_JSON" "$FOUNDATION_PARAMETERS_FILE" "$TOPIC_ARN" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" 2>/dev/null <<'PYEOF'
import json, sys
sns_file, params_file, expected_topic, expected_account, expected_region = sys.argv[1:6]
try:
    doc = json.load(open(sns_file))
except Exception:
    print("MALFORMED")
    sys.exit(0)
try:
    with open(params_file) as handle:
        params = json.load(handle)
except Exception:
    print("MALFORMED")
    sys.exit(0)
if isinstance(params, dict) and "Parameters" in params:
    params = params["Parameters"]
expected_email = ""
if isinstance(params, list):
    for entry in params:
        if isinstance(entry, dict) and entry.get("ParameterKey") == "BudgetNotifyEmail":
            value = entry.get("ParameterValue", "")
            if isinstance(value, str):
                expected_email = value
if not expected_email:
    print("EMPTY_EMAIL")
    sys.exit(0)
subs = doc.get("Subscriptions", None)
if not isinstance(subs, list):
    print("MALFORMED")
    sys.exit(0)
if not subs:
    print("EMPTY")
    sys.exit(0)
try:
    expected_parts = expected_topic.split(":")
    expected_name = expected_parts[5] if len(expected_parts) == 6 else ""
except Exception:
    expected_name = ""
def owned_sub_arn(value):
    if not isinstance(value, str) or not value or value == "PendingConfirmation":
        return False
    parts = value.split(":")
    if len(parts) != 7:
        return False
    if parts[0] != "arn" or parts[1] != "aws" or parts[2] != "sns":
        return False
    if parts[3] != expected_region or parts[4] != expected_account:
        return False
    if not expected_name or parts[5] != expected_name:
        return False
    return bool(parts[6])
exact = 0
confirmed_other = 0
pending_expected = False
for entry in subs:
    if not isinstance(entry, dict):
        continue
    endpoint = entry.get("Endpoint", "")
    protocol = entry.get("Protocol", "")
    topic = entry.get("TopicArn", "")
    sub_arn = entry.get("SubscriptionArn", "")
    owner = entry.get("Owner", "")
    is_exact = (endpoint == expected_email and protocol == "email"
                and topic == expected_topic and owned_sub_arn(sub_arn)
                and owner == expected_account)
    if is_exact:
        exact += 1
        continue
    if isinstance(sub_arn, str) and sub_arn and sub_arn != "PendingConfirmation":
        confirmed_other += 1
    elif (endpoint == expected_email and protocol == "email"
          and topic == expected_topic and sub_arn == "PendingConfirmation"
          and owner == expected_account):
        pending_expected = True
if exact == 1 and confirmed_other == 0 and not pending_expected:
    print("EXACT_OK")
elif exact > 1:
    print("DUPLICATE")
elif exact == 1:
    print("AMBIGUOUS")
elif confirmed_other > 0:
    print("WRONG")
elif pending_expected:
    print("PENDING")
else:
    print("NO_EXACT")
PYEOF
)" || { rm -f "$SNS_JSON"; echo "SNS subscription proof unreadable, no paid phase started." >&2; phase_failed "$PHASE"; }
  rm -f "$SNS_JSON"
  SNS_PROOF="$(printf '%s' "$SNS_PROOF" | tr -d '[:space:]')"
  case "$SNS_PROOF" in
    EXACT_OK) echo "Verified exact confirmed budget email subscription on the owned topic" ;;
    EMPTY_EMAIL) echo "refused: approved notify value is empty, no subscription exists, no paid phase started." >&2; phase_failed "$PHASE" ;;
    EMPTY|PENDING|NO_EXACT) echo "refused: no confirmed exact budget email subscription, confirm the approved address before paid phases, no change made." >&2; phase_failed "$PHASE" ;;
    DUPLICATE) echo "refused: duplicate budget email subscriptions, status ambiguous, no change made." >&2; phase_failed "$PHASE" ;;
    AMBIGUOUS) echo "refused: ambiguous budget subscriptions with extra confirmed entries, no change made." >&2; phase_failed "$PHASE" ;;
    WRONG) echo "refused: confirmed subscription is not the approved exact endpoint and protocol, no change made." >&2; phase_failed "$PHASE" ;;
    *) echo "refused: SNS subscription status unreadable, treated as not confirmed, no change made." >&2; phase_failed "$PHASE" ;;
  esac
}

# Paid gates for every spending phase, read-only and fail-closed. They verify
# the owned foundation stack tags and COMPLETE status, the exact foundation
# budget filter plus alert thresholds, the exact confirmed SNS subscription,
# and the foundation parameters file. CE Active and the Nov 9 expiry guard
# already ran globally before any paid phase. The app stack owns no budget.
check_paid_gates() {
  PAID_LABEL="$1"
  check_foundation_stack
  if [ "$FOUNDATION_EXISTS" -eq 0 ]; then
    echo "refused: foundation stack absent, deploy --phase foundation to COMPLETE first, no paid phase started." >&2
    phase_failed "$PAID_LABEL"
  fi
  case "$FOUNDATION_STATUS" in
    CREATE_COMPLETE|UPDATE_COMPLETE) echo "Verified owned foundation $FOUNDATION_STATUS before paid phase $PAID_LABEL" ;;
    *) echo "refused: foundation stack status is $FOUNDATION_STATUS, required CREATE_COMPLETE or UPDATE_COMPLETE before paid phase $PAID_LABEL." >&2; phase_failed "$PAID_LABEL" ;;
  esac
  check_foundation_params
  check_foundation_budget_filter
  check_foundation_notifications
  check_sns_exact_gate
  echo "Paid gates verified for $PAID_LABEL: owned foundation COMPLETE, exact budget filter plus alerts, exact confirmed SNS, Project Active, expiry guard passed."
}

# Read one parameter value from the app parameters file by key. Prints the
# value or fails. Used for the ACM certificate ARN the SDK jobs expect and
# for prereq binding to the actual applied parameters.
params_file_value() {
  python3 - "$PARAMETERS_FILE" "$1" 2>/dev/null <<'PYEOF'
import json, sys
params_file, want = sys.argv[1:3]
with open(params_file) as handle:
    doc = json.load(handle)
if isinstance(doc, dict) and "Parameters" in doc:
    doc = doc["Parameters"]
for entry in doc:
    if isinstance(entry, dict) and entry.get("ParameterKey") == want:
        value = entry.get("ParameterValue", "")
        if isinstance(value, str) and value:
            print(value)
            sys.exit(0)
sys.exit(1)
PYEOF
}

# Read-only prereqs readiness for every paid app phase, never a deploy. It
# verifies the owned prereqs stack tags and COMPLETE status, binds the exact
# READY physical refs to the actual app parameter AcmCertificateArn plus the
# four secret ARNs, and requires the exact ISSUED exportable cert. Validating
# one cert while applying another is refused. Missing, duplicate, foreign, or
# different refs fail before any deploy or RunTask, metadata only, never a
# secret value. A PENDING_VALIDATION cert stops as PENDING with no ready
# claim and no receipt write; explicit --phase prereqs owns the receipt step.
# Any other non-ISSUED status refuses without a ready claim.
check_prereqs_readiness() {
  READY_LABEL="${1:-all}"
  check_prereqs_stack
  if [ "$PREREQS_EXISTS" -eq 0 ]; then
    echo "refused: prereqs stack absent, run explicit --phase prereqs to COMPLETE first, no ready claim." >&2
    phase_failed "$READY_LABEL"
  fi
  case "$PREREQS_STATUS" in
    CREATE_COMPLETE|UPDATE_COMPLETE) echo "Verified owned prereqs $PREREQS_STATUS before $READY_LABEL" ;;
    *_IN_PROGRESS) echo "Prereqs stack $PREREQS_STATUS in progress, PENDING not ready, rerun --phase prereqs to resume read-only." >&2; phase_failed "$READY_LABEL" ;;
    *) echo "refused: prereqs stack status is $PREREQS_STATUS, explicit review required, no ready claim." >&2; phase_failed "$READY_LABEL" ;;
  esac
  READY_MASTER="$(prereq_stack_resource "$PREREQS_STACK_NAME" MasterSecret 2>"$TMP_ERR")" || { echo "prereqs master secret lookup failed, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  READY_RUNTIME="$(prereq_stack_resource "$PREREQS_STACK_NAME" RuntimeSecret 2>"$TMP_ERR")" || { echo "prereqs runtime secret lookup failed, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  READY_MIGRATION="$(prereq_stack_resource "$PREREQS_STACK_NAME" MigrationSecret 2>"$TMP_ERR")" || { echo "prereqs migration secret lookup failed, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  READY_TLS="$(prereq_stack_resource "$PREREQS_STACK_NAME" TlsSecret 2>"$TMP_ERR")" || { echo "prereqs TLS secret lookup failed, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  READY_CERT="$(prereq_stack_resource "$PREREQS_STACK_NAME" DemoCertificate 2>"$TMP_ERR")" || { echo "prereqs certificate lookup failed, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  READY_MASTER="$(printf '%s' "$READY_MASTER" | tr -d '[:space:]')"
  READY_RUNTIME="$(printf '%s' "$READY_RUNTIME" | tr -d '[:space:]')"
  READY_MIGRATION="$(printf '%s' "$READY_MIGRATION" | tr -d '[:space:]')"
  READY_TLS="$(printf '%s' "$READY_TLS" | tr -d '[:space:]')"
  READY_CERT="$(printf '%s' "$READY_CERT" | tr -d '[:space:]')"
  [ -n "$READY_MASTER" ] && [ "$READY_MASTER" != "None" ] || { echo "refused: prereqs master secret missing, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  [ -n "$READY_RUNTIME" ] && [ "$READY_RUNTIME" != "None" ] || { echo "refused: prereqs runtime secret missing, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  [ -n "$READY_MIGRATION" ] && [ "$READY_MIGRATION" != "None" ] || { echo "refused: prereqs migration secret missing, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  [ -n "$READY_TLS" ] && [ "$READY_TLS" != "None" ] || { echo "refused: prereqs TLS secret missing, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  [ -n "$READY_CERT" ] && [ "$READY_CERT" != "None" ] || { echo "refused: prereqs certificate missing, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  if [ -n "$MASTER_SECRET_ARN" ]; then
    [ "$READY_MASTER" = "$MASTER_SECRET_ARN" ] || { echo "refused: prereqs master secret does not equal the validated CLI ARN, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  fi
  if [ -n "$RUNTIME_SECRET_ARN" ]; then
    [ "$READY_RUNTIME" = "$RUNTIME_SECRET_ARN" ] || { echo "refused: prereqs runtime secret does not equal the validated CLI ARN, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  fi
  if [ -n "$MIGRATION_SECRET_ARN" ]; then
    [ "$READY_MIGRATION" = "$MIGRATION_SECRET_ARN" ] || { echo "refused: prereqs migration secret does not equal the validated CLI ARN, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  fi
  if [ -n "$TLS_SECRET_ARN" ]; then
    [ "$READY_TLS" = "$TLS_SECRET_ARN" ] || { echo "refused: prereqs TLS secret does not equal the validated CLI ARN, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  fi
  if ! FILE_MASTER="$(params_file_value MasterDbPasswordSecretArn)"; then echo "refused: app parameters file has no MasterDbPasswordSecretArn for the owned prereq ref, no ready claim." >&2; phase_failed "$READY_LABEL"; fi
  if ! FILE_RUNTIME="$(params_file_value RuntimeDbUrlSecretArn)"; then echo "refused: app parameters file has no RuntimeDbUrlSecretArn for the owned prereq ref, no ready claim." >&2; phase_failed "$READY_LABEL"; fi
  if ! FILE_MIGRATION="$(params_file_value MigrationDbUrlSecretArn)"; then echo "refused: app parameters file has no MigrationDbUrlSecretArn for the owned prereq ref, no ready claim." >&2; phase_failed "$READY_LABEL"; fi
  if ! FILE_TLS="$(params_file_value TlsSecretArn)"; then echo "refused: app parameters file has no TlsSecretArn for the owned prereq ref, no ready claim." >&2; phase_failed "$READY_LABEL"; fi
  if ! FILE_CERT="$(params_file_value AcmCertificateArn)"; then echo "refused: app parameters file has no AcmCertificateArn for the owned prereq cert, no ready claim." >&2; phase_failed "$READY_LABEL"; fi
  FILE_MASTER="$(printf '%s' "$FILE_MASTER" | tr -d '[:space:]')"
  FILE_RUNTIME="$(printf '%s' "$FILE_RUNTIME" | tr -d '[:space:]')"
  FILE_MIGRATION="$(printf '%s' "$FILE_MIGRATION" | tr -d '[:space:]')"
  FILE_TLS="$(printf '%s' "$FILE_TLS" | tr -d '[:space:]')"
  FILE_CERT="$(printf '%s' "$FILE_CERT" | tr -d '[:space:]')"
  [ "$FILE_MASTER" = "$READY_MASTER" ] || { echo "refused: app parameter MasterDbPasswordSecretArn does not equal the owned prereq ref, validating one set while applying another is refused, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  [ "$FILE_RUNTIME" = "$READY_RUNTIME" ] || { echo "refused: app parameter RuntimeDbUrlSecretArn does not equal the owned prereq ref, validating one set while applying another is refused, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  [ "$FILE_MIGRATION" = "$READY_MIGRATION" ] || { echo "refused: app parameter MigrationDbUrlSecretArn does not equal the owned prereq ref, validating one set while applying another is refused, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  [ "$FILE_TLS" = "$READY_TLS" ] || { echo "refused: app parameter TlsSecretArn does not equal the owned prereq ref, validating one set while applying another is refused, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  [ "$FILE_CERT" = "$READY_CERT" ] || { echo "refused: app parameter AcmCertificateArn does not equal the owned prereq cert, validating cert A while applying cert B is refused, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  check_secret_arn "$READY_MASTER" "prereqs-master"
  check_secret_arn "$READY_RUNTIME" "prereqs-runtime"
  check_secret_arn "$READY_MIGRATION" "prereqs-migration"
  check_secret_arn "$READY_TLS" "prereqs-tls"
  case "$READY_CERT" in
    arn:aws:acm:*:*:certificate/*) ;;
    *) echo "refused: prereqs certificate ARN is malformed, no ready claim." >&2; phase_failed "$READY_LABEL" ;;
  esac
  [ "$(printf '%s' "$READY_CERT" | cut -d: -f4)" = "$EXPECTED_REGION" ] || { echo "refused: prereqs certificate region mismatch, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  [ "$(printf '%s' "$READY_CERT" | cut -d: -f5)" = "$EXPECTED_ACCOUNT" ] || { echo "refused: prereqs certificate account mismatch, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  READY_CERT_JSON="$(mktemp /tmp/launchcrew-ready-cert-XXXXXX)"
  if ! "$AWS_BIN" acm describe-certificate --certificate-arn "$READY_CERT" --region "$EXPECTED_REGION" --output json >"$READY_CERT_JSON" 2>"$TMP_ERR"; then
    rm -f "$READY_CERT_JSON"
    echo "certificate state unreadable, no ready claim." >&2
    phase_failed "$READY_LABEL"
  fi
  READY_PARSED="$(python3 - "$READY_CERT_JSON" "$READY_CERT" 2>/dev/null <<'PYEOF'
import json, sys
cert_file, expected_arn = sys.argv[1:3]
expected_domain = "launchcrew.summitsingh.com"
try:
    doc = json.load(open(cert_file))
except Exception:
    sys.exit(1)
cert = doc.get("Certificate", {})
if not isinstance(cert, dict):
    cert = {}
status = cert.get("Status", "") or ""
domain = cert.get("DomainName", "") or ""
returned_arn = cert.get("CertificateArn", "") or ""
cert_type = cert.get("Type", "") or ""
options = cert.get("Options", {}) or {}
if not isinstance(options, dict):
    options = {}
export_flag = options.get("Export", "") or ""
sans = cert.get("SubjectAlternativeNames", None)
proof = "CERT_OK"
if returned_arn != expected_arn:
    proof = "ARN_MISMATCH"
elif domain != expected_domain:
    proof = "DOMAIN_MISMATCH"
elif not isinstance(sans, list) or sans != [expected_domain]:
    proof = "SAN_MISMATCH"
elif cert_type != "AMAZON_ISSUED":
    proof = "TYPE_MISMATCH"
elif export_flag != "ENABLED":
    proof = "EXPORT_MISMATCH"
print("STATUS\t%s" % status)
print("PROOF\t%s" % proof)
PYEOF
)" || { rm -f "$READY_CERT_JSON"; echo "certificate state unreadable, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  rm -f "$READY_CERT_JSON"
  READY_STATUS="$(printf '%s\n' "$READY_PARSED" | awk -F'\t' '$1=="STATUS"{print $2}')"
  READY_PROOF="$(printf '%s\n' "$READY_PARSED" | awk -F'\t' '$1=="PROOF"{print $2}')"
  READY_STATUS="$(printf '%s' "$READY_STATUS" | tr -d '[:space:]')"
  READY_PROOF="$(printf '%s' "$READY_PROOF" | tr -d '[:space:]')"
  [ "$READY_PROOF" = "CERT_OK" ] || { echo "refused: prereqs certificate identity mismatch ($READY_PROOF), no ready claim." >&2; phase_failed "$READY_LABEL"; }
  if [ "$READY_STATUS" = "PENDING_VALIDATION" ]; then
    echo "Prereqs certificate PENDING_VALIDATION, PENDING not ready: add the CNAME via explicit --phase prereqs, then rerun. No ready claim." >&2
    phase_failed "$READY_LABEL"
  fi
  [ "$READY_STATUS" = "ISSUED" ] || { echo "refused: prereqs certificate status is $READY_STATUS, expected ISSUED, no ready claim." >&2; phase_failed "$READY_LABEL"; }
  echo "Prereqs ready: owned COMPLETE stack, four owned secret metadata records, ISSUED exportable cert."
}

prereqs_deploy() {
  if [ "$PREREQS_EXISTS" -eq 0 ]; then
    if ! "$AWS_BIN" cloudformation create-stack --stack-name "$PREREQS_STACK_NAME" --template-body "file://$PREREQS_TEMPLATE_FILE" --tags Key=Project,Value=LaunchCrew Key=Environment,Value=demo --region "$EXPECTED_REGION" >"$TMP_JSON" 2>"$TMP_ERR"; then
      echo "refused: prereqs create failed, no claim made" >&2
      phase_failed prereqs
    fi
  else
    case "$PREREQS_STATUS" in
      *_IN_PROGRESS)
        echo "Prereqs stack $PREREQS_STATUS in progress, observing only, no update attempted" ;;
      CREATE_COMPLETE|UPDATE_COMPLETE)
        echo "Prereqs stack $PREREQS_STATUS complete, verifying without gratuitous update to preserve managed secrets and cert" ;;
      *)
        echo "refused: prereqs stack status is $PREREQS_STATUS, explicit review required, no automatic update to avoid secret or cert rotation" >&2
        phase_failed prereqs ;;
    esac
  fi
}

if [ "$PHASE" = "foundation" ]; then
  echo "Phase foundation: deploy Budget plus SNS"
  check_foundation_stack
  WAS_NEW="$FOUNDATION_EXISTS"
  if ! foundation_deploy; then
    echo "foundation deploy failed, no later phase started." >&2
    phase_failed foundation
  fi
  if [ "$WAS_NEW" -eq 0 ]; then
    if ! "$AWS_BIN" cloudformation wait stack-create-complete --stack-name "$FOUNDATION_STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
      echo "foundation create wait reported, verifying stack status before any claim." >&2
    fi
  else
    if ! "$AWS_BIN" cloudformation wait stack-update-complete --stack-name "$FOUNDATION_STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
      ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
      if is_auth_error "$ERR"; then
        echo "foundation wait authorization failure, state unknown, no later phase started." >&2
        phase_failed foundation
      fi
      echo "foundation wait reported, verifying stack status before any claim." >&2
    fi
  fi
  require_foundation_complete
  check_foundation_budget_filter
  check_foundation_notifications
  echo "Phase foundation complete: Budget plus SNS deployed, subscription confirmation stays an explicit operator step before paid phases"
  mark_done foundation
fi

if [ "$PHASE" = "prereqs" ]; then
  echo "Phase prereqs: exact SNS gate, then Secrets plus exportable ACM"
  check_foundation_stack
  if [ "$FOUNDATION_EXISTS" -eq 0 ]; then
    echo "refused: foundation stack absent, deploy --phase foundation to COMPLETE first, no paid prereqs started." >&2
    phase_failed prereqs
  fi
  case "$FOUNDATION_STATUS" in
    CREATE_COMPLETE|UPDATE_COMPLETE) echo "Verified owned foundation $FOUNDATION_STATUS before paid prereqs" ;;
    *) echo "refused: foundation stack status is $FOUNDATION_STATUS, required CREATE_COMPLETE or UPDATE_COMPLETE before paid prereqs." >&2; phase_failed prereqs ;;
  esac
  check_foundation_params
  check_foundation_budget_filter
  check_foundation_notifications
  check_sns_exact_gate
  check_prereqs_stack
  prereqs_deploy
  if ! PREREQS_STATUS_NOW="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$PREREQS_STACK_NAME" --region "$EXPECTED_REGION" --query "Stacks[0].StackStatus" --output text 2>"$TMP_ERR")"; then
    echo "prereqs stack status unreadable after deploy, not treated as success." >&2
    phase_failed prereqs
  fi
  PREREQS_STATUS_NOW="$(printf '%s' "$PREREQS_STATUS_NOW" | tr -d '[:space:]')"
  PREREQS_STATUS="$PREREQS_STATUS_NOW"
  CERT_ARN="$(observe_prereq_resource "$PREREQS_STACK_NAME" DemoCertificate)" || { echo "prereqs certificate not yet visible after bounded observations, rerun --phase prereqs to resume read-only, no recreate or update attempted." >&2; phase_failed prereqs; }
  CERT_ARN="$(printf '%s' "$CERT_ARN" | tr -d '[:space:]')"
  [ -n "$CERT_ARN" ] && [ "$CERT_ARN" != "None" ] || { echo "refused: prereqs certificate ARN missing after bounded observations, rerun to resume read-only." >&2; phase_failed prereqs; }
  case "$CERT_ARN" in
    arn:aws:acm:*:*:certificate/*) ;;
    *) echo "refused: prereqs certificate ARN is malformed, no claim made." >&2; phase_failed prereqs ;;
  esac
  [ "$(printf '%s' "$CERT_ARN" | cut -d: -f4)" = "$EXPECTED_REGION" ] || { echo "refused: prereqs certificate region mismatch, no claim made." >&2; phase_failed prereqs; }
  [ "$(printf '%s' "$CERT_ARN" | cut -d: -f5)" = "$EXPECTED_ACCOUNT" ] || { echo "refused: prereqs certificate account mismatch, no claim made." >&2; phase_failed prereqs; }
  MASTER_ARN="$(observe_prereq_resource "$PREREQS_STACK_NAME" MasterSecret)" || { echo "prereqs master secret not yet visible after bounded observations, rerun --phase prereqs to resume read-only." >&2; phase_failed prereqs; }
  RUNTIME_ARN="$(observe_prereq_resource "$PREREQS_STACK_NAME" RuntimeSecret)" || { echo "prereqs runtime secret not yet visible after bounded observations, rerun --phase prereqs to resume read-only." >&2; phase_failed prereqs; }
  MIGRATION_ARN="$(observe_prereq_resource "$PREREQS_STACK_NAME" MigrationSecret)" || { echo "prereqs migration secret not yet visible after bounded observations, rerun --phase prereqs to resume read-only." >&2; phase_failed prereqs; }
  TLS_ARN="$(observe_prereq_resource "$PREREQS_STACK_NAME" TlsSecret)" || { echo "prereqs TLS secret not yet visible after bounded observations, rerun --phase prereqs to resume read-only." >&2; phase_failed prereqs; }
  MASTER_ARN="$(printf '%s' "$MASTER_ARN" | tr -d '[:space:]')"
  RUNTIME_ARN="$(printf '%s' "$RUNTIME_ARN" | tr -d '[:space:]')"
  MIGRATION_ARN="$(printf '%s' "$MIGRATION_ARN" | tr -d '[:space:]')"
  TLS_ARN="$(printf '%s' "$TLS_ARN" | tr -d '[:space:]')"
  check_secret_arn "$MASTER_ARN" "prereqs-master"
  check_secret_arn "$RUNTIME_ARN" "prereqs-runtime"
  check_secret_arn "$MIGRATION_ARN" "prereqs-migration"
  check_secret_arn "$TLS_ARN" "prereqs-tls"
  CERT_JSON="$(mktemp /tmp/launchcrew-cert-XXXXXX)"
  CERT_TRY=1
  CERT_PARSED=""
  while [ "$CERT_TRY" -le 5 ]; do
    if ! "$AWS_BIN" acm describe-certificate --certificate-arn "$CERT_ARN" --region "$EXPECTED_REGION" --output json >"$CERT_JSON" 2>"$TMP_ERR"; then
      rm -f "$CERT_JSON"
      echo "certificate state unreadable, not treated as issued." >&2
      phase_failed prereqs
    fi
    if ! CERT_PARSED="$(python3 - "$CERT_JSON" "$CERT_ARN" 2>/dev/null <<'PYEOF'
import json, sys
cert_file, expected_arn = sys.argv[1:3]
expected_domain = "launchcrew.summitsingh.com"
try:
    doc = json.load(open(cert_file))
except Exception:
    sys.exit(1)
cert = doc.get("Certificate", {})
if not isinstance(cert, dict):
    cert = {}
status = cert.get("Status", "") or ""
domain = cert.get("DomainName", "") or ""
returned_arn = cert.get("CertificateArn", "") or ""
cert_type = cert.get("Type", "") or ""
options = cert.get("Options", {}) or {}
if not isinstance(options, dict):
    options = {}
export_flag = options.get("Export", "") or ""
sans = cert.get("SubjectAlternativeNames", None)
name = ""
value = ""
record_type = ""
proof = "CERT_OK"
if returned_arn != expected_arn:
    proof = "ARN_MISMATCH"
elif domain != expected_domain:
    proof = "DOMAIN_MISMATCH"
elif not isinstance(sans, list) or sans != [expected_domain]:
    proof = "SAN_MISMATCH"
elif any("*" in (s or "") for s in sans):
    proof = "SAN_MISMATCH"
elif cert_type != "AMAZON_ISSUED":
    proof = "TYPE_MISMATCH"
elif export_flag != "ENABLED":
    proof = "EXPORT_MISMATCH"
else:
    try:
        dvo_list = cert.get("DomainValidationOptions", []) or []
    except Exception:
        dvo_list = []
    relevant = None
    if isinstance(dvo_list, list):
        for opt in dvo_list:
            if isinstance(opt, dict) and opt.get("DomainName", "") == expected_domain:
                relevant = opt
                break
    if relevant is None:
        proof = "VALIDATION_MISMATCH"
    else:
        method = relevant.get("ValidationMethod", "DNS")
        if "ValidationMethod" in relevant and method != "DNS":
            proof = "VALIDATION_MISMATCH"
        else:
            record = relevant.get("ResourceRecord", None)
            if record is None:
                proof = "CERT_OK"
            elif not isinstance(record, dict):
                proof = "RECORD_MISMATCH"
            else:
                record_type = record.get("Type", "") or ""
                name = record.get("Name", "") or ""
                value = record.get("Value", "") or ""
                if record_type == "" and name == "" and value == "":
                    proof = "CERT_OK"
                elif record_type != "CNAME":
                    proof = "RECORD_MISMATCH"
                else:
                    proof = "CERT_OK"
print("STATUS\t%s" % status)
print("DOMAIN\t%s" % domain)
print("NAME\t%s" % name)
print("VALUE\t%s" % value)
print("PROOF\t%s" % proof)
PYEOF
)"; then
      rm -f "$CERT_JSON"
      echo "certificate state unreadable, not treated as issued." >&2
      phase_failed prereqs
    fi
    CERT_STATUS_TMP="$(printf '%s\n' "$CERT_PARSED" | awk -F'\t' '$1=="STATUS"{print $2}')"
    CERT_STATUS_TMP="$(printf '%s' "$CERT_STATUS_TMP" | tr -d '[:space:]')"
    VALIDATION_NAME_TMP="$(printf '%s\n' "$CERT_PARSED" | awk -F'\t' '$1=="NAME"{print $2}')"
    VALIDATION_VALUE_TMP="$(printf '%s\n' "$CERT_PARSED" | awk -F'\t' '$1=="VALUE"{print $2}')"
    CERT_PROOF_TMP="$(printf '%s\n' "$CERT_PARSED" | awk -F'\t' '$1=="PROOF"{print $2}')"
    CERT_PROOF_TMP="$(printf '%s' "$CERT_PROOF_TMP" | tr -d '[:space:]')"
    if [ "$CERT_PROOF_TMP" = "CERT_OK" ] && [ "$CERT_STATUS_TMP" = "PENDING_VALIDATION" ]; then
      if [ -n "$VALIDATION_NAME_TMP" ] && [ -n "$VALIDATION_VALUE_TMP" ]; then
        break
      elif [ "$CERT_TRY" -lt 5 ]; then
        sleep 2 2>/dev/null || true
        CERT_TRY=$((CERT_TRY + 1))
        continue
      else
        break
      fi
    else
      break
    fi
  done
  rm -f "$CERT_JSON"
  CERT_STATUS="$(printf '%s\n' "$CERT_PARSED" | awk -F'\t' '$1=="STATUS"{print $2}')"
  CERT_DOMAIN="$(printf '%s\n' "$CERT_PARSED" | awk -F'\t' '$1=="DOMAIN"{print $2}')"
  VALIDATION_NAME="$(printf '%s\n' "$CERT_PARSED" | awk -F'\t' '$1=="NAME"{print $2}')"
  VALIDATION_VALUE="$(printf '%s\n' "$CERT_PARSED" | awk -F'\t' '$1=="VALUE"{print $2}')"
  CERT_PROOF="$(printf '%s\n' "$CERT_PARSED" | awk -F'\t' '$1=="PROOF"{print $2}')"
  CERT_STATUS="$(printf '%s' "$CERT_STATUS" | tr -d '[:space:]')"
  CERT_PROOF="$(printf '%s' "$CERT_PROOF" | tr -d '[:space:]')"
  case "$CERT_PROOF" in
    CERT_OK) ;;
    ARN_MISMATCH) echo "refused: certificate ARN mismatch, describe returned a different ARN, no claim made." >&2; phase_failed prereqs ;;
    DOMAIN_MISMATCH) echo "refused: certificate domain mismatch, expected the exact demo hostname, no claim made." >&2; phase_failed prereqs ;;
    SAN_MISMATCH) echo "refused: certificate SAN mismatch, expected exact hostname only with no wildcard, no claim made." >&2; phase_failed prereqs ;;
    TYPE_MISMATCH) echo "refused: certificate type mismatch, expected AMAZON_ISSUED, no claim made." >&2; phase_failed prereqs ;;
    EXPORT_MISMATCH) echo "refused: certificate export mismatch, expected Options Export ENABLED, no claim made." >&2; phase_failed prereqs ;;
    VALIDATION_MISMATCH) echo "refused: certificate validation mismatch, expected DNS validation for the exact hostname, no claim made." >&2; phase_failed prereqs ;;
    RECORD_MISMATCH) echo "refused: certificate validation record mismatch, expected CNAME type, no claim made." >&2; phase_failed prereqs ;;
    *) echo "refused: certificate validation unreadable, no claim made." >&2; phase_failed prereqs ;;
  esac
  if ! CERT_TAGS_JSON="$("$AWS_BIN" acm list-tags-for-certificate --certificate-arn "$CERT_ARN" --region "$EXPECTED_REGION" --output json 2>"$TMP_ERR")"; then
    echo "certificate tag check failed, not treated as owned." >&2
    phase_failed prereqs
  fi
  printf '%s' "$CERT_TAGS_JSON" >"$TMP_JSON"
  CERT_TAGS="$(python3 - "$TMP_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
tags = {t.get("Key"): t.get("Value") for t in doc.get("Tags", []) if isinstance(t, dict)}
print("PROJECT\t%s" % tags.get("Project", ""))
print("ENV\t%s" % tags.get("Environment", ""))
PYEOF
)" || { echo "certificate tag check failed, not treated as owned." >&2; phase_failed prereqs; }
  CERT_PROJECT="$(printf '%s\n' "$CERT_TAGS" | awk -F'\t' '$1=="PROJECT"{print $2}')"
  CERT_ENV="$(printf '%s\n' "$CERT_TAGS" | awk -F'\t' '$1=="ENV"{print $2}')"
  [ "$CERT_PROJECT" = "LaunchCrew" ] || { echo "refused: certificate Project tag mismatch, no claim made." >&2; phase_failed prereqs; }
  [ "$CERT_ENV" = "demo" ] || { echo "refused: certificate Environment tag mismatch, no claim made." >&2; phase_failed prereqs; }
  if [ "$CERT_STATUS" = "PENDING_VALIDATION" ]; then
    [ -n "$VALIDATION_NAME" ] && [ -n "$VALIDATION_VALUE" ] || { echo "validation CNAME not yet visible after bounded observations, rerun --phase prereqs to resume read-only, no recreate or update attempted." >&2; phase_failed prereqs; }
    if ! (umask 077; python3 - "$DNS_RECEIPT_FILE" "$PREREQS_STACK_NAME" "$FOUNDATION_STACK_NAME" "$EXPECTED_REGION" "$CERT_ARN" "$CERT_STATUS" "$CERT_DOMAIN" "$VALIDATION_NAME" "$VALIDATION_VALUE" "$MASTER_ARN" "$RUNTIME_ARN" "$MIGRATION_ARN" "$TLS_ARN" "$PREREQS_STATUS_NOW" <<'PYEOF'
import json, os, sys, tempfile
(path, prereqs_stack, foundation_stack, region, cert_arn, cert_status,
 cert_domain, v_name, v_value, master_arn, runtime_arn,
 migration_arn, tls_arn, stack_status) = sys.argv[1:15]
if os.path.islink(path):
    raise SystemExit("refused: receipt path is a symlink")
doc = {
    "prereqs_stack": prereqs_stack,
    "foundation_stack": foundation_stack,
    "region": region,
    "stack_status": stack_status,
    "certificate_arn": cert_arn,
    "certificate_status": cert_status,
    "domain": cert_domain,
    "validation_name": v_name,
    "validation_value": v_value,
    "secrets": {
        "master": master_arn,
        "runtime": runtime_arn,
        "migration": migration_arn,
        "tls": tls_arn,
    },
}
directory = os.path.dirname(os.path.abspath(path)) or "."
fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".dns-receipt-")
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(doc, out, indent=2, sort_keys=True)
        out.write("\n")
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)
except Exception:
    try:
        os.unlink(tmp_path)
    except Exception:
        pass
    raise
PYEOF
); then
      echo "refused: private DNS receipt write failed, no claim made." >&2
      phase_failed prereqs
    fi
    chmod 600 "$DNS_RECEIPT_FILE" 2>/dev/null || { echo "refused: private DNS receipt mode failed, no claim made." >&2; phase_failed prereqs; }
    echo "Public DNS validation CNAME name: $VALIDATION_NAME"
    echo "Public DNS validation CNAME value: $VALIDATION_VALUE"
    echo "Prereqs stack $PREREQS_STATUS_NOW with PENDING_VALIDATION is expected, add the CNAME via Codex DNS, then rerun --phase prereqs after validation"
    echo "Private DNS receipt written with bounded metadata and no secret values"
    mark_done prereqs
  elif [ "$CERT_STATUS" = "ISSUED" ]; then
    case "$PREREQS_STATUS_NOW" in
      CREATE_COMPLETE|UPDATE_COMPLETE) ;;
      *) echo "Certificate ISSUED but prereqs stack is $PREREQS_STATUS_NOW, rerun --phase prereqs to observe completion" >&2; phase_failed prereqs ;;
    esac
    if ! (umask 077; python3 - "$DNS_RECEIPT_FILE" "$PREREQS_STACK_NAME" "$FOUNDATION_STACK_NAME" "$EXPECTED_REGION" "$CERT_ARN" "$CERT_STATUS" "$CERT_DOMAIN" "$VALIDATION_NAME" "$VALIDATION_VALUE" "$MASTER_ARN" "$RUNTIME_ARN" "$MIGRATION_ARN" "$TLS_ARN" "$PREREQS_STATUS_NOW" <<'PYEOF'
import json, os, sys, tempfile
(path, prereqs_stack, foundation_stack, region, cert_arn, cert_status,
 cert_domain, v_name, v_value, master_arn, runtime_arn,
 migration_arn, tls_arn, stack_status) = sys.argv[1:15]
if os.path.islink(path):
    raise SystemExit("refused: receipt path is a symlink")
doc = {
    "prereqs_stack": prereqs_stack,
    "foundation_stack": foundation_stack,
    "region": region,
    "stack_status": stack_status,
    "certificate_arn": cert_arn,
    "certificate_status": cert_status,
    "domain": cert_domain,
    "validation_name": v_name,
    "validation_value": v_value,
    "secrets": {
        "master": master_arn,
        "runtime": runtime_arn,
        "migration": migration_arn,
        "tls": tls_arn,
    },
}
directory = os.path.dirname(os.path.abspath(path)) or "."
fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".dns-receipt-")
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(doc, out, indent=2, sort_keys=True)
        out.write("\n")
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)
except Exception:
    try:
        os.unlink(tmp_path)
    except Exception:
        pass
    raise
PYEOF
); then
      echo "refused: private DNS receipt write failed, no claim made." >&2
      phase_failed prereqs
    fi
    chmod 600 "$DNS_RECEIPT_FILE" 2>/dev/null || { echo "refused: private DNS receipt mode failed, no claim made." >&2; phase_failed prereqs; }
    echo "Prereqs ready: ISSUED cert plus four owned secret metadata records"
    echo "Private DNS receipt written with bounded metadata and no secret values"
    mark_done prereqs
  else
    echo "refused: certificate status is $CERT_STATUS, expected ISSUED or PENDING_VALIDATION, no claim made." >&2
    phase_failed prereqs
  fi
fi

# Full-chain readiness for every paid app phase, read-only before mutation.
# Already issued owned stacks verify by readback; PENDING stops, not ready.
# Every standalone paid mutation verifies foundation plus owned ISSUED
# prereqs with exact cert and secret binding, not just all.
if [ "$PHASE" = "all" ]; then
  echo "Phase all readiness: owned foundation plus owned prereqs"
  check_paid_gates all
  check_prereqs_readiness all
fi
case "$PHASE" in
  infra|init|material|dbroles|migrate|enable|quiesce)
    check_paid_gates "$PHASE"
    check_prereqs_readiness "$PHASE" ;;
esac

if wants_phase infra; then
  echo "Phase infra: deploy stack"
  if [ "$STACK_EXISTS" -eq 1 ]; then
    require_stack_complete infra
  fi
  # Owned updates never refresh task definitions or images under running
  # services. When EnableServices is true on the existing owned stack, infra
  # and all refuse here; the operator must run explicit phase quiesce first,
  # then rerun infra with services at 0. Fresh stacks start stopped.
  if [ "$STACK_EXISTS" -eq 1 ] && [ "$CURRENT_ENABLE" = "true" ]; then
    echo "refused: owned stack has EnableServices=true with running services; task definition and image updates are blocked. Run explicit --phase quiesce with --quiesce-confirm <exact-StackId> first, then rerun --phase infra. No change made." >&2
    phase_failed infra
  fi
  TARGET_SERVICES="false"
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
  echo "Phase infra complete: stack $STACK_STATUS, services at 0 for safe update"
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

# Resolve the exact owned physical IAM role ARN for a stack logical role ID.
# CloudFormation generates physical role names that differ from logical IDs,
# so the logical ID is never treated as an ARN. The physical name comes from
# describe-stack-resource, then iam get-role returns the exact ARN, which must
# carry the expected account. Prints the ARN on stdout.
resolve_role_arn() {
  RESOLVE_LOGICAL="$1"
  RESOLVE_NAME="$(stack_resource "$RESOLVE_LOGICAL" 2>"$TMP_ERR")" || return 1
  RESOLVE_NAME="$(printf '%s' "$RESOLVE_NAME" | tr -d '[:space:]')"
  [ -n "$RESOLVE_NAME" ] && [ "$RESOLVE_NAME" != "None" ] || return 1
  RESOLVE_ARN=""
  if ! RESOLVE_ARN="$("$AWS_BIN" iam get-role --role-name "$RESOLVE_NAME" --query Role.Arn --output text --region "$EXPECTED_REGION" 2>"$TMP_ERR")"; then
    return 1
  fi
  RESOLVE_ARN="$(printf '%s' "$RESOLVE_ARN" | tr -d '[:space:]')"
  case "$RESOLVE_ARN" in
    "arn:aws:iam::$EXPECTED_ACCOUNT:role/"*) printf '%s' "$RESOLVE_ARN" ;;
    *) return 1 ;;
  esac
}

# Resolve the exact owned physical IAM role name for a stack logical role ID.
# Used for LAUNCHCREW_EXPECTED_ROLE, which carries the !Ref role name, not an
# ARN. Prints the name on stdout.
resolve_role_name() {
  RESOLVE_LOGICAL="$1"
  RESOLVE_NAME="$(stack_resource "$RESOLVE_LOGICAL" 2>"$TMP_ERR")" || return 1
  RESOLVE_NAME="$(printf '%s' "$RESOLVE_NAME" | tr -d '[:space:]')"
  [ -n "$RESOLVE_NAME" ] && [ "$RESOLVE_NAME" != "None" ] || return 1
  printf '%s' "$RESOLVE_NAME"
}

# Require the owned task definition to inject exactly the validated secrets
# and to run under the exact owned physical execution and task roles. Each
# pair is container.SECRETNAME=exact-ValueFrom. Both role ARNs resolve via
# describe-stack-resource plus iam get-role, never from the logical ID.
# Inspection happens here, before any one-off task starts and secret values
# are injected.
check_taskdef_binding() {
  BIND_LOGICAL="$1"
  BIND_EXEC_LOGICAL="$2"
  BIND_TASK_LOGICAL="$3"
  shift 3
  if ! BIND_EXEC_ARN="$(resolve_role_arn "$BIND_EXEC_LOGICAL")"; then
    echo "$BIND_LOGICAL owned execution role $BIND_EXEC_LOGICAL unresolvable, secrets not tied to an owned task." >&2
    phase_failed "$PHASE"
  fi
  if ! BIND_TASK_ARN="$(resolve_role_arn "$BIND_TASK_LOGICAL")"; then
    echo "$BIND_LOGICAL owned task role $BIND_TASK_LOGICAL unresolvable, secrets not tied to an owned task." >&2
    phase_failed "$PHASE"
  fi
  BIND_JSON="$(mktemp /tmp/launchcrew-bind-XXXXXX)"
  if ! fetch_taskdef_json "$BIND_LOGICAL" "$BIND_JSON"; then
    rm -f "$BIND_JSON"
    echo "$BIND_LOGICAL task definition missing, secrets not tied to an owned task." >&2
    phase_failed "$PHASE"
  fi
  BIND_EXPECTED="$(mktemp /tmp/launchcrew-expected-XXXXXX)"
  printf '%s\n' "$@" >"$BIND_EXPECTED"
  BIND_PROOF="$(python3 - "$BIND_JSON" "$BIND_EXPECTED" "$BIND_EXEC_ARN" "$BIND_TASK_ARN" 2>/dev/null <<'PYEOF'
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
exec_arn, task_arn = sys.argv[3], sys.argv[4]
taskdef = doc.get("taskDefinition", doc)
if (taskdef.get("executionRoleArn", "") or "") != exec_arn:
    print("EXEC_ROLE_MISMATCH")
    sys.exit(0)
if (taskdef.get("taskRoleArn", "") or "") != task_arn:
    print("TASK_ROLE_MISMATCH")
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
    OK) echo "Verified owned task definition secrets plus execution and task roles: $BIND_LOGICAL" ;;
    *) echo "refused: $BIND_LOGICAL task definition binding proof is $BIND_PROOF, secrets not proven owned." >&2; phase_failed "$PHASE" ;;
  esac
}

# Resolve the exact owned RDS endpoint address read-only. The Database stack
# resource yields the instance identifier, then rds describe-db-instances
# returns the live Endpoint Address. Prints the address on stdout.
owned_db_endpoint() {
  DB_INSTANCE="$(stack_resource Database 2>"$TMP_ERR")" || return 1
  DB_INSTANCE="$(printf '%s' "$DB_INSTANCE" | tr -d '[:space:]')"
  [ -n "$DB_INSTANCE" ] && [ "$DB_INSTANCE" != "None" ] || return 1
  DB_ENDPOINT=""
  if ! DB_ENDPOINT="$("$AWS_BIN" rds describe-db-instances --db-instance-identifier "$DB_INSTANCE" --region "$EXPECTED_REGION" --query "DBInstances[0].Endpoint.Address" --output text 2>"$TMP_ERR")"; then
    return 1
  fi
  DB_ENDPOINT="$(printf '%s' "$DB_ENDPOINT" | tr -d '[:space:]')"
  [ -n "$DB_ENDPOINT" ] && [ "$DB_ENDPOINT" != "None" ] || return 1
  printf '%s' "$DB_ENDPOINT"
}

# Require the owned SDK task definition to carry the exact job shape before
# any RunTask: the verified bootstrap image, explicit EntryPoint to
# populate_prereqs.py, exact Command flag, exact metadata env with zero
# injected Secrets entries, and the exact owned physical execution and task
# roles. Args: taskdef logical, exec role logical, task role logical,
# container name, command flag (--populate or --verify-material).
check_sdk_taskdef() {
  SDK_LOGICAL="$1"
  SDK_EXEC_LOGICAL="$2"
  SDK_TASK_LOGICAL="$3"
  SDK_CONTAINER="$4"
  SDK_COMMAND="$5"
  if ! SDK_EXEC_ARN="$(resolve_role_arn "$SDK_EXEC_LOGICAL")"; then
    echo "$SDK_LOGICAL owned execution role $SDK_EXEC_LOGICAL unresolvable, SDK job not proven owned." >&2
    phase_failed "$PHASE"
  fi
  if ! SDK_TASK_ARN="$(resolve_role_arn "$SDK_TASK_LOGICAL")"; then
    echo "$SDK_LOGICAL owned task role $SDK_TASK_LOGICAL unresolvable, SDK job not proven owned." >&2
    phase_failed "$PHASE"
  fi
  if ! SDK_TASK_NAME="$(resolve_role_name "$SDK_TASK_LOGICAL")"; then
    echo "$SDK_LOGICAL owned task role name unresolvable, SDK job not proven owned." >&2
    phase_failed "$PHASE"
  fi
  if ! SDK_CERT_ARN="$(params_file_value AcmCertificateArn)"; then
    echo "$SDK_LOGICAL certificate ARN missing from parameters file, SDK job not proven owned." >&2
    phase_failed "$PHASE"
  fi
  SDK_CERT_ARN="$(printf '%s' "$SDK_CERT_ARN" | tr -d '[:space:]')"
  if ! SDK_DB_HOST="$(owned_db_endpoint)"; then
    echo "$SDK_LOGICAL owned database endpoint unreadable, SDK job not proven owned." >&2
    phase_failed "$PHASE"
  fi
  SDK_JSON="$(mktemp /tmp/launchcrew-sdk-XXXXXX)"
  if ! fetch_taskdef_json "$SDK_LOGICAL" "$SDK_JSON"; then
    rm -f "$SDK_JSON"
    echo "$SDK_LOGICAL task definition missing, SDK job not tied to an owned task." >&2
    phase_failed "$PHASE"
  fi
  SDK_PROOF="$(python3 - "$SDK_JSON" "$SDK_CONTAINER" "$BOOTSTRAP_IMAGE" "$SDK_COMMAND" "$SDK_EXEC_ARN" "$SDK_TASK_ARN" "$SDK_TASK_NAME" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$MASTER_SECRET_ARN" "$RUNTIME_SECRET_ARN" "$MIGRATION_SECRET_ARN" "$TLS_SECRET_ARN" "$SDK_CERT_ARN" "$SDK_DB_HOST" 2>/dev/null <<'PYEOF'
import json, sys
(doc_file, want_container, want_image, want_command, want_exec, want_task,
 want_role_name, want_account, want_region, want_master, want_runtime,
 want_migration, want_tls, want_cert, want_host) = sys.argv[1:16]
try:
    doc = json.load(open(doc_file))
except Exception:
    sys.exit(1)
taskdef = doc.get("taskDefinition", doc)
if (taskdef.get("executionRoleArn", "") or "") != want_exec:
    print("EXEC_ROLE_MISMATCH")
    sys.exit(0)
if (taskdef.get("taskRoleArn", "") or "") != want_task:
    print("TASK_ROLE_MISMATCH")
    sys.exit(0)
containers = taskdef.get("containerDefinitions", []) or []
target = None
for container in containers:
    if (container.get("name", "") or "") == want_container:
        target = container
        break
if target is None:
    print("MISSING_CONTAINER")
    sys.exit(0)
if (target.get("image", "") or "") != want_image:
    print("IMAGE_MISMATCH")
    sys.exit(0)
if (target.get("entryPoint", None) or []) != ["/opt/venv/bin/python", "/app/scripts/populate_prereqs.py"]:
    print("ENTRYPOINT_MISMATCH")
    sys.exit(0)
if (target.get("command", None) or []) != [want_command]:
    print("COMMAND_MISMATCH")
    sys.exit(0)
if target.get("secrets", None):
    print("SECRET_INJECTION_REFUSED")
    sys.exit(0)
env = {}
for item in target.get("environment", []) or []:
    if isinstance(item, dict) and item.get("name"):
        env[item.get("name")] = item.get("value", "")
want_env = {
    "LAUNCHCREW_EXPECTED_ACCOUNT": want_account,
    "LAUNCHCREW_EXPECTED_REGION": want_region,
    "LAUNCHCREW_EXPECTED_ROLE": want_role_name,
    "LAUNCHCREW_MASTER_SECRET_ARN": want_master,
    "LAUNCHCREW_RUNTIME_SECRET_ARN": want_runtime,
    "LAUNCHCREW_MIGRATION_SECRET_ARN": want_migration,
    "LAUNCHCREW_TLS_SECRET_ARN": want_tls,
    "LAUNCHCREW_CERT_ARN": want_cert,
    "LAUNCHCREW_DB_HOST": want_host,
    "LAUNCHCREW_DB_TLS_MODE": "verify-full",
    "DATABASE_SSL_ROOTCERT": "/app/rds-ca-bundle.pem",
}
for key in sorted(want_env):
    if env.get(key, None) != want_env[key]:
        print("ENV_MISMATCH:" + key)
        sys.exit(0)
print("OK")
PYEOF
)" || { rm -f "$SDK_JSON"; echo "$SDK_LOGICAL SDK task definition unreadable, not treated as matching." >&2; phase_failed "$PHASE"; }
  rm -f "$SDK_JSON"
  SDK_PROOF="$(printf '%s' "$SDK_PROOF" | tr -d '[:space:]')"
  case "$SDK_PROOF" in
    OK) echo "Verified owned SDK task definition image, EntryPoint, Command, env, roles, zero secret injection: $SDK_LOGICAL" ;;
    *) echo "refused: $SDK_LOGICAL SDK task definition proof is $SDK_PROOF, job not proven owned." >&2; phase_failed "$PHASE" ;;
  esac
}

# Verify one published image: explicit tag required with no latest fallback,
# digest present with no failures, owned account and region and repository
# scope, and the exact URI the owned stack task definition references.
# batch-get-image can exit 0 with failures or a missing image, so the JSON
# fields are inspected, never the exit code alone. A tag@sha256 pin is
# honored by requiring the ECR digest to equal the pinned digest; a tag
# alone proves only the point-in-time digest read back here, even though
# the five app repos now carry IMMUTABLE tag locks, so enable rechecks
# this proof immediately before boot.
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
  if ! IMAGE_DIGEST="$("$AWS_BIN" ecr batch-get-image --repository-name "$REPO_NAME" --image-ids "imageTag=$IMAGE_TAG" --region "$EXPECTED_REGION" --query "images[0].imageId.imageDigest" --output text 2>"$TMP_ERR")"; then
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
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap SdkInitTaskDefinition sdk-init bootstrap-sdk-init
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap SdkMaterialTaskDefinition sdk-material bootstrap-sdk-material
  check_taskdef_binding ApiTaskDefinition ApiExecutionRole ApiTaskRole \
    "api.DATABASE_URL=$RUNTIME_SECRET_ARN:database-url::" \
    "api.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
    "api.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::"
  check_taskdef_binding WebTaskDefinition WebExecutionRole WebTaskRole \
    "web-proxy.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
    "web-proxy.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::"
  mark_done images
  echo "Phase images complete: five verified images, no placeholder running"
fi
# Write one private mode 600 metadata-only launch journal atomically. Args:
# journal path, outcome token, task ARN or empty. The journal carries only
# launch metadata (stack, phase, label, taskdef, cluster, client token,
# config digest, release generation, source SHA, target head, StackId,
# predecessor proof, timestamp, outcome, adopted task ARN); no secret value,
# URL, or key bytes ever appear here. The config digest is a hash of the exact
# account, region, stack, cluster, phase, label, and taskdef identity.
write_launch_journal() {
  JOURNAL_PATH="$1"
  JOURNAL_OUTCOME="$2"
  JOURNAL_TASK="$3"
  (umask 077; python3 - "$JOURNAL_PATH" "$STACK_NAME" "$TASK_PHASE" "$TASK_LABEL" "$TASKDEF_LOGICAL" "$TASKDEF_ARN" "$CLUSTER_NAME" "$CLIENT_TOKEN" "$EXPECTED_REGION" "$EXPECTED_ACCOUNT" "$JOURNAL_OUTCOME" "$JOURNAL_TASK" "${CONFIG_DIGEST:-}" "${RELEASE_GEN:-}" "${SOURCE_SHA:-}" "${TARGET_DB_HEAD:-006}" "${STACK_ID:-}" "${PREDECESSOR_TASK:-}" "${PREDECESSOR_OUTCOME:-none}" <<'PYEOF'
import json, os, sys, tempfile
(path, stack, phase, label, taskdef_logical, taskdef_arn, cluster,
 token, region, account, outcome, task_arn, config_digest,
 release_gen, source_sha, target_head, stack_id,
 predecessor_task, predecessor_outcome) = sys.argv[1:20]
if os.path.islink(path):
    raise SystemExit("refused: journal path is a symlink")
try:
    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
except Exception:
    stamp = ""
doc = {
    "version": 2,
    "stack": stack,
    "phase": phase,
    "label": label,
    "taskdef_logical": taskdef_logical,
    "taskdef_arn": taskdef_arn,
    "cluster": cluster,
    "client_token": token,
    "config_digest": config_digest,
    "region": region,
    "account": account,
    "outcome": outcome,
    "task_arn": task_arn,
    "release_generation": release_gen,
    "source_sha": source_sha,
    "target_head": target_head,
    "stack_id": stack_id,
    "predecessor_task_arn": predecessor_task,
    "predecessor_outcome": predecessor_outcome,
    "updated_utc": stamp,
}
directory = os.path.dirname(os.path.abspath(path)) or "."
fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".launch-journal-")
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(doc, out, indent=2, sort_keys=True)
        out.write("\n")
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)
except Exception:
    try:
        os.unlink(tmp_path)
    except Exception:
        pass
    raise
PYEOF
) || { echo "$TASK_LABEL launch journal write failed, no launch attempted." >&2; phase_failed "$TASK_PHASE"; }
  chmod 600 "$JOURNAL_PATH" 2>/dev/null || { echo "$TASK_LABEL launch journal mode failed, no launch attempted." >&2; phase_failed "$TASK_PHASE"; }
}

# Read-only recovery for an ambiguously failed run-task call, before any
# rerun. ListTasks defaults to RUNNING, so empty never proves nothing
# started: STOPPED or eventual consistency can hide an accepted task. There
# is no confirmed none state and no absence based new token recommendation.
# startedBy is a filter only and is never combined with desired status.
# Pagination is raw API with --no-paginate plus --cli-input-json carrying
# exact lowerCamel members cluster, startedBy or desiredStatus, maxResults,
# nextToken; each call is one API call so the outer page bound is honest.
# Recovery reconciles a known recorded ARN via Describe first when present.
# For an unrecorded launch it runs bounded read only queries scoped to the
# exact owned cluster only: one RUNNING query by token via startedBy alone,
# plus one STOPPED cluster query via desired status alone with per candidate
# Describe and token filtering. Empty after bounded reads remains AMBIGUOUS
# with a durable journal and no resend. Adoption matches taskdef, cluster,
# token, and required container identities; DescribeTasks carries no
# essential flag and none is faked. No new run task and no replay here.
# Sets RECOVERED_ARN on adoption.
recover_ambiguous_launch() {
  EXPECTED_CLUSTER_ARN="arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME"
  KNOWN_ARN=""
  if [ -f "$JOURNAL_FILE" ] && [ ! -L "$JOURNAL_FILE" ]; then
    KNOWN_ARN="$(python3 - "$JOURNAL_FILE" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
arn = doc.get("task_arn", "") if isinstance(doc, dict) else ""
if isinstance(arn, str) and arn and arn != "None":
    print(arn)
PYEOF
)" || KNOWN_ARN=""
    KNOWN_ARN="$(printf '%s' "$KNOWN_ARN" | tr -d '[:space:]')"
  fi
  if [ -n "$KNOWN_ARN" ] && [ "$KNOWN_ARN" != "None" ]; then
    RECOVER_DESC="$(mktemp /tmp/launchcrew-recover-desc-XXXXXX)"
    if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$KNOWN_ARN" --region "$EXPECTED_REGION" --output json >"$RECOVER_DESC" 2>"$TMP_ERR"; then
      rm -f "$RECOVER_DESC"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_describe_failed" "$KNOWN_ARN"
      echo "refused: $TASK_LABEL launch ambiguous and known task describe failed; task state unknown. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    RECOVER_PROOF="$(python3 - "$RECOVER_DESC" "$KNOWN_ARN" "$TASKDEF_ARN" "$EXPECTED_CLUSTER_ARN" "$CLIENT_TOKEN" 2>/dev/null <<'PYEOF'
import json, sys
desc_file, want_arn, want_taskdef, want_cluster, want_token = sys.argv[1:6]
try:
    doc = json.load(open(desc_file))
except Exception:
    sys.exit(1)
tasks = doc.get("tasks", [])
failures = doc.get("failures", [])
if failures or len(tasks) != 1:
    print("UNCONFIRMED")
    sys.exit(0)
task = tasks[0]
if not isinstance(task, dict):
    print("UNCONFIRMED")
    sys.exit(0)
if (task.get("taskArn", "") or "") != want_arn:
    print("WRONG_TASK_ARN")
    sys.exit(0)
if (task.get("taskDefinitionArn", "") or "") != want_taskdef:
    print("WRONG_TASKDEF")
    sys.exit(0)
if (task.get("clusterArn", "") or "") != want_cluster:
    print("WRONG_CLUSTER")
    sys.exit(0)
if (task.get("startedBy", "") or "") != want_token:
    print("WRONG_TOKEN")
    sys.exit(0)
containers = task.get("containers", None)
if not isinstance(containers, list) or not containers:
    print("UNCONFIRMED")
    sys.exit(0)
for entry in containers:
    if not isinstance(entry, dict) or not (entry.get("name", "") or ""):
        print("UNCONFIRMED")
        sys.exit(0)
print("ADOPTED")
PYEOF
)" || { rm -f "$RECOVER_DESC"; write_launch_journal "$JOURNAL_FILE" "ambiguous_describe_unreadable" "$KNOWN_ARN"; echo "refused: $TASK_LABEL launch ambiguous and known task describe unreadable; task state unknown. No automatic resend. Inspect journal $JOURNAL_FILE." >&2; phase_failed "$TASK_PHASE"; }
    rm -f "$RECOVER_DESC"
    RECOVER_PROOF="$(printf '%s' "$RECOVER_PROOF" | tr -d '[:space:]')"
    if [ "$RECOVER_PROOF" != "ADOPTED" ]; then
      write_launch_journal "$JOURNAL_FILE" "ambiguous_unconfirmed" "$KNOWN_ARN"
      echo "refused: $TASK_LABEL launch ambiguous and known task proof is $RECOVER_PROOF; manual review required. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    RECOVERED_ARN="$KNOWN_ARN"
    write_launch_journal "$JOURNAL_FILE" "adopted" "$RECOVERED_ARN"
    echo "$TASK_LABEL ambiguous launch recovered exactly one owned task, adopted for terminal proof: $RECOVERED_ARN"
    return 0
  fi
  RUNNING_COLLECTED="$(mktemp /tmp/launchcrew-recover-run-XXXXXX)"
  printf '[]' >"$RUNNING_COLLECTED"
  RUNNING_PAGE="$(mktemp /tmp/launchcrew-recover-page-XXXXXX)"
  RUNNING_INPUT="$(mktemp /tmp/launchcrew-recover-rin-XXXXXX)"
  RUNNING_NEXT=""
  RUNNING_PAGES=0
  while [ "$RUNNING_PAGES" -lt 3 ]; do
    RUNNING_PAGES=$((RUNNING_PAGES + 1))
    if ! python3 - "$RUNNING_INPUT" "$CLUSTER_NAME" "$CLIENT_TOKEN" "$RUNNING_NEXT" 2>/dev/null <<'PYEOF'
import json, sys
path, cluster, token_filter, token = sys.argv[1:5]
doc = {"cluster": cluster, "startedBy": token_filter, "maxResults": 10}
if token and token != "END" and token != "None":
    doc["nextToken"] = token
with open(path, "w", encoding="utf-8") as out:
    json.dump(doc, out)
PYEOF
    then
      rm -f "$RUNNING_PAGE" "$RUNNING_COLLECTED" "$RUNNING_INPUT"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_list_failed" ""
      echo "refused: $TASK_LABEL launch ambiguous and RUNNING recovery input failed; a task may have started. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    if ! "$AWS_BIN" ecs list-tasks --cli-input-json "file://$RUNNING_INPUT" --region "$EXPECTED_REGION" --no-paginate --output json >"$RUNNING_PAGE" 2>"$TMP_ERR"; then
      rm -f "$RUNNING_PAGE" "$RUNNING_COLLECTED" "$RUNNING_INPUT"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_list_failed" ""
      echo "refused: $TASK_LABEL launch ambiguous and RUNNING recovery list failed; a task may have started. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    RUNNING_NEXT="$(python3 - "$RUNNING_PAGE" "$RUNNING_COLLECTED" 2>/dev/null <<'PYEOF'
import json, sys
page_file, collected_file = sys.argv[1:3]
try:
    page = json.load(open(page_file))
    collected = json.load(open(collected_file))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(page, dict) or not isinstance(collected, list):
    print("MALFORMED")
    sys.exit(0)
arns = page.get("taskArns", None)
if not isinstance(arns, list):
    print("MALFORMED")
    sys.exit(0)
for arn in arns:
    if not isinstance(arn, str) or not arn or arn == "None":
        continue
    collected.append(arn)
if len(collected) > 20:
    print("TOO_MANY")
    sys.exit(0)
try:
    with open(collected_file, "w", encoding="utf-8") as out:
        json.dump(collected, out)
except Exception:
    print("MALFORMED")
    sys.exit(0)
if "NextToken" in page:
    print("MALFORMED")
    sys.exit(0)
nxt = page.get("nextToken", "")
if nxt is None or nxt == "None":
    nxt = ""
if not isinstance(nxt, str):
    print("MALFORMED")
    sys.exit(0)
nxt = nxt.strip()
print("END" if not nxt else nxt)
PYEOF
)" || RUNNING_NEXT="MALFORMED"
    RUNNING_NEXT="$(printf '%s' "$RUNNING_NEXT" | tr -d '[:space:]')"
    if [ "$RUNNING_NEXT" = "MALFORMED" ]; then
      rm -f "$RUNNING_PAGE" "$RUNNING_COLLECTED" "$RUNNING_INPUT"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_list_unreadable" ""
      echo "refused: $TASK_LABEL launch ambiguous and RUNNING recovery list malformed; a task may have started. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    if [ "$RUNNING_NEXT" = "TOO_MANY" ]; then
      rm -f "$RUNNING_PAGE" "$RUNNING_COLLECTED" "$RUNNING_INPUT"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_multiple" ""
      echo "refused: $TASK_LABEL launch ambiguous with too many RUNNING candidates for this token; manual review required. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    if [ -z "$RUNNING_NEXT" ] || [ "$RUNNING_NEXT" = "END" ] || [ "$RUNNING_NEXT" = "None" ]; then
      break
    fi
  done
  if [ -n "$RUNNING_NEXT" ] && [ "$RUNNING_NEXT" != "END" ] && [ "$RUNNING_NEXT" != "None" ]; then
    rm -f "$RUNNING_PAGE" "$RUNNING_COLLECTED" "$RUNNING_INPUT"
    write_launch_journal "$JOURNAL_FILE" "ambiguous_multiple" ""
    echo "refused: $TASK_LABEL launch ambiguous with truncated RUNNING recovery pages; manual review required. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  rm -f "$RUNNING_PAGE" "$RUNNING_INPUT"
  STOPPED_COLLECTED="$(mktemp /tmp/launchcrew-recover-stop-XXXXXX)"
  printf '[]' >"$STOPPED_COLLECTED"
  STOPPED_PAGE="$(mktemp /tmp/launchcrew-recover-spage-XXXXXX)"
  STOPPED_INPUT="$(mktemp /tmp/launchcrew-recover-sin-XXXXXX)"
  STOPPED_NEXT=""
  STOPPED_PAGES=0
  while [ "$STOPPED_PAGES" -lt 3 ]; do
    STOPPED_PAGES=$((STOPPED_PAGES + 1))
    if ! python3 - "$STOPPED_INPUT" "$CLUSTER_NAME" "$STOPPED_NEXT" 2>/dev/null <<'PYEOF'
import json, sys
path, cluster, token = sys.argv[1:4]
doc = {"cluster": cluster, "desiredStatus": "STOPPED", "maxResults": 10}
if token and token != "END" and token != "None":
    doc["nextToken"] = token
with open(path, "w", encoding="utf-8") as out:
    json.dump(doc, out)
PYEOF
    then
      rm -f "$STOPPED_PAGE" "$STOPPED_COLLECTED" "$RUNNING_COLLECTED" "$STOPPED_INPUT"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_list_failed" ""
      echo "refused: $TASK_LABEL launch ambiguous and STOPPED recovery input failed; a task may have started. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    if ! "$AWS_BIN" ecs list-tasks --cli-input-json "file://$STOPPED_INPUT" --region "$EXPECTED_REGION" --no-paginate --output json >"$STOPPED_PAGE" 2>"$TMP_ERR"; then
      rm -f "$STOPPED_PAGE" "$STOPPED_COLLECTED" "$RUNNING_COLLECTED" "$STOPPED_INPUT"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_list_failed" ""
      echo "refused: $TASK_LABEL launch ambiguous and STOPPED recovery list failed; a task may have started. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    STOPPED_NEXT="$(python3 - "$STOPPED_PAGE" "$STOPPED_COLLECTED" 2>/dev/null <<'PYEOF'
import json, sys
page_file, collected_file = sys.argv[1:3]
try:
    page = json.load(open(page_file))
    collected = json.load(open(collected_file))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(page, dict) or not isinstance(collected, list):
    print("MALFORMED")
    sys.exit(0)
arns = page.get("taskArns", None)
if not isinstance(arns, list):
    print("MALFORMED")
    sys.exit(0)
for arn in arns:
    if not isinstance(arn, str) or not arn or arn == "None":
        continue
    collected.append(arn)
if len(collected) > 20:
    print("TOO_MANY")
    sys.exit(0)
try:
    with open(collected_file, "w", encoding="utf-8") as out:
        json.dump(collected, out)
except Exception:
    print("MALFORMED")
    sys.exit(0)
if "NextToken" in page:
    print("MALFORMED")
    sys.exit(0)
nxt = page.get("nextToken", "")
if nxt is None or nxt == "None":
    nxt = ""
if not isinstance(nxt, str):
    print("MALFORMED")
    sys.exit(0)
nxt = nxt.strip()
print("END" if not nxt else nxt)
PYEOF
)" || STOPPED_NEXT="MALFORMED"
    STOPPED_NEXT="$(printf '%s' "$STOPPED_NEXT" | tr -d '[:space:]')"
    if [ "$STOPPED_NEXT" = "MALFORMED" ]; then
      rm -f "$STOPPED_PAGE" "$STOPPED_COLLECTED" "$RUNNING_COLLECTED" "$STOPPED_INPUT"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_list_unreadable" ""
      echo "refused: $TASK_LABEL launch ambiguous and STOPPED recovery list malformed; a task may have started. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    if [ "$STOPPED_NEXT" = "TOO_MANY" ]; then
      rm -f "$STOPPED_PAGE" "$STOPPED_COLLECTED" "$RUNNING_COLLECTED" "$STOPPED_INPUT"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_multiple" ""
      echo "refused: $TASK_LABEL launch ambiguous with too many STOPPED candidates in the owned cluster; manual review required. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    if [ -z "$STOPPED_NEXT" ] || [ "$STOPPED_NEXT" = "END" ] || [ "$STOPPED_NEXT" = "None" ]; then
      break
    fi
  done
  if [ -n "$STOPPED_NEXT" ] && [ "$STOPPED_NEXT" != "END" ] && [ "$STOPPED_NEXT" != "None" ]; then
    rm -f "$STOPPED_PAGE" "$STOPPED_COLLECTED" "$RUNNING_COLLECTED" "$STOPPED_INPUT"
    write_launch_journal "$JOURNAL_FILE" "ambiguous_multiple" ""
    echo "refused: $TASK_LABEL launch ambiguous with truncated STOPPED recovery pages; manual review required. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  rm -f "$STOPPED_PAGE" "$STOPPED_INPUT"
  RUNNING_LIST="$(mktemp /tmp/launchcrew-recover-runlist-XXXXXX)"
  STOPPED_LIST="$(mktemp /tmp/launchcrew-recover-stoplist-XXXXXX)"
  if ! python3 - "$RUNNING_COLLECTED" "$STOPPED_COLLECTED" "$RUNNING_LIST" "$STOPPED_LIST" 2>/dev/null <<'PYEOF'
import json, sys
run_file, stop_file, run_out, stop_out = sys.argv[1:5]
run = json.load(open(run_file))
stop = json.load(open(stop_file))
with open(run_out, "w", encoding="utf-8") as out:
    for arn in run:
        out.write(arn + "\n")
seen = set(run)
with open(stop_out, "w", encoding="utf-8") as out:
    for arn in stop:
        if arn not in seen:
            out.write(arn + "\n")
            seen.add(arn)
PYEOF
  then
    rm -f "$RUNNING_COLLECTED" "$STOPPED_COLLECTED" "$RUNNING_LIST" "$STOPPED_LIST"
    write_launch_journal "$JOURNAL_FILE" "ambiguous_list_unreadable" ""
    echo "refused: $TASK_LABEL launch ambiguous and recovery candidates unreadable; a task may have started. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  rm -f "$RUNNING_COLLECTED" "$STOPPED_COLLECTED"
  MATCHED_ARNS="$(mktemp /tmp/launchcrew-recover-match-XXXXXX)"
  : >"$MATCHED_ARNS"
  RUNNING_COUNT="$(grep -c . "$RUNNING_LIST" 2>/dev/null || echo 0)"
  RUNNING_COUNT="$(printf '%s' "$RUNNING_COUNT" | tr -d '[:space:]')"
  if [ -z "$RUNNING_COUNT" ]; then RUNNING_COUNT=0; fi
  if [ "$RUNNING_COUNT" -gt 1 ]; then
    rm -f "$RUNNING_LIST" "$STOPPED_LIST" "$MATCHED_ARNS"
    write_launch_journal "$JOURNAL_FILE" "ambiguous_multiple" ""
    echo "refused: $TASK_LABEL launch ambiguous with $RUNNING_COUNT RUNNING tasks for this token; manual review required. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  if [ "$RUNNING_COUNT" -eq 1 ]; then
    CANDIDATE_ARN="$(head -n 1 "$RUNNING_LIST" | tr -d '[:space:]')"
    RECOVER_DESC="$(mktemp /tmp/launchcrew-recover-desc-XXXXXX)"
    if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$CANDIDATE_ARN" --region "$EXPECTED_REGION" --output json >"$RECOVER_DESC" 2>"$TMP_ERR"; then
      rm -f "$RECOVER_DESC" "$RUNNING_LIST" "$STOPPED_LIST" "$MATCHED_ARNS"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_describe_failed" "$CANDIDATE_ARN"
      echo "refused: $TASK_LABEL launch ambiguous and RUNNING recovery describe failed; task state unknown. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    CANDIDATE_PROOF="$(python3 - "$RECOVER_DESC" "$CANDIDATE_ARN" "$TASKDEF_ARN" "$EXPECTED_CLUSTER_ARN" "$CLIENT_TOKEN" 2>/dev/null <<'PYEOF'
import json, sys
desc_file, want_arn, want_taskdef, want_cluster, want_token = sys.argv[1:6]
try:
    doc = json.load(open(desc_file))
except Exception:
    sys.exit(1)
tasks = doc.get("tasks", [])
failures = doc.get("failures", [])
if failures or len(tasks) != 1:
    print("UNCONFIRMED")
    sys.exit(0)
task = tasks[0]
if not isinstance(task, dict):
    print("UNCONFIRMED")
    sys.exit(0)
if (task.get("taskArn", "") or "") != want_arn:
    print("WRONG_TASK_ARN")
    sys.exit(0)
if (task.get("taskDefinitionArn", "") or "") != want_taskdef:
    print("WRONG_TASKDEF")
    sys.exit(0)
if (task.get("clusterArn", "") or "") != want_cluster:
    print("WRONG_CLUSTER")
    sys.exit(0)
if (task.get("startedBy", "") or "") != want_token:
    print("WRONG_TOKEN")
    sys.exit(0)
containers = task.get("containers", None)
if not isinstance(containers, list) or not containers:
    print("UNCONFIRMED")
    sys.exit(0)
for entry in containers:
    if not isinstance(entry, dict) or not (entry.get("name", "") or ""):
        print("UNCONFIRMED")
        sys.exit(0)
print("ADOPTED")
PYEOF
)" || { rm -f "$RECOVER_DESC" "$RUNNING_LIST" "$STOPPED_LIST" "$MATCHED_ARNS"; write_launch_journal "$JOURNAL_FILE" "ambiguous_describe_unreadable" "$CANDIDATE_ARN"; echo "refused: $TASK_LABEL launch ambiguous and RUNNING recovery describe unreadable; task state unknown. No automatic resend. Inspect journal $JOURNAL_FILE." >&2; phase_failed "$TASK_PHASE"; }
    rm -f "$RECOVER_DESC"
    CANDIDATE_PROOF="$(printf '%s' "$CANDIDATE_PROOF" | tr -d '[:space:]')"
    if [ "$CANDIDATE_PROOF" != "ADOPTED" ]; then
      rm -f "$RUNNING_LIST" "$STOPPED_LIST" "$MATCHED_ARNS"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_unconfirmed" "$CANDIDATE_ARN"
      echo "refused: $TASK_LABEL launch ambiguous and RUNNING recovery proof is $CANDIDATE_PROOF; manual review required. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    printf '%s\n' "$CANDIDATE_ARN" >>"$MATCHED_ARNS"
  fi
  rm -f "$RUNNING_LIST"
  while IFS= read -r CANDIDATE_ARN; do
    [ -n "$CANDIDATE_ARN" ] || continue
    RECOVER_DESC="$(mktemp /tmp/launchcrew-recover-desc-XXXXXX)"
    if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$CANDIDATE_ARN" --region "$EXPECTED_REGION" --output json >"$RECOVER_DESC" 2>"$TMP_ERR"; then
      rm -f "$RECOVER_DESC" "$STOPPED_LIST" "$MATCHED_ARNS"
      write_launch_journal "$JOURNAL_FILE" "ambiguous_describe_failed" "$CANDIDATE_ARN"
      echo "refused: $TASK_LABEL launch ambiguous and STOPPED recovery describe failed; task state unknown. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    CANDIDATE_PROOF="$(python3 - "$RECOVER_DESC" "$CANDIDATE_ARN" "$TASKDEF_ARN" "$EXPECTED_CLUSTER_ARN" "$CLIENT_TOKEN" 2>/dev/null <<'PYEOF'
import json, sys
desc_file, want_arn, want_taskdef, want_cluster, want_token = sys.argv[1:6]
try:
    doc = json.load(open(desc_file))
except Exception:
    sys.exit(1)
tasks = doc.get("tasks", [])
failures = doc.get("failures", [])
if failures or len(tasks) != 1:
    print("UNCONFIRMED")
    sys.exit(0)
task = tasks[0]
if not isinstance(task, dict):
    print("UNCONFIRMED")
    sys.exit(0)
if (task.get("taskArn", "") or "") != want_arn:
    print("WRONG_TASK_ARN")
    sys.exit(0)
if (task.get("taskDefinitionArn", "") or "") != want_taskdef:
    print("SKIP_TASKDEF")
    sys.exit(0)
if (task.get("clusterArn", "") or "") != want_cluster:
    print("SKIP_CLUSTER")
    sys.exit(0)
if (task.get("startedBy", "") or "") != want_token:
    print("SKIP_TOKEN")
    sys.exit(0)
containers = task.get("containers", None)
if not isinstance(containers, list) or not containers:
    print("UNCONFIRMED")
    sys.exit(0)
for entry in containers:
    if not isinstance(entry, dict) or not (entry.get("name", "") or ""):
        print("UNCONFIRMED")
        sys.exit(0)
print("ADOPTED")
PYEOF
)" || { rm -f "$RECOVER_DESC" "$STOPPED_LIST" "$MATCHED_ARNS"; write_launch_journal "$JOURNAL_FILE" "ambiguous_describe_unreadable" "$CANDIDATE_ARN"; echo "refused: $TASK_LABEL launch ambiguous and STOPPED recovery describe unreadable; task state unknown. No automatic resend. Inspect journal $JOURNAL_FILE." >&2; phase_failed "$TASK_PHASE"; }
    rm -f "$RECOVER_DESC"
    CANDIDATE_PROOF="$(printf '%s' "$CANDIDATE_PROOF" | tr -d '[:space:]')"
    case "$CANDIDATE_PROOF" in
      ADOPTED) printf '%s\n' "$CANDIDATE_ARN" >>"$MATCHED_ARNS" ;;
      SKIP_TASKDEF|SKIP_CLUSTER|SKIP_TOKEN) ;;
      WRONG_TASK_ARN|UNCONFIRMED)
        rm -f "$STOPPED_LIST" "$MATCHED_ARNS"
        write_launch_journal "$JOURNAL_FILE" "ambiguous_unconfirmed" "$CANDIDATE_ARN"
        echo "refused: $TASK_LABEL launch ambiguous and STOPPED recovery proof is $CANDIDATE_PROOF; manual review required. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
        phase_failed "$TASK_PHASE" ;;
      *) rm -f "$STOPPED_LIST" "$MATCHED_ARNS"
        write_launch_journal "$JOURNAL_FILE" "ambiguous_unconfirmed" "$CANDIDATE_ARN"
        echo "refused: $TASK_LABEL launch ambiguous and STOPPED recovery proof is $CANDIDATE_PROOF; manual review required. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
        phase_failed "$TASK_PHASE" ;;
    esac
  done <"$STOPPED_LIST"
  rm -f "$STOPPED_LIST"
  MATCHED_COUNT="$(grep -c . "$MATCHED_ARNS" 2>/dev/null || echo 0)"
  MATCHED_COUNT="$(printf '%s' "$MATCHED_COUNT" | tr -d '[:space:]')"
  if [ -z "$MATCHED_COUNT" ]; then MATCHED_COUNT=0; fi
  if [ "$MATCHED_COUNT" -eq 0 ]; then
    rm -f "$MATCHED_ARNS"
    write_launch_journal "$JOURNAL_FILE" "ambiguous_empty" ""
    echo "refused: $TASK_LABEL launch ambiguous and bounded RUNNING plus STOPPED recovery found zero matching tasks; empty remains AMBIGUOUS and never proves nothing started because STOPPED or eventual consistency can hide an accepted task. No automatic resend and no new token from absence. Inspect journal $JOURNAL_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  if [ "$MATCHED_COUNT" != "1" ]; then
    rm -f "$MATCHED_ARNS"
    write_launch_journal "$JOURNAL_FILE" "ambiguous_multiple" ""
    echo "refused: $TASK_LABEL launch ambiguous with $MATCHED_COUNT matching tasks for this token; manual review required. No automatic resend. Inspect journal $JOURNAL_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  RECOVERED_ARN="$(head -n 1 "$MATCHED_ARNS" | tr -d '[:space:]')"
  rm -f "$MATCHED_ARNS"
  [ -n "$RECOVERED_ARN" ] || { write_launch_journal "$JOURNAL_FILE" "ambiguous_unconfirmed" ""; echo "refused: $TASK_LABEL launch ambiguous and recovery match unreadable. No automatic resend. Inspect journal $JOURNAL_FILE." >&2; phase_failed "$TASK_PHASE"; }
  write_launch_journal "$JOURNAL_FILE" "adopted" "$RECOVERED_ARN"
  echo "$TASK_LABEL ambiguous launch recovered exactly one owned task, adopted for terminal proof: $RECOVERED_ARN"
}

# Prove terminal state for an already launched task ARN. Waits for STOPPED
# as a hint only, then requires STOPPED lastStatus, exact task and taskdef
# ARNs, exact owned cluster ARN, exact startedBy token, and STOPPED exit 0
# from every expected essential container from the owned taskdef document.
# Writes complete on success. Never fabricates success. Expects TASK_ARN
# plus the usual task globals set. Fails closed via phase_failed on mismatch.
prove_terminal_task() {
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
  TASK_PROOF="$(python3 - "$DESCRIBE_JSON" "$TASKDEF_JSON" "$TASK_ARN" "$TASKDEF_ARN" "$EXPECTED_CLUSTER_ARN" "$CLIENT_TOKEN" 2>/dev/null <<'PYEOF'
import json, sys
try:
    describe = json.load(open(sys.argv[1]))
    defined = json.load(open(sys.argv[2]))
except Exception:
    sys.exit(1)
expected_arn, expected_taskdef, expected_cluster, expected_token = sys.argv[3:7]
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
if (task.get("startedBy", "") or "") != expected_token:
    print("WRONG_TOKEN")
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
    OK)
      write_launch_journal "$JOURNAL_FILE" "complete" "$TASK_ARN"
      echo "$TASK_LABEL terminal proof: STOPPED, exact owned task and cluster ARNs, every expected container exit 0" ;;
    *) echo "refused: $TASK_LABEL terminal proof is $TASK_PROOF, later phases not started." >&2; phase_failed "$TASK_PHASE" ;;
  esac
}

# True for mutating one-shot labels that must never resend after success.
# Read-only labels return false and may fresh recheck after terminal prior.
is_mutating_label() {
  case "$TASK_LABEL" in
    sdk-init|bootstrap|migration) return 0 ;;
    sdk-material|verify) return 1 ;;
    *) return 0 ;;
  esac
}

# Run one isolated one-off task and prove its terminal state. Jobs run in the
# public subnets with a public IP under a group with no inbound rules: the
# database stays private, and the job can actually reach ECR, Secrets Manager,
# and Logs. Operation lifecycle: pending then started then complete is the
# only terminal success; pending, started, adopted, and every ambiguous
# outcome are non-terminal and block any new launch. A stable active
# operation record in a dedicated persistent private mode 700 dir with mode
# 600 file carries the exact account, region, stack, cluster, phase, label,
# taskdef, and config digest. The default dir is under the ignored .local
# tree derived from the script root, never shared /tmp, and repeated
# invocation reuses the same record for crash resume. Whole lookup, claim,
# recovery, and launch serialize under an atomic exclusive operation lock
# scoped to the exact active record path; account, region, taskdef, and
# config are validated inside the lock. Two controllers sharing a directory
# never run twice for the same unresolved operation. Trap releases only the
# owned lock; stale lock fails closed with read-only reconciliation and no
# fresh launch. Genuine crash resume reads and validates that record before
# any new token: it adopts and reconciles the prior task, and unresolved
# blocks new launch. A successful mutating init, bind, or migrate never
# resends from the same operation after restart. Same operation with changed
# taskdef or config fails explicit, never auto fresh. Read-only material and
# verify may fresh recheck only after prior terminal complete, never by
# duplicating an unresolved attempt. No fabricated terminal and no review
# bypass. The run-task call carries a bounded client token as both
# client-token and startedBy with no automatic resend. Ambiguous responses
# use read-only recovery with empty remaining AMBIGUOUS. Terminal proof is
# STOPPED with every expected essential container exit 0. No secret value in
# argv, files, logs, or journal.
run_one_off_task() {
  TASKDEF_LOGICAL="$1"
  TASK_LABEL="$2"
  TASK_PHASE="$3"
  TASKDEF_ARN="$(stack_resource "$TASKDEF_LOGICAL" 2>"$TMP_ERR")" || { echo "$TASK_LABEL task definition lookup failed before any launch, no run attempted." >&2; phase_failed "$TASK_PHASE"; }
  TASKDEF_ARN="$(printf '%s' "$TASKDEF_ARN" | tr -d '[:space:]')"
  [ -n "$TASKDEF_ARN" ] && [ "$TASKDEF_ARN" != "None" ] || { echo "$TASK_LABEL task definition missing before any launch, no run attempted." >&2; phase_failed "$TASK_PHASE"; }
  SUBNET_A="$(stack_resource PublicSubnetA 2>"$TMP_ERR")" || { echo "subnet lookup failed before any launch, no run attempted." >&2; phase_failed "$TASK_PHASE"; }
  SUBNET_B="$(stack_resource PublicSubnetB 2>"$TMP_ERR")" || { echo "subnet lookup failed before any launch, no run attempted." >&2; phase_failed "$TASK_PHASE"; }
  JOB_SG="$(stack_resource JobSecurityGroup 2>"$TMP_ERR")" || { echo "security group lookup failed before any launch, no run attempted." >&2; phase_failed "$TASK_PHASE"; }
  SUBNET_A="$(printf '%s' "$SUBNET_A" | tr -d '[:space:]')"
  SUBNET_B="$(printf '%s' "$SUBNET_B" | tr -d '[:space:]')"
  JOB_SG="$(printf '%s' "$JOB_SG" | tr -d '[:space:]')"
  if [ -z "$LAUNCH_JOURNAL_DIR" ]; then
    case "$0" in
      */*) BOOTSTRAP_SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd 2>/dev/null || echo "")" ;;
      *) BOOTSTRAP_SCRIPT_DIR="" ;;
    esac
    if [ -n "$BOOTSTRAP_SCRIPT_DIR" ] && [ -d "$BOOTSTRAP_SCRIPT_DIR" ]; then
      LAUNCH_JOURNAL_DIR="$BOOTSTRAP_SCRIPT_DIR/../../.local/launch-journals"
    else
      echo "$TASK_LABEL journal directory missing and script root unreadable, no launch attempted. Pass --launch-journal-dir with a private directory." >&2; phase_failed "$TASK_PHASE"
    fi
  fi
  if [ -L "$LAUNCH_JOURNAL_DIR" ]; then echo "$TASK_LABEL journal directory is a symlink, no launch attempted." >&2; phase_failed "$TASK_PHASE"; fi
  case "$LAUNCH_JOURNAL_DIR" in
    /|/tmp|/tmp/|/var/tmp|/var/tmp/|/var|/var/|/etc|/etc/|/usr|/usr/) echo "$TASK_LABEL journal directory is a shared root, no launch attempted. Use a dedicated private directory." >&2; phase_failed "$TASK_PHASE" ;;
  esac
  JOURNAL_CREATED=0
  if [ ! -d "$LAUNCH_JOURNAL_DIR" ]; then
    if ! (umask 077; mkdir -p "$LAUNCH_JOURNAL_DIR" 2>/dev/null); then echo "$TASK_LABEL journal directory unwritable, no launch attempted." >&2; phase_failed "$TASK_PHASE"; fi
    JOURNAL_CREATED=1
  fi
  if [ "$JOURNAL_CREATED" -eq 1 ]; then
    chmod 700 "$LAUNCH_JOURNAL_DIR" 2>/dev/null || { echo "$TASK_LABEL journal directory mode failed, no launch attempted." >&2; phase_failed "$TASK_PHASE"; }
  fi
  if ! python3 - "$LAUNCH_JOURNAL_DIR" 2>/dev/null <<'PYEOF'
import os, sys
path = sys.argv[1]
if os.path.islink(path):
    sys.exit(1)
try:
    info = os.stat(path)
    mode = info.st_mode & 0o777
    if info.st_uid != os.getuid():
        sys.exit(1)
except Exception:
    sys.exit(1)
sys.exit(0 if mode == 0o700 else 1)
PYEOF
  then echo "$TASK_LABEL journal directory is not private mode 700 owned, no launch attempted." >&2; phase_failed "$TASK_PHASE"; fi
  if ! CONFIG_DIGEST="$(python3 - "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$TASK_PHASE" "$TASK_LABEL" "$TASKDEF_LOGICAL" "$TASKDEF_ARN" 2>/dev/null <<'PYEOF'
import hashlib, sys
raw = "|".join(sys.argv[1:9])
print(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32])
PYEOF
)"; then echo "$TASK_LABEL config digest failed, no launch attempted." >&2; phase_failed "$TASK_PHASE"; fi
  CONFIG_DIGEST="$(printf '%s' "$CONFIG_DIGEST" | tr -d '[:space:]')"
  [ -n "$CONFIG_DIGEST" ] || { echo "$TASK_LABEL config digest empty, no launch attempted." >&2; phase_failed "$TASK_PHASE"; }
  ACTIVE_FILE="$LAUNCH_JOURNAL_DIR/launchcrew-$STACK_NAME-$TASK_PHASE-$TASK_LABEL-$RELEASE_GEN-active.json"
  LEGACY_ACTIVE_FILE="$LAUNCH_JOURNAL_DIR/launchcrew-$STACK_NAME-$TASK_PHASE-$TASK_LABEL-active.json"
  if [ -L "$ACTIVE_FILE" ]; then echo "$TASK_LABEL active operation record is a symlink, no launch attempted." >&2; phase_failed "$TASK_PHASE"; fi
  if [ -L "$LEGACY_ACTIVE_FILE" ]; then echo "$TASK_LABEL legacy operation record is a symlink, no launch attempted." >&2; phase_failed "$TASK_PHASE"; fi
  PREDECESSOR_TASK=""
  PREDECESSOR_OUTCOME="none"
  acquire_operation_lock
  if [ -f "$LEGACY_ACTIVE_FILE" ]; then
    LEGACY_PARSED="$(python3 - "$LEGACY_ACTIVE_FILE" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$TASK_PHASE" "$TASK_LABEL" 2>/dev/null <<'PYEOF'
import json, os, sys
path, want_account, want_region, want_stack, want_cluster, want_phase, want_label = sys.argv[1:8]
try:
    if os.path.islink(path):
        print("PROOF\tSYMLINK")
        sys.exit(0)
    finfo = os.stat(path)
    if (finfo.st_mode & 0o777) != 0o600:
        print("PROOF\tMODE")
        sys.exit(0)
    if finfo.st_size <= 0 or finfo.st_size > 10240:
        print("PROOF\tSIZE")
        sys.exit(0)
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
except Exception:
    print("PROOF\tUNREADABLE")
    sys.exit(0)
if not isinstance(doc, dict):
    print("PROOF\tMALFORMED")
    sys.exit(0)
allow = {"version", "stack", "phase", "label", "taskdef_logical", "taskdef_arn",
         "cluster", "client_token", "config_digest", "region", "account",
         "outcome", "task_arn", "updated_utc", "release_generation",
         "source_sha", "target_head", "stack_id", "predecessor_task_arn",
         "predecessor_outcome"}
for key in doc:
    if key not in allow:
        print("PROOF\tFOREIGN_FIELD")
        sys.exit(0)
blob = json.dumps(doc).lower()
for bad in ("password", ":secret:", "tls-cert-b64", "tls-key-b64",
            "database-url", "BEGIN PRIVATE", "BEGIN CERTIFICATE"):
    if bad in blob:
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
if doc.get("account", "") != want_account:
    print("PROOF\tACCOUNT_MISMATCH")
    sys.exit(0)
if doc.get("region", "") != want_region:
    print("PROOF\tREGION_MISMATCH")
    sys.exit(0)
if doc.get("stack", "") != want_stack:
    print("PROOF\tSTACK_MISMATCH")
    sys.exit(0)
if doc.get("cluster", "") != want_cluster:
    print("PROOF\tCLUSTER_MISMATCH")
    sys.exit(0)
if doc.get("phase", "") != want_phase:
    print("PROOF\tPHASE_MISMATCH")
    sys.exit(0)
if doc.get("label", "") != want_label:
    print("PROOF\tLABEL_MISMATCH")
    sys.exit(0)
token = doc.get("client_token", "")
if not isinstance(token, str) or len(token) != 33 or not token.startswith("lc-"):
    print("PROOF\tTOKEN_MALFORMED")
    sys.exit(0)
outcome = doc.get("outcome", "")
task_arn = doc.get("task_arn", "") or ""
if not isinstance(outcome, str) or not outcome:
    print("PROOF\tOUTCOME_MISSING")
    sys.exit(0)
if not isinstance(task_arn, str):
    print("PROOF\tMALFORMED")
    sys.exit(0)
print("PROOF\tOK")
print("OUTCOME\t%s" % outcome)
print("TOKEN\t%s" % token)
print("TASKARN\t%s" % task_arn)
print("TASKDEF\t%s" % (doc.get("taskdef_arn", "") or ""))
PYEOF
)" || LEGACY_PARSED="PROOF\tUNREADABLE"
    LEGACY_PROOF="$(printf '%s\n' "$LEGACY_PARSED" | awk -F'\t' '$1=="PROOF"{print $2}')"
    LEGACY_PROOF="$(printf '%s' "$LEGACY_PROOF" | tr -d '[:space:]')"
    if [ "$LEGACY_PROOF" != "OK" ]; then
      echo "refused: $TASK_LABEL legacy operation record is $LEGACY_PROOF, preserved with no new launch and no overwrite. Inspect $LEGACY_ACTIVE_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    LEGACY_OUTCOME="$(printf '%s\n' "$LEGACY_PARSED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
    LEGACY_TOKEN="$(printf '%s\n' "$LEGACY_PARSED" | awk -F'\t' '$1=="TOKEN"{print $2}' | tr -d '[:space:]')"
    LEGACY_TASK="$(printf '%s\n' "$LEGACY_PARSED" | awk -F'\t' '$1=="TASKARN"{print $2}' | tr -d '[:space:]')"
    LEGACY_TASKDEF="$(printf '%s\n' "$LEGACY_PARSED" | awk -F'\t' '$1=="TASKDEF"{print $2}' | tr -d '[:space:]')"
    if [ "$LEGACY_OUTCOME" != "complete" ]; then
      echo "refused: $TASK_LABEL legacy generation is $LEGACY_OUTCOME, not complete. Reconcile the prior generation to STOPPED with all essential exits 0 before any new $RELEASE_GEN launch. Legacy preserved at $LEGACY_ACTIVE_FILE, no new launch." >&2
      phase_failed "$TASK_PHASE"
    fi
    [ -n "$LEGACY_TASK" ] && [ "$LEGACY_TASK" != "None" ] || { echo "refused: $TASK_LABEL legacy complete has no task ARN, cannot re-prove predecessor. Inspect $LEGACY_ACTIVE_FILE." >&2; phase_failed "$TASK_PHASE"; }
    [ -n "$LEGACY_TASKDEF" ] && [ "$LEGACY_TASKDEF" != "None" ] || { echo "refused: $TASK_LABEL legacy complete has no taskdef ARN, cannot re-prove predecessor. Inspect $LEGACY_ACTIVE_FILE." >&2; phase_failed "$TASK_PHASE"; }
    LEGACY_DESC="$(mktemp /tmp/launchcrew-legacy-XXXXXX)"
    if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$LEGACY_TASK" --region "$EXPECTED_REGION" --output json >"$LEGACY_DESC" 2>"$TMP_ERR"; then
      rm -f "$LEGACY_DESC"
      echo "refused: $TASK_LABEL legacy predecessor terminal state unreadable, no new launch. Inspect $LEGACY_ACTIVE_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    LEGACY_TASKDEF_JSON="$(mktemp /tmp/launchcrew-legacy-def-XXXXXX)"
    if ! "$AWS_BIN" ecs "describe-task""-definition" --task"-definition" "$LEGACY_TASKDEF" --region "$EXPECTED_REGION" --output json >"$LEGACY_TASKDEF_JSON" 2>"$TMP_ERR"; then
      rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
      echo "refused: $TASK_LABEL legacy predecessor taskdef unreadable, no new launch. Inspect $LEGACY_ACTIVE_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    LEGACY_CHECK="$(python3 - "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON" "$LEGACY_TASK" "$LEGACY_TASKDEF" "arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME" "$LEGACY_TOKEN" 2>/dev/null <<'PYEOF'
import json, sys
try:
    describe = json.load(open(sys.argv[1]))
    defined = json.load(open(sys.argv[2]))
except Exception:
    sys.exit(1)
expected_arn, expected_taskdef, expected_cluster, expected_token = sys.argv[3:7]
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
if (task.get("startedBy", "") or "") != expected_token:
    print("WRONG_TOKEN")
    sys.exit(0)
actual = task.get("containers", []) or []
names = [(c.get("name", "?") or "?") for c in actual]
if len(set(names)) != len(names):
    print("DUPLICATE")
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
)" || LEGACY_CHECK="UNREADABLE"
    rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
    LEGACY_CHECK="$(printf '%s' "$LEGACY_CHECK" | tr -d '[:space:]')"
    if [ "$LEGACY_CHECK" != "OK" ]; then
      echo "refused: $TASK_LABEL legacy predecessor terminal proof is $LEGACY_CHECK, no new $RELEASE_GEN launch. Inspect $LEGACY_ACTIVE_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    PREDECESSOR_TASK="$LEGACY_TASK"
    PREDECESSOR_OUTCOME="complete"
    echo "$TASK_LABEL legacy predecessor reconciled STOPPED exit 0, preserved at $LEGACY_ACTIVE_FILE; new generation $RELEASE_GEN proceeds."
  fi
  if [ -f "$ACTIVE_FILE" ]; then
    PRIOR_PARSED="$(python3 - "$ACTIVE_FILE" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$TASK_PHASE" "$TASK_LABEL" "$TASKDEF_LOGICAL" "$TASKDEF_ARN" "$CONFIG_DIGEST" "$RELEASE_GEN" "$TARGET_DB_HEAD" "${STACK_ID:-}" 2>/dev/null <<'PYEOF'
import json, os, sys
(path, want_account, want_region, want_stack, want_cluster,
 want_phase, want_label, want_logical, want_taskdef, want_digest,
 want_gen, want_head, want_stack_id) = sys.argv[1:14]
try:
    if os.path.islink(path):
        print("PROOF\tSYMLINK")
        sys.exit(0)
    finfo = os.stat(path)
    if (finfo.st_mode & 0o777) != 0o600:
        print("PROOF\tMODE")
        sys.exit(0)
    if finfo.st_size <= 0 or finfo.st_size > 10240:
        print("PROOF\tSIZE")
        sys.exit(0)
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
except Exception:
    print("PROOF\tUNREADABLE")
    sys.exit(0)
if not isinstance(doc, dict):
    print("PROOF\tMALFORMED")
    sys.exit(0)
allow = {"version", "stack", "phase", "label", "taskdef_logical", "taskdef_arn",
         "cluster", "client_token", "config_digest", "region", "account",
         "outcome", "task_arn", "updated_utc", "release_generation",
         "source_sha", "target_head", "stack_id", "predecessor_task_arn",
         "predecessor_outcome"}
for key in doc:
    if key not in allow:
        print("PROOF\tFOREIGN_FIELD")
        sys.exit(0)
blob = json.dumps(doc).lower()
for bad in ("password", ":secret:", "tls-cert-b64", "tls-key-b64",
            "database-url", "BEGIN PRIVATE", "BEGIN CERTIFICATE"):
    if bad in blob:
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
if doc.get("account", "") != want_account:
    print("PROOF\tACCOUNT_MISMATCH")
    sys.exit(0)
if doc.get("region", "") != want_region:
    print("PROOF\tREGION_MISMATCH")
    sys.exit(0)
if doc.get("stack", "") != want_stack:
    print("PROOF\tSTACK_MISMATCH")
    sys.exit(0)
if doc.get("cluster", "") != want_cluster:
    print("PROOF\tCLUSTER_MISMATCH")
    sys.exit(0)
if doc.get("phase", "") != want_phase:
    print("PROOF\tPHASE_MISMATCH")
    sys.exit(0)
if doc.get("label", "") != want_label:
    print("PROOF\tLABEL_MISMATCH")
    sys.exit(0)
if doc.get("taskdef_logical", "") != want_logical:
    print("PROOF\tTASKDEF_LOGICAL_MISMATCH")
    sys.exit(0)
if doc.get("taskdef_arn", "") != want_taskdef:
    print("PROOF\tTASKDEF_MISMATCH")
    sys.exit(0)
if doc.get("config_digest", "") != want_digest:
    print("PROOF\tCONFIG_MISMATCH")
    sys.exit(0)
if doc.get("release_generation", "") != want_gen:
    print("PROOF\tGENERATION_MISMATCH")
    sys.exit(0)
if doc.get("target_head", "") != want_head:
    print("PROOF\tHEAD_MISMATCH")
    sys.exit(0)
if want_stack_id and doc.get("stack_id", "") != want_stack_id:
    print("PROOF\tSTACKID_MISMATCH")
    sys.exit(0)
token = doc.get("client_token", "")
if not isinstance(token, str) or len(token) != 33 or not token.startswith("lc-"):
    print("PROOF\tTOKEN_MALFORMED")
    sys.exit(0)
outcome = doc.get("outcome", "")
task_arn = doc.get("task_arn", "")
if not isinstance(outcome, str) or not outcome:
    print("PROOF\tOUTCOME_MISSING")
    sys.exit(0)
if task_arn is None:
    task_arn = ""
if not isinstance(task_arn, str):
    print("PROOF\tMALFORMED")
    sys.exit(0)
print("PROOF\tOK")
print("OUTCOME\t%s" % outcome)
print("TOKEN\t%s" % token)
print("TASKARN\t%s" % task_arn)
PYEOF
)" || PRIOR_PARSED="PROOF\tUNREADABLE"
    PRIOR_PROOF="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="PROOF"{print $2}')"
    PRIOR_PROOF="$(printf '%s' "$PRIOR_PROOF" | tr -d '[:space:]')"
    if [ "$PRIOR_PROOF" != "OK" ]; then
      echo "refused: $TASK_LABEL prior operation record is $PRIOR_PROOF, same operation with changed identity never auto fresh, no new launch. Inspect $ACTIVE_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    PRIOR_OUTCOME="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="OUTCOME"{print $2}')"
    PRIOR_TOKEN="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="TOKEN"{print $2}')"
    PRIOR_TASK="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="TASKARN"{print $2}')"
    PRIOR_OUTCOME="$(printf '%s' "$PRIOR_OUTCOME" | tr -d '[:space:]')"
    PRIOR_TOKEN="$(printf '%s' "$PRIOR_TOKEN" | tr -d '[:space:]')"
    PRIOR_TASK="$(printf '%s' "$PRIOR_TASK" | tr -d '[:space:]')"
    case "$PRIOR_TOKEN" in
      lc-??????????????????????????????) ;;
      *) echo "refused: $TASK_LABEL prior client token malformed, no new launch. Inspect $ACTIVE_FILE." >&2; phase_failed "$TASK_PHASE" ;;
    esac
    if [ "$PRIOR_OUTCOME" = "complete" ]; then
      if is_mutating_label; then
        [ -n "$PRIOR_TASK" ] && [ "$PRIOR_TASK" != "None" ] || { echo "refused: $TASK_LABEL prior mutating success has no task ARN, cannot re-prove, no resend. Inspect $ACTIVE_FILE." >&2; phase_failed "$TASK_PHASE"; }
        CLIENT_TOKEN="$PRIOR_TOKEN"
        JOURNAL_FILE="$ACTIVE_FILE"
        TASK_ARN="$PRIOR_TASK"
        echo "$TASK_LABEL prior mutating operation already complete, re-proving terminal state with no resend."
        prove_terminal_task
        echo "$TASK_LABEL already complete, one-shot preserved with no new run-task."
        release_operation_lock
        return 0
      else
        ARCHIVE_FILE="$LAUNCH_JOURNAL_DIR/launchcrew-$STACK_NAME-$TASK_PHASE-$TASK_LABEL-$RELEASE_GEN-complete-$PRIOR_TOKEN.json"
        if [ -L "$ARCHIVE_FILE" ] || [ -e "$ARCHIVE_FILE" ]; then echo "refused: $TASK_LABEL read-only archive path exists, no fresh recheck. Inspect $ACTIVE_FILE." >&2; phase_failed "$TASK_PHASE"; fi
        if ! python3 - "$ACTIVE_FILE" "$ARCHIVE_FILE" 2>/dev/null <<'PYEOF'
import os, sys
src, dst = sys.argv[1:3]
if os.path.islink(src) or os.path.islink(dst):
    sys.exit(1)
if os.path.exists(dst):
    sys.exit(1)
os.replace(src, dst)
os.chmod(dst, 0o600)
PYEOF
        then echo "$TASK_LABEL read-only archive failed, no fresh recheck." >&2; phase_failed "$TASK_PHASE"; fi
        echo "$TASK_LABEL prior read-only complete archived, fresh recheck proceeds with a new token."
      fi
    else
      CLIENT_TOKEN="$PRIOR_TOKEN"
      JOURNAL_FILE="$ACTIVE_FILE"
      echo "$TASK_LABEL prior operation $PRIOR_OUTCOME unresolved, reconciling prior token with no new launch."
      if [ -n "$PRIOR_TASK" ] && [ "$PRIOR_TASK" != "None" ]; then
        TASK_ARN="$PRIOR_TASK"
        prove_terminal_task
        release_operation_lock
        return 0
      fi
      RECOVERED_ARN=""
      recover_ambiguous_launch
      TASK_ARN="$RECOVERED_ARN"
      prove_terminal_task
      release_operation_lock
      return 0
    fi
  fi
  if ! CLIENT_TOKEN="$(python3 - 2>/dev/null <<'PYEOF'
import uuid
print("lc-" + uuid.uuid4().hex[:30])
PYEOF
)"; then echo "$TASK_LABEL client token generation failed, no launch attempted." >&2; phase_failed "$TASK_PHASE"; fi
  CLIENT_TOKEN="$(printf '%s' "$CLIENT_TOKEN" | tr -d '[:space:]')"
  case "$CLIENT_TOKEN" in
    lc-??????????????????????????????) ;;
    *) echo "$TASK_LABEL client token malformed, no launch attempted." >&2; phase_failed "$TASK_PHASE" ;;
  esac
  JOURNAL_FILE="$ACTIVE_FILE"
  write_launch_journal "$JOURNAL_FILE" "pending" ""
  echo "$TASK_LABEL launch journal written before run-task: $JOURNAL_FILE"
  TASK_JSON="$(mktemp /tmp/launchcrew-run-XXXXXX)"
  RUN_OK=1
  if ! "$AWS_BIN" ecs run-task --cluster "$CLUSTER_NAME" --task"-definition" "$TASKDEF_ARN" --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$JOB_SG],assignPublicIp=ENABLED}" --client-token "$CLIENT_TOKEN" --started-by "$CLIENT_TOKEN" --region "$EXPECTED_REGION" --output json >"$TASK_JSON" 2>"$TMP_ERR"; then
    RUN_OK=0
  fi
  if [ "$RUN_OK" -eq 0 ]; then
    rm -f "$TASK_JSON"
    write_launch_journal "$JOURNAL_FILE" "ambiguous_call_failed" ""
    echo "$TASK_LABEL run-task call failed; launch is ambiguous, recovering read-only before any claim." >&2
    RECOVERED_ARN=""
    recover_ambiguous_launch
    TASK_ARN="$RECOVERED_ARN"
  else
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
elif len(tasks) != 1:
    print("MULTIPLE")
else:
    arn = (tasks[0] or {}).get("taskArn", "")
    print(arn if arn and arn != "None" else "EMPTY")
PYEOF
)" || TASK_ARN="UNREADABLE"
    rm -f "$TASK_JSON"
    TASK_ARN="$(printf '%s' "$TASK_ARN" | tr -d '[:space:]')"
    case "$TASK_ARN" in
      FAILURES|EMPTY|MULTIPLE|UNREADABLE|"")
        write_launch_journal "$JOURNAL_FILE" "ambiguous_response" ""
        echo "$TASK_LABEL run-task response is ${TASK_ARN:-empty}; launch is ambiguous, recovering read-only before any claim." >&2
        RECOVERED_ARN=""
        recover_ambiguous_launch
        TASK_ARN="$RECOVERED_ARN" ;;
      *)
        write_launch_journal "$JOURNAL_FILE" "started" "$TASK_ARN"
        echo "$TASK_LABEL task started in isolated public subnets with no inbound: $TASK_ARN" ;;
    esac
  fi
  prove_terminal_task
  release_operation_lock
}

if wants_phase init; then
  echo "Phase init: isolated SDK populate task writes canonical prereq materials in task memory"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no stack owns the SDK init task; run --phase infra first" >&2; phase_failed init; }
  require_stack_complete init
  case "$COMPLETED" in
    *images*) echo "Init precondition: images already proved in this run" ;;
    *)
      verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap BootstrapTaskDefinition bootstrap-db-roles bootstrap
      echo "Init precondition: bootstrap image re-proved published with digest" ;;
  esac
  check_sdk_taskdef SdkInitTaskDefinition SdkInitExecutionRole SdkInitTaskRole sdk-init --populate
  run_one_off_task SdkInitTaskDefinition sdk-init init
  mark_done init
  echo "Phase init complete: canonical runtime, migration, and TLS materials populated"
fi

if wants_phase material; then
  echo "Phase material: isolated SDK material verify task, read-only with zero Put and zero Export"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no stack owns the SDK material task; run --phase infra first" >&2; phase_failed material; }
  require_stack_complete material
  case "$COMPLETED" in
    *init*) echo "Material precondition: init already proved in this run" ;;
    *) echo "Material precondition: init materials assumed from a previous run, verified read-only here" ;;
  esac
  check_sdk_taskdef SdkMaterialTaskDefinition SdkMaterialExecutionRole SdkMaterialTaskRole sdk-material --verify-material
  run_one_off_task SdkMaterialTaskDefinition sdk-material material
  mark_done material
  echo "Phase material complete: runtime, migration, and TLS materials verified read-only"
fi

if wants_phase dbroles; then
  echo "Phase dbroles: isolated bootstrap task binds role passwords in task memory only"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no stack owns the bootstrap task; run --phase infra first" >&2; phase_failed dbroles; }
  check_taskdef_binding BootstrapTaskDefinition BootstrapExecutionRole BootstrapTaskRole \
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
  check_taskdef_binding MigrationTaskDefinition MigrationExecutionRole MigrationTaskRole \
    "migration.DATABASE_URL=$MIGRATION_SECRET_ARN:database-url::"
  check_taskdef_binding VerifyTaskDefinition VerifyExecutionRole VerifyTaskRole \
    "bootstrap-db-roles.RUNTIME_DB_URL=$RUNTIME_SECRET_ARN:database-url::"
  run_one_off_task MigrationTaskDefinition migration migrate
  echo "Phase migrate task STOPPED exit 0; running verify-mode schema and runtime-identity proof"
  # Verify runs as its own task definition that injects only the runtime URL:
  # the master and migration secrets are never present in verify task memory.
  run_one_off_task VerifyTaskDefinition verify migrate
  mark_done migrate
  echo "Phase migrate complete: migration STOPPED exit 0 with schema and runtime read-only proof"
fi

# Foundation budget readiness on enable, read-only and fail-closed. The app
# stack owns no budget: this re-reads the exact owned foundation budget
# filter plus the exact ACTUAL 80 and FORECASTED 100 alert thresholds and
# the exact confirmed SNS subscription. It never activates a cost allocation
# tag and never changes billing. This readback only proves the filter and
# the alert wiring, never cost data, never a hard cap: filtered spend with
# no data or 0 is not proof of zero spend, spend starts at infra, RDS, and
# ALB creation even at DesiredCount 0, and the manual billing guard stays on
# the operator.
check_budget_readiness() {
  check_foundation_budget_filter
  check_foundation_notifications
  check_sns_exact_gate
  echo "Budget readiness: activation already verified Active before paid phases; this script never activates tags."
  echo "Budget readiness: filtered spend with no data or 0 is NOT proof of zero spend and NOT a hard cap. Spend starts at infra, RDS, and ALB creation even at DesiredCount 0. Manual billing guard stays on the operator."
}

# Fail-closed ECS service count proof for enable. CloudFormation does not set
# ServiceName, so physical service names are generated. A guessed name query
# returns empty services plus failures with CLI exit 0, and services[0]
# yields None, which is never treated as success. This resolves the exact
# owned physical ApiService or WebService identifier via describe-stack-resource,
# queries that identifier on the current cluster with full DescribeServices
# JSON and no JMESPath projection, then requires exactly one service with no
# failures, matching owned identity, owned cluster ARN, ACTIVE status, and
# desired 1, running 1, pending 0. Missing, duplicate, wrong identity,
# failures, non-ACTIVE, count mismatch, or malformed JSON all refuse.
verify_ecs_service() {
  VERIFY_LOGICAL="$1"
  VERIFY_SHORT="$2"
  VERIFY_PHYSICAL=""
  if ! VERIFY_PHYSICAL="$(stack_resource "$VERIFY_LOGICAL" 2>"$TMP_ERR")"; then
    echo "service $VERIFY_SHORT owned identifier unreadable, not claimed running." >&2
    phase_failed enable
  fi
  VERIFY_PHYSICAL="$(printf '%s' "$VERIFY_PHYSICAL" | tr -d '[:space:]')"
  [ -n "$VERIFY_PHYSICAL" ] && [ "$VERIFY_PHYSICAL" != "None" ] || { echo "refused: service $VERIFY_SHORT owned identifier missing, not claimed running." >&2; phase_failed enable; }
  VERIFY_JSON="$(mktemp /tmp/launchcrew-svc-XXXXXX)"
  if ! "$AWS_BIN" ecs describe-services --cluster "$CLUSTER_NAME" --services "$VERIFY_PHYSICAL" --region "$EXPECTED_REGION" --output json >"$VERIFY_JSON" 2>"$TMP_ERR"; then
    rm -f "$VERIFY_JSON"
    echo "service $VERIFY_SHORT counts unreadable, not claimed running." >&2
    phase_failed enable
  fi
  VERIFY_PROOF="$(python3 - "$VERIFY_JSON" "$VERIFY_PHYSICAL" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$CLUSTER_NAME" 2>/dev/null <<'PYEOF'
import json, sys
path, expected_id, account, region, cluster = sys.argv[1:6]
try:
    doc = json.load(open(path))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(doc, dict):
    print("MALFORMED")
    sys.exit(0)
failures = doc.get("failures", None)
if not isinstance(failures, list):
    print("MALFORMED")
    sys.exit(0)
if failures:
    print("FAILURES")
    sys.exit(0)
services = doc.get("services", None)
if not isinstance(services, list):
    print("MALFORMED")
    sys.exit(0)
if len(services) == 0:
    print("EMPTY")
    sys.exit(0)
if len(services) != 1:
    print("DUPLICATE")
    sys.exit(0)
svc = services[0]
if not isinstance(svc, dict):
    print("MALFORMED")
    sys.exit(0)
arn = svc.get("serviceArn", "")
name = svc.get("serviceName", "")
if (not isinstance(arn, str) or not isinstance(name, str)
        or not arn or not name or arn == "None" or name == "None"):
    print("IDENTITY_MISSING")
    sys.exit(0)
if arn != expected_id and name != expected_id:
    print("WRONG_SERVICE")
    sys.exit(0)
prefix = "arn:aws:ecs:%s:%s:service/" % (region, account)
if not arn.startswith(prefix):
    print("WRONG_SERVICE")
    sys.exit(0)
expected_cluster = "arn:aws:ecs:%s:%s:cluster/%s" % (region, account, cluster)
if (svc.get("clusterArn", "") or "") != expected_cluster:
    print("WRONG_CLUSTER")
    sys.exit(0)
if (svc.get("status", "") or "") != "ACTIVE":
    print("NOT_ACTIVE")
    sys.exit(0)
desired = svc.get("desiredCount", None)
running = svc.get("runningCount", None)
pending = svc.get("pendingCount", None)
for value in (desired, running, pending):
    if not isinstance(value, int) or isinstance(value, bool):
        print("MALFORMED")
        sys.exit(0)
if desired != 1:
    print("DESIRED_%s" % desired)
    sys.exit(0)
if running != 1:
    print("RUNNING_%s" % running)
    sys.exit(0)
if pending != 0:
    print("PENDING_%s" % pending)
    sys.exit(0)
print("OK")
PYEOF
)" || { rm -f "$VERIFY_JSON"; echo "service $VERIFY_SHORT proof unreadable, not claimed running." >&2; phase_failed enable; }
  rm -f "$VERIFY_JSON"
  VERIFY_PROOF="$(printf '%s' "$VERIFY_PROOF" | tr -d '[:space:]')"
  case "$VERIFY_PROOF" in
    OK)
      echo "Verified service $VERIFY_PHYSICAL desiredCount 1 runningCount 1 pendingCount 0 ACTIVE (configuration check; serving health needs ALB targets after DNS)" ;;
    *) echo "refused: service $VERIFY_SHORT proof is $VERIFY_PROOF, expected ACTIVE fixed 1/1/0 on owned identity" >&2; phase_failed enable ;;
  esac
}

# Fail-closed ECS service stopped proof for quiesce. Same owned identity
# resolution as enable, but requires ACTIVE desired 0 running 0 pending 0.
# Used only after the quiesce change set executes. Any mismatch refuses.
verify_ecs_service_stopped() {
  STOP_LOGICAL="$1"
  STOP_SHORT="$2"
  STOP_PHYSICAL=""
  if ! STOP_PHYSICAL="$(stack_resource "$STOP_LOGICAL" 2>"$TMP_ERR")"; then
    echo "service $STOP_SHORT owned identifier unreadable, not claimed stopped." >&2
    phase_failed quiesce
  fi
  STOP_PHYSICAL="$(printf '%s' "$STOP_PHYSICAL" | tr -d '[:space:]')"
  [ -n "$STOP_PHYSICAL" ] && [ "$STOP_PHYSICAL" != "None" ] || { echo "refused: service $STOP_SHORT owned identifier missing, not claimed stopped." >&2; phase_failed quiesce; }
  STOP_JSON="$(mktemp /tmp/launchcrew-svc-stop-XXXXXX)"
  if ! "$AWS_BIN" ecs describe-services --cluster "$CLUSTER_NAME" --services "$STOP_PHYSICAL" --region "$EXPECTED_REGION" --output json >"$STOP_JSON" 2>"$TMP_ERR"; then
    rm -f "$STOP_JSON"
    echo "service $STOP_SHORT counts unreadable, not claimed stopped." >&2
    phase_failed quiesce
  fi
  STOP_PROOF="$(python3 - "$STOP_JSON" "$STOP_PHYSICAL" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$CLUSTER_NAME" 2>/dev/null <<'PYEOF'
import json, sys
path, expected_id, account, region, cluster = sys.argv[1:6]
try:
    doc = json.load(open(path))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(doc, dict):
    print("MALFORMED")
    sys.exit(0)
failures = doc.get("failures", None)
if not isinstance(failures, list):
    print("MALFORMED")
    sys.exit(0)
if failures:
    print("FAILURES")
    sys.exit(0)
services = doc.get("services", None)
if not isinstance(services, list):
    print("MALFORMED")
    sys.exit(0)
if len(services) == 0:
    print("EMPTY")
    sys.exit(0)
if len(services) != 1:
    print("DUPLICATE")
    sys.exit(0)
svc = services[0]
if not isinstance(svc, dict):
    print("MALFORMED")
    sys.exit(0)
arn = svc.get("serviceArn", "")
name = svc.get("serviceName", "")
if (not isinstance(arn, str) or not isinstance(name, str)
        or not arn or not name or arn == "None" or name == "None"):
    print("IDENTITY_MISSING")
    sys.exit(0)
if arn != expected_id and name != expected_id:
    print("WRONG_SERVICE")
    sys.exit(0)
prefix = "arn:aws:ecs:%s:%s:service/" % (region, account)
if not arn.startswith(prefix):
    print("WRONG_SERVICE")
    sys.exit(0)
expected_cluster = "arn:aws:ecs:%s:%s:cluster/%s" % (region, account, cluster)
if (svc.get("clusterArn", "") or "") != expected_cluster:
    print("WRONG_CLUSTER")
    sys.exit(0)
if (svc.get("status", "") or "") != "ACTIVE":
    print("NOT_ACTIVE")
    sys.exit(0)
desired = svc.get("desiredCount", None)
running = svc.get("runningCount", None)
pending = svc.get("pendingCount", None)
for value in (desired, running, pending):
    if not isinstance(value, int) or isinstance(value, bool):
        print("MALFORMED")
        sys.exit(0)
if desired != 0:
    print("DESIRED_%s" % desired)
    sys.exit(0)
if running != 0:
    print("RUNNING_%s" % running)
    sys.exit(0)
if pending != 0:
    print("PENDING_%s" % pending)
    sys.exit(0)
print("OK")
PYEOF
)" || { rm -f "$STOP_JSON"; echo "service $STOP_SHORT proof unreadable, not claimed stopped." >&2; phase_failed quiesce; }
  rm -f "$STOP_JSON"
  STOP_PROOF="$(printf '%s' "$STOP_PROOF" | tr -d '[:space:]')"
  case "$STOP_PROOF" in
    OK)
      echo "Verified service $STOP_PHYSICAL desiredCount 0 runningCount 0 pendingCount 0 ACTIVE (stopped, not serving)" ;;
    *) echo "refused: service $STOP_SHORT proof is $STOP_PROOF, expected ACTIVE fixed 0/0/0 on owned identity" >&2; phase_failed quiesce ;;
  esac
}

if wants_phase enable; then
  echo "Phase enable: update stack with EnableServices=true for fixed count 1 each"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no stack to enable; run --phase infra first" >&2; phase_failed enable; }
  require_stack_complete enable
  check_budget_readiness
  # Resume guard: a standalone enable re-proves everything boot would rely
  # on, because nothing is assumed from memory. Refresh the full image
  # digest and task definition ref proof, the owned secrets and role bindings
  # including TLS material, the read-only material verify proof, and the
  # runtime-only verify proof (expected head, runtime identity, rolled-back
  # write, DDL refusal) before any deploy. Standalone enable never
  # populates, exports, binds, or migrates.
  verify_image "$API_IMAGE" launchcrew-api ApiTaskDefinition api api
  verify_image "$WEB_IMAGE" launchcrew-web WebTaskDefinition web-app web
  verify_image "$WEB_PROXY_IMAGE" launchcrew-web-proxy WebTaskDefinition web-proxy web-proxy
  verify_image "$MIGRATION_IMAGE" launchcrew-migration MigrationTaskDefinition migration migration
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap BootstrapTaskDefinition bootstrap-db-roles bootstrap
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap SdkInitTaskDefinition sdk-init bootstrap-sdk-init
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap SdkMaterialTaskDefinition sdk-material bootstrap-sdk-material
  check_taskdef_binding ApiTaskDefinition ApiExecutionRole ApiTaskRole \
    "api.DATABASE_URL=$RUNTIME_SECRET_ARN:database-url::" \
    "api.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
    "api.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::"
  check_taskdef_binding WebTaskDefinition WebExecutionRole WebTaskRole \
    "web-proxy.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
    "web-proxy.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::"
  check_taskdef_binding VerifyTaskDefinition VerifyExecutionRole VerifyTaskRole \
    "bootstrap-db-roles.RUNTIME_DB_URL=$RUNTIME_SECRET_ARN:database-url::"
  check_sdk_taskdef SdkMaterialTaskDefinition SdkMaterialExecutionRole SdkMaterialTaskRole sdk-material --verify-material
  echo "Enable precheck: all five owned task definition images, secrets, and owned roles match validated values, SDK material shape proven"
  case "$COMPLETED" in
    *material*) echo "Enable proof: material already proved verify in this run, no rerun" ;;
    *) run_one_off_task SdkMaterialTaskDefinition sdk-material enable ;;
  esac
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
  verify_ecs_service ApiService api
  verify_ecs_service WebService web
  mark_done enable
  echo "Phase enable complete: both services fixed count 1 each, no autoscaling"
fi

if [ "$PHASE" = "quiesce" ]; then
  echo "Phase quiesce: safe maintenance to DesiredCount 0 on the owned stack"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no owned stack to quiesce; run --phase infra first, no change made" >&2; phase_failed quiesce; }
  require_stack_complete quiesce
  [ -n "$QUIESCE_CONFIRM" ] || { echo "refused: quiesce needs explicit --quiesce-confirm <exact-StackId>, no change made" >&2; phase_failed quiesce; }
  [ "$QUIESCE_CONFIRM" = "$STACK_ID" ] || { echo "refused: quiesce confirm does not equal the exact owned StackId, no change made" >&2; phase_failed quiesce; }
  echo "Verified quiesce ownership: caller $CALLER_ACCOUNT, stack $STACK_NAME, StackId confirmed, tags Project LaunchCrew Environment demo"
  if [ "$CURRENT_ENABLE" = "false" ]; then
    echo "Quiesce: stack already EnableServices=false, verifying stopped state with no change."
    verify_ecs_service_stopped ApiService api
    verify_ecs_service_stopped WebService web
    mark_done quiesce
    echo "Phase quiesce complete: already stopped, no change made"
  else
    [ "$CURRENT_ENABLE" = "true" ] || { echo "refused: EnableServices is $CURRENT_ENABLE, expected true or false, no change made" >&2; phase_failed quiesce; }
    QUIESCE_OLD_API_TASKDEF=""
    QUIESCE_OLD_WEB_TASKDEF=""
    if ! QUIESCE_OLD_API_TASKDEF="$(stack_resource ApiTaskDefinition 2>"$TMP_ERR")"; then
      echo "refused: old ApiTaskDefinition unreadable, no change made" >&2; phase_failed quiesce
    fi
    if ! QUIESCE_OLD_WEB_TASKDEF="$(stack_resource WebTaskDefinition 2>"$TMP_ERR")"; then
      echo "refused: old WebTaskDefinition unreadable, no change made" >&2; phase_failed quiesce
    fi
    QUIESCE_OLD_API_TASKDEF="$(printf '%s' "$QUIESCE_OLD_API_TASKDEF" | tr -d '[:space:]')"
    QUIESCE_OLD_WEB_TASKDEF="$(printf '%s' "$QUIESCE_OLD_WEB_TASKDEF" | tr -d '[:space:]')"
    [ -n "$QUIESCE_OLD_API_TASKDEF" ] && [ "$QUIESCE_OLD_API_TASKDEF" != "None" ] || { echo "refused: old ApiTaskDefinition missing, no change made" >&2; phase_failed quiesce; }
    [ -n "$QUIESCE_OLD_WEB_TASKDEF" ] && [ "$QUIESCE_OLD_WEB_TASKDEF" != "None" ] || { echo "refused: old WebTaskDefinition missing, no change made" >&2; phase_failed quiesce; }
    QUIESCE_OLD_API_JSON="$(mktemp /tmp/launchcrew-quiesce-api-XXXXXX)"
    QUIESCE_OLD_WEB_JSON="$(mktemp /tmp/launchcrew-quiesce-web-XXXXXX)"
    if ! fetch_taskdef_json ApiTaskDefinition "$QUIESCE_OLD_API_JSON"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"
      echo "refused: old ApiTaskDefinition document unreadable, no change made" >&2; phase_failed quiesce
    fi
    if ! fetch_taskdef_json WebTaskDefinition "$QUIESCE_OLD_WEB_JSON"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"
      echo "refused: old WebTaskDefinition document unreadable, no change made" >&2; phase_failed quiesce
    fi
    QUIESCE_OLD_IMAGES="$(python3 - "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    api = json.load(open(sys.argv[1]))
    web = json.load(open(sys.argv[2]))
except Exception:
    sys.exit(1)
def image_of(doc, name):
    taskdef = doc.get("taskDefinition", doc)
    for container in taskdef.get("containerDefinitions", []) or []:
        if (container.get("name", "") or "") == name:
            return container.get("image", "") or ""
    return ""
print("API\t%s" % image_of(api, "api"))
print("WEB\t%s" % image_of(web, "web-app"))
print("PROXY\t%s" % image_of(web, "web-proxy"))
PYEOF
)" || { rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"; echo "refused: old taskdef images unreadable, no change made" >&2; phase_failed quiesce; }
    QUIESCE_OLD_API_IMAGE="$(printf '%s\n' "$QUIESCE_OLD_IMAGES" | awk -F'\t' '$1=="API"{print $2}')"
    QUIESCE_OLD_WEB_IMAGE="$(printf '%s\n' "$QUIESCE_OLD_IMAGES" | awk -F'\t' '$1=="WEB"{print $2}')"
    QUIESCE_OLD_PROXY_IMAGE="$(printf '%s\n' "$QUIESCE_OLD_IMAGES" | awk -F'\t' '$1=="PROXY"{print $2}')"
    [ -n "$QUIESCE_OLD_API_IMAGE" ] || { rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"; echo "refused: old api image missing, no change made" >&2; phase_failed quiesce; }
    [ -n "$QUIESCE_OLD_WEB_IMAGE" ] || { rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"; echo "refused: old web image missing, no change made" >&2; phase_failed quiesce; }
    [ -n "$QUIESCE_OLD_PROXY_IMAGE" ] || { rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"; echo "refused: old proxy image missing, no change made" >&2; phase_failed quiesce; }
    echo "Quiesce old identity captured: ApiTaskDefinition and WebTaskDefinition plus three images pinned for unchanged proof"
    QUIESCE_STACK_JSON="$(mktemp /tmp/launchcrew-quiesce-stack-XXXXXX)"
    if ! "$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" --output json >"$QUIESCE_STACK_JSON" 2>"$TMP_ERR"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"
      echo "refused: stack parameters unreadable, no change made" >&2; phase_failed quiesce
    fi
    QUIESCE_PARAMS="$(python3 - "$QUIESCE_STACK_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
stacks = doc.get("Stacks", [])
if len(stacks) != 1:
    print("COUNT")
    sys.exit(0)
params = stacks[0].get("Parameters", [])
if not isinstance(params, list) or not params:
    print("EMPTY")
    sys.exit(0)
keys = []
for entry in params:
    if not isinstance(entry, dict):
        print("MALFORMED")
        sys.exit(0)
    key = entry.get("ParameterKey", "")
    if not isinstance(key, str) or not key:
        print("MALFORMED")
        sys.exit(0)
    keys.append(key)
if len(set(keys)) != len(keys):
    print("DUPLICATE")
    sys.exit(0)
if "EnableServices" not in keys:
    print("NO_ENABLE")
    sys.exit(0)
print("OK")
for key in sorted(keys):
    print("KEY\t%s" % key)
PYEOF
)" || { rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"; echo "refused: stack parameters unreadable, no change made" >&2; phase_failed quiesce; }
    QUIESCE_PARAMS_PROOF="$(printf '%s\n' "$QUIESCE_PARAMS" | head -n 1 | tr -d '[:space:]')"
    if [ "$QUIESCE_PARAMS_PROOF" != "OK" ]; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"
      echo "refused: stack parameters proof is $QUIESCE_PARAMS_PROOF, expected owned list with EnableServices, no change made" >&2
      phase_failed quiesce
    fi
    QUIESCE_CHANGESET="quiesce-$TARGET_DB_HEAD"
    QUIESCE_ARGS_FILE="$(mktemp /tmp/launchcrew-quiesce-args-XXXXXX)"
    printf '%s\n' "$QUIESCE_PARAMS" | awk -F'\t' '$1=="KEY"{print $2}' >"$QUIESCE_ARGS_FILE"
    QUIESCE_PARAM_ARGS=""
    while IFS= read -r QUIESCE_KEY; do
      [ -n "$QUIESCE_KEY" ] || continue
      if [ "$QUIESCE_KEY" = "EnableServices" ]; then
        QUIESCE_PARAM_ARGS="$QUIESCE_PARAM_ARGS ParameterKey=EnableServices,ParameterValue=false"
      else
        QUIESCE_PARAM_ARGS="$QUIESCE_PARAM_ARGS ParameterKey=$QUIESCE_KEY,UsePreviousValue=true"
      fi
    done <"$QUIESCE_ARGS_FILE"
    rm -f "$QUIESCE_ARGS_FILE" "$QUIESCE_STACK_JSON"
    [ -n "$QUIESCE_PARAM_ARGS" ] || { rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"; echo "refused: quiesce parameters empty, no change made" >&2; phase_failed quiesce; }
    echo "Quiesce change set uses the existing deployed template with all existing values except EnableServices=false"
    # shellcheck disable=SC2086
    if ! "$AWS_BIN" cloudformation create-change-set --stack-name "$STACK_NAME" --change-set-name "$QUIESCE_CHANGESET" --change-set-type UPDATE --use-previous-template --parameters $QUIESCE_PARAM_ARGS --capabilities CAPABILITY_NAMED_IAM --tags Key=Project,Value=LaunchCrew Key=Environment,Value=demo --region "$EXPECTED_REGION" --output json >"$TMP_JSON" 2>"$TMP_ERR"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"
      echo "refused: quiesce change set create failed, no change made" >&2; phase_failed quiesce
    fi
    QUIESCE_DESC_JSON="$(mktemp /tmp/launchcrew-quiesce-desc-XXXXXX)"
    if ! "$AWS_BIN" cloudformation describe-change-set --stack-name "$STACK_NAME" --change-set-name "$QUIESCE_CHANGESET" --region "$EXPECTED_REGION" --output json >"$QUIESCE_DESC_JSON" 2>"$TMP_ERR"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_DESC_JSON"
      "$AWS_BIN" cloudformation delete-change-set --stack-name "$STACK_NAME" --change-set-name "$QUIESCE_CHANGESET" --region "$EXPECTED_REGION" >/dev/null 2>&1 || true
      echo "refused: quiesce change set unreadable, deleted with no change made" >&2; phase_failed quiesce
    fi
    QUIESCE_REVIEW="$(python3 - "$QUIESCE_DESC_JSON" "$STACK_NAME" "$STACK_ID" 2>/dev/null <<'PYEOF'
import json, sys
path, want_stack, want_id = sys.argv[1:4]
try:
    doc = json.load(open(path))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(doc, dict):
    print("MALFORMED")
    sys.exit(0)
if (doc.get("StackName", "") or "") != want_stack:
    print("STACK_MISMATCH")
    sys.exit(0)
if (doc.get("StackId", "") or "") != want_id:
    print("STACKID_MISMATCH")
    sys.exit(0)
if (doc.get("Status", "") or "") != "CREATE_COMPLETE":
    print("STATUS_%s" % (doc.get("Status", "") or "EMPTY"))
    sys.exit(0)
if (doc.get("ExecutionStatus", "") or "") != "AVAILABLE":
    print("EXEC_%s" % (doc.get("ExecutionStatus", "") or "EMPTY"))
    sys.exit(0)
changes = doc.get("Changes", None)
if not isinstance(changes, list):
    print("MALFORMED")
    sys.exit(0)
if len(changes) == 0:
    print("EMPTY")
    sys.exit(0)
if len(changes) > 4:
    print("TOO_MANY_%s" % len(changes))
    sys.exit(0)
seen = set()
for entry in changes:
    if not isinstance(entry, dict):
        print("MALFORMED")
        sys.exit(0)
    if (entry.get("Type", "") or "") != "Resource":
        print("NON_RESOURCE")
        sys.exit(0)
    rc = entry.get("ResourceChange", None)
    if not isinstance(rc, dict):
        print("MALFORMED")
        sys.exit(0)
    logical = rc.get("LogicalResourceId", "") or ""
    action = rc.get("Action", "") or ""
    rtype = rc.get("ResourceType", "") or ""
    replacement = rc.get("Replacement", "False")
    if logical not in ("ApiService", "WebService"):
        print("FOREIGN_%s" % (logical or "EMPTY"))
        sys.exit(0)
    if logical in seen:
        print("DUPLICATE_%s" % logical)
        sys.exit(0)
    seen.add(logical)
    if action != "Modify":
        print("ACTION_%s_%s" % (logical, action or "EMPTY"))
        sys.exit(0)
    if rtype != "AWS::ECS::Service":
        print("TYPE_%s_%s" % (logical, rtype or "EMPTY"))
        sys.exit(0)
    if str(replacement) != "False":
        print("REPLACEMENT_%s_%s" % (logical, str(replacement)))
        sys.exit(0)
    scope = rc.get("Scope", None)
    if scope is not None:
        if not isinstance(scope, list) or not scope:
            print("SCOPE_%s" % logical)
            sys.exit(0)
        for item in scope:
            if item not in ("Properties", "Tags", "Metadata"):
                print("SCOPE_%s_%s" % (logical, str(item)))
                sys.exit(0)
if seen != {"ApiService", "WebService"}:
    print("INCOMPLETE_%s" % ",".join(sorted(seen)))
    sys.exit(0)
print("OK")
PYEOF
)" || QUIESCE_REVIEW="UNREADABLE"
    QUIESCE_REVIEW="$(printf '%s' "$QUIESCE_REVIEW" | tr -d '[:space:]')"
    if [ "$QUIESCE_REVIEW" != "OK" ]; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_DESC_JSON"
      "$AWS_BIN" cloudformation delete-change-set --stack-name "$STACK_NAME" --change-set-name "$QUIESCE_CHANGESET" --region "$EXPECTED_REGION" >/dev/null 2>&1 || true
      echo "refused: quiesce change set proof is $QUIESCE_REVIEW, expected only ApiService and WebService Modify with no replacement. Change set deleted with no change made." >&2
      phase_failed quiesce
    fi
    rm -f "$QUIESCE_DESC_JSON"
    echo "Quiesce change set reviewed: only ApiService and WebService Modify to DesiredCount 0, no replacement, no DB or network or cert or secrets change"
    if ! "$AWS_BIN" cloudformation execute-change-set --stack-name "$STACK_NAME" --change-set-name "$QUIESCE_CHANGESET" --region "$EXPECTED_REGION" >/dev/null 2>"$TMP_ERR"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"
      echo "refused: quiesce execute failed, state unknown, verify stack status before any retry" >&2; phase_failed quiesce
    fi
    if ! "$AWS_BIN" cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
      echo "quiesce wait reported, verifying exact UPDATE_COMPLETE before any claim." >&2
    fi
    QUIESCE_STATUS=""
    if ! QUIESCE_STATUS="$("$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" --query "Stacks[0].StackStatus" --output text 2>"$TMP_ERR")"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"
      echo "refused: quiesce stack status unreadable, not treated as success" >&2; phase_failed quiesce
    fi
    QUIESCE_STATUS="$(printf '%s' "$QUIESCE_STATUS" | tr -d '[:space:]')"
    if [ "$QUIESCE_STATUS" != "UPDATE_COMPLETE" ]; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"
      echo "refused: quiesce stack status is $QUIESCE_STATUS, expected exact UPDATE_COMPLETE" >&2; phase_failed quiesce
    fi
    STACK_STATUS="$QUIESCE_STATUS"
    verify_ecs_service_stopped ApiService api
    verify_ecs_service_stopped WebService web
    QUIESCE_NEW_API_TASKDEF=""
    QUIESCE_NEW_WEB_TASKDEF=""
    if ! QUIESCE_NEW_API_TASKDEF="$(stack_resource ApiTaskDefinition 2>"$TMP_ERR")"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"
      echo "refused: new ApiTaskDefinition unreadable after quiesce" >&2; phase_failed quiesce
    fi
    if ! QUIESCE_NEW_WEB_TASKDEF="$(stack_resource WebTaskDefinition 2>"$TMP_ERR")"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"
      echo "refused: new WebTaskDefinition unreadable after quiesce" >&2; phase_failed quiesce
    fi
    QUIESCE_NEW_API_TASKDEF="$(printf '%s' "$QUIESCE_NEW_API_TASKDEF" | tr -d '[:space:]')"
    QUIESCE_NEW_WEB_TASKDEF="$(printf '%s' "$QUIESCE_NEW_WEB_TASKDEF" | tr -d '[:space:]')"
    if [ "$QUIESCE_NEW_API_TASKDEF" != "$QUIESCE_OLD_API_TASKDEF" ]; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"
      echo "refused: ApiTaskDefinition changed during quiesce, expected unchanged old identity" >&2; phase_failed quiesce
    fi
    if [ "$QUIESCE_NEW_WEB_TASKDEF" != "$QUIESCE_OLD_WEB_TASKDEF" ]; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"
      echo "refused: WebTaskDefinition changed during quiesce, expected unchanged old identity" >&2; phase_failed quiesce
    fi
    QUIESCE_NEW_API_JSON="$(mktemp /tmp/launchcrew-quiesce-new-api-XXXXXX)"
    QUIESCE_NEW_WEB_JSON="$(mktemp /tmp/launchcrew-quiesce-new-web-XXXXXX)"
    if ! fetch_taskdef_json ApiTaskDefinition "$QUIESCE_NEW_API_JSON"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_NEW_API_JSON" "$QUIESCE_NEW_WEB_JSON"
      echo "refused: new ApiTaskDefinition document unreadable after quiesce" >&2; phase_failed quiesce
    fi
    if ! fetch_taskdef_json WebTaskDefinition "$QUIESCE_NEW_WEB_JSON"; then
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_NEW_API_JSON" "$QUIESCE_NEW_WEB_JSON"
      echo "refused: new WebTaskDefinition document unreadable after quiesce" >&2; phase_failed quiesce
    fi
    QUIESCE_NEW_IMAGES="$(python3 - "$QUIESCE_NEW_API_JSON" "$QUIESCE_NEW_WEB_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    api = json.load(open(sys.argv[1]))
    web = json.load(open(sys.argv[2]))
except Exception:
    sys.exit(1)
def image_of(doc, name):
    taskdef = doc.get("taskDefinition", doc)
    for container in taskdef.get("containerDefinitions", []) or []:
        if (container.get("name", "") or "") == name:
            return container.get("image", "") or ""
    return ""
print("API\t%s" % image_of(api, "api"))
print("WEB\t%s" % image_of(web, "web-app"))
print("PROXY\t%s" % image_of(web, "web-proxy"))
PYEOF
)" || { rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_NEW_API_JSON" "$QUIESCE_NEW_WEB_JSON"; echo "refused: new taskdef images unreadable after quiesce" >&2; phase_failed quiesce; }
    QUIESCE_NEW_API_IMAGE="$(printf '%s\n' "$QUIESCE_NEW_IMAGES" | awk -F'\t' '$1=="API"{print $2}')"
    QUIESCE_NEW_WEB_IMAGE="$(printf '%s\n' "$QUIESCE_NEW_IMAGES" | awk -F'\t' '$1=="WEB"{print $2}')"
    QUIESCE_NEW_PROXY_IMAGE="$(printf '%s\n' "$QUIESCE_NEW_IMAGES" | awk -F'\t' '$1=="PROXY"{print $2}')"
    rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_NEW_API_JSON" "$QUIESCE_NEW_WEB_JSON"
    [ "$QUIESCE_NEW_API_IMAGE" = "$QUIESCE_OLD_API_IMAGE" ] || { echo "refused: api image changed during quiesce, expected unchanged old image" >&2; phase_failed quiesce; }
    [ "$QUIESCE_NEW_WEB_IMAGE" = "$QUIESCE_OLD_WEB_IMAGE" ] || { echo "refused: web image changed during quiesce, expected unchanged old image" >&2; phase_failed quiesce; }
    [ "$QUIESCE_NEW_PROXY_IMAGE" = "$QUIESCE_OLD_PROXY_IMAGE" ] || { echo "refused: proxy image changed during quiesce, expected unchanged old image" >&2; phase_failed quiesce; }
    echo "Verified quiesce identity: old task definitions and images unchanged"
    mark_done quiesce
    echo "Phase quiesce complete: stack UPDATE_COMPLETE, both services 0/0/0, old images preserved. Foundation and prereqs untouched."
  fi
fi

echo "BOOTSTRAP COMPLETE phases requested: $PHASE. Completed: ${COMPLETED:-none}."
echo "Outside-stack remaining work: secret values, ACM certificate, DNS, snapshots need separate approval with exact identifiers."
