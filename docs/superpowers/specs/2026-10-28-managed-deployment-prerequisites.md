# Managed deployment prerequisites design, source only

Status: user authorized deployment execution in AWS and Cloudflare DNS
plus local CLI install. This authoring terminal does source only. No
budget, SNS topic, subscription, secret, certificate, DNS record, task,
deploy, or paid action is created or run in this terminal. Codex
performs actual cloud and host verification and executes new paid cloud
actions after implementation is verified. Cloudflare CLI and DNS auth
are handled by Codex. This file holds no account ID, ARN, secret value,
passphrase, PEM, email, or registry URI. Budget 45 is a monthly ALERT
threshold, not a hard cap and not a billing stop. New app IAM roles,
Secrets, ACM, budget, DNS, and spend are authorized for later Codex
execution, not done now.

## Gap, stated plainly

The 61979 audit found a real gap: current scripts securely CONSUME
existing Secrets Manager JSONs plus ACM but have NO secure
fresh-account generation, population, or certificate ordering method.
Initial account inventory read 0 Secrets Manager metadata and 0 ACM
certificates with no values read. The consuming interfaces are real
and stay unchanged in shape:

- `deploy/aws/bootstrap.sh` ownership gates check secret metadata only
  through `describe-secret` and never call the read-value API
  (`check_secret_arn`, secret tag checks, parameters match).
- `deploy/aws/fargate.yaml` consumes four secret ARNs plus one ACM ARN
  as parameters: `MasterDbPasswordSecretArn` feeds RDS creation
  through a dynamic reference on JSON key `password`; task
  definitions select `database-url` for runtime and migration,
  `tls-cert-b64` and `tls-key-b64` for API and web proxy.
- `scripts/bootstrap_db_roles.py` consumes injected `MASTER_DB_PASSWORD`,
  `DB_HOST`, `RUNTIME_DB_URL`, and `MIGRATION_DB_URL` in task memory
  only, with strict effective-host parsing and verify-full TLS.

This missing path MUST be implemented and meaningfully host verified
before Codex executes paid cloud actions. Deployment is authorized and
execution follows verification. Manual plaintext passwords in argv or
files, and claims that fake AWS or loopback PG superuser proof means
cloud ready, are explicitly refused. The original full proposal,
deadline, demo, provider, contributors, and submission task are
retained. Working photo progress and product features are not rebuilt.

## Goals

1. Foundation alerts (Budget plus SNS topic, scoped topic policy, and
   exact confirmed email subscription) exist and are confirmed BEFORE
   the first paid app or prereq resource, with an exact endpoint plus
   protocol plus owned TopicARN plus confirmed SubscriptionArn gate.
2. AWS managed password generation for master, runtime, and migration
   JSON passwords with nonsecret username metadata plus a generated
   password key, and no plaintext password params, files, argv, or
   logs. TLS secret starts as empty metadata. All four secrets use a
   Retain lifecycle.
3. One newly requested EXPORTABLE public ACM certificate for the exact
   demo hostname, used for the public ALB listener AND the sidecar
   secret, with DNS validation as an explicit Codex handled operator
   step with a private receipt.
4. A private least privilege one-off init job plus a separate readonly
   verifier, sharing the bootstrap image, where init populates
   `database-url` values after the RDS endpoint is confirmed and
   exports real certificate material into the TLS secret, all in RAM
   with no provisioner PEM files, and the verifier proves readiness
   read-only with no Put or Export.
5. Deterministic idempotent writes with purpose plus ARN hash tokens
   and canonical stable payloads, honest concurrency and crash
   semantics with readback only, no automatic rotation and no
   automatic versions for drift, with an explicit later rotation gate.
6. A staged integrate order with concrete gates, ending in the existing
   enable proof, plus a planned teardown scope with Retain and 7 day
   recovery.

## Non goals

No broad rewrite of the guarded driver or lifecycle. No new NAT, no
new database, no Redis, no new service, no new ECR repo: the existing
bootstrap image serves the additional one-off init job and the separate
readonly verifier, so local images stay six and app ECR repos stay
five. The five publisher ECR permissions are already created under
human approval; the publisher role in `deploy/aws/publisher-role.yaml`
MUST NOT be expanded or changed, and no other cloud resources are
created in this terminal. Deployment is authorized for later Codex
execution after verification. No Cloudflare connector, no new API key,
and no DNS mutation in source; Cloudflare auth is handled by Codex. No
automatic rotation, no new S3, DynamoDB, or database. No provider
permission is implied by adding `.env` alone; no actual Meta or SAM
calls. Photo and product behavior stay untouched.

