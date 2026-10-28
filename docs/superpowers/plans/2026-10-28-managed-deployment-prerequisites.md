# Managed deployment prerequisites plan, source only

Spec:
`docs/superpowers/specs/2026-10-28-managed-deployment-prerequisites.md`

Constraint: CLI read, edit, and explicit commit only. No tests,
collection, build, DB, network, AWS, GitHub API, env or credential
reads, installs, push, dispatch, cloud, IAM, credential, or model
calls in any authoring turn. HOST runs all checks after the authoring
terminal. Codex reviews final source and runs offline, static, and
full checks after the terminal, then executes new paid cloud actions
with all actual cloud gates intact. User authorized deployment in AWS
and Cloudflare DNS plus local CLI install; this terminal does source
only with no cloud done. Cloudflare CLI and DNS auth are handled by
Codex. No actual cloud actions, no new credential values, no user
design questions; recommended source choices in the spec stand. No
design approval pause.

## Staging rule

Never publish an intermediate broken legacy flow. Phase A and B are
strictly additive seams (new files plus new opt-in driver phases and
modes); the default `bootstrap.sh` phase order and the existing
fargate resources stay untouched until Phase C, which atomically
integrates and moves resources for the fresh unapplied app stack in
one reviewable commit. The applied publisher stack stays unchanged
throughout. The currently working legacy path is preserved until the
atomic Phase C.

## Phase A: foundation and prereq metadata, templates plus fake AWS

Owner: template and driver author. Depends on: the spec above, plus
actual `deploy/aws/bootstrap.sh`, `deploy/aws/fargate.yaml`,
`deploy/aws/publisher-role.yaml`, `deploy/aws/teardown.sh`,
`deploy/aws/parameters.example.json`, and `tests/test_bootstrap.py`.

- [ ] Task A1: add `deploy/aws/foundation.yaml` (DemoBudget with
  Project LaunchCrew EQUALS-only filter, BudgetTopic,
  BudgetTopicPolicy, BudgetEmailSubscription, moved verbatim in shape
  from fargate, with Project LaunchCrew, Environment demo, and
  TeardownBy tags; empty email default means no subscription). Include
  a private parameters example for the notify email, never with a real
  address in source. No public secrets. Exact SNS gate runs before the
  first paid Secret.
- [ ] Task A2: add `deploy/aws/prereqs.yaml` (four Secrets Manager
  secrets: master, runtime, and migration with managed
  GenerateSecretString using nonsecret username metadata plus
  GenerateStringKey password, not an empty password placeholder; TLS
  with neither GenerateSecretString nor SecretString so it starts as
  EMPTY metadata; all four secrets with DeletionPolicy Retain plus
  UpdateReplacePolicy Retain and a separately reviewed exact ARN
  DeleteSecret 7 day recovery with no force; one ACM Certificate for
  the exact hostname `launchcrew.summitsingh.com` with DNS validation
  and CertificateExport ENABLED, no wildcard, no Route53 assumed;
  owned tags; documented lifecycle with no public secrets).
- [ ] Task A3: add additive `foundation` and `prereqs` phases to
  `deploy/aws/bootstrap.sh`, callable explicitly, with the default
  `all` order unchanged: caller and StackId ownership, CE Project
  Active admission reused, exact SNS gate requiring approved private
  endpoint plus `email` protocol plus owned TopicARN plus confirmed
  owned SubscriptionArn with wrong, ambiguous, and duplicate refusal,
  exact stack resource derivation by logical ID while the cert stack
  is CREATE_IN_PROGRESS, bounded ISSUED observation with a private
  DNS validation receipt at mode 600 and the public validation CNAME
  printed as an explicit operator step, no account, ARN, email, or
  sensitive fields in public CI, no broad ValidationError as absence
  with exact API errors only, real account, stack, and tag ownership
  with bounded private metadata receipts and no secret values in argv,
  files, or logs, and an expiry guard refusing confirm runs after
  2026-11-09 as a source guard only, never as a billing stop claim.
