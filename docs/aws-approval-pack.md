# LaunchCrew demo approval pack, isolated KoruShield demo

Status: review only, refreshed Oct 28, 2026. No apply, no DNS, no secret,
no paid resource, no deployment from this pack. Read-only validation was
completed Oct 28, 2026 against us-east-1 with a limited inventory scope:
Active CloudFormation stacks 0, ACM certificates 0, ECS clusters 0, ECR
private repositories 0, Secrets Manager list 0 with no secret values
retrieved; two available VPCs seen (default 172.31/16 and one existing
nondefault 10.0.0.0/16) with no peering and no touch of existing
resources; public DNS nameservers are Cloudflare and the demo hostname
has no A, CNAME, or AAAA answer (NODATA or NOERROR), so it is not live
TLS; browser read access proof only, never permission to provision or
automate. No account ID, production names, resource names, spend amounts,
or private URLs appear in public source or docs. This pack authorizes
nothing; provisioning and any DNS record each need a separate user
authorization tap after this pack is reviewed. Every figure below is
recomputed from primary public price evidence read Oct 28, 2026
(Codex read-only, no AWS account), not copied from a fake total. Nothing
here is a hard spend cap: AWS Budgets send alerts only and cannot enforce
spending. No contributor or team email and no registration status are
invented anywhere in this pack. No active CloudFormation stack is not
proof of no resources globally.

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
- Network: fresh unpeered demo VPC 10.42.0.0/16, chosen to avoid the
  existing nondefault 10.0.0.0/16 range, with 2 public subnets
  (10.42.1.0/24, 10.42.2.0/24) for service tasks, ALB, and one-off job
  tasks, and 2 private subnets (10.42.11.0/24, 10.42.12.0/24) for RDS.
  Same AZ layout, masks, and security policy as the reviewed design,
  with no changes to existing networks, routes, or attachments, and no
  peering. Tasks carry public IPs (no NAT gateway, no VPC
  endpoints). One-off jobs run in the public subnets with a public IP
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

## Owner contact, project budget filter, and coverage limits

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

DemoBudget is Project scoped only: FilterExpression Tags Project
LaunchCrew with MatchOptions EQUALS, using the current official
FilterExpression and TagValues schema. Legacy CostFilters JSON is
deprecated and not used. This filter never counts the whole account, and
the old same-account 45 aggregate framing must not be reused as the demo
budget. Priced resources carry Project LaunchCrew tags (VPC, subnets,
security groups, ALB, target groups, ECS services with PropagateTags
SERVICE, ECS task definitions, ECR repositories, RDS, log groups, SNS
topic) where supported, and ECS tasks inherit service tags through
propagation. Coverage is not 100 percent and is stated plainly: public
IPv4, data transfer, SNS delivery, Secrets Manager API calls and staged
secret rotation, and any untagged or nontagging charges stay outside
tag-filtered coverage, so a manual billing guard stays on the operator and
no broad cloud platform monitoring is added here. There is no hard cap
anywhere in this design.

Budget tag readiness, current as of Oct 28, 2026: the Project key now reads Active. The earlier INACTIVE read-only Billing console check on Oct 28, 2026 (Project key exists as a user defined resource cost allocation tag with Status Inactive, no activation made) remains meaningful dated history and is now superseded. Human explicitly approved activation ONLY of the existing Project tag in KoruShield Billing; Codex used the AWS Console to select Project only, then Activate and confirm 1 tag. Saved status Active Oct 28, 2026 10:24 UTC-05, reloaded page and verified Project Active persists. Other tags untouched, no backfill, no resources deployed, no IAM change, no secret values, no credentials, no ECR push, no DNS, and no spending action. The screenshot stays private at `../.local/aws-project-tag-active.png`, and no screenshot or account, production, or cost data is published here. This is browser persisted proof only, with no new CLI or API permission proof. Cost data availability and hard cap are NEVER implied. This observed Active state must still be rechecked live with ce list-cost-allocation-tags before any future mutation, and future paid preflight must still read actual CE status. Allow about 24 hours for a new tag key to appear plus about 24 hours for activation as general timing context. A filter with no data or 0 is NOT proof of zero spend and NOT a hard cap. Source and bootstrap still fail closed on this point: an Inactive, absent, ambiguous, or unreadable Project key refuses every paid phase before any CloudFormation deploy or one-off task, and an unfiltered or inexact budget refuses enable. Monitoring is never claimed working before the operator preflight in deploy/aws/bootstrap.sh passes. Resource billing begins at infra, RDS, and ALB creation even with both ECS services at DesiredCount 0, and activating the shared PROJECT key changes global billing reporting, so deployment and spending approvals stay gated with no resources changed by the activation step. The approved Project activation is complete. Deployment and spending still require separate authorization. No broad cost estimate change is made here.

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
  exact stack NAME in this pack is a proposal, NOT an existing stack ID.
  Account identity was confirmed privately; no account ID appears here.
  This pack distinguishes an isolated ACCOUNT from a separate STACK in the
  same existing account, and does NOT claim the account is empty: the
  account is already in use, not fresh and empty, and unrelated spend
  already exists above the demo threshold, so the demo budget must stay
  Project filtered and must never reuse a same-account global aggregate.
  Human credentials stay outside the repository and images.