## D1. Foundation ownership: Budget plus SNS before anything paid

Source already carries Budget and SNS inside `deploy/aws/fargate.yaml`
(`DemoBudget`, `BudgetTopic`, `BudgetTopicPolicy`,
`BudgetEmailSubscription`). For a fresh unapplied app stack the
coherent ownership is a move, done atomically at integration time (see
the companion plan): a new `deploy/aws/foundation.yaml` owns those
four resources verbatim, and `deploy/aws/fargate.yaml` drops them.
The publisher IAM stack (`launchcrew-publisher`) is already applied
and stays unchanged.

Proposed foundation stack name: `launchcrew-foundation`. Exact
account (12 digits), region `us-east-1`, tags Project LaunchCrew and
Environment demo, and StackID ownership guards reuse the existing
driver pattern: caller identity match, stack tag match, StackId
account and region match, and read-only CE Project Active admission
through `ce list-cost-allocation-tags` with tag key Project and type
UserDefined, exactly like `check_cost_tag_activation`. Inactive,
absent, ambiguous, wrong-type, unreadable, or authorization-failed
states refuse before any paid phase.

SNS exact gate blocks paid Secrets and app stages until the approved
private address is proven confirmed on the owned topic. The concrete
gate lists subscriptions by owned TopicARN and requires exactly one
subscription with Endpoint equal to the approved private
BudgetNotifyEmail value supplied privately at deploy review, Protocol
exactly `email`, TopicArn equal to the owned TopicARN with account and
region owned, and SubscriptionArn a real owned ARN, not the literal
`PendingConfirmation` string. Empty notify email means no subscription
exists and paid stages refuse. Wrong recipient, wrong protocol, wrong
owner, unowned TopicARN, unconfirmed ARN, empty list, and duplicate or
ambiguous matches all refuse. Any confirmed subscription for a
different recipient or protocol is not proof. The user email stays
private, is never asked for again, never hardcoded in source, never
appears in public CI files or logs, and no actual subscription or
email is created in this terminal. Budget, Secrets, and ACM creation
are authorized for later Codex execution after verification, not done
now.

## D2. Managed secrets: generated passwords, empty TLS, same 4 ARNs

A new `deploy/aws/prereqs.yaml` defines exactly four
`AWS::SecretsManager::Secret` resources with owned tags and no
`SecretString` plaintext anywhere. Each secret carries
`DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`, because a
CloudFormation `Delete` policy on Secrets defaults to force delete
without recovery. Recovery uses a separately reviewed exact ARN
`DeleteSecret` with 7 day recovery, no force. See D7 and public facts
for the verified lifecycle.

- Master: `GenerateSecretString` with nonsecret `SecretStringTemplate`
  `{"username":"launchcrew_master"}` and `GenerateStringKey`
  `password`, per official CloudFormation template and key. Strong
  supported length and charset, chosen at implementation time within
  RDS password rules and URL safety after percent-encoding (concrete
  recommendation: length 32, exclude quote, at-sign, slash,
  backslash, and space). Consumed by the existing RDS dynamic
  reference; never read by runtime or migration tasks.
- Runtime and migration: same managed shape at creation, BEFORE the DB
  host exists, with nonsecret username metadata plus generated
  `password`. The `database-url` key is added ONLY later by the init
  job, preserving the generated password and username.
- TLS: BOTH `GenerateSecretString` and `SecretString` omitted, so
  CloudFormation creates EMPTY secret metadata as the placeholder.
  Material arrives ONLY through the init job export path.

Creation of generated secrets needs the `GetRandomPassword`
permission on the deploying identity; the driver documents and checks
this as a preflight shape, and a property update to any generation
property creates a NEW secret version, so the driver MUST guard owned
resume with no accidental rotation: after first create, the prereqs
phase never redeploys changed generation properties, and any drift
there fails closed instead of rotating.

