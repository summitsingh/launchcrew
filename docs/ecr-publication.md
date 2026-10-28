# Manual ECR publication, source only

Status: source preparation only. No role, provider, secret, dispatch,
push, deploy, or paid action is created or run by this document or the
source it describes. All checks run on the host after the authoring
terminal exits.

## Setup (separately gated, not done here)

1. If absent, create the account-global GitHub OIDC provider once
   (URL https://token.actions.githubusercontent.com, client ID
   sts.amazonaws.com) under its own approval. Never alter shared
   provider state from the publisher template.
2. Apply `deploy/aws/publisher-role.yaml` under its own approval with
   the existing provider ARN as parameter. Record the output role ARN
   privately.
3. Store two private repository secrets, values never in public
   source: `ECR_PUBLISH_EXPECTED_ACCOUNT_ID` (12 digits) and
   `ECR_PUBLISHER_ROLE_ARN`. No account ID or ARN appears in dispatch
   inputs, manifests, logs, or artifacts.
4. Read-only preflight fact: CloudShell already proves the operator
   identity is ROOT (not the publisher), so a publish attempt from the
   preflight identity would be refused by the helper before any push.
   No account ID is published here.

## Publish

Actions tab, workflow `Publish ECR images (manual)`, branch main,
inputs are the full 40-char source SHA and the confirmation flag.
The workflow refuses unless the input SHA equals the checked out
origin/main SHA, the secrets are present with valid shapes, and the
branch is main in the exact repository. It assumes the publisher role
for 900 seconds with masked account IDs and no exported credentials,
then runs `scripts/publish-ecr.sh --confirm`, which revalidates every
guard live (assumed role identity with root refused, owned stack tags,
CE Project Active UserDefined, five stack bindings, IMMUTABLE on all
five repos, no conflicting tag), builds the six proven Podman images,
pushes only the five app images with full SHA tags, reads back all
five digests, and writes `.local/ecr-publication-manifest.json` only
when every digest matches. The manifest uploads as the
`ecr-publication-manifest` artifact.

## Verify

The manifest holds only the source SHA, repo short names, and
digests. Confirm five entries, all digests starting with `sha256:`,
and the source SHA equal to the published main commit. Any refusal or
partial publication writes no manifest and names the failing guard;
assemble the full URI with digest (`registry/repo@digest`) only in
private operator parameters, never in public source.

## Teardown and cleanup scope

Publication creates no stack and no standing resource. The five ECR
repositories empty and delete with the demo stack delete. The
publisher role and the two private secrets are outside the stack and
are removed by their own delete step after the demo window closes.
Teardown of the demo stays in `deploy/aws/teardown.sh`.

## Boundaries

No push, pull request, schedule, or workflow event can publish.
No `latest` tag, no force, no delete, no overwrite. The database
image is built for local runs and never pushed. Errors are sanitized:
no raw AWS or Podman stderr, no IDs, no ARNs, no tokens. The ECR
password travels on stdin with a private auth file that is always
cleaned up. Cost, deploy, IAM, secret, DNS, recording, and submission
approvals remain pending and unchanged.
