# LaunchCrew demo approval pack, isolated KoruShield demo

Status: review only, refreshed Oct 28, 2026. No AWS account access, no
apply, no DNS, no secret, no paid resource, no deployment. No Cloud API
command is run from any CLI to prepare this pack, and cloud credential
availability plus account read-only validation itself is still gated.
This pack authorizes nothing; provisioning and any DNS record each need a
separate user authorization tap after this pack is reviewed. Every figure
below is recomputed from primary public price evidence read Oct 28, 2026
(Codex read-only, no AWS account), not copied from a fake total. Nothing
here is a hard spend cap: AWS Budgets send alerts only and cannot enforce
spending. No contributor or team email and no registration status are
invented anywhere in this pack.

## Proposed deployment

- Public base: https://launchcrew.summitsingh.com (DNS record NOT created by
  this pack; Cloudflare record needs a separate explicit authorization, and
  the template outputs only the ALB DNS name).
- Region: us-east-1, recommended, NOT confirmed. The template region is the
  deployment region at apply time, not an approval in this file.
- Window: live for the Nov 4 event, teardown required after Nov 4 and no
  later than Nov 9, 2026, via deploy/aws/teardown.sh.
- Access profile, recommended: keyless synthetic public demo. AUTH_ENABLED
  stays false, no Meta key is deployed, paid Meta stays OFF, global SAM
  stays 0, and no paid inference path is reachable anonymously. Existing
  Google and Facebook auth plumbing is not live verified and stays out of
  this deployment. Demo data is synthetic only. If the user wants a gate
  instead of open keyless access, the fallback is Cloudflare Access in
  front of the same origin, decided at the authorization tap, not silently
  added later.

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

## Refreshed estimate, Oct 28, 2026 (primary public evidence, read-only)

Sources, all read Oct 28, 2026 with no AWS account and no network calls
beyond the reads named here. TLS-verified JSON downloads:
`../.local/aws-rds-us-east-1-oct28-refresh.json` (publication
2026-10-26T21:47:16Z, from
https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/us-east-1/index.json)
showing actual InstanceUsage db.t4g.micro PostgreSQL SingleAZ 0.016/hr and
RDS GP3-Storage for PostgreSQL 0.115/GB-month; do not pick UnusedBox or
MultiAZ rates.
`../.local/aws-ecs-us-east-1-oct28-refresh.json` (publication
2026-10-19T22:43:17Z, from
https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/us-east-1/index.json)
with USE1-Fargate-vCPU-Hours:perCPU 0.04048/hr and USE1-Fargate-GB-Hours
0.004445/hr, linux x86. Public primary pages checked Oct 28:
https://aws.amazon.com/elasticloadbalancing/pricing/ (ALB example
N. Virginia 0.0225/hr + 0.008/LCU-hr),
https://aws.amazon.com/vpc/pricing/ (both in-use and idle public IPv4
0.005/IP-hr),
https://aws.amazon.com/secrets-manager/pricing/ (0.40/secret-month +
0.05/10k API),
https://aws.amazon.com/ecr/pricing/ (0.10/GB-month),
https://aws.amazon.com/cloudwatch/pricing/ (Standard ingest 0.50/GB,
archived 0.03/GB-month, NO assumed free credits),
https://aws.amazon.com/rds/postgresql/pricing/ (T4g Unlimited 0.075/vCPU-hr
above baseline). SNS: https://aws.amazon.com/sns/pricing/ shows dynamic
email rates NOT retrievable in web text; fresh public regional and global
SNS JSON (`../.local/aws-sns-us-east-1-oct28-refresh.json`,
`../.local/aws-sns-global-oct28-refresh.json`, publication
2026-09-15T15:19:44Z) shows standard requests Tier 1 free first 1M then
0.50 per 1M thereafter, but the EMAIL delivery rate could NOT be resolved.
Do NOT assume free-tier eligibility or email free. SNS delivery stays
unpriced and excluded, pending the exact rate; this is a coverage gap, not
absence of charge. No free-tier eligibility is assumed anywhere. No
credits assumed. No further network calls are made from this pack.

Rates used (recomputed from the rates above, not copied from a total):