Exactly four secret ARNs and JSON selectors stay compatible with the
current consumers: master key `password`; runtime and migration task
selectors `database-url`; TLS keys `tls-cert-b64` and `tls-key-b64`.
`bootstrap_db_roles.py` already receives `MASTER_DB_PASSWORD` plus
`DB_HOST`, so no fifth master URL secret is needed. The operator
holds only metadata ARN parameter files at mode 600; no SecretString
values and no root DB URL ever sit on the operator machine.

## D3. Deployable TLS: one exportable cert, explicit DNS gate

No local self-signed reuse and no verification bypasses. The design
uses ONE newly requested EXPORTABLE public ACM certificate for the
exact hostname `launchcrew.summitsingh.com` (no wildcard), used for
the public ALB HTTPS listener (`AcmCertificateArn`) AND for the
sidecar secret through export. CloudFormation requests it with
`CertificateExport` ENABLED in `deploy/aws/prereqs.yaml`; the host
static check confirms the exact property spelling against the template
reference at implementation time. No Route53 zone is assumed.

DNS validation stays an explicit operator step handled by Codex after
verification: source carries no Cloudflare connector, no new API key,
and no DNS mutation. Cloudflare CLI and DNS auth are handled by Codex.
The driver reads the public validation CNAME name and value from
`DomainValidationOptions`, writes a private operator DNS validation
receipt at mode 600 with bounded metadata and no secret values,
prints the public CNAME as an explicit operator step, then observes
with bounded polls. No account, ARN, email, or sensitive fields appear
in public CI files or logs from this receipt; the receipt stays
private. Non-Route53 DNS means the prereqs stack remains
`CREATE_IN_PROGRESS` until the operator adds the validation CNAME;
that state is EXPECTED, not failure, and explicit staged pending
metadata is necessary. The driver derives the certificate and secret
metadata ARNs through exact owned `describe-stack-resource` calls by
logical ID while pending, and MUST NOT interpret a broad
`ValidationError` or 0 metadata as absence or as issuance. Only exact
API errors count: absent means the exact not found shape with the
exact stack name, auth means the exact auth substrings, all else fails
closed.

Before any private job, export, or app stage, the driver requires the
real ACM state: `describe-certificate` Status `ISSUED`, DomainName
exactly `launchcrew.summitsingh.com`, ARN account and region owned,
and owned tags. Source order respects Budget confirmed before charged
certificate issuance and before the four Secrets are created.

Honest platform boundary, kept even with the new valid cert: ALB
HTTPS connections to TARGETS do not validate backend certificates,
per the ALB target group routing reference. Nothing here claims ALB
peer identity verification or mTLS. The exportable cert is chosen to
avoid self-signed deployment credential reuse, not because the ALB
would verify it. Valid public frontend ACM TLS plus RDS verify-full
stay intact, with no TLS off switch and no browser warning bypass
anywhere.

## D4. Private init job and readonly verifier: reused image, narrow task roles, real SDK

The existing bootstrap image (built from
`containers/bootstrap-db.Containerfile`) serves the additional one-off
init job and the separate readonly verifier through new task
definitions with command overrides, keeping six local images and five
app ECR repos. The job code is a new additive script (proposed
`scripts/populate_prereqs.py`) with two argv-selected modes and no
secret ever in argv: `--populate` writes canonical values, and
`--verify-material` proves readiness read-only for standalone enable.
The existing `--bind` and `--verify` paths in
`scripts/bootstrap_db_roles.py` stay untouched.

The new narrow task roles (proposed `InitTaskRole` plus
`InitExecutionRole`, and separate `VerifyTaskRole` plus
`VerifyExecutionRole`, in `deploy/aws/fargate.yaml` at integration)
follow the execution role versus task role distinction that the
template already uses. The scanner stays unchanged; source says task
role and execution role with a space to avoid the false literal. Each
execution role pulls the image and writes logs only, with NO secret
injection through task `Secrets` entries. Each task role makes SDK
calls with task credentials only, and never sees root, publisher, or
static key credentials. All allows are scoped to exact owned ARNs with
no wildcards:

- Init task role: `secretsmanager:DescribeSecret` on the runtime,
  migration, and TLS secret ARNs; `secretsmanager:GetSecretValue` on
  those three ONLY as needed for populate reuse and readback checks,
  never on master; `secretsmanager:PutSecretValue` on those three ARNs
  ONLY for exact writes; `acm:DescribeCertificate` plus
  `acm:ExportCertificate` and tag read on the exact certificate ARN
  ONLY. No master secret value access, no secret delete, no rotation
  actions.
