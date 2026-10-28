# LaunchCrew demo approval pack, isolated KoruShield demo

Status: review only. No AWS account access, no apply, no DNS, no secret, no
paid resource, no deployment. This pack authorizes nothing; provisioning and
any DNS record each need a separate Summit authorization tap after this pack
is reviewed. Every figure below is a cached estimate that the orchestrator
must refresh from current AWS pricing before approval. Nothing here is a hard
spend cap: AWS Budgets send alerts only and cannot enforce spending.

## Proposed deployment

- Public base: https://launchcrew.summitsingh.com (DNS record NOT created by
  this pack; Cloudflare record needs a separate explicit authorization, and
  the template outputs only the ALB DNS name).
- Region: us-east-1, recommended, NOT confirmed. The template region is the
  deployment region at apply time, not an approval in this file.
- Window: live for the Nov 4 event, teardown required after Nov 4 and no
  later than Nov 9, 2026, via deploy/aws/teardown.sh.
- Access profile, recommended: keyless synthetic public demo. AUTH_ENABLED
  stays false, no Meta key is deployed, global SAM stays 0, and no paid
  inference path is reachable anonymously. Existing Google and Facebook auth
  plumbing is not live verified and stays out of this deployment. Demo data
  is synthetic only. If Summit wants a gate instead of open keyless access,
  the fallback is Cloudflare Access in front of the same origin, decided at
  the authorization tap, not silently added later.

## Fixed resource counts (source of truth: deploy/aws/fargate.yaml)

- ECS services: 2 (api, web), fixed DesiredCount 1 each, no autoscaling
  resource, no scaling policy. Default EnableServices=false keeps both at 0
  until images, role binding, and migration are proven.
- Task sizes: api 0.25 vCPU / 0.5 GB, web 0.25 vCPU / 0.5 GB
  (total constant 0.5 vCPU / 1 GB). One-off tasks (bootstrap, migration,
  verify) are 0.25 vCPU / 0.5 GB each and run for minutes only.
- RDS: private db.t4g.micro, 20 GB gp3, single AZ, no public port,
  storage encrypted, 1-day backup retention, deletion without a retained
  final snapshot (DeleteAutomatedBackups true, DeletionProtection false).
- ALB: internet-facing across 2 AZ, HTTPS 443 only plus HTTP to HTTPS
  redirect; API target HTTPS 8443 with /api/health, web target HTTPS 8443
  with / listening on the web TLS sidecar, never the plain app port.
- Network: 2 public subnets for service tasks, ALB, and one-off job tasks;
  2 private subnets for RDS. Tasks carry public IPs (no NAT gateway, no
  VPC endpoints). One-off jobs run in the public subnets with a public IP
  under an isolated group with no inbound rules at all, so they can reach
  ECR, Secrets Manager, and Logs; this is the honest minimal egress path,
  because the private subnets have no NAT and no endpoints. The database
  stays private: the job group may reach only Postgres on the database
  group plus HTTPS egress, and RDS is never public. Baseline IPv4 is 4
  addresses (2 ALB + 2 service task); each running one-off job temporarily
  holds one more address for its minutes of runtime.
- ECR: 5 repositories (api, web, web-proxy, migration, bootstrap), scan on
  push, emptied and deleted on stack delete.
- Secrets: 4 outside-stack Secrets Manager values (runtime DB URL, migration
  DB URL, TLS material, master password). Contents are never in the repo,
  never in an image, never logged.
- Logs: 7-day retention on api, web, and migration/bootstrap log groups
  before services start. No request bodies, headers, or secrets are logged.

## Cached estimate (must be refreshed before approval)

Sources, cached reference only: ../.local/aws-rds-us-east-1-prices.json
(Oct 26 publication) and ../.local/aws-ecs-us-east-1-prices.json (Oct 19
publication), plus the public AWS pricing pages for ALB, VPC IPv4, ECR,
Secrets Manager, CloudWatch Logs, and T4g unlimited. Rates used:

- Fargate x86 0.04048 per vCPU hour + 0.004445 per GB hour
- RDS db.t4g.micro 0.016 per hour, gp3 0.115 per GB month
- ALB 0.0225 per hour + 0.008 per LCU hour (assumes constant 1 LCU)
- Public IPv4 0.005 per address hour, 4 addresses
- Secrets Manager 0.40 per secret month + 0.05 per 10k API calls
- ECR 0.10 per GB month, assumes about 2.5 GB across 5 images
- CloudWatch Logs 0.50 per GB ingested + 0.03 per GB month stored
- T4g unlimited 0.075 per vCPU hour, only if the micro bursts past baseline
- 730-hour month proration. No free tier assumed. No credits assumed.

