# Public workspace pivot

The API task always receives `AUTH_ENABLED=false`. Sign-in credentials,
conditions, policies, and template parameters are removed. The bootstrap accepts
omitted sign-in parameters, or the retired `EnableGoogleAuth=false` plus empty
sign-in ARNs, and strips retired keys before CloudFormation calls. Enabled
sign-in configuration is refused before mutation. Meta and Drive configuration
remain separate from sign-in; the Instagram social connection is unchanged.

Health opens the workspace without probing auth routes. Auth routes return 404.
Social connection mutations and Drive picker-token issuance return 403 in public
mode. Connections remain readable, including handle, scopes, and token storage
state. Ready and publish execution remain available. No production data or kill
switch state was changed by this work.

The roster-serving API excludes only the historical verification names
VerifyClone and VerifyScout, case-insensitively. Neither name occurs in shipped
presets or seed code. Existing rows are retained; the backend roster filter is
the durable layer for brief and campaign selectors.

## Budget evidence

The be2a364 migration active journal is marked complete with target head 008,
predecessor outcome recovered, and task suffix
`978a886757ae44d1934c4cf5002f061b`. Its matching recovery attestation reports
observed head 008. AWS DescribeTasks now returns MISSING for that task. Its
CloudWatch stream in `/launchcrew/demo/migration` has no events, so there are no
030 through 033 upgrade lines or top-up exceptions proving execution.

The exact published be2a364 migration image was inspected through ECR layer
metadata and a checksum-verified layer download. Layer
`sha256:4439c99b09475314bfb9f7901f2a6e56ca72604d612c7f62c4fcec199fcb23bc`
contains revisions 030, 031, 032, and 033. Missing revisions in the image are
therefore excluded as the cause.

The bootstrap's recovery branch returns success for observed head 008 without
launching a new migration. Its role-state verifier also returns exit 0 when a
known revision is behind the current chain head, while reporting migration
outstanding. Treating this exit as head-008 equivalence allowed rollout success
without proof that the current migration image ran. That is the established
rollout defect behind the unlanded grant; historical task execution itself is
unprovable from the retained task and logs. The separate migrate-031 attempt in
`.local/rollout-logs/migrate.log` stopped before execution on
`TASKDEF_OPERATION_MISMATCH:IMAGE` during init recovery.

Migration 034 inserts a missing budget row, raises balances below 12000000,
preserves higher balances, and verifies the floor. Migrate and enable now also
require a real migration task STOPPED with exit 0, bound to the current release,
task definition, image URI, and ECR image digest. Recovery attestation alone
cannot satisfy that gate.

## Operator handoff

Deploy the pushed source using the bootstrap route. Use no Google or Facebook
sign-in secret parameters or CLI flags. Retain the independent social connection
and Meta configuration. Watch for actual Alembic upgrades through revision 034
and the current-image terminal proof before enabling services. The new gate
fails closed if a historical recovery shortcut skips execution.

Historical journal reconciliation remains an operator review step. This change
does not rewrite aged journals, resend old mutating tasks, bypass the existing
init image-mismatch guard, or deploy production. An inherited recovery refusal
must be resolved through the reviewed journal procedure before retrying; the
new gate must not be bypassed to claim a successful budget migration.