- Verify task role: `secretsmanager:DescribeSecret` plus
  `secretsmanager:GetSecretValue` on the exact three non master ARNs
  ONLY for readonly readiness; `acm:DescribeCertificate` plus tag read
  on the exact certificate ARN ONLY. NO `PutSecretValue`, NO
  `ExportCertificate`, NO master access, NO delete, rotation, or
  wildcard.

The job enforces caller, task role, account, region, and endpoint
ownership from live responses, using real SDK API shapes. Boto3 plus
the third party `cryptography` library are deployment only; Python
stdlib cannot decrypt PKCS8, so the decrypt path needs the pinned
third party backend. No hand-rolled SigV4, no hand-rolled crypto, no
password shell argv or files. New dependencies are pinned as DEPLOYMENT
ONLY additions without invented versions or pins in this spec; core
code stays stdlib plus psycopg for the distinct backend, and host
working deps and caches stay untouched. Public package facts needed
for host and source authoring are supplied by the host in Phase B; no
CLI install and no network happen in authoring. The deploying STS
identity needs only narrow scoped permissions for its exact calls,
with no broad policy need. No actual export, GetSecretValue, or job
runs in this terminal.

## D5. Populate semantics: RAM only, canonical, idempotent, bounded

Passphrase: generated in RAM, ASCII excluding `#`, `$`, `%`, length
within 4 to 128 bytes (concrete recommendation: 32 bytes from a
cryptographic RNG mapped to the allowed alphabet). AWS returns an
encrypted PKCS8 private key; the job decrypts it in RAM with the
pinned third party `cryptography` backend, because Python stdlib
cannot decrypt PKCS8. The job verifies certificate-key public match,
SAN equals the exact hostname, current time within validity bounds,
and the exported leaf parses as the actually issued certificate, then
constructs PEM plus chain base64 TLS JSON all in RAM and writes it
through SDK `PutSecretValue`. All offline crypto runs in RAM with no
`/tmp` PEM files for the provisioner. Synthetic generated materials
used in tests are never user keys. DB URL JSON keeps the generated
`password` and nonsecret username and adds the canonical
`database-url` built from the confirmed RDS endpoint with exactly
`sslmode=verify-full`, matching the strict parse rules in
`bootstrap_db_roles.py`. TLS JSON holds `tls-cert-b64` (certificate
plus chain PEM) and `tls-key-b64` (decrypted key PEM in one canonical
PKCS8 unencrypted form).

No PEMs, private keys, passphrases, or passwords appear in argv,
files, logs, or public receipts; raw AWS exceptions and tracebacks
are sanitized to bounded phase tokens following the existing `_fail`
and `_redact` pattern. Payload sizes are bounded (secret JSON well
under the Secrets Manager limit), SDK calls carry timeouts and bounded
retries, and there is no blind resend and no automatic new password or
certificate version after ambiguity: on an ambiguous write the job
reads back the current value, treats readback-equal as success, and
otherwise fails closed without writing a new version. Accepted but
unconfirmed retries use readback only.

Existing ready values validate and are reused unchanged. Malformed,
unowned, or refused values are never overwritten; the job fails
closed instead. Each secret gets a deterministic `ClientRequestToken`
of 32 to 64 chars derived as a stable hash of purpose plus the actual
SecretARN, reused on every retry of the same payload, which makes
`PutSecretValue` idempotent: same existing version plus same content
is a no-op, while different content under the same token fails instead
of forking. Canonical stable payloads carry no timestamp or random
fields that would create false differences. Endpoint or certificate
drift never triggers automatic new versions or tokens; drift fails
closed and needs an explicit later rotation gate. Certificate export
ciphertext varies with the passphrase, but the decrypted key and
certificate canonical content stays stable, so no new S3, DynamoDB, or
database is needed. Tests must use realistic adversarial fake SDKs
with normal response fields, and must prove repeated, parallel, and
unknown-write behavior.

## D6. Integrate order and preserved guards

Staged order with dependencies:

1. Foundation alerts confirmed (Budget plus exact confirmed SNS email).
2. Secrets plus ACM request, with Codex handled DNS validation,
   reaching prereq-ready (ISSUED cert plus four owned secret
   metadata records).
