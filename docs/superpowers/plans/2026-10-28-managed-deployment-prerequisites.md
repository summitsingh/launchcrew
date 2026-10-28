# Managed deployment prerequisites plan, source only

Spec:
`docs/superpowers/specs/2026-10-28-managed-deployment-prerequisites.md`

Constraint: CLI read, edit, and explicit commit only. No tests,
collection, build, DB, network, AWS, GitHub API, env or credential
reads, installs, push, dispatch, cloud, IAM, credential, or model
calls in any authoring turn. HOST runs all checks after the authoring
terminal. Codex reviews final source and runs offline, static, and
full checks after the terminal, then assigns implementation stages
with all actual cloud gates intact. No actual cloud actions, no new
credential values, no user design questions; recommended source
choices in the spec stand.

## Staging rule

Never publish an intermediate broken legacy flow. Phase A and B are
strictly additive seams (new files plus new opt-in driver phases and
modes); the default `bootstrap.sh` phase order and the existing
fargate resources stay untouched until Phase C, which atomically
integrates and moves resources for the fresh unapplied app stack in
one reviewable commit. The applied publisher stack stays unchanged
throughout.

## Phase A: foundation and prereq metadata, templates plus fake AWS

Owner: template and driver author. Depends on: the spec above, plus
actual `deploy/aws/bootstrap.sh`, `deploy/aws/fargate.yaml`,
`deploy/aws/publisher-role.yaml`, `deploy/aws/teardown.sh`,
`deploy/aws/parameters.example.json`, and `tests/test_bootstrap.py`.

- [ ] Task A1: add `deploy/aws/foundation.yaml` (DemoBudget,
  BudgetTopic, BudgetTopicPolicy, BudgetEmailSubscription, moved
  verbatim in shape from fargate, with Project LaunchCrew,
  Environment demo, and TeardownBy tags; empty email default means no
  subscription). Include a parameters example for the notify email
  held privately, never with a real address in source.
- [ ] Task A2: add `deploy/aws/prereqs.yaml` (four Secrets Manager
  secrets: master, runtime, and migration with managed
  GenerateSecretString JSON `{"password": ...}` generation
  properties; TLS with neither GenerateSecretString nor SecretString
  so it starts as EMPTY metadata; one ACM Certificate for the exact
  hostname with DNS validation and CertificateExport ENABLED; owned
  tags; documented DeletionPolicy and secret recovery window).
- [ ] Task A3: add additive `foundation` and `prereqs` phases to
  `deploy/aws/bootstrap.sh`, callable explicitly, with the default
  `all` order unchanged: caller and StackId ownership, CE Project
  Active admission reused, SNS PendingConfirmation blocking gate,
  exact stack resource derivation by logical ID while the cert stack
  is CREATE_IN_PROGRESS, bounded ISSUED observation with the public
  validation CNAME printed as an explicit operator step, no
  ValidationError or 0 metadata reading as absence or issuance, and
  an expiry guard refusing confirm runs after 2026-11-09 as a source
  guard only, never as a billing stop claim.
- [ ] Task A4: add `tests/test_prereq_foundation.py` with the fake AWS
  runner pattern from `tests/test_bootstrap.py` (dry run zero calls;
  ownership refusals before any paid call; PendingConfirmation
  blocks; confirmed subscription passes; CE state matrix refuses;
  expiry guard refuses; no SecretString outside the job; no secret
  bytes in output).
- [ ] Task A5: add `tests/test_prereq_templates.py` (static: no
  SecretString plaintext in prereqs template; generation properties
  match the managed JSON shape; TLS has neither generation nor
  literal; cert has exact hostname, DNS validation, export enabled,
  no wildcard; cfn-lint clean on both new templates; bash -n on
  driver changes).

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
  passphrase in the allowed ASCII set and length; PKCS8 decrypt with
  the standard library; key match, SAN, and time bound checks;
  canonical DB URL and TLS JSON with no timestamp or random fields;
  deterministic per-secret ClientRequestToken in 32 to 64 chars;
  readback-equal treats ambiguous writes as success, otherwise fails
  closed with no new version; ready values reused unchanged;
  malformed, unowned, or refused values never overwritten; sanitized
  bounded errors only).
- [ ] Task B2: pin DEPLOYMENT ONLY dependencies (boto3 plus
  cryptography) with exact versions and lockfile entries, and record
  the public package facts used; core stays stdlib plus psycopg and
  host working deps and caches stay untouched. No install or network
  in authoring.
