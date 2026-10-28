# Manual ECR publication, source only

Status: source preparation only. No role, provider, secret, dispatch,
push, deploy, or paid action is created or run by this document or the
source it describes. All checks run on the host after the authoring
terminal exits.

## Setup (separately gated, not done here)

1. If absent, create the account-global GitHub OIDC provider once
   (URL https://token.actions.githubusercontent.com, client ID
   sts.amazonaws.com) under its own approval. Provider existence is
   otherwise unverified here. Never alter shared provider state from
   the publisher template: no provider create, update, delete, or
   GitHub subject customization change.
2. Apply `deploy/aws/publisher-role.yaml` under its own approval with
   the existing provider ARN as parameter. The parameter pattern only
   accepts `arn:aws:iam::` plus 12 digits plus
   `:oidc-provider/token.actions.githubusercontent.com`. The operator
   pre-apply review still confirms the same signed-in account, the
   provider URL, the audience, and that no shared provider change is
   included. Record the output role ARN privately.
3. Store two private repository secrets, values never in public
   source: `ECR_PUBLISH_EXPECTED_ACCOUNT_ID` (12 digits) and
   `ECR_PUBLISHER_ROLE_ARN`. No account ID or ARN appears in dispatch
   inputs, manifests, logs, or artifacts.
4. Read-only preflight fact: CloudShell already proves the operator
   identity is ROOT (not the publisher), so a publish attempt from the
   preflight identity would be refused by the helper before any cloud
   mutation. No account ID is published here.

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

Publication creates no stack and no standing resource. The five ECR
repositories empty and delete with the demo stack delete. The
publisher role and the two private secrets are outside the stack and
are removed by their own delete step after the demo window closes.
Teardown of the demo stays in `deploy/aws/teardown.sh`.

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
removed on success and on failure. Cost,
deploy, IAM, secret, DNS, recording, and submission approvals remain
pending and unchanged.
