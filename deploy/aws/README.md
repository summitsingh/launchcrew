# LaunchCrew AWS deployment code, review only, not applied

Status: Code review only. No AWS account access, no apply, no IAM change, no DNS, no secret, no paid resource, no deployment. This directory is in a separate deployment-code worktree, based on main 4bb295d, and it does not touch the integration owner checkout or main.

## What this code does, and what it does not do

Implemented in code, reviewable here:
- Separate migration job: containers/api.Containerfile no longer runs alembic at runtime startup. Runtime CMD is uvicorn only, through containers/api-entrypoint.sh. Migration is a separate image, containers/migrate.Containerfile, CMD alembic upgrade head only, no server, for a separate Fargate one-off task, with its own IAM migration role in deploy/aws/fargate.yaml. Runtime database identities have no DDL in the template, migration is the only schema change path.
- TLS-capable API container target: containers/api-entrypoint.sh serves TLS on port 8443 when TLS_CERT_FILE and TLS_KEY_FILE are present, mounted at task start from Secrets Manager, never baked into the image, never logged. If LAUNCHCREW_REQUIRE_CONTAINER_TLS=1, set in the Fargate API task definition, and either file is missing, the task fails closed, exit 1, instead of starting plain HTTP. If only one file is set, exit 1. Plain HTTP on port 8000 is local development only, and must never be used for a public deployment.
- Verified database TLS: backend/store.py enforces, for any non-local Postgres URL, sslmode=verify-full in DATABASE_URL, which verifies both certificate chain and hostname. sslmode=require, prefer, or disable are rejected. Local URLs, localhost or 127.0.0.1, are exempt, for local development and isolated test clusters only, and must never be used for a deployment. DATABASE_SSL_ROOTCERT, if set, is passed as sslrootcert, with no value logged. This enforcement applies to both API and migration connections, because backend/migrations/env.py shares the backend SQLAlchemy engine.
- Fixed task counts: deploy/aws/fargate.yaml sets DesiredCount 1 for api and web, with no autoscaling resource, no AutoScaling policy, and no scaling target. Any scaling change requires a template change and a new review, it cannot happen by default.
- Log retention: 7 days, set in the template for api, web, and migration log groups, before services start, per the bounded logs requirement. No request bodies, headers, or secrets are logged by this code, and that rule must be checked in application code before deployment.
- Resource tags: Project LaunchCrew, Environment demo, TeardownBy 2026-11-09, on VPC, subnets, ECR repos, RDS, cluster, and ALB, in the template. Tags are not a cost cap, they are an inventory and teardown aid.
- Teardown plan in code: deploy/aws/teardown.sh, dry-run by default, prints deletion steps in reverse dependency order, with no AWS call in dry-run mode, and requires an explicit --confirm flag before any AWS call. Teardown order: services, listeners, target groups, ALB, task definitions, cluster, RDS and snapshots, ECR images, log groups, IAM roles, VPC and subnets, budget, then Cloudflare record, only if created, then verification of no recurring charges. Teardown is required after Nov 4 and no later than Nov 9, 2026.

## Remaining gap, stated plainly, not hidden

Web container target TLS is NOT implemented in code here. Next.js standalone server.js serves HTTP only, and a custom TLS Next server was not built and tested in this work, because building it without a verified standalone TLS run would be a fake implementation. The template therefore uses a fail-closed gate: WebTlsReady parameter AllowedValues is ['true'] only, so any other value fails template validation, and the web target group is HTTPS on port 8443, so provisioning with a plain HTTP web image will fail health checks, not silently succeed as HTTP. Before provisioning, a TLS-capable web image must be built, with a custom Next https server, tested locally with ephemeral self-signed certificates, and WebTlsReady must be set to true with evidence. Until then, web target TLS is a remaining code gap, and deployment must not be approved as meeting strict HTTPS to the web container target. API target TLS is implemented, web target TLS is not, and those two statements must not be conflated.

## Inputs, explicit and unapproved