- [ ] Task B3: add the init image seam (copy the new script into the
  existing bootstrap image build; no new repo, no new local image
  beyond the existing six) plus `InitTaskDefinition`,
  `InitExecutionRole` (pull and logs only, no secret injection), and
  the narrow `InitTaskRole` (describe plus scoped get and put on the
  three owned non-master secret ARNs; ACM describe, export, and tag
  read on the exact cert ARN; no delete, rotation, wildcard, master
  value, root, publisher, or static key access).
- [ ] Task B4: add `tests/test_populate_prereqs.py` with realistic
  adversarial fake SDKs carrying normal response fields (idempotent
  same token plus same content no-op; different content fails;
  repeated plus parallel plus unknown-write proof; crash
  accepted-but-unconfirmed retries without rotation; reuse and
  never-overwrite matrix; secret privacy scan of argv, files, logs,
  and receipts; payload bounds and timeout behavior).
- [ ] Task B5: add `tests/test_prereq_crypto.py` with actual offline
  crypto (ephemeral fixtures in /tmp, deleted after; PKCS8 decrypt
  roundtrip; key match positive; mismatch, wrong SAN, and bad time
  negatives; canonical payload byte stability; export ciphertext may
  vary while decrypted content stays fixed).

Phase B acceptance: no test touches AWS or the network; every crypto
negative fails closed; concurrency and crash cases prove no rotation
and no overwrite; privacy scans find no secret bytes.

## Phase C: atomic integration, least IAM, cost pack, full host and CI

Owner: integration author. Depends on: Phase A plus B green on host,
actual `deploy/aws/fargate.yaml` task bindings and execution roles,
`scripts/publish-ecr.sh` image proof, and `docs/aws-approval-pack.md`.

- [ ] Task C1: atomic integration commit for the fresh unapplied app
  stack (move the four Budget and SNS resources from fargate to the
  foundation template; add the init task definition and roles; wire
  the full phase order foundation, prereqs plus DNS gate,
  prereq-ready, infra Desired 0, images, init populate plus validate,
  dbroles, migrate, runtime verify, enable; standalone enable runs
  read-only material verification with no auto rotation and no
  re-migration; all existing fresh versus owned, ECR, binding,
  rollback CRUD, and 42501 guards preserved).
- [ ] Task C2: update `deploy/aws/teardown.sh` scope and docs for the
  exact new stacks, secret recovery policy, ACM detach plus DNS
  cleanup, publisher outside asset review, and the no automatic
  deletion rule.
- [ ] Task C3: update `docs/aws-approval-pack.md` cost section only
  (one-off USD 7 at issuance plus each renewal; 23.53 and 35.15
  totals BEFORE job, API, SNS email, traffic, CPU credits, tax, and
  overlap; exports tier free reads but account usage UNVERIFIED so no
  free assumption; 45 stays an UNAPPROVED alert, never a cap; no new
  certificate actually requested or exported; ALB target boundary
  stays honest).
- [ ] Task C4: full host verification and Codex review (HOST checks
  below, including the full relevant PG, frontend, browser, and CI
  suites; existing publisher tests remain valid and green).

Phase C acceptance: one atomic commit, no intermediate broken flow on
any ref; every gate below passes on host; Codex assigns later
implementation stages only after green.

## HOST checks (after authoring terminal, not by the author)

1. `python3 -m unittest tests.test_prereq_foundation -v` (fake AWS
   only: zero-call dry run, exact ownership, PendingConfirmation
   blocking, expiry guard, no SecretString outside the job).
2. `python3 -m unittest tests.test_prereq_templates -v` plus
   `cfn-lint deploy/aws/foundation.yaml deploy/aws/prereqs.yaml`
   with no errors and no warnings.
3. `python3 -m unittest tests.test_populate_prereqs -v` (adversarial
   fake SDK: idempotent versions, partial and concurrent semantics,
   secret privacy).
4. `python3 -m unittest tests.test_prereq_crypto -v` (actual offline
   crypto match and negatives, canonical stability).
5. `bash -n deploy/aws/bootstrap.sh deploy/aws/teardown.sh` and
   shellcheck if configured; repo scan with no secrets.
6. Full relevant suites: `uv run python -m unittest discover -s
   tests`, plus the relevant PG, frontend, browser, and CI checks;
   existing publisher tests green and unchanged in scope.
7. Codex final review, then stage assignment only when green.

## Exit

One checkpoint commit of the source plan files, then exit with honest
UNEXECUTED checks. No fake pass. Full goal uncompleted: this source
plan is NOT deployment approval and NOT readiness.