- Fargate x86 0.04048 per vCPU hour + 0.004445 per GB hour
- RDS db.t4g.micro 0.016 per hour, gp3 0.115 per GB month
- ALB 0.0225 per hour + 0.008 per LCU hour (assumes constant 1 LCU)
- Public IPv4 0.005 per address hour, 4 addresses
- Secrets Manager 0.40 per secret month + 0.05 per 10k API calls
- ECR 0.10 per GB month, assumes about 2.5 GB across 5 images
- CloudWatch Logs 0.50 per GB ingested + 0.03 per GB month stored
- T4g unlimited 0.075 per vCPU hour, only if the micro bursts past baseline
- 730-hour month proration

Assumptions, all conservative: 2 constant tasks total 0.5 vCPU / 1 GB,
PG micro 20 GB, ALB 1 constant LCU, 4 baseline IPs, 4 secrets, 2.5 GB ECR,
0.5 GB log ingest + 0.5 GB log storage for the full period (conservative).

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
| Logs, 0.5 GB ingest + 0.5 GB storage | 0.25 | 0.26 |
| Subtotal | 16.53 | 28.15 |

Exact subtotal 7 days: 16.52760055, shown as 16.53. Exact subtotal
12 days: 28.15445808, shown as 28.15. Line items round; the rounded rows
can differ from a sum of rounded rows, so full precision above governs.

One-off overlap, estimated not capped: bootstrap, migration, and verify
one-off jobs each run minutes at 0.25 vCPU / 0.5 GB. Compute is
0.0002057083/min plus one public IP 0.0000833333/min, total
0.0002890417/min before logs and other charges, so a clean run is a few
cents but NOT under 0.10 guaranteed, with no retry bound. Failed jobs,
pre-warming, and enable retries each add more task minutes linearly; there
is no code bound on retries. Image builds run on the existing Linux CI
with podman-local.sh build covering all six images (db, api, migrate, web,
web-proxy, bootstrap), no Fargate build cost. CI does not publish to ECR:
publication is a separate authorized push of the exact built digests (see
deploy/aws/README.md), and bootstrap phase 3 refuses any image that is not
in the owned repository.

Variable limits and buffer: actual service cost begins when infra, RDS, or
ALB are created, even at DesiredCount 0, not only during enabled time.
Traffic beyond 1 LCU, log volume beyond 0.5 GB, cross-AZ data transfer,
T4g unlimited credits (up to 0.15 per hour for 2 vCPUs if the demo bursts
past baseline), and delayed teardown all add cost above the subtotal.
Teardown itself bills until each resource deletes; the 7-day log groups
and any manual snapshot keep storage charges until their retention
expires, and secrets bill until deleted outside the stack. No new VPC
endpoint and no NAT are used (each interface endpoint would add hourly
plus per-GB charges). Recommended user alert threshold: 45 USD monthly
budget to cover the 12-day window plus teardown lag and traffic variance.
45 is a notification threshold, never an enforced hard cap: the budget
sends an 80 percent actual alert and a 100 percent forecast alert to the
owner email, and nothing stops spending. Automatic teardown is NOT
configured and there is no hard stop. SNS email delivery needs a
conservative explicit planning allowance if chosen, NOT a verified quote.

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
  Automatic teardown is NOT configured; expiry is a stop criterion, not a
  hard stop, and residual billing risk runs until every resource and every
  outside-stack item below is actually deleted.
- Outside-stack cleanup needs a separate approval with exact identifiers:
  the 4 Secrets Manager values, the ACM certificate, the Cloudflare DNS
  record if created, and any manual snapshot. None are deleted by teardown.
  The 4 outside-stack secrets plus ACM and DNS inputs stay privately gated;
  no actual identifiers are invented in this pack.
- Access boundary: the user asked for isolated KoruShield resources. The
  exact stack NAME in this pack is a proposal, NOT an existing stack ID,
  and account identity is UNVERIFIED: this pack distinguishes an isolated
  ACCOUNT from a separate STACK in the same existing account, and does NOT
  claim the account is empty or that unrelated production never existed,
  because no actual inventory was performed. Same-account CostFilters are
  absent, so an AWS Budget MONTHLY aggregate may cover other account costs.
  Human credentials stay outside the repository and images.

## Gates the user must clear at the authorization tap

No generic TBD approval is asked here; each gate below names its exact
owner and evidence. Cloud credential availability and account read-only
validation itself is still gated, and no Cloud API command runs in any CLI
before that tap.

1. Figures above are already refreshed Oct 28, 2026 from primary evidence;
   at the tap, confirm the region is us-east-1 or record the confirmed
   region, with no new figure assumed.
2. User fills BudgetLimitUsd (recommended 45) and BudgetNotifyEmail.
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
