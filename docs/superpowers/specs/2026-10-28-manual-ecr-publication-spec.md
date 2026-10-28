# Manual ECR publication design, source only

Status: source preparation only. No role, provider, secret, dispatch,
push, deploy, or paid action is created or run by this design. All AWS,
Podman, and network checks are HOST executed after the authoring
terminal. This file holds no account ID, ARN, token, email, or registry
URI.

## Problem

`.github/workflows/verify.yml` builds six local Podman images but never
publishes. The five app images must reach ECR before any Fargate deploy,
with no push path on push, pull request, or schedule events.

## Shape

1. New workflow `.github/workflows/publish-ecr.yml`, trigger
   `workflow_dispatch` only, single job, exact repo and main ref guard,
   one concurrent run, no cancel of an active run, bounded job timeout.
   Job permissions are `contents: read` plus `id-token: write`, and no
   other write. Official actions are pinned by full SHA.
2. Isolated helper `scripts/publish-ecr.sh`, dry run default with zero
   AWS and zero Podman calls. Confirm path validates exact source SHA
   (full 40 hex through env, never eval of shell input), checked out
   HEAD equality plus origin/main snapshot equality, clean tree with
   no modified tracked files and no non-ignored untracked build
   source, required repo and main context with no silent bypass,
   fixed expected constants, expected account (12 digits),
   region us-east-1, role ARN shape with matching account, exact STS
   assumed role identity (root, user, and wrong role refused), owned
   stack proof with exact ID and stable status and exact tags, CE
   Project exactly once as UserDefined Active through tag-keys and
   type flags, five stack resource bindings, IMMUTABLE with no
   exclusions and exact resource tags on all five repos, and existing
   tag state before any build or push. Any existing tag for the SHA
   refuses the whole run before any build or push, with no overwrite
   and no replay. Full SHA tags only. Storage flags match the proven
   local path. ECR login pipes the password on stdin with a private
   mode 600 auth file in an owned mode 700 temp dir, removed on
   success and failure; the auth file is real reversible credential
   storage on local disk during the run. The pushed digest comes only
   from the push digest file, never from parsed stdout. Errors are
   fixed stage or error class text only, bounded, and never carry raw
   stderr, IDs, ARNs, tokens, emails, registry URIs, or bodies. A
   preexisting manifest refuses the run instead of being overwritten.
3. Publisher role `deploy/aws/publisher-role.yaml`, referencing an
   existing account provider ARN parameter restricted by pattern to
   the exact token.actions.githubusercontent.com issuer host and
   never altering shared provider state. Assume condition is the
   exact immutable subject plus
   audience sts.amazonaws.com. Grants are ECR upload, readback,
   describe, and list tags on the five exact repo ARNs,
   GetAuthorizationToken on Resource star, CE
   ListCostAllocationTags on Resource star for metadata only, and
   minimum CloudFormation reads on the one owned stack ARN. No stack
   write, IAM mutation, PassRole, ECS, SecretsManager, S3, deploy
   access, broad managed policy, chaining, or runtime secret.
   MaxSessionDuration 3600, workflow requests 900, tags
   Project LaunchCrew and Environment demo.
4. Existing controller honesty is preserved: the helper reports honest
   partial publication and writes no manifest unless all five readback
   digests match the pushed digests.
5. Manifest holds only source SHA, repo short name, and digest per
   image. Full URI with digest is assembled later in private operator
   parameters, never in public source.

## Non goals

No OIDC provider creation, no role creation, no secret creation, no
dispatch, no push, no deploy, no database change, no app or model
change, no CloudShell use, no email handling.