- [ ] Task A4: add `tests/test_prereq_foundation.py` with the fake AWS
  runner pattern from `tests/test_bootstrap.py` shaped like real APIs
  (dry run zero calls; ownership refusals before any paid call; exact
  SNS gate matrix for endpoint, protocol, owner, confirmed ARN,
  pending, empty, wrong, and duplicates; CE state matrix refuses;
  expiry guard refuses; pending CREATE_IN_PROGRESS yields staged
  metadata without claiming issuance; private receipt mode 600 with no
  secret values; no SecretString outside the job; no secret bytes in
  output).
- [ ] Task A5: add `tests/test_prereq_templates.py` (static: no
  SecretString plaintext in prereqs template; generation properties
  use nonsecret username plus GenerateStringKey password; TLS has
  neither generation nor literal; all four secrets carry Retain
  policies; cert has exact hostname, DNS validation, export enabled,
  no wildcard; foundation keeps the exact Project filter plus `email`
  protocol plus empty default; task role and execution role wording
  uses a space with the scanner unchanged).

Phase A acceptance: all new files parse; new driver phases refuse
correctly under every fake negative; default legacy flow behaves
exactly as before; the existing publisher tests stay green and
unchanged in scope.

## Phase B: memory-only SDK provisioner plus real offline crypto

Owner: job and crypto author. Depends on: Phase A templates and
ARN shapes, actual `scripts/bootstrap_db_roles.py` (parse rules,
`_fail` and `_redact` pattern, TLS guard), and
`containers/bootstrap-db.Containerfile`.

- [ ] Task B1: add `scripts/populate_prereqs.py` (`--populate` and
  `--verify-material`, argv flags only, no secret in argv; boto3 SDK
  calls with bounded payloads, timeouts, and retries; RAM-only
  passphrase in the allowed ASCII set and length; PKCS8 decrypt in RAM
  with the pinned third party `cryptography` backend because Python
  stdlib cannot decrypt PKCS8, with no `/tmp` PEM files for the
  provisioner; key match, SAN, and time bound checks; canonical DB URL
  and TLS JSON with no timestamp or random fields; deterministic
  per-secret ClientRequestToken as purpose plus actual SecretARN hash
  in 32 to 64 chars; no automatic new versions or tokens for endpoint
  or cert drift with an explicit later rotation gate; readback-equal
  treats ambiguous or accepted-but-unconfirmed writes as success,
  otherwise fails closed with no new version; ready values reused
  unchanged; malformed, unowned, or refused values never overwritten;
  sanitized bounded errors only; synthetic generated materials are
  never user keys).
- [ ] Task B2: record DEPLOYMENT ONLY dependencies (boto3 plus
  third party cryptography) without invented versions or pins; public
  package facts are supplied by the host in Phase B; core stays stdlib
  plus psycopg for the distinct backend and host working deps and
  caches stay untouched. Isolated deploy dependency verification runs
  later, host only. No install or network in authoring.
- [ ] Task B3: add the init image seam (copy the new script into the
  existing bootstrap image build; no new repo, no new local image
  beyond the existing six) plus `InitTaskDefinition`,
  `InitExecutionRole` (pull and logs only, no secret injection), the
  narrow `InitTaskRole` (describe plus scoped get on the three owned
  non-master secret ARNs for reuse and readback, exact Put on those
  three, ACM describe plus Export on the exact cert ARN, no master
  value, no delete, rotation, wildcard, root, publisher, or static key
  access), plus the separate readonly `VerifyTaskDefinition`,
  `VerifyExecutionRole`, and `VerifyTaskRole` on the same bootstrap
  image (Get on the exact three plus Describe certificate only, NO Put
  and NO Export). STS identity carries no broad policy need. Task role
  and execution role wording uses a space with the scanner unchanged.
- [ ] Task B4: add `tests/test_populate_prereqs.py` with realistic
  adversarial fake SDKs carrying normal response fields (idempotent
  same token plus same content no-op with purpose plus ARN hash; different
  content fails; drift creates no automatic versions or tokens;
  repeated plus parallel plus unknown-write proof; crash
  accepted-but-unconfirmed uses readback only without rotation; reuse
  and never-overwrite matrix; secret privacy scan of argv, files, logs,
  and receipts; payload bounds and timeout behavior).
