#!/bin/sh
# LaunchCrew demo staged bootstrap, dry-run by default, gated phased bring-up.
# Dry-run makes no AWS call. Confirm path brings infrastructure up in order and
# refuses to start the app early:
#   phase infra   deploy the CloudFormation stack with EnableServices=false on a
#                 fresh stack (owned updates refuse while EnableServices=true
#                 so task definitions and images are never updated under
#                 running services; run explicit phase quiesce first, and owned
#                 updates prove both services live 0/0/0, review every page of
#                 a bounded change set allowing only owned task definition
#                 image or service taskdef Modify with replacement only on the
#                 eight task definitions plus optional exact ApiGoogleAuthPolicy
#                 Add only when Google explicitly enabled plus optional exact
#                 ApiMetaSecretPolicy Add only when MetaSecretArn is set, each
#                 with least privilege proof, then execute the same reviewed
#                 change set ID and re-prove 0/0/0, never deleting a
#                 same-name pending set),
#                 so VPC, ECR repositories, RDS, and task definitions
#                 exist with both ECS services at DesiredCount 0 and no app running
#   phase quiesce safe maintenance to stop the owned app before an update:
#                 verify exact stack ownership, identity, and tags, review every
#                 page of a bounded change set built from the existing deployed
#                 template and all existing parameter values except
#                 EnableServices=false whose only accepted effect is ApiService
#                 and WebService DesiredCount to 0 with no other property, tag,
#                 or resource change, with bounded wait for CREATE_COMPLETE and
#                 safe resume of an existing exact same-name set after read-only
#                 identity, status, stack, parameter, tag, and diff proof, never
#                 deleting or recreating blindly and never executing when state
#                 is ambiguous, malformed, foreign, or mismatched, then execute
#                 the same reviewed change set ID only on explicit operator
#                 confirm, then require UPDATE_COMPLETE plus both services 0/0/0
#                 with unchanged old task definition and image identity,
#                 preserved exact stack tags, and both owned ALB target groups
#                 drained. Fail closed on drift, empty or ambiguous data, or any
#                 other resource change. Never part of phase all; run explicitly
#                 before infra on a live stack.
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
#                 prior complete material, migration, and verify journals from
#                 the current release generation with live describe and no new
#                 run-task call, then update the stack with EnableServices=true
#                 for fixed count 1 each, then verify both owned physical
#                 services report ACTIVE desired 1 running 1 pending 0 with
#                 task definitions and images unchanged by the enable deploy.
#                 Standalone enable never populates, exports, binds, migrates,
#                 or launches any one-off task.
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
GOOGLE_SECRET_ARN=""
META_SECRET_ARN=""
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
TARGET_DB_HEAD="008"
# Empty journal default resolves inside run_one_off_task to a dedicated
# persistent private directory under the ignored .local tree derived from the
# script root, never shared /tmp. An explicit --launch-journal-dir still
# overrides. Release generation defaults to head008 plus the source Git SHA
# short hash when available; an explicit --release-generation still overrides
# for tests. Old one-shot journals are never deleted, renamed, or overwritten;
# a new generation uses a distinct path and must enumerate and reconcile
# every prior-generation record to STOPPED with all essential exits 0.

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
  echo "  --quiesce-confirm <exact-StackId> plus --parameters-file plus --foundation-stack-name"
  echo "  plus --foundation-parameters-file plus --prereqs-stack-name; it never runs as part of --phase all."
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
    --google-secret-arn) GOOGLE_SECRET_ARN="${2:-}"; shift 2 ;;
    --google-secret-arn=*) GOOGLE_SECRET_ARN="${1#--google-secret-arn=}"; shift ;;
    --meta-secret-arn) META_SECRET_ARN="${2:-}"; shift 2 ;;
    --meta-secret-arn=*) META_SECRET_ARN="${1#--meta-secret-arn=}"; shift ;;
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
  echo "     run explicit phase quiesce first, prove live 0/0/0, review every page of a"
  echo "     bounded diff with taskdef-only replacement plus optional exact Google policy"
  echo "     Add only when enabled with least privilege proof, execute the same reviewed ID,"
  echo "     re-prove 0/0/0, then require CREATE_COMPLETE or UPDATE_COMPLETE"
  echo "  2a. quiesce: explicit safe maintenance only, never part of all; verify exact owned"
  echo "     stack identity and tags, bounded wait for CREATE_COMPLETE, review every page"
  echo "     of a bounded change set from the existing template with only ApiService and"
  echo "     WebService DesiredCount to 0, safe resume of an existing exact same-name set"
  echo "     after read-only proof with no blind delete, execute the same reviewed ID only"
  echo "     on explicit --quiesce-confirm StackId, then require UPDATE_COMPLETE plus 0/0/0"
  echo "     with unchanged images, exact tags, and drained target groups"
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
  echo "     activated here), then re-prove images, bindings, plus prior material,"
  echo "     migration, and verify journals with live describe and no new run-task,"
  echo "     then update stack with EnableServices=true, verify owned services ACTIVE"
  echo "     desired 1 running 1 pending 0 each with taskdefs and images unchanged"
  echo "     by the enable deploy (configuration check only; serving"
  echo "     health is proven by ALB targets after DNS). Standalone"
  echo "     enable never populates, exports, binds, migrates, or launches tasks."
  echo "Per-phase inputs: infra needs stack, account, region, parameters file plus foundation gate args;"
  echo "  images needs the five image URIs plus the four secret ARNs for the API and web bindings;"
  echo "  init and material need the bootstrap image plus all four secret ARNs plus foundation gate args;"
  echo "  dbroles needs the bootstrap image and three secret ARNs plus foundation gate args;"
  echo "  migrate needs the migration and bootstrap images plus migration and runtime secret ARNs plus foundation gate args;"
  echo "  enable needs the five image URIs and all four secret ARNs to re-prove refs, bindings, and verify."
  echo "  Google auth, when EnableGoogleAuth true in the parameters file: images, infra, and enable need"
  echo "  --google-secret-arn with the exact owned Google secret for five secret API binding proof."
  echo "  --meta-secret-arn with the exact owned Meta key secret for live model API binding proof."
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
    [ -n "$PARAMETERS_FILE" ] || { echo "confirm requires --parameters-file" >&2; exit 2; }
    [ -f "$PARAMETERS_FILE" ] || { echo "refused: parameters file not found: $PARAMETERS_FILE" >&2; exit 2; }
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
  [ -n "$RUNTIME_SECRET_ARN" ] || [ -n "$MIGRATION_SECRET_ARN" ] || [ -n "$MASTER_SECRET_ARN" ] || [ -n "$TLS_SECRET_ARN" ] || [ -n "$GOOGLE_SECRET_ARN" ] || [ -n "$META_SECRET_ARN" ]
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
RECOVERY_LOCK_DIR=""
RECOVERY_LOCK_OWNER_FILE=""
RECOVERY_LOCK_OWNED=0

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
  if [ "${RECOVERY_LOCK_OWNED:-0}" -eq 1 ] && [ -n "${RECOVERY_LOCK_DIR:-}" ] && [ -n "${RECOVERY_LOCK_OWNER_FILE:-}" ]; then
    if [ -f "$RECOVERY_LOCK_OWNER_FILE" ]; then
      RECOVERY_OWNER_PID="$(cat "$RECOVERY_LOCK_OWNER_FILE" 2>/dev/null | tr -d '[:space:]' || echo "")"
      if [ "$RECOVERY_OWNER_PID" = "$$" ]; then
        rm -f "$RECOVERY_LOCK_OWNER_FILE" 2>/dev/null || true
        rmdir "$RECOVERY_LOCK_DIR" 2>/dev/null || true
      fi
    fi
  fi
  RECOVERY_LOCK_DIR=""
  RECOVERY_LOCK_OWNER_FILE=""
  RECOVERY_LOCK_OWNED=0
  rm -f "$TMP_ERR" "$TMP_JSON" "$TMP_PARAMS" 2>/dev/null || true
}

release_recovery_lock() {
  if [ "${RECOVERY_LOCK_OWNED:-0}" -eq 1 ] && [ -n "${RECOVERY_LOCK_DIR:-}" ] && [ -n "${RECOVERY_LOCK_OWNER_FILE:-}" ]; then
    if [ -f "$RECOVERY_LOCK_OWNER_FILE" ]; then
      RECOVERY_OWNER_PID="$(cat "$RECOVERY_LOCK_OWNER_FILE" 2>/dev/null | tr -d '[:space:]' || echo "")"
      if [ "$RECOVERY_OWNER_PID" = "$$" ]; then
        rm -f "$RECOVERY_LOCK_OWNER_FILE" 2>/dev/null || true
        rmdir "$RECOVERY_LOCK_DIR" 2>/dev/null || true
      fi
    fi
  fi
  RECOVERY_LOCK_DIR=""
  RECOVERY_LOCK_OWNER_FILE=""
  RECOVERY_LOCK_OWNED=0
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
  if [ -n "$GOOGLE_SECRET_ARN" ]; then check_secret_arn "$GOOGLE_SECRET_ARN" "google"; fi
  if [ -n "$META_SECRET_ARN" ]; then check_secret_arn "$META_SECRET_ARN" "meta"; fi
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
                     "MasterDbPasswordSecretArn", "TlsSecretArn",
                     "GoogleOAuthSecretArn", "MetaSecretArn"}
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
  PARAM_MATCH GoogleOAuthSecretArn "$GOOGLE_SECRET_ARN" || exit 1
  PARAM_MATCH MetaSecretArn "$META_SECRET_ARN" || exit 1
  echo "Verified CLI images and secret ARNs match the parameters file being deployed"
}

case "$PHASE" in
  infra|init|material|dbroles|migrate|enable|all) check_params_match ;;
esac

# Google-only auth gate, fail-closed before any mutation. Reads EnableGoogleAuth
# plus GoogleOAuthSecretArn from the parameters file being deployed. True plus
# empty, placeholder, malformed, unowned, or CLI mismatch refuses. True requires
# an exact validated CLI Google ARN that equals the file value and passes exact
# ARN shape plus account plus region plus returned ARN plus Project LaunchCrew
# plus Environment demo metadata. False with a CLI Google ARN refuses, since a
# validated secret must not be ignored. False without CLI keeps the keyless
# three secret path. No secret value appears in argv, files, or logs.
check_google_auth_gate() {
  GATE_LABEL="${1:-all}"
  GATE_ENABLE=""
  GATE_FILE_GOOGLE=""
  GATE_ENABLE="$(params_file_value EnableGoogleAuth 2>/dev/null || true)"
  GATE_FILE_GOOGLE="$(params_file_value GoogleOAuthSecretArn 2>/dev/null || true)"
  GATE_ENABLE="$(printf '%s' "$GATE_ENABLE" | tr -d '[:space:]')"
  GATE_FILE_GOOGLE="$(printf '%s' "$GATE_FILE_GOOGLE" | tr -d '[:space:]')"
  if [ -z "$GATE_ENABLE" ]; then GATE_ENABLE="false"; fi
  case "$GATE_ENABLE" in
    true|false) ;;
    *) echo "refused: EnableGoogleAuth is $GATE_ENABLE, expected true or false, no change made" >&2; phase_failed "$GATE_LABEL" ;;
  esac
  if [ "$GATE_ENABLE" = "true" ]; then
    case "$GATE_FILE_GOOGLE" in
      ""|*REPLACE_WITH*|*PLACEHOLDER*)
        echo "refused: EnableGoogleAuth true requires exact GoogleOAuthSecretArn, empty or placeholder refused before any mutation" >&2
        phase_failed "$GATE_LABEL" ;;
    esac
    [ -n "$GOOGLE_SECRET_ARN" ] || { echo "refused: EnableGoogleAuth true requires exact --google-secret-arn, missing CLI value refused before any mutation" >&2; phase_failed "$GATE_LABEL"; }
    [ "$GATE_FILE_GOOGLE" = "$GOOGLE_SECRET_ARN" ] || { echo "refused: parameters file GoogleOAuthSecretArn does not equal the validated CLI value, validating one set while deploying another is refused" >&2; phase_failed "$GATE_LABEL"; }
    check_secret_arn "$GOOGLE_SECRET_ARN" "google"
    echo "Verified Google auth gate: EnableGoogleAuth true plus exact owned Google secret $GOOGLE_SECRET_ARN"
  else
    if [ -n "$GOOGLE_SECRET_ARN" ]; then
      echo "refused: --google-secret-arn requires EnableGoogleAuth true, keyless false must not ignore a validated secret" >&2
      phase_failed "$GATE_LABEL"
    fi
    echo "Verified Google auth gate: EnableGoogleAuth false, keyless three secret path"
  fi
}

# Meta key gate, fail-closed before any mutation. Reads MetaSecretArn from
# the parameters file being deployed. Empty keeps the runtime keyless with
# deterministic fallback. A placeholder or malformed value refuses. A set
# value requires an exact validated CLI Meta ARN that equals the file value
# and passes exact ARN shape plus account plus region plus returned ARN plus
# Project LaunchCrew plus Environment demo metadata. No secret value appears
# in argv, files, or logs.
check_meta_key_gate() {
  META_GATE_LABEL="${1:-all}"
  META_FILE_ARN="$(params_file_value MetaSecretArn 2>/dev/null || true)"
  META_FILE_ARN="$(printf '%s' "$META_FILE_ARN" | tr -d '[:space:]')"
  if [ -z "$META_FILE_ARN" ]; then
    if [ -n "$META_SECRET_ARN" ]; then
      echo "refused: --meta-secret-arn with empty MetaSecretArn in the parameters file validates one secret while deploying another, no change made" >&2
      phase_failed "$META_GATE_LABEL"
    fi
    echo "Verified Meta key gate: MetaSecretArn empty, keyless runtime with deterministic fallback"
    return 0
  fi
  case "$META_FILE_ARN" in
    *REPLACE_WITH*|*PLACEHOLDER*)
      echo "refused: MetaSecretArn is a placeholder, replace with the exact owned Meta secret ARN before any mutation" >&2
      phase_failed "$META_GATE_LABEL" ;;
  esac
  [ -n "$META_SECRET_ARN" ] || { echo "refused: MetaSecretArn is set, exact --meta-secret-arn is required, missing CLI value refused before any mutation" >&2; phase_failed "$META_GATE_LABEL"; }
  [ "$META_FILE_ARN" = "$META_SECRET_ARN" ] || { echo "refused: parameters file MetaSecretArn does not equal the validated CLI value, validating one set while deploying another is refused" >&2; phase_failed "$META_GATE_LABEL"; }
  check_secret_arn "$META_SECRET_ARN" "meta"
  echo "Verified Meta key gate: exact owned Meta secret $META_SECRET_ARN"
}

# Least privilege proof for the conditional Google IAM policy, fail-closed
# before any infra mutation when Google is enabled. Reads the deployed
# template file and proves ApiGoogleAuthPolicy carries exactly one Allow
# for secretsmanager:GetSecretValue on only the exact Google secret ref,
# attached to only the exact ApiExecutionRole ref, with no wildcard, no
# extra action, no extra resource, and no KMS grant. Secret ownership plus
# CLI and file equality is already proven by the Google gate before this
# runs. Any other shape refuses with no mutation.
verify_google_policy_least_privilege() {
  POLICY_LABEL="${1:-infra}"
  POLICY_PROOF="$(python3 - "$TEMPLATE_FILE" 2>/dev/null <<'PYEOF'
import sys
path = sys.argv[1]
try:
    text = open(path, encoding="utf-8").read()
except Exception:
    print("TEMPLATE_UNREADABLE")
    sys.exit(0)
marker = "ApiGoogleAuthPolicy:"
start = text.find(marker)
if start < 0:
    print("POLICY_ABSENT")
    sys.exit(0)
end = text.find("\n  ApiMetaSecretPolicy:", start)
if end < 0:
    end = text.find("\n  ApiTaskDefinition:", start)
if end < 0:
    end = len(text)
block = text[start:end]
def has(piece):
    return piece in block
required = [
    "Type: AWS::IAM::Policy",
    "Condition: GoogleAuthEnabled",
    "PolicyName: api-google-auth-secret-only",
    "Action: [secretsmanager:GetSecretValue]",
    "Resource: [!Ref GoogleOAuthSecretArn]",
    "Roles: [!Ref ApiExecutionRole]",
    "Effect: Allow",
]
for piece in required:
    if not has(piece):
        print("POLICY_MISSING")
        sys.exit(0)
if "*" in block:
    print("POLICY_WILDCARD")
    sys.exit(0)
lowered = block.lower()
if "putsecretvalue" in lowered or "kms:" in lowered:
    print("POLICY_EXTRA_ACTION")
    sys.exit(0)
if block.count("Resource:") != 1:
    print("POLICY_EXTRA_RESOURCE")
    sys.exit(0)
if block.count("Action:") != 1:
    print("POLICY_EXTRA_ACTION")
    sys.exit(0)
if "Effect: Deny" in block:
    print("POLICY_DENY")
    sys.exit(0)
if "Facebook" in block or "FACEBOOK" in block:
    print("POLICY_FOREIGN_AUTH")
    sys.exit(0)
print("OK")
PYEOF
)" || POLICY_PROOF="UNREADABLE"
  POLICY_PROOF="$(printf '%s' "$POLICY_PROOF" | tr -d '[:space:]')"
  if [ "$POLICY_PROOF" != "OK" ]; then
    echo "refused: Google policy least privilege proof is $POLICY_PROOF, expected only GetSecretValue on the exact Google secret for the exact API execution role with no wildcard, no change made." >&2
    phase_failed "$POLICY_LABEL"
  fi
  echo "Verified Google policy least privilege: ApiGoogleAuthPolicy allows only GetSecretValue on the exact owned secret for the exact API execution role"
}

# Least privilege proof for the conditional Meta IAM policy, fail-closed
# before any infra mutation when a Meta key is configured. Reads the deployed
# template file and proves ApiMetaSecretPolicy carries exactly one Allow
# for secretsmanager:GetSecretValue on only the exact Meta secret ref,
# attached to only the exact ApiExecutionRole ref, with no wildcard, no
# extra action, no extra resource, and no KMS grant. Secret ownership plus
# CLI and file equality is already proven by the Meta gate before this
# runs. Any other shape refuses with no mutation.
verify_meta_policy_least_privilege() {
  META_POLICY_LABEL="${1:-infra}"
  META_POLICY_PROOF="$(python3 - "$TEMPLATE_FILE" 2>/dev/null <<'PYEOF'
import sys
path = sys.argv[1]
try:
    text = open(path, encoding="utf-8").read()
except Exception:
    print("TEMPLATE_UNREADABLE")
    sys.exit(0)
marker = "ApiMetaSecretPolicy:"
start = text.find(marker)
if start < 0:
    print("POLICY_ABSENT")
    sys.exit(0)
end = text.find("\n  ApiTaskDefinition:", start)
if end < 0:
    end = len(text)
block = text[start:end]
def has(piece):
    return piece in block
required = [
    "Type: AWS::IAM::Policy",
    "Condition: MetaKeyEnabled",
    "PolicyName: api-meta-secret-only",
    "Action: [secretsmanager:GetSecretValue]",
    "Resource: [!Ref MetaSecretArn]",
    "Roles: [!Ref ApiExecutionRole]",
    "Effect: Allow",
]
for piece in required:
    if not has(piece):
        print("POLICY_MISSING")
        sys.exit(0)
if "*" in block:
    print("POLICY_WILDCARD")
    sys.exit(0)
lowered = block.lower()
if "putsecretvalue" in lowered or "kms:" in lowered:
    print("POLICY_EXTRA_ACTION")
    sys.exit(0)
if block.count("Resource:") != 1:
    print("POLICY_EXTRA_RESOURCE")
    sys.exit(0)
if block.count("Action:") != 1:
    print("POLICY_EXTRA_ACTION")
    sys.exit(0)
if "Effect: Deny" in block:
    print("POLICY_DENY")
    sys.exit(0)
print("OK")
PYEOF
)" || META_POLICY_PROOF="UNREADABLE"
  META_POLICY_PROOF="$(printf '%s' "$META_POLICY_PROOF" | tr -d '[:space:]')"
  if [ "$META_POLICY_PROOF" != "OK" ]; then
    echo "refused: Meta policy least privilege proof is $META_POLICY_PROOF, expected only GetSecretValue on the exact Meta secret for the exact API execution role with no wildcard, no change made." >&2
    phase_failed "$META_POLICY_LABEL"
  fi
  echo "Verified Meta policy least privilege: ApiMetaSecretPolicy allows only GetSecretValue on the exact owned secret for the exact API execution role"
}

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

# Release generation for the head008 rollout. A new intentional release uses a
# distinct durable generation bound to the source Git SHA and the target DB
# head, plus the exact owned StackId, task definition, and config digest at
# launch time. Old one-shot journals are never deleted, renamed, or
# overwritten; the new generation uses a distinct active path and must
# enumerate and reconcile every prior-generation record to STOPPED with all
# essential exits 0 before any new launch. An empty new path never proves
# absence. The head008 generation name never collides with a head007 prior
# journal: prior head007 records reconcile as legitimate predecessors, with
# 004, 005, and 006 preserved as allowed historical predecessors.
resolve_release_generation() {
  if [ -n "$RELEASE_GEN" ]; then
    case "$RELEASE_GEN" in
      *[!A-Za-z0-9_.-]*) echo "refused: release generation has invalid characters: $RELEASE_GEN" >&2; exit 2 ;;
    esac
    case "$RELEASE_GEN" in
      *head008*|*008*) ;;
      *) echo "refused: release generation must name the target head008: $RELEASE_GEN" >&2; exit 2 ;;
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
  RELEASE_GEN="head008-$SHA_SHORT"
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

case "$PHASE" in
  infra|images|init|material|dbroles|migrate|enable|all) check_google_auth_gate "$PHASE" ;;
esac

case "$PHASE" in
  infra|images|init|material|dbroles|migrate|enable|all) check_meta_key_gate "$PHASE" ;;
esac

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

# Defined early: infra proves stopped before later helpers are parsed.
# Fail-closed ECS service stopped proof for quiesce and infra. Same owned
# identity resolution as enable, but requires ACTIVE desired 0 running 0
# pending 0. Used after the quiesce change set executes and before plus
# after any owned infra task definition update. Any mismatch refuses. The
# optional third argument names the failing phase, default quiesce.
verify_ecs_service_stopped() {
  STOP_LOGICAL="$1"
  STOP_SHORT="$2"
  STOP_LABEL="${3:-quiesce}"
  STOP_PHYSICAL=""
  if ! STOP_PHYSICAL="$(stack_resource "$STOP_LOGICAL" 2>"$TMP_ERR")"; then
    echo "service $STOP_SHORT owned identifier unreadable, not claimed stopped." >&2
    phase_failed "$STOP_LABEL"
  fi
  STOP_PHYSICAL="$(printf '%s' "$STOP_PHYSICAL" | tr -d '[:space:]')"
  [ -n "$STOP_PHYSICAL" ] && [ "$STOP_PHYSICAL" != "None" ] || { echo "refused: service $STOP_SHORT owned identifier missing, not claimed stopped." >&2; phase_failed "$STOP_LABEL"; }
  STOP_JSON="$(mktemp /tmp/launchcrew-svc-stop-XXXXXX)"
  if ! "$AWS_BIN" ecs describe-services --cluster "$CLUSTER_NAME" --services "$STOP_PHYSICAL" --region "$EXPECTED_REGION" --output json >"$STOP_JSON" 2>"$TMP_ERR"; then
    rm -f "$STOP_JSON"
    echo "service $STOP_SHORT counts unreadable, not claimed stopped." >&2
    phase_failed "$STOP_LABEL"
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
)" || { rm -f "$STOP_JSON"; echo "service $STOP_SHORT proof unreadable, not claimed stopped." >&2; phase_failed "$STOP_LABEL"; }
  rm -f "$STOP_JSON"
  STOP_PROOF="$(printf '%s' "$STOP_PROOF" | tr -d '[:space:]')"
  case "$STOP_PROOF" in
    OK)
      echo "Verified service $STOP_PHYSICAL desiredCount 0 runningCount 0 pendingCount 0 ACTIVE (stopped, not serving)" ;;
    *) echo "refused: service $STOP_SHORT proof is $STOP_PROOF, expected ACTIVE fixed 0/0/0 on owned identity" >&2; phase_failed "$STOP_LABEL" ;;
  esac
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
  INFRA_GOOGLE_ENABLE="$(params_file_value EnableGoogleAuth 2>/dev/null || true)"
  INFRA_GOOGLE_ENABLE="$(printf '%s' "$INFRA_GOOGLE_ENABLE" | tr -d '[:space:]')"
  [ -n "$INFRA_GOOGLE_ENABLE" ] || INFRA_GOOGLE_ENABLE="false"
  INFRA_GOOGLE_ARN="$(params_file_value GoogleOAuthSecretArn 2>/dev/null || true)"
  INFRA_GOOGLE_ARN="$(printf '%s' "$INFRA_GOOGLE_ARN" | tr -d '[:space:]')"
  case "$INFRA_GOOGLE_ENABLE" in
    true|false) ;;
    *) echo "refused: EnableGoogleAuth is $INFRA_GOOGLE_ENABLE, expected true or false, no change made" >&2; phase_failed infra ;;
  esac
  if [ "$INFRA_GOOGLE_ENABLE" = "true" ]; then
    [ -n "$GOOGLE_SECRET_ARN" ] || { echo "refused: EnableGoogleAuth true requires exact --google-secret-arn for infra staging, no change made" >&2; phase_failed infra; }
    [ "$INFRA_GOOGLE_ARN" = "$GOOGLE_SECRET_ARN" ] || { echo "refused: infra GoogleOAuthSecretArn does not equal the validated CLI value, no change made" >&2; phase_failed infra; }
    verify_google_policy_least_privilege infra
  else
    if [ -n "$GOOGLE_SECRET_ARN" ]; then
      echo "refused: --google-secret-arn requires EnableGoogleAuth true for infra staging, no change made" >&2
      phase_failed infra
    fi
  fi
  INFRA_META_ARN="$(params_file_value MetaSecretArn 2>/dev/null || true)"
  INFRA_META_ARN="$(printf '%s' "$INFRA_META_ARN" | tr -d '[:space:]')"
  if [ -n "$INFRA_META_ARN" ]; then
    case "$INFRA_META_ARN" in
      *REPLACE_WITH*|*PLACEHOLDER*)
        echo "refused: infra MetaSecretArn is a placeholder, replace with the exact owned Meta secret ARN, no change made" >&2
        phase_failed infra ;;
    esac
    [ -n "$META_SECRET_ARN" ] || { echo "refused: infra MetaSecretArn requires exact --meta-secret-arn for infra staging, no change made" >&2; phase_failed infra; }
    [ "$INFRA_META_ARN" = "$META_SECRET_ARN" ] || { echo "refused: infra MetaSecretArn does not equal the validated CLI value, no change made" >&2; phase_failed infra; }
    verify_meta_policy_least_privilege infra
  else
    if [ -n "$META_SECRET_ARN" ]; then
      echo "refused: --meta-secret-arn requires MetaSecretArn in the parameters file for infra staging, validating one secret while deploying another is refused" >&2
      phase_failed infra
    fi
  fi
  if [ "$WAS_NEW" -eq 1 ]; then
    echo "Infra: proving both owned services stopped before any task definition update."
    verify_ecs_service_stopped ApiService api infra
    verify_ecs_service_stopped WebService web infra
    INFRA_CHANGESET="infra-$TARGET_DB_HEAD"
    echo "Infra: reviewing a bounded update diff at services 0, then executing the same reviewed change set."
    if ! python3 - "$PARAMETERS_FILE" "$AWS_BIN" "$STACK_NAME" "$INFRA_CHANGESET" "$TEMPLATE_FILE" "$EXPECTED_REGION" <<'PYEOF'
import json, os, subprocess, sys
params_file, aws_bin, stack, changeset, template, region = sys.argv[1:7]
try:
    with open(params_file) as handle:
        doc = json.load(handle)
except Exception:
    raise SystemExit("parameters file is not valid JSON")
if isinstance(doc, dict) and "Parameters" in doc:
    doc = doc["Parameters"]
if not isinstance(doc, list):
    raise SystemExit("parameters file must be a JSON list")
params = []
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
    params.append("ParameterKey=%s,ParameterValue=%s" % (key, value))
params.append("ParameterKey=EnableServices,ParameterValue=false")
template_abs = os.path.abspath(template)
template_body = "file://" + template_abs
cmd = [aws_bin, "cloudformation", "create-change-set",
       "--stack-name", stack, "--change-set-name", changeset,
       "--change-set-type", "UPDATE", "--template-body", template_body,
       "--parameters"] + params + [
       "--capabilities", "CAPABILITY_NAMED_IAM",
       "--tags", "Key=Project,Value=LaunchCrew", "Key=Environment,Value=demo",
       "--region", region]
proc = subprocess.run(cmd, capture_output=True, text=True)
sys.exit(proc.returncode)
PYEOF
    then
      echo "refused: infra change set create failed; an existing same-name change set is never deleted or replaced, inspect $INFRA_CHANGESET manually after review. No change made." >&2
      phase_failed infra
    fi
    INFRA_PAGES_DIR="$(mktemp -d /tmp/launchcrew-infra-pages-XXXXXX)"
    INFRA_NEXT=""
    INFRA_PAGE_NUM=0
    while [ "$INFRA_PAGE_NUM" -lt 3 ]; do
      INFRA_PAGE_NUM=$((INFRA_PAGE_NUM + 1))
      INFRA_PAGE_FILE="$INFRA_PAGES_DIR/page-$INFRA_PAGE_NUM.json"
      INFRA_INPUT="$(mktemp /tmp/launchcrew-infra-in-XXXXXX)"
      if ! python3 - "$INFRA_INPUT" "$STACK_NAME" "$INFRA_CHANGESET" "$INFRA_NEXT" 2>/dev/null <<'PYEOF'
import json, sys
path, stack, changeset, token = sys.argv[1:5]
doc = {"StackName": stack, "ChangeSetName": changeset}
if token and token != "END" and token != "None":
    doc["NextToken"] = token
with open(path, "w", encoding="utf-8") as out:
    json.dump(doc, out)
PYEOF
      then
        rm -f "$INFRA_INPUT"
        rm -rf "$INFRA_PAGES_DIR"
        echo "refused: infra change set describe input failed, no change made. Pending change set $INFRA_CHANGESET preserved for inspection." >&2
        phase_failed infra
      fi
      if ! "$AWS_BIN" cloudformation describe-change-set --cli-input-json "file://$INFRA_INPUT" --no-paginate --region "$EXPECTED_REGION" --output json >"$INFRA_PAGE_FILE" 2>"$TMP_ERR"; then
        rm -f "$INFRA_INPUT"
        rm -rf "$INFRA_PAGES_DIR"
        echo "refused: infra change set $INFRA_CHANGESET unreadable, no change made. Pending change set preserved for inspection." >&2
        phase_failed infra
      fi
      rm -f "$INFRA_INPUT"
      INFRA_NEXT="$(python3 - "$INFRA_PAGE_FILE" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(doc, dict):
    print("MALFORMED")
    sys.exit(0)
if "nextToken" in doc:
    print("MALFORMED")
    sys.exit(0)
nxt = doc.get("NextToken", "")
if nxt is None or nxt == "None":
    nxt = ""
if not isinstance(nxt, str):
    print("MALFORMED")
    sys.exit(0)
print("END" if not nxt.strip() else nxt.strip())
PYEOF
)" || INFRA_NEXT="MALFORMED"
      INFRA_NEXT="$(printf '%s' "$INFRA_NEXT" | tr -d '[:space:]')"
      if [ "$INFRA_NEXT" = "MALFORMED" ]; then
        rm -rf "$INFRA_PAGES_DIR"
        echo "refused: infra change set page $INFRA_PAGE_NUM malformed, no change made. Pending change set $INFRA_CHANGESET preserved for inspection." >&2
        phase_failed infra
      fi
      if [ -z "$INFRA_NEXT" ] || [ "$INFRA_NEXT" = "END" ] || [ "$INFRA_NEXT" = "None" ]; then
        INFRA_NEXT=""
        break
      fi
    done
    if [ -n "$INFRA_NEXT" ]; then
      rm -rf "$INFRA_PAGES_DIR"
      echo "refused: infra change set has unreviewed pages after 3, no change made. Pending change set $INFRA_CHANGESET preserved for inspection." >&2
      phase_failed infra
    fi
    INFRA_RAW="$(python3 - "$INFRA_PAGES_DIR" "$STACK_NAME" "$STACK_ID" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$INFRA_CHANGESET" "$PARAMETERS_FILE" "$INFRA_GOOGLE_ENABLE" "$INFRA_GOOGLE_ARN" "$INFRA_META_ARN" 2>/dev/null <<'PYEOF'
import glob, json, os, sys
pages_dir, want_stack, want_id = sys.argv[1:4]
want_account, want_region, want_name, params_file = sys.argv[4:8]
google_enable = sys.argv[8] if len(sys.argv) > 8 else "false"
google_arn = sys.argv[9] if len(sys.argv) > 9 else ""
meta_arn = sys.argv[10] if len(sys.argv) > 10 else ""
pages = sorted(glob.glob(os.path.join(pages_dir, "page-*.json")))
if not pages:
    print("MALFORMED")
    sys.exit(0)
try:
    first = json.load(open(pages[0]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(first, dict):
    print("MALFORMED")
    sys.exit(0)
cs_id = first.get("ChangeSetId", "") or ""
if not isinstance(cs_id, str) or not cs_id.startswith(
        "arn:aws:cloudformation:%s:%s:changeSet/%s/" % (want_region, want_account, want_name)):
    print("ID_MISMATCH")
    sys.exit(0)
if (first.get("ChangeSetName", "") or "") != want_name:
    print("NAME_MISMATCH")
    sys.exit(0)
if (first.get("StackName", "") or "") != want_stack:
    print("STACK_MISMATCH")
    sys.exit(0)
if want_id and (first.get("StackId", "") or "") != want_id:
    print("STACKID_MISMATCH")
    sys.exit(0)
status = first.get("Status", "") or ""
reason = first.get("StatusReason", "") or ""
if status == "FAILED" and ("didn't contain changes" in reason or "No updates" in reason):
    print("NO_CHANGES")
    print("ID\t%s" % cs_id)
    sys.exit(0)
if status != "CREATE_COMPLETE":
    print("STATUS_%s" % (status or "EMPTY"))
    sys.exit(0)
if (first.get("ExecutionStatus", "") or "") != "AVAILABLE":
    print("EXEC_%s" % (first.get("ExecutionStatus", "") or "EMPTY"))
    sys.exit(0)
changes = []
for page_file in pages:
    try:
        page = json.load(open(page_file))
    except Exception:
        print("MALFORMED")
        sys.exit(0)
    if not isinstance(page, dict):
        print("MALFORMED")
        sys.exit(0)
    part = page.get("Changes", None)
    if not isinstance(part, list):
        print("MALFORMED")
        sys.exit(0)
    changes.extend(part)
    if len(changes) > 10:
        print("TOO_MANY_%d" % len(changes))
        sys.exit(0)
if len(changes) == 0:
    print("NO_CHANGES")
    print("ID\t%s" % cs_id)
    sys.exit(0)
TASKDEFS = {"ApiTaskDefinition", "WebTaskDefinition", "MigrationTaskDefinition",
            "BootstrapTaskDefinition", "VerifyTaskDefinition",
            "SdkInitTaskDefinition", "SdkMaterialTaskDefinition",
            "RoleStateTaskDefinition"}
SERVICES = {"ApiService", "WebService"}
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
    if logical == "ApiGoogleAuthPolicy":
        if google_enable != "true":
            print("GOOGLE_DISABLED")
            sys.exit(0)
        if not google_arn or "REPLACE_WITH" in google_arn or "PLACEHOLDER" in google_arn:
            print("GOOGLE_ARN_EMPTY")
            sys.exit(0)
        if not google_arn.startswith(
                "arn:aws:secretsmanager:%s:%s:secret:" % (want_region, want_account)):
            print("GOOGLE_ARN_FOREIGN")
            sys.exit(0)
        if logical in seen:
            print("DUPLICATE_%s" % logical)
            sys.exit(0)
        seen.add(logical)
        if action != "Add":
            print("ACTION_%s_%s" % (logical, action or "EMPTY"))
            sys.exit(0)
        if rtype != "AWS::IAM::Policy":
            print("TYPE_%s_%s" % (logical, rtype or "EMPTY"))
            sys.exit(0)
        if str(replacement) != "False":
            print("REPLACEMENT_%s_%s" % (logical, str(replacement)))
            sys.exit(0)
        scope = rc.get("Scope", None)
        if scope is not None:
            if not isinstance(scope, list):
                print("SCOPE_%s" % logical)
                sys.exit(0)
            if len(scope) == 0:
                pass
            elif scope != ["Properties"]:
                for item in scope:
                    if item != "Properties":
                        print("SCOPE_%s_%s" % (logical, str(item)))
                        sys.exit(0)
                print("SCOPE_%s" % logical)
                sys.exit(0)
        details = rc.get("Details", None)
        if not isinstance(details, list):
            print("DETAILS_%s_MALFORMED" % logical)
            sys.exit(0)
        if len(details) != 0:
            try:
                blob = json.dumps(details)
            except Exception:
                blob = ""
            if "*" in blob:
                print("WILDCARD_%s" % logical)
                sys.exit(0)
            print("DETAILS_%s_UNEXPECTED" % logical)
            sys.exit(0)
        continue
    if logical == "ApiMetaSecretPolicy":
        if not meta_arn or "REPLACE_WITH" in meta_arn or "PLACEHOLDER" in meta_arn:
            print("META_ARN_EMPTY")
            sys.exit(0)
        if not meta_arn.startswith(
                "arn:aws:secretsmanager:%s:%s:secret:" % (want_region, want_account)):
            print("META_ARN_FOREIGN")
            sys.exit(0)
        if logical in seen:
            print("DUPLICATE_%s" % logical)
            sys.exit(0)
        seen.add(logical)
        if action != "Add":
            print("ACTION_%s_%s" % (logical, action or "EMPTY"))
            sys.exit(0)
        if rtype != "AWS::IAM::Policy":
            print("TYPE_%s_%s" % (logical, rtype or "EMPTY"))
            sys.exit(0)
        if str(replacement) != "False":
            print("REPLACEMENT_%s_%s" % (logical, str(replacement)))
            sys.exit(0)
        scope = rc.get("Scope", None)
        if scope is not None:
            if not isinstance(scope, list):
                print("SCOPE_%s" % logical)
                sys.exit(0)
            if len(scope) == 0:
                pass
            elif scope != ["Properties"]:
                for item in scope:
                    if item != "Properties":
                        print("SCOPE_%s_%s" % (logical, str(item)))
                        sys.exit(0)
                print("SCOPE_%s" % logical)
                sys.exit(0)
        details = rc.get("Details", None)
        if not isinstance(details, list):
            print("DETAILS_%s_MALFORMED" % logical)
            sys.exit(0)
        if len(details) != 0:
            try:
                blob = json.dumps(details)
            except Exception:
                blob = ""
            if "*" in blob:
                print("WILDCARD_%s" % logical)
                sys.exit(0)
            print("DETAILS_%s_UNEXPECTED" % logical)
            sys.exit(0)
        continue
    if logical in TASKDEFS:
        want_type = "AWS::ECS::TaskDefinition"
    elif logical in SERVICES:
        want_type = "AWS::ECS::Service"
    else:
        print("FOREIGN_%s" % (logical or "EMPTY"))
        sys.exit(0)
    if logical in seen:
        print("DUPLICATE_%s" % logical)
        sys.exit(0)
    seen.add(logical)
    if action != "Modify":
        print("ACTION_%s_%s" % (logical, action or "EMPTY"))
        sys.exit(0)
    if rtype != want_type:
        print("TYPE_%s_%s" % (logical, rtype or "EMPTY"))
        sys.exit(0)
    replacement = str(replacement)
    if logical in TASKDEFS:
        if replacement not in ("True", "False"):
            print("REPLACEMENT_%s_%s" % (logical, replacement))
            sys.exit(0)
    else:
        if replacement != "False":
            print("REPLACEMENT_%s_%s" % (logical, replacement))
            sys.exit(0)
    scope = rc.get("Scope", None)
    if scope is not None:
        if not isinstance(scope, list) or not scope:
            print("SCOPE_%s" % logical)
            sys.exit(0)
        for item in scope:
            if item != "Properties":
                print("SCOPE_%s_%s" % (logical, str(item)))
                sys.exit(0)
    details = rc.get("Details", None)
    if not isinstance(details, list) or not details:
        print("DETAILS_%s_MISSING" % logical)
        sys.exit(0)
    if len(details) > 10:
        print("DETAILS_%s_MANY" % logical)
        sys.exit(0)
    for detail in details:
        if not isinstance(detail, dict):
            print("DETAILS_%s_MALFORMED" % logical)
            sys.exit(0)
        target = detail.get("Target", None)
        if not isinstance(target, dict):
            print("DETAILS_%s_MALFORMED" % logical)
            sys.exit(0)
        attr = target.get("Attribute", "") or ""
        name = target.get("Name", "") or ""
        recre = target.get("RequiresRecreation", "") or ""
        if attr != "Properties":
            print("DETAIL_%s_ATTR_%s" % (logical, attr or "EMPTY"))
            sys.exit(0)
        if logical in TASKDEFS:
            if name != "ContainerDefinitions":
                print("DETAIL_%s_NAME_%s" % (logical, name or "EMPTY"))
                sys.exit(0)
            want_recre = "Always" if replacement == "True" else "Never"
            if recre != want_recre:
                print("DETAIL_%s_RECRE_%s" % (logical, recre or "EMPTY"))
                sys.exit(0)
        else:
            if name != "TaskDefinition":
                print("DETAIL_%s_NAME_%s" % (logical, name or "EMPTY"))
                sys.exit(0)
            if recre != "Never":
                print("DETAIL_%s_RECRE_%s" % (logical, recre or "EMPTY"))
                sys.exit(0)
try:
    with open(params_file) as handle:
        doc = json.load(handle)
except Exception:
    print("PARAMS_FILE")
    sys.exit(0)
if isinstance(doc, dict) and "Parameters" in doc:
    doc = doc["Parameters"]
if not isinstance(doc, list):
    print("PARAMS_FILE")
    sys.exit(0)
expected = {}
for item in doc:
    if not isinstance(item, dict) or "ParameterKey" not in item:
        print("PARAMS_FILE")
        sys.exit(0)
    key = item["ParameterKey"]
    if key == "EnableServices":
        continue
    if key in ("BudgetLimitUsd", "BudgetNotifyEmail"):
        print("PARAMS_BUDGET_KEY")
        sys.exit(0)
    value = item.get("ParameterValue", None)
    if not isinstance(value, str):
        print("PARAMS_FILE")
        sys.exit(0)
    expected[key] = value
expected["EnableServices"] = "false"
if google_enable == "true":
    if expected.get("EnableGoogleAuth", "") != "true":
        print("PARAMS_GOOGLE_ENABLE")
        sys.exit(0)
    if expected.get("GoogleOAuthSecretArn", "") != google_arn:
        print("PARAMS_GOOGLE_ARN")
        sys.exit(0)
if meta_arn:
    if expected.get("MetaSecretArn", "") != meta_arn:
        print("PARAMS_META_ARN")
        sys.exit(0)
if len(expected) > 20:
    print("PARAMS_MANY")
    sys.exit(0)
got_params = first.get("Parameters", None)
if not isinstance(got_params, list):
    print("PARAMS_MISSING")
    sys.exit(0)
seen_params = set()
for item in got_params:
    if not isinstance(item, dict):
        print("PARAMS_MALFORMED")
        sys.exit(0)
    key = item.get("ParameterKey", "") or ""
    if not key or key in seen_params:
        print("PARAMS_DUP_%s" % (key or "EMPTY"))
        sys.exit(0)
    seen_params.add(key)
    if key not in expected:
        print("PARAMS_FOREIGN_%s" % key)
        sys.exit(0)
    if item.get("UsePreviousValue", False):
        print("PARAMS_PREVIOUS_%s" % key)
        sys.exit(0)
    if (item.get("ParameterValue", "") or "") != expected[key]:
        print("PARAMS_VALUE_%s" % key)
        sys.exit(0)
if seen_params != set(expected):
    print("PARAMS_INCOMPLETE")
    sys.exit(0)
tags = first.get("Tags", None)
if not isinstance(tags, list):
    print("TAGS_MISSING")
    sys.exit(0)
pairs = set()
for item in tags:
    if not isinstance(item, dict):
        print("TAGS_MALFORMED")
        sys.exit(0)
    pairs.add(((item.get("Key", "") or ""), (item.get("Value", "") or "")))
if pairs != {("Project", "LaunchCrew"), ("Environment", "demo")}:
    print("TAGS_MISMATCH")
    sys.exit(0)
caps = first.get("Capabilities", None)
if not isinstance(caps, list) or "CAPABILITY_NAMED_IAM" not in caps:
    print("CAPABILITIES")
    sys.exit(0)
print("OK")
print("ID\t%s" % cs_id)
PYEOF
)" || INFRA_RAW="UNREADABLE"
    INFRA_REVIEW="$(printf '%s\n' "$INFRA_RAW" | head -n 1 | tr -d '[:space:]')"
    if [ "$INFRA_REVIEW" = "NO_CHANGES" ]; then
      INFRA_NOCHANGE_ID="$(printf '%s\n' "$INFRA_RAW" | awk -F'\t' '$1=="ID"{print $2}' | tr -d '[:space:]')"
      rm -rf "$INFRA_PAGES_DIR"
      if [ -n "$INFRA_NOCHANGE_ID" ] && "$AWS_BIN" cloudformation delete-change-set --stack-name "$STACK_NAME" --change-set-name "$INFRA_NOCHANGE_ID" --region "$EXPECTED_REGION" >/dev/null 2>&1; then
        echo "Infra: review reports no updates, stack already current at services 0, self-created no-change set removed by reviewed ID, no execute made."
      else
        echo "Infra: review reports no updates, stack already current at services 0, no execute made. Remove $INFRA_CHANGESET manually after review if a rerun reports it exists."
      fi
    elif [ "$INFRA_REVIEW" != "OK" ]; then
      rm -rf "$INFRA_PAGES_DIR"
      echo "refused: infra review proof is $INFRA_REVIEW, expected only owned task definition image or service taskdef Modify with taskdef-only replacement plus optional exact ApiGoogleAuthPolicy Add only when Google explicitly enabled and optional exact ApiMetaSecretPolicy Add only when MetaSecretArn is set, each with least privilege proof, and no DB, network, cert, or other secrets change. Pending change set $INFRA_CHANGESET preserved for inspection, no execute made, no delete made." >&2
      phase_failed infra
    else
      INFRA_CHANGESET_ID="$(printf '%s\n' "$INFRA_RAW" | awk -F'\t' '$1=="ID"{print $2}')"
      INFRA_CHANGESET_ID="$(printf '%s' "$INFRA_CHANGESET_ID" | tr -d '[:space:]')"
      rm -rf "$INFRA_PAGES_DIR"
      [ -n "$INFRA_CHANGESET_ID" ] || { echo "refused: infra reviewed change set ID missing, no execute made." >&2; phase_failed infra; }
      echo "Infra: review passed, executing the same reviewed change set ID."
      if ! "$AWS_BIN" cloudformation execute-change-set --stack-name "$STACK_NAME" --change-set-name "$INFRA_CHANGESET_ID" --region "$EXPECTED_REGION" >/dev/null 2>"$TMP_ERR"; then
        echo "refused: infra execute failed, state unknown, verify stack status before any retry" >&2; phase_failed infra
      fi
      if ! "$AWS_BIN" cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
        ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
        if is_auth_error "$ERR"; then
          echo "infra wait authorization failure, state unknown, no later phase started." >&2
          phase_failed infra
        fi
        echo "infra wait reported, verifying stack status before any claim." >&2
      fi
      require_stack_complete infra
    fi
    echo "Infra: proving both owned services still stopped after the update."
    verify_ecs_service_stopped ApiService api infra
    verify_ecs_service_stopped WebService web infra
    if [ "$INFRA_GOOGLE_ENABLE" = "true" ]; then
      INFRA_POLICY_PHYSICAL=""
      if ! INFRA_POLICY_PHYSICAL="$(stack_resource ApiGoogleAuthPolicy 2>"$TMP_ERR")"; then
        echo "refused: infra Google policy missing after update, expected exact ApiGoogleAuthPolicy, no later phase started." >&2
        phase_failed infra
      fi
      INFRA_POLICY_PHYSICAL="$(printf '%s' "$INFRA_POLICY_PHYSICAL" | tr -d '[:space:]')"
      [ -n "$INFRA_POLICY_PHYSICAL" ] && [ "$INFRA_POLICY_PHYSICAL" != "None" ] || { echo "refused: infra Google policy physical ID missing after update, no later phase started." >&2; phase_failed infra; }
      echo "Verified infra Google policy present: ApiGoogleAuthPolicy"
    else
      if INFRA_POLICY_PHYSICAL="$(stack_resource ApiGoogleAuthPolicy 2>/dev/null)"; then
        INFRA_POLICY_PHYSICAL="$(printf '%s' "$INFRA_POLICY_PHYSICAL" | tr -d '[:space:]')"
        if [ -n "$INFRA_POLICY_PHYSICAL" ] && [ "$INFRA_POLICY_PHYSICAL" != "None" ]; then
          echo "refused: infra Google policy present while EnableGoogleAuth false, expected absent, no later phase started." >&2
          phase_failed infra
        fi
      fi
    fi
    if [ -n "$INFRA_META_ARN" ]; then
      INFRA_META_PHYSICAL=""
      if ! INFRA_META_PHYSICAL="$(stack_resource ApiMetaSecretPolicy 2>"$TMP_ERR")"; then
        echo "refused: infra Meta policy missing after update, expected exact ApiMetaSecretPolicy, no later phase started." >&2
        phase_failed infra
      fi
      INFRA_META_PHYSICAL="$(printf '%s' "$INFRA_META_PHYSICAL" | tr -d '[:space:]')"
      [ -n "$INFRA_META_PHYSICAL" ] && [ "$INFRA_META_PHYSICAL" != "None" ] || { echo "refused: infra Meta policy physical ID missing after update, no later phase started." >&2; phase_failed infra; }
      echo "Verified infra Meta policy present: ApiMetaSecretPolicy"
    else
      if INFRA_META_PHYSICAL="$(stack_resource ApiMetaSecretPolicy 2>/dev/null)"; then
        INFRA_META_PHYSICAL="$(printf '%s' "$INFRA_META_PHYSICAL" | tr -d '[:space:]')"
        if [ -n "$INFRA_META_PHYSICAL" ] && [ "$INFRA_META_PHYSICAL" != "None" ]; then
          echo "refused: infra Meta policy present while MetaSecretArn empty, expected absent, no later phase started." >&2
          phase_failed infra
        fi
      fi
    fi
  fi
  if [ "$WAS_NEW" -eq 0 ]; then
    if ! cloudformation_deploy "$TARGET_SERVICES" infra; then
      echo "infra deploy failed, no later phase started." >&2
      phase_failed infra
    fi
    if ! "$AWS_BIN" cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
      echo "infra create wait reported, verifying stack status before any claim." >&2
    fi
    require_stack_complete infra
    if [ "$INFRA_GOOGLE_ENABLE" = "true" ]; then
      INFRA_POLICY_PHYSICAL=""
      if ! INFRA_POLICY_PHYSICAL="$(stack_resource ApiGoogleAuthPolicy 2>"$TMP_ERR")"; then
        echo "refused: infra Google policy missing after create, expected exact ApiGoogleAuthPolicy, no later phase started." >&2
        phase_failed infra
      fi
      INFRA_POLICY_PHYSICAL="$(printf '%s' "$INFRA_POLICY_PHYSICAL" | tr -d '[:space:]')"
      [ -n "$INFRA_POLICY_PHYSICAL" ] && [ "$INFRA_POLICY_PHYSICAL" != "None" ] || { echo "refused: infra Google policy physical ID missing after create, no later phase started." >&2; phase_failed infra; }
      echo "Verified infra Google policy present: ApiGoogleAuthPolicy"
    else
      if INFRA_POLICY_PHYSICAL="$(stack_resource ApiGoogleAuthPolicy 2>/dev/null)"; then
        INFRA_POLICY_PHYSICAL="$(printf '%s' "$INFRA_POLICY_PHYSICAL" | tr -d '[:space:]')"
        if [ -n "$INFRA_POLICY_PHYSICAL" ] && [ "$INFRA_POLICY_PHYSICAL" != "None" ]; then
          echo "refused: infra Google policy present while EnableGoogleAuth false, expected absent, no later phase started." >&2
          phase_failed infra
        fi
      fi
    fi
    if [ -n "$INFRA_META_ARN" ]; then
      INFRA_META_PHYSICAL=""
      if ! INFRA_META_PHYSICAL="$(stack_resource ApiMetaSecretPolicy 2>"$TMP_ERR")"; then
        echo "refused: infra Meta policy missing after create, expected exact ApiMetaSecretPolicy, no later phase started." >&2
        phase_failed infra
      fi
      INFRA_META_PHYSICAL="$(printf '%s' "$INFRA_META_PHYSICAL" | tr -d '[:space:]')"
      [ -n "$INFRA_META_PHYSICAL" ] && [ "$INFRA_META_PHYSICAL" != "None" ] || { echo "refused: infra Meta policy physical ID missing after create, no later phase started." >&2; phase_failed infra; }
      echo "Verified infra Meta policy present: ApiMetaSecretPolicy"
    else
      if INFRA_META_PHYSICAL="$(stack_resource ApiMetaSecretPolicy 2>/dev/null)"; then
        INFRA_META_PHYSICAL="$(printf '%s' "$INFRA_META_PHYSICAL" | tr -d '[:space:]')"
        if [ -n "$INFRA_META_PHYSICAL" ] && [ "$INFRA_META_PHYSICAL" != "None" ]; then
          echo "refused: infra Meta policy present while MetaSecretArn empty, expected absent, no later phase started." >&2
          phase_failed infra
        fi
      fi
    fi
  fi
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

# Require the owned role-state task definition to carry the exact
# read-only job shape before any RunTask: exactly one essential
# bootstrap-db-roles container with the verified bootstrap image, default
# binder EntryPoint with exact Command --verify-role-state, exact required
# unique metadata env with no extras, exact two unique secrets (runtime plus
# migration URLs, no master) with no extras, the exact owned physical
# execution and task roles, and the exact owned physical task definition
# ARN. Extra, duplicate, or malformed containers, secrets, or env entries
# fail here before any RunTask, including on journal replay. Sets
# RS_CHECKED_ARN to the resolved ARN that was proven, so callers can assert
# check-versus-use equality before RunTask. Least privilege with no master
# secret is proven here plus the fargate template.
check_rolestate_taskdef() {
  RS_LOGICAL="RoleStateTaskDefinition"
  RS_EXEC_LOGICAL="RoleStateExecutionRole"
  RS_TASK_LOGICAL="RoleStateTaskRole"
  RS_CHECKED_ARN=""
  if ! RS_EXEC_ARN="$(resolve_role_arn "$RS_EXEC_LOGICAL")"; then
    echo "$RS_LOGICAL owned execution role unresolvable, job not proven owned." >&2
    phase_failed "$PHASE"
  fi
  if ! RS_TASK_ARN="$(resolve_role_arn "$RS_TASK_LOGICAL")"; then
    echo "$RS_LOGICAL owned task role unresolvable, job not proven owned." >&2
    phase_failed "$PHASE"
  fi
  if ! RS_DB_HOST="$(owned_db_endpoint)"; then
    echo "$RS_LOGICAL owned database endpoint unreadable, job not proven owned." >&2
    phase_failed "$PHASE"
  fi
  if ! RS_MASTER_USER="$(params_file_value DatabaseUsername)"; then
    echo "$RS_LOGICAL master username missing from parameters file, job not proven owned." >&2
    phase_failed "$PHASE"
  fi
  RS_MASTER_USER="$(printf '%s' "$RS_MASTER_USER" | tr -d '[:space:]')"
  RS_JSON="$(mktemp /tmp/launchcrew-rolestate-XXXXXX)"
  if ! fetch_taskdef_json "$RS_LOGICAL" "$RS_JSON"; then
    rm -f "$RS_JSON"
    echo "$RS_LOGICAL task definition missing, job not tied to an owned task." >&2
    phase_failed "$PHASE"
  fi
  RS_CHECKED_ARN="$(printf '%s' "${FETCH_ARN:-}" | tr -d '[:space:]')"
  if [ -z "$RS_CHECKED_ARN" ] || [ "$RS_CHECKED_ARN" = "None" ]; then
    rm -f "$RS_JSON"
    echo "$RS_LOGICAL task definition ARN missing, job not tied to an owned task." >&2
    phase_failed "$PHASE"
  fi
  case "$RS_CHECKED_ARN" in
    "arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:task""-definition/"*) ;;
    *) rm -f "$RS_JSON"
      echo "refused: $RS_LOGICAL task definition ARN is not owned, job not proven owned." >&2
      phase_failed "$PHASE" ;;
  esac
  RS_PROOF="$(python3 - "$RS_JSON" "$BOOTSTRAP_IMAGE" "$RS_EXEC_ARN" "$RS_TASK_ARN" "$RUNTIME_SECRET_ARN" "$MIGRATION_SECRET_ARN" "$RS_DB_HOST" "$RS_MASTER_USER" "$RS_CHECKED_ARN" 2>/dev/null <<'PYEOF'
import json, sys
(doc_file, want_image, want_exec, want_task,
 want_rt, want_mg, want_host, want_master,
 want_taskdef_arn) = sys.argv[1:10]
try:
    doc = json.load(open(doc_file))
except Exception:
    sys.exit(1)
taskdef = doc.get("taskDefinition", doc)
if not isinstance(taskdef, dict):
    print("TASKDEF_MALFORMED")
    sys.exit(0)
if (taskdef.get("taskDefinitionArn", "") or "") != want_taskdef_arn:
    print("TASKDEF_ARN_MISMATCH")
    sys.exit(0)
if (taskdef.get("executionRoleArn", "") or "") != want_exec:
    print("EXEC_ROLE_MISMATCH")
    sys.exit(0)
if (taskdef.get("taskRoleArn", "") or "") != want_task:
    print("TASK_ROLE_MISMATCH")
    sys.exit(0)
containers = taskdef.get("containerDefinitions", None)
if not isinstance(containers, list):
    print("CONTAINER_MALFORMED")
    sys.exit(0)
if len(containers) != 1:
    print("CONTAINER_COUNT_MISMATCH")
    sys.exit(0)
target = containers[0]
if not isinstance(target, dict):
    print("CONTAINER_MALFORMED")
    sys.exit(0)
if (target.get("name", "") or "") != "bootstrap-db-roles":
    print("CONTAINER_NAME_MISMATCH")
    sys.exit(0)
if target.get("essential", None) is not True:
    print("ESSENTIAL_MISMATCH")
    sys.exit(0)
if (target.get("image", "") or "") != want_image:
    print("IMAGE_MISMATCH")
    sys.exit(0)
if target.get("entryPoint", None):
    print("ENTRYPOINT_MISMATCH")
    sys.exit(0)
if (target.get("command", None) or []) != ["--verify-role-state"]:
    print("COMMAND_MISMATCH")
    sys.exit(0)
raw_secrets = target.get("secrets", None)
if not isinstance(raw_secrets, list):
    print("SECRET_MALFORMED")
    sys.exit(0)
if len(raw_secrets) != 2:
    print("SECRET_COUNT_MISMATCH")
    sys.exit(0)
actual = {}
for secret in raw_secrets:
    if not isinstance(secret, dict):
        print("SECRET_MALFORMED")
        sys.exit(0)
    sname = secret.get("name", None)
    sfrom = secret.get("valueFrom", None)
    if not isinstance(sname, str) or not sname:
        print("SECRET_MALFORMED")
        sys.exit(0)
    if not isinstance(sfrom, str) or not sfrom:
        print("SECRET_MALFORMED")
        sys.exit(0)
    if sname in actual:
        print("SECRET_DUPLICATE:" + sname)
        sys.exit(0)
    actual[sname] = sfrom
want = {
    "RUNTIME_DB_URL": "%s:database-url::" % want_rt,
    "MIGRATION_DB_URL": "%s:database-url::" % want_mg,
}
for key in sorted(want):
    if key not in actual:
        print("MISSING:" + key)
        sys.exit(0)
    if actual[key] != want[key]:
        print("SECRET_MISMATCH:" + key)
        sys.exit(0)
for key in sorted(actual):
    if key not in want:
        print("UNEXPECTED:" + key)
        sys.exit(0)
if "MASTER_DB_PASSWORD" in actual:
    print("MASTER_REFUSED")
    sys.exit(0)
raw_env = target.get("environment", None)
if not isinstance(raw_env, list):
    print("ENV_MALFORMED")
    sys.exit(0)
want_env = {
    "LAUNCHCREW_DB_TLS_MODE": "verify-full",
    "DATABASE_SSL_ROOTCERT": "/app/rds-ca-bundle.pem",
    "DB_NAME": "launchcrew",
    "DB_MASTER_USER": want_master,
    "DB_HOST": want_host,
    "APP_SCHEMA": "public",
    "RUNTIME_USER": "launchcrew_runtime",
    "MIGRATION_USER": "launchcrew_migration",
}
if len(raw_env) != len(want_env):
    print("ENV_COUNT_MISMATCH")
    sys.exit(0)
env = {}
for item in raw_env:
    if not isinstance(item, dict):
        print("ENV_MALFORMED")
        sys.exit(0)
    ename = item.get("name", None)
    evalue = item.get("value", None)
    if not isinstance(ename, str) or not ename:
        print("ENV_MALFORMED")
        sys.exit(0)
    if not isinstance(evalue, str):
        print("ENV_MALFORMED")
        sys.exit(0)
    if ename in env:
        print("ENV_DUPLICATE:" + ename)
        sys.exit(0)
    env[ename] = evalue
for key in sorted(want_env):
    if key not in env:
        print("ENV_MISMATCH:" + key)
        sys.exit(0)
    if env[key] != want_env[key]:
        print("ENV_MISMATCH:" + key)
        sys.exit(0)
for key in sorted(env):
    if key not in want_env:
        print("ENV_UNEXPECTED:" + key)
        sys.exit(0)
print("OK")
PYEOF
)" || { rm -f "$RS_JSON"; echo "$RS_LOGICAL task definition unreadable, not treated as matching." >&2; phase_failed "$PHASE"; }
  rm -f "$RS_JSON"
  RS_PROOF="$(printf '%s' "$RS_PROOF" | tr -d '[:space:]')"
  case "$RS_PROOF" in
    OK) echo "Verified owned role-state task definition one essential container, image, Command, exact env with no extras, two secrets with no master, roles, physical ARN: $RS_LOGICAL" ;;
    *) echo "refused: $RS_LOGICAL task definition proof is $RS_PROOF, job not proven owned." >&2; phase_failed "$PHASE" ;;
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

# Verify a historical image from an aged original task definition. Same owned
# account, region, repository, explicit tag, no latest, digest present with no
# failures as verify_image, but the URI must be digest-pinned (tag@sha256:...)
# and is never required to equal the current CLI image. The original
# journal/taskdef/source binding is proven separately via the exact original
# ARN plus config digest; this proves only the image itself is owned immutable.
# Wrong repo, unpinned, moved digest, missing digest, or ECR failures refuse.
# Returns 0 on success, 1 on failure with TASKDEF_OPERATION_MISMATCH:IMAGE
# text for typed recovery callers. Never prints the full URI.
verify_historical_image() {
  HIST_IMAGE="$1"
  HIST_EXPECTED_REPO="$2"
  HIST_LABEL="$3"
  case "$HIST_IMAGE" in
    *REPLACE_WITH*|*PLACEHOLDER*|"") echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_PLACEHOLDER, historical image is placeholder or missing, no recovery claimed." >&2; return 1 ;;
  esac
  case "$HIST_IMAGE" in
    *@sha256:*) HIST_PINNED="sha256:$(printf '%s' "$HIST_IMAGE" | sed 's/^.*@sha256://')"
      HIST_BASE="$(printf '%s' "$HIST_IMAGE" | cut -d@ -f1)" ;;
    *) echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_UNPINNED, tag-only historical image refused, no recovery claimed." >&2; return 1 ;;
  esac
  HIST_PINNED="$(printf '%s' "$HIST_PINNED" | tr -d '[:space:]')"
  HIST_BASE="$(printf '%s' "$HIST_BASE" | tr -d '[:space:]')"
  [ -n "$HIST_PINNED" ] && [ "$HIST_PINNED" != "sha256:" ] && [ "$HIST_PINNED" != "None" ] || { echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_UNPINNED, historical pinned digest missing, no recovery claimed." >&2; return 1; }
  case "$HIST_BASE" in
    *:* ) ;;
    *) echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_TAG, historical image has no explicit tag, no recovery claimed." >&2; return 1 ;;
  esac
  case "$HIST_BASE" in
    *:latest) echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_LATEST, historical image uses floating latest tag, no recovery claimed." >&2; return 1 ;;
  esac
  HIST_REPO_FULL="$(printf '%s' "$HIST_BASE" | cut -d/ -f2-)"
  HIST_REPO_NAME="$(printf '%s' "$HIST_REPO_FULL" | cut -d: -f1)"
  HIST_IMAGE_TAG="$(printf '%s' "$HIST_REPO_FULL" | cut -s -d: -f2)"
  [ -n "$HIST_IMAGE_TAG" ] || { echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_TAG, historical image has no explicit tag, no recovery claimed." >&2; return 1; }
  [ "$HIST_REPO_NAME" = "$HIST_EXPECTED_REPO" ] || { echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_REPO, historical repository $HIST_REPO_NAME is not owned $HIST_EXPECTED_REPO, no recovery claimed." >&2; return 1; }
  HIST_IMAGE_ACCOUNT="$(printf '%s' "$HIST_BASE" | cut -d. -f1)"
  HIST_IMAGE_REGION="$(printf '%s' "$HIST_BASE" | cut -d. -f4)"
  [ "$HIST_IMAGE_ACCOUNT" = "$EXPECTED_ACCOUNT" ] || { echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_ACCOUNT, historical image account does not match expected, no recovery claimed." >&2; return 1; }
  [ "$HIST_IMAGE_REGION" = "$EXPECTED_REGION" ] || { echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_REGION, historical image region does not match expected, no recovery claimed." >&2; return 1; }
  if ! HIST_DIGEST="$("$AWS_BIN" ecr batch-get-image --repository-name "$HIST_REPO_NAME" --image-ids "imageTag=$HIST_IMAGE_TAG" --region "$EXPECTED_REGION" --query "images[0].imageId.imageDigest" --output text 2>"$TMP_ERR")"; then
    echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_MISSING, historical image $HIST_REPO_NAME:$HIST_IMAGE_TAG not found in ECR, no recovery claimed." >&2
    return 1
  fi
  HIST_DIGEST="$(printf '%s' "$HIST_DIGEST" | tr -d '[:space:]')"
  if [ -z "$HIST_DIGEST" ] || [ "$HIST_DIGEST" = "None" ]; then
    echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_DIGEST, historical image $HIST_REPO_NAME:$HIST_IMAGE_TAG has no digest in ECR, no recovery claimed." >&2
    return 1
  fi
  if [ "$HIST_DIGEST" != "$HIST_PINNED" ]; then
    echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_MOVED, historical pinned digest does not match ECR digest, no recovery claimed." >&2
    return 1
  fi
  if ! HIST_FAILURES="$("$AWS_BIN" ecr batch-get-image --repository-name "$HIST_REPO_NAME" --image-ids "imageTag=$HIST_IMAGE_TAG" --region "$EXPECTED_REGION" --query "length(failures)" --output text 2>"$TMP_ERR")"; then
    echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_FAILURES, historical image $HIST_REPO_NAME:$HIST_IMAGE_TAG failure check failed, no recovery claimed." >&2
    return 1
  fi
  HIST_FAILURES="$(printf '%s' "$HIST_FAILURES" | tr -d '[:space:]')"
  [ "$HIST_FAILURES" = "0" ] || { echo "refused: original $HIST_LABEL operation proof is TASKDEF_OPERATION_MISMATCH:IMAGE_HISTORICAL_FAILURES, historical image $HIST_REPO_NAME:$HIST_IMAGE_TAG reports ECR failures, no recovery claimed." >&2; return 1; }
  echo "Verified historical image present with digest: $HIST_REPO_NAME:$HIST_IMAGE_TAG"
  return 0
}

# API task definition binding with Google plus Meta shape awareness. Reads
# EnableGoogleAuth and MetaSecretArn from the parameters file being deployed.
# Google true proves the five secret Google shape with exact owned Google
# client ID plus secret refs. A set MetaSecretArn adds the exact owned Meta
# key ref on top of either shape. Both empty proves the keyless three secret
# shape. No secret value appears here, only ARNs plus key names. Called in
# images plus enable before any boot.
check_api_taskdef_binding() {
  API_BIND_LABEL="${1:-images}"
  API_BIND_ENABLE="$(params_file_value EnableGoogleAuth 2>/dev/null || true)"
  API_BIND_ENABLE="$(printf '%s' "$API_BIND_ENABLE" | tr -d '[:space:]')"
  if [ -z "$API_BIND_ENABLE" ]; then API_BIND_ENABLE="false"; fi
  API_BIND_META="$(params_file_value MetaSecretArn 2>/dev/null || true)"
  API_BIND_META="$(printf '%s' "$API_BIND_META" | tr -d '[:space:]')"
  if [ -n "$API_BIND_META" ]; then
    [ -n "$META_SECRET_ARN" ] || { echo "refused: MetaSecretArn is set, exact --meta-secret-arn is required for API binding proof" >&2; phase_failed "$API_BIND_LABEL"; }
    [ "$API_BIND_META" = "$META_SECRET_ARN" ] || { echo "refused: API binding MetaSecretArn does not equal the validated CLI value, no change made" >&2; phase_failed "$API_BIND_LABEL"; }
  else
    if [ -n "$META_SECRET_ARN" ]; then
      echo "refused: --meta-secret-arn requires MetaSecretArn in the parameters file for API binding proof, no change made" >&2
      phase_failed "$API_BIND_LABEL"
    fi
  fi
  API_BIND_EXTRA=""
  if [ -n "$API_BIND_META" ]; then
    API_BIND_EXTRA="api.META_API_KEY=$META_SECRET_ARN:meta-api-key::"
  fi
  if [ "$API_BIND_ENABLE" = "true" ]; then
    [ -n "$GOOGLE_SECRET_ARN" ] || { echo "refused: EnableGoogleAuth true requires exact --google-secret-arn for API binding proof" >&2; phase_failed "$API_BIND_LABEL"; }
    if [ -n "$API_BIND_EXTRA" ]; then
      check_taskdef_binding ApiTaskDefinition ApiExecutionRole ApiTaskRole \
        "api.DATABASE_URL=$RUNTIME_SECRET_ARN:database-url::" \
        "api.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
        "api.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::" \
        "api.GOOGLE_CLIENT_ID=$GOOGLE_SECRET_ARN:google-client-id::" \
        "api.GOOGLE_CLIENT_SECRET=$GOOGLE_SECRET_ARN:google-client-secret::" \
        "$API_BIND_EXTRA"
    else
      check_taskdef_binding ApiTaskDefinition ApiExecutionRole ApiTaskRole \
        "api.DATABASE_URL=$RUNTIME_SECRET_ARN:database-url::" \
        "api.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
        "api.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::" \
        "api.GOOGLE_CLIENT_ID=$GOOGLE_SECRET_ARN:google-client-id::" \
        "api.GOOGLE_CLIENT_SECRET=$GOOGLE_SECRET_ARN:google-client-secret::"
    fi
  else
    if [ -n "$API_BIND_EXTRA" ]; then
      check_taskdef_binding ApiTaskDefinition ApiExecutionRole ApiTaskRole \
        "api.DATABASE_URL=$RUNTIME_SECRET_ARN:database-url::" \
        "api.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
        "api.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::" \
        "$API_BIND_EXTRA"
    else
      check_taskdef_binding ApiTaskDefinition ApiExecutionRole ApiTaskRole \
        "api.DATABASE_URL=$RUNTIME_SECRET_ARN:database-url::" \
        "api.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
        "api.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::"
    fi
  fi
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
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap RoleStateTaskDefinition bootstrap-db-roles bootstrap-rolestate
  check_api_taskdef_binding images
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
  (umask 077; python3 - "$JOURNAL_PATH" "$STACK_NAME" "$TASK_PHASE" "$TASK_LABEL" "$TASKDEF_LOGICAL" "$TASKDEF_ARN" "$CLUSTER_NAME" "$CLIENT_TOKEN" "$EXPECTED_REGION" "$EXPECTED_ACCOUNT" "$JOURNAL_OUTCOME" "$JOURNAL_TASK" "${CONFIG_DIGEST:-}" "${RELEASE_GEN:-}" "${SOURCE_SHA:-}" "${TARGET_DB_HEAD:-008}" "${STACK_ID:-}" "${PREDECESSOR_TASK:-}" "${PREDECESSOR_OUTCOME:-none}" <<'PYEOF'
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

# Enumerate and validate every other owned journal record for this exact
# stack, phase, and label, under the operation lock. A different source SHA
# or an accepted --release-generation uses a new empty active path, which
# never proves absence of prior work: each prior-generation active or
# archived record must be owned, well-formed, complete, and terminally
# re-proven STOPPED with every required essential container exit 0 before
# any new release work. Versioned predecessors must name an allowed head
# (004, 005, 006, 007, or current 008) explicitly via headXXX or a delimited
# token, match the filename generation exactly, and carry a recomputed
# config digest. Head 007 is a legitimate predecessor of the 008 rollout;
# 004, 005, and 006 stay allowed as historical predecessors. Unknown,
# future, or mismatched heads still refuse with no new launch.
# Same-generation archives from read-only rechecks are field validated,
# must be complete, and are live re-proven exactly like prior generations:
# archive-time proof never substitutes for current ECS terminal proof. Unknown,
# ambiguous, malformed, foreign, conflicting, or over-bound records fail
# closed with no new launch and no automatic resend. Every old record is
# preserved; nothing here deletes, renames, or overwrites history. Requires
# the usual task globals plus ACTIVE_FILE and LEGACY_ACTIVE_FILE set. Fails
# closed via phase_failed on any mismatch. Aged sdk-init COMPLETE priors
# with NO_TASK attest via recovery but never return early: the loop sets
# RECOVERED_AGED_PRIOR_INIT and continues to validate every remaining
# foreign, ambiguous, or pending record before any short-circuit.
reconcile_prior_generations() {
  PRIOR_LIST="$(mktemp /tmp/launchcrew-prior-list-XXXXXX)"
  PRIOR_ENUM="$(python3 - "$LAUNCH_JOURNAL_DIR" "$STACK_NAME" "$TASK_PHASE" "$TASK_LABEL" "$(basename "$ACTIVE_FILE")" "$(basename "$LEGACY_ACTIVE_FILE")" "$PRIOR_LIST" 2>/dev/null <<'PYEOF'
import os, re, sys
directory, stack, phase, label = sys.argv[1:5]
active_base, legacy_base, out_path = sys.argv[5:8]
prefix = "launchcrew-%s-%s-%s-" % (stack, phase, label)
base = "launchcrew-" + re.escape(stack) + "-" + re.escape(phase) + "-" + re.escape(label)
active_re = re.compile(r"^" + base + r"-([A-Za-z0-9_.-]+)-active\.json$")
archive_re = re.compile(r"^" + base + r"-([A-Za-z0-9_.-]+)-complete-(lc-[A-Za-z0-9]{30})\.json$")
try:
    names = sorted(os.listdir(directory))
except Exception:
    print("PROOF\tLIST_FAILED")
    sys.exit(0)
found = []
for name in names:
    if not name.startswith(prefix) or not name.endswith(".json"):
        continue
    if name == active_base or name == legacy_base:
        continue
    if not active_re.match(name) and not archive_re.match(name):
        print("PROOF\tUNKNOWN_FILE")
        print("FILE\t%s" % name)
        sys.exit(0)
    found.append(name)
    if len(found) > 32:
        print("PROOF\tTOO_MANY")
        sys.exit(0)
try:
    with open(out_path, "w", encoding="utf-8") as out:
        for name in found:
            out.write(name + "\n")
except Exception:
    print("PROOF\tLIST_FAILED")
    sys.exit(0)
print("PROOF\tOK")
print("COUNT\t%d" % len(found))
PYEOF
)" || PRIOR_ENUM="PROOF\tLIST_FAILED"
  PRIOR_ENUM_PROOF="$(printf '%s\n' "$PRIOR_ENUM" | awk -F'\t' '$1=="PROOF"{print $2}')"
  PRIOR_ENUM_PROOF="$(printf '%s' "$PRIOR_ENUM_PROOF" | tr -d '[:space:]')"
  if [ "$PRIOR_ENUM_PROOF" != "OK" ]; then
    PRIOR_ENUM_FILE="$(printf '%s\n' "$PRIOR_ENUM" | awk -F'\t' '$1=="FILE"{print $2}')"
    rm -f "$PRIOR_LIST"
    echo "refused: $TASK_LABEL prior journal enumeration is $PRIOR_ENUM_PROOF ${PRIOR_ENUM_FILE:-}, preserved with no new launch and no overwrite. Inspect $LAUNCH_JOURNAL_DIR." >&2
    phase_failed "$TASK_PHASE"
  fi
  PRIOR_ENUM_COUNT="$(printf '%s\n' "$PRIOR_ENUM" | awk -F'\t' '$1=="COUNT"{print $2}')"
  PRIOR_ENUM_COUNT="$(printf '%s' "$PRIOR_ENUM_COUNT" | tr -d '[:space:]')"
  if [ -z "$PRIOR_ENUM_COUNT" ] || [ "$PRIOR_ENUM_COUNT" = "0" ]; then
    rm -f "$PRIOR_LIST"
    return 0
  fi
  while IFS= read -r PRIOR_BASE || [ -n "$PRIOR_BASE" ]; do
    [ -n "$PRIOR_BASE" ] || continue
    PRIOR_PATH="$LAUNCH_JOURNAL_DIR/$PRIOR_BASE"
    PRIOR_PARSED="$(python3 - "$PRIOR_PATH" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$TASK_PHASE" "$TASK_LABEL" "$TASKDEF_LOGICAL" "$TARGET_DB_HEAD" "${STACK_ID:-}" "$PRIOR_BASE" 2>/dev/null <<'PYEOF'
import hashlib, json, os, re, sys
(path, want_account, want_region, want_stack, want_cluster,
 want_phase, want_label, want_logical, want_head,
 want_stack_id, want_file_base) = sys.argv[1:13]
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
for _k, _v in doc.items():
    if _k == "version":
        if not isinstance(_v, int) or isinstance(_v, bool):
            print("PROOF\tMALFORMED")
            sys.exit(0)
        continue
    if not isinstance(_v, str):
        print("PROOF\tMALFORMED")
        sys.exit(0)
for _k, _v in doc.items():
    _kl = str(_k).lower()
    if _kl in ("password", "database-url", "database_url",
               "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
               "secret_value", "secretvalue", "private_key", "privatekey",
               "certificate_body", "certificate_chain"):
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
    if isinstance(_v, str):
        _vl = _v.lower()
        if "://" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "password" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
checks = (("account", want_account), ("region", want_region),
          ("stack", want_stack), ("cluster", want_cluster),
          ("phase", want_phase), ("label", want_label),
          ("taskdef_logical", want_logical))
for field, want in checks:
    if doc.get(field, "") != want:
        print("PROOF\t%s_MISMATCH" % field.upper())
        sys.exit(0)
gen = doc.get("release_generation", "")
if not isinstance(gen, str) or not gen:
    print("PROOF\tGENERATION_MISSING")
    sys.exit(0)
for char in gen:
    if char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-":
        print("PROOF\tGENERATION_MALFORMED")
        sys.exit(0)
try:
    base_esc = "launchcrew-" + re.escape(want_stack) + "-" + re.escape(want_phase) + "-" + re.escape(want_label)
    active_re = re.compile(r"^" + base_esc + r"-([A-Za-z0-9_.-]+)-active\.json$")
    archive_re = re.compile(r"^" + base_esc + r"-([A-Za-z0-9_.-]+)-complete-(lc-[A-Za-z0-9]{30})\.json$")
    file_gen = None
    m = active_re.match(want_file_base or "")
    if m:
        file_gen = m.group(1)
    else:
        m2 = archive_re.match(want_file_base or "")
        if m2:
            file_gen = m2.group(1)
except Exception:
    file_gen = None
if not file_gen or file_gen != gen:
    print("PROOF\tGENERATION_FILENAME_MISMATCH")
    sys.exit(0)
head = doc.get("target_head", "")
allowed_heads = {"004", "005", "006", "007", want_head}
if not isinstance(head, str) or head not in allowed_heads:
    print("PROOF\tHEAD_UNKNOWN")
    sys.exit(0)
named = set()
for found in re.findall(r"head(\d{3})", gen):
    named.add(found)
for tok in re.split(r"[-_.]", gen):
    if re.fullmatch(r"\d{3}", tok or ""):
        named.add(tok)
if len(named) == 0:
    print("PROOF\tGENERATION_FOREIGN")
    sys.exit(0)
if len(named) != 1:
    print("PROOF\tGENERATION_AMBIGUOUS")
    sys.exit(0)
if next(iter(named)) != head:
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
allowed_prior = ("complete", "started") if (want_phase == "dbroles" and want_label == "bootstrap") else ("complete",)
if outcome not in allowed_prior:
    print("PROOF\tUNRESOLVED")
    print("OUTCOME\t%s" % (outcome if isinstance(outcome, str) and outcome else "MISSING"))
    sys.exit(0)
task_arn = doc.get("task_arn", "")
if not isinstance(task_arn, str) or not task_arn.startswith(
        "arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
    print("PROOF\tTASKARN_FOREIGN")
    sys.exit(0)
taskdef_arn = doc.get("taskdef_arn", "")
if not isinstance(taskdef_arn, str) or not taskdef_arn.startswith(
        "arn:aws:ecs:%s:%s:task" "-definition/" % (want_region, want_account)):
    print("PROOF\tTASKDEF_FOREIGN")
    sys.exit(0)
try:
    rec_digest = doc.get("config_digest", "")
    raw = "|".join([
        doc.get("account", ""), doc.get("region", ""),
        doc.get("stack", ""), doc.get("cluster", ""),
        doc.get("phase", ""), doc.get("label", ""),
        doc.get("taskdef_logical", ""), doc.get("taskdef_arn", ""),
    ])
    expect_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    if not isinstance(rec_digest, str) or rec_digest != expect_digest:
        print("PROOF\tCONFIG_MISMATCH")
        sys.exit(0)
except Exception:
    print("PROOF\tCONFIG_MISMATCH")
    sys.exit(0)
print("PROOF\tOK")
print("TOKEN\t%s" % token)
print("TASKARN\t%s" % task_arn)
print("TASKDEF\t%s" % taskdef_arn)
print("GEN\t%s" % gen)
print("OUTCOME\t%s" % outcome)
PYEOF
)" || PRIOR_PARSED="PROOF\tUNREADABLE"
    PRIOR_PROOF="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="PROOF"{print $2}')"
    PRIOR_PROOF="$(printf '%s' "$PRIOR_PROOF" | tr -d '[:space:]')"
    PRIOR_OUTCOME="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
    if [ "$PRIOR_PROOF" != "OK" ]; then
      rm -f "$PRIOR_LIST"
      echo "refused: $TASK_LABEL prior record $PRIOR_BASE is $PRIOR_PROOF ${PRIOR_OUTCOME:-}, preserved with no new launch and no overwrite. Inspect $PRIOR_PATH." >&2
      phase_failed "$TASK_PHASE"
    fi
    PRIOR_TOKEN="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="TOKEN"{print $2}' | tr -d '[:space:]')"
    PRIOR_TASK="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="TASKARN"{print $2}' | tr -d '[:space:]')"
    PRIOR_TASKDEF="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="TASKDEF"{print $2}' | tr -d '[:space:]')"
    PRIOR_GEN="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="GEN"{print $2}' | tr -d '[:space:]')"
    PRIOR_JOURNAL_OUTCOME="$(printf '%s\n' "$PRIOR_PARSED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
    PRIOR_DESC="$(mktemp /tmp/launchcrew-prior-desc-XXXXXX)"
    if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$PRIOR_TASK" --region "$EXPECTED_REGION" --output json >"$PRIOR_DESC" 2>"$TMP_ERR"; then
      rm -f "$PRIOR_DESC" "$PRIOR_LIST"
      echo "refused: $TASK_LABEL prior $PRIOR_GEN predecessor terminal state unreadable, no new launch. Inspect $PRIOR_PATH." >&2
      phase_failed "$TASK_PHASE"
    fi
    PRIOR_DEF_JSON="$(mktemp /tmp/launchcrew-prior-def-XXXXXX)"
    if ! "$AWS_BIN" ecs "describe-task""-definition" --task"-definition" "$PRIOR_TASKDEF" --region "$EXPECTED_REGION" --output json >"$PRIOR_DEF_JSON" 2>"$TMP_ERR"; then
      rm -f "$PRIOR_DESC" "$PRIOR_DEF_JSON" "$PRIOR_LIST"
      echo "refused: $TASK_LABEL prior $PRIOR_GEN predecessor taskdef unreadable, no new launch. Inspect $PRIOR_PATH." >&2
      phase_failed "$TASK_PHASE"
    fi
    PRIOR_CHECK="$(python3 - "$PRIOR_DESC" "$PRIOR_DEF_JSON" "$PRIOR_TASK" "$PRIOR_TASKDEF" "arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME" "$PRIOR_TOKEN" 2>/dev/null <<'PYEOF'
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
)" || PRIOR_CHECK="UNREADABLE"
    rm -f "$PRIOR_DESC" "$PRIOR_DEF_JSON"
    PRIOR_CHECK="$(printf '%s' "$PRIOR_CHECK" | tr -d '[:space:]')"
    if [ "$PRIOR_CHECK" != "OK" ]; then
      if [ "$PRIOR_CHECK" = "NO_TASK" ] && [ "$TASK_LABEL" = "sdk-init" ] && [ "$TASK_PHASE" = "init" ]; then
        echo "$TASK_LABEL prior $PRIOR_GEN aged out NO_TASK, requiring recovery attestation before new $RELEASE_GEN launch."
        attest_aged_init_recovery "$TASK_PHASE" "$PRIOR_PATH" "$PRIOR_BASE"
        echo "$TASK_LABEL prior $PRIOR_GEN recovered via attestation, desired-state equivalence for new $RELEASE_GEN, not retroactive proof. Preserved at $PRIOR_PATH."
        RECOVERED_AGED_PRIOR_INIT=1
      elif [ "$PRIOR_CHECK" = "NO_TASK" ] && [ "$TASK_LABEL" = "sdk-material" ] && [ "$TASK_PHASE" = "material" ]; then
        echo "$TASK_LABEL prior $PRIOR_GEN aged out NO_TASK, requiring recovery attestation before new $RELEASE_GEN launch."
        attest_aged_typed_recovery "$TASK_PHASE" "$PRIOR_PATH" "$PRIOR_BASE" "material" "sdk-material" "SdkMaterialTaskDefinition" "material-recovery-attestation" "SdkMaterialTaskDefinition" "sdk-material" "0" "0"
        echo "$TASK_LABEL prior $PRIOR_GEN recovered via attestation, desired-state equivalence for new $RELEASE_GEN, not retroactive proof. Preserved at $PRIOR_PATH."
        RECOVERED_AGED_PRIOR_MATERIAL=1
      elif [ "$PRIOR_CHECK" = "NO_TASK" ] && [ "$TASK_LABEL" = "bootstrap" ] && [ "$TASK_PHASE" = "dbroles" ]; then
        echo "$TASK_LABEL prior $PRIOR_GEN aged out NO_TASK, requiring recovery attestation before new $RELEASE_GEN launch."
        attest_aged_typed_recovery "$TASK_PHASE" "$PRIOR_PATH" "$PRIOR_BASE" "dbroles" "bootstrap" "BootstrapTaskDefinition" "dbroles-recovery-attestation" "RoleStateTaskDefinition" "bootstrap-db-roles" "1" "1"
        echo "$TASK_LABEL prior $PRIOR_GEN recovered via attestation, desired-state equivalence for new $RELEASE_GEN, not retroactive proof and never a binder rerun. Preserved at $PRIOR_PATH."
        RECOVERED_AGED_PRIOR_DBROLES=1
      elif [ "$PRIOR_CHECK" = "NO_TASK" ] && [ "$TASK_LABEL" = "migration" ] && [ "$TASK_PHASE" = "migrate" ]; then
        echo "$TASK_LABEL prior $PRIOR_GEN aged out NO_TASK, requiring recovery attestation before new $RELEASE_GEN launch."
        attest_aged_typed_recovery "$TASK_PHASE" "$PRIOR_PATH" "$PRIOR_BASE" "migrate" "migration" "MigrationTaskDefinition" "migration-recovery-attestation" "RoleStateTaskDefinition" "bootstrap-db-roles" "0" "1"
        echo "$TASK_LABEL prior $PRIOR_GEN recovered via attestation, desired-state equivalence for new $RELEASE_GEN, not retroactive proof. Preserved at $PRIOR_PATH."
        RECOVERED_AGED_PRIOR_MIGRATION=1
      elif [ "$PRIOR_CHECK" = "NO_TASK" ] && [ "$TASK_LABEL" = "verify" ] && [ "$TASK_PHASE" = "migrate" ]; then
        echo "$TASK_LABEL prior $PRIOR_GEN aged out NO_TASK, requiring recovery attestation before new $RELEASE_GEN launch."
        attest_aged_typed_recovery "$TASK_PHASE" "$PRIOR_PATH" "$PRIOR_BASE" "migrate" "verify" "VerifyTaskDefinition" "runtime-recovery-attestation" "VerifyTaskDefinition" "bootstrap-db-roles" "0" "0"
        echo "$TASK_LABEL prior $PRIOR_GEN recovered via attestation, desired-state equivalence for new $RELEASE_GEN, not retroactive proof. Preserved at $PRIOR_PATH."
        RECOVERED_AGED_PRIOR_VERIFY=1
      else
        rm -f "$PRIOR_LIST"
        echo "refused: $TASK_LABEL prior $PRIOR_GEN predecessor terminal proof is $PRIOR_CHECK, no new $RELEASE_GEN launch. Inspect $PRIOR_PATH." >&2
        phase_failed "$TASK_PHASE"
      fi
    else
      if [ "${PRIOR_JOURNAL_OUTCOME:-complete}" = "started" ]; then
        rm -f "$PRIOR_LIST"
        echo "refused: $TASK_LABEL prior $PRIOR_GEN is STARTED with live STOPPED task, historical ambiguity requires separately reviewed repair, no automatic binder rerun and no relabel. Inspect $PRIOR_PATH." >&2
        phase_failed "$TASK_PHASE"
      fi
      if [ "$PRIOR_GEN" = "$RELEASE_GEN" ]; then
        echo "$TASK_LABEL same-generation archive $PRIOR_BASE reconciled STOPPED exit 0, preserved at $PRIOR_PATH; new launch proceeds."
      else
        echo "$TASK_LABEL prior generation $PRIOR_GEN reconciled STOPPED exit 0, preserved at $PRIOR_PATH; new generation $RELEASE_GEN proceeds."
      fi
    fi
  done <"$PRIOR_LIST"
  rm -f "$PRIOR_LIST"
}

# Fail-closed recovery for an aged-out prior COMPLETE init journal.
# ECS DescribeTasks returns NO_TASK after retention expiry. A historical
# POPULATE COMPLETE log or current secret metadata alone never proves the
# historical terminal exit. This protocol never deletes, renames, rewrites,
# or treats the old journal as terminal proof, and never resends init,
# rotates material, PutSecretValue, ExportCertificate, DB role binding, or
# migration merely because ECS lost that task. Crash, restart, and ambiguous
# outcomes stay fail-closed with no automatic resend.
# Recovery is desired-state equivalence for proceeding, not retroactive proof
# that the old init exited successfully. It uses a separate durable
# recovery attestation with its own one-shot journal in a recovery subdir
# plus the existing isolated read-only material verifier with zero mutation
# permissions. Admission persists before any verifier RunTask with exact
# startedBy and token. Terminal proof derives essential names from live
# DescribeTaskDefinition, never inventing essential on DescribeTasks.
# Before any later mutating task, a bounded point-in-time gate for the old
# startedBy is required with startedBy-only plus desired STOPPED sweeps and
# recorded MISSING in two stable rounds; if AWS cannot support the proof,
# refuse. Fresh init resend is never permitted through this route. General NO_TASK
# is never success; only this init path with full attestation proceeds.
ensure_recovery_dir() {
  RECOVERY_DIR="$LAUNCH_JOURNAL_DIR/recovery"
  if [ -L "$RECOVERY_DIR" ]; then
    echo "recovery directory is a symlink, no recovery attempted. Inspect $RECOVERY_DIR." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  if [ ! -d "$RECOVERY_DIR" ]; then
    if ! (umask 077; mkdir -p "$RECOVERY_DIR" 2>/dev/null); then
      echo "recovery directory unwritable, no recovery attempted." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    chmod 700 "$RECOVERY_DIR" 2>/dev/null || {
      echo "recovery directory mode failed, no recovery attempted." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    }
  fi
  if ! python3 - "$RECOVERY_DIR" 2>/dev/null <<'PYEOF'
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
  then
    echo "recovery directory is not private mode 700 owned, no recovery attempted." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
}

acquire_recovery_lock() {
  RECOVERY_LOCK_BASE="$1"
  RECOVERY_LOCK_DIR="$LAUNCH_JOURNAL_DIR/recovery/$RECOVERY_LOCK_BASE.lock"
  RECOVERY_LOCK_OWNER_FILE="$RECOVERY_LOCK_DIR/owner"
  RECOVERY_LOCK_OWNED=0
  if [ -L "$RECOVERY_LOCK_DIR" ]; then
    echo "recovery lock is a symlink, no recovery attempted. Inspect $RECOVERY_LOCK_DIR." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  if [ -e "$RECOVERY_LOCK_DIR" ] && [ ! -d "$RECOVERY_LOCK_DIR" ]; then
    echo "recovery lock path exists as a file, no recovery attempted. Inspect $RECOVERY_LOCK_DIR." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  RECOVERY_ATTEMPTS=0
  while [ "$RECOVERY_ATTEMPTS" -lt 30 ]; do
    if mkdir "$RECOVERY_LOCK_DIR" 2>/dev/null; then
      if ! (umask 077; printf '%s' "$$" >"$RECOVERY_LOCK_OWNER_FILE" 2>/dev/null); then
        rmdir "$RECOVERY_LOCK_DIR" 2>/dev/null || true
        echo "recovery lock owner write failed, no recovery attempted." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}"
      fi
      chmod 600 "$RECOVERY_LOCK_OWNER_FILE" 2>/dev/null || true
      RECOVERY_LOCK_OWNED=1
      return 0
    fi
    if [ -d "$RECOVERY_LOCK_DIR" ]; then
      if [ -f "$RECOVERY_LOCK_OWNER_FILE" ]; then
        RECOVERY_PID="$(cat "$RECOVERY_LOCK_OWNER_FILE" 2>/dev/null | tr -d '[:space:]' || echo "")"
        case "$RECOVERY_PID" in
          ''|*[!0-9]*) RECOVERY_PID="" ;;
        esac
        if [ -n "$RECOVERY_PID" ]; then
          if kill -0 "$RECOVERY_PID" 2>/dev/null; then
            RECOVERY_ATTEMPTS=$((RECOVERY_ATTEMPTS + 1))
            sleep 1 2>/dev/null || sleep 1
            continue
          else
            echo "recovery lock is stale (owner $RECOVERY_PID dead), manual reconciliation required with no new verifier. Inspect $RECOVERY_LOCK_DIR." >&2
            phase_failed "${RECOVERY_FAIL_PHASE:-init}"
          fi
        else
          echo "recovery lock owner unreadable, no recovery attempted. Inspect $RECOVERY_LOCK_DIR." >&2
          phase_failed "${RECOVERY_FAIL_PHASE:-init}"
        fi
      else
        RECOVERY_ATTEMPTS=$((RECOVERY_ATTEMPTS + 1))
        sleep 1 2>/dev/null || sleep 1
        continue
      fi
    else
      RECOVERY_ATTEMPTS=$((RECOVERY_ATTEMPTS + 1))
      continue
    fi
  done
  echo "recovery lock held after bounded wait, no new verifier to avoid duplicate run-task. Rerun after holder completes. Inspect $RECOVERY_LOCK_DIR." >&2
  phase_failed "${RECOVERY_FAIL_PHASE:-init}"
}

sha256_of_file() {
  python3 - "$1" 2>/dev/null <<'PYEOF'
import hashlib, sys
try:
    with open(sys.argv[1], "rb") as handle:
        print(hashlib.sha256(handle.read()).hexdigest())
except Exception:
    sys.exit(1)
PYEOF
}

# Fetch exact owned secret identity read-only: Name, ARN, AWSCURRENT
# VersionId, Project and Environment tags. Metadata only, never a value.
# Args: secret ARN, label. Prints tab lines NAME, ARN, VERSION, PROJECT,
# ENV on success, or PROOF tab reason. Caller fails closed on mismatch.
fetch_secret_version_identity() {
  FETCH_SECRET_ARN="$1"
  FETCH_SECRET_LABEL="$2"
  FETCH_NAME=""
  FETCH_ARN=""
  FETCH_VERSION_JSON=""
  FETCH_PROJECT=""
  FETCH_ENV=""
  if ! FETCH_NAME="$("$AWS_BIN" secretsmanager describe-secret --secret-id "$FETCH_SECRET_ARN" --region "$EXPECTED_REGION" --query Name --output text 2>"$TMP_ERR")"; then
    printf 'PROOF\tSECRET_UNREADABLE\n'
    return 0
  fi
  if ! FETCH_ARN="$("$AWS_BIN" secretsmanager describe-secret --secret-id "$FETCH_SECRET_ARN" --region "$EXPECTED_REGION" --query ARN --output text 2>"$TMP_ERR")"; then
    printf 'PROOF\tSECRET_UNREADABLE\n'
    return 0
  fi
  FETCH_VERSION_JSON="$(mktemp /tmp/launchcrew-secrets-XXXXXX)"
  if ! "$AWS_BIN" secretsmanager describe-secret --secret-id "$FETCH_SECRET_ARN" --region "$EXPECTED_REGION" --query VersionIdsToStages --output json >"$FETCH_VERSION_JSON" 2>"$TMP_ERR"; then
    rm -f "$FETCH_VERSION_JSON"
    printf 'PROOF\tSECRET_UNREADABLE\n'
    return 0
  fi
  if ! FETCH_PROJECT="$("$AWS_BIN" secretsmanager describe-secret --secret-id "$FETCH_SECRET_ARN" --region "$EXPECTED_REGION" --query "Tags[?Key=='Project'].Value | [0]" --output text 2>"$TMP_ERR")"; then
    rm -f "$FETCH_VERSION_JSON"
    printf 'PROOF\tSECRET_UNREADABLE\n'
    return 0
  fi
  if ! FETCH_ENV="$("$AWS_BIN" secretsmanager describe-secret --secret-id "$FETCH_SECRET_ARN" --region "$EXPECTED_REGION" --query "Tags[?Key=='Environment'].Value | [0]" --output text 2>"$TMP_ERR")"; then
    rm -f "$FETCH_VERSION_JSON"
    printf 'PROOF\tSECRET_UNREADABLE\n'
    return 0
  fi
  FETCH_NAME="$(printf '%s' "$FETCH_NAME" | tr -d '[:space:]')"
  FETCH_ARN="$(printf '%s' "$FETCH_ARN" | tr -d '[:space:]')"
  FETCH_PROJECT="$(printf '%s' "$FETCH_PROJECT" | tr -d '[:space:]')"
  FETCH_ENV="$(printf '%s' "$FETCH_ENV" | tr -d '[:space:]')"
  FETCH_VERSION="$(python3 - "$FETCH_VERSION_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(doc, dict) or not doc:
    print("EMPTY")
    sys.exit(0)
current = []
for vid, stages in doc.items():
    if not isinstance(vid, str) or not vid:
        print("MALFORMED")
        sys.exit(0)
    if not isinstance(stages, list):
        print("MALFORMED")
        sys.exit(0)
    if "AWSCURRENT" in stages:
        current.append(vid)
if len(current) != 1:
    print("AMBIGUOUS")
    sys.exit(0)
print(current[0])
PYEOF
)"
  rm -f "$FETCH_VERSION_JSON"
  FETCH_VERSION="$(printf '%s' "$FETCH_VERSION" | tr -d '[:space:]')"
  case "$FETCH_VERSION" in
    ""|MALFORMED|EMPTY|AMBIGUOUS) printf 'PROOF\tVERSION_%s\n' "$FETCH_VERSION"; return 0 ;;
  esac
  if [ -z "$FETCH_NAME" ] || [ "$FETCH_NAME" = "None" ]; then printf 'PROOF\tNAME_MISSING\n'; return 0; fi
  if [ "$FETCH_ARN" != "$FETCH_SECRET_ARN" ]; then printf 'PROOF\tARN_MISMATCH\n'; return 0; fi
  if [ "$FETCH_PROJECT" != "LaunchCrew" ]; then printf 'PROOF\tPROJECT_MISMATCH\n'; return 0; fi
  if [ "$FETCH_ENV" != "demo" ]; then printf 'PROOF\tENV_MISMATCH\n'; return 0; fi
  printf 'PROOF\tOK\n'
  printf 'NAME\t%s\n' "$FETCH_NAME"
  printf 'ARN\t%s\n' "$FETCH_ARN"
  printf 'VERSION\t%s\n' "$FETCH_VERSION"
  printf 'PROJECT\t%s\n' "$FETCH_PROJECT"
  printf 'ENV\t%s\n' "$FETCH_ENV"
}

# Fetch exact owned certificate identity read-only: ARN, domain,
# serial, status, type, export, plus Project and Environment tags.
# Args: certificate ARN. Prints tab lines or PROOF reason.
fetch_cert_identity() {
  FETCH_CERT_ARN="$1"
  FETCH_CERT_JSON="$(mktemp /tmp/launchcrew-cert-XXXXXX)"
  if ! "$AWS_BIN" acm describe-certificate --certificate-arn "$FETCH_CERT_ARN" --region "$EXPECTED_REGION" --output json >"$FETCH_CERT_JSON" 2>"$TMP_ERR"; then
    rm -f "$FETCH_CERT_JSON"
    printf 'PROOF\tCERT_UNREADABLE\n'
    return 0
  fi
  FETCH_TAGS_JSON="$(mktemp /tmp/launchcrew-certtags-XXXXXX)"
  if ! "$AWS_BIN" acm list-tags-for-certificate --certificate-arn "$FETCH_CERT_ARN" --region "$EXPECTED_REGION" --output json >"$FETCH_TAGS_JSON" 2>"$TMP_ERR"; then
    rm -f "$FETCH_CERT_JSON" "$FETCH_TAGS_JSON"
    printf 'PROOF\tCERT_TAGS_UNREADABLE\n'
    return 0
  fi
  FETCH_CERT_PARSED="$(python3 - "$FETCH_CERT_JSON" "$FETCH_TAGS_JSON" "$FETCH_CERT_ARN" 2>/dev/null <<'PYEOF'
import json, sys
cert_file, tags_file, want_arn = sys.argv[1:4]
try:
    cert_doc = json.load(open(cert_file))
    tags_doc = json.load(open(tags_file))
except Exception:
    print("PROOF\tMALFORMED")
    sys.exit(0)
cert = cert_doc.get("Certificate", {}) if isinstance(cert_doc, dict) else {}
if not isinstance(cert, dict):
    print("PROOF\tMALFORMED")
    sys.exit(0)
arn = cert.get("CertificateArn", "") or ""
domain = cert.get("DomainName", "") or ""
status = cert.get("Status", "") or ""
ctype = cert.get("Type", "") or ""
serial = cert.get("Serial", "") or ""
opts = cert.get("Options", {}) or {}
export = opts.get("Export", "") or "" if isinstance(opts, dict) else ""
sans = cert.get("SubjectAlternativeNames", None)
if arn != want_arn:
    print("PROOF\tARN_MISMATCH")
    sys.exit(0)
if domain != "launchcrew.summitsingh.com":
    print("PROOF\tDOMAIN_MISMATCH")
    sys.exit(0)
if not isinstance(sans, list) or sans != ["launchcrew.summitsingh.com"]:
    print("PROOF\tSAN_MISMATCH")
    sys.exit(0)
if ctype != "AMAZON_ISSUED":
    print("PROOF\tTYPE_MISMATCH")
    sys.exit(0)
if export != "ENABLED":
    print("PROOF\tEXPORT_MISMATCH")
    sys.exit(0)
if status != "ISSUED":
    print("PROOF\tSTATUS_%s" % (status if isinstance(status, str) and status else "MISSING"))
    sys.exit(0)
if not isinstance(serial, str) or not serial:
    print("PROOF\tSERIAL_MISSING")
    sys.exit(0)
tags = tags_doc.get("Tags", None) if isinstance(tags_doc, dict) else None
if not isinstance(tags, list):
    print("PROOF\tTAGS_MALFORMED")
    sys.exit(0)
got = {}
for entry in tags:
    if isinstance(entry, dict) and entry.get("Key"):
        got[entry.get("Key")] = entry.get("Value", "")
if got.get("Project", "") != "LaunchCrew":
    print("PROOF\tPROJECT_MISMATCH")
    sys.exit(0)
if got.get("Environment", "") != "demo":
    print("PROOF\tENV_MISMATCH")
    sys.exit(0)
print("PROOF\tOK")
print("ARN\t%s" % arn)
print("DOMAIN\t%s" % domain)
print("SERIAL\t%s" % serial)
print("STATUS\t%s" % status)
print("TYPE\t%s" % ctype)
print("EXPORT\t%s" % export)
PYEOF
)"
  rm -f "$FETCH_CERT_JSON" "$FETCH_TAGS_JSON"
  printf '%s\n' "$FETCH_CERT_PARSED"
}

# Validate live owned stack identity for recovery: exact StackId plus
# Project LaunchCrew and Environment demo tags. Sets RECOVERY_STACK_ID,
# RECOVERY_PROJECT, RECOVERY_ENV. Fails closed via phase_failed.
validate_stack_for_recovery() {
  RECOVERY_STACK_JSON="$(mktemp /tmp/launchcrew-recstack-XXXXXX)"
  if ! "$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" --output json >"$RECOVERY_STACK_JSON" 2>"$TMP_ERR"; then
    rm -f "$RECOVERY_STACK_JSON"
    echo "recovery stack identity unreadable, no recovery claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  RECOVERY_STACK_PARSED="$(python3 - "$RECOVERY_STACK_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
stacks = doc.get("Stacks", [])
if len(stacks) != 1:
    print("PROOF\tCOUNT")
    sys.exit(0)
stack = stacks[0]
tags = {t.get("Key"): t.get("Value") for t in stack.get("Tags", []) if isinstance(t, dict)}
print("PROOF\tOK")
print("STACKID\t%s" % stack.get("StackId", ""))
print("PROJECT\t%s" % tags.get("Project", ""))
print("ENV\t%s" % tags.get("Environment", ""))
PYEOF
)" || {
    rm -f "$RECOVERY_STACK_JSON"
    echo "recovery stack identity unreadable, no recovery claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  }
  rm -f "$RECOVERY_STACK_JSON"
  RECOVERY_STACK_PROOF="$(printf '%s\n' "$RECOVERY_STACK_PARSED" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_STACK_PROOF" != "OK" ]; then
    echo "refused: recovery stack proof is $RECOVERY_STACK_PROOF, no recovery claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  RECOVERY_STACK_ID="$(printf '%s\n' "$RECOVERY_STACK_PARSED" | awk -F'\t' '$1=="STACKID"{print $2}' | tr -d '[:space:]')"
  RECOVERY_PROJECT="$(printf '%s\n' "$RECOVERY_STACK_PARSED" | awk -F'\t' '$1=="PROJECT"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ENV="$(printf '%s\n' "$RECOVERY_STACK_PARSED" | awk -F'\t' '$1=="ENV"{print $2}' | tr -d '[:space:]')"
  case "$RECOVERY_STACK_ID" in
    "arn:aws:cloudformation:$EXPECTED_REGION:$EXPECTED_ACCOUNT:"*) ;;
    *) echo "refused: recovery StackId is not owned, no recovery claimed." >&2; phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
  esac
  if [ -n "${STACK_ID:-}" ] && [ "$RECOVERY_STACK_ID" != "$STACK_ID" ]; then
    echo "refused: recovery StackId does not equal the owned StackId, no recovery claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  if [ "$RECOVERY_PROJECT" != "LaunchCrew" ]; then
    echo "refused: recovery Project tag is $RECOVERY_PROJECT, expected LaunchCrew, no recovery claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  if [ "$RECOVERY_ENV" != "demo" ]; then
    echo "refused: recovery Environment tag is $RECOVERY_ENV, expected demo, no recovery claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
}

# Write one private mode 600 recovery attestation atomically. Uses
# RECOVERY_* globals plus path and outcome args. Metadata only, never a
# secret value, URL, or key bytes. Includes original journal SHA256,
# exact current material identities, verifier proof, and a cryptographically
# bound one-shot terminal proof for durability after verifier retention.
# Legacy unversioned originals mark legacy_unversioned true and explain
# current desired-state equivalence, never historical exit, head, or StackId.
write_recovery_attestation() {
  RECOVERY_WRITE_PATH="$1"
  RECOVERY_WRITE_OUTCOME="$2"
  (umask 077; python3 - "$RECOVERY_WRITE_PATH" "$STACK_NAME" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$CLUSTER_NAME" \
    "${RECOVERY_ORIG_BASENAME:-}" "${RECOVERY_ORIG_SHA:-}" "${RECOVERY_ORIG_TOKEN:-}" "${RECOVERY_ORIG_TASK:-}" \
    "${RECOVERY_ORIG_TASKDEF:-}" "${RECOVERY_ORIG_GEN:-}" "${RECOVERY_ORIG_SOURCE:-}" "${RECOVERY_ORIG_HEAD:-}" \
    "${RECOVERY_ORIG_LEGACY:-false}" \
    "${RECOVERY_STACK_ID:-}" "${RECOVERY_PROJECT:-}" "${RECOVERY_ENV:-}" "${RELEASE_GEN:-}" "${SOURCE_SHA:-}" \
    "${TARGET_DB_HEAD:-008}" "${RECOVERY_RT_NAME:-}" "${RECOVERY_RT_ARN:-}" "${RECOVERY_RT_PRE:-}" "${RECOVERY_RT_POST:-}" \
    "${RECOVERY_MG_NAME:-}" "${RECOVERY_MG_ARN:-}" "${RECOVERY_MG_PRE:-}" "${RECOVERY_MG_POST:-}" \
    "${RECOVERY_TLS_NAME:-}" "${RECOVERY_TLS_ARN:-}" "${RECOVERY_TLS_PRE:-}" "${RECOVERY_TLS_POST:-}" \
    "${RECOVERY_CERT_ARN:-}" "${RECOVERY_CERT_DOMAIN:-}" "${RECOVERY_CERT_SERIAL_PRE:-}" "${RECOVERY_CERT_SERIAL_POST:-}" \
    "${RECOVERY_CERT_STATUS:-}" "${RECOVERY_CERT_TYPE:-}" "${RECOVERY_CERT_EXPORT:-}" \
    "${RECOVERY_VERIFIER_TOKEN:-}" "${RECOVERY_VERIFIER_TASK:-}" "${RECOVERY_VERIFIER_TASKDEF:-}" \
    "${RECOVERY_VERIFIER_PROOF:-}" "${RECOVERY_VERIFIER_CONTAINERS:-}" "${RECOVERY_VERIFIER_LAST_STATUS:-}" \
    "${RECOVERY_VERIFIER_DIGEST:-}" "${RECOVERY_ABSENCE_PROOF:-}" "$RECOVERY_WRITE_OUTCOME" <<'PYEOF'
import json, os, sys, tempfile
(path, stack, account, region, cluster,
 orig_base, orig_sha, orig_token, orig_task,
 orig_taskdef, orig_gen, orig_source, orig_head,
 orig_legacy,
 stack_id, project, env,
 release_gen, source_sha, target_head,
 rt_name, rt_arn, rt_pre, rt_post,
 mg_name, mg_arn, mg_pre, mg_post,
 tls_name, tls_arn, tls_pre, tls_post,
 cert_arn, cert_domain, cert_pre, cert_post,
 cert_status, cert_type, cert_export,
 verifier_token, verifier_task, verifier_taskdef,
 verifier_proof, verifier_containers, verifier_last_status,
 verifier_digest, absence_proof, outcome) = sys.argv[1:56]
if os.path.islink(path):
    raise SystemExit("refused: recovery path is a symlink")
try:
    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
except Exception:
    stamp = ""
if orig_legacy == "true":
    note_text = "legacy_unversioned desired-state equivalence for proceeding, proves current desired-state equivalence, not historical task exit, head, or StackId"
else:
    note_text = "desired-state equivalence for proceeding, not retroactive proof that the old init exited successfully"
doc = {
    "version": 1,
    "kind": "init-recovery-attestation",
    "stack": stack,
    "account": account,
    "region": region,
    "cluster": cluster,
    "original_basename": orig_base,
    "original_sha256": orig_sha,
    "original_token": orig_token,
    "original_task_arn": orig_task,
    "original_taskdef_arn": orig_taskdef,
    "original_generation": orig_gen,
    "original_source_sha": orig_source,
    "original_target_head": orig_head,
    "legacy_unversioned": orig_legacy,
    "stack_id": stack_id,
    "project": project,
    "environment": env,
    "release_generation": release_gen,
    "source_sha": source_sha,
    "target_head": target_head,
    "runtime_name": rt_name,
    "runtime_arn": rt_arn,
    "runtime_version_pre": rt_pre,
    "runtime_version_post": rt_post,
    "migration_name": mg_name,
    "migration_arn": mg_arn,
    "migration_version_pre": mg_pre,
    "migration_version_post": mg_post,
    "tls_name": tls_name,
    "tls_arn": tls_arn,
    "tls_version_pre": tls_pre,
    "tls_version_post": tls_post,
    "cert_arn": cert_arn,
    "cert_domain": cert_domain,
    "cert_serial_pre": cert_pre,
    "cert_serial_post": cert_post,
    "cert_status": cert_status,
    "cert_type": cert_type,
    "cert_export": cert_export,
    "verifier_token": verifier_token,
    "verifier_task_arn": verifier_task,
    "verifier_taskdef_arn": verifier_taskdef,
    "verifier_proof": verifier_proof,
    "verifier_containers": verifier_containers,
    "verifier_last_status": verifier_last_status,
    "verifier_digest": verifier_digest,
    "absence_proof": absence_proof,
    "outcome": outcome,
    "note": note_text,
    "updated_utc": stamp,
}
directory = os.path.dirname(os.path.abspath(path)) or "."
fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".recovery-")
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
) || {
    echo "recovery attestation write failed, no verifier claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  }
  chmod 600 "$RECOVERY_WRITE_PATH" 2>/dev/null || {
    echo "recovery attestation mode failed, no verifier claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  }
}

# Write one private mode 600 typed recovery attestation atomically. Uses
# RECOVERY_KIND plus RECOVERY_* globals plus path and outcome args. Metadata
# only, never a secret value, URL, or key bytes. Includes original journal
# SHA256 and outcome, exact current material identities, verifier proof,
# observed DB head, and a cryptographically bound one-shot terminal proof
# for durability after verifier retention. For a STARTED binder original the
# note states current-state equivalence and explicitly does not relabel the
# old STARTED job as completed. Legacy unversioned originals mark
# legacy_unversioned true and explain current desired-state equivalence,
# never historical exit, head, or StackId.
write_typed_recovery_attestation() {
  TYPED_WRITE_PATH="$1"
  TYPED_WRITE_OUTCOME="$2"
  (umask 077; python3 - "$TYPED_WRITE_PATH" "$STACK_NAME" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$CLUSTER_NAME" \
    "${RECOVERY_KIND:-}" \
    "${RECOVERY_ORIG_BASENAME:-}" "${RECOVERY_ORIG_SHA:-}" "${RECOVERY_ORIG_TOKEN:-}" "${RECOVERY_ORIG_TASK:-}" \
    "${RECOVERY_ORIG_TASKDEF:-}" "${RECOVERY_ORIG_GEN:-}" "${RECOVERY_ORIG_SOURCE:-}" "${RECOVERY_ORIG_HEAD:-}" \
    "${RECOVERY_ORIG_OUTCOME:-}" "${RECOVERY_ORIG_LEGACY:-false}" \
    "${RECOVERY_STACK_ID:-}" "${RECOVERY_PROJECT:-}" "${RECOVERY_ENV:-}" "${RELEASE_GEN:-}" "${SOURCE_SHA:-}" \
    "${TARGET_DB_HEAD:-008}" "${RECOVERY_RT_NAME:-}" "${RECOVERY_RT_ARN:-}" "${RECOVERY_RT_PRE:-}" "${RECOVERY_RT_POST:-}" \
    "${RECOVERY_MG_NAME:-}" "${RECOVERY_MG_ARN:-}" "${RECOVERY_MG_PRE:-}" "${RECOVERY_MG_POST:-}" \
    "${RECOVERY_TLS_NAME:-}" "${RECOVERY_TLS_ARN:-}" "${RECOVERY_TLS_PRE:-}" "${RECOVERY_TLS_POST:-}" \
    "${RECOVERY_CERT_ARN:-}" "${RECOVERY_CERT_DOMAIN:-}" "${RECOVERY_CERT_SERIAL_PRE:-}" "${RECOVERY_CERT_SERIAL_POST:-}" \
    "${RECOVERY_CERT_STATUS:-}" "${RECOVERY_CERT_TYPE:-}" "${RECOVERY_CERT_EXPORT:-}" \
    "${RECOVERY_VERIFIER_TOKEN:-}" "${RECOVERY_VERIFIER_TASK:-}" "${RECOVERY_VERIFIER_TASKDEF:-}" \
    "${RECOVERY_VERIFIER_PROOF:-}" "${RECOVERY_VERIFIER_CONTAINERS:-}" "${RECOVERY_VERIFIER_LAST_STATUS:-}" \
    "${RECOVERY_VERIFIER_DIGEST:-}" "${RECOVERY_ABSENCE_PROOF:-}" "${RECOVERY_OBSERVED_HEAD:-}" "$TYPED_WRITE_OUTCOME" <<'PYEOF'
import json, os, sys, tempfile
(path, stack, account, region, cluster,
 kind,
 orig_base, orig_sha, orig_token, orig_task,
 orig_taskdef, orig_gen, orig_source, orig_head,
 orig_outcome, orig_legacy,
 stack_id, project, env,
 release_gen, source_sha, target_head,
 rt_name, rt_arn, rt_pre, rt_post,
 mg_name, mg_arn, mg_pre, mg_post,
 tls_name, tls_arn, tls_pre, tls_post,
 cert_arn, cert_domain, cert_pre, cert_post,
 cert_status, cert_type, cert_export,
 verifier_token, verifier_task, verifier_taskdef,
 verifier_proof, verifier_containers, verifier_last_status,
 verifier_digest, absence_proof, observed_head, outcome) = sys.argv[1:60]
if os.path.islink(path):
    raise SystemExit("refused: recovery path is a symlink")
try:
    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
except Exception:
    stamp = ""
if orig_legacy == "true":
    note_text = "legacy_unversioned desired-state equivalence for proceeding, proves current desired-state equivalence, not historical task exit, head, or StackId"
elif orig_outcome == "started":
    note_text = "desired-state equivalence for proceeding, not retroactive proof that the old job succeeded; does not relabel old STARTED as completed"
else:
    note_text = "desired-state equivalence for proceeding, not retroactive proof that the old job exited successfully"
doc = {
    "version": 1,
    "kind": kind,
    "stack": stack,
    "account": account,
    "region": region,
    "cluster": cluster,
    "original_basename": orig_base,
    "original_sha256": orig_sha,
    "original_token": orig_token,
    "original_task_arn": orig_task,
    "original_taskdef_arn": orig_taskdef,
    "original_generation": orig_gen,
    "original_source_sha": orig_source,
    "original_target_head": orig_head,
    "original_outcome": orig_outcome,
    "legacy_unversioned": orig_legacy,
    "stack_id": stack_id,
    "project": project,
    "environment": env,
    "release_generation": release_gen,
    "source_sha": source_sha,
    "target_head": target_head,
    "runtime_name": rt_name,
    "runtime_arn": rt_arn,
    "runtime_version_pre": rt_pre,
    "runtime_version_post": rt_post,
    "migration_name": mg_name,
    "migration_arn": mg_arn,
    "migration_version_pre": mg_pre,
    "migration_version_post": mg_post,
    "tls_name": tls_name,
    "tls_arn": tls_arn,
    "tls_version_pre": tls_pre,
    "tls_version_post": tls_post,
    "cert_arn": cert_arn,
    "cert_domain": cert_domain,
    "cert_serial_pre": cert_pre,
    "cert_serial_post": cert_post,
    "cert_status": cert_status,
    "cert_type": cert_type,
    "cert_export": cert_export,
    "verifier_token": verifier_token,
    "verifier_task_arn": verifier_task,
    "verifier_taskdef_arn": verifier_taskdef,
    "verifier_proof": verifier_proof,
    "verifier_containers": verifier_containers,
    "verifier_last_status": verifier_last_status,
    "verifier_digest": verifier_digest,
    "absence_proof": absence_proof,
    "observed_head": observed_head,
    "outcome": outcome,
    "note": note_text,
    "updated_utc": stamp,
}
directory = os.path.dirname(os.path.abspath(path)) or "."
fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".recovery-")
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
) || {
    echo "recovery attestation write failed, no verifier claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  }
  chmod 600 "$TYPED_WRITE_PATH" 2>/dev/null || {
    echo "recovery attestation mode failed, no verifier claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  }
}

# Strict validation of an original init journal for recovery. Args: path,
# basename. Only outcome complete qualifies; pending, started, adopted,
# and every ambiguous outcome refuse with no recovery. Versioned records
# validate exact owned account, region, stack, cluster, phase init, label
# sdk-init, logical SdkInitTaskDefinition, generation, head, StackId,
# token, task ARN shape, taskdef ARN shape, and recomputed config digest.
# Exact legacy unversioned branch ONLY for the exact unversioned init active
# basename validates the 14-key legacy schema with version 1, COMPLETE,
# owned identity, token, task and taskdef ARNs, and recomputed digest. It
# never fabricates release_generation, source_sha, target_head, or stack_id
# and returns those empty with LEGACY true. Prints PROOF OK plus TOKEN,
# TASKARN, TASKDEF, GEN, SOURCE, HEAD, STACKID, LEGACY on success, else
# PROOF reason. Never writes the original.
validate_init_journal_for_recovery() {
  VALIDATE_PATH="$1"
  VALIDATE_BASE="$2"
  python3 - "$VALIDATE_PATH" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$TARGET_DB_HEAD" "${STACK_ID:-}" "$VALIDATE_BASE" 2>/dev/null <<'PYEOF'
import hashlib, json, os, re, sys
(path, want_account, want_region, want_stack, want_cluster,
 want_head, want_stack_id, want_base) = sys.argv[1:9]
try:
    if os.path.islink(path):
        print("PROOF\tSYMLINK")
        sys.exit(0)
    finfo = os.stat(path)
    if (finfo.st_mode & 0o777) != 0o600:
        print("PROOF\tMODE")
        sys.exit(0)
    if finfo.st_uid != os.getuid():
        print("PROOF\tOWNER")
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
try:
    if want_base and want_base not in ("active.json", "legacy"):
        if os.path.basename(path) != want_base:
            print("PROOF\tPATH_MISMATCH")
            sys.exit(0)
except Exception:
    print("PROOF\tPATH_MISMATCH")
    sys.exit(0)
legacy_base = "launchcrew-%s-init-sdk-init-active.json" % want_stack
if want_base == legacy_base:
    legacy_expected = {"account", "client_token", "cluster", "config_digest",
                       "label", "outcome", "phase", "region", "stack",
                       "task_arn", "taskdef_arn", "taskdef_logical",
                       "updated_utc", "version"}
    if set(doc.keys()) != legacy_expected:
        for _k in doc:
            if _k not in legacy_expected:
                print("PROOF\tFOREIGN_FIELD")
                sys.exit(0)
        print("PROOF\tLEGACY_KEYS_MISMATCH")
        sys.exit(0)
    if doc.get("version", 0) != 1:
        print("PROOF\tVERSION_MISMATCH")
        sys.exit(0)
    for _k, _v in doc.items():
        if _k == "version":
            if not isinstance(_v, int) or isinstance(_v, bool):
                print("PROOF\tMALFORMED")
                sys.exit(0)
            continue
        if not isinstance(_v, str):
            print("PROOF\tMALFORMED")
            sys.exit(0)
    for _k, _v in doc.items():
        _kl = str(_k).lower()
        if _kl in ("password", "database-url", "database_url",
                   "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
                   "secret_value", "secretvalue", "private_key", "privatekey",
                   "certificate_body", "certificate_chain"):
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if isinstance(_v, str):
            _vl = _v.lower()
            if "://" in _vl:
                print("PROOF\tSECRET_FIELD")
                sys.exit(0)
            if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
                print("PROOF\tSECRET_FIELD")
                sys.exit(0)
            if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
                print("PROOF\tSECRET_FIELD")
                sys.exit(0)
            if "password" in _vl:
                print("PROOF\tSECRET_FIELD")
                sys.exit(0)
    for _f, _w in (("account", want_account), ("region", want_region),
                   ("stack", want_stack), ("cluster", want_cluster),
                   ("phase", "init"), ("label", "sdk-init"),
                   ("taskdef_logical", "SdkInitTaskDefinition")):
        if doc.get(_f, "") != _w:
            print("PROOF\t%s_MISMATCH" % _f.upper())
            sys.exit(0)
    _token = doc.get("client_token", "")
    if not isinstance(_token, str) or len(_token) != 33 or not _token.startswith("lc-"):
        print("PROOF\tTOKEN_MALFORMED")
        sys.exit(0)
    _outcome = doc.get("outcome", "")
    if _outcome != "complete":
        print("PROOF\tUNRESOLVED")
        print("OUTCOME\t%s" % (_outcome if isinstance(_outcome, str) and _outcome else "MISSING"))
        sys.exit(0)
    _task = doc.get("task_arn", "")
    if not isinstance(_task, str) or not _task.startswith(
            "arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
        print("PROOF\tTASKARN_FOREIGN")
        sys.exit(0)
    _tdef = doc.get("taskdef_arn", "")
    if not isinstance(_tdef, str) or not _tdef.startswith(
            "arn:aws:ecs:%s:%s:task" "-definition/" % (want_region, want_account)):
        print("PROOF\tTASKDEF_FOREIGN")
        sys.exit(0)
    try:
        _tail = _tdef.split(":task" "-definition/", 1)[1]
        _fam = _tail.split(":", 1)[0]
        _rev = _tail.split(":", 1)[1] if ":" in _tail else ""
    except Exception:
        _fam = ""
        _rev = ""
    if not _fam or not _rev:
        print("PROOF\tTASKDEF_MALFORMED")
        sys.exit(0)
    try:
        _rec = doc.get("config_digest", "")
        _raw = "|".join([
            doc.get("account", ""), doc.get("region", ""),
            doc.get("stack", ""), doc.get("cluster", ""),
            doc.get("phase", ""), doc.get("label", ""),
            doc.get("taskdef_logical", ""), doc.get("taskdef_arn", ""),
        ])
        _exp = hashlib.sha256(_raw.encode("utf-8")).hexdigest()[:32]
        if not isinstance(_rec, str) or _rec != _exp:
            print("PROOF\tCONFIG_MISMATCH")
            sys.exit(0)
    except Exception:
        print("PROOF\tCONFIG_MISMATCH")
        sys.exit(0)
    _upd = doc.get("updated_utc", "")
    if not isinstance(_upd, str) or not _upd:
        print("PROOF\tUPDATED_MISSING")
        sys.exit(0)
    print("PROOF\tOK")
    print("TOKEN\t%s" % _token)
    print("TASKARN\t%s" % _task)
    print("TASKDEF\t%s" % _tdef)
    print("GEN\t")
    print("SOURCE\t")
    print("HEAD\t")
    print("STACKID\t")
    print("LEGACY\ttrue")
    print("UPDATED\t%s" % _upd)
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
for _k, _v in doc.items():
    if _k == "version":
        if not isinstance(_v, int) or isinstance(_v, bool):
            print("PROOF\tMALFORMED")
            sys.exit(0)
        continue
    if not isinstance(_v, str):
        print("PROOF\tMALFORMED")
        sys.exit(0)
for _k, _v in doc.items():
    _kl = str(_k).lower()
    if _kl in ("password", "database-url", "database_url",
               "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
               "secret_value", "secretvalue", "private_key", "privatekey",
               "certificate_body", "certificate_chain"):
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
    if isinstance(_v, str):
        _vl = _v.lower()
        if "://" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "password" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
checks = (("account", want_account), ("region", want_region),
          ("stack", want_stack), ("cluster", want_cluster),
          ("phase", "init"), ("label", "sdk-init"),
          ("taskdef_logical", "SdkInitTaskDefinition"))
for field, want in checks:
    if doc.get(field, "") != want:
        print("PROOF\t%s_MISMATCH" % field.upper())
        sys.exit(0)
gen = doc.get("release_generation", "")
source = doc.get("source_sha", "")
head = doc.get("target_head", "")
if not isinstance(gen, str) or not gen:
    print("PROOF\tGENERATION_MISSING")
    sys.exit(0)
for char in gen:
    if char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-":
        print("PROOF\tGENERATION_MALFORMED")
        sys.exit(0)
if not isinstance(source, str):
    print("PROOF\tSOURCE_MALFORMED")
    sys.exit(0)
if source:
    if len(source) < 7 or len(source) > 40:
        print("PROOF\tSOURCE_MALFORMED")
        sys.exit(0)
    for char in source:
        if char not in "0123456789abcdefABCDEF":
            print("PROOF\tSOURCE_MALFORMED")
            sys.exit(0)
allowed_heads = {"004", "005", "006", "007", want_head}
if not isinstance(head, str) or head not in allowed_heads:
    print("PROOF\tHEAD_UNKNOWN")
    sys.exit(0)
named = set()
for found in re.findall(r"head(\d{3})", gen):
    named.add(found)
for tok in re.split(r"[-_.]", gen):
    if re.fullmatch(r"\d{3}", tok or ""):
        named.add(tok)
if len(named) == 0:
    print("PROOF\tGENERATION_FOREIGN")
    sys.exit(0)
if len(named) != 1:
    print("PROOF\tGENERATION_AMBIGUOUS")
    sys.exit(0)
if next(iter(named)) != head:
    print("PROOF\tHEAD_MISMATCH")
    sys.exit(0)
if want_stack_id and doc.get("stack_id", "") != want_stack_id:
    print("PROOF\tSTACKID_MISMATCH")
    sys.exit(0)
if want_base and want_base != "active.json" and want_base != "legacy":
    try:
        base_esc = "launchcrew-" + re.escape(want_stack) + "-init-sdk-init"
        active_re = re.compile(r"^" + base_esc + r"-([A-Za-z0-9_.-]+)-active\.json$")
        archive_re = re.compile(r"^" + base_esc + r"-([A-Za-z0-9_.-]+)-complete-(lc-[A-Za-z0-9]{30})\.json$")
        file_gen = None
        m = active_re.match(want_base or "")
        if m:
            file_gen = m.group(1)
        else:
            m2 = archive_re.match(want_base or "")
            if m2:
                file_gen = m2.group(1)
    except Exception:
        file_gen = None
    if file_gen and file_gen != gen:
        print("PROOF\tGENERATION_FILENAME_MISMATCH")
        sys.exit(0)
token = doc.get("client_token", "")
if not isinstance(token, str) or len(token) != 33 or not token.startswith("lc-"):
    print("PROOF\tTOKEN_MALFORMED")
    sys.exit(0)
outcome = doc.get("outcome", "")
if outcome != "complete":
    print("PROOF\tUNRESOLVED")
    print("OUTCOME\t%s" % (outcome if isinstance(outcome, str) and outcome else "MISSING"))
    sys.exit(0)
task_arn = doc.get("task_arn", "")
if not isinstance(task_arn, str) or not task_arn.startswith(
        "arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
    print("PROOF\tTASKARN_FOREIGN")
    sys.exit(0)
taskdef_arn = doc.get("taskdef_arn", "")
if not isinstance(taskdef_arn, str) or not taskdef_arn.startswith(
        "arn:aws:ecs:%s:%s:task" "-definition/" % (want_region, want_account)):
    print("PROOF\tTASKDEF_FOREIGN")
    sys.exit(0)
try:
    rec_digest = doc.get("config_digest", "")
    raw = "|".join([
        doc.get("account", ""), doc.get("region", ""),
        doc.get("stack", ""), doc.get("cluster", ""),
        doc.get("phase", ""), doc.get("label", ""),
        doc.get("taskdef_logical", ""), doc.get("taskdef_arn", ""),
    ])
    expect_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    if not isinstance(rec_digest, str) or rec_digest != expect_digest:
        print("PROOF\tCONFIG_MISMATCH")
        sys.exit(0)
except Exception:
    print("PROOF\tCONFIG_MISMATCH")
    sys.exit(0)
print("PROOF\tOK")
print("TOKEN\t%s" % token)
print("TASKARN\t%s" % task_arn)
print("TASKDEF\t%s" % taskdef_arn)
print("GEN\t%s" % gen)
print("SOURCE\t%s" % source)
print("HEAD\t%s" % head)
print("STACKID\t%s" % doc.get("stack_id", ""))
print("LEGACY\tfalse")
PYEOF
}

# Strict validation of an original typed journal for recovery. Args: path,
# basename, phase, label, logical, allow_started (0 complete only, 1 started
# or complete for the distinct binder case). Only allowed outcomes qualify;
# pending, adopted, and every ambiguous outcome refuse with no recovery.
# Versioned records validate exact owned account, region, stack, cluster,
# phase, label, logical, generation, head, StackId, token, task ARN shape,
# taskdef ARN shape, and recomputed config digest. Exact legacy unversioned
# branch ONLY for the exact unversioned active basename validates the 14-key
# legacy schema with version 1, allowed outcome, owned identity, token, task
# and taskdef ARNs, and recomputed digest. It never fabricates generation,
# source, head, or stack id and returns those empty with LEGACY true. Prints
# PROOF OK plus TOKEN, TASKARN, TASKDEF, GEN, SOURCE, HEAD, STACKID, OUTCOME,
# LEGACY on success, else PROOF reason. Never writes the original.
validate_typed_journal_for_recovery() {
  TYPED_PATH="$1"
  TYPED_BASE="$2"
  TYPED_PHASE="$3"
  TYPED_LABEL="$4"
  TYPED_LOGICAL="$5"
  TYPED_ALLOW_STARTED="${6:-0}"
  python3 - "$TYPED_PATH" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$TARGET_DB_HEAD" "${STACK_ID:-}" "$TYPED_BASE" "$TYPED_PHASE" "$TYPED_LABEL" "$TYPED_LOGICAL" "$TYPED_ALLOW_STARTED" 2>/dev/null <<'PYEOF'
import hashlib, json, os, re, sys
(path, want_account, want_region, want_stack, want_cluster,
 want_head, want_stack_id, want_base,
 want_phase, want_label, want_logical, allow_started) = sys.argv[1:13]
allow_started = (allow_started == "1")
try:
    if os.path.islink(path):
        print("PROOF\tSYMLINK")
        sys.exit(0)
    finfo = os.stat(path)
    if (finfo.st_mode & 0o777) != 0o600:
        print("PROOF\tMODE")
        sys.exit(0)
    if finfo.st_uid != os.getuid():
        print("PROOF\tOWNER")
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
try:
    if want_base and want_base not in ("active.json", "legacy"):
        if os.path.basename(path) != want_base:
            print("PROOF\tPATH_MISMATCH")
            sys.exit(0)
except Exception:
    print("PROOF\tPATH_MISMATCH")
    sys.exit(0)
legacy_base = "launchcrew-%s-%s-%s-active.json" % (want_stack, want_phase, want_label)
if want_base == legacy_base:
    legacy_expected = {"account", "client_token", "cluster", "config_digest",
                       "label", "outcome", "phase", "region", "stack",
                       "task_arn", "taskdef_arn", "taskdef_logical",
                       "updated_utc", "version"}
    if set(doc.keys()) != legacy_expected:
        for _k in doc:
            if _k not in legacy_expected:
                print("PROOF\tFOREIGN_FIELD")
                sys.exit(0)
        print("PROOF\tLEGACY_KEYS_MISMATCH")
        sys.exit(0)
    if doc.get("version", 0) != 1:
        print("PROOF\tVERSION_MISMATCH")
        sys.exit(0)
    for _k, _v in doc.items():
        if _k == "version":
            if not isinstance(_v, int) or isinstance(_v, bool):
                print("PROOF\tMALFORMED")
                sys.exit(0)
            continue
        if not isinstance(_v, str):
            print("PROOF\tMALFORMED")
            sys.exit(0)
    for _k, _v in doc.items():
        _kl = str(_k).lower()
        if _kl in ("password", "database-url", "database_url",
                   "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
                   "secret_value", "secretvalue", "private_key", "privatekey",
                   "certificate_body", "certificate_chain"):
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if isinstance(_v, str):
            _vl = _v.lower()
            if "://" in _vl:
                print("PROOF\tSECRET_FIELD")
                sys.exit(0)
            if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
                print("PROOF\tSECRET_FIELD")
                sys.exit(0)
            if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
                print("PROOF\tSECRET_FIELD")
                sys.exit(0)
            if "password" in _vl:
                print("PROOF\tSECRET_FIELD")
                sys.exit(0)
    for _f, _w in (("account", want_account), ("region", want_region),
                   ("stack", want_stack), ("cluster", want_cluster),
                   ("phase", want_phase), ("label", want_label),
                   ("taskdef_logical", want_logical)):
        if doc.get(_f, "") != _w:
            print("PROOF\t%s_MISMATCH" % _f.upper())
            sys.exit(0)
    _token = doc.get("client_token", "")
    if not isinstance(_token, str) or len(_token) != 33 or not _token.startswith("lc-"):
        print("PROOF\tTOKEN_MALFORMED")
        sys.exit(0)
    _outcome = doc.get("outcome", "")
    allowed = ("complete", "started") if allow_started else ("complete",)
    if _outcome not in allowed:
        print("PROOF\tUNRESOLVED")
        print("OUTCOME\t%s" % (_outcome if isinstance(_outcome, str) and _outcome else "MISSING"))
        sys.exit(0)
    _task = doc.get("task_arn", "")
    if not isinstance(_task, str) or not _task.startswith(
            "arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
        print("PROOF\tTASKARN_FOREIGN")
        sys.exit(0)
    _tdef = doc.get("taskdef_arn", "")
    if not isinstance(_tdef, str) or not _tdef.startswith(
            "arn:aws:ecs:%s:%s:task" "-definition/" % (want_region, want_account)):
        print("PROOF\tTASKDEF_FOREIGN")
        sys.exit(0)
    try:
        _tail = _tdef.split(":task" "-definition/", 1)[1]
        _fam = _tail.split(":", 1)[0]
        _rev = _tail.split(":", 1)[1] if ":" in _tail else ""
    except Exception:
        _fam = ""
        _rev = ""
    if not _fam or not _rev:
        print("PROOF\tTASKDEF_MALFORMED")
        sys.exit(0)
    try:
        _rec = doc.get("config_digest", "")
        _raw = "|".join([
            doc.get("account", ""), doc.get("region", ""),
            doc.get("stack", ""), doc.get("cluster", ""),
            doc.get("phase", ""), doc.get("label", ""),
            doc.get("taskdef_logical", ""), doc.get("taskdef_arn", ""),
        ])
        _exp = hashlib.sha256(_raw.encode("utf-8")).hexdigest()[:32]
        if not isinstance(_rec, str) or _rec != _exp:
            print("PROOF\tCONFIG_MISMATCH")
            sys.exit(0)
    except Exception:
        print("PROOF\tCONFIG_MISMATCH")
        sys.exit(0)
    _upd = doc.get("updated_utc", "")
    if not isinstance(_upd, str) or not _upd:
        print("PROOF\tUPDATED_MISSING")
        sys.exit(0)
    print("PROOF\tOK")
    print("TOKEN\t%s" % _token)
    print("TASKARN\t%s" % _task)
    print("TASKDEF\t%s" % _tdef)
    print("GEN\t")
    print("SOURCE\t")
    print("HEAD\t")
    print("STACKID\t")
    print("OUTCOME\t%s" % _outcome)
    print("LEGACY\ttrue")
    print("UPDATED\t%s" % _upd)
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
for _k, _v in doc.items():
    if _k == "version":
        if not isinstance(_v, int) or isinstance(_v, bool):
            print("PROOF\tMALFORMED")
            sys.exit(0)
        continue
    if not isinstance(_v, str):
        print("PROOF\tMALFORMED")
        sys.exit(0)
for _k, _v in doc.items():
    _kl = str(_k).lower()
    if _kl in ("password", "database-url", "database_url",
               "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
               "secret_value", "secretvalue", "private_key", "privatekey",
               "certificate_body", "certificate_chain"):
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
    if isinstance(_v, str):
        _vl = _v.lower()
        if "://" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "password" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
checks = (("account", want_account), ("region", want_region),
          ("stack", want_stack), ("cluster", want_cluster),
          ("phase", want_phase), ("label", want_label),
          ("taskdef_logical", want_logical))
for field, want in checks:
    if doc.get(field, "") != want:
        print("PROOF\t%s_MISMATCH" % field.upper())
        sys.exit(0)
gen = doc.get("release_generation", "")
source = doc.get("source_sha", "")
head = doc.get("target_head", "")
if not isinstance(gen, str) or not gen:
    print("PROOF\tGENERATION_MISSING")
    sys.exit(0)
for char in gen:
    if char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-":
        print("PROOF\tGENERATION_MALFORMED")
        sys.exit(0)
if not isinstance(source, str):
    print("PROOF\tSOURCE_MALFORMED")
    sys.exit(0)
if source:
    if len(source) < 7 or len(source) > 40:
        print("PROOF\tSOURCE_MALFORMED")
        sys.exit(0)
    for char in source:
        if char not in "0123456789abcdefABCDEF":
            print("PROOF\tSOURCE_MALFORMED")
            sys.exit(0)
allowed_heads = {"004", "005", "006", "007", want_head}
if not isinstance(head, str) or head not in allowed_heads:
    print("PROOF\tHEAD_UNKNOWN")
    sys.exit(0)
named = set()
for found in re.findall(r"head(\d{3})", gen):
    named.add(found)
for tok in re.split(r"[-_.]", gen):
    if re.fullmatch(r"\d{3}", tok or ""):
        named.add(tok)
if len(named) == 0:
    print("PROOF\tGENERATION_FOREIGN")
    sys.exit(0)
if len(named) != 1:
    print("PROOF\tGENERATION_AMBIGUOUS")
    sys.exit(0)
if next(iter(named)) != head:
    print("PROOF\tHEAD_MISMATCH")
    sys.exit(0)
if want_stack_id and doc.get("stack_id", "") != want_stack_id:
    print("PROOF\tSTACKID_MISMATCH")
    sys.exit(0)
if want_base and want_base != "active.json" and want_base != "legacy":
    try:
        base_esc = "launchcrew-" + re.escape(want_stack) + "-" + re.escape(want_phase) + "-" + re.escape(want_label)
        active_re = re.compile(r"^" + base_esc + r"-([A-Za-z0-9_.-]+)-active\.json$")
        archive_re = re.compile(r"^" + base_esc + r"-([A-Za-z0-9_.-]+)-complete-(lc-[A-Za-z0-9]{30})\.json$")
        file_gen = None
        m = active_re.match(want_base or "")
        if m:
            file_gen = m.group(1)
        else:
            m2 = archive_re.match(want_base or "")
            if m2:
                file_gen = m2.group(1)
    except Exception:
        file_gen = None
    if not file_gen:
        print("PROOF\tGENERATION_FILENAME_MISMATCH")
        sys.exit(0)
    if file_gen != gen:
        print("PROOF\tGENERATION_FILENAME_MISMATCH")
        sys.exit(0)
token = doc.get("client_token", "")
if not isinstance(token, str) or len(token) != 33 or not token.startswith("lc-"):
    print("PROOF\tTOKEN_MALFORMED")
    sys.exit(0)
outcome = doc.get("outcome", "")
allowed = ("complete", "started") if allow_started else ("complete",)
if outcome not in allowed:
    print("PROOF\tUNRESOLVED")
    print("OUTCOME\t%s" % (outcome if isinstance(outcome, str) and outcome else "MISSING"))
    sys.exit(0)
task_arn = doc.get("task_arn", "")
if not isinstance(task_arn, str) or not task_arn.startswith(
        "arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
    print("PROOF\tTASKARN_FOREIGN")
    sys.exit(0)
taskdef_arn = doc.get("taskdef_arn", "")
if not isinstance(taskdef_arn, str) or not taskdef_arn.startswith(
        "arn:aws:ecs:%s:%s:task" "-definition/" % (want_region, want_account)):
    print("PROOF\tTASKDEF_FOREIGN")
    sys.exit(0)
try:
    rec_digest = doc.get("config_digest", "")
    raw = "|".join([
        doc.get("account", ""), doc.get("region", ""),
        doc.get("stack", ""), doc.get("cluster", ""),
        doc.get("phase", ""), doc.get("label", ""),
        doc.get("taskdef_logical", ""), doc.get("taskdef_arn", ""),
    ])
    expect_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    if not isinstance(rec_digest, str) or rec_digest != expect_digest:
        print("PROOF\tCONFIG_MISMATCH")
        sys.exit(0)
except Exception:
    print("PROOF\tCONFIG_MISMATCH")
    sys.exit(0)
print("PROOF\tOK")
print("TOKEN\t%s" % token)
print("TASKARN\t%s" % task_arn)
print("TASKDEF\t%s" % taskdef_arn)
print("GEN\t%s" % gen)
print("SOURCE\t%s" % source)
print("HEAD\t%s" % head)
print("STACKID\t%s" % doc.get("stack_id", ""))
print("OUTCOME\t%s" % outcome)
print("LEGACY\tfalse")
PYEOF
}

# Strict paginated startedBy-only sweep for one token, one round.
# Lists by startedBy alone with raw --no-paginate plus --cli-input-json,
# exact lowerCamel cluster, startedBy, maxResults, nextToken. Never combines
# startedBy with desiredStatus in the same request. Requires exact JSON
# structure with only taskArns plus optional nextToken, zero ARNs across
# every page with no truncation, no failure, and no malformed element. Every
# element must be a nonempty owned ECS task ARN for the exact account,
# region, and cluster. Any null, number, empty, None, foreign ARN, object,
# duplicate, failed page, truncation, or pagination ambiguity refuses, never
# counts as absence. Args: token, context label, round tag ("" or "second").
# Fails closed via phase_failed. On success returns 0 with no claim; the
# outer gate combines this with recorded MISSING plus desired STOPPED sweep
# and a second stable round, reporting only a point-in-time observation.
absence_startedby_sweep_once() {
  ABSENCE_TOKEN="$1"
  ABSENCE_CONTEXT="$2"
  ABSENCE_ROUND="${3:-}"
  if [ "$ABSENCE_ROUND" = "second" ]; then
    ABSENCE_PREFIX="second sweep inconsistent, possible transition: "
  else
    ABSENCE_PREFIX=""
  fi
  ABSENCE_COLLECTED="$(mktemp /tmp/launchcrew-absence-XXXXXX)"
  printf '[]' >"$ABSENCE_COLLECTED"
  ABSENCE_PAGE="$(mktemp /tmp/launchcrew-absence-page-XXXXXX)"
  ABSENCE_INPUT="$(mktemp /tmp/launchcrew-absence-in-XXXXXX)"
  ABSENCE_NEXT=""
  ABSENCE_PAGES=0
  while [ "$ABSENCE_PAGES" -lt 3 ]; do
    ABSENCE_PAGES=$((ABSENCE_PAGES + 1))
    if ! python3 - "$ABSENCE_INPUT" "$CLUSTER_NAME" "$ABSENCE_TOKEN" "$ABSENCE_NEXT" 2>/dev/null <<'PYEOF'
import json, sys
path, cluster, token_filter, token = sys.argv[1:5]
doc = {"cluster": cluster, "startedBy": token_filter, "maxResults": 10}
if token and token != "END" and token != "None":
    doc["nextToken"] = token
with open(path, "w", encoding="utf-8") as out:
    json.dump(doc, out)
PYEOF
    then
      rm -f "$ABSENCE_PAGE" "$ABSENCE_COLLECTED" "$ABSENCE_INPUT"
      echo "refused: $ABSENCE_CONTEXT ${ABSENCE_PREFIX}running absence input failed for token, cannot prove absence." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    if ! "$AWS_BIN" ecs list-tasks --cli-input-json "file://$ABSENCE_INPUT" --region "$EXPECTED_REGION" --no-paginate --output json >"$ABSENCE_PAGE" 2>"$TMP_ERR"; then
      rm -f "$ABSENCE_PAGE" "$ABSENCE_COLLECTED" "$ABSENCE_INPUT"
      echo "refused: $ABSENCE_CONTEXT ${ABSENCE_PREFIX}running absence list failed, cannot prove absence." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    ABSENCE_NEXT="$(python3 - "$ABSENCE_PAGE" "$ABSENCE_COLLECTED" "$EXPECTED_REGION" "$EXPECTED_ACCOUNT" "$CLUSTER_NAME" 2>/dev/null <<'PYEOF'
import json, sys
page_file, collected_file, want_region, want_account, want_cluster = sys.argv[1:6]
try:
    page = json.load(open(page_file))
    collected = json.load(open(collected_file))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(page, dict) or not isinstance(collected, list):
    print("MALFORMED")
    sys.exit(0)
for key in page:
    if key not in ("taskArns", "nextToken"):
        print("MALFORMED")
        sys.exit(0)
if "taskArns" not in page:
    print("MALFORMED")
    sys.exit(0)
arns = page.get("taskArns")
if not isinstance(arns, list):
    print("MALFORMED")
    sys.exit(0)
prefix = "arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)
seen = set()
for existing in collected:
    if not isinstance(existing, str) or not existing.startswith(prefix):
        print("MALFORMED")
        sys.exit(0)
    suffix = existing[len(prefix):]
    if not suffix or not suffix.strip() or any(c.isspace() for c in existing):
        print("MALFORMED")
        sys.exit(0)
    if existing in seen:
        print("MALFORMED")
        sys.exit(0)
    seen.add(existing)
for arn in arns:
    if not isinstance(arn, str):
        print("MALFORMED")
        sys.exit(0)
    if not arn or arn == "None":
        print("MALFORMED")
        sys.exit(0)
    if not arn.startswith(prefix):
        print("MALFORMED")
        sys.exit(0)
    suffix = arn[len(prefix):]
    if not suffix or not suffix.strip() or any(c.isspace() for c in arn):
        print("MALFORMED")
        sys.exit(0)
    if arn in seen:
        print("MALFORMED")
        sys.exit(0)
    seen.add(arn)
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
)" || ABSENCE_NEXT="MALFORMED"
    ABSENCE_NEXT="$(printf '%s' "$ABSENCE_NEXT" | tr -d '[:space:]')"
    if [ "$ABSENCE_NEXT" = "MALFORMED" ]; then
      rm -f "$ABSENCE_PAGE" "$ABSENCE_COLLECTED" "$ABSENCE_INPUT"
      echo "refused: $ABSENCE_CONTEXT ${ABSENCE_PREFIX}running absence list malformed, cannot prove absence." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    if [ "$ABSENCE_NEXT" = "TOO_MANY" ]; then
      rm -f "$ABSENCE_PAGE" "$ABSENCE_COLLECTED" "$ABSENCE_INPUT"
      echo "refused: $ABSENCE_CONTEXT ${ABSENCE_PREFIX}running absence has too many candidates, cannot prove absence." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    if [ -z "$ABSENCE_NEXT" ] || [ "$ABSENCE_NEXT" = "END" ] || [ "$ABSENCE_NEXT" = "None" ]; then
      break
    fi
  done
  if [ -n "$ABSENCE_NEXT" ] && [ "$ABSENCE_NEXT" != "END" ] && [ "$ABSENCE_NEXT" != "None" ]; then
    rm -f "$ABSENCE_PAGE" "$ABSENCE_COLLECTED" "$ABSENCE_INPUT"
    echo "refused: $ABSENCE_CONTEXT ${ABSENCE_PREFIX}running absence has truncated pages, cannot prove absence." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  rm -f "$ABSENCE_PAGE" "$ABSENCE_INPUT"
  ABSENCE_COUNT="$(python3 - "$ABSENCE_COLLECTED" 2>/dev/null <<'PYEOF'
import json, sys
try:
    collected = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
print(len(collected) if isinstance(collected, list) else "MALFORMED")
PYEOF
)" || ABSENCE_COUNT="MALFORMED"
  rm -f "$ABSENCE_COLLECTED"
  ABSENCE_COUNT="$(printf '%s' "$ABSENCE_COUNT" | tr -d '[:space:]')"
  if [ "$ABSENCE_COUNT" = "MALFORMED" ]; then
    echo "refused: $ABSENCE_CONTEXT ${ABSENCE_PREFIX}running absence unreadable, cannot prove absence." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  if [ "$ABSENCE_COUNT" != "0" ]; then
    echo "refused: $ABSENCE_CONTEXT ${ABSENCE_PREFIX}still has $ABSENCE_COUNT running tasks for old token, cannot proceed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  return 0
}

# Direct recorded-task MISSING proof for one round, read-only.
# Describes the exact recorded task ARN and requires well-formed zero tasks
# with exactly one MISSING failure for that ARN. Any PRESENT, wrong reason,
# wrong ARN, mixed task plus failure, malformed type, multiple failures,
# empty response, call failure, or ambiguity refuses, never counts as
# absence. Args: token (kept for clarity), recorded ARN, context, round tag
# ("" or "second"). Fails closed via phase_failed. On success returns 0.
absence_prove_recorded_missing_once() {
  MISSING_TOKEN="$1"
  MISSING_RECORDED="$2"
  MISSING_CONTEXT="$3"
  MISSING_ROUND="${4:-}"
  if [ "$MISSING_ROUND" = "second" ]; then
    MISSING_PREFIX="second sweep inconsistent, possible transition: "
  else
    MISSING_PREFIX=""
  fi
  MISSING_DESC="$(mktemp /tmp/launchcrew-missing-XXXXXX)"
  if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$MISSING_RECORDED" --region "$EXPECTED_REGION" --output json >"$MISSING_DESC" 2>"$TMP_ERR"; then
    rm -f "$MISSING_DESC"
    echo "refused: $MISSING_CONTEXT ${MISSING_PREFIX}recorded task MISSING proof failed, cannot prove absence." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  MISSING_PRESENCE="$(python3 - "$MISSING_DESC" "$MISSING_RECORDED" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("UNREADABLE")
    sys.exit(0)
expected = sys.argv[2] if len(sys.argv) > 2 else ""
if not isinstance(doc, dict):
    print("UNREADABLE")
    sys.exit(0)
if "tasks" not in doc or "failures" not in doc:
    print("AMBIGUOUS_RESPONSE")
    sys.exit(0)
tasks = doc.get("tasks")
failures = doc.get("failures")
if not isinstance(tasks, list) or not isinstance(failures, list):
    print("AMBIGUOUS_RESPONSE")
    sys.exit(0)
for entry in tasks:
    if not isinstance(entry, dict):
        print("AMBIGUOUS_RESPONSE")
        sys.exit(0)
for entry in failures:
    if not isinstance(entry, dict):
        print("AMBIGUOUS_RESPONSE")
        sys.exit(0)
    if not isinstance(entry.get("arn"), str) or not isinstance(entry.get("reason"), str):
        print("AMBIGUOUS_RESPONSE")
        sys.exit(0)
if tasks and failures:
    print("AMBIGUOUS_MIXED")
    sys.exit(0)
if tasks and not failures:
    print("PRESENT")
    sys.exit(0)
if not tasks and not failures:
    print("AMBIGUOUS_EMPTY")
    sys.exit(0)
if len(failures) != 1:
    print("AMBIGUOUS_FAILURES")
    sys.exit(0)
single = failures[0]
if single.get("reason") != "MISSING":
    print("AMBIGUOUS_REASON")
    sys.exit(0)
if not expected or single.get("arn") != expected:
    print("AMBIGUOUS_ARN")
    sys.exit(0)
print("NO_TASK")
PYEOF
)" || MISSING_PRESENCE="UNREADABLE"
  rm -f "$MISSING_DESC"
  MISSING_PRESENCE="$(printf '%s' "$MISSING_PRESENCE" | tr -d '[:space:]')"
  if [ "$MISSING_PRESENCE" = "NO_TASK" ]; then
    return 0
  fi
  if [ "$MISSING_PRESENCE" = "PRESENT" ]; then
    echo "refused: $MISSING_CONTEXT ${MISSING_PREFIX}still has recorded task present, not MISSING, cannot proceed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  echo "refused: $MISSING_CONTEXT ${MISSING_PREFIX}recorded task presence is $MISSING_PRESENCE, cannot prove absence." >&2
  phase_failed "${RECOVERY_FAIL_PHASE:-init}"
}

# Strict paginated desired STOPPED sweep for one round, plus batch describe.
# Lists all tasks in the exact owned cluster with desiredStatus STOPPED and
# no startedBy, using raw --no-paginate plus --cli-input-json with exact
# lowerCamel cluster, desiredStatus, maxResults, nextToken. Never combines
# desiredStatus with startedBy in the same request. Uses bounded raw
# pagination (10 pages, at most 100 ARNs) and validates every page, key,
# task ARN, duplicate, foreign, and response, refusing truncation, error, or
# ambiguous shapes. Returned STOPPED-desired tasks are described in
# AWS-supported batches of at most 100, checking exact task ARN, cluster,
# startedBy, desiredStatus, and lastStatus, refusing any failure, missing,
# mismatched, or unknown status. For any task with the old recorded
# startedBy, refuses unless the exact recorded ARN is already proven MISSING
# and no other same-token task exists; a same-token task still RUNNING or
# STOPPING always refuses. Args: old token, recorded ARN, context, round tag
# ("" or "second"). Fails closed via phase_failed. On success returns 0.
absence_stopped_sweep_once() {
  ABSSTOP_TOKEN="$1"
  ABSSTOP_RECORDED="$2"
  ABSSTOP_CONTEXT="$3"
  ABSSTOP_ROUND="${4:-}"
  if [ "$ABSSTOP_ROUND" = "second" ]; then
    ABSSTOP_PREFIX="second sweep inconsistent, possible transition: "
  else
    ABSSTOP_PREFIX=""
  fi
  ABSSTOP_COLLECTED="$(mktemp /tmp/launchcrew-stopabs-XXXXXX)"
  printf '[]' >"$ABSSTOP_COLLECTED"
  ABSSTOP_PAGE="$(mktemp /tmp/launchcrew-stopabs-page-XXXXXX)"
  ABSSTOP_INPUT="$(mktemp /tmp/launchcrew-stopabs-in-XXXXXX)"
  ABSSTOP_NEXT=""
  ABSSTOP_PAGES=0
  while [ "$ABSSTOP_PAGES" -lt 10 ]; do
    ABSSTOP_PAGES=$((ABSSTOP_PAGES + 1))
    if ! python3 - "$ABSSTOP_INPUT" "$CLUSTER_NAME" "$ABSSTOP_NEXT" 2>/dev/null <<'PYEOF'
import json, sys
path, cluster, token = sys.argv[1:4]
doc = {"cluster": cluster, "desiredStatus": "STOPPED", "maxResults": 10}
if token and token != "END" and token != "None":
    doc["nextToken"] = token
with open(path, "w", encoding="utf-8") as out:
    json.dump(doc, out)
PYEOF
    then
      rm -f "$ABSSTOP_PAGE" "$ABSSTOP_COLLECTED" "$ABSSTOP_INPUT"
      echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep input failed, cannot prove absence due to ECS API limits." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    if ! "$AWS_BIN" ecs list-tasks --cli-input-json "file://$ABSSTOP_INPUT" --region "$EXPECTED_REGION" --no-paginate --output json >"$ABSSTOP_PAGE" 2>"$TMP_ERR"; then
      rm -f "$ABSSTOP_PAGE" "$ABSSTOP_COLLECTED" "$ABSSTOP_INPUT"
      echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep list failed, cannot prove absence due to ECS API limits." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    ABSSTOP_NEXT="$(python3 - "$ABSSTOP_PAGE" "$ABSSTOP_COLLECTED" "$EXPECTED_REGION" "$EXPECTED_ACCOUNT" "$CLUSTER_NAME" 2>/dev/null <<'PYEOF'
import json, sys
page_file, collected_file, want_region, want_account, want_cluster = sys.argv[1:6]
try:
    page = json.load(open(page_file))
    collected = json.load(open(collected_file))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(page, dict) or not isinstance(collected, list):
    print("MALFORMED")
    sys.exit(0)
for key in page:
    if key not in ("taskArns", "nextToken"):
        print("MALFORMED")
        sys.exit(0)
if "taskArns" not in page:
    print("MALFORMED")
    sys.exit(0)
arns = page.get("taskArns")
if not isinstance(arns, list):
    print("MALFORMED")
    sys.exit(0)
prefix = "arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)
seen = set()
for existing in collected:
    if not isinstance(existing, str) or not existing.startswith(prefix):
        print("MALFORMED")
        sys.exit(0)
    suffix = existing[len(prefix):]
    if not suffix or not suffix.strip() or any(c.isspace() for c in existing):
        print("MALFORMED")
        sys.exit(0)
    if existing in seen:
        print("MALFORMED")
        sys.exit(0)
    seen.add(existing)
for arn in arns:
    if not isinstance(arn, str):
        print("MALFORMED")
        sys.exit(0)
    if not arn or arn == "None":
        print("MALFORMED")
        sys.exit(0)
    if not arn.startswith(prefix):
        print("MALFORMED")
        sys.exit(0)
    suffix = arn[len(prefix):]
    if not suffix or not suffix.strip() or any(c.isspace() for c in arn):
        print("MALFORMED")
        sys.exit(0)
    if arn in seen:
        print("MALFORMED")
        sys.exit(0)
    seen.add(arn)
    collected.append(arn)
if len(collected) > 100:
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
)" || ABSSTOP_NEXT="MALFORMED"
    ABSSTOP_NEXT="$(printf '%s' "$ABSSTOP_NEXT" | tr -d '[:space:]')"
    if [ "$ABSSTOP_NEXT" = "MALFORMED" ]; then
      rm -f "$ABSSTOP_PAGE" "$ABSSTOP_COLLECTED" "$ABSSTOP_INPUT"
      echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep list malformed, cannot prove absence." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    if [ "$ABSSTOP_NEXT" = "TOO_MANY" ]; then
      rm -f "$ABSSTOP_PAGE" "$ABSSTOP_COLLECTED" "$ABSSTOP_INPUT"
      echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep has too many candidates, cannot reliably prove absence due to ECS API limits." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    if [ -z "$ABSSTOP_NEXT" ] || [ "$ABSSTOP_NEXT" = "END" ] || [ "$ABSSTOP_NEXT" = "None" ]; then
      break
    fi
  done
  if [ -n "$ABSSTOP_NEXT" ] && [ "$ABSSTOP_NEXT" != "END" ] && [ "$ABSSTOP_NEXT" != "None" ]; then
    rm -f "$ABSSTOP_PAGE" "$ABSSTOP_COLLECTED" "$ABSSTOP_INPUT"
    echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep has truncated pages, cannot reliably prove absence due to ECS API limits." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  rm -f "$ABSSTOP_PAGE" "$ABSSTOP_INPUT"
  ABSSTOP_COUNT="$(python3 - "$ABSSTOP_COLLECTED" 2>/dev/null <<'PYEOF'
import json, sys
try:
    collected = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
print(len(collected) if isinstance(collected, list) else "MALFORMED")
PYEOF
)" || ABSSTOP_COUNT="MALFORMED"
  ABSSTOP_COUNT="$(printf '%s' "$ABSSTOP_COUNT" | tr -d '[:space:]')"
  if [ "$ABSSTOP_COUNT" = "MALFORMED" ]; then
    rm -f "$ABSSTOP_COLLECTED"
    echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep unreadable, cannot prove absence." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  case "$ABSSTOP_COUNT" in
    ''|*[!0-9]*) rm -f "$ABSSTOP_COLLECTED"
      echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep unreadable, cannot prove absence." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
  esac
  if [ "$ABSSTOP_COUNT" -eq 0 ]; then
    rm -f "$ABSSTOP_COLLECTED"
    return 0
  fi
  if [ "$ABSSTOP_COUNT" -gt 100 ]; then
    rm -f "$ABSSTOP_COLLECTED"
    echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep has too many candidates, cannot reliably prove absence due to ECS API limits." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  ABSSTOP_ALL="$(mktemp /tmp/launchcrew-stopabs-all-XXXXXX)"
  if ! python3 - "$ABSSTOP_COLLECTED" "$ABSSTOP_ALL" "$EXPECTED_REGION" "$EXPECTED_ACCOUNT" "$CLUSTER_NAME" 2>/dev/null <<'PYEOF'
import json, sys
collected_file, out_path, want_region, want_account, want_cluster = sys.argv[1:6]
try:
    collected = json.load(open(collected_file))
except Exception:
    sys.exit(1)
if not isinstance(collected, list) or not collected:
    sys.exit(1)
prefix = "arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)
try:
    with open(out_path, "w", encoding="utf-8") as out:
        for arn in collected:
            if not isinstance(arn, str) or not arn.startswith(prefix):
                sys.exit(1)
            suffix = arn[len(prefix):]
            if not suffix or not suffix.strip() or any(c.isspace() for c in arn):
                sys.exit(1)
            out.write(arn + "\n")
except SystemExit:
    raise
except Exception:
    sys.exit(1)
PYEOF
  then
    rm -f "$ABSSTOP_COLLECTED" "$ABSSTOP_ALL"
    echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep unreadable, cannot prove absence." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  rm -f "$ABSSTOP_COLLECTED"
  ABSSTOP_REMAINING="$(mktemp /tmp/launchcrew-stopabs-rem-XXXXXX)"
  if ! cp "$ABSSTOP_ALL" "$ABSSTOP_REMAINING" 2>/dev/null; then
    rm -f "$ABSSTOP_ALL" "$ABSSTOP_REMAINING"
    echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep unreadable, cannot prove absence." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  rm -f "$ABSSTOP_ALL"
  ABSSTOP_CLUSTER_ARN="arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME"
  while [ -s "$ABSSTOP_REMAINING" ]; do
    ABSSTOP_BATCH="$(mktemp /tmp/launchcrew-stopabs-batch-XXXXXX)"
    if ! head -n 100 "$ABSSTOP_REMAINING" >"$ABSSTOP_BATCH" 2>/dev/null; then
      rm -f "$ABSSTOP_BATCH" "$ABSSTOP_REMAINING"
      echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep unreadable, cannot prove absence." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    ABSSTOP_TMP="$(mktemp /tmp/launchcrew-stopabs-tmp-XXXXXX)"
    tail -n +101 "$ABSSTOP_REMAINING" >"$ABSSTOP_TMP" 2>/dev/null || true
    if ! mv "$ABSSTOP_TMP" "$ABSSTOP_REMAINING" 2>/dev/null; then
      rm -f "$ABSSTOP_BATCH" "$ABSSTOP_REMAINING" "$ABSSTOP_TMP"
      echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep unreadable, cannot prove absence." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    ABSSTOP_BATCH_COUNT="$(grep -c . "$ABSSTOP_BATCH" 2>/dev/null || echo 0)"
    ABSSTOP_BATCH_COUNT="$(printf '%s' "$ABSSTOP_BATCH_COUNT" | tr -d '[:space:]')"
    if [ -z "$ABSSTOP_BATCH_COUNT" ]; then ABSSTOP_BATCH_COUNT=0; fi
    case "$ABSSTOP_BATCH_COUNT" in
      ''|*[!0-9]*) rm -f "$ABSSTOP_BATCH" "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED sweep unreadable, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
    esac
    if [ "$ABSSTOP_BATCH_COUNT" -eq 0 ] || [ "$ABSSTOP_BATCH_COUNT" -gt 100 ]; then
      rm -f "$ABSSTOP_BATCH" "$ABSSTOP_REMAINING"
      echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe batch exceeds AWS limit of 100, cannot reliably prove absence due to ECS API limits." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    ABSSTOP_DESC="$(mktemp /tmp/launchcrew-stopabs-desc-XXXXXX)"
    if ! python3 - "$ABSSTOP_BATCH" "$AWS_BIN" "$CLUSTER_NAME" "$EXPECTED_REGION" "$ABSSTOP_DESC" "$TMP_ERR" 2>/dev/null <<'PYEOF'
import subprocess, sys
batch_file, aws_bin, cluster, region, out_path, err_path = sys.argv[1:7]
try:
    with open(batch_file, encoding="utf-8") as handle:
        arns = [line.strip() for line in handle if line.strip()]
except Exception:
    sys.exit(1)
if not arns or len(arns) > 100:
    sys.exit(1)
for arn in arns:
    if not arn or any(c.isspace() for c in arn):
        sys.exit(1)
cmd = [aws_bin, "ecs", "describe-tasks", "--cluster", cluster, "--tasks"] + arns + ["--region", region, "--output", "json"]
try:
    proc = subprocess.run(cmd, capture_output=True, text=True)
except Exception:
    sys.exit(1)
try:
    with open(out_path, "w", encoding="utf-8") as out:
        out.write(proc.stdout or "")
except Exception:
    sys.exit(1)
if proc.returncode != 0:
    try:
        with open(err_path, "w", encoding="utf-8") as err:
            err.write(proc.stderr or "")
    except Exception:
        pass
    sys.exit(proc.returncode)
PYEOF
    then
      rm -f "$ABSSTOP_BATCH" "$ABSSTOP_DESC" "$ABSSTOP_REMAINING"
      echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe failed, cannot prove absence due to ECS API limits." >&2
      phase_failed "${RECOVERY_FAIL_PHASE:-init}"
    fi
    ABSSTOP_CHECK="$(python3 - "$ABSSTOP_DESC" "$ABSSTOP_BATCH" "$ABSSTOP_TOKEN" "$ABSSTOP_RECORDED" "$EXPECTED_REGION" "$EXPECTED_ACCOUNT" "$CLUSTER_NAME" "$ABSSTOP_CLUSTER_ARN" 2>/dev/null <<'PYEOF'
import json, sys
desc_file, batch_file, old_token, recorded_arn = sys.argv[1:5]
want_region, want_account, want_cluster, want_cluster_arn = sys.argv[5:9]
try:
    doc = json.load(open(desc_file))
    with open(batch_file, encoding="utf-8") as handle:
        requested = [line.strip() for line in handle if line.strip()]
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(doc, dict):
    print("MALFORMED")
    sys.exit(0)
if "tasks" not in doc or "failures" not in doc:
    print("MALFORMED")
    sys.exit(0)
tasks = doc.get("tasks")
failures = doc.get("failures")
if not isinstance(tasks, list) or not isinstance(failures, list):
    print("MALFORMED")
    sys.exit(0)
for entry in tasks:
    if not isinstance(entry, dict):
        print("MALFORMED")
        sys.exit(0)
for entry in failures:
    if not isinstance(entry, dict):
        print("MALFORMED")
        sys.exit(0)
if failures:
    print("FAILURES")
    sys.exit(0)
if len(tasks) != len(requested):
    print("COUNT_MISMATCH")
    sys.exit(0)
prefix = "arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)
requested_set = set()
for arn in requested:
    if not isinstance(arn, str) or not arn.startswith(prefix):
        print("MALFORMED")
        sys.exit(0)
    suffix = arn[len(prefix):]
    if not suffix or not suffix.strip() or any(c.isspace() for c in arn):
        print("MALFORMED")
        sys.exit(0)
    if arn in requested_set:
        print("MALFORMED")
        sys.exit(0)
    requested_set.add(arn)
allowed_last = {"PROVISIONING", "PENDING", "ACTIVATING", "RUNNING", "DEACTIVATING", "STOPPING", "DEPROVISIONING", "STOPPED"}
seen = set()
same_token = []
for task in tasks:
    arn = task.get("taskArn", None)
    if not isinstance(arn, str) or not arn.startswith(prefix):
        print("FOREIGN")
        sys.exit(0)
    suffix = arn[len(prefix):]
    if not suffix or not suffix.strip() or any(c.isspace() for c in arn):
        print("FOREIGN")
        sys.exit(0)
    if arn in seen:
        print("DUPLICATE")
        sys.exit(0)
    seen.add(arn)
    if arn not in requested_set:
        print("TASK_MISMATCH")
        sys.exit(0)
    if task.get("clusterArn", "") != want_cluster_arn:
        print("CLUSTER_MISMATCH")
        sys.exit(0)
    desired = task.get("desiredStatus", None)
    if not isinstance(desired, str) or not desired:
        print("MISSING_STATUS")
        sys.exit(0)
    if desired != "STOPPED":
        print("DESIRED_MISMATCH")
        sys.exit(0)
    last = task.get("lastStatus", None)
    if not isinstance(last, str) or not last:
        print("MISSING_STATUS")
        sys.exit(0)
    if last not in allowed_last:
        print("UNKNOWN_STATUS")
        sys.exit(0)
    started = task.get("startedBy", "")
    if started is None:
        started = ""
    if started != "" and not isinstance(started, str):
        print("MALFORMED")
        sys.exit(0)
    if started == old_token:
        same_token.append((arn, last))
if seen != requested_set:
    print("TASK_MISMATCH")
    sys.exit(0)
for arn, last in same_token:
    if last != "STOPPED":
        print("SAME_TOKEN_EXECUTING:%s" % last)
        sys.exit(0)
if same_token:
    for arn, last in same_token:
        if arn == recorded_arn:
            print("SAME_TOKEN_RECORDED_INCONSISTENT")
            sys.exit(0)
    print("SAME_TOKEN_STOPPED_DUPLICATE:%d" % len(same_token))
    sys.exit(0)
print("OK")
PYEOF
)" || ABSSTOP_CHECK="MALFORMED"
    rm -f "$ABSSTOP_DESC" "$ABSSTOP_BATCH"
    ABSSTOP_CHECK="$(printf '%s' "$ABSSTOP_CHECK" | tr -d '[:space:]')"
    case "$ABSSTOP_CHECK" in
      OK) ;;
      SAME_TOKEN_EXECUTING:*)
        ABSSTOP_LAST="${ABSSTOP_CHECK#SAME_TOKEN_EXECUTING:}"
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}still has same-token task still executing with desired STOPPED but lastStatus ${ABSSTOP_LAST:-unknown}, cannot proceed." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      SAME_TOKEN_RECORDED_INCONSISTENT)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}recorded task ARN found in STOPPED sweep despite MISSING proof, inconsistent, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      SAME_TOKEN_STOPPED_DUPLICATE:*)
        ABSSTOP_DUP="${ABSSTOP_CHECK#SAME_TOKEN_STOPPED_DUPLICATE:}"
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}still has ${ABSSTOP_DUP:-1} same-token STOPPED tasks including a second task besides recorded, cannot proceed." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      FAILURES)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe has failures, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      COUNT_MISMATCH)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe count mismatched, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      FOREIGN)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe has foreign task ARN, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      DUPLICATE)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe has duplicate task ARN, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      CLUSTER_MISMATCH)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe cluster mismatched, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      TASK_MISMATCH)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe task mismatched, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      DESIRED_MISMATCH)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe desiredStatus mismatched, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      MISSING_STATUS)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe missing desired or last status, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      UNKNOWN_STATUS)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe has unknown lastStatus, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
      *)
        rm -f "$ABSSTOP_REMAINING"
        echo "refused: $ABSSTOP_CONTEXT ${ABSSTOP_PREFIX}STOPPED describe is ${ABSSTOP_CHECK:-malformed}, cannot prove absence." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
    esac
  done
  rm -f "$ABSSTOP_REMAINING"
  return 0
}

# Point-in-time recovery gate for an aged COMPLETE init, without claiming
# mathematical atomic absence. Preserves exact recorded task DescribeTasks
# MISSING admission, original journal byte-for-byte, fresh read-only
# verifier, pre and post exact material VersionIds and cert, and no old init
# resend. First keeps a strict paginated startedBy-only sweep (ListTasks
# with startedBy alone must be the only filter and defaults to desired
# RUNNING; never combines startedBy with desiredStatus in the same
# request). Then separately lists all tasks in the exact owned cluster with
# desiredStatus STOPPED and no startedBy, using bounded raw pagination and
# strict validation of every page, key, task ARN, duplicate, foreign, and
# response, refusing truncation, error, or ambiguous shapes. Returned
# STOPPED-desired tasks are described in AWS-supported batches of at most
# 100, checking exact task ARN, cluster, startedBy, desiredStatus, and
# lastStatus, refusing any failure, missing, mismatched, or unknown status.
# ECS can have desired STOPPED while last is RUNNING or STOPPING, so a zero
# startedBy list alone is not exhaustive current-execution absence. For any
# task with the old recorded startedBy, refuses unless the exact recorded
# ARN is already proven MISSING and no other same-token task exists; a
# same-token task still RUNNING or STOPPING always refuses. If no currently
# executing same-token task is observed under this bounded sweep, reports
# accurately as a point-in-time observation, not an absolute global or
# forever guarantee. Repeats both sweeps plus direct recorded MISSING after
# a short bounded interval to detect transition; any inconsistency refuses.
# Keeps all AWS calls read-only with no new init, Put, Export, or
# migration. If ECS API limits prevent a reliable proof, fails closed with
# a specific diagnostic instead of pretending exhaustive absence. Args:
# old token, context label, exact recorded task ARN. Fails closed via
# phase_failed.
prove_no_running_for_startedby() {
  GATE_TOKEN="$1"
  GATE_CONTEXT="$2"
  GATE_RECORDED="${3:-${RECOVERY_ORIG_TASK:-}}"
  case "$GATE_TOKEN" in
    lc-??????????????????????????????) ;;
    *) echo "refused: $GATE_CONTEXT old token malformed, cannot prove absence." >&2; phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
  esac
  if printf '%s' "$GATE_TOKEN" | grep -q '[[:space:]]' 2>/dev/null; then
    echo "refused: $GATE_CONTEXT old token malformed, cannot prove absence." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  case "$GATE_RECORDED" in
    "arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:task/$CLUSTER_NAME/"*) ;;
    *) echo "refused: $GATE_CONTEXT recorded task ARN foreign or malformed, cannot prove absence." >&2; phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
  esac
  GATE_SUFFIX="${GATE_RECORDED##*/}"
  if [ -z "$GATE_SUFFIX" ]; then
    echo "refused: $GATE_CONTEXT recorded task ARN foreign or malformed, cannot prove absence." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  if printf '%s' "$GATE_RECORDED" | grep -q '[[:space:]]' 2>/dev/null; then
    echo "refused: $GATE_CONTEXT recorded task ARN foreign or malformed, cannot prove absence." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  absence_startedby_sweep_once "$GATE_TOKEN" "$GATE_CONTEXT" ""
  absence_prove_recorded_missing_once "$GATE_TOKEN" "$GATE_RECORDED" "$GATE_CONTEXT" ""
  absence_stopped_sweep_once "$GATE_TOKEN" "$GATE_RECORDED" "$GATE_CONTEXT" ""
  sleep 1 2>/dev/null || true
  absence_startedby_sweep_once "$GATE_TOKEN" "$GATE_CONTEXT" "second"
  absence_prove_recorded_missing_once "$GATE_TOKEN" "$GATE_RECORDED" "$GATE_CONTEXT" "second"
  absence_stopped_sweep_once "$GATE_TOKEN" "$GATE_RECORDED" "$GATE_CONTEXT" "second"
  echo "$GATE_CONTEXT point-in-time observation: no currently executing same-token tasks in bounded startedBy-only plus desired STOPPED sweeps (two stable rounds) with recorded task MISSING; not an absolute global or forever guarantee."
}

# Terminal proof for a recovery verifier task. Args: task ARN, token,
# taskdef ARN. Waits as hint only, then requires STOPPED lastStatus,
# exact task, taskdef, cluster ARNs, exact startedBy token, and STOPPED
# exit 0 from every essential container derived live from
# DescribeTaskDefinition. Never invents essential on DescribeTasks.
# Sets RECOVERY_VERIFIER_PROOF to OK on success, else fails closed.
prove_recovery_verifier_terminal() {
  PROVE_TASK="$1"
  PROVE_TOKEN="$2"
  PROVE_TASKDEF="$3"
  if ! "$AWS_BIN" ecs wait tasks-stopped --cluster "$CLUSTER_NAME" --tasks "$PROVE_TASK" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    echo "recovery verifier wait reported, verifying terminal state before any claim." >&2
  fi
  PROVE_DESC="$(mktemp /tmp/launchcrew-recverify-XXXXXX)"
  if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$PROVE_TASK" --region "$EXPECTED_REGION" --output json >"$PROVE_DESC" 2>"$TMP_ERR"; then
    rm -f "$PROVE_DESC"
    echo "recovery verifier terminal state unreadable, not treated as success." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  PROVE_DEF_JSON="$(mktemp /tmp/launchcrew-recverify-def-XXXXXX)"
  if ! "$AWS_BIN" ecs "describe-task""-definition" --task"-definition" "$PROVE_TASKDEF" --region "$EXPECTED_REGION" --output json >"$PROVE_DEF_JSON" 2>"$TMP_ERR"; then
    rm -f "$PROVE_DESC" "$PROVE_DEF_JSON"
    echo "recovery verifier expected container set unreadable, not treated as success." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  PROVE_CHECK="$(python3 - "$PROVE_DESC" "$PROVE_DEF_JSON" "$PROVE_TASK" "$PROVE_TASKDEF" "arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME" "$PROVE_TOKEN" 2>/dev/null <<'PYEOF'
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
)" || PROVE_CHECK="UNREADABLE"
  rm -f "$PROVE_DESC" "$PROVE_DEF_JSON"
  PROVE_CHECK="$(printf '%s' "$PROVE_CHECK" | tr -d '[:space:]')"
  if [ "$PROVE_CHECK" != "OK" ]; then
    echo "refused: recovery verifier terminal proof is $PROVE_CHECK, not claimed." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  RECOVERY_VERIFIER_PROOF="OK"
  echo "recovery verifier terminal proof: STOPPED, exact owned task and cluster ARNs, every expected container exit 0."
}

# Compute cryptographically bound one-shot terminal proof digest for recovery.
# Binds verifier task, token, taskdef, containers, lastStatus, original SHA,
# StackId, material ARNs, names, VersionIds, cert identity, release, source,
# head, original basename, and legacy flag. Order must match attestation
# validation exactly. Sets RECOVERY_VERIFIER_DIGEST. Fails closed on empty.
compute_recovery_verifier_digest() {
  if ! RECOVERY_VERIFIER_DIGEST="$(python3 - "$RECOVERY_VERIFIER_TASK" "$RECOVERY_VERIFIER_TOKEN" "$RECOVERY_VERIFIER_TASKDEF" "$RECOVERY_VERIFIER_CONTAINERS" "$RECOVERY_VERIFIER_LAST_STATUS" "$RECOVERY_ORIG_SHA" "$RECOVERY_STACK_ID" "$RECOVERY_RT_ARN" "$RECOVERY_RT_NAME" "$RECOVERY_RT_PRE" "$RECOVERY_RT_POST" "$RECOVERY_MG_ARN" "$RECOVERY_MG_NAME" "$RECOVERY_MG_PRE" "$RECOVERY_MG_POST" "$RECOVERY_TLS_ARN" "$RECOVERY_TLS_NAME" "$RECOVERY_TLS_PRE" "$RECOVERY_TLS_POST" "$RECOVERY_CERT_ARN" "$RECOVERY_CERT_DOMAIN" "$RECOVERY_CERT_SERIAL_PRE" "$RECOVERY_CERT_SERIAL_POST" "${RELEASE_GEN:-}" "${SOURCE_SHA:-}" "${TARGET_DB_HEAD:-008}" "$RECOVERY_ORIG_BASENAME" "${RECOVERY_ORIG_LEGACY:-false}" 2>/dev/null <<'PYEOF'
import hashlib, sys
parts = sys.argv[1:]
print(hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest())
PYEOF
)"; then
    echo "refused: recovery verifier digest failed, no attestation." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  RECOVERY_VERIFIER_DIGEST="$(printf '%s' "$RECOVERY_VERIFIER_DIGEST" | tr -d '[:space:]')"
  [ -n "$RECOVERY_VERIFIER_DIGEST" ] || {
    echo "refused: recovery verifier digest empty, no attestation." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  }
}

# Compute cryptographically bound one-shot terminal proof digest for typed
# recovery. Binds kind, verifier task, token, taskdef, containers,
# lastStatus, original SHA, outcome, StackId, material ARNs, names,
# VersionIds, cert identity, release, source, head, observed head, original
# basename, and legacy flag. Order must match typed attestation validation
# exactly. Sets RECOVERY_VERIFIER_DIGEST. Fails closed on empty.
compute_typed_verifier_digest() {
  if ! RECOVERY_VERIFIER_DIGEST="$(python3 - "${RECOVERY_KIND:-}" "$RECOVERY_VERIFIER_TASK" "$RECOVERY_VERIFIER_TOKEN" "$RECOVERY_VERIFIER_TASKDEF" "$RECOVERY_VERIFIER_CONTAINERS" "$RECOVERY_VERIFIER_LAST_STATUS" "$RECOVERY_ORIG_SHA" "${RECOVERY_ORIG_OUTCOME:-}" "$RECOVERY_STACK_ID" "$RECOVERY_RT_ARN" "$RECOVERY_RT_NAME" "$RECOVERY_RT_PRE" "$RECOVERY_RT_POST" "$RECOVERY_MG_ARN" "$RECOVERY_MG_NAME" "$RECOVERY_MG_PRE" "$RECOVERY_MG_POST" "$RECOVERY_TLS_ARN" "$RECOVERY_TLS_NAME" "$RECOVERY_TLS_PRE" "$RECOVERY_TLS_POST" "$RECOVERY_CERT_ARN" "$RECOVERY_CERT_DOMAIN" "$RECOVERY_CERT_SERIAL_PRE" "$RECOVERY_CERT_SERIAL_POST" "${RELEASE_GEN:-}" "${SOURCE_SHA:-}" "${TARGET_DB_HEAD:-008}" "${RECOVERY_OBSERVED_HEAD:-}" "$RECOVERY_ORIG_BASENAME" "${RECOVERY_ORIG_LEGACY:-false}" 2>/dev/null <<'PYEOF'
import hashlib, sys
parts = sys.argv[1:]
print(hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest())
PYEOF
)"; then
    echo "refused: recovery verifier digest failed, no attestation." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  RECOVERY_VERIFIER_DIGEST="$(printf '%s' "$RECOVERY_VERIFIER_DIGEST" | tr -d '[:space:]')"
  [ -n "$RECOVERY_VERIFIER_DIGEST" ] || {
    echo "refused: recovery verifier digest empty, no attestation." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  }
}

# Terminal proof for a typed recovery verifier task. Args: task ARN, token,
# taskdef ARN, allow_exit10 (0 exit 0 only, 1 exit 0 or 10 for role-state
# head007 ready). Requires STOPPED with exact owned task, taskdef, cluster,
# and startedBy, plus every expected essential container STOPPED with an
# allowed exit. Sets RECOVERY_VERIFIER_PROOF to OK, RECOVERY_VERIFIER_EXIT
# to the observed exit, and RECOVERY_OBSERVED_HEAD for role-state (008 for
# 0, 007 for 10, empty otherwise). Fails closed via phase_failed.
prove_typed_verifier_terminal() {
  TYPED_TASK="$1"
  TYPED_TOKEN="$2"
  TYPED_TASKDEF="$3"
  TYPED_ALLOW10="${4:-0}"
  if ! "$AWS_BIN" ecs wait tasks-stopped --cluster "$CLUSTER_NAME" --tasks "$TYPED_TASK" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    echo "recovery verifier wait reported, verifying terminal state before any claim." >&2
  fi
  TYPED_DESC="$(mktemp /tmp/launchcrew-typedverify-XXXXXX)"
  if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$TYPED_TASK" --region "$EXPECTED_REGION" --output json >"$TYPED_DESC" 2>"$TMP_ERR"; then
    rm -f "$TYPED_DESC"
    echo "recovery verifier terminal state unreadable, not treated as success." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  TYPED_DEF_JSON="$(mktemp /tmp/launchcrew-typedverify-def-XXXXXX)"
  if ! "$AWS_BIN" ecs "describe-task""-definition" --task"-definition" "$TYPED_TASKDEF" --region "$EXPECTED_REGION" --output json >"$TYPED_DEF_JSON" 2>"$TMP_ERR"; then
    rm -f "$TYPED_DESC" "$TYPED_DEF_JSON"
    echo "recovery verifier expected container set unreadable, not treated as success." >&2
    phase_failed "${RECOVERY_FAIL_PHASE:-init}"
  fi
  TYPED_CHECK="$(python3 - "$TYPED_DESC" "$TYPED_DEF_JSON" "$TYPED_TASK" "$TYPED_TASKDEF" "arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME" "$TYPED_TOKEN" "$TYPED_ALLOW10" 2>/dev/null <<'PYEOF'
import json, sys
try:
    describe = json.load(open(sys.argv[1]))
    defined = json.load(open(sys.argv[2]))
except Exception:
    sys.exit(1)
expected_arn, expected_taskdef, expected_cluster, expected_token, allow10 = sys.argv[3:8]
allow10 = (allow10 == "1")
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
exits = set()
for container in actual:
    if container.get("lastStatus") != "STOPPED":
        print("EXIT_NONZERO:" + (container.get("name", "?") or "?"))
        sys.exit(0)
    code = container.get("exitCode", None)
    if not isinstance(code, int) or isinstance(code, bool):
        print("EXIT_NONZERO:" + (container.get("name", "?") or "?"))
        sys.exit(0)
    if code != 0 and not (allow10 and code == 10):
        print("EXIT_NONZERO:" + (container.get("name", "?") or "?"))
        sys.exit(0)
    exits.add(code)
if len(exits) != 1:
    print("EXIT_MIXED")
    sys.exit(0)
print("OK:%d" % next(iter(exits)))
PYEOF
)" || TYPED_CHECK="UNREADABLE"
  rm -f "$TYPED_DESC" "$TYPED_DEF_JSON"
  TYPED_CHECK="$(printf '%s' "$TYPED_CHECK" | tr -d '[:space:]')"
  case "$TYPED_CHECK" in
    OK:0) RECOVERY_VERIFIER_EXIT="0" ;;
    OK:10)
      if [ "$TYPED_ALLOW10" != "1" ]; then
        echo "refused: recovery verifier terminal proof is EXIT_NONZERO, not claimed." >&2
        phase_failed "${RECOVERY_FAIL_PHASE:-init}"
      fi
      RECOVERY_VERIFIER_EXIT="10" ;;
    *) echo "refused: recovery verifier terminal proof is $TYPED_CHECK, not claimed." >&2; phase_failed "${RECOVERY_FAIL_PHASE:-init}" ;;
  esac
  RECOVERY_VERIFIER_PROOF="OK"
  if [ "${RECOVERY_KIND:-}" = "dbroles-recovery-attestation" ] || [ "${RECOVERY_KIND:-}" = "migration-recovery-attestation" ]; then
    if [ "$RECOVERY_VERIFIER_EXIT" = "0" ]; then
      RECOVERY_OBSERVED_HEAD="008"
    elif [ "$RECOVERY_VERIFIER_EXIT" = "10" ]; then
      RECOVERY_OBSERVED_HEAD="007"
    else
      RECOVERY_OBSERVED_HEAD=""
    fi
  elif [ "${RECOVERY_KIND:-}" = "runtime-recovery-attestation" ]; then
    RECOVERY_OBSERVED_HEAD="008"
  else
    RECOVERY_OBSERVED_HEAD=""
  fi
  echo "recovery verifier terminal proof: STOPPED, exact owned task and cluster ARNs, every expected container exit $RECOVERY_VERIFIER_EXIT."
}

# Attest an aged-out prior COMPLETE init journal via a separate read-only
# material verifier. Args: fail phase, original path, original basename.
# Validates exact owned StackId, tags, heads, original ownership, digest,
# taskdef operation, roles, image, token, plus exact current owned secret
# names, ARNs, VersionIds and certificate identity before and after
# verification. Persists admission before any verifier RunTask with exact
# startedBy and token, requires live STOPPED all essential exit 0 with exact
# task, cluster, and taskdef identity, then persists a mode 600 attestation
# with a cryptographically bound one-shot terminal proof tied to the
# unmodified original SHA256, exact material identities, and release. On
# restart with complete, validates immutable schema, original hash and
# ownership, current StackId, tags, material Names, ARNs, VersionIds, cert
# identity, generation, source, head, plus a bounded point-in-time gate for
# the old startedBy with startedBy-only, recorded MISSING, and desired
# STOPPED sweeps in two stable rounds. If the verifier is still live, rechecks live STOPPED
# all essential exit 0; if aged out, permits only for a well-formed zero
# tasks response with exactly one MISSING failure for the attested task
# ARN plus intact persisted proof and fresh desired state, never claiming
# live status after expiry or retroactive old init exit. Any other reason,
# foreign ARN, mixed task plus failure, malformed type, multiple failures,
# empty response, or ambiguity refuses. No new verifier or init resend on
# restart. Legacy unversioned
# originals use an exact 14-key branch, never fabricate StackId, head, or
# generation, and mark legacy_unversioned. Never Put, Export, bind, or
# migration through this route. Returns 0 on recovered, else fails.
attest_aged_init_recovery() {
  RECOVERY_FAIL_PHASE="$1"
  RECOVERY_ORIG_PATH="$2"
  RECOVERY_ORIG_BASENAME="$3"
  if [ -z "$LAUNCH_JOURNAL_DIR" ] || [ ! -d "$LAUNCH_JOURNAL_DIR" ]; then
    echo "refused: recovery needs journal directory with prior init record, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ -L "$LAUNCH_JOURNAL_DIR" ]; then
    echo "recovery journal directory is a symlink, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_ORIG_SHA="$(sha256_of_file "$RECOVERY_ORIG_PATH")"; then
    echo "refused: original init journal hash unreadable, no recovery claimed. Inspect $RECOVERY_ORIG_PATH." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_ORIG_SHA="$(printf '%s' "$RECOVERY_ORIG_SHA" | tr -d '[:space:]')"
  [ -n "$RECOVERY_ORIG_SHA" ] || {
    echo "refused: original init journal hash empty, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  }
  RECOVERY_VALIDATED="$(validate_init_journal_for_recovery "$RECOVERY_ORIG_PATH" "$RECOVERY_ORIG_BASENAME")" || RECOVERY_VALIDATED="PROOF\tUNREADABLE"
  RECOVERY_VALID_PROOF="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_VALID_PROOF" != "OK" ]; then
    RECOVERY_VALID_OUTCOME="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
    echo "refused: original init journal $RECOVERY_ORIG_BASENAME is $RECOVERY_VALID_PROOF ${RECOVERY_VALID_OUTCOME:-}, no recovery claimed. Inspect $RECOVERY_ORIG_PATH." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_ORIG_TOKEN="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="TOKEN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_TASK="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="TASKARN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_TASKDEF="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="TASKDEF"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_GEN="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="GEN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_SOURCE="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="SOURCE"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_HEAD="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="HEAD"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_STACKID="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="STACKID"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_LEGACY="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="LEGACY"{print $2}' | tr -d '[:space:]')"
  [ "$RECOVERY_ORIG_LEGACY" = "true" ] || RECOVERY_ORIG_LEGACY="false"
  validate_stack_for_recovery
  if [ -n "$RECOVERY_ORIG_STACKID" ] && [ "$RECOVERY_ORIG_STACKID" != "$RECOVERY_STACK_ID" ]; then
    echo "refused: original init StackId does not equal the owned StackId, no recovery claimed. Inspect $RECOVERY_ORIG_PATH." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_ORIG_DEF_JSON="$(mktemp /tmp/launchcrew-recorig-XXXXXX)"
  if ! "$AWS_BIN" ecs "describe-task""-definition" --task"-definition" "$RECOVERY_ORIG_TASKDEF" --region "$EXPECTED_REGION" --output json >"$RECOVERY_ORIG_DEF_JSON" 2>"$TMP_ERR"; then
    rm -f "$RECOVERY_ORIG_DEF_JSON"
    echo "refused: original init taskdef unreadable, no recovery claimed. Inspect $RECOVERY_ORIG_PATH." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_EXPECT_EXEC="$(resolve_role_arn SdkInitExecutionRole)"; then
    rm -f "$RECOVERY_ORIG_DEF_JSON"
    echo "refused: original init expected execution role unresolvable, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_EXPECT_TASK_ROLE="$(resolve_role_arn SdkInitTaskRole)"; then
    rm -f "$RECOVERY_ORIG_DEF_JSON"
    echo "refused: original init expected task role unresolvable, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_EXPECT_EXEC="$(printf '%s' "$RECOVERY_EXPECT_EXEC" | tr -d '[:space:]')"
  RECOVERY_EXPECT_TASK_ROLE="$(printf '%s' "$RECOVERY_EXPECT_TASK_ROLE" | tr -d '[:space:]')"
  RECOVERY_ORIG_OP="$(python3 - "$RECOVERY_ORIG_DEF_JSON" "$RECOVERY_EXPECT_EXEC" "$RECOVERY_EXPECT_TASK_ROLE" "${BOOTSTRAP_IMAGE:-}" 2>/dev/null <<'PYEOF'
import json, sys
doc_file, want_exec, want_task, want_image = sys.argv[1:5]
try:
    doc = json.load(open(doc_file))
except Exception:
    sys.exit(1)
taskdef = doc.get("taskDefinition", doc)
if (taskdef.get("executionRoleArn", "") or "") != want_exec:
    print("TASKDEF_OPERATION_MISMATCH:EXEC_ROLE")
    sys.exit(0)
if (taskdef.get("taskRoleArn", "") or "") != want_task:
    print("TASKDEF_OPERATION_MISMATCH:TASK_ROLE")
    sys.exit(0)
containers = taskdef.get("containerDefinitions", []) or []
target = None
for container in containers:
    if (container.get("name", "") or "") == "sdk-init" and container.get("essential", True):
        target = container
        break
if target is None:
    print("TASKDEF_OPERATION_MISMATCH:MISSING_CONTAINER")
    sys.exit(0)
if (target.get("entryPoint", None) or []) != ["/opt/venv/bin/python", "/app/scripts/populate_prereqs.py"]:
    print("TASKDEF_OPERATION_MISMATCH:ENTRYPOINT")
    sys.exit(0)
if (target.get("command", None) or []) != ["--populate"]:
    print("TASKDEF_OPERATION_MISMATCH:COMMAND")
    sys.exit(0)
if want_image and (target.get("image", "") or "") != want_image:
    print("TASKDEF_OPERATION_MISMATCH:IMAGE")
    sys.exit(0)
print("OK")
PYEOF
)" || RECOVERY_ORIG_OP="UNREADABLE"
  rm -f "$RECOVERY_ORIG_DEF_JSON"
  RECOVERY_ORIG_OP="$(printf '%s' "$RECOVERY_ORIG_OP" | tr -d '[:space:]')"
  if [ "$RECOVERY_ORIG_OP" != "OK" ]; then
    echo "refused: original init operation proof is $RECOVERY_ORIG_OP, no recovery claimed. Inspect $RECOVERY_ORIG_PATH." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  [ -n "$RUNTIME_SECRET_ARN" ] || { echo "refused: recovery needs exact runtime secret ARN, no recovery claimed." >&2; phase_failed "$RECOVERY_FAIL_PHASE"; }
  [ -n "$MIGRATION_SECRET_ARN" ] || { echo "refused: recovery needs exact migration secret ARN, no recovery claimed." >&2; phase_failed "$RECOVERY_FAIL_PHASE"; }
  [ -n "$TLS_SECRET_ARN" ] || { echo "refused: recovery needs exact TLS secret ARN, no recovery claimed." >&2; phase_failed "$RECOVERY_FAIL_PHASE"; }
  RECOVERY_RT_IDENTITY="$(fetch_secret_version_identity "$RUNTIME_SECRET_ARN" runtime)"
  RECOVERY_RT_PROOF="$(printf '%s\n' "$RECOVERY_RT_IDENTITY" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_RT_PROOF" != "OK" ]; then
    echo "refused: recovery runtime secret proof is $RECOVERY_RT_PROOF, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_MG_IDENTITY="$(fetch_secret_version_identity "$MIGRATION_SECRET_ARN" migration)"
  RECOVERY_MG_PROOF="$(printf '%s\n' "$RECOVERY_MG_IDENTITY" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_MG_PROOF" != "OK" ]; then
    echo "refused: recovery migration secret proof is $RECOVERY_MG_PROOF, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_TLS_IDENTITY="$(fetch_secret_version_identity "$TLS_SECRET_ARN" tls)"
  RECOVERY_TLS_PROOF="$(printf '%s\n' "$RECOVERY_TLS_IDENTITY" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_TLS_PROOF" != "OK" ]; then
    echo "refused: recovery TLS secret proof is $RECOVERY_TLS_PROOF, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_RT_NAME="$(printf '%s\n' "$RECOVERY_RT_IDENTITY" | awk -F'\t' '$1=="NAME"{print $2}' | tr -d '[:space:]')"
  RECOVERY_RT_ARN="$(printf '%s\n' "$RECOVERY_RT_IDENTITY" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_RT_PRE="$(printf '%s\n' "$RECOVERY_RT_IDENTITY" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  RECOVERY_MG_NAME="$(printf '%s\n' "$RECOVERY_MG_IDENTITY" | awk -F'\t' '$1=="NAME"{print $2}' | tr -d '[:space:]')"
  RECOVERY_MG_ARN="$(printf '%s\n' "$RECOVERY_MG_IDENTITY" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_MG_PRE="$(printf '%s\n' "$RECOVERY_MG_IDENTITY" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  RECOVERY_TLS_NAME="$(printf '%s\n' "$RECOVERY_TLS_IDENTITY" | awk -F'\t' '$1=="NAME"{print $2}' | tr -d '[:space:]')"
  RECOVERY_TLS_ARN="$(printf '%s\n' "$RECOVERY_TLS_IDENTITY" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_TLS_PRE="$(printf '%s\n' "$RECOVERY_TLS_IDENTITY" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  if ! RECOVERY_CERT_ARN_VALUE="$(params_file_value AcmCertificateArn)"; then
    echo "refused: recovery certificate ARN missing from parameters file, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_CERT_ARN_VALUE="$(printf '%s' "$RECOVERY_CERT_ARN_VALUE" | tr -d '[:space:]')"
  [ -n "$RECOVERY_CERT_ARN_VALUE" ] || { echo "refused: recovery certificate ARN empty, no recovery claimed." >&2; phase_failed "$RECOVERY_FAIL_PHASE"; }
  RECOVERY_CERT_IDENTITY="$(fetch_cert_identity "$RECOVERY_CERT_ARN_VALUE")"
  RECOVERY_CERT_PROOF="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_CERT_PROOF" != "OK" ]; then
    echo "refused: recovery certificate proof is $RECOVERY_CERT_PROOF, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_CERT_ARN="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_DOMAIN="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="DOMAIN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_SERIAL_PRE="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="SERIAL"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_STATUS="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="STATUS"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_TYPE="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="TYPE"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_EXPORT="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="EXPORT"{print $2}' | tr -d '[:space:]')"
  ensure_recovery_dir
  RECOVERY_FILE="$LAUNCH_JOURNAL_DIR/recovery/$RECOVERY_ORIG_BASENAME.recovery.json"
  if [ -L "$RECOVERY_FILE" ]; then
    echo "refused: recovery attestation is a symlink, no recovery claimed. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "${RECOVERY_READONLY:-0}" = "1" ] && [ ! -f "$RECOVERY_FILE" ]; then
    echo "refused: enable re-proof needs prior init recovery attestation $RECOVERY_FILE but none exists. Run --phase material first to attest. No new launch." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  acquire_recovery_lock "$RECOVERY_ORIG_BASENAME"
  if [ -f "$RECOVERY_FILE" ]; then
    RECOVERY_EXISTING="$(python3 - "$RECOVERY_FILE" "$STACK_NAME" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$CLUSTER_NAME" \
      "$RECOVERY_ORIG_BASENAME" "$RECOVERY_ORIG_SHA" "$RECOVERY_ORIG_TOKEN" "$RECOVERY_ORIG_TASK" \
      "$RECOVERY_ORIG_TASKDEF" "$RECOVERY_ORIG_GEN" "$RECOVERY_ORIG_SOURCE" "$RECOVERY_ORIG_HEAD" \
      "$RECOVERY_STACK_ID" "${RECOVERY_ORIG_LEGACY:-false}" 2>/dev/null <<'PYEOF'
import hashlib, json, os, sys
(path, want_stack, want_account, want_region, want_cluster,
 want_base, want_sha, want_token, want_task,
 want_taskdef, want_gen, want_source, want_head,
 want_stack_id, want_legacy) = sys.argv[1:16]
try:
    if os.path.islink(path):
        print("PROOF\tSYMLINK")
        sys.exit(0)
    finfo = os.stat(path)
    if (finfo.st_mode & 0o777) != 0o600:
        print("PROOF\tMODE")
        sys.exit(0)
    if finfo.st_uid != os.getuid():
        print("PROOF\tOWNER")
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
try:
    if os.path.basename(path) != want_base + ".recovery.json":
        print("PROOF\tPATH_MISMATCH")
        sys.exit(0)
    if os.path.basename(os.path.dirname(os.path.abspath(path))) != "recovery":
        print("PROOF\tPATH_MISMATCH")
        sys.exit(0)
except Exception:
    print("PROOF\tPATH_MISMATCH")
    sys.exit(0)
allow = {"version", "kind", "stack", "account", "region", "cluster",
         "original_basename", "original_sha256", "original_token",
         "original_task_arn", "original_taskdef_arn", "original_generation",
         "original_source_sha", "original_target_head", "legacy_unversioned",
         "stack_id", "project", "environment", "release_generation",
         "source_sha", "target_head", "runtime_name", "runtime_arn",
         "runtime_version_pre", "runtime_version_post", "migration_name",
         "migration_arn", "migration_version_pre", "migration_version_post",
         "tls_name", "tls_arn", "tls_version_pre", "tls_version_post",
         "cert_arn", "cert_domain", "cert_serial_pre", "cert_serial_post",
         "cert_status", "cert_type", "cert_export", "verifier_token",
         "verifier_task_arn", "verifier_taskdef_arn", "verifier_proof",
         "verifier_containers", "verifier_last_status", "verifier_digest",
         "absence_proof", "outcome", "note", "updated_utc"}
for key in doc:
    if key not in allow:
        print("PROOF\tFOREIGN_FIELD")
        sys.exit(0)
for _k, _v in doc.items():
    if _k == "version":
        if not isinstance(_v, int) or isinstance(_v, bool):
            print("PROOF\tMALFORMED")
            sys.exit(0)
        continue
    if not isinstance(_v, str):
        print("PROOF\tMALFORMED")
        sys.exit(0)
for _k, _v in doc.items():
    _kl = str(_k).lower()
    if _kl in ("password", "database-url", "database_url",
               "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
               "secret_value", "secretvalue", "private_key", "privatekey",
               "certificate_body", "certificate_chain"):
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
    if isinstance(_v, str):
        _vl = _v.lower()
        if "://" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "password" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
if doc.get("version", 0) != 1 or doc.get("kind", "") != "init-recovery-attestation":
    print("PROOF\tKIND_MISMATCH")
    sys.exit(0)
if doc.get("stack", "") != want_stack or doc.get("account", "") != want_account:
    print("PROOF\tOWNER_MISMATCH")
    sys.exit(0)
if doc.get("region", "") != want_region or doc.get("cluster", "") != want_cluster:
    print("PROOF\tOWNER_MISMATCH")
    sys.exit(0)
if doc.get("original_basename", "") != want_base:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_sha256", "") != want_sha:
    print("PROOF\tORIGINAL_ALTERED")
    sys.exit(0)
if doc.get("original_token", "") != want_token:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_task_arn", "") != want_task:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_taskdef_arn", "") != want_taskdef:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_generation", "") != want_gen:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_source_sha", "") != want_source:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_target_head", "") != want_head:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("legacy_unversioned", "") not in ("true", "false"):
    print("PROOF\tLEGACY_MALFORMED")
    sys.exit(0)
if doc.get("legacy_unversioned", "") != want_legacy:
    print("PROOF\tLEGACY_MISMATCH")
    sys.exit(0)
if doc.get("stack_id", "") != want_stack_id:
    print("PROOF\tSTACKID_MISMATCH")
    sys.exit(0)
if doc.get("project", "") != "LaunchCrew" or doc.get("environment", "") != "demo":
    print("PROOF\tTAG_MISMATCH")
    sys.exit(0)
token = doc.get("verifier_token", "")
if not isinstance(token, str) or len(token) != 33 or not token.startswith("lc-"):
    print("PROOF\tVERIFIER_TOKEN_MALFORMED")
    sys.exit(0)
outcome = doc.get("outcome", "")
if not isinstance(outcome, str) or not outcome:
    print("PROOF\tOUTCOME_MISSING")
    sys.exit(0)
if outcome not in ("admitted", "started", "complete", "ambiguous_call_failed", "ambiguous_response"):
    print("PROOF\tOUTCOME_UNKNOWN")
    sys.exit(0)
if outcome == "complete":
    if doc.get("verifier_proof", "") != "OK":
        print("PROOF\tVERIFIER_PROOF_MISMATCH")
        sys.exit(0)
    if doc.get("verifier_last_status", "") != "STOPPED":
        print("PROOF\tVERIFIER_STATUS_MISMATCH")
        sys.exit(0)
    if doc.get("verifier_containers", "") != "sdk-material:STOPPED:0":
        print("PROOF\tVERIFIER_CONTAINERS_MISMATCH")
        sys.exit(0)
    _dig = doc.get("verifier_digest", "")
    if not isinstance(_dig, str) or len(_dig) != 64:
        print("PROOF\tDIGEST_MALFORMED")
        sys.exit(0)
    for _c in _dig:
        if _c not in "0123456789abcdef":
            print("PROOF\tDIGEST_MALFORMED")
            sys.exit(0)
    try:
        _parts = [
            doc.get("verifier_task_arn", ""), doc.get("verifier_token", ""),
            doc.get("verifier_taskdef_arn", ""), doc.get("verifier_containers", ""),
            doc.get("verifier_last_status", ""), doc.get("original_sha256", ""),
            doc.get("stack_id", ""), doc.get("runtime_arn", ""),
            doc.get("runtime_name", ""), doc.get("runtime_version_pre", ""),
            doc.get("runtime_version_post", ""), doc.get("migration_arn", ""),
            doc.get("migration_name", ""), doc.get("migration_version_pre", ""),
            doc.get("migration_version_post", ""), doc.get("tls_arn", ""),
            doc.get("tls_name", ""), doc.get("tls_version_pre", ""),
            doc.get("tls_version_post", ""), doc.get("cert_arn", ""),
            doc.get("cert_domain", ""), doc.get("cert_serial_pre", ""),
            doc.get("cert_serial_post", ""), doc.get("release_generation", ""),
            doc.get("source_sha", ""), doc.get("target_head", ""),
            doc.get("original_basename", ""), doc.get("legacy_unversioned", ""),
        ]
        _exp = hashlib.sha256("|".join(_parts).encode("utf-8")).hexdigest()
        if _dig != _exp:
            print("PROOF\tDIGEST_MISMATCH")
            sys.exit(0)
    except Exception:
        print("PROOF\tDIGEST_MISMATCH")
        sys.exit(0)
    if doc.get("absence_proof", "") != "OK":
        print("PROOF\tABSENCE_MISMATCH")
        sys.exit(0)
    _vtask = doc.get("verifier_task_arn", "")
    if not _vtask.startswith("arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
        print("PROOF\tVERIFIER_TASK_FOREIGN")
        sys.exit(0)
    _vtdef = doc.get("verifier_taskdef_arn", "")
    if not _vtdef.startswith("arn:aws:ecs:%s:%s:task" "-definition/" % (want_region, want_account)):
        print("PROOF\tVERIFIER_TASKDEF_FOREIGN")
        sys.exit(0)
print("PROOF\tOK")
print("OUTCOME\t%s" % outcome)
print("VTOKEN\t%s" % token)
print("VTASK\t%s" % (doc.get("verifier_task_arn", "") or ""))
print("VTASKDEF\t%s" % (doc.get("verifier_taskdef_arn", "") or ""))
print("VPROOF\t%s" % (doc.get("verifier_proof", "") or ""))
print("VCONTAINERS\t%s" % (doc.get("verifier_containers", "") or ""))
print("VLASTSTATUS\t%s" % (doc.get("verifier_last_status", "") or ""))
print("VDIGEST\t%s" % (doc.get("verifier_digest", "") or ""))
print("LEGACY\t%s" % (doc.get("legacy_unversioned", "") or ""))
print("RT_PRE\t%s" % (doc.get("runtime_version_pre", "") or ""))
print("RT_POST\t%s" % (doc.get("runtime_version_post", "") or ""))
print("RT_ARN\t%s" % (doc.get("runtime_arn", "") or ""))
print("RT_NAME\t%s" % (doc.get("runtime_name", "") or ""))
print("MG_PRE\t%s" % (doc.get("migration_version_pre", "") or ""))
print("MG_POST\t%s" % (doc.get("migration_version_post", "") or ""))
print("MG_ARN\t%s" % (doc.get("migration_arn", "") or ""))
print("MG_NAME\t%s" % (doc.get("migration_name", "") or ""))
print("TLS_PRE\t%s" % (doc.get("tls_version_pre", "") or ""))
print("TLS_POST\t%s" % (doc.get("tls_version_post", "") or ""))
print("TLS_ARN\t%s" % (doc.get("tls_arn", "") or ""))
print("TLS_NAME\t%s" % (doc.get("tls_name", "") or ""))
print("CERT_PRE\t%s" % (doc.get("cert_serial_pre", "") or ""))
print("CERT_POST\t%s" % (doc.get("cert_serial_post", "") or ""))
print("CERT_ARN\t%s" % (doc.get("cert_arn", "") or ""))
print("CERT_DOMAIN\t%s" % (doc.get("cert_domain", "") or ""))
print("CERT_STATUS\t%s" % (doc.get("cert_status", "") or ""))
print("CERT_TYPE\t%s" % (doc.get("cert_type", "") or ""))
print("CERT_EXPORT\t%s" % (doc.get("cert_export", "") or ""))
print("REL_GEN\t%s" % (doc.get("release_generation", "") or ""))
print("REL_SOURCE\t%s" % (doc.get("source_sha", "") or ""))
print("REL_HEAD\t%s" % (doc.get("target_head", "") or ""))
PYEOF
)" || RECOVERY_EXISTING="PROOF\tUNREADABLE"
    RECOVERY_EXIST_PROOF="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$RECOVERY_EXIST_PROOF" != "OK" ]; then
      release_recovery_lock
      echo "refused: existing recovery attestation is $RECOVERY_EXIST_PROOF, no new verifier. Inspect $RECOVERY_FILE and $RECOVERY_ORIG_PATH." >&2
      phase_failed "$RECOVERY_FAIL_PHASE"
    fi
    RECOVERY_EXIST_OUTCOME="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
    RECOVERY_EXIST_VTOKEN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="VTOKEN"{print $2}' | tr -d '[:space:]')"
    RECOVERY_EXIST_VTASK="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="VTASK"{print $2}' | tr -d '[:space:]')"
    RECOVERY_EXIST_VTASKDEF="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="VTASKDEF"{print $2}' | tr -d '[:space:]')"
    if [ "$RECOVERY_EXIST_OUTCOME" = "complete" ]; then
      RECOVERY_ATTEST_RT_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_RT_POST="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_POST"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_RT_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_RT_NAME="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_NAME"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_MG_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_MG_POST="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_POST"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_MG_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_MG_NAME="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_NAME"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_TLS_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_TLS_POST="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_POST"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_TLS_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_TLS_NAME="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_NAME"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_CERT_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_CERT_POST="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_POST"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_CERT_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_CERT_DOMAIN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_DOMAIN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_REL_GEN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_GEN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_REL_SOURCE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_SOURCE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_REL_HEAD="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_HEAD"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_VPROOF="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="VPROOF"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_VCONTAINERS="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="VCONTAINERS"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_VLASTSTATUS="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="VLASTSTATUS"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_VDIGEST="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="VDIGEST"{print $2}' | tr -d '[:space:]')"
      if [ "$RECOVERY_RT_PRE" != "$RECOVERY_ATTEST_RT_PRE" ] || [ "$RECOVERY_RT_PRE" != "$RECOVERY_ATTEST_RT_POST" ]; then
        release_recovery_lock
        echo "refused: live runtime VersionId changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_MG_PRE" != "$RECOVERY_ATTEST_MG_PRE" ] || [ "$RECOVERY_MG_PRE" != "$RECOVERY_ATTEST_MG_POST" ]; then
        release_recovery_lock
        echo "refused: live migration VersionId changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_TLS_PRE" != "$RECOVERY_ATTEST_TLS_PRE" ] || [ "$RECOVERY_TLS_PRE" != "$RECOVERY_ATTEST_TLS_POST" ]; then
        release_recovery_lock
        echo "refused: live TLS VersionId changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_CERT_SERIAL_PRE" != "$RECOVERY_ATTEST_CERT_PRE" ] || [ "$RECOVERY_CERT_SERIAL_PRE" != "$RECOVERY_ATTEST_CERT_POST" ]; then
        release_recovery_lock
        echo "refused: live certificate serial changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_RT_ARN" != "$RECOVERY_ATTEST_RT_ARN" ] || [ "$RECOVERY_ATTEST_RT_ARN" != "$RUNTIME_SECRET_ARN" ]; then
        release_recovery_lock
        echo "refused: recovery runtime ARN does not equal exact owned ARN, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_RT_NAME" != "$RECOVERY_ATTEST_RT_NAME" ]; then
        release_recovery_lock
        echo "refused: live runtime Name changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_MG_ARN" != "$RECOVERY_ATTEST_MG_ARN" ] || [ "$RECOVERY_ATTEST_MG_ARN" != "$MIGRATION_SECRET_ARN" ]; then
        release_recovery_lock
        echo "refused: recovery migration ARN does not equal exact owned ARN, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_MG_NAME" != "$RECOVERY_ATTEST_MG_NAME" ]; then
        release_recovery_lock
        echo "refused: live migration Name changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_TLS_ARN" != "$RECOVERY_ATTEST_TLS_ARN" ] || [ "$RECOVERY_ATTEST_TLS_ARN" != "$TLS_SECRET_ARN" ]; then
        release_recovery_lock
        echo "refused: recovery TLS ARN does not equal exact owned ARN, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_TLS_NAME" != "$RECOVERY_ATTEST_TLS_NAME" ]; then
        release_recovery_lock
        echo "refused: live TLS Name changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_CERT_ARN" != "$RECOVERY_ATTEST_CERT_ARN" ] || [ "$RECOVERY_ATTEST_CERT_ARN" != "$RECOVERY_CERT_ARN_VALUE" ]; then
        release_recovery_lock
        echo "refused: recovery certificate ARN does not equal exact owned ARN, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_CERT_DOMAIN" != "$RECOVERY_ATTEST_CERT_DOMAIN" ]; then
        release_recovery_lock
        echo "refused: live certificate domain changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_ATTEST_REL_GEN" != "${RELEASE_GEN:-}" ] || [ "$RECOVERY_ATTEST_REL_HEAD" != "${TARGET_DB_HEAD:-008}" ]; then
        release_recovery_lock
        echo "refused: recovery attestation release generation or head does not equal current owned release, same-release restart only with no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_ATTEST_REL_SOURCE" != "${SOURCE_SHA:-}" ]; then
        release_recovery_lock
        echo "refused: recovery attestation source SHA does not equal current owned source, same-release restart only with no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      [ -n "$RECOVERY_EXIST_VTASK" ] && [ "$RECOVERY_EXIST_VTASK" != "None" ] || {
        release_recovery_lock
        echo "refused: recovery attestation complete has no verifier task, cannot re-prove. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      }
      [ -n "$RECOVERY_EXIST_VTASKDEF" ] && [ "$RECOVERY_EXIST_VTASKDEF" != "None" ] || {
        release_recovery_lock
        echo "refused: recovery attestation complete has no verifier taskdef, cannot re-prove. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      }
      if [ "$RECOVERY_ATTEST_VPROOF" != "OK" ] || [ "$RECOVERY_ATTEST_VLASTSTATUS" != "STOPPED" ] || [ "$RECOVERY_ATTEST_VCONTAINERS" != "sdk-material:STOPPED:0" ] || [ -z "$RECOVERY_ATTEST_VDIGEST" ]; then
        release_recovery_lock
        echo "refused: recovery attestation complete terminal proof is incomplete, cannot re-prove. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      RECOVERY_REVERIFY_DESC="$(mktemp /tmp/launchcrew-reverify-XXXXXX)"
      if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$RECOVERY_EXIST_VTASK" --region "$EXPECTED_REGION" --output json >"$RECOVERY_REVERIFY_DESC" 2>"$TMP_ERR"; then
        rm -f "$RECOVERY_REVERIFY_DESC"
        release_recovery_lock
        echo "refused: recovery verifier terminal state unreadable, not treated as success. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      RECOVERY_REVERIFY_PRESENCE="$(python3 - "$RECOVERY_REVERIFY_DESC" "$RECOVERY_EXIST_VTASK" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("UNREADABLE")
    sys.exit(0)
expected = sys.argv[2] if len(sys.argv) > 2 else ""
if not isinstance(doc, dict):
    print("UNREADABLE")
    sys.exit(0)
if "tasks" not in doc or "failures" not in doc:
    print("AMBIGUOUS_RESPONSE")
    sys.exit(0)
tasks = doc.get("tasks")
failures = doc.get("failures")
if not isinstance(tasks, list) or not isinstance(failures, list):
    print("AMBIGUOUS_RESPONSE")
    sys.exit(0)
for entry in tasks:
    if not isinstance(entry, dict):
        print("AMBIGUOUS_RESPONSE")
        sys.exit(0)
for entry in failures:
    if not isinstance(entry, dict):
        print("AMBIGUOUS_RESPONSE")
        sys.exit(0)
    if not isinstance(entry.get("arn"), str) or not isinstance(entry.get("reason"), str):
        print("AMBIGUOUS_RESPONSE")
        sys.exit(0)
if tasks and failures:
    print("AMBIGUOUS_MIXED")
    sys.exit(0)
if tasks and not failures:
    print("PRESENT")
    sys.exit(0)
if not tasks and not failures:
    print("AMBIGUOUS_EMPTY")
    sys.exit(0)
if len(failures) != 1:
    print("AMBIGUOUS_FAILURES")
    sys.exit(0)
single = failures[0]
if single.get("reason") != "MISSING":
    print("AMBIGUOUS_REASON")
    sys.exit(0)
if not expected or single.get("arn") != expected:
    print("AMBIGUOUS_ARN")
    sys.exit(0)
print("NO_TASK")
PYEOF
)" || RECOVERY_REVERIFY_PRESENCE="UNREADABLE"
      rm -f "$RECOVERY_REVERIFY_DESC"
      RECOVERY_REVERIFY_PRESENCE="$(printf '%s' "$RECOVERY_REVERIFY_PRESENCE" | tr -d '[:space:]')"
      if [ "$RECOVERY_REVERIFY_PRESENCE" = "NO_TASK" ]; then
        prove_no_running_for_startedby "$RECOVERY_ORIG_TOKEN" "recovery re-verify" "$RECOVERY_ORIG_TASK"
        RECOVERY_ABSENCE_PROOF="OK"
        release_recovery_lock
        echo "recovery re-verified via persisted one-shot terminal proof after verifier retention expiry: original $RECOVERY_ORIG_BASENAME unchanged, fresh desired state intact, no live verifier claim, no new verifier, no resend. Not retroactive proof."
        return 0
      fi
      if [ "$RECOVERY_REVERIFY_PRESENCE" != "PRESENT" ]; then
        release_recovery_lock
        echo "refused: recovery verifier presence is $RECOVERY_REVERIFY_PRESENCE, cannot re-prove. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      prove_recovery_verifier_terminal "$RECOVERY_EXIST_VTASK" "$RECOVERY_EXIST_VTOKEN" "$RECOVERY_EXIST_VTASKDEF"
      prove_no_running_for_startedby "$RECOVERY_ORIG_TOKEN" "recovery re-verify" "$RECOVERY_ORIG_TASK"
      RECOVERY_ABSENCE_PROOF="OK"
      release_recovery_lock
      echo "recovery re-verified: original $RECOVERY_ORIG_BASENAME unchanged, live material and verifier still prove desired-state equivalence, not retroactive proof."
      return 0
    fi
    if [ "$RECOVERY_EXIST_OUTCOME" = "started" ] && [ -n "$RECOVERY_EXIST_VTASK" ] && [ "$RECOVERY_EXIST_VTASK" != "None" ]; then
      if [ "${RECOVERY_READONLY:-0}" = "1" ]; then
        release_recovery_lock
        echo "refused: enable re-proof needs complete recovery attestation but existing is $RECOVERY_EXIST_OUTCOME unresolved. Run --phase material to reconcile first. No new launch." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      [ -n "$RECOVERY_EXIST_VTASKDEF" ] && [ "$RECOVERY_EXIST_VTASKDEF" != "None" ] || {
        release_recovery_lock
        echo "refused: recovery $RECOVERY_EXIST_OUTCOME has no verifier taskdef, manual review required. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      }
      RECOVERY_RESUME_RT_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_MG_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_TLS_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_CERT_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_RT_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_MG_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_TLS_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_CERT_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_REL_GEN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_GEN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_REL_HEAD="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_HEAD"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_REL_SOURCE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_SOURCE"{print $2}' | tr -d '[:space:]')"
      if [ "$RECOVERY_RT_PRE" != "$RECOVERY_RESUME_RT_PRE" ]; then
        release_recovery_lock
        echo "refused: live runtime VersionId changed during recovery resume, no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_MG_PRE" != "$RECOVERY_RESUME_MG_PRE" ]; then
        release_recovery_lock
        echo "refused: live migration VersionId changed during recovery resume, no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_TLS_PRE" != "$RECOVERY_RESUME_TLS_PRE" ]; then
        release_recovery_lock
        echo "refused: live TLS VersionId changed during recovery resume, no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_CERT_SERIAL_PRE" != "$RECOVERY_RESUME_CERT_PRE" ]; then
        release_recovery_lock
        echo "refused: live certificate serial changed during recovery resume, no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_RT_ARN" != "$RECOVERY_RESUME_RT_ARN" ] || [ "$RECOVERY_MG_ARN" != "$RECOVERY_RESUME_MG_ARN" ] || [ "$RECOVERY_TLS_ARN" != "$RECOVERY_RESUME_TLS_ARN" ] || [ "$RECOVERY_CERT_ARN" != "$RECOVERY_RESUME_CERT_ARN" ]; then
        release_recovery_lock
        echo "refused: live material ARN changed during recovery resume, no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_RESUME_REL_GEN" != "${RELEASE_GEN:-}" ] || [ "$RECOVERY_RESUME_REL_HEAD" != "${TARGET_DB_HEAD:-008}" ] || [ "$RECOVERY_RESUME_REL_SOURCE" != "${SOURCE_SHA:-}" ]; then
        release_recovery_lock
        echo "refused: recovery resume release does not equal current owned release, same-release only with no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      echo "recovery prior $RECOVERY_EXIST_OUTCOME unresolved, reconciling recorded verifier with no new RunTask."
      prove_recovery_verifier_terminal "$RECOVERY_EXIST_VTASK" "$RECOVERY_EXIST_VTOKEN" "$RECOVERY_EXIST_VTASKDEF"
      RECOVERY_VERIFIER_TOKEN="$RECOVERY_EXIST_VTOKEN"
      RECOVERY_VERIFIER_TASK="$RECOVERY_EXIST_VTASK"
      RECOVERY_VERIFIER_TASKDEF="$RECOVERY_EXIST_VTASKDEF"
      RECOVERY_RT_POST="$RECOVERY_RT_PRE"
      RECOVERY_MG_POST="$RECOVERY_MG_PRE"
      RECOVERY_TLS_POST="$RECOVERY_TLS_PRE"
      RECOVERY_CERT_SERIAL_POST="$RECOVERY_CERT_SERIAL_PRE"
      RECOVERY_VERIFIER_PROOF="OK"
      RECOVERY_VERIFIER_CONTAINERS="sdk-material:STOPPED:0"
      RECOVERY_VERIFIER_LAST_STATUS="STOPPED"
      compute_recovery_verifier_digest
      prove_no_running_for_startedby "$RECOVERY_ORIG_TOKEN" "recovery resume" "$RECOVERY_ORIG_TASK"
      RECOVERY_ABSENCE_PROOF="OK"
      write_recovery_attestation "$RECOVERY_FILE" "complete"
      release_recovery_lock
      echo "recovery resumed to complete: desired-state equivalence for $RECOVERY_ORIG_BASENAME, not retroactive proof."
      return 0
    fi
    release_recovery_lock
    echo "refused: existing recovery is $RECOVERY_EXIST_OUTCOME unresolved, manual review required with no new verifier and no resend. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "${RECOVERY_READONLY:-0}" = "1" ]; then
    release_recovery_lock
    echo "refused: enable re-proof needs complete recovery attestation but none exists. Run --phase material first to attest. No new launch." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_VERIFIER_TASKDEF="$(stack_resource SdkMaterialTaskDefinition 2>"$TMP_ERR")"; then
    release_recovery_lock
    echo "refused: recovery verifier task definition lookup failed, no verifier claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_VERIFIER_TASKDEF="$(printf '%s' "$RECOVERY_VERIFIER_TASKDEF" | tr -d '[:space:]')"
  [ -n "$RECOVERY_VERIFIER_TASKDEF" ] && [ "$RECOVERY_VERIFIER_TASKDEF" != "None" ] || {
    release_recovery_lock
    echo "refused: recovery verifier task definition missing, no verifier claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  }
  check_sdk_taskdef SdkMaterialTaskDefinition SdkMaterialExecutionRole SdkMaterialTaskRole sdk-material --verify-material
  if ! RECOVERY_VERIFIER_TOKEN="$(python3 - 2>/dev/null <<'PYEOF'
import uuid
print("lc-" + uuid.uuid4().hex[:30])
PYEOF
)"; then
    release_recovery_lock
    echo "recovery verifier token generation failed, no verifier claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_VERIFIER_TOKEN="$(printf '%s' "$RECOVERY_VERIFIER_TOKEN" | tr -d '[:space:]')"
  case "$RECOVERY_VERIFIER_TOKEN" in
    lc-??????????????????????????????) ;;
    *) release_recovery_lock; echo "recovery verifier token malformed, no verifier claimed." >&2; phase_failed "$RECOVERY_FAIL_PHASE" ;;
  esac
  RECOVERY_VERIFIER_TASK=""
  RECOVERY_RT_POST=""
  RECOVERY_MG_POST=""
  RECOVERY_TLS_POST=""
  RECOVERY_CERT_SERIAL_POST=""
  RECOVERY_VERIFIER_PROOF=""
  RECOVERY_VERIFIER_CONTAINERS=""
  RECOVERY_VERIFIER_LAST_STATUS=""
  RECOVERY_VERIFIER_DIGEST=""
  RECOVERY_ABSENCE_PROOF=""
  write_recovery_attestation "$RECOVERY_FILE" "admitted"
  echo "recovery admission persisted before verifier RunTask: $RECOVERY_FILE"
  if ! RECOVERY_SUBNET_A="$(stack_resource PublicSubnetA 2>"$TMP_ERR")"; then
    echo "refused: recovery subnets unreadable after admission, manual review required. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_SUBNET_B="$(stack_resource PublicSubnetB 2>"$TMP_ERR")"; then
    echo "refused: recovery subnets unreadable after admission, manual review required. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_JOB_SG="$(stack_resource JobSecurityGroup 2>"$TMP_ERR")"; then
    echo "refused: recovery security group unreadable after admission, manual review required. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_SUBNET_A="$(printf '%s' "$RECOVERY_SUBNET_A" | tr -d '[:space:]')"
  RECOVERY_SUBNET_B="$(printf '%s' "$RECOVERY_SUBNET_B" | tr -d '[:space:]')"
  RECOVERY_JOB_SG="$(printf '%s' "$RECOVERY_JOB_SG" | tr -d '[:space:]')"
  RECOVERY_RUN_JSON="$(mktemp /tmp/launchcrew-recrun-XXXXXX)"
  RECOVERY_RUN_OK=1
  if ! "$AWS_BIN" ecs run-task --cluster "$CLUSTER_NAME" --task"-definition" "$RECOVERY_VERIFIER_TASKDEF" --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$RECOVERY_SUBNET_A,$RECOVERY_SUBNET_B],securityGroups=[$RECOVERY_JOB_SG],assignPublicIp=ENABLED}" --client-token "$RECOVERY_VERIFIER_TOKEN" --started-by "$RECOVERY_VERIFIER_TOKEN" --region "$EXPECTED_REGION" --output json >"$RECOVERY_RUN_JSON" 2>"$TMP_ERR"; then
    RECOVERY_RUN_OK=0
  fi
  if [ "$RECOVERY_RUN_OK" -eq 0 ]; then
    rm -f "$RECOVERY_RUN_JSON"
    write_recovery_attestation "$RECOVERY_FILE" "ambiguous_call_failed"
    release_recovery_lock
    echo "refused: recovery verifier run-task call failed; launch is ambiguous with no resend. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_VERIFIER_TASK="$(python3 - "$RECOVERY_RUN_JSON" 2>/dev/null <<'PYEOF'
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
)" || RECOVERY_VERIFIER_TASK="UNREADABLE"
  rm -f "$RECOVERY_RUN_JSON"
  RECOVERY_VERIFIER_TASK="$(printf '%s' "$RECOVERY_VERIFIER_TASK" | tr -d '[:space:]')"
  case "$RECOVERY_VERIFIER_TASK" in
    FAILURES|EMPTY|MULTIPLE|UNREADABLE|"")
      write_recovery_attestation "$RECOVERY_FILE" "ambiguous_response"
      release_recovery_lock
      echo "refused: recovery verifier run-task response is ${RECOVERY_VERIFIER_TASK:-empty}; launch is ambiguous with no resend. Inspect $RECOVERY_FILE." >&2
      phase_failed "$RECOVERY_FAIL_PHASE" ;;
  esac
  write_recovery_attestation "$RECOVERY_FILE" "started"
  echo "recovery verifier started: $RECOVERY_VERIFIER_TASK"
  prove_recovery_verifier_terminal "$RECOVERY_VERIFIER_TASK" "$RECOVERY_VERIFIER_TOKEN" "$RECOVERY_VERIFIER_TASKDEF"
  RECOVERY_POST_RT="$(fetch_secret_version_identity "$RUNTIME_SECRET_ARN" runtime)"
  RECOVERY_POST_RT_PROOF="$(printf '%s\n' "$RECOVERY_POST_RT" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_POST_RT_PROOF" != "OK" ]; then
    echo "refused: recovery post runtime proof is $RECOVERY_POST_RT_PROOF, material changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_POST_MG="$(fetch_secret_version_identity "$MIGRATION_SECRET_ARN" migration)"
  RECOVERY_POST_MG_PROOF="$(printf '%s\n' "$RECOVERY_POST_MG" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_POST_MG_PROOF" != "OK" ]; then
    echo "refused: recovery post migration proof is $RECOVERY_POST_MG_PROOF, material changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_POST_TLS="$(fetch_secret_version_identity "$TLS_SECRET_ARN" tls)"
  RECOVERY_POST_TLS_PROOF="$(printf '%s\n' "$RECOVERY_POST_TLS" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_POST_TLS_PROOF" != "OK" ]; then
    echo "refused: recovery post TLS proof is $RECOVERY_POST_TLS_PROOF, material changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_POST_CERT="$(fetch_cert_identity "$RECOVERY_CERT_ARN_VALUE")"
  RECOVERY_POST_CERT_PROOF="$(printf '%s\n' "$RECOVERY_POST_CERT" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_POST_CERT_PROOF" != "OK" ]; then
    echo "refused: recovery post certificate proof is $RECOVERY_POST_CERT_PROOF, material changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_RT_POST="$(printf '%s\n' "$RECOVERY_POST_RT" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  RECOVERY_MG_POST="$(printf '%s\n' "$RECOVERY_POST_MG" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  RECOVERY_TLS_POST="$(printf '%s\n' "$RECOVERY_POST_TLS" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_SERIAL_POST="$(printf '%s\n' "$RECOVERY_POST_CERT" | awk -F'\t' '$1=="SERIAL"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_RT_POST" != "$RECOVERY_RT_PRE" ]; then
    echo "refused: runtime VersionId changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "$RECOVERY_MG_POST" != "$RECOVERY_MG_PRE" ]; then
    echo "refused: migration VersionId changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "$RECOVERY_TLS_POST" != "$RECOVERY_TLS_PRE" ]; then
    echo "refused: TLS VersionId changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "$RECOVERY_CERT_SERIAL_POST" != "$RECOVERY_CERT_SERIAL_PRE" ]; then
    echo "refused: certificate serial changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_VERIFIER_CONTAINERS="sdk-material:STOPPED:0"
  RECOVERY_VERIFIER_LAST_STATUS="STOPPED"
  compute_recovery_verifier_digest
  prove_no_running_for_startedby "$RECOVERY_ORIG_TOKEN" "recovery" "$RECOVERY_ORIG_TASK"
  RECOVERY_ABSENCE_PROOF="OK"
  write_recovery_attestation "$RECOVERY_FILE" "complete"
  release_recovery_lock
  echo "recovery complete: $RECOVERY_ORIG_BASENAME attested via read-only verifier $RECOVERY_VERIFIER_TASK; desired-state equivalence, not retroactive proof."
}

# Attest an aged-out prior typed journal via a separate read-only verifier.
# Args: fail phase, original path, original basename, phase, label, logical,
# kind, verifier logical, verifier container, allow_started (0/1),
# allow_exit10 (0/1). Validates exact owned StackId, tags, heads, original
# ownership, digest, taskdef operation, roles, image, token, plus exact
# current owned secret names, ARNs, VersionIds and certificate identity
# before and after verification. Persists admission before any verifier
# RunTask, requires live STOPPED with allowed exit and exact identities,
# then persists a mode 600 typed attestation with bound one-shot proof.
# On restart with complete, validates immutable schema, original hash and
# ownership, current StackId, tags, material, generation, source, head,
# plus the bounded point-in-time gate for the old startedBy in two stable
# rounds. If verifier still live, rechecks terminal; if aged out, permits
# only for exact MISSING plus intact proof and fresh desired state, never
# claiming live status after expiry or retroactive old exit. Never Put,
# Export, bind, migrate, or resend through this route. Binder STARTED
# originals never relabel as completed. Returns 0 on recovered, else fails.
attest_aged_typed_recovery() {
  RECOVERY_FAIL_PHASE="$1"
  RECOVERY_ORIG_PATH="$2"
  RECOVERY_ORIG_BASENAME="$3"
  RECOVERY_TYPED_PHASE="$4"
  RECOVERY_TYPED_LABEL="$5"
  RECOVERY_TYPED_LOGICAL="$6"
  RECOVERY_KIND="$7"
  RECOVERY_VERIFIER_LOGICAL="$8"
  RECOVERY_VERIFIER_CONTAINER="$9"
  RECOVERY_ALLOW_STARTED="${10:-0}"
  RECOVERY_ALLOW10="${11:-0}"
  RECOVERY_OBSERVED_HEAD=""
  RECOVERY_VERIFIER_EXIT=""
  if [ -z "$LAUNCH_JOURNAL_DIR" ] || [ ! -d "$LAUNCH_JOURNAL_DIR" ]; then
    echo "refused: recovery needs journal directory with prior $RECOVERY_TYPED_LABEL record, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ -L "$LAUNCH_JOURNAL_DIR" ]; then
    echo "recovery journal directory is a symlink, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_ORIG_SHA="$(sha256_of_file "$RECOVERY_ORIG_PATH")"; then
    echo "refused: original $RECOVERY_TYPED_LABEL journal hash unreadable, no recovery claimed. Inspect $RECOVERY_ORIG_PATH." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_ORIG_SHA="$(printf '%s' "$RECOVERY_ORIG_SHA" | tr -d '[:space:]')"
  [ -n "$RECOVERY_ORIG_SHA" ] || {
    echo "refused: original $RECOVERY_TYPED_LABEL journal hash empty, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  }
  RECOVERY_VALIDATED="$(validate_typed_journal_for_recovery "$RECOVERY_ORIG_PATH" "$RECOVERY_ORIG_BASENAME" "$RECOVERY_TYPED_PHASE" "$RECOVERY_TYPED_LABEL" "$RECOVERY_TYPED_LOGICAL" "$RECOVERY_ALLOW_STARTED")" || RECOVERY_VALIDATED="PROOF\tUNREADABLE"
  RECOVERY_VALID_PROOF="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_VALID_PROOF" != "OK" ]; then
    RECOVERY_VALID_OUTCOME="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
    echo "refused: original $RECOVERY_TYPED_LABEL journal $RECOVERY_ORIG_BASENAME is $RECOVERY_VALID_PROOF ${RECOVERY_VALID_OUTCOME:-}, no recovery claimed. Inspect $RECOVERY_ORIG_PATH." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_ORIG_TOKEN="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="TOKEN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_TASK="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="TASKARN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_TASKDEF="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="TASKDEF"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_GEN="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="GEN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_SOURCE="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="SOURCE"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_HEAD="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="HEAD"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_STACKID="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="STACKID"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_OUTCOME="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
  RECOVERY_ORIG_LEGACY="$(printf '%s\n' "$RECOVERY_VALIDATED" | awk -F'\t' '$1=="LEGACY"{print $2}' | tr -d '[:space:]')"
  [ "$RECOVERY_ORIG_LEGACY" = "true" ] || RECOVERY_ORIG_LEGACY="false"
  [ -n "$RECOVERY_ORIG_OUTCOME" ] || RECOVERY_ORIG_OUTCOME="complete"
  validate_stack_for_recovery
  if [ -n "$RECOVERY_ORIG_STACKID" ] && [ "$RECOVERY_ORIG_STACKID" != "$RECOVERY_STACK_ID" ]; then
    echo "refused: original $RECOVERY_TYPED_LABEL StackId does not equal the owned StackId, no recovery claimed. Inspect $RECOVERY_ORIG_PATH." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_ORIG_DEF_JSON="$(mktemp /tmp/launchcrew-recorig-XXXXXX)"
  if ! "$AWS_BIN" ecs "describe-task""-definition" --task"-definition" "$RECOVERY_ORIG_TASKDEF" --region "$EXPECTED_REGION" --output json >"$RECOVERY_ORIG_DEF_JSON" 2>"$TMP_ERR"; then
    rm -f "$RECOVERY_ORIG_DEF_JSON"
    echo "refused: original $RECOVERY_TYPED_LABEL taskdef unreadable, no recovery claimed. Inspect $RECOVERY_ORIG_PATH." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  case "$RECOVERY_TYPED_LOGICAL" in
    SdkMaterialTaskDefinition)
      RECOVERY_EXPECT_EXEC_L="SdkMaterialExecutionRole"
      RECOVERY_EXPECT_TASK_L="SdkMaterialTaskRole"
      RECOVERY_EXPECT_C="sdk-material"
      RECOVERY_EXPECT_CMD="--verify-material"
      RECOVERY_EXPECT_EP="1"
      RECOVERY_EXPECT_IMAGE="${BOOTSTRAP_IMAGE:-}" ;;
    BootstrapTaskDefinition)
      RECOVERY_EXPECT_EXEC_L="BootstrapExecutionRole"
      RECOVERY_EXPECT_TASK_L="BootstrapTaskRole"
      RECOVERY_EXPECT_C="bootstrap-db-roles"
      RECOVERY_EXPECT_CMD="ABSENT"
      RECOVERY_EXPECT_EP="ABSENT"
      RECOVERY_EXPECT_IMAGE="${BOOTSTRAP_IMAGE:-}" ;;
    MigrationTaskDefinition)
      RECOVERY_EXPECT_EXEC_L="MigrationExecutionRole"
      RECOVERY_EXPECT_TASK_L="MigrationTaskRole"
      RECOVERY_EXPECT_C="migration"
      RECOVERY_EXPECT_CMD="ABSENT"
      RECOVERY_EXPECT_EP="ABSENT"
      RECOVERY_EXPECT_IMAGE="${MIGRATION_IMAGE:-}" ;;
    VerifyTaskDefinition)
      RECOVERY_EXPECT_EXEC_L="VerifyExecutionRole"
      RECOVERY_EXPECT_TASK_L="VerifyTaskRole"
      RECOVERY_EXPECT_C="bootstrap-db-roles"
      RECOVERY_EXPECT_CMD="--verify"
      RECOVERY_EXPECT_EP="ABSENT"
      RECOVERY_EXPECT_IMAGE="${BOOTSTRAP_IMAGE:-}" ;;
    *) rm -f "$RECOVERY_ORIG_DEF_JSON"
      echo "refused: original $RECOVERY_TYPED_LABEL logical $RECOVERY_TYPED_LOGICAL unknown, no recovery claimed." >&2
      phase_failed "$RECOVERY_FAIL_PHASE" ;;
  esac
  if ! RECOVERY_EXPECT_EXEC="$(resolve_role_arn "$RECOVERY_EXPECT_EXEC_L")"; then
    rm -f "$RECOVERY_ORIG_DEF_JSON"
    echo "refused: original $RECOVERY_TYPED_LABEL expected execution role unresolvable, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_EXPECT_TASK_ROLE="$(resolve_role_arn "$RECOVERY_EXPECT_TASK_L")"; then
    rm -f "$RECOVERY_ORIG_DEF_JSON"
    echo "refused: original $RECOVERY_TYPED_LABEL expected task role unresolvable, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_EXPECT_EXEC="$(printf '%s' "$RECOVERY_EXPECT_EXEC" | tr -d '[:space:]')"
  RECOVERY_EXPECT_TASK_ROLE="$(printf '%s' "$RECOVERY_EXPECT_TASK_ROLE" | tr -d '[:space:]')"
  RECOVERY_EXPECT_IMAGE="$(printf '%s' "${RECOVERY_EXPECT_IMAGE:-}" | tr -d '[:space:]')"
  if [ -z "$RECOVERY_EXPECT_IMAGE" ] || [ "$RECOVERY_EXPECT_IMAGE" = "None" ]; then
    rm -f "$RECOVERY_ORIG_DEF_JSON"
    echo "refused: original $RECOVERY_TYPED_LABEL expected image missing, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  case "$RECOVERY_TYPED_LOGICAL" in
    BootstrapTaskDefinition)
      [ -n "${MASTER_SECRET_ARN:-}" ] && [ -n "${RUNTIME_SECRET_ARN:-}" ] && [ -n "${MIGRATION_SECRET_ARN:-}" ] || {
        rm -f "$RECOVERY_ORIG_DEF_JSON"
        echo "refused: original $RECOVERY_TYPED_LABEL needs exact master, runtime and migration secret ARNs for operation proof, no recovery claimed." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      } ;;
    MigrationTaskDefinition)
      [ -n "${MIGRATION_SECRET_ARN:-}" ] || {
        rm -f "$RECOVERY_ORIG_DEF_JSON"
        echo "refused: original $RECOVERY_TYPED_LABEL needs exact migration secret ARN for operation proof, no recovery claimed." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      } ;;
    VerifyTaskDefinition)
      [ -n "${RUNTIME_SECRET_ARN:-}" ] || {
        rm -f "$RECOVERY_ORIG_DEF_JSON"
        echo "refused: original $RECOVERY_TYPED_LABEL needs exact runtime secret ARN for operation proof, no recovery claimed." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      } ;;
  esac
  RECOVERY_ACTUAL_IMAGE="$(python3 - "$RECOVERY_ORIG_DEF_JSON" "$RECOVERY_EXPECT_C" 2>/dev/null <<'PYEOF'
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
)" || RECOVERY_ACTUAL_IMAGE="UNREADABLE"
  RECOVERY_ACTUAL_IMAGE="$(printf '%s' "$RECOVERY_ACTUAL_IMAGE" | tr -d '[:space:]')"
  if [ -n "$RECOVERY_ACTUAL_IMAGE" ] && [ "$RECOVERY_ACTUAL_IMAGE" != "MISSING_CONTAINER" ] && [ "$RECOVERY_ACTUAL_IMAGE" != "MISSING_IMAGE" ] && [ "$RECOVERY_ACTUAL_IMAGE" != "UNREADABLE" ] && [ "$RECOVERY_ACTUAL_IMAGE" != "None" ] && [ "$RECOVERY_ACTUAL_IMAGE" != "$RECOVERY_EXPECT_IMAGE" ]; then
    case "$RECOVERY_TYPED_LOGICAL" in
      MigrationTaskDefinition) RECOVERY_HIST_REPO="launchcrew-migration" ;;
      *) RECOVERY_HIST_REPO="launchcrew-bootstrap" ;;
    esac
    if ! verify_historical_image "$RECOVERY_ACTUAL_IMAGE" "$RECOVERY_HIST_REPO" "$RECOVERY_TYPED_LABEL"; then
      rm -f "$RECOVERY_ORIG_DEF_JSON"
      phase_failed "$RECOVERY_FAIL_PHASE"
    fi
    RECOVERY_EXPECT_IMAGE="$RECOVERY_ACTUAL_IMAGE"
    echo "Verified original $RECOVERY_TYPED_LABEL historical image differs from current CLI but is owned pinned with digest, operation proof continues."
  fi
  RECOVERY_ORIG_OP="$(python3 - "$RECOVERY_ORIG_DEF_JSON" "$RECOVERY_EXPECT_EXEC" "$RECOVERY_EXPECT_TASK_ROLE" "$RECOVERY_EXPECT_C" "$RECOVERY_EXPECT_CMD" "$RECOVERY_EXPECT_EP" "$RECOVERY_EXPECT_IMAGE" "${RUNTIME_SECRET_ARN:-}" "${MIGRATION_SECRET_ARN:-}" "${MASTER_SECRET_ARN:-}" "$RECOVERY_TYPED_LOGICAL" 2>/dev/null <<'PYEOF'
import json, sys
(doc_file, want_exec, want_task, want_c, want_cmd, want_ep,
 want_image, want_rt, want_mg, want_master, want_logical) = sys.argv[1:12]
try:
    doc = json.load(open(doc_file))
except Exception:
    sys.exit(1)
taskdef = doc.get("taskDefinition", doc)
if (taskdef.get("executionRoleArn", "") or "") != want_exec:
    print("TASKDEF_OPERATION_MISMATCH:EXEC_ROLE")
    sys.exit(0)
if (taskdef.get("taskRoleArn", "") or "") != want_task:
    print("TASKDEF_OPERATION_MISMATCH:TASK_ROLE")
    sys.exit(0)
containers = taskdef.get("containerDefinitions", None)
if not isinstance(containers, list) or len(containers) != 1:
    print("TASKDEF_OPERATION_MISMATCH:CONTAINER_COUNT")
    sys.exit(0)
target = containers[0]
if not isinstance(target, dict):
    print("TASKDEF_OPERATION_MISMATCH:MISSING_CONTAINER")
    sys.exit(0)
if (target.get("name", "") or "") != want_c or not target.get("essential", True):
    print("TASKDEF_OPERATION_MISMATCH:MISSING_CONTAINER")
    sys.exit(0)
if not want_image or want_image == "None":
    print("TASKDEF_OPERATION_MISMATCH:IMAGE_MISSING")
    sys.exit(0)
if (target.get("image", "") or "") != want_image:
    print("TASKDEF_OPERATION_MISMATCH:IMAGE")
    sys.exit(0)
if want_ep == "1":
    if (target.get("entryPoint", None) or []) != ["/opt/venv/bin/python", "/app/scripts/populate_prereqs.py"]:
        print("TASKDEF_OPERATION_MISMATCH:ENTRYPOINT")
        sys.exit(0)
elif want_ep == "ABSENT":
    _ep = target.get("entryPoint", None)
    if _ep not in (None, []):
        print("TASKDEF_OPERATION_MISMATCH:ENTRYPOINT")
        sys.exit(0)
else:
    print("TASKDEF_OPERATION_MISMATCH:ENTRYPOINT_UNKNOWN")
    sys.exit(0)
if want_cmd == "ABSENT":
    _cmd = target.get("command", None)
    if _cmd not in (None, []):
        print("TASKDEF_OPERATION_MISMATCH:COMMAND")
        sys.exit(0)
elif want_cmd:
    if (target.get("command", None) or []) != [want_cmd]:
        print("TASKDEF_OPERATION_MISMATCH:COMMAND")
        sys.exit(0)
else:
    print("TASKDEF_OPERATION_MISMATCH:COMMAND_UNKNOWN")
    sys.exit(0)
actual = {}
for secret in target.get("secrets", []) or []:
    if not isinstance(secret, dict):
        print("TASKDEF_OPERATION_MISMATCH:SECRET_MALFORMED")
        sys.exit(0)
    _n = secret.get("name", "") or ""
    _v = secret.get("valueFrom", "") or ""
    if not _n or not _v:
        print("TASKDEF_OPERATION_MISMATCH:SECRET_MALFORMED")
        sys.exit(0)
    if _n in actual:
        print("TASKDEF_OPERATION_MISMATCH:SECRET_DUPLICATE")
        sys.exit(0)
    actual[_n] = _v
if want_logical == "SdkMaterialTaskDefinition":
    if actual:
        print("TASKDEF_OPERATION_MISMATCH:UNEXPECTED_SECRET")
        sys.exit(0)
elif want_logical == "BootstrapTaskDefinition":
    if not want_rt or not want_mg or not want_master:
        print("TASKDEF_OPERATION_MISMATCH:SECRET_EXPECTED_MISSING")
        sys.exit(0)
    want = {
        "MASTER_DB_PASSWORD": "%s:password::" % want_master,
        "RUNTIME_DB_URL": "%s:database-url::" % want_rt,
        "MIGRATION_DB_URL": "%s:database-url::" % want_mg,
    }
    for key in sorted(want):
        if key not in actual:
            print("TASKDEF_OPERATION_MISMATCH:MISSING_SECRET")
            sys.exit(0)
        if actual[key] != want[key]:
            print("TASKDEF_OPERATION_MISMATCH:SECRET")
            sys.exit(0)
    for key in sorted(actual):
        if key not in want:
            print("TASKDEF_OPERATION_MISMATCH:UNEXPECTED_SECRET")
            sys.exit(0)
elif want_logical == "MigrationTaskDefinition":
    if not want_mg:
        print("TASKDEF_OPERATION_MISMATCH:SECRET_EXPECTED_MISSING")
        sys.exit(0)
    want = {"DATABASE_URL": "%s:database-url::" % want_mg}
    for key in sorted(want):
        if key not in actual:
            print("TASKDEF_OPERATION_MISMATCH:MISSING_SECRET")
            sys.exit(0)
        if actual[key] != want[key]:
            print("TASKDEF_OPERATION_MISMATCH:SECRET")
            sys.exit(0)
    for key in sorted(actual):
        if key not in want:
            print("TASKDEF_OPERATION_MISMATCH:UNEXPECTED_SECRET")
            sys.exit(0)
elif want_logical == "VerifyTaskDefinition":
    if not want_rt:
        print("TASKDEF_OPERATION_MISMATCH:SECRET_EXPECTED_MISSING")
        sys.exit(0)
    want = {"RUNTIME_DB_URL": "%s:database-url::" % want_rt}
    for key in sorted(want):
        if key not in actual:
            print("TASKDEF_OPERATION_MISMATCH:MISSING_SECRET")
            sys.exit(0)
        if actual[key] != want[key]:
            print("TASKDEF_OPERATION_MISMATCH:SECRET")
            sys.exit(0)
    for key in sorted(actual):
        if key not in want:
            print("TASKDEF_OPERATION_MISMATCH:UNEXPECTED_SECRET")
            sys.exit(0)
else:
    print("TASKDEF_OPERATION_MISMATCH:LOGICAL_UNKNOWN")
    sys.exit(0)
print("OK")
PYEOF
)" || RECOVERY_ORIG_OP="UNREADABLE"
  rm -f "$RECOVERY_ORIG_DEF_JSON"
  RECOVERY_ORIG_OP="$(printf '%s' "$RECOVERY_ORIG_OP" | tr -d '[:space:]')"
  if [ "$RECOVERY_ORIG_OP" != "OK" ]; then
    echo "refused: original $RECOVERY_TYPED_LABEL operation proof is $RECOVERY_ORIG_OP, no recovery claimed. Inspect $RECOVERY_ORIG_PATH." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  [ -n "$RUNTIME_SECRET_ARN" ] || { echo "refused: recovery needs exact runtime secret ARN, no recovery claimed." >&2; phase_failed "$RECOVERY_FAIL_PHASE"; }
  [ -n "$MIGRATION_SECRET_ARN" ] || { echo "refused: recovery needs exact migration secret ARN, no recovery claimed." >&2; phase_failed "$RECOVERY_FAIL_PHASE"; }
  [ -n "$TLS_SECRET_ARN" ] || { echo "refused: recovery needs exact TLS secret ARN, no recovery claimed." >&2; phase_failed "$RECOVERY_FAIL_PHASE"; }
  RECOVERY_RT_IDENTITY="$(fetch_secret_version_identity "$RUNTIME_SECRET_ARN" runtime)"
  RECOVERY_RT_PROOF="$(printf '%s\n' "$RECOVERY_RT_IDENTITY" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_RT_PROOF" != "OK" ]; then
    echo "refused: recovery runtime secret proof is $RECOVERY_RT_PROOF, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_MG_IDENTITY="$(fetch_secret_version_identity "$MIGRATION_SECRET_ARN" migration)"
  RECOVERY_MG_PROOF="$(printf '%s\n' "$RECOVERY_MG_IDENTITY" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_MG_PROOF" != "OK" ]; then
    echo "refused: recovery migration secret proof is $RECOVERY_MG_PROOF, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_TLS_IDENTITY="$(fetch_secret_version_identity "$TLS_SECRET_ARN" tls)"
  RECOVERY_TLS_PROOF="$(printf '%s\n' "$RECOVERY_TLS_IDENTITY" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_TLS_PROOF" != "OK" ]; then
    echo "refused: recovery TLS secret proof is $RECOVERY_TLS_PROOF, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_RT_NAME="$(printf '%s\n' "$RECOVERY_RT_IDENTITY" | awk -F'\t' '$1=="NAME"{print $2}' | tr -d '[:space:]')"
  RECOVERY_RT_ARN="$(printf '%s\n' "$RECOVERY_RT_IDENTITY" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_RT_PRE="$(printf '%s\n' "$RECOVERY_RT_IDENTITY" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  RECOVERY_MG_NAME="$(printf '%s\n' "$RECOVERY_MG_IDENTITY" | awk -F'\t' '$1=="NAME"{print $2}' | tr -d '[:space:]')"
  RECOVERY_MG_ARN="$(printf '%s\n' "$RECOVERY_MG_IDENTITY" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_MG_PRE="$(printf '%s\n' "$RECOVERY_MG_IDENTITY" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  RECOVERY_TLS_NAME="$(printf '%s\n' "$RECOVERY_TLS_IDENTITY" | awk -F'\t' '$1=="NAME"{print $2}' | tr -d '[:space:]')"
  RECOVERY_TLS_ARN="$(printf '%s\n' "$RECOVERY_TLS_IDENTITY" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_TLS_PRE="$(printf '%s\n' "$RECOVERY_TLS_IDENTITY" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  if ! RECOVERY_CERT_ARN_VALUE="$(params_file_value AcmCertificateArn)"; then
    echo "refused: recovery certificate ARN missing from parameters file, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_CERT_ARN_VALUE="$(printf '%s' "$RECOVERY_CERT_ARN_VALUE" | tr -d '[:space:]')"
  [ -n "$RECOVERY_CERT_ARN_VALUE" ] || { echo "refused: recovery certificate ARN empty, no recovery claimed." >&2; phase_failed "$RECOVERY_FAIL_PHASE"; }
  RECOVERY_CERT_IDENTITY="$(fetch_cert_identity "$RECOVERY_CERT_ARN_VALUE")"
  RECOVERY_CERT_PROOF="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_CERT_PROOF" != "OK" ]; then
    echo "refused: recovery certificate proof is $RECOVERY_CERT_PROOF, no recovery claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_CERT_ARN="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_DOMAIN="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="DOMAIN"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_SERIAL_PRE="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="SERIAL"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_STATUS="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="STATUS"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_TYPE="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="TYPE"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_EXPORT="$(printf '%s\n' "$RECOVERY_CERT_IDENTITY" | awk -F'\t' '$1=="EXPORT"{print $2}' | tr -d '[:space:]')"
  ensure_recovery_dir
  RECOVERY_FILE="$LAUNCH_JOURNAL_DIR/recovery/$RECOVERY_ORIG_BASENAME.recovery.json"
  if [ -L "$RECOVERY_FILE" ]; then
    echo "refused: recovery attestation is a symlink, no recovery claimed. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "${RECOVERY_READONLY:-0}" = "1" ] && [ ! -f "$RECOVERY_FILE" ]; then
    echo "refused: enable re-proof needs prior $RECOVERY_TYPED_LABEL recovery attestation $RECOVERY_FILE but none exists. Run --phase $RECOVERY_TYPED_PHASE first to attest. No new launch." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  acquire_recovery_lock "$RECOVERY_ORIG_BASENAME"
  if [ -f "$RECOVERY_FILE" ]; then
    RECOVERY_EXISTING="$(python3 - "$RECOVERY_FILE" "$STACK_NAME" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$CLUSTER_NAME" \
      "$RECOVERY_KIND" "$RECOVERY_ORIG_BASENAME" "$RECOVERY_ORIG_SHA" "$RECOVERY_ORIG_TOKEN" "$RECOVERY_ORIG_TASK" \
      "$RECOVERY_ORIG_TASKDEF" "$RECOVERY_ORIG_GEN" "$RECOVERY_ORIG_SOURCE" "$RECOVERY_ORIG_HEAD" "$RECOVERY_ORIG_OUTCOME" \
      "$RECOVERY_STACK_ID" "${RECOVERY_ORIG_LEGACY:-false}" 2>/dev/null <<'PYEOF'
import hashlib, json, os, sys
(path, want_stack, want_account, want_region, want_cluster,
 want_kind, want_base, want_sha, want_token, want_task,
 want_taskdef, want_gen, want_source, want_head, want_outcome,
 want_stack_id, want_legacy) = sys.argv[1:18]
try:
    if os.path.islink(path):
        print("PROOF\tSYMLINK")
        sys.exit(0)
    finfo = os.stat(path)
    if (finfo.st_mode & 0o777) != 0o600:
        print("PROOF\tMODE")
        sys.exit(0)
    if finfo.st_uid != os.getuid():
        print("PROOF\tOWNER")
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
try:
    if os.path.basename(path) != want_base + ".recovery.json":
        print("PROOF\tPATH_MISMATCH")
        sys.exit(0)
    if os.path.basename(os.path.dirname(os.path.abspath(path))) != "recovery":
        print("PROOF\tPATH_MISMATCH")
        sys.exit(0)
except Exception:
    print("PROOF\tPATH_MISMATCH")
    sys.exit(0)
allow = {"version", "kind", "stack", "account", "region", "cluster",
         "original_basename", "original_sha256", "original_token",
         "original_task_arn", "original_taskdef_arn", "original_generation",
         "original_source_sha", "original_target_head", "original_outcome",
         "legacy_unversioned",
         "stack_id", "project", "environment", "release_generation",
         "source_sha", "target_head", "runtime_name", "runtime_arn",
         "runtime_version_pre", "runtime_version_post", "migration_name",
         "migration_arn", "migration_version_pre", "migration_version_post",
         "tls_name", "tls_arn", "tls_version_pre", "tls_version_post",
         "cert_arn", "cert_domain", "cert_serial_pre", "cert_serial_post",
         "cert_status", "cert_type", "cert_export", "verifier_token",
         "verifier_task_arn", "verifier_taskdef_arn", "verifier_proof",
         "verifier_containers", "verifier_last_status", "verifier_digest",
         "absence_proof", "observed_head", "outcome", "note", "updated_utc"}
for key in doc:
    if key not in allow:
        print("PROOF\tFOREIGN_FIELD")
        sys.exit(0)
for _k, _v in doc.items():
    if _k == "version":
        if not isinstance(_v, int) or isinstance(_v, bool):
            print("PROOF\tMALFORMED")
            sys.exit(0)
        continue
    if not isinstance(_v, str):
        print("PROOF\tMALFORMED")
        sys.exit(0)
for _k, _v in doc.items():
    _kl = str(_k).lower()
    if _kl in ("password", "database-url", "database_url",
               "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
               "secret_value", "secretvalue", "private_key", "privatekey",
               "certificate_body", "certificate_chain"):
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
    if isinstance(_v, str):
        _vl = _v.lower()
        if "://" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "password" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
if doc.get("version", 0) != 1 or doc.get("kind", "") != want_kind:
    print("PROOF\tKIND_MISMATCH")
    sys.exit(0)
if doc.get("stack", "") != want_stack or doc.get("account", "") != want_account:
    print("PROOF\tOWNER_MISMATCH")
    sys.exit(0)
if doc.get("region", "") != want_region or doc.get("cluster", "") != want_cluster:
    print("PROOF\tOWNER_MISMATCH")
    sys.exit(0)
if doc.get("original_basename", "") != want_base:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_sha256", "") != want_sha:
    print("PROOF\tORIGINAL_ALTERED")
    sys.exit(0)
if doc.get("original_token", "") != want_token:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_task_arn", "") != want_task:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_taskdef_arn", "") != want_taskdef:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_generation", "") != want_gen:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_source_sha", "") != want_source:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_target_head", "") != want_head:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("original_outcome", "") != want_outcome:
    print("PROOF\tORIGINAL_MISMATCH")
    sys.exit(0)
if doc.get("legacy_unversioned", "") not in ("true", "false"):
    print("PROOF\tLEGACY_MALFORMED")
    sys.exit(0)
if doc.get("legacy_unversioned", "") != want_legacy:
    print("PROOF\tLEGACY_MISMATCH")
    sys.exit(0)
if doc.get("stack_id", "") != want_stack_id:
    print("PROOF\tSTACKID_MISMATCH")
    sys.exit(0)
if doc.get("project", "") != "LaunchCrew" or doc.get("environment", "") != "demo":
    print("PROOF\tTAG_MISMATCH")
    sys.exit(0)
token = doc.get("verifier_token", "")
if not isinstance(token, str) or len(token) != 33 or not token.startswith("lc-"):
    print("PROOF\tVERIFIER_TOKEN_MALFORMED")
    sys.exit(0)
outcome = doc.get("outcome", "")
if not isinstance(outcome, str) or not outcome:
    print("PROOF\tOUTCOME_MISSING")
    sys.exit(0)
if outcome not in ("admitted", "started", "complete", "ambiguous_call_failed", "ambiguous_response"):
    print("PROOF\tOUTCOME_UNKNOWN")
    sys.exit(0)
if outcome == "complete":
    if doc.get("verifier_proof", "") != "OK":
        print("PROOF\tVERIFIER_PROOF_MISMATCH")
        sys.exit(0)
    if doc.get("verifier_last_status", "") != "STOPPED":
        print("PROOF\tVERIFIER_STATUS_MISMATCH")
        sys.exit(0)
    _cont = doc.get("verifier_containers", "")
    if not isinstance(_cont, str) or ":STOPPED:" not in _cont:
        print("PROOF\tVERIFIER_CONTAINERS_MISMATCH")
        sys.exit(0)
    try:
        _exit = _cont.rsplit(":", 1)[1]
    except Exception:
        _exit = ""
    if want_kind in ("dbroles-recovery-attestation", "migration-recovery-attestation"):
        if _exit not in ("0", "10"):
            print("PROOF\tVERIFIER_CONTAINERS_MISMATCH")
            sys.exit(0)
        _obs = doc.get("observed_head", "")
        if (_exit == "0" and _obs != "008") or (_exit == "10" and _obs != "007"):
            print("PROOF\tOBSERVED_HEAD_MISMATCH")
            sys.exit(0)
    elif want_kind == "runtime-recovery-attestation":
        if _exit != "0" or doc.get("observed_head", "") != "008":
            print("PROOF\tVERIFIER_CONTAINERS_MISMATCH")
            sys.exit(0)
    else:
        if _exit != "0":
            print("PROOF\tVERIFIER_CONTAINERS_MISMATCH")
            sys.exit(0)
    _dig = doc.get("verifier_digest", "")
    if not isinstance(_dig, str) or len(_dig) != 64:
        print("PROOF\tDIGEST_MALFORMED")
        sys.exit(0)
    for _c in _dig:
        if _c not in "0123456789abcdef":
            print("PROOF\tDIGEST_MALFORMED")
            sys.exit(0)
    try:
        _parts = [
            doc.get("kind", ""), doc.get("verifier_task_arn", ""), doc.get("verifier_token", ""),
            doc.get("verifier_taskdef_arn", ""), doc.get("verifier_containers", ""),
            doc.get("verifier_last_status", ""), doc.get("original_sha256", ""),
            doc.get("original_outcome", ""), doc.get("stack_id", ""), doc.get("runtime_arn", ""),
            doc.get("runtime_name", ""), doc.get("runtime_version_pre", ""),
            doc.get("runtime_version_post", ""), doc.get("migration_arn", ""),
            doc.get("migration_name", ""), doc.get("migration_version_pre", ""),
            doc.get("migration_version_post", ""), doc.get("tls_arn", ""),
            doc.get("tls_name", ""), doc.get("tls_version_pre", ""),
            doc.get("tls_version_post", ""), doc.get("cert_arn", ""),
            doc.get("cert_domain", ""), doc.get("cert_serial_pre", ""),
            doc.get("cert_serial_post", ""), doc.get("release_generation", ""),
            doc.get("source_sha", ""), doc.get("target_head", ""),
            doc.get("observed_head", ""), doc.get("original_basename", ""), doc.get("legacy_unversioned", ""),
        ]
        _exp = hashlib.sha256("|".join(_parts).encode("utf-8")).hexdigest()
        if _dig != _exp:
            print("PROOF\tDIGEST_MISMATCH")
            sys.exit(0)
    except Exception:
        print("PROOF\tDIGEST_MISMATCH")
        sys.exit(0)
    if doc.get("absence_proof", "") != "OK":
        print("PROOF\tABSENCE_MISMATCH")
        sys.exit(0)
    _vtask = doc.get("verifier_task_arn", "")
    if not _vtask.startswith("arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
        print("PROOF\tVERIFIER_TASK_FOREIGN")
        sys.exit(0)
    _vtdef = doc.get("verifier_taskdef_arn", "")
    if not _vtdef.startswith("arn:aws:ecs:%s:%s:task" "-definition/" % (want_region, want_account)):
        print("PROOF\tVERIFIER_TASKDEF_FOREIGN")
        sys.exit(0)
print("PROOF\tOK")
print("OUTCOME\t%s" % outcome)
print("VTOKEN\t%s" % token)
print("VTASK\t%s" % (doc.get("verifier_task_arn", "") or ""))
print("VTASKDEF\t%s" % (doc.get("verifier_taskdef_arn", "") or ""))
print("VPROOF\t%s" % (doc.get("verifier_proof", "") or ""))
print("VCONTAINERS\t%s" % (doc.get("verifier_containers", "") or ""))
print("VLASTSTATUS\t%s" % (doc.get("verifier_last_status", "") or ""))
print("VDIGEST\t%s" % (doc.get("verifier_digest", "") or ""))
print("LEGACY\t%s" % (doc.get("legacy_unversioned", "") or ""))
print("RT_PRE\t%s" % (doc.get("runtime_version_pre", "") or ""))
print("RT_POST\t%s" % (doc.get("runtime_version_post", "") or ""))
print("RT_ARN\t%s" % (doc.get("runtime_arn", "") or ""))
print("RT_NAME\t%s" % (doc.get("runtime_name", "") or ""))
print("MG_PRE\t%s" % (doc.get("migration_version_pre", "") or ""))
print("MG_POST\t%s" % (doc.get("migration_version_post", "") or ""))
print("MG_ARN\t%s" % (doc.get("migration_arn", "") or ""))
print("MG_NAME\t%s" % (doc.get("migration_name", "") or ""))
print("TLS_PRE\t%s" % (doc.get("tls_version_pre", "") or ""))
print("TLS_POST\t%s" % (doc.get("tls_version_post", "") or ""))
print("TLS_ARN\t%s" % (doc.get("tls_arn", "") or ""))
print("TLS_NAME\t%s" % (doc.get("tls_name", "") or ""))
print("CERT_PRE\t%s" % (doc.get("cert_serial_pre", "") or ""))
print("CERT_POST\t%s" % (doc.get("cert_serial_post", "") or ""))
print("CERT_ARN\t%s" % (doc.get("cert_arn", "") or ""))
print("CERT_DOMAIN\t%s" % (doc.get("cert_domain", "") or ""))
print("CERT_STATUS\t%s" % (doc.get("cert_status", "") or ""))
print("CERT_TYPE\t%s" % (doc.get("cert_type", "") or ""))
print("CERT_EXPORT\t%s" % (doc.get("cert_export", "") or ""))
print("REL_GEN\t%s" % (doc.get("release_generation", "") or ""))
print("REL_SOURCE\t%s" % (doc.get("source_sha", "") or ""))
print("REL_HEAD\t%s" % (doc.get("target_head", "") or ""))
print("OBS_HEAD\t%s" % (doc.get("observed_head", "") or ""))
PYEOF
)" || RECOVERY_EXISTING="PROOF\tUNREADABLE"
    RECOVERY_EXIST_PROOF="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$RECOVERY_EXIST_PROOF" != "OK" ]; then
      release_recovery_lock
      echo "refused: existing recovery attestation is $RECOVERY_EXIST_PROOF, no new verifier. Inspect $RECOVERY_FILE and $RECOVERY_ORIG_PATH." >&2
      phase_failed "$RECOVERY_FAIL_PHASE"
    fi
    RECOVERY_EXIST_OUTCOME="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
    RECOVERY_EXIST_VTOKEN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="VTOKEN"{print $2}' | tr -d '[:space:]')"
    RECOVERY_EXIST_VTASK="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="VTASK"{print $2}' | tr -d '[:space:]')"
    RECOVERY_EXIST_VTASKDEF="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="VTASKDEF"{print $2}' | tr -d '[:space:]')"
    if [ "$RECOVERY_EXIST_OUTCOME" = "complete" ]; then
      RECOVERY_ATTEST_RT_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_RT_POST="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_POST"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_RT_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_RT_NAME="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_NAME"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_MG_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_MG_POST="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_POST"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_MG_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_MG_NAME="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_NAME"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_TLS_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_TLS_POST="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_POST"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_TLS_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_TLS_NAME="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_NAME"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_CERT_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_CERT_POST="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_POST"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_CERT_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_CERT_DOMAIN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_DOMAIN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_REL_GEN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_GEN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_REL_SOURCE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_SOURCE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_ATTEST_REL_HEAD="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_HEAD"{print $2}' | tr -d '[:space:]')"
      if [ "$RECOVERY_RT_PRE" != "$RECOVERY_ATTEST_RT_PRE" ] || [ "$RECOVERY_RT_PRE" != "$RECOVERY_ATTEST_RT_POST" ]; then
        release_recovery_lock
        echo "refused: live runtime VersionId changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_MG_PRE" != "$RECOVERY_ATTEST_MG_PRE" ] || [ "$RECOVERY_MG_PRE" != "$RECOVERY_ATTEST_MG_POST" ]; then
        release_recovery_lock
        echo "refused: live migration VersionId changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_TLS_PRE" != "$RECOVERY_ATTEST_TLS_PRE" ] || [ "$RECOVERY_TLS_PRE" != "$RECOVERY_ATTEST_TLS_POST" ]; then
        release_recovery_lock
        echo "refused: live TLS VersionId changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_CERT_SERIAL_PRE" != "$RECOVERY_ATTEST_CERT_PRE" ] || [ "$RECOVERY_CERT_SERIAL_PRE" != "$RECOVERY_ATTEST_CERT_POST" ]; then
        release_recovery_lock
        echo "refused: live certificate serial changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_RT_ARN" != "$RECOVERY_ATTEST_RT_ARN" ] || [ "$RECOVERY_ATTEST_RT_ARN" != "$RUNTIME_SECRET_ARN" ]; then
        release_recovery_lock
        echo "refused: recovery runtime ARN does not equal exact owned ARN, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_RT_NAME" != "$RECOVERY_ATTEST_RT_NAME" ]; then
        release_recovery_lock
        echo "refused: live runtime Name changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_MG_ARN" != "$RECOVERY_ATTEST_MG_ARN" ] || [ "$RECOVERY_ATTEST_MG_ARN" != "$MIGRATION_SECRET_ARN" ]; then
        release_recovery_lock
        echo "refused: recovery migration ARN does not equal exact owned ARN, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_MG_NAME" != "$RECOVERY_ATTEST_MG_NAME" ]; then
        release_recovery_lock
        echo "refused: live migration Name changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_TLS_ARN" != "$RECOVERY_ATTEST_TLS_ARN" ] || [ "$RECOVERY_ATTEST_TLS_ARN" != "$TLS_SECRET_ARN" ]; then
        release_recovery_lock
        echo "refused: recovery TLS ARN does not equal exact owned ARN, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_TLS_NAME" != "$RECOVERY_ATTEST_TLS_NAME" ]; then
        release_recovery_lock
        echo "refused: live TLS Name changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_CERT_ARN" != "$RECOVERY_ATTEST_CERT_ARN" ] || [ "$RECOVERY_ATTEST_CERT_ARN" != "$RECOVERY_CERT_ARN_VALUE" ]; then
        release_recovery_lock
        echo "refused: recovery certificate ARN does not equal exact owned ARN, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_CERT_DOMAIN" != "$RECOVERY_ATTEST_CERT_DOMAIN" ]; then
        release_recovery_lock
        echo "refused: live certificate domain changed since recovery attestation, no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_ATTEST_REL_GEN" != "${RELEASE_GEN:-}" ] || [ "$RECOVERY_ATTEST_REL_HEAD" != "${TARGET_DB_HEAD:-008}" ]; then
        release_recovery_lock
        echo "refused: recovery attestation release generation or head does not equal current owned release, same-release restart only with no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_ATTEST_REL_SOURCE" != "${SOURCE_SHA:-}" ]; then
        release_recovery_lock
        echo "refused: recovery attestation source SHA does not equal current owned source, same-release restart only with no bypass. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      [ -n "$RECOVERY_EXIST_VTASK" ] && [ "$RECOVERY_EXIST_VTASK" != "None" ] || {
        release_recovery_lock
        echo "refused: recovery attestation complete has no verifier task, cannot re-prove. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      }
      [ -n "$RECOVERY_EXIST_VTASKDEF" ] && [ "$RECOVERY_EXIST_VTASKDEF" != "None" ] || {
        release_recovery_lock
        echo "refused: recovery attestation complete has no verifier taskdef, cannot re-prove. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      }
      RECOVERY_REVERIFY_DESC="$(mktemp /tmp/launchcrew-reverify-XXXXXX)"
      if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$RECOVERY_EXIST_VTASK" --region "$EXPECTED_REGION" --output json >"$RECOVERY_REVERIFY_DESC" 2>"$TMP_ERR"; then
        rm -f "$RECOVERY_REVERIFY_DESC"
        release_recovery_lock
        echo "refused: recovery verifier terminal state unreadable, not treated as success. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      RECOVERY_REVERIFY_PRESENCE="$(python3 - "$RECOVERY_REVERIFY_DESC" "$RECOVERY_EXIST_VTASK" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("UNREADABLE")
    sys.exit(0)
expected = sys.argv[2] if len(sys.argv) > 2 else ""
if not isinstance(doc, dict):
    print("UNREADABLE")
    sys.exit(0)
if "tasks" not in doc or "failures" not in doc:
    print("AMBIGUOUS_RESPONSE")
    sys.exit(0)
tasks = doc.get("tasks")
failures = doc.get("failures")
if not isinstance(tasks, list) or not isinstance(failures, list):
    print("AMBIGUOUS_RESPONSE")
    sys.exit(0)
for entry in tasks:
    if not isinstance(entry, dict):
        print("AMBIGUOUS_RESPONSE")
        sys.exit(0)
for entry in failures:
    if not isinstance(entry, dict):
        print("AMBIGUOUS_RESPONSE")
        sys.exit(0)
    if not isinstance(entry.get("arn"), str) or not isinstance(entry.get("reason"), str):
        print("AMBIGUOUS_RESPONSE")
        sys.exit(0)
if tasks and failures:
    print("AMBIGUOUS_MIXED")
    sys.exit(0)
if tasks and not failures:
    print("PRESENT")
    sys.exit(0)
if not tasks and not failures:
    print("AMBIGUOUS_EMPTY")
    sys.exit(0)
if len(failures) != 1:
    print("AMBIGUOUS_FAILURES")
    sys.exit(0)
single = failures[0]
if single.get("reason") != "MISSING":
    print("AMBIGUOUS_REASON")
    sys.exit(0)
if not expected or single.get("arn") != expected:
    print("AMBIGUOUS_ARN")
    sys.exit(0)
print("NO_TASK")
PYEOF
)" || RECOVERY_REVERIFY_PRESENCE="UNREADABLE"
      rm -f "$RECOVERY_REVERIFY_DESC"
      RECOVERY_REVERIFY_PRESENCE="$(printf '%s' "$RECOVERY_REVERIFY_PRESENCE" | tr -d '[:space:]')"
      if [ "$RECOVERY_REVERIFY_PRESENCE" = "NO_TASK" ]; then
        prove_no_running_for_startedby "$RECOVERY_ORIG_TOKEN" "recovery re-verify" "$RECOVERY_ORIG_TASK"
        RECOVERY_ABSENCE_PROOF="OK"
        release_recovery_lock
        echo "recovery re-verified via persisted one-shot terminal proof after verifier retention expiry: original $RECOVERY_ORIG_BASENAME unchanged, fresh desired state intact, no live verifier claim, no new verifier, no resend. Not retroactive proof."
        return 0
      fi
      if [ "$RECOVERY_REVERIFY_PRESENCE" != "PRESENT" ]; then
        release_recovery_lock
        echo "refused: recovery verifier presence is $RECOVERY_REVERIFY_PRESENCE, cannot re-prove. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      prove_typed_verifier_terminal "$RECOVERY_EXIST_VTASK" "$RECOVERY_EXIST_VTOKEN" "$RECOVERY_EXIST_VTASKDEF" "$RECOVERY_ALLOW10"
      prove_no_running_for_startedby "$RECOVERY_ORIG_TOKEN" "recovery re-verify" "$RECOVERY_ORIG_TASK"
      RECOVERY_ABSENCE_PROOF="OK"
      release_recovery_lock
      echo "recovery re-verified: original $RECOVERY_ORIG_BASENAME unchanged, live material and verifier still prove desired-state equivalence, not retroactive proof."
      return 0
    fi
    if [ "$RECOVERY_EXIST_OUTCOME" = "started" ] && [ -n "$RECOVERY_EXIST_VTASK" ] && [ "$RECOVERY_EXIST_VTASK" != "None" ]; then
      if [ "${RECOVERY_READONLY:-0}" = "1" ]; then
        release_recovery_lock
        echo "refused: enable re-proof needs complete recovery attestation but existing is $RECOVERY_EXIST_OUTCOME unresolved. Run --phase $RECOVERY_TYPED_PHASE to reconcile first. No new launch." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      [ -n "$RECOVERY_EXIST_VTASKDEF" ] && [ "$RECOVERY_EXIST_VTASKDEF" != "None" ] || {
        release_recovery_lock
        echo "refused: recovery $RECOVERY_EXIST_OUTCOME has no verifier taskdef, manual review required. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      }
      RECOVERY_RESUME_RT_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_MG_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_TLS_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_CERT_PRE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_PRE"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_RT_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="RT_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_MG_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="MG_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_TLS_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="TLS_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_CERT_ARN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="CERT_ARN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_REL_GEN="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_GEN"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_REL_HEAD="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_HEAD"{print $2}' | tr -d '[:space:]')"
      RECOVERY_RESUME_REL_SOURCE="$(printf '%s\n' "$RECOVERY_EXISTING" | awk -F'\t' '$1=="REL_SOURCE"{print $2}' | tr -d '[:space:]')"
      if [ "$RECOVERY_RT_PRE" != "$RECOVERY_RESUME_RT_PRE" ]; then
        release_recovery_lock
        echo "refused: live runtime VersionId changed during recovery resume, no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_MG_PRE" != "$RECOVERY_RESUME_MG_PRE" ]; then
        release_recovery_lock
        echo "refused: live migration VersionId changed during recovery resume, no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_TLS_PRE" != "$RECOVERY_RESUME_TLS_PRE" ]; then
        release_recovery_lock
        echo "refused: live TLS VersionId changed during recovery resume, no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_CERT_SERIAL_PRE" != "$RECOVERY_RESUME_CERT_PRE" ]; then
        release_recovery_lock
        echo "refused: live certificate serial changed during recovery resume, no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_RT_ARN" != "$RECOVERY_RESUME_RT_ARN" ] || [ "$RECOVERY_MG_ARN" != "$RECOVERY_RESUME_MG_ARN" ] || [ "$RECOVERY_TLS_ARN" != "$RECOVERY_RESUME_TLS_ARN" ] || [ "$RECOVERY_CERT_ARN" != "$RECOVERY_RESUME_CERT_ARN" ]; then
        release_recovery_lock
        echo "refused: live material ARN changed during recovery resume, no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      if [ "$RECOVERY_RESUME_REL_GEN" != "${RELEASE_GEN:-}" ] || [ "$RECOVERY_RESUME_REL_HEAD" != "${TARGET_DB_HEAD:-008}" ] || [ "$RECOVERY_RESUME_REL_SOURCE" != "${SOURCE_SHA:-}" ]; then
        release_recovery_lock
        echo "refused: recovery resume release does not equal current owned release, same-release only with no attestation. Inspect $RECOVERY_FILE." >&2
        phase_failed "$RECOVERY_FAIL_PHASE"
      fi
      echo "recovery prior $RECOVERY_EXIST_OUTCOME unresolved, reconciling recorded verifier with no new RunTask."
      prove_typed_verifier_terminal "$RECOVERY_EXIST_VTASK" "$RECOVERY_EXIST_VTOKEN" "$RECOVERY_EXIST_VTASKDEF" "$RECOVERY_ALLOW10"
      RECOVERY_VERIFIER_TOKEN="$RECOVERY_EXIST_VTOKEN"
      RECOVERY_VERIFIER_TASK="$RECOVERY_EXIST_VTASK"
      RECOVERY_VERIFIER_TASKDEF="$RECOVERY_EXIST_VTASKDEF"
      RECOVERY_RT_POST="$RECOVERY_RT_PRE"
      RECOVERY_MG_POST="$RECOVERY_MG_PRE"
      RECOVERY_TLS_POST="$RECOVERY_TLS_PRE"
      RECOVERY_CERT_SERIAL_POST="$RECOVERY_CERT_SERIAL_PRE"
      RECOVERY_VERIFIER_PROOF="OK"
      if [ "$RECOVERY_KIND" = "material-recovery-attestation" ]; then
        RECOVERY_VERIFIER_CONTAINERS="sdk-material:STOPPED:0"
      elif [ "$RECOVERY_KIND" = "runtime-recovery-attestation" ]; then
        RECOVERY_VERIFIER_CONTAINERS="bootstrap-db-roles:STOPPED:0"
      else
        if [ "${RECOVERY_VERIFIER_EXIT:-0}" = "10" ]; then
          RECOVERY_VERIFIER_CONTAINERS="bootstrap-db-roles:STOPPED:10"
        else
          RECOVERY_VERIFIER_CONTAINERS="bootstrap-db-roles:STOPPED:0"
        fi
      fi
      RECOVERY_VERIFIER_LAST_STATUS="STOPPED"
      compute_typed_verifier_digest
      prove_no_running_for_startedby "$RECOVERY_ORIG_TOKEN" "recovery resume" "$RECOVERY_ORIG_TASK"
      RECOVERY_ABSENCE_PROOF="OK"
      write_typed_recovery_attestation "$RECOVERY_FILE" "complete"
      release_recovery_lock
      echo "recovery resumed to complete: desired-state equivalence for $RECOVERY_ORIG_BASENAME, not retroactive proof."
      return 0
    fi
    release_recovery_lock
    echo "refused: existing recovery is $RECOVERY_EXIST_OUTCOME unresolved, manual review required with no new verifier and no resend. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "${RECOVERY_READONLY:-0}" = "1" ]; then
    release_recovery_lock
    echo "refused: enable re-proof needs complete recovery attestation but none exists. Run --phase $RECOVERY_TYPED_PHASE first to attest. No new launch." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_VERIFIER_TASKDEF="$(stack_resource "$RECOVERY_VERIFIER_LOGICAL" 2>"$TMP_ERR")"; then
    release_recovery_lock
    echo "refused: recovery verifier task definition lookup failed, no verifier claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_VERIFIER_TASKDEF="$(printf '%s' "$RECOVERY_VERIFIER_TASKDEF" | tr -d '[:space:]')"
  [ -n "$RECOVERY_VERIFIER_TASKDEF" ] && [ "$RECOVERY_VERIFIER_TASKDEF" != "None" ] || {
    release_recovery_lock
    echo "refused: recovery verifier task definition missing, no verifier claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  }
  case "$RECOVERY_VERIFIER_LOGICAL" in
    SdkMaterialTaskDefinition)
      check_sdk_taskdef SdkMaterialTaskDefinition SdkMaterialExecutionRole SdkMaterialTaskRole sdk-material --verify-material ;;
    RoleStateTaskDefinition)
      check_rolestate_taskdef ;;
    VerifyTaskDefinition)
      check_taskdef_binding VerifyTaskDefinition VerifyExecutionRole VerifyTaskRole \
        "bootstrap-db-roles.RUNTIME_DB_URL=$RUNTIME_SECRET_ARN:database-url::" ;;
    *) release_recovery_lock
      echo "refused: recovery verifier $RECOVERY_VERIFIER_LOGICAL unknown, no verifier claimed." >&2
      phase_failed "$RECOVERY_FAIL_PHASE" ;;
  esac
  if ! RECOVERY_VERIFIER_TOKEN="$(python3 - 2>/dev/null <<'PYEOF'
import uuid
print("lc-" + uuid.uuid4().hex[:30])
PYEOF
)"; then
    release_recovery_lock
    echo "recovery verifier token generation failed, no verifier claimed." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_VERIFIER_TOKEN="$(printf '%s' "$RECOVERY_VERIFIER_TOKEN" | tr -d '[:space:]')"
  case "$RECOVERY_VERIFIER_TOKEN" in
    lc-??????????????????????????????) ;;
    *) release_recovery_lock; echo "recovery verifier token malformed, no verifier claimed." >&2; phase_failed "$RECOVERY_FAIL_PHASE" ;;
  esac
  RECOVERY_VERIFIER_TASK=""
  RECOVERY_RT_POST=""
  RECOVERY_MG_POST=""
  RECOVERY_TLS_POST=""
  RECOVERY_CERT_SERIAL_POST=""
  RECOVERY_VERIFIER_PROOF=""
  RECOVERY_VERIFIER_CONTAINERS=""
  RECOVERY_VERIFIER_LAST_STATUS=""
  RECOVERY_VERIFIER_DIGEST=""
  RECOVERY_ABSENCE_PROOF=""
  RECOVERY_OBSERVED_HEAD=""
  write_typed_recovery_attestation "$RECOVERY_FILE" "admitted"
  echo "recovery admission persisted before verifier RunTask: $RECOVERY_FILE"
  if ! RECOVERY_SUBNET_A="$(stack_resource PublicSubnetA 2>"$TMP_ERR")"; then
    echo "refused: recovery subnets unreadable after admission, manual review required. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_SUBNET_B="$(stack_resource PublicSubnetB 2>"$TMP_ERR")"; then
    echo "refused: recovery subnets unreadable after admission, manual review required. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if ! RECOVERY_JOB_SG="$(stack_resource JobSecurityGroup 2>"$TMP_ERR")"; then
    echo "refused: recovery security group unreadable after admission, manual review required. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_SUBNET_A="$(printf '%s' "$RECOVERY_SUBNET_A" | tr -d '[:space:]')"
  RECOVERY_SUBNET_B="$(printf '%s' "$RECOVERY_SUBNET_B" | tr -d '[:space:]')"
  RECOVERY_JOB_SG="$(printf '%s' "$RECOVERY_JOB_SG" | tr -d '[:space:]')"
  RECOVERY_RUN_JSON="$(mktemp /tmp/launchcrew-recrun-XXXXXX)"
  RECOVERY_RUN_OK=1
  if ! "$AWS_BIN" ecs run-task --cluster "$CLUSTER_NAME" --task"-definition" "$RECOVERY_VERIFIER_TASKDEF" --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$RECOVERY_SUBNET_A,$RECOVERY_SUBNET_B],securityGroups=[$RECOVERY_JOB_SG],assignPublicIp=ENABLED}" --client-token "$RECOVERY_VERIFIER_TOKEN" --started-by "$RECOVERY_VERIFIER_TOKEN" --region "$EXPECTED_REGION" --output json >"$RECOVERY_RUN_JSON" 2>"$TMP_ERR"; then
    RECOVERY_RUN_OK=0
  fi
  if [ "$RECOVERY_RUN_OK" -eq 0 ]; then
    rm -f "$RECOVERY_RUN_JSON"
    write_typed_recovery_attestation "$RECOVERY_FILE" "ambiguous_call_failed"
    release_recovery_lock
    echo "refused: recovery verifier run-task call failed; launch is ambiguous with no resend. Inspect $RECOVERY_FILE." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_VERIFIER_TASK="$(python3 - "$RECOVERY_RUN_JSON" 2>/dev/null <<'PYEOF'
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
)" || RECOVERY_VERIFIER_TASK="UNREADABLE"
  rm -f "$RECOVERY_RUN_JSON"
  RECOVERY_VERIFIER_TASK="$(printf '%s' "$RECOVERY_VERIFIER_TASK" | tr -d '[:space:]')"
  case "$RECOVERY_VERIFIER_TASK" in
    FAILURES|EMPTY|MULTIPLE|UNREADABLE|"")
      write_typed_recovery_attestation "$RECOVERY_FILE" "ambiguous_response"
      release_recovery_lock
      echo "refused: recovery verifier run-task response is ${RECOVERY_VERIFIER_TASK:-empty}; launch is ambiguous with no resend. Inspect $RECOVERY_FILE." >&2
      phase_failed "$RECOVERY_FAIL_PHASE" ;;
  esac
  write_typed_recovery_attestation "$RECOVERY_FILE" "started"
  echo "recovery verifier started: $RECOVERY_VERIFIER_TASK"
  prove_typed_verifier_terminal "$RECOVERY_VERIFIER_TASK" "$RECOVERY_VERIFIER_TOKEN" "$RECOVERY_VERIFIER_TASKDEF" "$RECOVERY_ALLOW10"
  RECOVERY_POST_RT="$(fetch_secret_version_identity "$RUNTIME_SECRET_ARN" runtime)"
  RECOVERY_POST_RT_PROOF="$(printf '%s\n' "$RECOVERY_POST_RT" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_POST_RT_PROOF" != "OK" ]; then
    echo "refused: recovery post runtime proof is $RECOVERY_POST_RT_PROOF, material changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_POST_MG="$(fetch_secret_version_identity "$MIGRATION_SECRET_ARN" migration)"
  RECOVERY_POST_MG_PROOF="$(printf '%s\n' "$RECOVERY_POST_MG" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_POST_MG_PROOF" != "OK" ]; then
    echo "refused: recovery post migration proof is $RECOVERY_POST_MG_PROOF, material changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_POST_TLS="$(fetch_secret_version_identity "$TLS_SECRET_ARN" tls)"
  RECOVERY_POST_TLS_PROOF="$(printf '%s\n' "$RECOVERY_POST_TLS" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_POST_TLS_PROOF" != "OK" ]; then
    echo "refused: recovery post TLS proof is $RECOVERY_POST_TLS_PROOF, material changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_POST_CERT="$(fetch_cert_identity "$RECOVERY_CERT_ARN_VALUE")"
  RECOVERY_POST_CERT_PROOF="$(printf '%s\n' "$RECOVERY_POST_CERT" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_POST_CERT_PROOF" != "OK" ]; then
    echo "refused: recovery post certificate proof is $RECOVERY_POST_CERT_PROOF, material changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  RECOVERY_RT_POST="$(printf '%s\n' "$RECOVERY_POST_RT" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  RECOVERY_MG_POST="$(printf '%s\n' "$RECOVERY_POST_MG" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  RECOVERY_TLS_POST="$(printf '%s\n' "$RECOVERY_POST_TLS" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
  RECOVERY_CERT_SERIAL_POST="$(printf '%s\n' "$RECOVERY_POST_CERT" | awk -F'\t' '$1=="SERIAL"{print $2}' | tr -d '[:space:]')"
  if [ "$RECOVERY_RT_POST" != "$RECOVERY_RT_PRE" ]; then
    echo "refused: runtime VersionId changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "$RECOVERY_MG_POST" != "$RECOVERY_MG_PRE" ]; then
    echo "refused: migration VersionId changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "$RECOVERY_TLS_POST" != "$RECOVERY_TLS_PRE" ]; then
    echo "refused: TLS VersionId changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "$RECOVERY_CERT_SERIAL_POST" != "$RECOVERY_CERT_SERIAL_PRE" ]; then
    echo "refused: certificate serial changed during verification, no attestation." >&2
    phase_failed "$RECOVERY_FAIL_PHASE"
  fi
  if [ "$RECOVERY_KIND" = "material-recovery-attestation" ]; then
    RECOVERY_VERIFIER_CONTAINERS="sdk-material:STOPPED:0"
  elif [ "$RECOVERY_KIND" = "runtime-recovery-attestation" ]; then
    RECOVERY_VERIFIER_CONTAINERS="bootstrap-db-roles:STOPPED:0"
  else
    if [ "${RECOVERY_VERIFIER_EXIT:-0}" = "10" ]; then
      RECOVERY_VERIFIER_CONTAINERS="bootstrap-db-roles:STOPPED:10"
    else
      RECOVERY_VERIFIER_CONTAINERS="bootstrap-db-roles:STOPPED:0"
    fi
  fi
  RECOVERY_VERIFIER_LAST_STATUS="STOPPED"
  compute_typed_verifier_digest
  prove_no_running_for_startedby "$RECOVERY_ORIG_TOKEN" "recovery" "$RECOVERY_ORIG_TASK"
  RECOVERY_ABSENCE_PROOF="OK"
  write_typed_recovery_attestation "$RECOVERY_FILE" "complete"
  release_recovery_lock
  echo "recovery complete: $RECOVERY_ORIG_BASENAME attested via read-only verifier $RECOVERY_VERIFIER_TASK; desired-state equivalence, not retroactive proof."
}

# Require desired-state equivalence for every prior init journal before a
# later phase proceeds. Args: calling phase. With zero init journals,
# allow and let the later read-only verifier prove material, preserving
# existing runs that never populated. With any init journal, unresolved,
# foreign, or altered records refuse with no bypass. Complete records
# that still live-prove STOPPED exit 0 proceed with no recovery. Complete
# records that return NO_TASK require a valid recovery attestation via
# attest_aged_init_recovery, re-verified live with no new verifier when
# already complete. Any other live proof refuses with no recovery, so
# general NO_TASK is never success and normal terminal proof is unchanged.
require_init_desired_state() {
  REQUIRE_FAIL_PHASE="$1"
  RECOVERY_FAIL_PHASE="$REQUIRE_FAIL_PHASE"
  if [ -z "$LAUNCH_JOURNAL_DIR" ]; then
    case "$0" in
      */*) REQUIRE_SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd 2>/dev/null || echo "")" ;;
      *) REQUIRE_SCRIPT_DIR="" ;;
    esac
    if [ -n "$REQUIRE_SCRIPT_DIR" ] && [ -d "$REQUIRE_SCRIPT_DIR" ]; then
      LAUNCH_JOURNAL_DIR="$REQUIRE_SCRIPT_DIR/../../.local/launch-journals"
    else
      echo "init desired-state journal directory missing, no claim made." >&2
      phase_failed "$REQUIRE_FAIL_PHASE"
    fi
  fi
  if [ -L "$LAUNCH_JOURNAL_DIR" ]; then
    echo "init desired-state journal directory is a symlink, no claim made." >&2
    phase_failed "$REQUIRE_FAIL_PHASE"
  fi
  if [ ! -d "$LAUNCH_JOURNAL_DIR" ]; then
    echo "init desired-state: no journal directory, no prior init to reconcile, proceeding to verifier."
    return 0
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
  then
    echo "init desired-state journal directory is not private mode 700 owned, no claim made." >&2
    phase_failed "$REQUIRE_FAIL_PHASE"
  fi
  REQUIRE_LIST="$(mktemp /tmp/launchcrew-init-list-XXXXXX)"
  REQUIRE_ENUM="$(python3 - "$LAUNCH_JOURNAL_DIR" "$STACK_NAME" "$REQUIRE_LIST" 2>/dev/null <<'PYEOF'
import os, sys
directory, stack, out_path = sys.argv[1:4]
prefix = "launchcrew-%s-init-sdk-init-" % stack
try:
    names = sorted(os.listdir(directory))
except Exception:
    print("PROOF\tLIST_FAILED")
    sys.exit(0)
found = []
for name in names:
    if not name.startswith(prefix) or not name.endswith(".json"):
        continue
    if name.endswith(".lock") or name.endswith(".recovery.json"):
        continue
    found.append(name)
    if len(found) > 32:
        print("PROOF\tTOO_MANY")
        sys.exit(0)
try:
    with open(out_path, "w", encoding="utf-8") as out:
        for name in found:
            out.write(name + "\n")
except Exception:
    print("PROOF\tLIST_FAILED")
    sys.exit(0)
print("PROOF\tOK")
print("COUNT\t%d" % len(found))
PYEOF
)" || REQUIRE_ENUM="PROOF\tLIST_FAILED"
  REQUIRE_PROOF="$(printf '%s\n' "$REQUIRE_ENUM" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$REQUIRE_PROOF" != "OK" ]; then
    rm -f "$REQUIRE_LIST"
    echo "refused: init desired-state enumeration is $REQUIRE_PROOF, no bypass. Inspect $LAUNCH_JOURNAL_DIR." >&2
    phase_failed "$REQUIRE_FAIL_PHASE"
  fi
  REQUIRE_COUNT="$(printf '%s\n' "$REQUIRE_ENUM" | awk -F'\t' '$1=="COUNT"{print $2}' | tr -d '[:space:]')"
  if [ -z "$REQUIRE_COUNT" ] || [ "$REQUIRE_COUNT" = "0" ]; then
    rm -f "$REQUIRE_LIST"
    echo "init desired-state: no prior init record, proceeding to verifier which will prove material."
    return 0
  fi
  while IFS= read -r REQUIRE_BASE || [ -n "$REQUIRE_BASE" ]; do
    [ -n "$REQUIRE_BASE" ] || continue
    REQUIRE_PATH="$LAUNCH_JOURNAL_DIR/$REQUIRE_BASE"
    REQUIRE_VALIDATED="$(validate_init_journal_for_recovery "$REQUIRE_PATH" "$REQUIRE_BASE")" || REQUIRE_VALIDATED="PROOF\tUNREADABLE"
    REQUIRE_VALID_PROOF="$(printf '%s\n' "$REQUIRE_VALIDATED" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$REQUIRE_VALID_PROOF" != "OK" ]; then
      REQUIRE_VALID_OUTCOME="$(printf '%s\n' "$REQUIRE_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
      rm -f "$REQUIRE_LIST"
      echo "refused: init desired-state prior $REQUIRE_BASE is $REQUIRE_VALID_PROOF ${REQUIRE_VALID_OUTCOME:-}, no bypass. Inspect $REQUIRE_PATH." >&2
      phase_failed "$REQUIRE_FAIL_PHASE"
    fi
    REQUIRE_TOKEN="$(printf '%s\n' "$REQUIRE_VALIDATED" | awk -F'\t' '$1=="TOKEN"{print $2}' | tr -d '[:space:]')"
    REQUIRE_TASK="$(printf '%s\n' "$REQUIRE_VALIDATED" | awk -F'\t' '$1=="TASKARN"{print $2}' | tr -d '[:space:]')"
    REQUIRE_TASKDEF="$(printf '%s\n' "$REQUIRE_VALIDATED" | awk -F'\t' '$1=="TASKDEF"{print $2}' | tr -d '[:space:]')"
    REQUIRE_DESC="$(mktemp /tmp/launchcrew-init-desc-XXXXXX)"
    if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$REQUIRE_TASK" --region "$EXPECTED_REGION" --output json >"$REQUIRE_DESC" 2>"$TMP_ERR"; then
      rm -f "$REQUIRE_DESC" "$REQUIRE_LIST"
      echo "refused: init desired-state prior $REQUIRE_BASE terminal state unreadable, no bypass. Inspect $REQUIRE_PATH." >&2
      phase_failed "$REQUIRE_FAIL_PHASE"
    fi
    REQUIRE_DEF_JSON="$(mktemp /tmp/launchcrew-init-def-XXXXXX)"
    if ! "$AWS_BIN" ecs "describe-task""-definition" --task"-definition" "$REQUIRE_TASKDEF" --region "$EXPECTED_REGION" --output json >"$REQUIRE_DEF_JSON" 2>"$TMP_ERR"; then
      rm -f "$REQUIRE_DESC" "$REQUIRE_DEF_JSON" "$REQUIRE_LIST"
      echo "refused: init desired-state prior $REQUIRE_BASE taskdef unreadable, no bypass. Inspect $REQUIRE_PATH." >&2
      phase_failed "$REQUIRE_FAIL_PHASE"
    fi
    REQUIRE_CHECK="$(python3 - "$REQUIRE_DESC" "$REQUIRE_DEF_JSON" "$REQUIRE_TASK" "$REQUIRE_TASKDEF" "arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME" "$REQUIRE_TOKEN" 2>/dev/null <<'PYEOF'
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
)" || REQUIRE_CHECK="UNREADABLE"
    rm -f "$REQUIRE_DESC" "$REQUIRE_DEF_JSON"
    REQUIRE_CHECK="$(printf '%s' "$REQUIRE_CHECK" | tr -d '[:space:]')"
    if [ "$REQUIRE_CHECK" = "OK" ]; then
      echo "init desired-state: $REQUIRE_BASE live-proven STOPPED exit 0, no recovery needed."
      continue
    fi
    if [ "$REQUIRE_CHECK" = "NO_TASK" ]; then
      echo "init desired-state: $REQUIRE_BASE aged out NO_TASK, requiring recovery attestation."
      attest_aged_init_recovery "$REQUIRE_FAIL_PHASE" "$REQUIRE_PATH" "$REQUIRE_BASE"
      echo "init desired-state: $REQUIRE_BASE recovered via attestation, desired-state equivalence, not retroactive proof."
      continue
    fi
    rm -f "$REQUIRE_LIST"
    echo "refused: init desired-state prior $REQUIRE_BASE terminal proof is $REQUIRE_CHECK, no bypass and no recovery for non-NO_TASK. Inspect $REQUIRE_PATH." >&2
    phase_failed "$REQUIRE_FAIL_PHASE"
  done <"$REQUIRE_LIST"
  rm -f "$REQUIRE_LIST"
  echo "init desired-state satisfied for $REQUIRE_FAIL_PHASE: every prior init live-proven or recovered, none bypassed."
}

# Require desired-state equivalence for every prior typed journal before a
# later phase proceeds. Args: calling phase, target phase, label, logical,
# kind, verifier logical, verifier container, allow_started, allow_exit10.
# With zero journals, allow and let the later read-only verifier prove state.
# With any journal, unresolved, foreign, or altered records refuse with no
# bypass. Allowed records that still live-prove STOPPED with allowed exit
# proceed with no recovery. Allowed records that return NO_TASK require a
# valid typed recovery attestation via attest_aged_typed_recovery,
# re-verified live with no new verifier when already complete. Any other
# live proof refuses with no recovery, so general NO_TASK is never success.
# Binder STARTED originals never rerun the binder; they attest via the
# read-only role-state verifier and never relabel STARTED as completed.
require_typed_desired_state() {
  TYPED_REQ_FAIL="$1"
  TYPED_REQ_PHASE="$2"
  TYPED_REQ_LABEL="$3"
  TYPED_REQ_LOGICAL="$4"
  TYPED_REQ_KIND="$5"
  TYPED_REQ_VERIFIER="$6"
  TYPED_REQ_CONTAINER="$7"
  TYPED_REQ_STARTED="${8:-0}"
  TYPED_REQ_ALLOW10="${9:-0}"
  RECOVERY_FAIL_PHASE="$TYPED_REQ_FAIL"
  if [ -z "$LAUNCH_JOURNAL_DIR" ]; then
    case "$0" in
      */*) TYPED_REQ_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd 2>/dev/null || echo "")" ;;
      *) TYPED_REQ_DIR="" ;;
    esac
    if [ -n "$TYPED_REQ_DIR" ] && [ -d "$TYPED_REQ_DIR" ]; then
      LAUNCH_JOURNAL_DIR="$TYPED_REQ_DIR/../../.local/launch-journals"
    else
      echo "$TYPED_REQ_LABEL desired-state journal directory missing, no claim made." >&2
      phase_failed "$TYPED_REQ_FAIL"
    fi
  fi
  if [ -L "$LAUNCH_JOURNAL_DIR" ]; then
    echo "$TYPED_REQ_LABEL desired-state journal directory is a symlink, no claim made." >&2
    phase_failed "$TYPED_REQ_FAIL"
  fi
  if [ ! -d "$LAUNCH_JOURNAL_DIR" ]; then
    echo "$TYPED_REQ_LABEL desired-state: no journal directory, no prior to reconcile, proceeding to verifier."
    return 0
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
  then
    echo "$TYPED_REQ_LABEL desired-state journal directory is not private mode 700 owned, no claim made." >&2
    phase_failed "$TYPED_REQ_FAIL"
  fi
  TYPED_REQ_LIST="$(mktemp /tmp/launchcrew-typed-list-XXXXXX)"
  TYPED_REQ_ENUM="$(python3 - "$LAUNCH_JOURNAL_DIR" "$STACK_NAME" "$TYPED_REQ_PHASE" "$TYPED_REQ_LABEL" "$TYPED_REQ_LIST" 2>/dev/null <<'PYEOF'
import os, sys
directory, stack, phase, label, out_path = sys.argv[1:6]
prefix = "launchcrew-%s-%s-%s-" % (stack, phase, label)
try:
    names = sorted(os.listdir(directory))
except Exception:
    print("PROOF\tLIST_FAILED")
    sys.exit(0)
found = []
for name in names:
    if not name.startswith(prefix) or not name.endswith(".json"):
        continue
    if name.endswith(".lock") or name.endswith(".recovery.json"):
        continue
    found.append(name)
    if len(found) > 32:
        print("PROOF\tTOO_MANY")
        sys.exit(0)
try:
    with open(out_path, "w", encoding="utf-8") as out:
        for name in found:
            out.write(name + "\n")
except Exception:
    print("PROOF\tLIST_FAILED")
    sys.exit(0)
print("PROOF\tOK")
print("COUNT\t%d" % len(found))
PYEOF
)" || TYPED_REQ_ENUM="PROOF\tLIST_FAILED"
  TYPED_REQ_PROOF="$(printf '%s\n' "$TYPED_REQ_ENUM" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
  if [ "$TYPED_REQ_PROOF" != "OK" ]; then
    rm -f "$TYPED_REQ_LIST"
    echo "refused: $TYPED_REQ_LABEL desired-state enumeration is $TYPED_REQ_PROOF, no bypass. Inspect $LAUNCH_JOURNAL_DIR." >&2
    phase_failed "$TYPED_REQ_FAIL"
  fi
  TYPED_REQ_COUNT="$(printf '%s\n' "$TYPED_REQ_ENUM" | awk -F'\t' '$1=="COUNT"{print $2}' | tr -d '[:space:]')"
  if [ -z "$TYPED_REQ_COUNT" ] || [ "$TYPED_REQ_COUNT" = "0" ]; then
    rm -f "$TYPED_REQ_LIST"
    echo "$TYPED_REQ_LABEL desired-state: no prior record, proceeding to verifier which will prove state."
    return 0
  fi
  while IFS= read -r TYPED_REQ_BASE || [ -n "$TYPED_REQ_BASE" ]; do
    [ -n "$TYPED_REQ_BASE" ] || continue
    TYPED_REQ_PATH="$LAUNCH_JOURNAL_DIR/$TYPED_REQ_BASE"
    TYPED_REQ_VALIDATED="$(validate_typed_journal_for_recovery "$TYPED_REQ_PATH" "$TYPED_REQ_BASE" "$TYPED_REQ_PHASE" "$TYPED_REQ_LABEL" "$TYPED_REQ_LOGICAL" "$TYPED_REQ_STARTED")" || TYPED_REQ_VALIDATED="PROOF\tUNREADABLE"
    TYPED_REQ_VPROOF="$(printf '%s\n' "$TYPED_REQ_VALIDATED" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$TYPED_REQ_VPROOF" != "OK" ]; then
      TYPED_REQ_VOUT="$(printf '%s\n' "$TYPED_REQ_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
      rm -f "$TYPED_REQ_LIST"
      echo "refused: $TYPED_REQ_LABEL desired-state prior $TYPED_REQ_BASE is $TYPED_REQ_VPROOF ${TYPED_REQ_VOUT:-}, no bypass. Inspect $TYPED_REQ_PATH." >&2
      phase_failed "$TYPED_REQ_FAIL"
    fi
    TYPED_REQ_TOKEN="$(printf '%s\n' "$TYPED_REQ_VALIDATED" | awk -F'\t' '$1=="TOKEN"{print $2}' | tr -d '[:space:]')"
    TYPED_REQ_TASK="$(printf '%s\n' "$TYPED_REQ_VALIDATED" | awk -F'\t' '$1=="TASKARN"{print $2}' | tr -d '[:space:]')"
    TYPED_REQ_TASKDEF="$(printf '%s\n' "$TYPED_REQ_VALIDATED" | awk -F'\t' '$1=="TASKDEF"{print $2}' | tr -d '[:space:]')"
    TYPED_REQ_OUTCOME="$(printf '%s\n' "$TYPED_REQ_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
    TYPED_REQ_DESC="$(mktemp /tmp/launchcrew-typed-desc-XXXXXX)"
    if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$TYPED_REQ_TASK" --region "$EXPECTED_REGION" --output json >"$TYPED_REQ_DESC" 2>"$TMP_ERR"; then
      rm -f "$TYPED_REQ_DESC" "$TYPED_REQ_LIST"
      echo "refused: $TYPED_REQ_LABEL desired-state prior $TYPED_REQ_BASE terminal state unreadable, no bypass. Inspect $TYPED_REQ_PATH." >&2
      phase_failed "$TYPED_REQ_FAIL"
    fi
    TYPED_REQ_DEF_JSON="$(mktemp /tmp/launchcrew-typed-def-XXXXXX)"
    if ! "$AWS_BIN" ecs "describe-task""-definition" --task"-definition" "$TYPED_REQ_TASKDEF" --region "$EXPECTED_REGION" --output json >"$TYPED_REQ_DEF_JSON" 2>"$TMP_ERR"; then
      rm -f "$TYPED_REQ_DESC" "$TYPED_REQ_DEF_JSON" "$TYPED_REQ_LIST"
      echo "refused: $TYPED_REQ_LABEL desired-state prior $TYPED_REQ_BASE taskdef unreadable, no bypass. Inspect $TYPED_REQ_PATH." >&2
      phase_failed "$TYPED_REQ_FAIL"
    fi
    TYPED_REQ_CHECK="$(python3 - "$TYPED_REQ_DESC" "$TYPED_REQ_DEF_JSON" "$TYPED_REQ_TASK" "$TYPED_REQ_TASKDEF" "arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME" "$TYPED_REQ_TOKEN" "$TYPED_REQ_ALLOW10" 2>/dev/null <<'PYEOF'
import json, sys
try:
    describe = json.load(open(sys.argv[1]))
    defined = json.load(open(sys.argv[2]))
except Exception:
    sys.exit(1)
expected_arn, expected_taskdef, expected_cluster, expected_token, allow10 = sys.argv[3:8]
allow10 = (allow10 == "1")
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
    code = container.get("exitCode", None)
    if container.get("lastStatus") != "STOPPED":
        print("EXIT_NONZERO:" + (container.get("name", "?") or "?"))
        sys.exit(0)
    if not isinstance(code, int) or isinstance(code, bool):
        print("EXIT_NONZERO:" + (container.get("name", "?") or "?"))
        sys.exit(0)
    if code != 0 and not (allow10 and code == 10):
        print("EXIT_NONZERO:" + (container.get("name", "?") or "?"))
        sys.exit(0)
print("OK")
PYEOF
)" || TYPED_REQ_CHECK="UNREADABLE"
    rm -f "$TYPED_REQ_DESC" "$TYPED_REQ_DEF_JSON"
    TYPED_REQ_CHECK="$(printf '%s' "$TYPED_REQ_CHECK" | tr -d '[:space:]')"
    if [ "$TYPED_REQ_CHECK" = "OK" ]; then
      if [ "$TYPED_REQ_OUTCOME" = "started" ]; then
        rm -f "$TYPED_REQ_LIST"
        echo "refused: $TYPED_REQ_LABEL desired-state prior $TYPED_REQ_BASE is STARTED with live STOPPED task, historical ambiguity requires separately reviewed repair, no automatic binder rerun and no relabel. Inspect $TYPED_REQ_PATH." >&2
        phase_failed "$TYPED_REQ_FAIL"
      fi
      echo "$TYPED_REQ_LABEL desired-state: $TYPED_REQ_BASE live-proven STOPPED exit allowed, no recovery needed."
      continue
    fi
    if [ "$TYPED_REQ_CHECK" = "NO_TASK" ]; then
      echo "$TYPED_REQ_LABEL desired-state: $TYPED_REQ_BASE aged out NO_TASK, requiring recovery attestation."
      attest_aged_typed_recovery "$TYPED_REQ_FAIL" "$TYPED_REQ_PATH" "$TYPED_REQ_BASE" "$TYPED_REQ_PHASE" "$TYPED_REQ_LABEL" "$TYPED_REQ_LOGICAL" "$TYPED_REQ_KIND" "$TYPED_REQ_VERIFIER" "$TYPED_REQ_CONTAINER" "$TYPED_REQ_STARTED" "$TYPED_REQ_ALLOW10"
      echo "$TYPED_REQ_LABEL desired-state: $TYPED_REQ_BASE recovered via attestation, desired-state equivalence, not retroactive proof."
      continue
    fi
    rm -f "$TYPED_REQ_LIST"
    echo "refused: $TYPED_REQ_LABEL desired-state prior $TYPED_REQ_BASE terminal proof is $TYPED_REQ_CHECK, no bypass and no recovery for non-NO_TASK. Inspect $TYPED_REQ_PATH." >&2
    phase_failed "$TYPED_REQ_FAIL"
  done <"$TYPED_REQ_LIST"
  rm -f "$TYPED_REQ_LIST"
  echo "$TYPED_REQ_LABEL desired-state satisfied for $TYPED_REQ_FAIL: every prior live-proven or recovered, none bypassed."
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
# argv, files, logs, or journal. Under the same lock, every other owned
# record for this stack, phase, and label across all prior generations is
# enumerated and re-proven terminal before any new release work, so a new
# empty active path never bypasses history.
# Write one private mode 600 preflight journal atomically. Args: journal
# path, outcome, task ARN, observed head, verifier exit, containers, last
# status. Metadata only, no secret value, URL, or key bytes. Uses the exact
# preflight stack, cluster, taskdef, token, config digest, release, source,
# target, and StackId globals. Fails closed via phase_failed on write fault.
write_preflight_journal() {
  PREFLIGHT_JOURNAL_PATH="$1"
  PREFLIGHT_JOURNAL_OUTCOME="$2"
  PREFLIGHT_JOURNAL_TASK="$3"
  PREFLIGHT_JOURNAL_OBSERVED="$4"
  PREFLIGHT_JOURNAL_EXIT="$5"
  PREFLIGHT_JOURNAL_CONTAINERS="$6"
  PREFLIGHT_JOURNAL_LAST="$7"
  (umask 077; python3 - "$PREFLIGHT_JOURNAL_PATH" "$STACK_NAME" "$PREFLIGHT_PHASE" "$PREFLIGHT_LABEL" "$PREFLIGHT_LOGICAL" "$PREFLIGHT_TASKDEF" "$CLUSTER_NAME" "$PREFLIGHT_TOKEN" "$EXPECTED_REGION" "$EXPECTED_ACCOUNT" "$PREFLIGHT_JOURNAL_OUTCOME" "$PREFLIGHT_JOURNAL_TASK" "$PREFLIGHT_CONFIG_DIGEST" "${RELEASE_GEN:-}" "${SOURCE_SHA:-}" "${TARGET_DB_HEAD:-008}" "${STACK_ID:-}" "$PREFLIGHT_JOURNAL_OBSERVED" "$PREFLIGHT_JOURNAL_EXIT" "$PREFLIGHT_JOURNAL_CONTAINERS" "$PREFLIGHT_JOURNAL_LAST" <<'PYEOF'
import json, os, sys, tempfile
if len(sys.argv) != 22:
    raise SystemExit("refused: preflight journal args malformed")
(path, stack, phase, label, taskdef_logical, taskdef_arn, cluster,
 token, region, account, outcome, task_arn, config_digest,
 release_gen, source_sha, target_head, stack_id,
 observed_head, verifier_exit, verifier_containers,
 verifier_last) = sys.argv[1:22]
if os.path.islink(path):
    raise SystemExit("refused: preflight journal path is a symlink")
try:
    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
except Exception:
    stamp = ""
doc = {
    "version": 1,
    "kind": "migration-role-state-preflight",
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
    "observed_head": observed_head,
    "verifier_exit": verifier_exit,
    "verifier_containers": verifier_containers,
    "verifier_last_status": verifier_last,
    "updated_utc": stamp,
}
directory = os.path.dirname(os.path.abspath(path)) or "."
fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".launch-preflight-")
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(doc, out, indent=2, sort_keys=True)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)
    with open(path, "rb") as synced:
        os.fsync(synced.fileno())
    dir_fd = os.open(directory, os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
except Exception:
    try:
        os.unlink(tmp_path)
    except Exception:
        pass
    raise
PYEOF
) || { echo "migration preflight journal write failed, no launch attempted." >&2; phase_failed "$TASK_PHASE"; }
  chmod 600 "$PREFLIGHT_JOURNAL_PATH" 2>/dev/null || { echo "migration preflight journal mode failed, no launch attempted." >&2; phase_failed "$TASK_PHASE"; }
}
# Read-only terminal check for one preflight task. Args: task ARN, token,
# taskdef ARN. Waits for STOPPED as a hint only, then requires ECS
# DescribeTasks tasks and failures to be arrays with exactly one task and
# zero failures, STOPPED lastStatus, exact task and taskdef ARNs, exact
# owned cluster ARN, exact startedBy token, and STOPPED exit 0 or 10 from
# every expected essential container named by the owned DescribeTaskDefinition
# document, with all exits equal. DescribeTasks carries no essential flag
# and none is trusted. Sets PREFLIGHT_TERM_PROOF to OK:<exit>:<containers>
# or a fail-closed reason. Never writes journals and never fails the phase;
# the caller decides.
preflight_terminal_proof() {
  PREFLIGHT_TERM_TASK="$1"
  PREFLIGHT_TERM_TOKEN="$2"
  PREFLIGHT_TERM_TASKDEF="$3"
  PREFLIGHT_TERM_PROOF="UNREADABLE"
  if ! "$AWS_BIN" ecs wait tasks-stopped --cluster "$CLUSTER_NAME" --tasks "$PREFLIGHT_TERM_TASK" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    echo "migration preflight wait reported, verifying terminal state before any claim." >&2
  fi
  PREFLIGHT_TERM_DESC="$(mktemp /tmp/launchcrew-preflight-desc-XXXXXX)"
  if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$PREFLIGHT_TERM_TASK" --region "$EXPECTED_REGION" --output json >"$PREFLIGHT_TERM_DESC" 2>"$TMP_ERR"; then
    rm -f "$PREFLIGHT_TERM_DESC"
    PREFLIGHT_TERM_PROOF="UNREADABLE"
    return 0
  fi
  PREFLIGHT_TERM_DEF="$(mktemp /tmp/launchcrew-preflight-def-XXXXXX)"
  if ! "$AWS_BIN" ecs "describe-task""-definition" --task"-definition" "$PREFLIGHT_TERM_TASKDEF" --region "$EXPECTED_REGION" --output json >"$PREFLIGHT_TERM_DEF" 2>"$TMP_ERR"; then
    rm -f "$PREFLIGHT_TERM_DESC" "$PREFLIGHT_TERM_DEF"
    PREFLIGHT_TERM_PROOF="UNREADABLE"
    return 0
  fi
  PREFLIGHT_TERM_PROOF="$(python3 - "$PREFLIGHT_TERM_DESC" "$PREFLIGHT_TERM_DEF" "$PREFLIGHT_TERM_TASK" "$PREFLIGHT_TERM_TASKDEF" "arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME" "$PREFLIGHT_TERM_TOKEN" 2>/dev/null <<'PYEOF'
import json, sys
try:
    describe = json.load(open(sys.argv[1]))
    defined = json.load(open(sys.argv[2]))
except Exception:
    sys.exit(1)
expected_arn, expected_taskdef, expected_cluster, expected_token = sys.argv[3:7]
if not isinstance(describe, dict) or not isinstance(defined, dict):
    print("MALFORMED_RESPONSE")
    sys.exit(0)
taskdef_doc = defined.get("taskDefinition", defined)
if not isinstance(taskdef_doc, dict):
    print("MALFORMED_TASKDEF")
    sys.exit(0)
container_defs = taskdef_doc.get("containerDefinitions", None)
if not isinstance(container_defs, list):
    print("MALFORMED_TASKDEF")
    sys.exit(0)
expected_names = []
for container in container_defs:
    if not isinstance(container, dict):
        print("MALFORMED_TASKDEF")
        sys.exit(0)
    essential = container.get("essential", True)
    if not isinstance(essential, bool):
        print("MALFORMED_TASKDEF")
        sys.exit(0)
    if not essential:
        continue
    name = container.get("name", "")
    if not isinstance(name, str) or not name:
        print("MALFORMED_TASKDEF")
        sys.exit(0)
    expected_names.append(name)
tasks = describe.get("tasks", None)
failures = describe.get("failures", None)
if not isinstance(tasks, list) or not isinstance(failures, list):
    print("MALFORMED_RESPONSE")
    sys.exit(0)
if len(failures) != 0:
    print("HAS_FAILURES")
    sys.exit(0)
if len(tasks) != 1:
    if len(tasks) == 0:
        print("NO_TASK")
    else:
        print("MULTIPLE_TASKS")
    sys.exit(0)
if not expected_names:
    print("NO_EXPECTED_CONTAINERS")
    sys.exit(0)
task = tasks[0]
if not isinstance(task, dict):
    print("MALFORMED_TASK")
    sys.exit(0)
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
actual = task.get("containers", None)
if not isinstance(actual, list):
    print("MALFORMED_CONTAINERS")
    sys.exit(0)
for entry in actual:
    if not isinstance(entry, dict):
        print("MALFORMED_CONTAINERS")
        sys.exit(0)
    entry_name = entry.get("name", "")
    if not isinstance(entry_name, str) or not entry_name:
        print("MALFORMED_CONTAINERS")
        sys.exit(0)
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
exits = set()
parts = []
for container in actual:
    if container.get("lastStatus") != "STOPPED":
        print("EXIT_NONZERO:" + (container.get("name", "?") or "?"))
        sys.exit(0)
    code = container.get("exitCode", None)
    if not isinstance(code, int) or isinstance(code, bool):
        print("EXIT_NONZERO:" + (container.get("name", "?") or "?"))
        sys.exit(0)
    if code != 0 and code != 10:
        print("EXIT_NONZERO:" + (container.get("name", "?") or "?"))
        sys.exit(0)
    exits.add(code)
    parts.append("%s:STOPPED:%d" % ((container.get("name", "?") or "?"), code))
if len(exits) != 1:
    print("EXIT_MIXED")
    sys.exit(0)
print("OK:%d:%s" % (next(iter(exits)), ",".join(sorted(parts))))
PYEOF
)" || PREFLIGHT_TERM_PROOF="UNREADABLE"
  rm -f "$PREFLIGHT_TERM_DESC" "$PREFLIGHT_TERM_DEF"
  PREFLIGHT_TERM_PROOF="$(printf '%s' "$PREFLIGHT_TERM_PROOF" | tr -d '[:space:]')"
  [ -n "$PREFLIGHT_TERM_PROOF" ] || PREFLIGHT_TERM_PROOF="UNREADABLE"
  return 0
}
# Verify the preflight bootstrap image digest at use time. Same owned
# account, region, repository, explicit tag, no latest, digest present with
# no ECR failures as verify_image, but fails via the preflight task phase
# with no new RunTask. A tag@sha256 pin requires ECR digest equality.
preflight_verify_bootstrap_digest() {
  PREFLIGHT_IMAGE_URI="$BOOTSTRAP_IMAGE"
  case "$PREFLIGHT_IMAGE_URI" in
    *REPLACE_WITH*|*PLACEHOLDER*|"")
      release_operation_lock
      echo "refused: migration preflight bootstrap image is placeholder, no new migration RunTask. Preserved history, no resend." >&2
      phase_failed "$TASK_PHASE" ;;
  esac
  PREFLIGHT_PINNED=""
  case "$PREFLIGHT_IMAGE_URI" in
    *@sha256:*) PREFLIGHT_PINNED="sha256:$(printf '%s' "$PREFLIGHT_IMAGE_URI" | sed 's/^.*@sha256://')"
      PREFLIGHT_BASE="$(printf '%s' "$PREFLIGHT_IMAGE_URI" | cut -d@ -f1)" ;;
    *) PREFLIGHT_BASE="$PREFLIGHT_IMAGE_URI" ;;
  esac
  case "$PREFLIGHT_BASE" in
    *:* ) ;;
    *) release_operation_lock
      echo "refused: migration preflight bootstrap image has no explicit tag, no new migration RunTask. Preserved history, no resend." >&2
      phase_failed "$TASK_PHASE" ;;
  esac
  case "$PREFLIGHT_BASE" in
    *:latest)
      release_operation_lock
      echo "refused: migration preflight bootstrap image uses floating latest, no new migration RunTask. Preserved history, no resend." >&2
      phase_failed "$TASK_PHASE" ;;
  esac
  PREFLIGHT_REPO_FULL="$(printf '%s' "$PREFLIGHT_BASE" | cut -d/ -f2-)"
  PREFLIGHT_REPO_NAME="$(printf '%s' "$PREFLIGHT_REPO_FULL" | cut -d: -f1)"
  PREFLIGHT_IMAGE_TAG="$(printf '%s' "$PREFLIGHT_REPO_FULL" | cut -s -d: -f2)"
  if [ -z "$PREFLIGHT_IMAGE_TAG" ] || [ "$PREFLIGHT_REPO_NAME" != "launchcrew-bootstrap" ]; then
    release_operation_lock
    echo "refused: migration preflight bootstrap image is not owned launchcrew-bootstrap with explicit tag, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  PREFLIGHT_IMAGE_ACCOUNT="$(printf '%s' "$PREFLIGHT_BASE" | cut -d. -f1)"
  PREFLIGHT_IMAGE_REGION="$(printf '%s' "$PREFLIGHT_BASE" | cut -d. -f4)"
  if [ "$PREFLIGHT_IMAGE_ACCOUNT" != "$EXPECTED_ACCOUNT" ] || [ "$PREFLIGHT_IMAGE_REGION" != "$EXPECTED_REGION" ]; then
    release_operation_lock
    echo "refused: migration preflight bootstrap image account or region mismatch, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  if ! PREFLIGHT_DIGEST="$("$AWS_BIN" ecr batch-get-image --repository-name "$PREFLIGHT_REPO_NAME" --image-ids "imageTag=$PREFLIGHT_IMAGE_TAG" --region "$EXPECTED_REGION" --query "images[0].imageId.imageDigest" --output text 2>"$TMP_ERR")"; then
    release_operation_lock
    echo "migration preflight bootstrap image $PREFLIGHT_REPO_NAME:$PREFLIGHT_IMAGE_TAG not found in ECR, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  PREFLIGHT_DIGEST="$(printf '%s' "$PREFLIGHT_DIGEST" | tr -d '[:space:]')"
  if [ -z "$PREFLIGHT_DIGEST" ] || [ "$PREFLIGHT_DIGEST" = "None" ]; then
    release_operation_lock
    echo "refused: migration preflight bootstrap image has no digest in ECR, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  if [ -n "$PREFLIGHT_PINNED" ] && [ "$PREFLIGHT_DIGEST" != "$PREFLIGHT_PINNED" ]; then
    release_operation_lock
    echo "refused: migration preflight bootstrap pinned digest moved, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  if ! PREFLIGHT_FAILURES="$("$AWS_BIN" ecr batch-get-image --repository-name "$PREFLIGHT_REPO_NAME" --image-ids "imageTag=$PREFLIGHT_IMAGE_TAG" --region "$EXPECTED_REGION" --query "length(failures)" --output text 2>"$TMP_ERR")"; then
    release_operation_lock
    echo "migration preflight bootstrap image failure check failed, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  PREFLIGHT_FAILURES="$(printf '%s' "$PREFLIGHT_FAILURES" | tr -d '[:space:]')"
  if [ "$PREFLIGHT_FAILURES" != "0" ]; then
    release_operation_lock
    echo "refused: migration preflight bootstrap image reports ECR failures, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  echo "Verified migration preflight bootstrap image digest with no ECR failures"
}
# Reprove the exact owned RoleState task definition before any RunTask and
# on every journal replay before accepting exit 10 or 0. Proves exact
# Command, EntryPoint, runtime plus migration secret refs with no master,
# roles, image tag, physical ARN, plus ECR digest, then asserts the checked
# ARN equals the ARN resolved for RunTask. Any drift fails closed with no
# resend. The journal parser separately requires the persisted ARN to equal
# the resolved ARN, so checked, persisted, live task, and RunTask ARNs match.
preflight_reprove_taskdef() {
  check_rolestate_taskdef
  PREFLIGHT_CHECKED="$(printf '%s' "${RS_CHECKED_ARN:-}" | tr -d '[:space:]')"
  if [ -z "$PREFLIGHT_CHECKED" ] || [ "$PREFLIGHT_CHECKED" != "$PREFLIGHT_TASKDEF" ]; then
    release_operation_lock
    echo "refused: migration preflight task definition drift between check and use, no new migration RunTask. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  preflight_verify_bootstrap_digest
}
# Durable read-only current-release role-state preflight for a live 007 to
# 008 migration. Runs only under the migration operation lock after all
# historical migration priors are validated with exact completed target007,
# no historical target008, and no legacy. Uses the owned RoleState taskdef
# proven by check_rolestate_taskdef with exact Command --verify-role-state
# plus runtime and migration secrets only and no master, plus physical ARN
# and ECR digest, with check-versus-use ARN equality on every fresh launch
# and every replay. Exit 10 means exact validated head007 ready, exit 0
# means exact validated head008 complete.
# Persists token and journal before RunTask with exact task ARN, cluster,
# taskdef, container, STOPPED, all required container exits, and observed
# head. Restart reuses one persisted token and task with no resend.
# Ambiguous launch, pending, wrong exit, or mismatched identity fails closed
# with no automatic resend. Sets PREFLIGHT_OBSERVED_HEAD to 007 or 008 on
# terminal success. Never claims aged recovery and never fabricates a
# migration receipt. No secret values in argv, files, or logs.
migration_role_state_preflight() {
  PREFLIGHT_PHASE="migrate"
  PREFLIGHT_LABEL="preflight"
  PREFLIGHT_LOGICAL="RoleStateTaskDefinition"
  PREFLIGHT_CONTAINER="bootstrap-db-roles"
  PREFLIGHT_OBSERVED_HEAD=""
  if [ -z "${LAUNCH_JOURNAL_DIR:-}" ] || [ ! -d "$LAUNCH_JOURNAL_DIR" ]; then
    release_operation_lock
    echo "refused: migration preflight needs journal directory with live 007 history, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  if [ -L "$LAUNCH_JOURNAL_DIR" ]; then
    release_operation_lock
    echo "migration preflight journal directory is a symlink, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  case "${RELEASE_GEN:-}" in
    ""|*"/"*|"."|".."|*[!A-Za-z0-9_.-]*)
      release_operation_lock
      echo "refused: migration preflight release generation is missing or malformed, no new migration RunTask. Preserved history, no resend." >&2
      phase_failed "$TASK_PHASE" ;;
  esac
  PREFLIGHT_FILE="$LAUNCH_JOURNAL_DIR/launchcrew-$STACK_NAME-$PREFLIGHT_PHASE-$PREFLIGHT_LABEL-$RELEASE_GEN-active.json"
  if [ -L "$PREFLIGHT_FILE" ]; then
    release_operation_lock
    echo "migration preflight record is a symlink, no new migration RunTask. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  if [ -e "$PREFLIGHT_FILE" ] && [ ! -f "$PREFLIGHT_FILE" ]; then
    release_operation_lock
    echo "migration preflight path exists as non-file, no new migration RunTask. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  if ! PREFLIGHT_TASKDEF="$(stack_resource "$PREFLIGHT_LOGICAL" 2>"$TMP_ERR")"; then
    release_operation_lock
    echo "migration preflight task definition lookup failed before any launch, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  PREFLIGHT_TASKDEF="$(printf '%s' "$PREFLIGHT_TASKDEF" | tr -d '[:space:]')"
  if [ -z "$PREFLIGHT_TASKDEF" ] || [ "$PREFLIGHT_TASKDEF" = "None" ]; then
    release_operation_lock
    echo "migration preflight task definition missing before any launch, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  if ! PREFLIGHT_CONFIG_DIGEST="$(python3 - "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$PREFLIGHT_PHASE" "$PREFLIGHT_LABEL" "$PREFLIGHT_LOGICAL" "$PREFLIGHT_TASKDEF" 2>/dev/null <<'PYEOF'
import hashlib, sys
raw = "|".join(sys.argv[1:9])
print(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32])
PYEOF
)"; then
    release_operation_lock
    echo "migration preflight config digest failed, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  PREFLIGHT_CONFIG_DIGEST="$(printf '%s' "$PREFLIGHT_CONFIG_DIGEST" | tr -d '[:space:]')"
  if [ -z "$PREFLIGHT_CONFIG_DIGEST" ]; then
    release_operation_lock
    echo "migration preflight config digest empty, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  if [ -f "$PREFLIGHT_FILE" ]; then
    PREFLIGHT_EXISTING="$(python3 - "$PREFLIGHT_FILE" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$PREFLIGHT_PHASE" "$PREFLIGHT_LABEL" "$PREFLIGHT_LOGICAL" "$PREFLIGHT_TASKDEF" "$PREFLIGHT_CONFIG_DIGEST" "${RELEASE_GEN:-}" "${SOURCE_SHA:-}" "${TARGET_DB_HEAD:-008}" "${STACK_ID:-}" "$(basename "$PREFLIGHT_FILE")" 2>/dev/null <<'PYEOF'
import hashlib, json, os, sys
(path, want_account, want_region, want_stack, want_cluster,
 want_phase, want_label, want_logical, want_taskdef, want_digest,
 want_gen, want_source, want_head, want_stack_id, want_base) = sys.argv[1:16]
try:
    if os.path.islink(path):
        print("PROOF\tSYMLINK")
        sys.exit(0)
    finfo = os.stat(path)
    if (finfo.st_mode & 0o777) != 0o600:
        print("PROOF\tMODE")
        sys.exit(0)
    if finfo.st_uid != os.getuid():
        print("PROOF\tOWNER")
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
if os.path.basename(path) != want_base:
    print("PROOF\tPATH_MISMATCH")
    sys.exit(0)
allow = {"version", "kind", "stack", "phase", "label", "taskdef_logical",
         "taskdef_arn", "cluster", "client_token", "config_digest",
         "region", "account", "outcome", "task_arn", "release_generation",
         "source_sha", "target_head", "stack_id", "observed_head",
         "verifier_exit", "verifier_containers", "verifier_last_status",
         "updated_utc"}
for key in doc:
    if key not in allow:
        print("PROOF\tFOREIGN_FIELD")
        sys.exit(0)
if doc.get("version", 0) != 1:
    print("PROOF\tVERSION_MISMATCH")
    sys.exit(0)
for _k, _v in doc.items():
    if _k == "version":
        if not isinstance(_v, int) or isinstance(_v, bool):
            print("PROOF\tMALFORMED")
            sys.exit(0)
        continue
    if not isinstance(_v, str):
        print("PROOF\tMALFORMED")
        sys.exit(0)
for _k, _v in doc.items():
    _kl = str(_k).lower()
    if _kl in ("password", "database-url", "database_url",
               "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
               "secret_value", "secretvalue", "private_key", "privatekey",
               "certificate_body", "certificate_chain"):
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
    if isinstance(_v, str):
        _vl = _v.lower()
        if "://" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "password" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
if doc.get("kind", "") != "migration-role-state-preflight":
    print("PROOF\tKIND_MISMATCH")
    sys.exit(0)
for _f, _w in (("account", want_account), ("region", want_region),
               ("stack", want_stack), ("cluster", want_cluster),
               ("phase", want_phase), ("label", want_label),
               ("taskdef_logical", want_logical)):
    if doc.get(_f, "") != _w:
        print("PROOF\t%s_MISMATCH" % _f.upper())
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
if want_source and doc.get("source_sha", "") != want_source:
    print("PROOF\tSOURCE_MISMATCH")
    sys.exit(0)
if doc.get("target_head", "") != want_head:
    print("PROOF\tHEAD_MISMATCH")
    sys.exit(0)
if want_stack_id and doc.get("stack_id", "") != want_stack_id:
    print("PROOF\tSTACKID_MISMATCH")
    sys.exit(0)
_token = doc.get("client_token", "")
if not isinstance(_token, str) or len(_token) != 33 or not _token.startswith("lc-"):
    print("PROOF\tTOKEN_MALFORMED")
    sys.exit(0)
_outcome = doc.get("outcome", "")
if not isinstance(_outcome, str) or not _outcome:
    print("PROOF\tOUTCOME_MISSING")
    sys.exit(0)
_task = doc.get("task_arn", "") or ""
_obs = doc.get("observed_head", "") or ""
_exit = doc.get("verifier_exit", "") or ""
_cont = doc.get("verifier_containers", "") or ""
_last = doc.get("verifier_last_status", "") or ""
if _outcome == "complete":
    if not _task.startswith("arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
        print("PROOF\tTASKARN_FOREIGN")
        sys.exit(0)
    if _obs == "007":
        if _exit != "10" or _cont != "bootstrap-db-roles:STOPPED:10" or _last != "STOPPED":
            print("PROOF\tOBSERVED_MISMATCH")
            sys.exit(0)
    elif _obs == "008":
        if _exit != "0" or _cont != "bootstrap-db-roles:STOPPED:0" or _last != "STOPPED":
            print("PROOF\tOBSERVED_MISMATCH")
            sys.exit(0)
    else:
        print("PROOF\tOBSERVED_MISMATCH")
        sys.exit(0)
elif _outcome == "started":
    if not _task.startswith("arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
        print("PROOF\tTASKARN_FOREIGN")
        sys.exit(0)
    if _obs or _exit or _cont or _last:
        print("PROOF\tOBSERVED_MISMATCH")
        sys.exit(0)
else:
    if _task and not _task.startswith("arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
        print("PROOF\tTASKARN_FOREIGN")
        sys.exit(0)
print("PROOF\tOK")
print("TOKEN\t%s" % _token)
print("TASKARN\t%s" % _task)
print("OUTCOME\t%s" % _outcome)
print("OBSERVED\t%s" % _obs)
print("EXIT\t%s" % _exit)
print("CONTAINERS\t%s" % _cont)
print("LAST\t%s" % _last)
PYEOF
)" || PREFLIGHT_EXISTING="PROOF\tUNREADABLE"
    PREFLIGHT_EXIST_PROOF="$(printf '%s\n' "$PREFLIGHT_EXISTING" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$PREFLIGHT_EXIST_PROOF" != "OK" ]; then
      release_operation_lock
      echo "refused: migration preflight record is $PREFLIGHT_EXIST_PROOF, no new migration RunTask and no preflight resend. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    PREFLIGHT_TOKEN="$(printf '%s\n' "$PREFLIGHT_EXISTING" | awk -F'\t' '$1=="TOKEN"{print $2}' | tr -d '[:space:]')"
    PREFLIGHT_TASK="$(printf '%s\n' "$PREFLIGHT_EXISTING" | awk -F'\t' '$1=="TASKARN"{print $2}' | tr -d '[:space:]')"
    PREFLIGHT_OUTCOME="$(printf '%s\n' "$PREFLIGHT_EXISTING" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
    PREFLIGHT_SAVED_OBSERVED="$(printf '%s\n' "$PREFLIGHT_EXISTING" | awk -F'\t' '$1=="OBSERVED"{print $2}' | tr -d '[:space:]')"
    PREFLIGHT_SAVED_EXIT="$(printf '%s\n' "$PREFLIGHT_EXISTING" | awk -F'\t' '$1=="EXIT"{print $2}' | tr -d '[:space:]')"
    case "$PREFLIGHT_TOKEN" in
      lc-??????????????????????????????) ;;
      *) release_operation_lock
        echo "refused: migration preflight token malformed, no new migration RunTask and no preflight resend. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
        phase_failed "$TASK_PHASE" ;;
    esac
    if [ "$PREFLIGHT_OUTCOME" = "complete" ]; then
      [ -n "$PREFLIGHT_TASK" ] && [ "$PREFLIGHT_TASK" != "None" ] || {
        release_operation_lock
        echo "refused: migration preflight complete has no task ARN, no new migration RunTask and no preflight resend. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
        phase_failed "$TASK_PHASE"
      }
      preflight_reprove_taskdef
      preflight_terminal_proof "$PREFLIGHT_TASK" "$PREFLIGHT_TOKEN" "$PREFLIGHT_TASKDEF"
      case "$PREFLIGHT_TERM_PROOF" in
        OK:10:bootstrap-db-roles:STOPPED:10)
          if [ "$PREFLIGHT_SAVED_OBSERVED" != "007" ] || [ "$PREFLIGHT_SAVED_EXIT" != "10" ]; then
            release_operation_lock
            echo "refused: migration preflight persisted head does not match live exit 10, no new migration RunTask and no preflight resend. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
            phase_failed "$TASK_PHASE"
          fi
          PREFLIGHT_OBSERVED_HEAD="007"
          echo "migration preflight re-proved STOPPED exit 10 with observed head007 ready, reusing one persisted token and task with no resend."
          return 0 ;;
        OK:0:bootstrap-db-roles:STOPPED:0)
          if [ "$PREFLIGHT_SAVED_OBSERVED" != "008" ] || [ "$PREFLIGHT_SAVED_EXIT" != "0" ]; then
            release_operation_lock
            echo "refused: migration preflight persisted head does not match live exit 0, no new migration RunTask and no preflight resend. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
            phase_failed "$TASK_PHASE"
          fi
          PREFLIGHT_OBSERVED_HEAD="008"
          echo "migration preflight re-proved STOPPED exit 0 with observed head008 complete, reusing one persisted token and task with no resend."
          return 0 ;;
        *)
          release_operation_lock
          echo "refused: migration preflight live terminal proof is $PREFLIGHT_TERM_PROOF, no new migration RunTask and no preflight resend. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
          phase_failed "$TASK_PHASE" ;;
      esac
    fi
    if [ "$PREFLIGHT_OUTCOME" = "started" ]; then
      [ -n "$PREFLIGHT_TASK" ] && [ "$PREFLIGHT_TASK" != "None" ] || {
        release_operation_lock
        echo "refused: migration preflight started has no task ARN, no new migration RunTask and no preflight resend. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
        phase_failed "$TASK_PHASE"
      }
      echo "migration preflight prior started, re-proving terminal state with no resend."
      preflight_reprove_taskdef
      preflight_terminal_proof "$PREFLIGHT_TASK" "$PREFLIGHT_TOKEN" "$PREFLIGHT_TASKDEF"
      case "$PREFLIGHT_TERM_PROOF" in
        OK:10:bootstrap-db-roles:STOPPED:10)
          write_preflight_journal "$PREFLIGHT_FILE" "complete" "$PREFLIGHT_TASK" "007" "10" "bootstrap-db-roles:STOPPED:10" "STOPPED"
          PREFLIGHT_OBSERVED_HEAD="007"
          echo "migration preflight terminal proof: STOPPED, exact owned task and cluster ARNs, every expected container exit 10 with observed head007 ready."
          return 0 ;;
        OK:0:bootstrap-db-roles:STOPPED:0)
          write_preflight_journal "$PREFLIGHT_FILE" "complete" "$PREFLIGHT_TASK" "008" "0" "bootstrap-db-roles:STOPPED:0" "STOPPED"
          PREFLIGHT_OBSERVED_HEAD="008"
          echo "migration preflight terminal proof: STOPPED, exact owned task and cluster ARNs, every expected container exit 0 with observed head008 complete."
          return 0 ;;
        *)
          release_operation_lock
          echo "refused: migration preflight live terminal proof is $PREFLIGHT_TERM_PROOF, no new migration RunTask and no preflight resend. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
          phase_failed "$TASK_PHASE" ;;
      esac
    fi
    release_operation_lock
    echo "refused: migration preflight prior $PREFLIGHT_OUTCOME is unresolved, restart uses one persisted token and task with no resend, manual review required with zero new migration RunTask. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  preflight_reprove_taskdef
  if ! PREFLIGHT_TOKEN="$(python3 - 2>/dev/null <<'PYEOF'
import uuid
print("lc-" + uuid.uuid4().hex[:30])
PYEOF
)"; then
    release_operation_lock
    echo "migration preflight client token generation failed, no new migration RunTask. Preserved history, no resend." >&2
    phase_failed "$TASK_PHASE"
  fi
  PREFLIGHT_TOKEN="$(printf '%s' "$PREFLIGHT_TOKEN" | tr -d '[:space:]')"
  case "$PREFLIGHT_TOKEN" in
    lc-??????????????????????????????) ;;
    *) release_operation_lock
      echo "migration preflight client token malformed, no new migration RunTask. Preserved history, no resend." >&2
      phase_failed "$TASK_PHASE" ;;
  esac
  PREFLIGHT_TASK=""
  write_preflight_journal "$PREFLIGHT_FILE" "pending" "" "" "" "" ""
  echo "migration preflight journal written before run-task: $PREFLIGHT_FILE"
  PREFLIGHT_RUN_JSON="$(mktemp /tmp/launchcrew-preflight-run-XXXXXX)"
  PREFLIGHT_RUN_OK=1
  if ! "$AWS_BIN" ecs run-task --cluster "$CLUSTER_NAME" --task"-definition" "$PREFLIGHT_TASKDEF" --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$JOB_SG],assignPublicIp=ENABLED}" --client-token "$PREFLIGHT_TOKEN" --started-by "$PREFLIGHT_TOKEN" --region "$EXPECTED_REGION" --output json >"$PREFLIGHT_RUN_JSON" 2>"$TMP_ERR"; then
    PREFLIGHT_RUN_OK=0
  fi
  if [ "$PREFLIGHT_RUN_OK" -eq 0 ]; then
    rm -f "$PREFLIGHT_RUN_JSON"
    write_preflight_journal "$PREFLIGHT_FILE" "ambiguous_call_failed" "" "" "" "" ""
    release_operation_lock
    echo "refused: migration preflight run-task call failed; launch is ambiguous with no automatic resend and zero new migration RunTask. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
    phase_failed "$TASK_PHASE"
  fi
  PREFLIGHT_TASK="$(python3 - "$PREFLIGHT_RUN_JSON" 2>/dev/null <<'PYEOF'
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
)" || PREFLIGHT_TASK="UNREADABLE"
  rm -f "$PREFLIGHT_RUN_JSON"
  PREFLIGHT_TASK="$(printf '%s' "$PREFLIGHT_TASK" | tr -d '[:space:]')"
  case "$PREFLIGHT_TASK" in
    FAILURES|EMPTY|MULTIPLE|UNREADABLE|"")
      write_preflight_journal "$PREFLIGHT_FILE" "ambiguous_response" "" "" "" "" ""
      release_operation_lock
      echo "refused: migration preflight run-task response is ${PREFLIGHT_TASK:-empty}; launch is ambiguous with no automatic resend and zero new migration RunTask. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
      phase_failed "$TASK_PHASE" ;;
  esac
  write_preflight_journal "$PREFLIGHT_FILE" "started" "$PREFLIGHT_TASK" "" "" "" ""
  echo "migration preflight task started in isolated public subnets with no inbound: $PREFLIGHT_TASK"
  preflight_terminal_proof "$PREFLIGHT_TASK" "$PREFLIGHT_TOKEN" "$PREFLIGHT_TASKDEF"
  case "$PREFLIGHT_TERM_PROOF" in
    OK:10:bootstrap-db-roles:STOPPED:10)
      write_preflight_journal "$PREFLIGHT_FILE" "complete" "$PREFLIGHT_TASK" "007" "10" "bootstrap-db-roles:STOPPED:10" "STOPPED"
      PREFLIGHT_OBSERVED_HEAD="007"
      echo "migration preflight terminal proof: STOPPED, exact owned task and cluster ARNs, every expected container exit 10 with observed head007 ready."
      return 0 ;;
    OK:0:bootstrap-db-roles:STOPPED:0)
      write_preflight_journal "$PREFLIGHT_FILE" "complete" "$PREFLIGHT_TASK" "008" "0" "bootstrap-db-roles:STOPPED:0" "STOPPED"
      PREFLIGHT_OBSERVED_HEAD="008"
      echo "migration preflight terminal proof: STOPPED, exact owned task and cluster ARNs, every expected container exit 0 with observed head008 complete."
      return 0 ;;
    *)
      release_operation_lock
      echo "refused: migration preflight terminal proof is $PREFLIGHT_TERM_PROOF, no new migration RunTask and no preflight resend. Preserved history, no resend. Inspect $PREFLIGHT_FILE." >&2
      phase_failed "$TASK_PHASE" ;;
  esac
}
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
  RECOVERED_AGED_PRIOR_INIT=0
  RECOVERED_AGED_PRIOR_MATERIAL=0
  RECOVERED_AGED_PRIOR_DBROLES=0
  RECOVERED_AGED_PRIOR_MIGRATION=0
  RECOVERED_AGED_PRIOR_VERIFY=0
  acquire_operation_lock
  # Legacy unversioned predecessor allows a different family after
  # replacement (Family omitted, so a new family may appear). It still
  # requires exact recorded account, region, stack, cluster, phase, label,
  # logical, StackId when present, recomputed digest when present, valid
  # old ARN shape with account and region, live operation shape for the
  # recorded logical, and live STOPPED exit 0 proof before any new RunTask.
  # It never compares the old ARN or family to the current taskdef.
  if [ -f "$LEGACY_ACTIVE_FILE" ]; then
    LEGACY_PARSED="$(python3 - "$LEGACY_ACTIVE_FILE" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$TASK_PHASE" "$TASK_LABEL" "$TASKDEF_LOGICAL" "${STACK_ID:-}" 2>/dev/null <<'PYEOF'
import hashlib, json, os, sys
(path, want_account, want_region, want_stack, want_cluster,
 want_phase, want_label, want_logical,
 want_stack_id) = sys.argv[1:10]
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
for _k, _v in doc.items():
    if _k == "version":
        if not isinstance(_v, int) or isinstance(_v, bool):
            print("PROOF\tMALFORMED")
            sys.exit(0)
        continue
    if not isinstance(_v, str):
        print("PROOF\tMALFORMED")
        sys.exit(0)
for _k, _v in doc.items():
    _kl = str(_k).lower()
    if _kl in ("password", "database-url", "database_url",
               "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
               "secret_value", "secretvalue", "private_key", "privatekey",
               "certificate_body", "certificate_chain"):
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
    if isinstance(_v, str):
        _vl = _v.lower()
        if "://" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "password" in _vl:
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
if want_stack_id and "stack_id" in doc:
    rec_stack = doc.get("stack_id", "")
    if not isinstance(rec_stack, str):
        print("PROOF\tSTACKID_MISMATCH")
        sys.exit(0)
    if rec_stack != "" and rec_stack != want_stack_id:
        print("PROOF\tSTACKID_MISMATCH")
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
taskdef_arn = doc.get("taskdef_arn", "") or ""
if not isinstance(taskdef_arn, str) or not taskdef_arn.startswith(
        "arn:aws:ecs:%s:%s:task" "-definition/" % (want_region, want_account)):
    print("PROOF\tTASKDEF_FOREIGN")
    sys.exit(0)
try:
    tail = taskdef_arn.split(":task" "-definition/", 1)[1]
    rec_family = tail.split(":", 1)[0]
    rec_revision = tail.split(":", 1)[1] if ":" in tail else ""
except Exception:
    rec_family = ""
    rec_revision = ""
if not rec_family or not rec_revision:
    print("PROOF\tTASKDEF_MALFORMED")
    sys.exit(0)
if "config_digest" in doc:
    try:
        rec_digest = doc.get("config_digest", "")
        raw = "|".join([
            doc.get("account", ""), doc.get("region", ""),
            doc.get("stack", ""), doc.get("cluster", ""),
            doc.get("phase", ""), doc.get("label", ""),
            doc.get("taskdef_logical", ""), doc.get("taskdef_arn", ""),
        ])
        expect_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        if not isinstance(rec_digest, str) or rec_digest != expect_digest:
            print("PROOF\tCONFIG_MISMATCH")
            sys.exit(0)
    except Exception:
        print("PROOF\tCONFIG_MISMATCH")
        sys.exit(0)
if outcome != "complete":
    print("PROOF\tOK")
    print("OUTCOME\t%s" % outcome)
    print("TOKEN\t%s" % token)
    print("TASKARN\t%s" % task_arn)
    print("TASKDEF\t%s" % taskdef_arn)
    sys.exit(0)
if not task_arn.startswith(
        "arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
    print("PROOF\tTASKARN_FOREIGN")
    sys.exit(0)
print("PROOF\tOK")
print("OUTCOME\t%s" % outcome)
print("TOKEN\t%s" % token)
print("TASKARN\t%s" % task_arn)
print("TASKDEF\t%s" % taskdef_arn)
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
    if [ "$TASK_LABEL" = "bootstrap" ] && [ "$TASK_PHASE" = "dbroles" ]; then
      if [ "$LEGACY_OUTCOME" != "complete" ] && [ "$LEGACY_OUTCOME" != "started" ]; then
        echo "refused: $TASK_LABEL legacy generation is $LEGACY_OUTCOME, not complete or started. Reconcile the prior generation before any new $RELEASE_GEN launch. Legacy preserved at $LEGACY_ACTIVE_FILE, no new launch." >&2
        phase_failed "$TASK_PHASE"
      fi
    else
      if [ "$LEGACY_OUTCOME" != "complete" ]; then
        echo "refused: $TASK_LABEL legacy generation is $LEGACY_OUTCOME, not complete. Reconcile the prior generation to STOPPED with all essential exits 0 before any new $RELEASE_GEN launch. Legacy preserved at $LEGACY_ACTIVE_FILE, no new launch." >&2
        phase_failed "$TASK_PHASE"
      fi
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
    case "$TASKDEF_LOGICAL" in
      SdkInitTaskDefinition)
        LEGACY_EXPECT_EXEC="SdkInitExecutionRole"
        LEGACY_EXPECT_TASK="SdkInitTaskRole"
        LEGACY_EXPECT_CONTAINER="sdk-init"
        LEGACY_EXPECT_COMMAND="--populate"
        LEGACY_EXPECT_ENTRYPOINT="1"
        LEGACY_EXPECT_IMAGE="${BOOTSTRAP_IMAGE:-}"
        ;;
      SdkMaterialTaskDefinition)
        LEGACY_EXPECT_EXEC="SdkMaterialExecutionRole"
        LEGACY_EXPECT_TASK="SdkMaterialTaskRole"
        LEGACY_EXPECT_CONTAINER="sdk-material"
        LEGACY_EXPECT_COMMAND="--verify-material"
        LEGACY_EXPECT_ENTRYPOINT="1"
        LEGACY_EXPECT_IMAGE="${BOOTSTRAP_IMAGE:-}"
        ;;
      MigrationTaskDefinition)
        LEGACY_EXPECT_EXEC="MigrationExecutionRole"
        LEGACY_EXPECT_TASK="MigrationTaskRole"
        LEGACY_EXPECT_CONTAINER="migration"
        LEGACY_EXPECT_COMMAND="ABSENT"
        LEGACY_EXPECT_ENTRYPOINT="ABSENT"
        LEGACY_EXPECT_IMAGE="${MIGRATION_IMAGE:-}"
        ;;
      BootstrapTaskDefinition)
        LEGACY_EXPECT_EXEC="BootstrapExecutionRole"
        LEGACY_EXPECT_TASK="BootstrapTaskRole"
        LEGACY_EXPECT_CONTAINER="bootstrap-db-roles"
        LEGACY_EXPECT_COMMAND="ABSENT"
        LEGACY_EXPECT_ENTRYPOINT="ABSENT"
        LEGACY_EXPECT_IMAGE="${BOOTSTRAP_IMAGE:-}"
        ;;
      VerifyTaskDefinition)
        LEGACY_EXPECT_EXEC="VerifyExecutionRole"
        LEGACY_EXPECT_TASK="VerifyTaskRole"
        LEGACY_EXPECT_CONTAINER="bootstrap-db-roles"
        LEGACY_EXPECT_COMMAND="--verify"
        LEGACY_EXPECT_ENTRYPOINT="ABSENT"
        LEGACY_EXPECT_IMAGE="${BOOTSTRAP_IMAGE:-}"
        ;;
      *)
        rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
        echo "refused: $TASK_LABEL legacy operation $TASKDEF_LOGICAL unknown, no new launch. Inspect $LEGACY_ACTIVE_FILE." >&2
        phase_failed "$TASK_PHASE"
        ;;
    esac
    if ! LEGACY_EXPECT_EXEC_ARN="$(resolve_role_arn "$LEGACY_EXPECT_EXEC")"; then
      rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
      echo "refused: $TASK_LABEL legacy predecessor expected execution role unresolvable, no new launch. Inspect $LEGACY_ACTIVE_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    if ! LEGACY_EXPECT_TASK_ARN="$(resolve_role_arn "$LEGACY_EXPECT_TASK")"; then
      rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
      echo "refused: $TASK_LABEL legacy predecessor expected task role unresolvable, no new launch. Inspect $LEGACY_ACTIVE_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    LEGACY_EXPECT_EXEC_ARN="$(printf '%s' "$LEGACY_EXPECT_EXEC_ARN" | tr -d '[:space:]')"
    LEGACY_EXPECT_TASK_ARN="$(printf '%s' "$LEGACY_EXPECT_TASK_ARN" | tr -d '[:space:]')"
    LEGACY_EXPECT_IMAGE="$(printf '%s' "${LEGACY_EXPECT_IMAGE:-}" | tr -d '[:space:]')"
    if [ -z "$LEGACY_EXPECT_IMAGE" ] || [ "$LEGACY_EXPECT_IMAGE" = "None" ]; then
      rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
      echo "refused: $TASK_LABEL legacy predecessor expected image missing, no new $RELEASE_GEN launch. Inspect $LEGACY_ACTIVE_FILE." >&2
      phase_failed "$TASK_PHASE"
    fi
    case "$TASKDEF_LOGICAL" in
      BootstrapTaskDefinition)
        [ -n "${MASTER_SECRET_ARN:-}" ] && [ -n "${RUNTIME_SECRET_ARN:-}" ] && [ -n "${MIGRATION_SECRET_ARN:-}" ] || {
          rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
          echo "refused: $TASK_LABEL legacy predecessor needs exact master, runtime and migration secret ARNs for operation proof, no new $RELEASE_GEN launch. Inspect $LEGACY_ACTIVE_FILE." >&2
          phase_failed "$TASK_PHASE"
        } ;;
      MigrationTaskDefinition)
        [ -n "${MIGRATION_SECRET_ARN:-}" ] || {
          rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
          echo "refused: $TASK_LABEL legacy predecessor needs exact migration secret ARN for operation proof, no new $RELEASE_GEN launch. Inspect $LEGACY_ACTIVE_FILE." >&2
          phase_failed "$TASK_PHASE"
        } ;;
      VerifyTaskDefinition)
        [ -n "${RUNTIME_SECRET_ARN:-}" ] || {
          rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
          echo "refused: $TASK_LABEL legacy predecessor needs exact runtime secret ARN for operation proof, no new $RELEASE_GEN launch. Inspect $LEGACY_ACTIVE_FILE." >&2
          phase_failed "$TASK_PHASE"
        } ;;
    esac
    LEGACY_ACTUAL_IMAGE="$(python3 - "$LEGACY_TASKDEF_JSON" "$LEGACY_EXPECT_CONTAINER" 2>/dev/null <<'PYEOF'
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
)" || LEGACY_ACTUAL_IMAGE="UNREADABLE"
    LEGACY_ACTUAL_IMAGE="$(printf '%s' "$LEGACY_ACTUAL_IMAGE" | tr -d '[:space:]')"
    if [ -n "$LEGACY_ACTUAL_IMAGE" ] && [ "$LEGACY_ACTUAL_IMAGE" != "MISSING_CONTAINER" ] && [ "$LEGACY_ACTUAL_IMAGE" != "MISSING_IMAGE" ] && [ "$LEGACY_ACTUAL_IMAGE" != "UNREADABLE" ] && [ "$LEGACY_ACTUAL_IMAGE" != "None" ] && [ "$LEGACY_ACTUAL_IMAGE" != "$LEGACY_EXPECT_IMAGE" ]; then
      case "$TASKDEF_LOGICAL" in
        MigrationTaskDefinition) LEGACY_HIST_REPO="launchcrew-migration" ;;
        *) LEGACY_HIST_REPO="launchcrew-bootstrap" ;;
      esac
      if ! verify_historical_image "$LEGACY_ACTUAL_IMAGE" "$LEGACY_HIST_REPO" "$TASK_LABEL"; then
        rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
        phase_failed "$TASK_PHASE"
      fi
      LEGACY_EXPECT_IMAGE="$LEGACY_ACTUAL_IMAGE"
      echo "Verified legacy $TASK_LABEL historical image differs from current CLI but is owned pinned with digest, operation proof continues."
    fi
    LEGACY_OPERATION="$(python3 - "$LEGACY_TASKDEF_JSON" "$LEGACY_EXPECT_CONTAINER" "$LEGACY_EXPECT_COMMAND" "$LEGACY_EXPECT_ENTRYPOINT" "$LEGACY_EXPECT_EXEC_ARN" "$LEGACY_EXPECT_TASK_ARN" "$LEGACY_EXPECT_IMAGE" "${RUNTIME_SECRET_ARN:-}" "${MIGRATION_SECRET_ARN:-}" "${MASTER_SECRET_ARN:-}" "$TASKDEF_LOGICAL" 2>/dev/null <<'PYEOF'
import json, sys
(doc_file, want_container, want_command, want_entry, want_exec, want_task,
 want_image, want_rt, want_mg, want_master, want_logical) = sys.argv[1:12]
try:
    doc = json.load(open(doc_file))
except Exception:
    sys.exit(1)
taskdef = doc.get("taskDefinition", doc)
if (taskdef.get("executionRoleArn", "") or "") != want_exec:
    print("TASKDEF_OPERATION_MISMATCH:EXEC_ROLE")
    sys.exit(0)
if (taskdef.get("taskRoleArn", "") or "") != want_task:
    print("TASKDEF_OPERATION_MISMATCH:TASK_ROLE")
    sys.exit(0)
containers = taskdef.get("containerDefinitions", None)
if not isinstance(containers, list) or len(containers) != 1:
    print("TASKDEF_OPERATION_MISMATCH:CONTAINER_COUNT")
    sys.exit(0)
target = containers[0]
if not isinstance(target, dict):
    print("TASKDEF_OPERATION_MISMATCH:MISSING_CONTAINER")
    sys.exit(0)
if (target.get("name", "") or "") != want_container or not target.get("essential", True):
    print("TASKDEF_OPERATION_MISMATCH:MISSING_CONTAINER")
    sys.exit(0)
if not want_image or want_image == "None":
    print("TASKDEF_OPERATION_MISMATCH:IMAGE_MISSING")
    sys.exit(0)
if (target.get("image", "") or "") != want_image:
    print("TASKDEF_OPERATION_MISMATCH:IMAGE")
    sys.exit(0)
if want_entry == "1":
    if (target.get("entryPoint", None) or []) != ["/opt/venv/bin/python", "/app/scripts/populate_prereqs.py"]:
        print("TASKDEF_OPERATION_MISMATCH:ENTRYPOINT")
        sys.exit(0)
elif want_entry == "ABSENT":
    _ep = target.get("entryPoint", None)
    if _ep not in (None, []):
        print("TASKDEF_OPERATION_MISMATCH:ENTRYPOINT")
        sys.exit(0)
else:
    print("TASKDEF_OPERATION_MISMATCH:ENTRYPOINT_UNKNOWN")
    sys.exit(0)
if want_command == "ABSENT":
    _cmd = target.get("command", None)
    if _cmd not in (None, []):
        print("TASKDEF_OPERATION_MISMATCH:COMMAND")
        sys.exit(0)
elif want_command:
    if (target.get("command", None) or []) != [want_command]:
        print("TASKDEF_OPERATION_MISMATCH:COMMAND")
        sys.exit(0)
else:
    print("TASKDEF_OPERATION_MISMATCH:COMMAND_UNKNOWN")
    sys.exit(0)
actual = {}
for secret in target.get("secrets", []) or []:
    if not isinstance(secret, dict):
        print("TASKDEF_OPERATION_MISMATCH:SECRET_MALFORMED")
        sys.exit(0)
    _n = secret.get("name", "") or ""
    _v = secret.get("valueFrom", "") or ""
    if not _n or not _v:
        print("TASKDEF_OPERATION_MISMATCH:SECRET_MALFORMED")
        sys.exit(0)
    if _n in actual:
        print("TASKDEF_OPERATION_MISMATCH:SECRET_DUPLICATE")
        sys.exit(0)
    actual[_n] = _v
if want_logical in ("SdkInitTaskDefinition", "SdkMaterialTaskDefinition"):
    if actual:
        print("TASKDEF_OPERATION_MISMATCH:UNEXPECTED_SECRET")
        sys.exit(0)
elif want_logical == "BootstrapTaskDefinition":
    if not want_rt or not want_mg or not want_master:
        print("TASKDEF_OPERATION_MISMATCH:SECRET_EXPECTED_MISSING")
        sys.exit(0)
    want = {
        "MASTER_DB_PASSWORD": "%s:password::" % want_master,
        "RUNTIME_DB_URL": "%s:database-url::" % want_rt,
        "MIGRATION_DB_URL": "%s:database-url::" % want_mg,
    }
    for key in sorted(want):
        if key not in actual:
            print("TASKDEF_OPERATION_MISMATCH:MISSING_SECRET")
            sys.exit(0)
        if actual[key] != want[key]:
            print("TASKDEF_OPERATION_MISMATCH:SECRET")
            sys.exit(0)
    for key in sorted(actual):
        if key not in want:
            print("TASKDEF_OPERATION_MISMATCH:UNEXPECTED_SECRET")
            sys.exit(0)
elif want_logical == "MigrationTaskDefinition":
    if not want_mg:
        print("TASKDEF_OPERATION_MISMATCH:SECRET_EXPECTED_MISSING")
        sys.exit(0)
    want = {"DATABASE_URL": "%s:database-url::" % want_mg}
    for key in sorted(want):
        if key not in actual:
            print("TASKDEF_OPERATION_MISMATCH:MISSING_SECRET")
            sys.exit(0)
        if actual[key] != want[key]:
            print("TASKDEF_OPERATION_MISMATCH:SECRET")
            sys.exit(0)
    for key in sorted(actual):
        if key not in want:
            print("TASKDEF_OPERATION_MISMATCH:UNEXPECTED_SECRET")
            sys.exit(0)
elif want_logical == "VerifyTaskDefinition":
    if not want_rt:
        print("TASKDEF_OPERATION_MISMATCH:SECRET_EXPECTED_MISSING")
        sys.exit(0)
    want = {"RUNTIME_DB_URL": "%s:database-url::" % want_rt}
    for key in sorted(want):
        if key not in actual:
            print("TASKDEF_OPERATION_MISMATCH:MISSING_SECRET")
            sys.exit(0)
        if actual[key] != want[key]:
            print("TASKDEF_OPERATION_MISMATCH:SECRET")
            sys.exit(0)
    for key in sorted(actual):
        if key not in want:
            print("TASKDEF_OPERATION_MISMATCH:UNEXPECTED_SECRET")
            sys.exit(0)
else:
    print("TASKDEF_OPERATION_MISMATCH:LOGICAL_UNKNOWN")
    sys.exit(0)
print("OK")
PYEOF
)" || LEGACY_OPERATION="UNREADABLE"
    LEGACY_OPERATION="$(printf '%s' "$LEGACY_OPERATION" | tr -d '[:space:]')"
    if [ "$LEGACY_OPERATION" != "OK" ]; then
      rm -f "$LEGACY_DESC" "$LEGACY_TASKDEF_JSON"
      echo "refused: $TASK_LABEL legacy predecessor operation proof is $LEGACY_OPERATION, no new $RELEASE_GEN launch. Inspect $LEGACY_ACTIVE_FILE." >&2
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
      if [ "$LEGACY_CHECK" = "NO_TASK" ] && [ "$TASK_LABEL" = "sdk-init" ] && [ "$TASK_PHASE" = "init" ]; then
        echo "$TASK_LABEL legacy predecessor aged out NO_TASK, requiring recovery attestation before new $RELEASE_GEN launch."
        attest_aged_init_recovery "$TASK_PHASE" "$LEGACY_ACTIVE_FILE" "$(basename "$LEGACY_ACTIVE_FILE")"
        echo "$TASK_LABEL legacy predecessor recovered via attestation, desired-state equivalence for new $RELEASE_GEN, not retroactive proof. Preserved at $LEGACY_ACTIVE_FILE."
        PREDECESSOR_TASK="$LEGACY_TASK"
        PREDECESSOR_OUTCOME="recovered"
        RECOVERED_AGED_PRIOR_INIT=1
      elif [ "$LEGACY_CHECK" = "NO_TASK" ] && [ "$TASK_LABEL" = "sdk-material" ] && [ "$TASK_PHASE" = "material" ]; then
        echo "$TASK_LABEL legacy predecessor aged out NO_TASK, requiring recovery attestation before new $RELEASE_GEN launch."
        attest_aged_typed_recovery "$TASK_PHASE" "$LEGACY_ACTIVE_FILE" "$(basename "$LEGACY_ACTIVE_FILE")" "material" "sdk-material" "SdkMaterialTaskDefinition" "material-recovery-attestation" "SdkMaterialTaskDefinition" "sdk-material" "0" "0"
        echo "$TASK_LABEL legacy predecessor recovered via attestation, desired-state equivalence for new $RELEASE_GEN, not retroactive proof. Preserved at $LEGACY_ACTIVE_FILE."
        PREDECESSOR_TASK="$LEGACY_TASK"
        PREDECESSOR_OUTCOME="recovered"
        RECOVERED_AGED_PRIOR_MATERIAL=1
      elif [ "$LEGACY_CHECK" = "NO_TASK" ] && [ "$TASK_LABEL" = "bootstrap" ] && [ "$TASK_PHASE" = "dbroles" ]; then
        echo "$TASK_LABEL legacy predecessor aged out NO_TASK, requiring recovery attestation before new $RELEASE_GEN launch."
        attest_aged_typed_recovery "$TASK_PHASE" "$LEGACY_ACTIVE_FILE" "$(basename "$LEGACY_ACTIVE_FILE")" "dbroles" "bootstrap" "BootstrapTaskDefinition" "dbroles-recovery-attestation" "RoleStateTaskDefinition" "bootstrap-db-roles" "1" "1"
        echo "$TASK_LABEL legacy predecessor recovered via attestation, desired-state equivalence for new $RELEASE_GEN, never a binder rerun and never a relabel of STARTED. Preserved at $LEGACY_ACTIVE_FILE."
        PREDECESSOR_TASK="$LEGACY_TASK"
        PREDECESSOR_OUTCOME="recovered"
        RECOVERED_AGED_PRIOR_DBROLES=1
      elif [ "$LEGACY_CHECK" = "NO_TASK" ] && [ "$TASK_LABEL" = "migration" ] && [ "$TASK_PHASE" = "migrate" ]; then
        echo "$TASK_LABEL legacy predecessor aged out NO_TASK, requiring recovery attestation before new $RELEASE_GEN launch."
        attest_aged_typed_recovery "$TASK_PHASE" "$LEGACY_ACTIVE_FILE" "$(basename "$LEGACY_ACTIVE_FILE")" "migrate" "migration" "MigrationTaskDefinition" "migration-recovery-attestation" "RoleStateTaskDefinition" "bootstrap-db-roles" "0" "1"
        echo "$TASK_LABEL legacy predecessor recovered via attestation, desired-state equivalence for new $RELEASE_GEN, not retroactive proof. Preserved at $LEGACY_ACTIVE_FILE."
        PREDECESSOR_TASK="$LEGACY_TASK"
        PREDECESSOR_OUTCOME="recovered"
        RECOVERED_AGED_PRIOR_MIGRATION=1
      elif [ "$LEGACY_CHECK" = "NO_TASK" ] && [ "$TASK_LABEL" = "verify" ] && [ "$TASK_PHASE" = "migrate" ]; then
        echo "$TASK_LABEL legacy predecessor aged out NO_TASK, requiring recovery attestation before new $RELEASE_GEN launch."
        attest_aged_typed_recovery "$TASK_PHASE" "$LEGACY_ACTIVE_FILE" "$(basename "$LEGACY_ACTIVE_FILE")" "migrate" "verify" "VerifyTaskDefinition" "runtime-recovery-attestation" "VerifyTaskDefinition" "bootstrap-db-roles" "0" "0"
        echo "$TASK_LABEL legacy predecessor recovered via attestation, desired-state equivalence for new $RELEASE_GEN, not retroactive proof. Preserved at $LEGACY_ACTIVE_FILE."
        PREDECESSOR_TASK="$LEGACY_TASK"
        PREDECESSOR_OUTCOME="recovered"
        RECOVERED_AGED_PRIOR_VERIFY=1
      else
        echo "refused: $TASK_LABEL legacy predecessor terminal proof is $LEGACY_CHECK, no new $RELEASE_GEN launch. Inspect $LEGACY_ACTIVE_FILE." >&2
        phase_failed "$TASK_PHASE"
      fi
    else
      if [ "$TASK_LABEL" = "bootstrap" ] && [ "$TASK_PHASE" = "dbroles" ] && [ "$LEGACY_OUTCOME" = "started" ]; then
        echo "refused: $TASK_LABEL legacy predecessor is STARTED with live STOPPED task, historical ambiguity requires separately reviewed repair, no automatic binder rerun and no relabel. Inspect $LEGACY_ACTIVE_FILE." >&2
        phase_failed "$TASK_PHASE"
      fi
      PREDECESSOR_TASK="$LEGACY_TASK"
      PREDECESSOR_OUTCOME="complete"
      echo "$TASK_LABEL legacy predecessor reconciled STOPPED exit 0, preserved at $LEGACY_ACTIVE_FILE; new generation $RELEASE_GEN proceeds."
    fi
  fi
  reconcile_prior_generations
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
for _k, _v in doc.items():
    if _k == "version":
        if not isinstance(_v, int) or isinstance(_v, bool):
            print("PROOF\tMALFORMED")
            sys.exit(0)
        continue
    if not isinstance(_v, str):
        print("PROOF\tMALFORMED")
        sys.exit(0)
for _k, _v in doc.items():
    _kl = str(_k).lower()
    if _kl in ("password", "database-url", "database_url",
               "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
               "secret_value", "secretvalue", "private_key", "privatekey",
               "certificate_body", "certificate_chain"):
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
    if isinstance(_v, str):
        _vl = _v.lower()
        if "://" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "password" in _vl:
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
        if [ "$TASK_LABEL" = "sdk-init" ] && [ "$TASK_PHASE" = "init" ]; then
          ACTIVE_PRE_DESC="$(mktemp /tmp/launchcrew-active-pre-XXXXXX)"
          if "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$PRIOR_TASK" --region "$EXPECTED_REGION" --output json >"$ACTIVE_PRE_DESC" 2>"$TMP_ERR"; then
            ACTIVE_PRE_CHECK="$(python3 - "$ACTIVE_PRE_DESC" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("UNREADABLE")
    sys.exit(0)
tasks = doc.get("tasks", [])
failures = doc.get("failures", [])
if failures or not tasks:
    print("NO_TASK")
else:
    print("PRESENT")
PYEOF
)" || ACTIVE_PRE_CHECK="UNREADABLE"
            rm -f "$ACTIVE_PRE_DESC"
            ACTIVE_PRE_CHECK="$(printf '%s' "$ACTIVE_PRE_CHECK" | tr -d '[:space:]')"
            if [ "$ACTIVE_PRE_CHECK" = "NO_TASK" ]; then
              echo "$TASK_LABEL prior mutating complete aged out NO_TASK, requiring recovery attestation with no resend."
              attest_aged_init_recovery "$TASK_PHASE" "$ACTIVE_FILE" "$(basename "$ACTIVE_FILE")"
              echo "$TASK_LABEL already complete via recovery attestation, one-shot preserved with no new run-task; desired-state equivalence, not retroactive proof."
              release_operation_lock
              return 0
            fi
          else
            rm -f "$ACTIVE_PRE_DESC"
          fi
        fi
        if [ "$TASK_LABEL" = "bootstrap" ] && [ "$TASK_PHASE" = "dbroles" ]; then
          ACTIVE_PRE_DESC="$(mktemp /tmp/launchcrew-active-pre-XXXXXX)"
          if "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$PRIOR_TASK" --region "$EXPECTED_REGION" --output json >"$ACTIVE_PRE_DESC" 2>"$TMP_ERR"; then
            ACTIVE_PRE_CHECK="$(python3 - "$ACTIVE_PRE_DESC" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("UNREADABLE")
    sys.exit(0)
tasks = doc.get("tasks", [])
failures = doc.get("failures", [])
if failures or not tasks:
    print("NO_TASK")
else:
    print("PRESENT")
PYEOF
)" || ACTIVE_PRE_CHECK="UNREADABLE"
            rm -f "$ACTIVE_PRE_DESC"
            ACTIVE_PRE_CHECK="$(printf '%s' "$ACTIVE_PRE_CHECK" | tr -d '[:space:]')"
            if [ "$ACTIVE_PRE_CHECK" = "NO_TASK" ]; then
              echo "$TASK_LABEL prior mutating complete aged out NO_TASK, requiring recovery attestation with no binder rerun."
              attest_aged_typed_recovery "$TASK_PHASE" "$ACTIVE_FILE" "$(basename "$ACTIVE_FILE")" "dbroles" "bootstrap" "BootstrapTaskDefinition" "dbroles-recovery-attestation" "RoleStateTaskDefinition" "bootstrap-db-roles" "1" "1"
              echo "$TASK_LABEL already complete via recovery attestation, one-shot preserved with no new binder run-task; desired-state equivalence, never a relabel."
              release_operation_lock
              return 0
            fi
          else
            rm -f "$ACTIVE_PRE_DESC"
          fi
        fi
        if [ "$TASK_LABEL" = "migration" ] && [ "$TASK_PHASE" = "migrate" ]; then
          ACTIVE_PRE_DESC="$(mktemp /tmp/launchcrew-active-pre-XXXXXX)"
          if "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$PRIOR_TASK" --region "$EXPECTED_REGION" --output json >"$ACTIVE_PRE_DESC" 2>"$TMP_ERR"; then
            ACTIVE_PRE_CHECK="$(python3 - "$ACTIVE_PRE_DESC" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("UNREADABLE")
    sys.exit(0)
tasks = doc.get("tasks", [])
failures = doc.get("failures", [])
if failures or not tasks:
    print("NO_TASK")
else:
    print("PRESENT")
PYEOF
)" || ACTIVE_PRE_CHECK="UNREADABLE"
            rm -f "$ACTIVE_PRE_DESC"
            ACTIVE_PRE_CHECK="$(printf '%s' "$ACTIVE_PRE_CHECK" | tr -d '[:space:]')"
            if [ "$ACTIVE_PRE_CHECK" = "NO_TASK" ]; then
              echo "$TASK_LABEL prior mutating complete aged out NO_TASK, requiring recovery attestation with no resend."
              attest_aged_typed_recovery "$TASK_PHASE" "$ACTIVE_FILE" "$(basename "$ACTIVE_FILE")" "migrate" "migration" "MigrationTaskDefinition" "migration-recovery-attestation" "RoleStateTaskDefinition" "bootstrap-db-roles" "0" "1"
              MIGRATION_ACTIVE_OBS="$(python3 - "$LAUNCH_JOURNAL_DIR/recovery/$(basename "$ACTIVE_FILE").recovery.json" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("UNREADABLE")
    sys.exit(0)
print(doc.get("observed_head", "") or "MISSING")
PYEOF
)" || MIGRATION_ACTIVE_OBS="UNREADABLE"
              MIGRATION_ACTIVE_OBS="$(printf '%s' "$MIGRATION_ACTIVE_OBS" | tr -d '[:space:]')"
              if [ "$MIGRATION_ACTIVE_OBS" = "008" ]; then
                echo "$TASK_LABEL already complete via recovery attestation with observed head008, one-shot preserved with no new run-task; desired-state equivalence, not retroactive proof."
                release_operation_lock
                return 0
              fi
              release_operation_lock
              echo "refused: $TASK_LABEL same-generation complete aged out but observed head is $MIGRATION_ACTIVE_OBS, not 008; ambiguous 008 attempt with no automatic resend. Inspect $ACTIVE_FILE." >&2
              phase_failed "$TASK_PHASE"
            fi
          else
            rm -f "$ACTIVE_PRE_DESC"
          fi
        fi
        echo "$TASK_LABEL prior mutating operation already complete, re-proving terminal state with no resend."
        prove_terminal_task
        echo "$TASK_LABEL already complete, one-shot preserved with no new run-task."
        release_operation_lock
        return 0
      else
        [ -n "$PRIOR_TASK" ] && [ "$PRIOR_TASK" != "None" ] || { echo "refused: $TASK_LABEL prior read-only success has no task ARN, cannot re-prove, no fresh recheck. Inspect $ACTIVE_FILE." >&2; phase_failed "$TASK_PHASE"; }
        CLIENT_TOKEN="$PRIOR_TOKEN"
        JOURNAL_FILE="$ACTIVE_FILE"
        TASK_ARN="$PRIOR_TASK"
        ACTIVE_RO_DESC="$(mktemp /tmp/launchcrew-active-ro-XXXXXX)"
        if "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$PRIOR_TASK" --region "$EXPECTED_REGION" --output json >"$ACTIVE_RO_DESC" 2>"$TMP_ERR"; then
          ACTIVE_RO_CHECK="$(python3 - "$ACTIVE_RO_DESC" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("UNREADABLE")
    sys.exit(0)
tasks = doc.get("tasks", [])
failures = doc.get("failures", [])
if failures or not tasks:
    print("NO_TASK")
else:
    print("PRESENT")
PYEOF
)" || ACTIVE_RO_CHECK="UNREADABLE"
          rm -f "$ACTIVE_RO_DESC"
          ACTIVE_RO_CHECK="$(printf '%s' "$ACTIVE_RO_CHECK" | tr -d '[:space:]')"
          if [ "$ACTIVE_RO_CHECK" = "NO_TASK" ]; then
            echo "$TASK_LABEL prior read-only complete aged out NO_TASK, requiring recovery attestation before fresh recheck."
            if [ "$TASK_LABEL" = "sdk-material" ] && [ "$TASK_PHASE" = "material" ]; then
              attest_aged_typed_recovery "$TASK_PHASE" "$ACTIVE_FILE" "$(basename "$ACTIVE_FILE")" "material" "sdk-material" "SdkMaterialTaskDefinition" "material-recovery-attestation" "SdkMaterialTaskDefinition" "sdk-material" "0" "0"
            elif [ "$TASK_LABEL" = "verify" ] && [ "$TASK_PHASE" = "migrate" ]; then
              attest_aged_typed_recovery "$TASK_PHASE" "$ACTIVE_FILE" "$(basename "$ACTIVE_FILE")" "migrate" "verify" "VerifyTaskDefinition" "runtime-recovery-attestation" "VerifyTaskDefinition" "bootstrap-db-roles" "0" "0"
            else
              echo "refused: $TASK_LABEL read-only aged out with no recovery path, no fresh recheck. Inspect $ACTIVE_FILE." >&2
              phase_failed "$TASK_PHASE"
            fi
            echo "$TASK_LABEL aged prior recovered via attestation, proceeding to archive and fresh recheck."
          fi
        else
          rm -f "$ACTIVE_RO_DESC"
        fi
        echo "$TASK_LABEL prior read-only complete, re-proving terminal state before archive with no resend."
        if [ "${ACTIVE_RO_CHECK:-PRESENT}" = "NO_TASK" ]; then
          echo "$TASK_LABEL prior read-only complete aged out but recovered via attestation, archiving original with no live re-proof and proceeding to fresh recheck."
        else
          prove_terminal_task
        fi
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
  if [ "$TASK_LABEL" = "sdk-init" ] && [ "$TASK_PHASE" = "init" ] && [ "${RECOVERED_AGED_PRIOR_INIT:-0}" = "1" ]; then
    echo "$TASK_LABEL aged prior recovered via attestation, desired-state equivalence with no new run-task; short-circuiting init with no new active journal, no Put/Export, and no migration before later gates. Preserved history, no resend."
    release_operation_lock
    return 0
  fi
  if [ "$TASK_LABEL" = "bootstrap" ] && [ "$TASK_PHASE" = "dbroles" ] && [ "${RECOVERED_AGED_PRIOR_DBROLES:-0}" = "1" ]; then
    echo "$TASK_LABEL aged prior recovered via read-only role-state verifier, desired-state equivalence with no new binder run-task; short-circuiting dbroles with no new active journal, never rerunning the binder automatically and never relabel STARTED as completed. Preserved history, no resend."
    release_operation_lock
    return 0
  fi
  if [ "$TASK_LABEL" = "migration" ] && [ "$TASK_PHASE" = "migrate" ] && [ "${RECOVERED_AGED_PRIOR_MIGRATION:-0}" = "1" ]; then
    MIGRATION_OBSERVED="$(python3 - "$LAUNCH_JOURNAL_DIR" "$STACK_NAME" "${RELEASE_GEN:-}" "${SOURCE_SHA:-}" "${TARGET_DB_HEAD:-008}" 2>/dev/null <<'PYEOF'
import json, os, sys
directory, stack, want_gen, want_source, want_head = sys.argv[1:6]
prefix = "launchcrew-%s-migrate-migration-" % stack
rec_dir = os.path.join(directory, "recovery")
try:
    names = sorted(os.listdir(rec_dir))
except Exception:
    print("PROOF\tLIST_FAILED")
    sys.exit(0)
heads = set()
orig_heads = set()
orig_legacy = False
orig_basenames = []
for name in names:
    if not name.startswith(prefix) or not name.endswith(".recovery.json"):
        continue
    path = os.path.join(rec_dir, name)
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except Exception:
        print("PROOF\tUNREADABLE")
        sys.exit(0)
    if not isinstance(doc, dict):
        print("PROOF\tMALFORMED")
        sys.exit(0)
    if doc.get("kind", "") != "migration-recovery-attestation":
        continue
    if doc.get("outcome", "") != "complete":
        print("PROOF\tUNRESOLVED")
        sys.exit(0)
    if doc.get("release_generation", "") != want_gen:
        continue
    if doc.get("source_sha", "") != want_source:
        continue
    if doc.get("target_head", "") != want_head:
        continue
    head = doc.get("observed_head", "")
    if head not in ("007", "008"):
        print("PROOF\tHEAD_UNKNOWN")
        sys.exit(0)
    legacy = doc.get("legacy_unversioned", "")
    if legacy not in ("true", "false"):
        print("PROOF\tLEGACY_MALFORMED")
        sys.exit(0)
    orig = doc.get("original_target_head", "")
    base = doc.get("original_basename", "")
    if not isinstance(base, str) or not base:
        print("PROOF\tORIGINAL_BASENAME_MISSING")
        sys.exit(0)
    if legacy == "true":
        orig_legacy = True
        orig_heads.add("LEGACY")
    else:
        if orig not in ("004", "005", "006", "007", "008"):
            print("PROOF\tORIG_HEAD_UNKNOWN")
            sys.exit(0)
        orig_heads.add(orig)
    orig_basenames.append(base)
    heads.add(head)
if not heads:
    print("PROOF\tNO_ATTESTATION")
    sys.exit(0)
if len(heads) != 1:
    print("PROOF\tHEAD_MISMATCH")
    sys.exit(0)
print("PROOF\tOK")
print("HEAD\t%s" % next(iter(heads)))
if orig_legacy:
    print("ORIG_HEAD\tLEGACY")
else:
    if len(orig_heads) == 1:
        print("ORIG_HEAD\t%s" % next(iter(orig_heads)))
    else:
        print("ORIG_HEAD\t%s" % ",".join(sorted(orig_heads)))
print("ORIG_HAS007\t%s" % ("true" if "007" in orig_heads else "false"))
print("ORIG_HAS008\t%s" % ("true" if "008" in orig_heads else "false"))
print("ORIG_LEGACY\t%s" % ("true" if orig_legacy else "false"))
print("COUNT\t%d" % len(orig_basenames))
for _b in sorted(set(orig_basenames)):
    print("ORIG_BASE\t%s" % _b)
PYEOF
)" || MIGRATION_OBSERVED="PROOF\tUNREADABLE"
    MIGRATION_OBS_PROOF="$(printf '%s\n' "$MIGRATION_OBSERVED" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    MIGRATION_OBS_HEAD="$(printf '%s\n' "$MIGRATION_OBSERVED" | awk -F'\t' '$1=="HEAD"{print $2}' | tr -d '[:space:]')"
    MIGRATION_ORIG_HEAD="$(printf '%s\n' "$MIGRATION_OBSERVED" | awk -F'\t' '$1=="ORIG_HEAD"{print $2}' | tr -d '[:space:]')"
    MIGRATION_ORIG_LEGACY="$(printf '%s\n' "$MIGRATION_OBSERVED" | awk -F'\t' '$1=="ORIG_LEGACY"{print $2}' | tr -d '[:space:]')"
    MIGRATION_ORIG_HAS007="$(printf '%s\n' "$MIGRATION_OBSERVED" | awk -F'\t' '$1=="ORIG_HAS007"{print $2}' | tr -d '[:space:]')"
    MIGRATION_ORIG_HAS008="$(printf '%s\n' "$MIGRATION_OBSERVED" | awk -F'\t' '$1=="ORIG_HAS008"{print $2}' | tr -d '[:space:]')"
    if [ "$MIGRATION_OBS_PROOF" != "OK" ]; then
      release_operation_lock
      echo "refused: migration recovery observed head proof is $MIGRATION_OBS_PROOF, no new migration and no skip without exact head. Inspect $LAUNCH_JOURNAL_DIR/recovery." >&2
      phase_failed "$TASK_PHASE"
    fi
    if [ "$MIGRATION_OBS_HEAD" = "008" ]; then
      echo "$TASK_LABEL aged prior recovered with observed head008 plus verified equivalence, skipping migration with no new run-task under typed attestation; fresh runtime verification still required. Preserved history, no resend."
      release_operation_lock
      return 0
    fi
    if [ "$MIGRATION_OBS_HEAD" = "007" ]; then
      if [ "$MIGRATION_ORIG_LEGACY" = "true" ]; then
        release_operation_lock
        echo "refused: migration recovery observed007 with legacy unversioned original target is ambiguous, historical 008 attempt cannot be excluded, separately reviewed repair required with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR/recovery." >&2
        phase_failed "$TASK_PHASE"
      fi
      if [ "$MIGRATION_ORIG_HAS008" = "true" ]; then
        release_operation_lock
        echo "refused: migration recovery observed007 but original history includes target008 (${MIGRATION_ORIG_HEAD:-unknown}) with state regression, ambiguous prior 008 requires separately reviewed repair with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR/recovery." >&2
        phase_failed "$TASK_PHASE"
      fi
      MIGRATION_HIST_ENUM="$(python3 - "$LAUNCH_JOURNAL_DIR" "$STACK_NAME" "$(basename "$ACTIVE_FILE")" 2>/dev/null <<'PYEOF'
import os, sys
directory, stack, active_base = sys.argv[1:4]
prefix = "launchcrew-%s-migrate-migration-" % stack
try:
    names = sorted(os.listdir(directory))
except Exception:
    print("PROOF\tLIST_FAILED")
    sys.exit(0)
found = []
for name in names:
    if not name.startswith(prefix) or not name.endswith(".json"):
        continue
    if name == active_base:
        continue
    found.append(name)
    if len(found) > 32:
        print("PROOF\tTOO_MANY")
        sys.exit(0)
print("PROOF\tOK")
for _b in found:
    print("BASE\t%s" % _b)
PYEOF
)" || MIGRATION_HIST_ENUM="PROOF\tLIST_FAILED"
      MIGRATION_HIST_PROOF="$(printf '%s\n' "$MIGRATION_HIST_ENUM" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
      if [ "$MIGRATION_HIST_PROOF" != "OK" ]; then
        release_operation_lock
        echo "refused: migration recovery observed007 but historical target inventory proof is $MIGRATION_HIST_PROOF, separately reviewed repair required with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR." >&2
        phase_failed "$TASK_PHASE"
      fi
      MIGRATION_HIST_LIST="$(printf '%s\n' "$MIGRATION_HIST_ENUM" | awk -F'\t' '$1=="BASE"{print $2}')"
      MIGRATION_HIST_OK=1
      MIGRATION_HIST_HAS008=0
      MIGRATION_HIST_HAS_LEGACY=0
      while IFS= read -r MIGRATION_HIST_BASE || [ -n "$MIGRATION_HIST_BASE" ]; do
        [ -n "$MIGRATION_HIST_BASE" ] || continue
        case "$MIGRATION_HIST_BASE" in
          *"/"*|"."|"..") MIGRATION_HIST_OK=0; break ;;
        esac
        MIGRATION_HIST_PATH="$LAUNCH_JOURNAL_DIR/$MIGRATION_HIST_BASE"
        if [ -L "$MIGRATION_HIST_PATH" ] || [ ! -f "$MIGRATION_HIST_PATH" ]; then
          MIGRATION_HIST_OK=0; break
        fi
        MIGRATION_HIST_VALIDATED="$(validate_typed_journal_for_recovery "$MIGRATION_HIST_PATH" "$MIGRATION_HIST_BASE" "migrate" "migration" "MigrationTaskDefinition" "1")" || MIGRATION_HIST_VALIDATED="PROOF\tUNREADABLE"
        MIGRATION_HIST_VPROOF="$(printf '%s\n' "$MIGRATION_HIST_VALIDATED" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
        MIGRATION_HIST_VHEAD="$(printf '%s\n' "$MIGRATION_HIST_VALIDATED" | awk -F'\t' '$1=="HEAD"{print $2}' | tr -d '[:space:]')"
        MIGRATION_HIST_VLEGACY="$(printf '%s\n' "$MIGRATION_HIST_VALIDATED" | awk -F'\t' '$1=="LEGACY"{print $2}' | tr -d '[:space:]')"
        MIGRATION_HIST_VOUT="$(printf '%s\n' "$MIGRATION_HIST_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
        if [ "$MIGRATION_HIST_VPROOF" != "OK" ]; then
          MIGRATION_HIST_OK=0; break
        fi
        if [ "$MIGRATION_HIST_VLEGACY" = "true" ]; then
          MIGRATION_HIST_HAS_LEGACY=1; continue
        fi
        case "$MIGRATION_HIST_VHEAD" in
          008) MIGRATION_HIST_HAS008=1 ;;
          004|005|006|007)
            if [ "$MIGRATION_HIST_VOUT" != "complete" ]; then
              MIGRATION_HIST_OK=0; break
            fi ;;
          *) MIGRATION_HIST_OK=0; break ;;
        esac
      done <<EOF_HIST_LIST
$MIGRATION_HIST_LIST
EOF_HIST_LIST
      if [ "$MIGRATION_HIST_OK" != "1" ]; then
        release_operation_lock
        echo "refused: migration recovery observed007 but historical target inventory is malformed or ambiguous, separately reviewed repair required with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR and $LAUNCH_JOURNAL_DIR/recovery." >&2
        phase_failed "$TASK_PHASE"
      fi
      if [ "$MIGRATION_HIST_HAS_LEGACY" = "1" ]; then
        release_operation_lock
        echo "refused: migration recovery observed007 with legacy unversioned historical target is ambiguous, historical 008 attempt cannot be excluded, separately reviewed repair required with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR and $LAUNCH_JOURNAL_DIR/recovery." >&2
        phase_failed "$TASK_PHASE"
      fi
      if [ "$MIGRATION_HIST_HAS008" = "1" ]; then
        release_operation_lock
        echo "refused: migration recovery observed007 but validated history includes target008 with state regression, ambiguous prior 008 requires separately reviewed repair with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR and $LAUNCH_JOURNAL_DIR/recovery." >&2
        phase_failed "$TASK_PHASE"
      fi
      if [ "$MIGRATION_ORIG_HAS007" != "true" ]; then
        release_operation_lock
        echo "refused: migration recovery observed007 but original target is ${MIGRATION_ORIG_HEAD:-unknown}, not validated 007; ambiguous prior 008 with state regression requires separately reviewed repair with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR/recovery." >&2
        phase_failed "$TASK_PHASE"
      fi
      MIGRATION_ORIG_LIST="$(printf '%s\n' "$MIGRATION_OBSERVED" | awk -F'\t' '$1=="ORIG_BASE"{print $2}')"
      MIGRATION_ORIG_OK=1
      MIGRATION_HAS_VALIDATED_007=0
      while IFS= read -r MIGRATION_ORIG_BASE || [ -n "$MIGRATION_ORIG_BASE" ]; do
        [ -n "$MIGRATION_ORIG_BASE" ] || continue
        case "$MIGRATION_ORIG_BASE" in
          *"/"*|"."|"..") MIGRATION_ORIG_OK=0; break ;;
        esac
        MIGRATION_ORIG_PATH="$LAUNCH_JOURNAL_DIR/$MIGRATION_ORIG_BASE"
        if [ -L "$MIGRATION_ORIG_PATH" ] || [ ! -f "$MIGRATION_ORIG_PATH" ]; then
          MIGRATION_ORIG_OK=0; break
        fi
        MIGRATION_ORIG_VALIDATED="$(validate_typed_journal_for_recovery "$MIGRATION_ORIG_PATH" "$MIGRATION_ORIG_BASE" "migrate" "migration" "MigrationTaskDefinition" "0")" || MIGRATION_ORIG_VALIDATED="PROOF\tUNREADABLE"
        MIGRATION_ORIG_VPROOF="$(printf '%s\n' "$MIGRATION_ORIG_VALIDATED" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
        MIGRATION_ORIG_VHEAD="$(printf '%s\n' "$MIGRATION_ORIG_VALIDATED" | awk -F'\t' '$1=="HEAD"{print $2}' | tr -d '[:space:]')"
        MIGRATION_ORIG_VLEGACY="$(printf '%s\n' "$MIGRATION_ORIG_VALIDATED" | awk -F'\t' '$1=="LEGACY"{print $2}' | tr -d '[:space:]')"
        MIGRATION_ORIG_VOUT="$(printf '%s\n' "$MIGRATION_ORIG_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
        if [ "$MIGRATION_ORIG_VPROOF" != "OK" ] || [ "$MIGRATION_ORIG_VLEGACY" = "true" ] || [ "$MIGRATION_ORIG_VOUT" != "complete" ]; then
          MIGRATION_ORIG_OK=0; break
        fi
        case "$MIGRATION_ORIG_VHEAD" in
          007) MIGRATION_HAS_VALIDATED_007=1 ;;
          004|005|006) ;;
          *) MIGRATION_ORIG_OK=0; break ;;
        esac
      done <<EOF_ORIG_LIST
$MIGRATION_ORIG_LIST
EOF_ORIG_LIST
      if [ "$MIGRATION_ORIG_OK" != "1" ]; then
        release_operation_lock
        echo "refused: migration recovery observed007 but validated original history proof failed, ambiguous prior requires separately reviewed repair with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR and $LAUNCH_JOURNAL_DIR/recovery." >&2
        phase_failed "$TASK_PHASE"
      fi
      if [ "$MIGRATION_HAS_VALIDATED_007" != "1" ]; then
        release_operation_lock
        echo "refused: migration recovery observed007 but no validated original target007 in preserved history (${MIGRATION_ORIG_HEAD:-unknown}), ambiguous prior requires separately reviewed repair with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR and $LAUNCH_JOURNAL_DIR/recovery." >&2
        phase_failed "$TASK_PHASE"
      fi
      echo "$TASK_LABEL aged prior recovered with observed head007 plus validated original target007, admitting at most one deliberate 007->008 migration after old-token and current-state checks; never automatically resending an ambiguous 008 attempt."
    else
      release_operation_lock
      echo "refused: migration recovery observed head is $MIGRATION_OBS_HEAD, not 007 or 008, no migration and no skip. Inspect $LAUNCH_JOURNAL_DIR/recovery." >&2
      phase_failed "$TASK_PHASE"
    fi
  fi
  if [ "$TASK_LABEL" = "migration" ] && [ "$TASK_PHASE" = "migrate" ] && [ "${RECOVERED_AGED_PRIOR_MIGRATION:-0}" != "1" ]; then
    MIGRATION_GLOBAL_ENUM="$(python3 - "$LAUNCH_JOURNAL_DIR" "$STACK_NAME" "$(basename "$ACTIVE_FILE")" 2>/dev/null <<'PYEOF'
import os, sys
directory, stack, active_base = sys.argv[1:4]
prefix = "launchcrew-%s-migrate-migration-" % stack
try:
    names = sorted(os.listdir(directory))
except Exception:
    print("PROOF\tLIST_FAILED")
    sys.exit(0)
found = []
for name in names:
    if not name.startswith(prefix) or not name.endswith(".json"):
        continue
    if name == active_base:
        continue
    found.append(name)
    if len(found) > 32:
        print("PROOF\tTOO_MANY")
        sys.exit(0)
print("PROOF\tOK")
for _b in found:
    print("BASE\t%s" % _b)
PYEOF
)" || MIGRATION_GLOBAL_ENUM="PROOF\tLIST_FAILED"
    MIGRATION_GLOBAL_PROOF="$(printf '%s\n' "$MIGRATION_GLOBAL_ENUM" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$MIGRATION_GLOBAL_PROOF" != "OK" ]; then
      release_operation_lock
      echo "refused: migration history target inventory proof is $MIGRATION_GLOBAL_PROOF, separately reviewed repair required with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR." >&2
      phase_failed "$TASK_PHASE"
    fi
    MIGRATION_GLOBAL_LIST="$(printf '%s\n' "$MIGRATION_GLOBAL_ENUM" | awk -F'\t' '$1=="BASE"{print $2}')"
    MIGRATION_GLOBAL_TRIMMED="$(printf '%s' "$MIGRATION_GLOBAL_LIST" | tr -d '[:space:]')"
    if [ -z "$MIGRATION_GLOBAL_TRIMMED" ]; then
      echo "$TASK_LABEL no prior migration history, admitting first fresh008 migration."
    else
      MIGRATION_GLOBAL_OK=1
      MIGRATION_GLOBAL_HAS008=0
      MIGRATION_GLOBAL_HAS_LEGACY=0
      MIGRATION_GLOBAL_HAS007=0
      MIGRATION_GLOBAL_REASON=""
      while IFS= read -r MIGRATION_GLOBAL_BASE || [ -n "$MIGRATION_GLOBAL_BASE" ]; do
        [ -n "$MIGRATION_GLOBAL_BASE" ] || continue
        case "$MIGRATION_GLOBAL_BASE" in
          *"/"*|"."|"..") MIGRATION_GLOBAL_OK=0; MIGRATION_GLOBAL_REASON="PATH"; break ;;
        esac
        MIGRATION_GLOBAL_PATH="$LAUNCH_JOURNAL_DIR/$MIGRATION_GLOBAL_BASE"
        if [ -L "$MIGRATION_GLOBAL_PATH" ] || [ ! -f "$MIGRATION_GLOBAL_PATH" ]; then
          MIGRATION_GLOBAL_OK=0; MIGRATION_GLOBAL_REASON="MISSING"; break
        fi
        MIGRATION_GLOBAL_VALIDATED="$(validate_typed_journal_for_recovery "$MIGRATION_GLOBAL_PATH" "$MIGRATION_GLOBAL_BASE" "migrate" "migration" "MigrationTaskDefinition" "1")" || MIGRATION_GLOBAL_VALIDATED="PROOF\tUNREADABLE"
        MIGRATION_GLOBAL_VPROOF="$(printf '%s\n' "$MIGRATION_GLOBAL_VALIDATED" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
        MIGRATION_GLOBAL_VHEAD="$(printf '%s\n' "$MIGRATION_GLOBAL_VALIDATED" | awk -F'\t' '$1=="HEAD"{print $2}' | tr -d '[:space:]')"
        MIGRATION_GLOBAL_VLEGACY="$(printf '%s\n' "$MIGRATION_GLOBAL_VALIDATED" | awk -F'\t' '$1=="LEGACY"{print $2}' | tr -d '[:space:]')"
        MIGRATION_GLOBAL_VOUT="$(printf '%s\n' "$MIGRATION_GLOBAL_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
        if [ "$MIGRATION_GLOBAL_VPROOF" != "OK" ]; then
          MIGRATION_GLOBAL_OK=0; MIGRATION_GLOBAL_REASON="$MIGRATION_GLOBAL_VPROOF"; break
        fi
        if [ "$MIGRATION_GLOBAL_VLEGACY" = "true" ]; then
          MIGRATION_GLOBAL_HAS_LEGACY=1; continue
        fi
        case "$MIGRATION_GLOBAL_VHEAD" in
          008) MIGRATION_GLOBAL_HAS008=1 ;;
          007)
            if [ "$MIGRATION_GLOBAL_VOUT" != "complete" ]; then
              MIGRATION_GLOBAL_OK=0; MIGRATION_GLOBAL_REASON="UNRESOLVED"; break
            fi
            MIGRATION_GLOBAL_HAS007=1 ;;
          004|005|006)
            if [ "$MIGRATION_GLOBAL_VOUT" != "complete" ]; then
              MIGRATION_GLOBAL_OK=0; MIGRATION_GLOBAL_REASON="UNRESOLVED"; break
            fi ;;
          *) MIGRATION_GLOBAL_OK=0; MIGRATION_GLOBAL_REASON="HEAD_UNKNOWN"; break ;;
        esac
      done <<EOF_GLOBAL_LIST
$MIGRATION_GLOBAL_LIST
EOF_GLOBAL_LIST
      if [ "$MIGRATION_GLOBAL_OK" != "1" ]; then
        release_operation_lock
        echo "refused: migration history target inventory is malformed or ambiguous (${MIGRATION_GLOBAL_REASON:-unknown}), separately reviewed repair required with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR." >&2
        phase_failed "$TASK_PHASE"
      fi
      if [ "$MIGRATION_GLOBAL_HAS_LEGACY" = "1" ]; then
        release_operation_lock
        echo "refused: migration history includes legacy unversioned target, historical 008 attempt cannot be excluded, separately reviewed repair required with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR." >&2
        phase_failed "$TASK_PHASE"
      fi
      if [ "$MIGRATION_GLOBAL_HAS008" = "1" ]; then
        release_operation_lock
        echo "refused: migration history includes preserved target008 attempt with possible state regression to007, ambiguous prior 008 requires separately reviewed repair with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR." >&2
        phase_failed "$TASK_PHASE"
      fi
      if [ "$MIGRATION_GLOBAL_HAS007" != "1" ]; then
        release_operation_lock
        echo "refused: migration history has no validated original target007, 006-only cannot authorize008, separately reviewed repair required with zero new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR." >&2
        phase_failed "$TASK_PHASE"
      fi
      migration_role_state_preflight
      if [ "$PREFLIGHT_OBSERVED_HEAD" = "007" ]; then
        echo "$TASK_LABEL live history has validated target007 with no target008 plus fresh preflight observed head007 ready, admitting at most one deliberate 007->008 migration after old-token and current-state checks; never automatically resending an ambiguous 008 attempt."
      elif [ "$PREFLIGHT_OBSERVED_HEAD" = "008" ]; then
        release_operation_lock
        echo "refused: migration live history has validated target007 with no target008 but fresh preflight observed head008 complete, DB already migrated with no validated 008 migration record; separately reviewed repair required with zero new migration RunTask and no fabricated receipt. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR and $PREFLIGHT_FILE." >&2
        phase_failed "$TASK_PHASE"
      else
        release_operation_lock
        echo "refused: migration preflight observed head is ${PREFLIGHT_OBSERVED_HEAD:-unknown}, not 007 or 008, no new migration RunTask. Preserved history, no resend. Inspect $LAUNCH_JOURNAL_DIR and ${PREFLIGHT_FILE:-unknown}." >&2
        phase_failed "$TASK_PHASE"
      fi
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
  require_init_desired_state material
  require_typed_desired_state material material sdk-material SdkMaterialTaskDefinition material-recovery-attestation SdkMaterialTaskDefinition sdk-material 0 0
  check_sdk_taskdef SdkMaterialTaskDefinition SdkMaterialExecutionRole SdkMaterialTaskRole sdk-material --verify-material
  run_one_off_task SdkMaterialTaskDefinition sdk-material material
  mark_done material
  echo "Phase material complete: runtime, migration, and TLS materials verified read-only"
fi

if wants_phase dbroles; then
  echo "Phase dbroles: isolated bootstrap task binds role passwords in task memory only"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no stack owns the bootstrap task; run --phase infra first" >&2; phase_failed dbroles; }
  require_init_desired_state dbroles
  require_typed_desired_state dbroles dbroles bootstrap BootstrapTaskDefinition dbroles-recovery-attestation RoleStateTaskDefinition bootstrap-db-roles 1 1
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
  require_init_desired_state migrate
  require_typed_desired_state migrate migrate migration MigrationTaskDefinition migration-recovery-attestation RoleStateTaskDefinition bootstrap-db-roles 0 1
  require_typed_desired_state migrate migrate verify VerifyTaskDefinition runtime-recovery-attestation VerifyTaskDefinition bootstrap-db-roles 0 0
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

# Fail-closed ALB target group drain proof for quiesce. Resolves the exact
# owned target group ARN via describe-stack-resource, requires the owned
# account and region shape, then requires every reported target to be fully
# drained: an empty target list or every TargetHealth State unused. Any
# healthy, unhealthy, initial, draining, deregistration, unavailable, or
# malformed entry refuses, because in-flight targets must finish before a
# schema migration. Unknown or unreadable health fails closed.
verify_target_group_drained() {
  TG_LOGICAL="$1"
  TG_SHORT="$2"
  TG_ARN=""
  if ! TG_ARN="$(stack_resource "$TG_LOGICAL" 2>"$TMP_ERR")"; then
    echo "target group $TG_SHORT owned ARN unreadable, not claimed drained." >&2
    phase_failed quiesce
  fi
  TG_ARN="$(printf '%s' "$TG_ARN" | tr -d '[:space:]')"
  case "$TG_ARN" in
    "arn:aws:elasticloadbalancing:$EXPECTED_REGION:$EXPECTED_ACCOUNT:targetgroup/"*) ;;
    *) echo "refused: target group $TG_SHORT ARN is foreign or malformed, not claimed drained." >&2; phase_failed quiesce ;;
  esac
  TG_JSON="$(mktemp /tmp/launchcrew-tg-XXXXXX)"
  if ! "$AWS_BIN" elbv2 describe-target-health --target-group-arn "$TG_ARN" --region "$EXPECTED_REGION" --output json >"$TG_JSON" 2>"$TMP_ERR"; then
    rm -f "$TG_JSON"
    echo "target group $TG_SHORT health unreadable, not claimed drained." >&2
    phase_failed quiesce
  fi
  TG_PROOF="$(python3 - "$TG_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(doc, dict):
    print("MALFORMED")
    sys.exit(0)
descs = doc.get("TargetHealthDescriptions", None)
if not isinstance(descs, list):
    print("MALFORMED")
    sys.exit(0)
if len(descs) > 100:
    print("TOO_MANY")
    sys.exit(0)
for entry in descs:
    if not isinstance(entry, dict):
        print("MALFORMED")
        sys.exit(0)
    health = entry.get("TargetHealth", None)
    if not isinstance(health, dict):
        print("MALFORMED")
        sys.exit(0)
    state = health.get("State", "") or ""
    if state != "unused":
        print("IN_FLIGHT_%s" % (state or "EMPTY"))
        sys.exit(0)
print("OK")
PYEOF
)" || { rm -f "$TG_JSON"; echo "target group $TG_SHORT proof unreadable, not claimed drained." >&2; phase_failed quiesce; }
  rm -f "$TG_JSON"
  TG_PROOF="$(printf '%s' "$TG_PROOF" | tr -d '[:space:]')"
  case "$TG_PROOF" in
    OK)
      echo "Verified target group $TG_ARN drained with no in-flight targets" ;;
    *) echo "refused: target group $TG_SHORT health proof is $TG_PROOF, expected drained with no in-flight targets" >&2; phase_failed quiesce ;;
  esac
}

# Read-only re-proof of a prior one-off task for enable, with no new
# run-task call. Args: taskdef logical, label, origin phase (material or
# migrate). Enable never launches one-off tasks, not even read-only
# verifiers; it re-proves the prior complete journals from the current
# release generation plus live describe. The prior file must be complete
# with the exact owned identity, release generation, head, StackId,
# taskdef, and config, and its task must be STOPPED with every expected
# essential container exit 0. Missing, unresolved, or mismatched priors
# fail closed with instructions to run the origin phase first. No journal
# write happens here, so concurrent origin runs cause a fail-closed rerun,
# never a false success. Legacy old-head records never satisfy a new
# generation; they are preserved and reported.
reprove_prior_one_off_readonly() {
  REPROVE_LOGICAL="$1"
  REPROVE_LABEL="$2"
  REPROVE_ORIGIN="$3"
  if [ -z "$LAUNCH_JOURNAL_DIR" ]; then
    case "$0" in
      */*) REPROVE_SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd 2>/dev/null || echo "")" ;;
      *) REPROVE_SCRIPT_DIR="" ;;
    esac
    if [ -n "$REPROVE_SCRIPT_DIR" ] && [ -d "$REPROVE_SCRIPT_DIR" ]; then
      LAUNCH_JOURNAL_DIR="$REPROVE_SCRIPT_DIR/../../.local/launch-journals"
    else
      echo "refused: enable re-proof needs prior $REPROVE_LABEL $REPROVE_ORIGIN record but journal directory is missing. Run --phase $REPROVE_ORIGIN first with shared journals. No new launch." >&2
      phase_failed enable
    fi
  fi
  if [ -L "$LAUNCH_JOURNAL_DIR" ]; then echo "enable re-proof journal directory is a symlink, no claim made." >&2; phase_failed enable; fi
  case "$LAUNCH_JOURNAL_DIR" in
    /|/tmp|/tmp/|/var/tmp|/var/tmp/|/var|/var/|/etc|/etc/|/usr|/usr/) echo "enable re-proof journal directory is a shared root, no claim made." >&2; phase_failed enable ;;
  esac
  if [ ! -d "$LAUNCH_JOURNAL_DIR" ]; then
    echo "refused: enable re-proof needs prior $REPROVE_LABEL $REPROVE_ORIGIN complete record but journal directory is absent. Run --phase $REPROVE_ORIGIN first. No new launch." >&2
    phase_failed enable
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
  then echo "enable re-proof journal directory is not private mode 700 owned, no claim made." >&2; phase_failed enable; fi
  if ! REPROVE_TASKDEF_ARN="$(stack_resource "$REPROVE_LOGICAL" 2>"$TMP_ERR")"; then
    echo "enable re-proof $REPROVE_LABEL task definition lookup failed, not claimed." >&2; phase_failed enable
  fi
  REPROVE_TASKDEF_ARN="$(printf '%s' "$REPROVE_TASKDEF_ARN" | tr -d '[:space:]')"
  [ -n "$REPROVE_TASKDEF_ARN" ] && [ "$REPROVE_TASKDEF_ARN" != "None" ] || { echo "enable re-proof $REPROVE_LABEL task definition missing, not claimed." >&2; phase_failed enable; }
  if ! REPROVE_CONFIG_DIGEST="$(python3 - "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$REPROVE_ORIGIN" "$REPROVE_LABEL" "$REPROVE_LOGICAL" "$REPROVE_TASKDEF_ARN" 2>/dev/null <<'PYEOF'
import hashlib, sys
raw = "|".join(sys.argv[1:9])
print(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32])
PYEOF
)"; then echo "enable re-proof $REPROVE_LABEL config digest failed, not claimed." >&2; phase_failed enable; fi
  REPROVE_CONFIG_DIGEST="$(printf '%s' "$REPROVE_CONFIG_DIGEST" | tr -d '[:space:]')"
  [ -n "$REPROVE_CONFIG_DIGEST" ] || { echo "enable re-proof $REPROVE_LABEL config digest empty, not claimed." >&2; phase_failed enable; }
  REPROVE_ACTIVE_FILE="$LAUNCH_JOURNAL_DIR/launchcrew-$STACK_NAME-$REPROVE_ORIGIN-$REPROVE_LABEL-$RELEASE_GEN-active.json"
  REPROVE_LEGACY_FILE="$LAUNCH_JOURNAL_DIR/launchcrew-$STACK_NAME-$REPROVE_ORIGIN-$REPROVE_LABEL-active.json"
  if [ -L "$REPROVE_ACTIVE_FILE" ]; then echo "enable re-proof $REPROVE_LABEL record is a symlink, no claim made. Inspect $REPROVE_ACTIVE_FILE." >&2; phase_failed enable; fi
  case "$REPROVE_ORIGIN/$REPROVE_LABEL" in
    material/sdk-material) REPROVE_KIND="material-recovery-attestation"; REPROVE_VERIFIER_LOGICAL="SdkMaterialTaskDefinition"; REPROVE_NEED_HEAD=""; REPROVE_ALLOW_STARTED="0"; REPROVE_TYPED_LOGICAL="SdkMaterialTaskDefinition" ;;
    dbroles/bootstrap) REPROVE_KIND="dbroles-recovery-attestation"; REPROVE_VERIFIER_LOGICAL="RoleStateTaskDefinition"; REPROVE_NEED_HEAD="007,008"; REPROVE_ALLOW_STARTED="1"; REPROVE_TYPED_LOGICAL="BootstrapTaskDefinition" ;;
    migrate/migration) REPROVE_KIND="migration-recovery-attestation"; REPROVE_VERIFIER_LOGICAL="RoleStateTaskDefinition"; REPROVE_NEED_HEAD="008"; REPROVE_ALLOW_STARTED="0"; REPROVE_TYPED_LOGICAL="MigrationTaskDefinition" ;;
    migrate/verify) REPROVE_KIND="runtime-recovery-attestation"; REPROVE_VERIFIER_LOGICAL="VerifyTaskDefinition"; REPROVE_NEED_HEAD="008"; REPROVE_ALLOW_STARTED="0"; REPROVE_TYPED_LOGICAL="VerifyTaskDefinition" ;;
    *) REPROVE_KIND=""; REPROVE_VERIFIER_LOGICAL=""; REPROVE_NEED_HEAD=""; REPROVE_ALLOW_STARTED="0"; REPROVE_TYPED_LOGICAL="" ;;
  esac
  if [ ! -f "$REPROVE_ACTIVE_FILE" ]; then
    if [ -z "$REPROVE_KIND" ]; then
      echo "refused: enable re-proof needs prior $REPROVE_LABEL $REPROVE_ORIGIN complete record $REPROVE_ACTIVE_FILE but none exists. Run --phase $REPROVE_ORIGIN first. No new launch." >&2
      phase_failed enable
    fi
    REPROVE_ATTEST_FOUND="$(python3 - "$LAUNCH_JOURNAL_DIR" "$STACK_NAME" "$REPROVE_ORIGIN" "$REPROVE_LABEL" "$REPROVE_KIND" "${RELEASE_GEN:-}" "${SOURCE_SHA:-}" "${TARGET_DB_HEAD:-008}" "$REPROVE_NEED_HEAD" "${STACK_ID:-}" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$CLUSTER_NAME" 2>/dev/null <<'PYEOF'
import hashlib, json, os, sys
(directory, stack, phase, label, want_kind, want_gen, want_source, want_head, need_head,
 want_stack_id, want_account, want_region, want_cluster) = sys.argv[1:14]
prefix = "launchcrew-%s-%s-%s-" % (stack, phase, label)
rec_dir = os.path.join(directory, "recovery")
try:
    names = sorted(os.listdir(rec_dir))
except Exception:
    print("PROOF\tLIST_FAILED")
    sys.exit(0)
need = set(x for x in (need_head or "").split(",") if x)
found = []
for name in names:
    if not name.startswith(prefix) or not name.endswith(".recovery.json"):
        continue
    path = os.path.join(rec_dir, name)
    try:
        if os.path.islink(path):
            print("PROOF\tSYMLINK")
            sys.exit(0)
        finfo = os.stat(path)
        if (finfo.st_mode & 0o777) != 0o600:
            continue
        if finfo.st_uid != os.getuid():
            continue
        if finfo.st_size <= 0 or finfo.st_size > 10240:
            continue
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except Exception:
        continue
    if not isinstance(doc, dict):
        continue
    if doc.get("kind", "") != want_kind:
        continue
    if doc.get("outcome", "") != "complete":
        continue
    if doc.get("release_generation", "") != want_gen:
        continue
    if doc.get("source_sha", "") != want_source:
        continue
    if doc.get("target_head", "") != want_head:
        continue
    if doc.get("verifier_proof", "") != "OK":
        continue
    if doc.get("verifier_last_status", "") != "STOPPED":
        continue
    if doc.get("absence_proof", "") != "OK":
        continue
    if not want_stack_id or doc.get("stack_id", "") != want_stack_id:
        continue
    _vtask = doc.get("verifier_task_arn", "") or ""
    _vtdef = doc.get("verifier_taskdef_arn", "") or ""
    _vtok = doc.get("verifier_token", "") or ""
    if not _vtask.startswith("arn:aws:ecs:%s:%s:task/%s/" % (want_region, want_account, want_cluster)):
        continue
    if not _vtdef.startswith("arn:aws:ecs:%s:%s:task" "-definition/" % (want_region, want_account)):
        continue
    if not isinstance(_vtok, str) or len(_vtok) != 33 or not _vtok.startswith("lc-"):
        continue
    obs = doc.get("observed_head", "") or ""
    if need and obs not in need:
        continue
    if not need and want_kind == "material-recovery-attestation" and obs != "":
        continue
    cont = doc.get("verifier_containers", "") or ""
    if want_kind == "material-recovery-attestation":
        if cont != "sdk-material:STOPPED:0" or obs != "":
            continue
    elif want_kind in ("dbroles-recovery-attestation", "migration-recovery-attestation"):
        if cont == "bootstrap-db-roles:STOPPED:0" and obs != "008":
            continue
        if cont == "bootstrap-db-roles:STOPPED:10" and obs != "007":
            continue
        if cont not in ("bootstrap-db-roles:STOPPED:0", "bootstrap-db-roles:STOPPED:10"):
            continue
    elif want_kind == "runtime-recovery-attestation":
        if cont != "bootstrap-db-roles:STOPPED:0" or obs != "008":
            continue
    else:
        if ":STOPPED:" not in cont:
            continue
    _base = doc.get("original_basename", "") or ""
    _sha = doc.get("original_sha256", "") or ""
    _leg = doc.get("legacy_unversioned", "") or ""
    _oout = doc.get("original_outcome", "") or ""
    if not _base or "/" in _base or not _base.startswith(prefix) or not _base.endswith(".json"):
        continue
    if len(_sha) != 64 or any(c not in "0123456789abcdef" for c in _sha):
        continue
    if _leg not in ("true", "false"):
        continue
    if want_kind == "dbroles-recovery-attestation":
        if _oout not in ("complete", "started"):
            continue
    else:
        if _oout != "complete":
            continue
    try:
        parts = [
            doc.get("kind", ""), doc.get("verifier_task_arn", ""), doc.get("verifier_token", ""),
            doc.get("verifier_taskdef_arn", ""), doc.get("verifier_containers", ""),
            doc.get("verifier_last_status", ""), doc.get("original_sha256", ""),
            doc.get("original_outcome", ""), doc.get("stack_id", ""), doc.get("runtime_arn", ""),
            doc.get("runtime_name", ""), doc.get("runtime_version_pre", ""),
            doc.get("runtime_version_post", ""), doc.get("migration_arn", ""),
            doc.get("migration_name", ""), doc.get("migration_version_pre", ""),
            doc.get("migration_version_post", ""), doc.get("tls_arn", ""),
            doc.get("tls_name", ""), doc.get("tls_version_pre", ""),
            doc.get("tls_version_post", ""), doc.get("cert_arn", ""),
            doc.get("cert_domain", ""), doc.get("cert_serial_pre", ""),
            doc.get("cert_serial_post", ""), doc.get("release_generation", ""),
            doc.get("source_sha", ""), doc.get("target_head", ""),
            doc.get("observed_head", ""), doc.get("original_basename", ""), doc.get("legacy_unversioned", ""),
        ]
        exp = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
        if doc.get("verifier_digest", "") != exp:
            continue
    except Exception:
        continue
    found.append(name)
if not found:
    print("PROOF\tNO_ATTESTATION")
    sys.exit(0)
if len(found) != 1:
    print("PROOF\tDUPLICATE")
    print("COUNT\t%d" % len(found))
    sys.exit(0)
print("PROOF\tOK")
print("FILE\t%s" % found[0])
PYEOF
)" || REPROVE_ATTEST_FOUND="PROOF\tUNREADABLE"
    REPROVE_ATTEST_PROOF="$(printf '%s\n' "$REPROVE_ATTEST_FOUND" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$REPROVE_ATTEST_PROOF" != "OK" ]; then
      if [ "$REPROVE_ATTEST_PROOF" = "DUPLICATE" ]; then
        echo "refused: enable re-proof found duplicate matching $REPROVE_KIND attestations for $REPROVE_LABEL $REPROVE_ORIGIN, ambiguous recovery requires separately reviewed repair with no stack update. Inspect $LAUNCH_JOURNAL_DIR/recovery. No new launch." >&2
        phase_failed enable
      fi
      if [ -f "$REPROVE_LEGACY_FILE" ]; then
        echo "refused: enable re-proof needs new $RELEASE_GEN prior $REPROVE_LABEL $REPROVE_ORIGIN complete record or single current-release $REPROVE_KIND with observed head ${REPROVE_NEED_HEAD:-any}, but found $REPROVE_ATTEST_PROOF and only a legacy old-head record exists. Run --phase $REPROVE_ORIGIN for $RELEASE_GEN first. Legacy preserved at $REPROVE_LEGACY_FILE, no new launch." >&2
      else
        echo "refused: enable re-proof needs prior $REPROVE_LABEL $REPROVE_ORIGIN complete record $REPROVE_ACTIVE_FILE or single current-release $REPROVE_KIND with observed head ${REPROVE_NEED_HEAD:-any}, but found $REPROVE_ATTEST_PROOF. Run --phase $REPROVE_ORIGIN first. No new launch." >&2
      fi
      phase_failed enable
    fi
    REPROVE_ATTEST_FILE="$(printf '%s\n' "$REPROVE_ATTEST_FOUND" | awk -F'\t' '$1=="FILE"{print $2}' | tr -d '[:space:]')"
    case "$REPROVE_ATTEST_FILE" in
      ""|*"/"*|"."|"..") echo "enable re-proof $REPROVE_LABEL attestation filename invalid, no claim made." >&2; phase_failed enable ;;
    esac
    REPROVE_ATTEST_PATH="$LAUNCH_JOURNAL_DIR/recovery/$REPROVE_ATTEST_FILE"
    if [ -L "$REPROVE_ATTEST_PATH" ] || [ ! -f "$REPROVE_ATTEST_PATH" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL attestation $REPROVE_ATTEST_FILE missing or symlink, no claim made. Inspect $LAUNCH_JOURNAL_DIR/recovery." >&2
      phase_failed enable
    fi
    REPROVE_ATTEST_DETAIL="$(python3 - "$REPROVE_ATTEST_PATH" 2>/dev/null <<'PYEOF'
import json, os, sys
path = sys.argv[1]
try:
    if os.path.islink(path):
        print("PROOF\tSYMLINK")
        sys.exit(0)
    finfo = os.stat(path)
    if (finfo.st_mode & 0o777) != 0o600:
        print("PROOF\tMODE")
        sys.exit(0)
    if finfo.st_uid != os.getuid():
        print("PROOF\tOWNER")
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
for _k in ("original_basename", "original_sha256", "original_token", "original_task_arn",
            "original_taskdef_arn", "original_generation", "original_source_sha",
            "original_target_head", "original_outcome", "legacy_unversioned",
            "stack_id", "release_generation", "source_sha", "target_head",
            "observed_head", "verifier_proof", "verifier_last_status",
            "absence_proof", "runtime_arn", "runtime_name",
            "runtime_version_pre", "runtime_version_post",
            "migration_arn", "migration_name",
            "migration_version_pre", "migration_version_post",
            "tls_arn", "tls_name", "tls_version_pre", "tls_version_post",
            "cert_arn", "cert_domain", "cert_serial_pre", "cert_serial_post"):
    print("%s\t%s" % (_k.upper(), doc.get(_k, "") or ""))
print("PROOF\tOK")
PYEOF
)" || REPROVE_ATTEST_DETAIL="PROOF\tUNREADABLE"
    REPROVE_DETAIL_PROOF="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$REPROVE_DETAIL_PROOF" != "OK" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL attestation $REPROVE_ATTEST_FILE is $REPROVE_DETAIL_PROOF, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    REPROVE_ORIG_BASE="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="ORIGINAL_BASENAME"{print $2}' | tr -d '[:space:]')"
    REPROVE_ORIG_SHA="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="ORIGINAL_SHA256"{print $2}' | tr -d '[:space:]')"
    case "$REPROVE_ORIG_BASE" in
      ""|*"/"*|"."|"..") echo "refused: enable re-proof $REPROVE_LABEL attestation has invalid original basename, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2; phase_failed enable ;;
    esac
    REPROVE_ORIG_PATH="$LAUNCH_JOURNAL_DIR/$REPROVE_ORIG_BASE"
    if [ -L "$REPROVE_ORIG_PATH" ] || [ ! -f "$REPROVE_ORIG_PATH" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL attestation $REPROVE_ATTEST_FILE is orphan, exact original $REPROVE_ORIG_BASE missing, separately reviewed repair required with no stack update. Inspect $REPROVE_ATTEST_PATH. No new launch." >&2
      phase_failed enable
    fi
    if ! REPROVE_ORIG_ACTUAL_SHA="$(sha256_of_file "$REPROVE_ORIG_PATH")"; then
      echo "refused: enable re-proof $REPROVE_LABEL original $REPROVE_ORIG_BASE hash unreadable, no claim made. Inspect $REPROVE_ORIG_PATH." >&2
      phase_failed enable
    fi
    REPROVE_ORIG_ACTUAL_SHA="$(printf '%s' "$REPROVE_ORIG_ACTUAL_SHA" | tr -d '[:space:]')"
    if [ -z "$REPROVE_ORIG_SHA" ] || [ "$REPROVE_ORIG_ACTUAL_SHA" != "$REPROVE_ORIG_SHA" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL original $REPROVE_ORIG_BASE hash mismatch, bytes changed since attestation, no claim made. Inspect $REPROVE_ORIG_PATH and $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    REPROVE_ORIG_VALIDATED="$(validate_typed_journal_for_recovery "$REPROVE_ORIG_PATH" "$REPROVE_ORIG_BASE" "$REPROVE_ORIGIN" "$REPROVE_LABEL" "$REPROVE_TYPED_LOGICAL" "${REPROVE_ALLOW_STARTED:-0}")" || REPROVE_ORIG_VALIDATED="PROOF\tUNREADABLE"
    REPROVE_ORIG_VPROOF="$(printf '%s\n' "$REPROVE_ORIG_VALIDATED" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$REPROVE_ORIG_VPROOF" != "OK" ]; then
      REPROVE_ORIG_VOUT="$(printf '%s\n' "$REPROVE_ORIG_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
      echo "refused: enable re-proof $REPROVE_LABEL original $REPROVE_ORIG_BASE is $REPROVE_ORIG_VPROOF ${REPROVE_ORIG_VOUT:-}, full typed binding failed, no claim made. Inspect $REPROVE_ORIG_PATH." >&2
      phase_failed enable
    fi
    REPROVE_V_TOKEN="$(printf '%s\n' "$REPROVE_ORIG_VALIDATED" | awk -F'\t' '$1=="TOKEN"{print $2}' | tr -d '[:space:]')"
    REPROVE_V_TASK="$(printf '%s\n' "$REPROVE_ORIG_VALIDATED" | awk -F'\t' '$1=="TASKARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_V_TASKDEF="$(printf '%s\n' "$REPROVE_ORIG_VALIDATED" | awk -F'\t' '$1=="TASKDEF"{print $2}' | tr -d '[:space:]')"
    REPROVE_V_GEN="$(printf '%s\n' "$REPROVE_ORIG_VALIDATED" | awk -F'\t' '$1=="GEN"{print $2}' | tr -d '[:space:]')"
    REPROVE_V_SOURCE="$(printf '%s\n' "$REPROVE_ORIG_VALIDATED" | awk -F'\t' '$1=="SOURCE"{print $2}' | tr -d '[:space:]')"
    REPROVE_V_HEAD="$(printf '%s\n' "$REPROVE_ORIG_VALIDATED" | awk -F'\t' '$1=="HEAD"{print $2}' | tr -d '[:space:]')"
    REPROVE_V_OUT="$(printf '%s\n' "$REPROVE_ORIG_VALIDATED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
    REPROVE_V_LEGACY="$(printf '%s\n' "$REPROVE_ORIG_VALIDATED" | awk -F'\t' '$1=="LEGACY"{print $2}' | tr -d '[:space:]')"
    [ "$REPROVE_V_LEGACY" = "true" ] || REPROVE_V_LEGACY="false"
    REPROVE_A_TOKEN="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="ORIGINAL_TOKEN"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_TASK="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="ORIGINAL_TASK_ARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_TASKDEF="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="ORIGINAL_TASKDEF_ARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_GEN="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="ORIGINAL_GENERATION"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_SOURCE="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="ORIGINAL_SOURCE_SHA"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_HEAD="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="ORIGINAL_TARGET_HEAD"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_OUT="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="ORIGINAL_OUTCOME"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_LEGACY="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="LEGACY_UNVERSIONED"{print $2}' | tr -d '[:space:]')"
    if [ "$REPROVE_V_TOKEN" != "$REPROVE_A_TOKEN" ] || [ "$REPROVE_V_TASK" != "$REPROVE_A_TASK" ] || [ "$REPROVE_V_TASKDEF" != "$REPROVE_A_TASKDEF" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL original task binding mismatch, wrong task or token, no claim made. Inspect $REPROVE_ORIG_PATH and $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if [ "$REPROVE_V_GEN" != "$REPROVE_A_GEN" ] || [ "$REPROVE_V_SOURCE" != "$REPROVE_A_SOURCE" ] || [ "$REPROVE_V_HEAD" != "$REPROVE_A_HEAD" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL original generation, source or head mismatch, no claim made. Inspect $REPROVE_ORIG_PATH and $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if [ "$REPROVE_V_OUT" != "$REPROVE_A_OUT" ] || [ "$REPROVE_V_LEGACY" != "$REPROVE_A_LEGACY" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL original outcome or legacy flag mismatch, no claim made. Inspect $REPROVE_ORIG_PATH and $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    REPROVE_A_STACK="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="STACK_ID"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_RELGEN="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="RELEASE_GENERATION"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_SOURCE="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="SOURCE_SHA"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_HEAD="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="TARGET_HEAD"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_VPROOF="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="VERIFIER_PROOF"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_VSTATUS="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="VERIFIER_LAST_STATUS"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_ABSENCE="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="ABSENCE_PROOF"{print $2}' | tr -d '[:space:]')"
    if [ -z "$REPROVE_A_STACK" ] || [ "$REPROVE_A_STACK" != "${STACK_ID:-}" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL attestation stack mismatch, wrong stack, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if [ "$REPROVE_A_RELGEN" != "${RELEASE_GEN:-}" ] || [ "$REPROVE_A_SOURCE" != "${SOURCE_SHA:-}" ] || [ "$REPROVE_A_HEAD" != "${TARGET_DB_HEAD:-008}" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL attestation release, source or head mismatch, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if [ "$REPROVE_A_VPROOF" != "OK" ] || [ "$REPROVE_A_VSTATUS" != "STOPPED" ] || [ "$REPROVE_A_ABSENCE" != "OK" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL attestation missing verifier proof, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    [ -n "${RUNTIME_SECRET_ARN:-}" ] && [ -n "${MIGRATION_SECRET_ARN:-}" ] && [ -n "${TLS_SECRET_ARN:-}" ] || {
      echo "refused: enable re-proof $REPROVE_LABEL needs exact runtime, migration and TLS secret ARNs, no claim made." >&2
      phase_failed enable
    }
    REPROVE_CUR_RT="$(fetch_secret_version_identity "$RUNTIME_SECRET_ARN" runtime)"
    REPROVE_CUR_RT_PROOF="$(printf '%s\n' "$REPROVE_CUR_RT" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$REPROVE_CUR_RT_PROOF" != "OK" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL runtime secret proof is $REPROVE_CUR_RT_PROOF, no claim made." >&2
      phase_failed enable
    fi
    REPROVE_CUR_MG="$(fetch_secret_version_identity "$MIGRATION_SECRET_ARN" migration)"
    REPROVE_CUR_MG_PROOF="$(printf '%s\n' "$REPROVE_CUR_MG" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$REPROVE_CUR_MG_PROOF" != "OK" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL migration secret proof is $REPROVE_CUR_MG_PROOF, no claim made." >&2
      phase_failed enable
    fi
    REPROVE_CUR_TLS="$(fetch_secret_version_identity "$TLS_SECRET_ARN" tls)"
    REPROVE_CUR_TLS_PROOF="$(printf '%s\n' "$REPROVE_CUR_TLS" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$REPROVE_CUR_TLS_PROOF" != "OK" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL TLS secret proof is $REPROVE_CUR_TLS_PROOF, no claim made." >&2
      phase_failed enable
    fi
    REPROVE_CUR_RT_ARN="$(printf '%s\n' "$REPROVE_CUR_RT" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_CUR_RT_NAME="$(printf '%s\n' "$REPROVE_CUR_RT" | awk -F'\t' '$1=="NAME"{print $2}' | tr -d '[:space:]')"
    REPROVE_CUR_RT_VER="$(printf '%s\n' "$REPROVE_CUR_RT" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
    REPROVE_CUR_MG_ARN="$(printf '%s\n' "$REPROVE_CUR_MG" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_CUR_MG_NAME="$(printf '%s\n' "$REPROVE_CUR_MG" | awk -F'\t' '$1=="NAME"{print $2}' | tr -d '[:space:]')"
    REPROVE_CUR_MG_VER="$(printf '%s\n' "$REPROVE_CUR_MG" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
    REPROVE_CUR_TLS_ARN="$(printf '%s\n' "$REPROVE_CUR_TLS" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_CUR_TLS_NAME="$(printf '%s\n' "$REPROVE_CUR_TLS" | awk -F'\t' '$1=="NAME"{print $2}' | tr -d '[:space:]')"
    REPROVE_CUR_TLS_VER="$(printf '%s\n' "$REPROVE_CUR_TLS" | awk -F'\t' '$1=="VERSION"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_RT_ARN="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="RUNTIME_ARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_RT_NAME="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="RUNTIME_NAME"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_RT_PRE="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="RUNTIME_VERSION_PRE"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_RT_POST="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="RUNTIME_VERSION_POST"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_MG_ARN="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="MIGRATION_ARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_MG_NAME="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="MIGRATION_NAME"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_MG_PRE="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="MIGRATION_VERSION_PRE"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_MG_POST="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="MIGRATION_VERSION_POST"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_TLS_ARN="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="TLS_ARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_TLS_NAME="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="TLS_NAME"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_TLS_PRE="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="TLS_VERSION_PRE"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_TLS_POST="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="TLS_VERSION_POST"{print $2}' | tr -d '[:space:]')"
    if [ "$REPROVE_CUR_RT_ARN" != "$REPROVE_A_RT_ARN" ] || [ "$REPROVE_A_RT_ARN" != "$RUNTIME_SECRET_ARN" ] || [ "$REPROVE_CUR_RT_NAME" != "$REPROVE_A_RT_NAME" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL runtime material identity mismatch, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if [ "$REPROVE_CUR_RT_VER" != "$REPROVE_A_RT_PRE" ] || [ "$REPROVE_CUR_RT_VER" != "$REPROVE_A_RT_POST" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL live runtime VersionId changed since recovery attestation, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if [ "$REPROVE_CUR_MG_ARN" != "$REPROVE_A_MG_ARN" ] || [ "$REPROVE_A_MG_ARN" != "$MIGRATION_SECRET_ARN" ] || [ "$REPROVE_CUR_MG_NAME" != "$REPROVE_A_MG_NAME" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL migration material identity mismatch, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if [ "$REPROVE_CUR_MG_VER" != "$REPROVE_A_MG_PRE" ] || [ "$REPROVE_CUR_MG_VER" != "$REPROVE_A_MG_POST" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL live migration VersionId changed since recovery attestation, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if [ "$REPROVE_CUR_TLS_ARN" != "$REPROVE_A_TLS_ARN" ] || [ "$REPROVE_A_TLS_ARN" != "$TLS_SECRET_ARN" ] || [ "$REPROVE_CUR_TLS_NAME" != "$REPROVE_A_TLS_NAME" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL TLS material identity mismatch, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if [ "$REPROVE_CUR_TLS_VER" != "$REPROVE_A_TLS_PRE" ] || [ "$REPROVE_CUR_TLS_VER" != "$REPROVE_A_TLS_POST" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL live TLS VersionId changed since recovery attestation, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if ! REPROVE_CUR_CERT_VALUE="$(params_file_value AcmCertificateArn)"; then
      echo "refused: enable re-proof $REPROVE_LABEL certificate ARN missing from parameters file, no claim made." >&2
      phase_failed enable
    fi
    REPROVE_CUR_CERT_VALUE="$(printf '%s' "$REPROVE_CUR_CERT_VALUE" | tr -d '[:space:]')"
    [ -n "$REPROVE_CUR_CERT_VALUE" ] || { echo "refused: enable re-proof $REPROVE_LABEL certificate ARN empty, no claim made." >&2; phase_failed enable; }
    REPROVE_CUR_CERT="$(fetch_cert_identity "$REPROVE_CUR_CERT_VALUE")"
    REPROVE_CUR_CERT_PROOF="$(printf '%s\n' "$REPROVE_CUR_CERT" | awk -F'\t' '$1=="PROOF"{print $2}' | tr -d '[:space:]')"
    if [ "$REPROVE_CUR_CERT_PROOF" != "OK" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL certificate proof is $REPROVE_CUR_CERT_PROOF, no claim made." >&2
      phase_failed enable
    fi
    REPROVE_CUR_CERT_ARN="$(printf '%s\n' "$REPROVE_CUR_CERT" | awk -F'\t' '$1=="ARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_CUR_CERT_DOMAIN="$(printf '%s\n' "$REPROVE_CUR_CERT" | awk -F'\t' '$1=="DOMAIN"{print $2}' | tr -d '[:space:]')"
    REPROVE_CUR_CERT_SERIAL="$(printf '%s\n' "$REPROVE_CUR_CERT" | awk -F'\t' '$1=="SERIAL"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_CERT_ARN="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="CERT_ARN"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_CERT_DOMAIN="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="CERT_DOMAIN"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_CERT_PRE="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="CERT_SERIAL_PRE"{print $2}' | tr -d '[:space:]')"
    REPROVE_A_CERT_POST="$(printf '%s\n' "$REPROVE_ATTEST_DETAIL" | awk -F'\t' '$1=="CERT_SERIAL_POST"{print $2}' | tr -d '[:space:]')"
    if [ "$REPROVE_CUR_CERT_ARN" != "$REPROVE_A_CERT_ARN" ] || [ "$REPROVE_A_CERT_ARN" != "$REPROVE_CUR_CERT_VALUE" ] || [ "$REPROVE_CUR_CERT_DOMAIN" != "$REPROVE_A_CERT_DOMAIN" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL certificate identity mismatch, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    if [ "$REPROVE_CUR_CERT_SERIAL" != "$REPROVE_A_CERT_PRE" ] || [ "$REPROVE_CUR_CERT_SERIAL" != "$REPROVE_A_CERT_POST" ]; then
      echo "refused: enable re-proof $REPROVE_LABEL live certificate serial changed since recovery attestation, no claim made. Inspect $REPROVE_ATTEST_PATH." >&2
      phase_failed enable
    fi
    echo "Enable re-proof: $REPROVE_LABEL prior $REPROVE_ORIGIN accepted via single current-release $REPROVE_KIND $REPROVE_ATTEST_FILE with exact original $REPROVE_ORIG_BASE revalidated and unchanged material, no new launch; aged file alone never passes."
    return 0
  fi
  REPROVE_PARSED="$(python3 - "$REPROVE_ACTIVE_FILE" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$STACK_NAME" "$CLUSTER_NAME" "$REPROVE_ORIGIN" "$REPROVE_LABEL" "$REPROVE_LOGICAL" "$REPROVE_TASKDEF_ARN" "$REPROVE_CONFIG_DIGEST" "$RELEASE_GEN" "$TARGET_DB_HEAD" "${STACK_ID:-}" 2>/dev/null <<'PYEOF'
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
for _k, _v in doc.items():
    if _k == "version":
        if not isinstance(_v, int) or isinstance(_v, bool):
            print("PROOF\tMALFORMED")
            sys.exit(0)
        continue
    if not isinstance(_v, str):
        print("PROOF\tMALFORMED")
        sys.exit(0)
for _k, _v in doc.items():
    _kl = str(_k).lower()
    if _kl in ("password", "database-url", "database_url",
               "tls-cert-b64", "tls-key-b64", "tls_cert_b64", "tls_key_b64",
               "secret_value", "secretvalue", "private_key", "privatekey",
               "certificate_body", "certificate_chain"):
        print("PROOF\tSECRET_FIELD")
        sys.exit(0)
    if isinstance(_v, str):
        _vl = _v.lower()
        if "://" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "-----begin" in _vl or "-----end" in _vl or "private key" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "tls-cert-b64" in _vl or "tls-key-b64" in _vl or "database-url" in _vl:
            print("PROOF\tSECRET_FIELD")
            sys.exit(0)
        if "password" in _vl:
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
)" || REPROVE_PARSED="PROOF\tUNREADABLE"
  REPROVE_PROOF="$(printf '%s\n' "$REPROVE_PARSED" | awk -F'\t' '$1=="PROOF"{print $2}')"
  REPROVE_PROOF="$(printf '%s' "$REPROVE_PROOF" | tr -d '[:space:]')"
  if [ "$REPROVE_PROOF" != "OK" ]; then
    echo "refused: enable re-proof prior $REPROVE_LABEL $REPROVE_ORIGIN record is $REPROVE_PROOF, no claim made. Inspect $REPROVE_ACTIVE_FILE." >&2
    phase_failed enable
  fi
  REPROVE_OUTCOME="$(printf '%s\n' "$REPROVE_PARSED" | awk -F'\t' '$1=="OUTCOME"{print $2}' | tr -d '[:space:]')"
  REPROVE_TOKEN="$(printf '%s\n' "$REPROVE_PARSED" | awk -F'\t' '$1=="TOKEN"{print $2}' | tr -d '[:space:]')"
  REPROVE_TASK="$(printf '%s\n' "$REPROVE_PARSED" | awk -F'\t' '$1=="TASKARN"{print $2}' | tr -d '[:space:]')"
  if [ "$REPROVE_OUTCOME" != "complete" ]; then
    echo "refused: enable re-proof prior $REPROVE_LABEL $REPROVE_ORIGIN is $REPROVE_OUTCOME, not complete. Run --phase $REPROVE_ORIGIN to reconcile first. No new launch. Inspect $REPROVE_ACTIVE_FILE." >&2
    phase_failed enable
  fi
  [ -n "$REPROVE_TASK" ] && [ "$REPROVE_TASK" != "None" ] || { echo "refused: enable re-proof prior $REPROVE_LABEL has no task ARN, not claimed. Inspect $REPROVE_ACTIVE_FILE." >&2; phase_failed enable; }
  if ! "$AWS_BIN" ecs wait tasks-stopped --cluster "$CLUSTER_NAME" --tasks "$REPROVE_TASK" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    echo "enable re-proof $REPROVE_LABEL wait reported, verifying terminal state before any claim." >&2
  fi
  REPROVE_DESC_JSON="$(mktemp /tmp/launchcrew-reprove-XXXXXX)"
  if ! "$AWS_BIN" ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$REPROVE_TASK" --region "$EXPECTED_REGION" --output json >"$REPROVE_DESC_JSON" 2>"$TMP_ERR"; then
    rm -f "$REPROVE_DESC_JSON"
    echo "enable re-proof $REPROVE_LABEL terminal state unreadable, not claimed." >&2
    phase_failed enable
  fi
  REPROVE_TASKDEF_JSON="$(mktemp /tmp/launchcrew-reprove-def-XXXXXX)"
  if ! fetch_taskdef_json "$REPROVE_LOGICAL" "$REPROVE_TASKDEF_JSON"; then
    rm -f "$REPROVE_DESC_JSON" "$REPROVE_TASKDEF_JSON"
    echo "enable re-proof $REPROVE_LABEL expected container set unreadable, not claimed." >&2
    phase_failed enable
  fi
  REPROVE_CHECK="$(python3 - "$REPROVE_DESC_JSON" "$REPROVE_TASKDEF_JSON" "$REPROVE_TASK" "$REPROVE_TASKDEF_ARN" "arn:aws:ecs:$EXPECTED_REGION:$EXPECTED_ACCOUNT:cluster/$CLUSTER_NAME" "$REPROVE_TOKEN" 2>/dev/null <<'PYEOF'
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
)" || REPROVE_CHECK="UNREADABLE"
  rm -f "$REPROVE_DESC_JSON" "$REPROVE_TASKDEF_JSON"
  REPROVE_CHECK="$(printf '%s' "$REPROVE_CHECK" | tr -d '[:space:]')"
  if [ "$REPROVE_CHECK" != "OK" ]; then
    echo "refused: enable re-proof prior $REPROVE_LABEL terminal proof is $REPROVE_CHECK, not claimed. Inspect $REPROVE_ACTIVE_FILE." >&2
    phase_failed enable
  fi
  echo "Enable re-proof: $REPROVE_LABEL prior $REPROVE_ORIGIN STOPPED exit 0 with no new launch."
}

if wants_phase enable; then
  echo "Phase enable: update stack with EnableServices=true for fixed count 1 each"
  [ "$STACK_EXISTS" -eq 1 ] || { echo "refused: no stack to enable; run --phase infra first" >&2; phase_failed enable; }
  require_stack_complete enable
  check_budget_readiness
  # Resume guard: a standalone enable re-proves everything boot would rely
  # on, because nothing is assumed from memory. Refresh the full image
  # digest and task definition ref proof, the owned secrets and role bindings
  # including TLS material, then re-prove current-release typed attestations
  # or fresh live terminal journals for material, roles, migration008 and
  # runtime, all exact identities and unchanged inputs, with no new mutating
  # run-task call. Standalone enable may refresh only read-only proofs, never
  # bind roles, migrate, rotate, publish, populate, or export. An aged file
  # alone never passes. Services stay zero until all gates pass.
  verify_image "$API_IMAGE" launchcrew-api ApiTaskDefinition api api
  verify_image "$WEB_IMAGE" launchcrew-web WebTaskDefinition web-app web
  verify_image "$WEB_PROXY_IMAGE" launchcrew-web-proxy WebTaskDefinition web-proxy web-proxy
  verify_image "$MIGRATION_IMAGE" launchcrew-migration MigrationTaskDefinition migration migration
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap BootstrapTaskDefinition bootstrap-db-roles bootstrap
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap SdkInitTaskDefinition sdk-init bootstrap-sdk-init
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap SdkMaterialTaskDefinition sdk-material bootstrap-sdk-material
  verify_image "$BOOTSTRAP_IMAGE" launchcrew-bootstrap RoleStateTaskDefinition bootstrap-db-roles bootstrap-rolestate
  check_api_taskdef_binding enable
  check_taskdef_binding WebTaskDefinition WebExecutionRole WebTaskRole \
    "web-proxy.TLS_CERT_B64=$TLS_SECRET_ARN:tls-cert-b64::" \
    "web-proxy.TLS_KEY_B64=$TLS_SECRET_ARN:tls-key-b64::"
  check_taskdef_binding VerifyTaskDefinition VerifyExecutionRole VerifyTaskRole \
    "bootstrap-db-roles.RUNTIME_DB_URL=$RUNTIME_SECRET_ARN:database-url::"
  check_taskdef_binding BootstrapTaskDefinition BootstrapExecutionRole BootstrapTaskRole \
    "bootstrap-db-roles.MASTER_DB_PASSWORD=$MASTER_SECRET_ARN:password::" \
    "bootstrap-db-roles.RUNTIME_DB_URL=$RUNTIME_SECRET_ARN:database-url::" \
    "bootstrap-db-roles.MIGRATION_DB_URL=$MIGRATION_SECRET_ARN:database-url::"
  check_taskdef_binding MigrationTaskDefinition MigrationExecutionRole MigrationTaskRole \
    "migration.DATABASE_URL=$MIGRATION_SECRET_ARN:database-url::"
  check_sdk_taskdef SdkMaterialTaskDefinition SdkMaterialExecutionRole SdkMaterialTaskRole sdk-material --verify-material
  check_rolestate_taskdef
  echo "Enable precheck: all owned task definition images, secrets, and owned roles match validated values, SDK material and role-state shapes proven"
  RECOVERY_READONLY=1
  require_init_desired_state enable
  require_typed_desired_state enable material sdk-material SdkMaterialTaskDefinition material-recovery-attestation SdkMaterialTaskDefinition sdk-material 0 0
  require_typed_desired_state enable dbroles bootstrap BootstrapTaskDefinition dbroles-recovery-attestation RoleStateTaskDefinition bootstrap-db-roles 1 1
  require_typed_desired_state enable migrate migration MigrationTaskDefinition migration-recovery-attestation RoleStateTaskDefinition bootstrap-db-roles 0 1
  require_typed_desired_state enable migrate verify VerifyTaskDefinition runtime-recovery-attestation VerifyTaskDefinition bootstrap-db-roles 0 0
  RECOVERY_READONLY=0
  reprove_prior_one_off_readonly SdkMaterialTaskDefinition sdk-material material
  reprove_prior_one_off_readonly BootstrapTaskDefinition bootstrap dbroles
  reprove_prior_one_off_readonly MigrationTaskDefinition migration migrate
  reprove_prior_one_off_readonly VerifyTaskDefinition verify migrate
  echo "Enable proof: material, roles, migration008 and runtime re-proved via current attestations or fresh journals with no new mutating run-task."
  ENABLE_OLD_API_TASKDEF=""
  ENABLE_OLD_WEB_TASKDEF=""
  if ! ENABLE_OLD_API_TASKDEF="$(stack_resource ApiTaskDefinition 2>"$TMP_ERR")"; then
    echo "refused: enable old ApiTaskDefinition unreadable, no change made" >&2; phase_failed enable
  fi
  if ! ENABLE_OLD_WEB_TASKDEF="$(stack_resource WebTaskDefinition 2>"$TMP_ERR")"; then
    echo "refused: enable old WebTaskDefinition unreadable, no change made" >&2; phase_failed enable
  fi
  ENABLE_OLD_API_TASKDEF="$(printf '%s' "$ENABLE_OLD_API_TASKDEF" | tr -d '[:space:]')"
  ENABLE_OLD_WEB_TASKDEF="$(printf '%s' "$ENABLE_OLD_WEB_TASKDEF" | tr -d '[:space:]')"
  [ -n "$ENABLE_OLD_API_TASKDEF" ] && [ "$ENABLE_OLD_API_TASKDEF" != "None" ] || { echo "refused: enable old ApiTaskDefinition missing, no change made" >&2; phase_failed enable; }
  [ -n "$ENABLE_OLD_WEB_TASKDEF" ] && [ "$ENABLE_OLD_WEB_TASKDEF" != "None" ] || { echo "refused: enable old WebTaskDefinition missing, no change made" >&2; phase_failed enable; }
  ENABLE_OLD_API_JSON="$(mktemp /tmp/launchcrew-enable-old-api-XXXXXX)"
  ENABLE_OLD_WEB_JSON="$(mktemp /tmp/launchcrew-enable-old-web-XXXXXX)"
  if ! fetch_taskdef_json ApiTaskDefinition "$ENABLE_OLD_API_JSON"; then
    rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
    echo "refused: enable old ApiTaskDefinition document unreadable, no change made" >&2; phase_failed enable
  fi
  if ! fetch_taskdef_json WebTaskDefinition "$ENABLE_OLD_WEB_JSON"; then
    rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
    echo "refused: enable old WebTaskDefinition document unreadable, no change made" >&2; phase_failed enable
  fi
  ENABLE_OLD_IMAGES="$(python3 - "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON" 2>/dev/null <<'PYEOF'
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
)" || { rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"; echo "refused: enable old taskdef images unreadable, no change made" >&2; phase_failed enable; }
  ENABLE_OLD_API_IMAGE="$(printf '%s\n' "$ENABLE_OLD_IMAGES" | awk -F'\t' '$1=="API"{print $2}')"
  ENABLE_OLD_WEB_IMAGE="$(printf '%s\n' "$ENABLE_OLD_IMAGES" | awk -F'\t' '$1=="WEB"{print $2}')"
  ENABLE_OLD_PROXY_IMAGE="$(printf '%s\n' "$ENABLE_OLD_IMAGES" | awk -F'\t' '$1=="PROXY"{print $2}')"
  [ -n "$ENABLE_OLD_API_IMAGE" ] || { rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"; echo "refused: enable old api image missing, no change made" >&2; phase_failed enable; }
  [ -n "$ENABLE_OLD_WEB_IMAGE" ] || { rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"; echo "refused: enable old web image missing, no change made" >&2; phase_failed enable; }
  [ -n "$ENABLE_OLD_PROXY_IMAGE" ] || { rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"; echo "refused: enable old proxy image missing, no change made" >&2; phase_failed enable; }
  ENABLE_GOOGLE_ENABLE="$(params_file_value EnableGoogleAuth 2>/dev/null || true)"
  ENABLE_GOOGLE_ENABLE="$(printf '%s' "$ENABLE_GOOGLE_ENABLE" | tr -d '[:space:]')"
  [ -n "$ENABLE_GOOGLE_ENABLE" ] || ENABLE_GOOGLE_ENABLE="false"
  ENABLE_OLD_POLICY=""
  if [ "$ENABLE_GOOGLE_ENABLE" = "true" ]; then
    if ! ENABLE_OLD_POLICY="$(stack_resource ApiGoogleAuthPolicy 2>"$TMP_ERR")"; then
      rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
      echo "refused: enable old ApiGoogleAuthPolicy unreadable, no change made" >&2; phase_failed enable
    fi
    ENABLE_OLD_POLICY="$(printf '%s' "$ENABLE_OLD_POLICY" | tr -d '[:space:]')"
    [ -n "$ENABLE_OLD_POLICY" ] && [ "$ENABLE_OLD_POLICY" != "None" ] || { rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"; echo "refused: enable old ApiGoogleAuthPolicy missing, no change made" >&2; phase_failed enable; }
  else
    if ENABLE_OLD_POLICY="$(stack_resource ApiGoogleAuthPolicy 2>/dev/null)"; then
      ENABLE_OLD_POLICY="$(printf '%s' "$ENABLE_OLD_POLICY" | tr -d '[:space:]')"
      if [ -n "$ENABLE_OLD_POLICY" ] && [ "$ENABLE_OLD_POLICY" != "None" ]; then
        rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
        echo "refused: enable old ApiGoogleAuthPolicy present while EnableGoogleAuth false, no change made" >&2; phase_failed enable
      fi
    fi
    ENABLE_OLD_POLICY=""
  fi
  ENABLE_META_ARN="$(params_file_value MetaSecretArn 2>/dev/null || true)"
  ENABLE_META_ARN="$(printf '%s' "$ENABLE_META_ARN" | tr -d '[:space:]')"
  ENABLE_OLD_META_POLICY=""
  if [ -n "$ENABLE_META_ARN" ]; then
    if ! ENABLE_OLD_META_POLICY="$(stack_resource ApiMetaSecretPolicy 2>"$TMP_ERR")"; then
      rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
      echo "refused: enable old ApiMetaSecretPolicy unreadable, no change made" >&2; phase_failed enable
    fi
    ENABLE_OLD_META_POLICY="$(printf '%s' "$ENABLE_OLD_META_POLICY" | tr -d '[:space:]')"
    [ -n "$ENABLE_OLD_META_POLICY" ] && [ "$ENABLE_OLD_META_POLICY" != "None" ] || { rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"; echo "refused: enable old ApiMetaSecretPolicy missing, no change made" >&2; phase_failed enable; }
  else
    if ENABLE_OLD_META_POLICY="$(stack_resource ApiMetaSecretPolicy 2>/dev/null)"; then
      ENABLE_OLD_META_POLICY="$(printf '%s' "$ENABLE_OLD_META_POLICY" | tr -d '[:space:]')"
      if [ -n "$ENABLE_OLD_META_POLICY" ] && [ "$ENABLE_OLD_META_POLICY" != "None" ]; then
        rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
        echo "refused: enable old ApiMetaSecretPolicy present while MetaSecretArn empty, no change made" >&2; phase_failed enable
      fi
    fi
    ENABLE_OLD_META_POLICY=""
  fi
  echo "Enable identity pinned: ApiTaskDefinition and WebTaskDefinition plus three images plus Google and Meta policies must be unchanged by this deploy"
  if ! cloudformation_deploy "true" enable; then
    rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
    echo "enable deploy failed, services unchanged." >&2
    phase_failed enable
  fi
  if ! "$AWS_BIN" cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" 2>"$TMP_ERR"; then
    echo "enable wait reported, verifying service counts before any claim." >&2
  fi
  require_stack_complete enable
  verify_ecs_service ApiService api
  verify_ecs_service WebService web
  ENABLE_NEW_API_TASKDEF=""
  ENABLE_NEW_WEB_TASKDEF=""
  if ! ENABLE_NEW_API_TASKDEF="$(stack_resource ApiTaskDefinition 2>"$TMP_ERR")"; then
    rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
    echo "refused: enable new ApiTaskDefinition unreadable after deploy" >&2; phase_failed enable
  fi
  if ! ENABLE_NEW_WEB_TASKDEF="$(stack_resource WebTaskDefinition 2>"$TMP_ERR")"; then
    rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
    echo "refused: enable new WebTaskDefinition unreadable after deploy" >&2; phase_failed enable
  fi
  ENABLE_NEW_API_TASKDEF="$(printf '%s' "$ENABLE_NEW_API_TASKDEF" | tr -d '[:space:]')"
  ENABLE_NEW_WEB_TASKDEF="$(printf '%s' "$ENABLE_NEW_WEB_TASKDEF" | tr -d '[:space:]')"
  if [ "$ENABLE_NEW_API_TASKDEF" != "$ENABLE_OLD_API_TASKDEF" ]; then
    rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
    echo "refused: ApiTaskDefinition changed during enable, task definition and image updates under services are blocked. Run explicit quiesce plus infra first." >&2; phase_failed enable
  fi
  if [ "$ENABLE_NEW_WEB_TASKDEF" != "$ENABLE_OLD_WEB_TASKDEF" ]; then
    rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
    echo "refused: WebTaskDefinition changed during enable, task definition and image updates under services are blocked. Run explicit quiesce plus infra first." >&2; phase_failed enable
  fi
  ENABLE_NEW_POLICY=""
  if [ "$ENABLE_GOOGLE_ENABLE" = "true" ]; then
    if ! ENABLE_NEW_POLICY="$(stack_resource ApiGoogleAuthPolicy 2>"$TMP_ERR")"; then
      rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
      echo "refused: enable new ApiGoogleAuthPolicy unreadable after deploy" >&2; phase_failed enable
    fi
    ENABLE_NEW_POLICY="$(printf '%s' "$ENABLE_NEW_POLICY" | tr -d '[:space:]')"
    if [ "$ENABLE_NEW_POLICY" != "$ENABLE_OLD_POLICY" ]; then
      rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
      echo "refused: ApiGoogleAuthPolicy changed during enable, task definition and policy updates under services are blocked. Run explicit quiesce plus infra first." >&2; phase_failed enable
    fi
  else
    if ENABLE_NEW_POLICY="$(stack_resource ApiGoogleAuthPolicy 2>/dev/null)"; then
      ENABLE_NEW_POLICY="$(printf '%s' "$ENABLE_NEW_POLICY" | tr -d '[:space:]')"
      if [ -n "$ENABLE_NEW_POLICY" ] && [ "$ENABLE_NEW_POLICY" != "None" ]; then
        rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
        echo "refused: ApiGoogleAuthPolicy appeared during enable while disabled, task definition and policy updates under services are blocked. Run explicit quiesce plus infra first." >&2; phase_failed enable
      fi
    fi
  fi
  ENABLE_NEW_META_POLICY=""
  if [ -n "$ENABLE_META_ARN" ]; then
    if ! ENABLE_NEW_META_POLICY="$(stack_resource ApiMetaSecretPolicy 2>"$TMP_ERR")"; then
      rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
      echo "refused: enable new ApiMetaSecretPolicy unreadable after deploy" >&2; phase_failed enable
    fi
    ENABLE_NEW_META_POLICY="$(printf '%s' "$ENABLE_NEW_META_POLICY" | tr -d '[:space:]')"
    if [ "$ENABLE_NEW_META_POLICY" != "$ENABLE_OLD_META_POLICY" ]; then
      rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
      echo "refused: ApiMetaSecretPolicy changed during enable, task definition and policy updates under services are blocked. Run explicit quiesce plus infra first." >&2; phase_failed enable
    fi
  else
    if ENABLE_NEW_META_POLICY="$(stack_resource ApiMetaSecretPolicy 2>/dev/null)"; then
      ENABLE_NEW_META_POLICY="$(printf '%s' "$ENABLE_NEW_META_POLICY" | tr -d '[:space:]')"
      if [ -n "$ENABLE_NEW_META_POLICY" ] && [ "$ENABLE_NEW_META_POLICY" != "None" ]; then
        rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON"
        echo "refused: ApiMetaSecretPolicy appeared during enable while MetaSecretArn empty, task definition and policy updates under services are blocked. Run explicit quiesce plus infra first." >&2; phase_failed enable
      fi
    fi
  fi
  ENABLE_NEW_API_JSON="$(mktemp /tmp/launchcrew-enable-new-api-XXXXXX)"
  ENABLE_NEW_WEB_JSON="$(mktemp /tmp/launchcrew-enable-new-web-XXXXXX)"
  if ! fetch_taskdef_json ApiTaskDefinition "$ENABLE_NEW_API_JSON"; then
    rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON" "$ENABLE_NEW_API_JSON" "$ENABLE_NEW_WEB_JSON"
    echo "refused: enable new ApiTaskDefinition document unreadable after deploy" >&2; phase_failed enable
  fi
  if ! fetch_taskdef_json WebTaskDefinition "$ENABLE_NEW_WEB_JSON"; then
    rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON" "$ENABLE_NEW_API_JSON" "$ENABLE_NEW_WEB_JSON"
    echo "refused: enable new WebTaskDefinition document unreadable after deploy" >&2; phase_failed enable
  fi
  ENABLE_NEW_IMAGES="$(python3 - "$ENABLE_NEW_API_JSON" "$ENABLE_NEW_WEB_JSON" 2>/dev/null <<'PYEOF'
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
)" || { rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON" "$ENABLE_NEW_API_JSON" "$ENABLE_NEW_WEB_JSON"; echo "refused: enable new taskdef images unreadable after deploy" >&2; phase_failed enable; }
  ENABLE_NEW_API_IMAGE="$(printf '%s\n' "$ENABLE_NEW_IMAGES" | awk -F'\t' '$1=="API"{print $2}')"
  ENABLE_NEW_WEB_IMAGE="$(printf '%s\n' "$ENABLE_NEW_IMAGES" | awk -F'\t' '$1=="WEB"{print $2}')"
  ENABLE_NEW_PROXY_IMAGE="$(printf '%s\n' "$ENABLE_NEW_IMAGES" | awk -F'\t' '$1=="PROXY"{print $2}')"
  rm -f "$ENABLE_OLD_API_JSON" "$ENABLE_OLD_WEB_JSON" "$ENABLE_NEW_API_JSON" "$ENABLE_NEW_WEB_JSON"
  [ "$ENABLE_NEW_API_IMAGE" = "$ENABLE_OLD_API_IMAGE" ] || { echo "refused: api image changed during enable, task definition and image updates under services are blocked. Run explicit quiesce plus infra first." >&2; phase_failed enable; }
  [ "$ENABLE_NEW_WEB_IMAGE" = "$ENABLE_OLD_WEB_IMAGE" ] || { echo "refused: web image changed during enable, task definition and image updates under services are blocked. Run explicit quiesce plus infra first." >&2; phase_failed enable; }
  [ "$ENABLE_NEW_PROXY_IMAGE" = "$ENABLE_OLD_PROXY_IMAGE" ] || { echo "refused: proxy image changed during enable, task definition and image updates under services are blocked. Run explicit quiesce plus infra first." >&2; phase_failed enable; }
  echo "Verified enable identity: task definitions, images, and Google plus Meta policies unchanged by this deploy"
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
    verify_target_group_drained ApiTargetGroup api
    verify_target_group_drained WebTargetGroup web
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
    rm -f "$QUIESCE_ARGS_FILE"
    [ -n "$QUIESCE_PARAM_ARGS" ] || { rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"; echo "refused: quiesce parameters empty, no change made" >&2; phase_failed quiesce; }
    echo "Quiesce change set uses the existing deployed template with all existing values except EnableServices=false"
    QUIESCE_RESUMED=0
    # shellcheck disable=SC2086
    if ! "$AWS_BIN" cloudformation create-change-set --stack-name "$STACK_NAME" --change-set-name "$QUIESCE_CHANGESET" --change-set-type UPDATE --use-previous-template --parameters $QUIESCE_PARAM_ARGS --capabilities CAPABILITY_NAMED_IAM --tags Key=Project,Value=LaunchCrew Key=Environment,Value=demo --region "$EXPECTED_REGION" --output json >"$TMP_JSON" 2>"$TMP_ERR"; then
      QUIESCE_CREATE_ERR="$(cat "$TMP_ERR" 2>/dev/null || true)"
      case "$QUIESCE_CREATE_ERR" in
        *AlreadyExists*)
          QUIESCE_RESUMED=1
          echo "Quiesce: same-name change set $QUIESCE_CHANGESET already exists, attempting safe resume with read-only proof, never deleting or recreating."
          ;;
        *)
          rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"
          echo "refused: quiesce change set create failed; an existing same-name change set is never deleted or replaced, inspect $QUIESCE_CHANGESET manually after review. No change made." >&2; phase_failed quiesce
          ;;
      esac
    fi
    QUIESCE_PAGES_DIR="$(mktemp -d /tmp/launchcrew-quiesce-pages-XXXXXX)"
    QUIESCE_NEXT=""
    QUIESCE_PAGE_NUM=0
    QUIESCE_WAIT_TRY=0
    while [ "$QUIESCE_PAGE_NUM" -lt 3 ]; do
      QUIESCE_PAGE_NUM=$((QUIESCE_PAGE_NUM + 1))
      QUIESCE_PAGE_FILE="$QUIESCE_PAGES_DIR/page-$QUIESCE_PAGE_NUM.json"
      QUIESCE_INPUT="$(mktemp /tmp/launchcrew-quiesce-in-XXXXXX)"
      if ! python3 - "$QUIESCE_INPUT" "$STACK_NAME" "$QUIESCE_CHANGESET" "$QUIESCE_NEXT" 2>/dev/null <<'PYEOF'
import json, sys
path, stack, changeset, token = sys.argv[1:5]
doc = {"StackName": stack, "ChangeSetName": changeset}
if token and token != "END" and token != "None":
    doc["NextToken"] = token
with open(path, "w", encoding="utf-8") as out:
    json.dump(doc, out)
PYEOF
      then
        rm -f "$QUIESCE_INPUT"
        rm -rf "$QUIESCE_PAGES_DIR"
        rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"
        echo "refused: quiesce change set describe input failed, no change made. Pending change set $QUIESCE_CHANGESET preserved for inspection." >&2
        phase_failed quiesce
      fi
      if ! "$AWS_BIN" cloudformation describe-change-set --cli-input-json "file://$QUIESCE_INPUT" --no-paginate --region "$EXPECTED_REGION" --output json >"$QUIESCE_PAGE_FILE" 2>"$TMP_ERR"; then
        rm -f "$QUIESCE_INPUT"
        rm -rf "$QUIESCE_PAGES_DIR"
        rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"
        echo "refused: quiesce change set $QUIESCE_CHANGESET unreadable, no change made. Pending change set preserved for inspection." >&2
        phase_failed quiesce
      fi
      rm -f "$QUIESCE_INPUT"
      if [ "$QUIESCE_PAGE_NUM" -eq 1 ]; then
        QUIESCE_WAIT_STATUS="$(python3 - "$QUIESCE_PAGE_FILE" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(doc, dict):
    print("MALFORMED")
    sys.exit(0)
print("%s" % (doc.get("Status", "") or "EMPTY"))
PYEOF
)" || QUIESCE_WAIT_STATUS="MALFORMED"
        QUIESCE_WAIT_STATUS="$(printf '%s' "$QUIESCE_WAIT_STATUS" | tr -d '[:space:]')"
        if [ "$QUIESCE_WAIT_STATUS" = "CREATE_IN_PROGRESS" ] || [ "$QUIESCE_WAIT_STATUS" = "CREATE_PENDING" ]; then
          if [ "$QUIESCE_WAIT_TRY" -lt 5 ]; then
            QUIESCE_WAIT_TRY=$((QUIESCE_WAIT_TRY + 1))
            echo "Quiesce: change set $QUIESCE_CHANGESET status $QUIESCE_WAIT_STATUS, waiting bounded ($QUIESCE_WAIT_TRY/5) before review."
            sleep 2 2>/dev/null || true
            QUIESCE_PAGE_NUM=0
            rm -f "$QUIESCE_PAGE_FILE"
            QUIESCE_NEXT=""
            continue
          else
            rm -rf "$QUIESCE_PAGES_DIR"
            rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"
            echo "refused: quiesce change set $QUIESCE_CHANGESET still $QUIESCE_WAIT_STATUS after bounded wait, no execute made. Pending change set preserved for inspection." >&2
            phase_failed quiesce
          fi
        fi
      fi
      QUIESCE_NEXT="$(python3 - "$QUIESCE_PAGE_FILE" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(doc, dict):
    print("MALFORMED")
    sys.exit(0)
if "nextToken" in doc:
    print("MALFORMED")
    sys.exit(0)
nxt = doc.get("NextToken", "")
if nxt is None or nxt == "None":
    nxt = ""
if not isinstance(nxt, str):
    print("MALFORMED")
    sys.exit(0)
print("END" if not nxt.strip() else nxt.strip())
PYEOF
)" || QUIESCE_NEXT="MALFORMED"
      QUIESCE_NEXT="$(printf '%s' "$QUIESCE_NEXT" | tr -d '[:space:]')"
      if [ "$QUIESCE_NEXT" = "MALFORMED" ]; then
        rm -rf "$QUIESCE_PAGES_DIR"
        rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"
        echo "refused: quiesce change set page $QUIESCE_PAGE_NUM malformed, no change made. Pending change set $QUIESCE_CHANGESET preserved for inspection." >&2
        phase_failed quiesce
      fi
      if [ -z "$QUIESCE_NEXT" ] || [ "$QUIESCE_NEXT" = "END" ] || [ "$QUIESCE_NEXT" = "None" ]; then
        QUIESCE_NEXT=""
        break
      fi
    done
    if [ -n "$QUIESCE_NEXT" ]; then
      rm -rf "$QUIESCE_PAGES_DIR"
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"
      echo "refused: quiesce change set has unreviewed pages after 3, no change made. Pending change set $QUIESCE_CHANGESET preserved for inspection." >&2
      phase_failed quiesce
    fi
    QUIESCE_RAW="$(python3 - "$QUIESCE_PAGES_DIR" "$STACK_NAME" "$STACK_ID" "$EXPECTED_ACCOUNT" "$EXPECTED_REGION" "$QUIESCE_CHANGESET" "$QUIESCE_STACK_JSON" 2>/dev/null <<'PYEOF'
import glob, json, os, sys
pages_dir, want_stack, want_id = sys.argv[1:4]
want_account, want_region, want_name, stack_params_path = sys.argv[4:8]
try:
    stack_doc = json.load(open(stack_params_path))
except Exception:
    print("PARAMS_STACK_KEYS")
    sys.exit(0)
stacks = stack_doc.get("Stacks", None)
if not isinstance(stacks, list) or len(stacks) != 1 or not isinstance(stacks[0], dict):
    print("PARAMS_STACK_KEYS")
    sys.exit(0)
live_params = stacks[0].get("Parameters", None)
if not isinstance(live_params, list) or not live_params:
    print("PARAMS_STACK_KEYS")
    sys.exit(0)
expected_live = {}
for live_entry in live_params:
    if not isinstance(live_entry, dict):
        print("PARAMS_STACK_KEYS")
        sys.exit(0)
    live_key = live_entry.get("ParameterKey", "")
    live_value = live_entry.get("ParameterValue", None)
    if not isinstance(live_key, str) or not live_key:
        print("PARAMS_STACK_KEYS")
        sys.exit(0)
    if live_key in expected_live:
        print("PARAMS_STACK_KEYS")
        sys.exit(0)
    if not isinstance(live_value, str):
        print("PARAMS_STACK_KEYS")
        sys.exit(0)
    expected_live[live_key] = live_value
want_keys = set(expected_live)
pages = sorted(glob.glob(os.path.join(pages_dir, "page-*.json")))
if not pages:
    print("MALFORMED")
    sys.exit(0)
try:
    first = json.load(open(pages[0]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
if not isinstance(first, dict):
    print("MALFORMED")
    sys.exit(0)
cs_id = first.get("ChangeSetId", "") or ""
if not isinstance(cs_id, str) or not cs_id.startswith(
        "arn:aws:cloudformation:%s:%s:changeSet/%s/" % (want_region, want_account, want_name)):
    print("ID_MISMATCH")
    sys.exit(0)
if (first.get("ChangeSetName", "") or "") != want_name:
    print("NAME_MISMATCH")
    sys.exit(0)
if (first.get("StackName", "") or "") != want_stack:
    print("STACK_MISMATCH")
    sys.exit(0)
if (first.get("StackId", "") or "") != want_id:
    print("STACKID_MISMATCH")
    sys.exit(0)
if (first.get("Status", "") or "") != "CREATE_COMPLETE":
    print("STATUS_%s" % (first.get("Status", "") or "EMPTY"))
    sys.exit(0)
if (first.get("ExecutionStatus", "") or "") != "AVAILABLE":
    print("EXEC_%s" % (first.get("ExecutionStatus", "") or "EMPTY"))
    sys.exit(0)
changes = []
for page_file in pages:
    try:
        page = json.load(open(page_file))
    except Exception:
        print("MALFORMED")
        sys.exit(0)
    if not isinstance(page, dict):
        print("MALFORMED")
        sys.exit(0)
    part = page.get("Changes", None)
    if not isinstance(part, list):
        print("MALFORMED")
        sys.exit(0)
    changes.extend(part)
    if len(changes) > 4:
        print("TOO_MANY_%d" % len(changes))
        sys.exit(0)
if len(changes) == 0:
    print("EMPTY")
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
            if item != "Properties":
                print("SCOPE_%s_%s" % (logical, str(item)))
                sys.exit(0)
    details = rc.get("Details", None)
    if not isinstance(details, list) or not details:
        print("DETAILS_%s_MISSING" % logical)
        sys.exit(0)
    if len(details) > 10:
        print("DETAILS_%s_MANY" % logical)
        sys.exit(0)
    for detail in details:
        if not isinstance(detail, dict):
            print("DETAILS_%s_MALFORMED" % logical)
            sys.exit(0)
        target = detail.get("Target", None)
        if not isinstance(target, dict):
            print("DETAILS_%s_MALFORMED" % logical)
            sys.exit(0)
        attr = target.get("Attribute", "") or ""
        name = target.get("Name", "") or ""
        recre = target.get("RequiresRecreation", "") or ""
        if attr != "Properties":
            print("DETAIL_%s_ATTR_%s" % (logical, attr or "EMPTY"))
            sys.exit(0)
        if name != "DesiredCount":
            print("DETAIL_%s_NAME_%s" % (logical, name or "EMPTY"))
            sys.exit(0)
        if recre != "Never":
            print("DETAIL_%s_RECRE_%s" % (logical, recre or "EMPTY"))
            sys.exit(0)
if seen != {"ApiService", "WebService"}:
    print("INCOMPLETE_%s" % ",".join(sorted(seen)))
    sys.exit(0)
if not want_keys or "EnableServices" not in want_keys or len(want_keys) > 20:
    print("PARAMS_STACK_KEYS")
    sys.exit(0)
got_params = first.get("Parameters", None)
if not isinstance(got_params, list):
    print("PARAMS_MISSING")
    sys.exit(0)
seen_params = set()
for item in got_params:
    if not isinstance(item, dict):
        print("PARAMS_MALFORMED")
        sys.exit(0)
    for json_key in item.keys():
        if json_key not in ("ParameterKey", "ParameterValue", "UsePreviousValue", "ResolvedValue"):
            print("PARAMS_MALFORMED")
            sys.exit(0)
    key = item.get("ParameterKey", "")
    if not isinstance(key, str):
        print("PARAMS_MALFORMED")
        sys.exit(0)
    if not key or key in seen_params:
        print("PARAMS_DUP_%s" % (key or "EMPTY"))
        sys.exit(0)
    seen_params.add(key)
    if key not in want_keys:
        print("PARAMS_FOREIGN_%s" % key)
        sys.exit(0)
    if "UsePreviousValue" in item and not isinstance(item.get("UsePreviousValue"), bool):
        print("PARAMS_MALFORMED")
        sys.exit(0)
    if "ResolvedValue" in item and not isinstance(item.get("ResolvedValue"), str):
        print("PARAMS_MALFORMED")
        sys.exit(0)
    use_prev = item.get("UsePreviousValue", False)
    if not isinstance(use_prev, bool):
        print("PARAMS_MALFORMED")
        sys.exit(0)
    has_value = "ParameterValue" in item
    raw_value = item.get("ParameterValue", "")
    if has_value and not isinstance(raw_value, str):
        print("PARAMS_MALFORMED")
        sys.exit(0)
    if key == "EnableServices":
        if use_prev:
            print("PARAMS_PREVIOUS_EnableServices")
            sys.exit(0)
        if not has_value:
            print("PARAMS_VALUE_EnableServices")
            sys.exit(0)
        if raw_value != "false":
            print("PARAMS_VALUE_EnableServices")
            sys.exit(0)
    else:
        live_expect = expected_live.get(key, None)
        if not isinstance(live_expect, str):
            print("PARAMS_STACK_KEYS")
            sys.exit(0)
        if use_prev:
            if has_value and raw_value != "":
                print("PARAMS_VALUE_%s" % key)
                sys.exit(0)
        else:
            if not has_value:
                print("PARAMS_VALUE_%s" % key)
                sys.exit(0)
            if raw_value != live_expect:
                print("PARAMS_VALUE_%s" % key)
                sys.exit(0)
if seen_params != want_keys:
    print("PARAMS_INCOMPLETE")
    sys.exit(0)
tags = first.get("Tags", None)
if not isinstance(tags, list):
    print("TAGS_MISSING")
    sys.exit(0)
pairs = set()
for item in tags:
    if not isinstance(item, dict):
        print("TAGS_MALFORMED")
        sys.exit(0)
    pairs.add(((item.get("Key", "") or ""), (item.get("Value", "") or "")))
if pairs != {("Project", "LaunchCrew"), ("Environment", "demo")}:
    print("TAGS_MISMATCH")
    sys.exit(0)
caps = first.get("Capabilities", None)
if not isinstance(caps, list) or "CAPABILITY_NAMED_IAM" not in caps:
    print("CAPABILITIES")
    sys.exit(0)
print("OK")
print("ID\t%s" % cs_id)
PYEOF
)" || QUIESCE_RAW="UNREADABLE"
    QUIESCE_REVIEW="$(printf '%s\n' "$QUIESCE_RAW" | head -n 1 | tr -d '[:space:]')"
    if [ "$QUIESCE_REVIEW" != "OK" ]; then
      rm -rf "$QUIESCE_PAGES_DIR"
      rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON" "$QUIESCE_STACK_JSON"
      echo "refused: quiesce change set proof is $QUIESCE_REVIEW, expected only ApiService and WebService DesiredCount to 0 with no replacement and no other property, tag, or resource change. Pending change set $QUIESCE_CHANGESET preserved for inspection, no execute made, no delete made." >&2
      phase_failed quiesce
    fi
    QUIESCE_CHANGESET_ID="$(printf '%s\n' "$QUIESCE_RAW" | awk -F'\t' '$1=="ID"{print $2}')"
    QUIESCE_CHANGESET_ID="$(printf '%s' "$QUIESCE_CHANGESET_ID" | tr -d '[:space:]')"
    rm -rf "$QUIESCE_PAGES_DIR"
    rm -f "$QUIESCE_STACK_JSON"
    [ -n "$QUIESCE_CHANGESET_ID" ] || { rm -f "$QUIESCE_OLD_API_JSON" "$QUIESCE_OLD_WEB_JSON"; echo "refused: quiesce reviewed change set ID missing, no execute made." >&2; phase_failed quiesce; }
    if [ "$QUIESCE_RESUMED" -eq 1 ]; then
      echo "Quiesce: resuming existing exact same-name change set $QUIESCE_CHANGESET with reviewed ID after read-only identity, status, stack, parameter, tag, and diff proof."
    fi
    echo "Quiesce change set reviewed: only ApiService and WebService DesiredCount to 0 with no replacement, same change set ID executes next."
    if ! "$AWS_BIN" cloudformation execute-change-set --stack-name "$STACK_NAME" --change-set-name "$QUIESCE_CHANGESET_ID" --region "$EXPECTED_REGION" >/dev/null 2>"$TMP_ERR"; then
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
    QUIESCE_TAGS_JSON="$(mktemp /tmp/launchcrew-quiesce-tags-XXXXXX)"
    if ! "$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$EXPECTED_REGION" --output json >"$QUIESCE_TAGS_JSON" 2>"$TMP_ERR"; then
      rm -f "$QUIESCE_TAGS_JSON"
      echo "refused: quiesce stack tags unreadable after update" >&2; phase_failed quiesce
    fi
    QUIESCE_TAGS_PROOF="$(python3 - "$QUIESCE_TAGS_JSON" 2>/dev/null <<'PYEOF'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print("MALFORMED")
    sys.exit(0)
stacks = doc.get("Stacks", None)
if not isinstance(stacks, list) or len(stacks) != 1:
    print("MALFORMED")
    sys.exit(0)
tags = stacks[0].get("Tags", None)
if not isinstance(tags, list):
    print("MALFORMED")
    sys.exit(0)
pairs = set()
for item in tags:
    if not isinstance(item, dict):
        print("MALFORMED")
        sys.exit(0)
    pairs.add(((item.get("Key", "") or ""), (item.get("Value", "") or "")))
print("OK" if pairs == {("Project", "LaunchCrew"), ("Environment", "demo")} else "TAGS_MISMATCH")
PYEOF
)" || { rm -f "$QUIESCE_TAGS_JSON"; echo "refused: quiesce stack tags unreadable after update" >&2; phase_failed quiesce; }
    rm -f "$QUIESCE_TAGS_JSON"
    QUIESCE_TAGS_PROOF="$(printf '%s' "$QUIESCE_TAGS_PROOF" | tr -d '[:space:]')"
    if [ "$QUIESCE_TAGS_PROOF" != "OK" ]; then
      echo "refused: quiesce stack tags proof is $QUIESCE_TAGS_PROOF, expected exact Project LaunchCrew plus Environment demo" >&2; phase_failed quiesce
    fi
    echo "Verified quiesce tags: exact Project LaunchCrew plus Environment demo preserved"
    verify_target_group_drained ApiTargetGroup api
    verify_target_group_drained WebTargetGroup web
    mark_done quiesce
    echo "Phase quiesce complete: stack UPDATE_COMPLETE, both services 0/0/0, old images preserved, target groups drained. Foundation and prereqs untouched."
  fi
fi

echo "BOOTSTRAP COMPLETE phases requested: $PHASE. Completed: ${COMPLETED:-none}."
echo "Outside-stack remaining work: secret values, ACM certificate, DNS, snapshots need separate approval with exact identifiers."
