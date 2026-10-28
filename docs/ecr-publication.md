# Manual ECR publication, execution UNRUN

Status: publisher access prereqs applied Oct 28, 2026 as the ONLY
human-approved scope; publisher workflow execution remains UNRUN.
Human explicitly approved ONLY publisher access prereqs after
reviewing published f08 policy, NOT app infra, deploy, spend, ECR
push, dispatch, DNS, or model calls. No dispatch, push, deploy, or
paid action is run by this document or the source it describes.
Source published does NOT grant further actions. All checks run on
the host after the authoring terminal exits.

## Applied state Oct 28, 2026, prereqs fulfilled, execution UNRUN

Published main `f08b3c3464abe11bf88806db7a0bdd5090383f39` is clean.
Exact CI `40738345974` is TERMINAL SUCCESS:
https://github.com/summitsingh/launchcrew/actions/runs/40738345974.
Actual 296 core 34.684s, 271 backend 10.98s, 71 Vitest plus contracts
plus typecheck plus build with all zero scans, 24 browser 2.3min, 6
actual Linux image builds including bootstrap, real container
API/web/proxy create plus receipt plus seeded block plus export 422
before approval plus export 200 after approval plus queue PASS; no
model calls. Full host `3a30a8a` previous 271 backend plus 291 core
plus 71 Vitest plus 24 browser 1.9min PASS; final f08 affected 43
publisher 84.208s PASS. Public source and CI links support
source and runtime keyless proof only.

Actual new GitHub OIDC provider created, with persisted get
readback canonical issuer `token.actions.githubusercontent.com`,
audience ONLY `sts.amazonaws.com`, Project LaunchCrew plus
Environment demo tags, and AWS retrieved 1 thumbprint normal
CA/TLS. No shared provider changed.

Separate stack `launchcrew-publisher` used the exact f08 published
`publisher-role.yaml` snapshot hash
`5e9083f644efb5a93cae9c8b1088ef610aeb55bcc64f43adfc077a986aad420c`.
Actual AWS ValidateTemplate accepted with
CAPABILITY_NAMED_IAM, then CREATE ONLY. Exact stack ARN is held
PRIVATE. Actual DescribeStacks is TERMINAL CREATE_COMPLETE; sole
StackResource is PublisherRole type AWS::IAM::Role name
`launchcrew-ecr-publisher` CREATE_COMPLETE, with both owner tags.

