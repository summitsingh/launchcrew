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
   HEAD equality, clean tracked tree, expected account (12 digits),
   region us-east-1, role ARN shape with matching account, assumed role
   identity (root refused), owned stack tags, CE Project Active
   UserDefined, five stack resource bindings, IMMUTABLE on all five
   repos, and existing tag state before any push. A conflicting tag
   refuses before any push unless the existing digest provably equals
   the local digest (safe replay skips that push). Full SHA tags only.
   ECR login pipes the password on stdin with a private mode 600
   auth file in an owned mode 700 temp dir, removed on success and
   failure. Errors are sanitized, bounded, and never carry raw
   stderr, IDs, ARNs, or tokens.
3. Publisher role `deploy/aws/publisher-role.yaml`, referencing an
   existing account provider ARN parameter and never altering shared
   provider state. Assume condition is the exact immutable subject plus
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