3. Base infra at DesiredCount 0 (RDS plus ALB cost starts here).
4. Explicit approved ECR publisher dispatch with image digest proof.
5. Least scope init job POPULATE plus validate.
6. Current owned role bind (existing dbroles semantics).
7. Migration to actual STOPPED with all essential containers exit 0
   and head `004`.
8. Runtime-only verify.
9. Existing enable proof.

Standalone enable MUST verify secret and certificate material ready
through the separate readonly verifier task role and task definition
via `--verify-material`, without Put or Export rights, without
auto-rotating secrets and without re-running migration. All working
guards are preserved: fresh versus owned stack handling, ECR digest
and task definition binding checks, rollback CRUD proof, 42501 DDL
refusal, fixed task counts, private RDS, and the job security group
with no inbound plus 443 egress. The app never receives the Master
or Migration secret or root keys. Public SAM stays OFF, global
budget stays 0, and the keyless synthetic demo profile stays the
recommendation. The currently working legacy path stays intact until
the atomic Phase C integration.

## D7. Teardown, expiry, and network retention

Planned teardown after Nov 4 and no later than Nov 9 covers the exact
new stacks (`launchcrew-foundation`, `launchcrew-prereqs`), the Secrets
retained lifecycle (Retain plus UpdateReplacePolicy Retain, with a
separately reviewed exact ARN `DeleteSecret` using 7 day recovery and
no force), ACM detach after the app stack listener is gone plus manual
DNS cleanup, and a review step for the publisher outside assets
(publisher stack, OIDC provider, and the two private repo secrets,
deleted by their own step). There is no automatic unapproved deletion
and no deletion now. Verified lifecycle: marked-for-deletion secrets
are inaccessible and not charged, while retained alone still persists.
Nov 9 teardown means stop resources and schedule secrets before the
deadline; recovery metadata may remain later. `DELETE_COMPLETE` with
retained secrets is not deletion proof. New provisioning after
expiration is refused by an explicit driver date guard, but the design
does NOT pretend AWS budgets or expiration fields stop billing by
themselves: expiry is a stop criterion, never a hard stop.

Network retention: the existing private production VPC `10.0.0.0/16`
stays untouched, the fresh demo VPC stays `10.42.0.0/16`, task counts
stay fixed at two, RDS stays private, one-off jobs keep the public
subnet placement with no inbound and 443 egress and no NAT, and no
account signed-in isolation guarantee is drawn from old inventory.

## Public facts used (checked Oct 28, not refetched)

- CloudFormation Secrets Manager Secret resource: managed password
  through `GenerateSecretString`; if BOTH `GenerateSecretString` and
  `SecretString` are omitted, the result is EMPTY secret metadata.
  https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-secretsmanager-secret.html
- `GenerateSecretString` properties: JSON `SecretStringTemplate` with
  nonsecret username or role metadata plus `GenerateStringKey` for the
  generated password key, password length and charset, and creation
  needs the `GetRandomPassword` permission. Property updates generate
  a NEW version, so owned resume needs a no-accidental-rotation
  guard. Empty password placeholder alone is not used.
  https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-secretsmanager-secret-generatesecretstring.html
- `PutSecretValue`: `ClientRequestToken` is the VersionId at 32 to 64
  chars; same version plus same SecretString is a no-op, different
  content fails; default `AWSCURRENT` moves; secrets do not appear in
  other params or CloudTrail logs; no sustained write version
  spamming.
  https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_PutSecretValue.html
- CloudFormation DeletionPolicy attribute: `Delete` for Secrets
  defaults to force delete without recovery. Secrets use `Retain`
  plus `UpdateReplacePolicy` `Retain`, with a separately reviewed
  exact ARN delete using recovery. Verified Oct 28.
  https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-deletionpolicy.html
- Secrets Manager delete: scheduled deletion with 7 day recovery and
  no force; marked-for-deletion secrets are inaccessible and not
  charged, while retained alone still persists. Nov 9 teardown stops
  resources and schedules secrets before the deadline; recovery
  metadata may remain later. Verified Oct 28.
  https://docs.aws.amazon.com/secretsmanager/latest/userguide/manage_delete-secret.html