- Outside-stack inputs stay gated: the ACM certificate and the 4 Secrets
  Manager values (runtime DB URL, migration DB URL, TLS material, master
  password) are created only under a later explicit authorization, and
  domain DNS is still absent. Actual ACM and DNS validation, cloud IAM
  bindings, image publication, RDS master creation, and live TLS remain
  gated and are not proven by reviewing this source. Source eligibility is
  not cloud API permission proof, and recording and submission gates stay
  intact.

## Gates the user must clear at the authorization tap

No generic TBD question is asked here; each gate below names its exact
owner and evidence, for approval only after this pack is reviewed.

1. Figures above are already refreshed Oct 28, 2026 from primary evidence;
   at the tap, confirm the region is us-east-1 or record the confirmed
   region, with no new figure assumed.
2. User fills BudgetLimitUsd (recommended 45 monthly, Project filtered)
   and BudgetNotifyEmail. The separate billing approval to activate
   the Project key as a user defined resource cost allocation tag was granted and is now fulfilled: Project reads Active as of Oct 28, 2026 10:24 UTC-05, other tags untouched, no resources changed by that step. That activation was a Billing console step, never done by the template or script. General timing context is about 24 hours for key appearance plus about 24 hours for activation. Deployment and spending approvals still require separate authorization.
3. Separate explicit authorization for the Cloudflare DNS record, the ACM
   certificate, and the 4 Secrets Manager values; none are created by
   reviewing this source.
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
   definition, then enable runs the budget readiness preflight (refuses an
   unfiltered or inexact budget, requires the Project key to read back
   Active after the earlier paid-phase admission gate, never activates
   tags, never claims no data or 0 as zero spend) and re-proves images,
   bindings, and the verify
   proof from live state before updating to fixed 1 each with desired and
   running counts read back (configuration check; serving health needs
   ALB targets after DNS, which this script never claims).
6. Live verification only after that tap: WEB 200, API 200 through the
   public base, HTTPS chain and container TLS hop, database verify-full,
   and keyless synthetic behavior with no paid inference reachable.

## Offline checks added in this source pass, not run here

No test, build, network, or cloud call was run to prepare this source
change; the host runs verification after exit. This pass adds focused
offline checks that prove behavior through the fake-AWS harness and real
ipaddress arithmetic instead of mirroring implementation strings:
tests/test_vpc_cidr.py proves the demo VPC is exactly 10.42.0.0/16, all
four demo subnets sit inside it, demo ranges never overlap, none collides
with the observed generic 10.0.0.0/16 or 172.31.0.0/16 ranges, AZ order
pairs public with private, public IP policy matches subnet role, and the
DB subnet group uses private subnets only; tests/test_bootstrap.py gains
CostTagAdmissionTests (Inactive, absent, failed, duplicate, wrong-type,
and malformed CE states refuse every paid phase before any deploy or
one-off task, Active continues, the CE query is scoped to
Project/UserDefined in-region, and no call activates tags or carries
secret values) and BudgetFilterTests (only the exact Project LaunchCrew
EQUALS-only FilterExpression passes enable; unfiltered, wrong-tag,
multi-valued, broadened, Or-wrapped, legacy, malformed, and failed
readbacks refuse with no EnableServices deploy). No AWS API is used by
those checks. The shared PROJECT key activation stays a gated Billing
approval with no resources changed by it.