Actual GetRole trust is the exact immutable main subject pinned in
published f08 `deploy/aws/publisher-role.yaml` StringEquals
`token.actions.githubusercontent.com:sub` (see
https://github.com/summitsingh/launchcrew/blob/f08b3c3464abe11bf88806db7a0bdd5090383f39/deploy/aws/publisher-role.yaml),
immutable owner ID 400621 with repo launchcrew ID 1436365964 on
ref `refs/heads/main`, plus audience `sts.amazonaws.com` on the
Federated same-account GitHub provider, Action
AssumeRoleWithWebIdentity only, max session 3600 and workflow
900. Actual GetRolePolicy is the exact
source five app ECR ARNs plus token star plus CE tag metadata star
plus own `launchcrew-demo` stack reads, with no IAM, PassRole,
ECS, SecretsManager, S3, or deploy actions.
List-attached-role-policies is EMPTY; list-role-policies is
exactly `ecr-publish-readback`. No root credentials were used for
publisher login or push, and no actual OIDC session was requested.

GitHub settings actual OIDC readback is use_default true plus
use_immutable_subject true, with the prefix matching the role
policy. Target repo secret LIST started at total 0 and matching
none. Created ONLY `ECR_PUBLISH_EXPECTED_ACCOUNT_ID` plus
`ECR_PUBLISHER_ROLE_ARN` through gh client stdin encryption,
with inputs account metadata plus readback RoleARN only and no
Meta or DB keys. Persisted API metadata readback is total 2 with
the two correct names and creation timestamps Oct 28 T18:09Z.
Values are not readable back by the GitHub API; this is metadata
readback, not secret value readback. No new static access key. No
dispatch, ECR publish, app infra, DNS, SNS subscription, model
call, recording, or submission.

Proof of live AWS IAM state is retained privately with the user
and cannot be verified from public CI or source alone. No public
Cloud proof URL or ID is invented here. Dated source-only design
remains history; the old no role, provider, or secret EVER wording
is now superseded for publisher prereqs only. App infra, ECR
push, dispatch, DNS, spend, and model calls remain unapproved and
unrun.

## Setup, fulfilled Oct 28, 2026 under its own approval

1. Done: the account-global GitHub OIDC provider was created once
   (URL https://token.actions.githubusercontent.com, client ID
   sts.amazonaws.com) with the readback above. Never alter shared
   provider state from the publisher template: no provider create,
   update, delete, or GitHub subject customization change.
2. Done: `deploy/aws/publisher-role.yaml` f08 snapshot hash above
   was applied under its own approval with the existing provider
   ARN as parameter. The parameter pattern only accepts
   `arn:aws:iam::` plus 12 digits plus
   `:oidc-provider/token.actions.githubusercontent.com`. The
   operator pre-apply review confirmed the same signed-in account,
   the provider URL, the audience, and no shared provider change.
   The output role ARN was recorded privately.
3. Done: two private repository secrets exist, values never in
   public source: `ECR_PUBLISH_EXPECTED_ACCOUNT_ID` (12 digits)
   and `ECR_PUBLISHER_ROLE_ARN`. No account ID or ARN appears in
   dispatch inputs, manifests, logs, or artifacts.
4. Read-only preflight fact, preserved dated history: CloudShell
   already proves the preflight operator identity is ROOT (not the
   publisher), so a publish attempt from that preflight identity
   would be refused by the helper before any cloud mutation. No
   root credentials were used for publisher login or push, and no
   actual OIDC session was requested. No account ID is published
   here.

## Publish

Actions tab, workflow `Publish ECR images (manual)`, branch main,
inputs are the full 40-char source SHA and the confirmation flag.
The workflow refuses unless the input SHA equals the checked out
origin/main SHA, the secrets are present with valid shapes, and the
branch is main in the exact repository. It assumes the publisher role
for 900 seconds with masked account IDs,
temporary action-managed environment credentials for the subsequent
AWS CLI steps, no step outputs, no persistent profiles, and no static
keys, then runs
`scripts/publish-ecr.sh --confirm`, which revalidates every guard live
(assumed role identity with root refused, owned stack proof, exact
stack tags, CE Project Active UserDefined, five stack bindings,
IMMUTABLE with no exclusions and exact resource tags on all five
repos, any existing tag for the SHA refused before any build or push),
builds the six proven Podman images with the proven storage flags,
pushes only the five app images with full SHA tags, reads back all
five digests, and writes `.local/ecr-publication-manifest.json` only
when every readback equals its pushed digest. The pushed digest comes
only from the push `--digestfile`; push stdout is never parsed. The
manifest uploads as the `ecr-publication-manifest` artifact on success
only. A preexisting manifest refuses the run instead of being
overwritten, so the operator removes it after manual review.

## Verify

The manifest holds only the source SHA, repo short names, and
digests. Confirm five entries, all digests starting with `sha256:`
plus 64 lowercase hex chars, and the source SHA equal to the published
main commit. Any refusal or partial publication writes no new manifest
and names the failing guard; a stale manifest left in place never
poses as a fresh receipt. Assemble the full URI with digest
(`registry/repo@digest`) only in private operator parameters, never
in public source.

## Teardown and cleanup scope

Image publication creates no app stack. The fulfilled publisher
access stack `launchcrew-publisher` plus the OIDC provider, the
publisher role, and the two private secrets live outside the demo
stack and are removed by their own delete step after the demo
window closes. The five ECR repositories empty and delete with the
demo stack delete. Teardown of the demo stays in
`deploy/aws/teardown.sh`.

## Boundaries

No push, pull request, schedule, or workflow event can publish.
No `latest` tag, no force, no delete, no overwrite, no replay of an
existing tag. The database image is built for local runs and never
pushed. Errors carry fixed stage or allowlisted error class text
only: no raw AWS or Podman stderr, no IDs, no ARNs, no tokens, no
emails, no registry URIs, no response bodies. The ECR password
travels on stdin from the
AWS CLI to Podman only, never in argv, files, or output. The Podman
auth file holds registry credentials as reversible credential storage
on local disk during the run (valid empty JSON, private mode 600
inside an owned mode 700 temp dir, set before login) and is always
removed on success and on failure. Publisher access prereqs are
fulfilled and need no reask; app deploy, spend, ECR push,
publisher execution, DNS, recording, submission, and model call
approvals remain pending and unchanged. Source published does NOT
grant further actions.