| Line item | 7-day demo (168 h) | 12-day window incl. teardown lag (288 h) |
| --- | --- | --- |
| Fargate constant 0.5 vCPU / 1 GB | 4.15 | 7.11 |
| RDS db.t4g.micro | 2.69 | 4.61 |
| RDS storage 20 GB gp3 | 0.53 | 0.91 |
| ALB hourly | 3.78 | 6.48 |
| ALB LCU, 1 constant | 1.34 | 2.30 |
| IPv4, 4 addresses | 3.36 | 5.76 |
| Secrets, 4 | 0.37 | 0.63 |
| ECR, about 2.5 GB | 0.06 | 0.10 |
| Logs, variable, assumes about 0.5 GB ingest | 0.25 | 0.25 |
| Subtotal | 16.53 | 28.15 |

One-off overlap, estimated not capped: bootstrap, migration, and verify
one-off jobs each run minutes at 0.25 vCPU / 0.5 GB, about 0.00021 per
task minute at the rates above, so a clean run is a few cents. Failed jobs,
pre-warming, and enable retries each add more task minutes linearly; there
is no code bound on retries, so no total under 0.10 is guaranteed. Image
builds run on the existing Linux CI with podman-local.sh build covering all
six images (db, api, migrate, web, web-proxy, bootstrap), no Fargate build
cost. CI does not publish to ECR: publication is a separate authorized push
of the exact built digests (see deploy/aws/README.md), and bootstrap phase
3 refuses any image that is not in the owned repository.

Variable limits and buffer: traffic beyond 1 LCU, log volume beyond 0.5 GB,
cross-AZ data transfer, T4g unlimited credits (up to 0.15 per hour for 2
vCPUs if the demo bursts past baseline), and delayed teardown all add cost
above the subtotal. Teardown itself bills until each resource deletes; the
7-day log groups and any manual snapshot keep storage charges until their
retention expires, and secrets bill until deleted outside the stack.
Recommended Summit alert threshold: 45 USD monthly budget to cover the
12-day window plus teardown lag and traffic variance. 45 is a notification
threshold, never an enforced hard cap: the budget sends an 80 percent
actual alert and a 100 percent forecast alert to the owner email, and
nothing stops spending. Cost assumptions added by this revision: no VPC
endpoints are used (each interface endpoint would add hourly plus per-GB
charges), SNS email delivery is assumed within the free tier, and log
ingest beyond 0.5 GB, traffic beyond 1 LCU, and cross-AZ transfer bill
above the subtotal.

## Owner contact and alerts

BudgetNotifyEmail is a template parameter with an empty default, supplied
privately at deploy review and never committed with a real address. When
filled, the stack creates an SNS topic plus one email subscription and the
DemoBudget notifies that topic at 80 percent actual and 100 percent
forecasted spend. The topic carries a topic policy that allows Publish only
from budgets.amazonaws.com scoped to this account and this budget; without
that policy the budget cannot deliver. When empty, no subscription is
created and the budget has no subscribers. Email delivery is not ready on
apply: the subscription stays PendingConfirmation until the owner clicks
the confirmation link, and no alert arrives before that. Readiness means a
confirmed subscription, verified after apply. No message or subscription is
created by reviewing this source; the subscription exists only after an
authorized stack apply.

## Explicit expiration, teardown, and access boundary

- Teardown is required after Nov 4 and no later than Nov 9, 2026, with
  deploy/aws/teardown.sh against the exact stack ARN plus expected account
  and region, after caller and tag verification. It deletes only the stack.
- Outside-stack cleanup needs a separate approval with exact identifiers:
  the 4 Secrets Manager values, the ACM certificate, the Cloudflare DNS
  record if created, and any manual snapshot. None are deleted by teardown.
- Access boundary: the demo account holds only this stack. No KoruShield
  production data, credentials, roles, databases, or policies are shared.
  Human credentials stay outside the repository and images.

## Gates the orchestrator must clear at the authorization tap

1. Refresh every cached figure above against current pricing and confirm
   the region is us-east-1 or record the confirmed region.
2. Summit fills BudgetLimitUsd (recommended 45) and BudgetNotifyEmail.
3. Separate explicit authorization for the Cloudflare DNS record.
4. Images built from containers/*.Containerfile on Linux CI
   (podman-local.sh build covers db, api, migrate, web, web-proxy, and
   bootstrap) and published to the owned ECR repositories by a separate
   authorized push of the exact built digests; no placeholder image boots
   the app (enforced by bootstrap phase 3, which also refuses images whose
   digest, failures, or task definition reference do not match).
5. Staged bootstrap via deploy/aws/bootstrap.sh: infra at DesiredCount 0
   on a fresh stack (owned updates preserve the current true value so
   running services are not reset), verified images by digest and task
   definition reference with owned secret and execution role bindings,
   bootstrap role binding STOPPED exit 0, migration
   STOPPED exit 0 with verify-mode proof from the separate verify task
   definition, then enable re-proving images, bindings, and the verify
   proof from live state before updating to fixed 1 each with desired and
   running counts read back (configuration check; serving health needs
   ALB targets after DNS, which this script never claims).
6. Live verification only after that tap: WEB 200, API 200 through the
   public base, HTTPS chain and container TLS hop, database verify-full,
   and keyless synthetic behavior with no paid inference reachable.
