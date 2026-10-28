#!/bin/sh
# LaunchCrew demo teardown plan, dry-run by default.
# No AWS call is made in dry-run mode. With --confirm, and only after
# a separate teardown authorization, this script would call AWS CLI
# commands in reverse dependency order. Do not run --confirm here,
# and do not run it against any account without that authorization.
# Teardown is required after Nov 4 and no later than Nov 9, 2026.
# Order: services, listeners, target groups, ALB, task definitions,
# cluster, RDS and snapshots, ECR images, log groups, IAM roles,
# VPC and subnets, budget, Cloudflare record only if created,
# then verification of no recurring charges.
set -eu
STACK_NAME="${STACK_NAME:-launchcrew-demo}"
REGION="${AWS_REGION:-us-east-1}"
if [ "${1:-}" != "--confirm" ]; then
  echo "DRY RUN, no AWS call made."
  echo "Stack: $STACK_NAME, region: $REGION, recommended, not confirmed."
  echo "1. Stop ECS services api and web, DesiredCount 0, wait for tasks to stop."
  echo "2. Delete ALB listeners, target groups, then ALB."
  echo "3. Deregister ECS task definitions api, web, migration."
  echo "4. Delete ECS cluster."
  echo "5. Delete RDS instance and all snapshots, verify no snapshot remains."
  echo "6. Delete ECR images in launchcrew-api, launchcrew-web, launchcrew-migration, then delete repos."
  echo "7. Delete CloudWatch log groups /launchcrew/demo/api, /web, /migration."
  echo "8. Delete IAM roles execution, api, web, migration, after dependencies are removed."
  echo "9. Delete VPC, subnets, route tables, internet gateway."
  echo "10. Delete AWS Budget launchcrew-demo."
  echo "11. Delete Cloudflare record for launchcrew.summitsingh.com, only if created in a later authorized run."
  echo "12. Verify: endpoint unavailable, DNS removed if applicable, no snapshots, images, logs, secrets, certificates, NAT gateways, public IPv4 addresses, or budgets remain, and report actual cost, without secrets."
  echo "To run for real, after separate authorization: $0 --confirm"
  exit 0
fi
echo "CONFIRM MODE requested. This mode is not authorized in this preparation run."
echo "Stop here unless a separate teardown authorization has been given for stack $STACK_NAME in region $REGION."
exit 1