- CloudFormation ACM Certificate resource: `CertificateExport`
  property; non-Route53 DNS means CloudFormation remains
  `CREATE_IN_PROGRESS` until the user adds the validation CNAME, so
  explicit staged pending metadata is necessary. No Route53 zone is
  assumed. No automatic Cloudflare path in source; Cloudflare auth is
  handled by Codex.
  https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-certificatemanager-certificate.html
- ACM `ExportCertificate`: supports NEW public certs created after
  June 17, 2025; returns Certificate, CertificateChain, and the
  encrypted PKCS8 private key; passphrase blob is 4 to 128 ASCII
  bytes except `#`, `$`, `%`. Decrypt runs in RAM with the pinned
  third party backend because Python stdlib cannot decrypt PKCS8.
  Response bounds are guarded; no fake plaintext private key
  assumption.
  https://docs.aws.amazon.com/acm/latest/APIReference/API_ExportCertificate.html
- ACM pricing, current page Oct 28: integrated non-exportable public
  certs carry no cost; an EXPORTABLE standard single FQDN cert now
  costs USD 7 AT ISSUANCE plus each renewal (NOT the old USD 15).
  Wildcard at 79 is NOT needed. The first 10k exports per month tier
  reads free but account usage is UNVERIFIED, so no free tier is
  assumed. Base subtotals 16.53 for 7 days and 28.15 for 12 days plus
  the new one-off 7 give 23.53 and 35.15 BEFORE additional job, API,
  SNS email, traffic, CPU credits, tax, and overlap charges. 45 is an
  ALERT, not a hard cap. No new certificate was actually requested or
  exported in this terminal; new paid cloud actions are authorized for
  Codex after verification.
  https://aws.amazon.com/certificate-manager/pricing/
- ALB target group routing: ALB HTTPS connections to targets do NOT
  validate backend certificates. This platform boundary stays honest
  even with the new valid ACM cert. No mTLS is claimed.
  https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-target-groups.html

## Acceptance and failure cases

- Foundation: dry run makes zero AWS calls; exact SNS gate passes only
  for the approved private endpoint plus `email` protocol plus owned
  TopicARN plus confirmed owned SubscriptionArn; pending, empty, wrong
  recipient, wrong protocol, wrong owner, and duplicate or ambiguous
  matches all block paid stages; wrong account, region, tags, StackId,
  or CE state refuses before any paid call.
- Secrets: template holds no SecretString plaintext; generation
  properties use nonsecret username metadata plus `GenerateStringKey`
  password, not an empty password placeholder; all four secrets carry
  Retain plus UpdateReplacePolicy Retain; creation without
  GetRandomPassword fails closed with a bounded message; generation
  property drift refuses instead of rotating.
- ACM: pending validation keeps the stack CREATE_IN_PROGRESS without
  claiming issuance; wrong domain, wrong account, or non-ISSUED
  status blocks export and app stages; only exact API errors count and
  broad ValidationError is never treated as absence; private DNS
  receipt is mode 600 with no secret values and no sensitive fields in
  public CI.
- Populate: token is purpose plus actual SecretARN hash; same token
  plus same content is a no-op; different content fails; endpoint or
  cert drift never creates automatic new versions or tokens and needs
  an explicit rotation gate; parallel identical puts stay safe; crash
  accepted-but-unconfirmed uses readback only without rotating;
  malformed or unowned current values are never overwritten; no secret
  bytes reach argv, files, logs, or receipts; provisioner crypto runs
  in RAM with no `/tmp` PEM files and synthetic materials are never
  user keys.
- Crypto: Python stdlib cannot decrypt PKCS8 so the pinned third party
  deployment-only backend decrypts; key match passes; mismatched key,
  wrong SAN, and out-of-bounds time fail; canonical payload bytes are
  stable across runs; export ciphertext may vary while decrypted
  content stays fixed.
- Enable standalone: unready material refuses without rotation or
  migration through the separate readonly verifier with Get exact
  three plus Describe only and no Put or Export; ready material reuses
  values unchanged and proceeds to the existing proof chain.
- Teardown: exact stacks only, Retain plus 7 day DeleteSecret with no
  force, marked-for-deletion inaccessible and not charged with retained
  alone persisting, Nov 9 stop and schedule before the deadline with
  recovery metadata possibly remaining later, DELETE_COMPLETE with
  retained secrets not deletion proof, DNS and publisher assets handled
  by explicit steps, no auto deletion and no deletion now.
