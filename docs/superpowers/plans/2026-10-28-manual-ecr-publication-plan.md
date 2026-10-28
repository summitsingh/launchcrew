# Manual ECR publication plan, source only

Spec: `docs/superpowers/specs/2026-10-28-manual-ecr-publication-spec.md`

Constraint: CLI read, edit, and explicit commit only. No tests,
collection, build, DB, network, AWS, GitHub API, env or credential
reads, installs, push, dispatch, cloud, IAM, credential, or model
calls in the authoring turn. HOST runs all checks after the authoring
terminal. Codex reviews final source and runs offline, static, and full
checks after the terminal, then normal main push only when safe and
green.

## Tasks

- [ ] Task 1: add `.github/workflows/publish-ecr.yml` (dispatch only,
  repo and main guard, concurrency one without cancel, bounded
  timeout, read plus id-token write only, pinned official SHAs,
  private secrets for expected account and role ARN, SHA equality
  guard before configure AWS credentials, helper call through env,
  manifest artifact on success only)
- [ ] Task 2: add `scripts/publish-ecr.sh` (dry run default zero
  calls, explicit confirm, exact SHA and main and clean tracked
  source, expected account and us-east-1, assumed role identity with
  root refused, owned stack tags, CE Project Active UserDefined,
  five stack bindings, IMMUTABLE everywhere, conflict tag refused
  before push with safe digest replay only, same proven Podman
  builds, five app pushes never db, full SHA tags, stdin login with
  private auth file and cleanup, sanitized errors, bounded single
  attempts, manifest only on five matching readback digests)
- [ ] Task 3: add `deploy/aws/publisher-role.yaml` (exact immutable
  subject plus audience condition, existing provider ARN parameter,
  five exact repo ARNs, GetAuthorizationToken on star only,
  CE metadata read only, minimum CFN reads on owned stack ARN only,
  tags, 3600 max session, private RoleArn output)
- [ ] Task 4: set `ImageTagMutability: IMMUTABLE` on the five existing
  ECR resources in `deploy/aws/fargate.yaml`, nothing else
- [ ] Task 5: add `tests/test_publish_ecr.py` with fake AWS and fake
  Podman recording real argv and stdin (dry run zero calls, every
  refusal before push, token never in argv log manifest or output
  with auth file cleanup, five readback success shapes, digest
  mismatch and partial failure with no manifest, IAM least privilege
  and subject parse, workflow guard and injection safe env parse)
- [ ] Task 6: add `docs/ecr-publication.md` (setup, publish, verify,
  teardown, boundaries, ROOT preflight fact without account ID) and
  update `docs/aws-approval-pack.md` for the new role and cleanup
  scope only

## HOST checks (after authoring terminal, not by the author)

1. `python3 -m unittest tests.test_publish_ecr -v` (fake AWS and
   Podman only, assert zero call cases and refusal cases)
2. Static parse of the role template (least privilege, subject,
   whitelist) and of the workflow (dispatch only, guards, pinned
   SHAs, secret handling)
3. `bash -n scripts/publish-ecr.sh` and shellcheck if configured
4. Full suite only if time allows: `uv run python -m unittest
   discover -s tests`
5. Codex final review, then normal main push only when green

## Exit

One checkpoint commit or a few logical commits, then exit with honest
UNEXECUTED checks. No fake pass.