- Region: us-east-1, recommended, NOT confirmed, nothing provisioned in it. The template region is the deployment region at apply time, it is not a default approval in this file.
- Domain: launchcrew.summitsingh.com, parameter DomainName, no default, Cloudflare record requires separate explicit authorization, no DNS record is created by this code.
- Certificate: ACM certificate ARN, parameter AcmCertificateArn, no default, no certificate value in this file.
- Image URIs: ApiImageUri, WebImageUri, MigrationImageUri, parameters, no default, images must be built from the Containerfiles in this worktree, with no key, .env, credential, or receipt history in the image, run as non-root.
- Database password: secret ARN only, parameter DatabasePasswordSecretArn, no value in this file, placeholder only. Runtime and migration roles read only their own secret, web role has no database or provider-secret access, with an empty policy list in the template.
- Cost cap and budget: BudgetLimitUsd, parameter, no approved default, no amount is implied here. A spending cap is a user choice after seeing the estimate, in the AWS deployment proposal, recommended Fargate $17.10 for 7 days, $28.57 for 12 days, App Runner revised with NAT egress $19.51 for 7 days, $32.69 for 12 days. A value of 0 in a parameters file is a placeholder that must be replaced, it is not an approval.
- Auth: AUTH_ENABLED is false in the template API task definition, matching the current code default, health auth disabled_demo, approval_by demo_placeholder. Real sign-in is a separate gate, with provider credentials supplied securely outside the repo, and HTTPS callback URLs, and it is not claimed as live here.

## What requires real cloud verification, and cannot be proven statically or locally

- CloudFormation template validation and apply, in a real account, with real parameters, after a separate deployment tap and a filled cost cap.
- ALB HTTPS listener with a real ACM certificate, Cloudflare Full strict origin verification, custom domain verification, and certificate renewal.
- ALB HTTPS target groups, with API TLS on 8443 verified by health checks, and web TLS on 8443 verified only after a TLS-capable web image is built and tested.
- RDS private connectivity, no public port, database TLS verify-full from both API and migration tasks, with a real RDS CA bundle, and rejection of an invalid certificate, which cannot be proven with a local trust-auth database.
- Separate migration execution, with the migration IAM role, before runtime tasks start, and runtime tasks starting without migration rights, in a real VPC.
- ECR image pull, Fargate task start, log group retention, budget alarm, and teardown deletion, with actual resource identifiers and actual cost, reported before provisioning, after provisioning, and after teardown, without secrets.
- Real identity-provider sign-in, session behavior, and public access boundary, only in a separately authorized deployment.
- NAT egress, if the App Runner alternative is ever revisited: App Runner VPC-connected services lose public internet egress, and require a NAT Gateway in private connector subnets, per AWS App Runner docs, with revised costs above. This Fargate template does not use App Runner, and Fargate tasks in public subnets with a public IP reach the internet through the internet gateway, with no NAT required, but that must still be verified in a real VPC run.

## Local validation, ephemeral fixtures only

- Static: YAML parse of deploy/aws/fargate.yaml, shell syntax check of containers/api-entrypoint.sh and deploy/aws/teardown.sh, node syntax check if a web TLS server is added later, repo scan, diff check, no secrets.
- Local, ephemeral: api entrypoint dry-run with and without TLS files, with LAUNCHCREW_REQUIRE_CONTAINER_TLS=1, verifying fail-closed exit 1 when files are missing, TLS command on 8443 when files are present, and plain 8000 only when TLS is not required. Self-signed certificates, if used for a local TLS test, must be generated in /tmp, used only for that test, and deleted after, never committed, never used for deployment.
- Database TLS unit logic: backend/store.py engine creation only, no database connection, with ephemeral DATABASE_URL values, verifying non-local without sslmode=verify-full raises, non-local with sslmode=require, prefer, or disable raises, local localhost passes, and non-local with sslmode=verify-full passes, with no secret value in the test output.
- No AWS account access, no apply, no IAM change, no DNS, no secret retrieval, no paid resource, no deployment was performed for this local validation.