- [ ] Task B5: add `tests/test_prereq_crypto.py` with actual offline
  crypto in RAM (PKCS8 decrypt roundtrip with the third party backend;
  key match positive; mismatch, wrong SAN, and bad time negatives;
  canonical payload byte stability; export ciphertext may vary while
  decrypted content stays fixed; synthetic generated materials are
  never user keys; no `/tmp` PEM files for the provisioner path).

Phase B acceptance: no test touches AWS or the network; every crypto
negative fails closed; concurrency, crash, and drift cases prove no
rotation and no overwrite; privacy scans find no secret bytes.

## Phase C: atomic integration, least IAM, cost pack, full host and CI

Owner: integration author. Depends on: Phase A plus B green on host,
actual `deploy/aws/fargate.yaml` task bindings and execution roles,
`scripts/publish-ecr.sh` image proof, and `docs/aws-approval-pack.md`.

- [ ] Task C1: atomic integration commit for the fresh unapplied app
  stack (move the four Budget and SNS resources from fargate to the
  foundation template; add the init and readonly verifier task
  definitions and roles; wire the full phase order foundation, prereqs
  plus DNS gate, prereq-ready, infra Desired 0, images, init populate
  plus validate, dbroles, migrate, runtime verify, enable; standalone
  enable runs readonly material verification with no auto rotation and
  no re-migration; all existing fresh versus owned, ECR, binding,
  rollback CRUD, and 42501 guards preserved).
- [ ] Task C2: update `deploy/aws/teardown.sh` scope and docs for the
  exact new stacks, secret Retain plus exact ARN DeleteSecret 7 day
  recovery with no force, marked-for-deletion inaccessible and not
  charged with retained alone persisting, Nov 9 stop and schedule
  before the deadline with recovery metadata possibly remaining later,
  DELETE_COMPLETE with retained secrets not deletion proof, ACM detach
  plus DNS cleanup, publisher outside asset review, and the no
  automatic deletion rule with no deletion now.
- [ ] Task C3: update `docs/aws-approval-pack.md` cost section only
  (one-off USD 7 at issuance plus each renewal; 23.53 and 35.15
  totals BEFORE job, API, SNS email, traffic, CPU credits, tax, and
  overlap; base 16.53 for 7 days and 28.15 for 12 days; exports tier
  free reads but account usage UNVERIFIED so no free assumption; 45
  stays an ALERT, never a cap; no new certificate actually requested
  or exported in source; ALB target boundary stays honest with no
  mTLS claim).
- [ ] Task C4: full host verification and Codex review (HOST checks
  below, including the full relevant PG, frontend, browser, and CI
  suites; existing publisher tests remain valid and green).

Phase C acceptance: one atomic commit, no intermediate broken flow on
any ref; every gate below passes on host; Codex assigns later
implementation stages only after green.

## HOST checks (after authoring terminal, not by the author)

Use the pinned venv runner without assuming system python or module
imports. Isolated deploy dependency verification runs later, host
only.

1. `.venv/bin/python -m unittest discover -s tests -p test_prereq_foundation.py -v` (fake AWS
   only: zero-call dry run, exact ownership, exact SNS gate,
   PendingConfirmation blocking, expiry guard, no SecretString outside
   the job).
2. `.venv/bin/python -m unittest discover -s tests -p test_prereq_templates.py -v` plus
   `cfn-lint deploy/aws/foundation.yaml deploy/aws/prereqs.yaml`
   with no errors and no warnings.
3. `.venv/bin/python -m unittest discover -s tests -p test_populate_prereqs.py -v` (adversarial
   fake SDK: idempotent versions, partial and concurrent semantics,
   secret privacy).
4. `.venv/bin/python -m unittest discover -s tests -p test_prereq_crypto.py -v` (actual offline
   crypto match and negatives, canonical stability).
5. `bash -n deploy/aws/bootstrap.sh deploy/aws/teardown.sh` and
   shellcheck if configured; repo scan with no secrets.
6. Full relevant suites: `.venv/bin/python -m unittest discover -s
   tests -v`, plus the relevant PG, frontend, browser, and CI checks;
   existing publisher tests green and unchanged in scope.
7. Codex final review, then paid execution only when green.

## Exit

One checkpoint commit of the source plan files, then exit with honest
UNEXECUTED checks. No fake pass. Full goal stays active: this source
plan is NOT cloud done and NOT readiness. Deployment is authorized for
Codex execution after verification.
