#!/usr/bin/env bash
# LaunchCrew manual ECR publisher, dry-run by default, isolated helper.
# Dry-run (no --confirm) makes zero AWS calls and zero Podman calls and
# prints the ordered publish plan only.
# Confirm path publishes the five app images (never db) to ECR with full
# SHA tags, reads back every image digest, and writes a manifest only
# when all five readbacks match the pushed digests. Any refusal or
# mismatch stops before the next paid or mutating step and writes no new
# manifest. A preexisting manifest is never deleted or overwritten: its
# presence refuses the run so a stale file can never pose as a fresh
# receipt. This script never deploys anything.
# Conventions: bash plus python3 for strict JSON parsing only. Error
# output is fixed bounded stage or allowlisted error class text only:
# raw AWS or Podman stderr, account IDs, ARNs, tokens, registry URIs,
# emails, and response bodies are never printed. The ECR password
# travels on stdin
# from the AWS CLI to Podman only, never in argv, files, or output. The
# Podman auth file is real reversible credential storage on local disk
# during the run: private mode 600 inside an owned mode 700 temp dir,
# removed on success and on failure. No other auth file, cache entry, or
# profile is touched. Storage flags mirror scripts/podman-local.sh
# (graph root, runroot, vfs, cgroupfs, containers config) so builds match
# the proven local path. Single attempts only with three explicit bounded
# transport retries via Podman --retry 3, no script level blind resend,
# no overwrite of an existing tag.
set -euo pipefail
AWS_BIN="${AWS_BIN:-aws}"
PODMAN_BIN="${PODMAN_BIN:-podman}"
CONFIRM=0
SOURCE_SHA="${SOURCE_SHA:-}"
EXPECTED_ACCOUNT="${EXPECTED_AWS_ACCOUNT_ID:-}"
EXPECTED_REGION="${EXPECTED_REGION:-us-east-1}"
ROLE_ARN="${PUBLISHER_ROLE_ARN:-}"
STACK_NAME="${STACK_NAME:-launchcrew-demo}"
EXPECTED_REPO="${EXPECTED_REPO:-summitsingh/launchcrew}"
EXPECTED_REF="${EXPECTED_REF:-refs/heads/main}"
MANIFEST="${MANIFEST:-.local/ecr-publication-manifest.json}"

FIXED_REPO="summitsingh/launchcrew"
FIXED_REF="refs/heads/main"
FIXED_REGION="us-east-1"
FIXED_STACK="launchcrew-demo"

usage() {
  echo "Usage: $0 [--confirm --source-sha SHA --expected-account ID --publisher-role-arn ARN] [--expected-region us-east-1] [--stack-name launchcrew-demo] [--manifest PATH]"
  echo "Dry-run default makes no AWS call and no Podman call."
}

while [ $# -gt 0 ]; do
  case "$1" in
    --confirm) CONFIRM=1; shift ;;
    --source-sha) SOURCE_SHA="${2:-}"; shift 2 ;;
    --source-sha=*) SOURCE_SHA="${1#--source-sha=}"; shift ;;
    --expected-account) EXPECTED_ACCOUNT="${2:-}"; shift 2 ;;
    --expected-account=*) EXPECTED_ACCOUNT="${1#--expected-account=}"; shift ;;
    --expected-region) EXPECTED_REGION="${2:-}"; shift 2 ;;
    --expected-region=*) EXPECTED_REGION="${1#--expected-region=}"; shift ;;
    --publisher-role-arn) ROLE_ARN="${2:-}"; shift 2 ;;
    --publisher-role-arn=*) ROLE_ARN="${1#--publisher-role-arn=}"; shift ;;
    --stack-name) STACK_NAME="${2:-}"; shift 2 ;;
    --stack-name=*) STACK_NAME="${1#--stack-name=}"; shift ;;
    --manifest) MANIFEST="${2:-}"; shift 2 ;;
    --manifest=*) MANIFEST="${1#--manifest=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "publish-ecr: refused: unknown argument" >&2; usage >&2; exit 2 ;;
  esac
done

refuse() {
  echo "publish-ecr: refused: $1" >&2
  exit 1
}

# Strict allowlist of recognized AWS error classes, else empty.
# Scans all parenthesized tokens and returns the first allowlisted
# class only. Any other parenthesized text, including long
# alphanumeric private fragments, is ignored and never returned.
aws_class() {
  _tokens="$(grep -o -E '\([A-Za-z][A-Za-z0-9]+\)' "$1" 2>/dev/null | tr -d '()' || true)"
  for _tok in $_tokens; do
    case "$_tok" in
      ImageNotFoundException|RepositoryNotFoundException|ExpiredToken|ExpiredTokenException|InvalidClientTokenId|AccessDenied|AccessDeniedException|ValidationError|InvalidParameterException|InvalidParameterValue|Throttling|ThrottlingException|TooManyRequestsException|ServerException|ResourceNotFoundException)
        printf '%s' "$_tok"
        return 0
        ;;
    esac
  done
  printf ''
}

# Fixed bounded failure line: stage plus an allowlisted class only,
# or fixed unknown. Raw AWS stderr is never printed.
fail_aws() {
  _class="$(aws_class "$2")"
  case "$_class" in
    ImageNotFoundException|RepositoryNotFoundException|ExpiredToken|ExpiredTokenException|InvalidClientTokenId|AccessDenied|AccessDeniedException|ValidationError|InvalidParameterException|InvalidParameterValue|Throttling|ThrottlingException|TooManyRequestsException|ServerException|ResourceNotFoundException)
      ;;
    *)
      _class="unknown"
      ;;
  esac
  echo "publish-ecr: refused: $1 (${_class})" >&2
  exit 1
}

valid_digest() {
  case "$1" in
    sha256:*) ;;
    *) return 1 ;;
  esac
  _hex="${1#sha256:}"
  [ "${#_hex}" -eq 64 ] || return 1
  case "$_hex" in
    *[!0-9a-f]*) return 1 ;;
  esac
  return 0
}

if [ "$CONFIRM" -ne 1 ]; then
  cat <<'PLAN'
publish-ecr DRY RUN: no AWS call and no Podman call were made.
Confirm path plan, in order:
  1. exact source SHA (40 hex) equals checked out HEAD and the
     origin/main snapshot, clean tree with no non-ignored untracked
     build source, exact repo and main ref context required
  2. expected account shape, region us-east-1, publisher role ARN shape
     with matching account, fixed values not overrideable
  3. assumed role caller identity is the exact STS assumed role
     (root, user, and wrong role refused)
  4. owned stack proof: one stack, exact ID, stable status, exact
     Project LaunchCrew and Environment demo tags
  5. cost allocation tag Project exactly once as UserDefined Active
  6. five unique stack ECR bindings plus IMMUTABLE with no exclusions
     and exact Project/Environment resource tags on every app repo
  7. any existing tag for the SHA refuses the whole run before any
     build or push, no overwrite and no replay
  8. build six proven Podman images with proven storage flags, push
     five app images only with full SHA tags, stdin login only,
     digest file only (stdout is never parsed)
  9. read back all five digests; manifest only when every readback
     equals its pushed digest, written atomically, never on partial
PLAN
  exit 0
fi

# --- static guards, before any AWS or Podman call ---
case "$SOURCE_SHA" in
  *[!0-9a-f]*|'') refuse "source SHA must be 40 lowercase hex chars" ;;
esac
if [ "${#SOURCE_SHA}" -ne 40 ]; then
  refuse "source SHA must be 40 lowercase hex chars"
fi
# Confirmed mode requires the real repo and main context. Missing
# context never silently passes: it refuses here.
if [ "${GITHUB_REPOSITORY:-}" != "$FIXED_REPO" ]; then
  refuse "repository guard mismatch"
fi
if [ "${GITHUB_REF:-}" != "$FIXED_REF" ]; then
  refuse "ref guard mismatch: main only"
fi
# Expected constants are fixed, never overrideable to another scope.
if [ "$EXPECTED_REPO" != "$FIXED_REPO" ]; then
  refuse "repository guard mismatch"
fi
if [ "$EXPECTED_REF" != "$FIXED_REF" ]; then
  refuse "ref guard mismatch: main only"
fi
if [ "$EXPECTED_REGION" != "$FIXED_REGION" ]; then
  refuse "region must be us-east-1"
fi
if [ "$STACK_NAME" != "$FIXED_STACK" ]; then
  refuse "stack must be launchcrew-demo"
fi
case "$EXPECTED_ACCOUNT" in
  *[!0-9]*|'') refuse "expected account must be 12 digits" ;;
esac
if [ "${#EXPECTED_ACCOUNT}" -ne 12 ]; then
  refuse "expected account must be 12 digits"
fi
case "$ROLE_ARN" in
  arn:aws:iam::????????????:role/?*) ;;
  *) refuse "publisher role ARN is malformed" ;;
esac
ROLE_ACCOUNT="$(printf '%s' "$ROLE_ARN" | cut -d: -f5)"
ROLE_REST="$(printf '%s' "$ROLE_ARN" | cut -d: -f6-)"
ROLE_NAME="${ROLE_REST#role/}"
case "$ROLE_ACCOUNT" in
  *[!0-9]*|'') refuse "publisher role ARN is malformed" ;;
esac
if [ "${#ROLE_ACCOUNT}" -ne 12 ]; then
  refuse "publisher role ARN is malformed"
fi
if [ "$ROLE_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
  refuse "publisher role account does not match expected account"
fi
if [ -z "$ROLE_NAME" ]; then
  refuse "publisher role ARN is malformed"
fi
# Fail closed when a manifest already exists: never delete or
# overwrite a user file, and never let a stale file pose as a fresh
# receipt. The operator removes it after manual review.
if [ -e "$MANIFEST" ]; then
  refuse "output already exists, manual review before overwrite"
fi
# The checked out HEAD and the origin/main snapshot must both equal
# the requested source SHA, and the tree must have no modified tracked
# files and no non-ignored untracked build source. Ignored paths such
# as .local stay out of the build context by .containerignore and git
# ignore rules and never reach this check.
HEAD_SHA="$(git rev-parse HEAD 2>/dev/null)" || refuse "source tree unreadable"
if [ "$HEAD_SHA" != "$SOURCE_SHA" ]; then
  refuse "source SHA does not equal checked out HEAD"
fi
ORIGIN_SHA="$(git rev-parse --verify refs/remotes/origin/main 2>/dev/null)" || refuse "origin main snapshot unreadable"
if [ "$ORIGIN_SHA" != "$SOURCE_SHA" ]; then
  refuse "source SHA does not equal origin main snapshot"
fi
GIT_STATUS="$(git status --porcelain 2>/dev/null)" || refuse "source tree unreadable"
if [ -n "$GIT_STATUS" ]; then
  refuse "source tree is not clean"
fi

ERR_TMP="$(mktemp -d)"
chmod 700 "$ERR_TMP"
cleanup_err() { rm -rf "$ERR_TMP"; }
trap cleanup_err EXIT INT TERM

# --- caller identity, first AWS call ---
"$AWS_BIN" sts get-caller-identity --output json >"$ERR_TMP/caller.json" 2>"$ERR_TMP/caller.err" || fail_aws "caller identity unreadable" "$ERR_TMP/caller.err"
CALLER_ACCOUNT="$(python3 -c '
import json,sys
d = json.load(open(sys.argv[1]))
a = d.get("Account")
assert isinstance(a, str) and len(a) == 12 and a.isdigit(), "account"
print(a)
' "$ERR_TMP/caller.json" 2>/dev/null)" || refuse "caller identity malformed"
CALLER_ARN="$(python3 -c '
import json,sys
d = json.load(open(sys.argv[1]))
a = d.get("Arn")
assert isinstance(a, str) and len(a) > 0, "arn"
print(a)
' "$ERR_TMP/caller.json" 2>/dev/null)" || refuse "caller identity malformed"
if [ "$CALLER_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
  refuse "caller account does not match expected account"
fi
case "$CALLER_ARN" in
  "arn:aws:sts::${EXPECTED_ACCOUNT}:assumed-role/${ROLE_NAME}/"*) ;;
  *) refuse "caller is not the expected publisher assumed role" ;;
esac
SESSION_SUFFIX="${CALLER_ARN##*/}"
if [ -z "$SESSION_SUFFIX" ]; then
  refuse "caller is not the expected publisher assumed role"
fi

# --- owned stack proof: one stack, exact ID, stable status, exact tags ---
"$AWS_BIN" cloudformation describe-stacks --stack-name "$FIXED_STACK" \
  --region "$FIXED_REGION" --output json >"$ERR_TMP/stacks.json" 2>"$ERR_TMP/stacks.err" || fail_aws "owned stack unreadable" "$ERR_TMP/stacks.err"
STACK_ID="$(python3 -c '
import json,sys
path, account = sys.argv[1], sys.argv[2]
d = json.load(open(path))
stacks = d.get("Stacks")
assert isinstance(stacks, list) and len(stacks) == 1, "stack count"
s = stacks[0]
assert isinstance(s, dict), "stack shape"
assert s.get("StackName") == "launchcrew-demo", "stack name"
sid = s.get("StackId")
assert isinstance(sid, str), "stack id shape"
prefix = "arn:aws:cloudformation:us-east-1:" + account + ":stack/launchcrew-demo/"
assert sid.startswith(prefix) and len(sid) > len(prefix) and "/" not in sid[len(prefix):], "stack id"
assert s.get("StackStatus") in ("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE", "IMPORT_COMPLETE"), "stack status"
tags = s.get("Tags")
assert isinstance(tags, list), "stack tags shape"
seen = {}
for t in tags:
    assert isinstance(t, dict), "stack tag shape"
    k, v = t.get("Key"), t.get("Value")
    assert isinstance(k, str) and isinstance(v, str), "stack tag fields"
    assert k not in seen, "stack tag duplicate"
    seen[k] = v
assert seen.get("Project") == "LaunchCrew", "stack Project tag"
assert seen.get("Environment") == "demo", "stack Environment tag"
print(sid)
' "$ERR_TMP/stacks.json" "$EXPECTED_ACCOUNT" 2>/dev/null)" || refuse "owned stack proof malformed"

# --- cost allocation tag Project must already read Active UserDefined ---
# Actual CLI shape filters server side to the one Project key.
"$AWS_BIN" ce list-cost-allocation-tags --tag-keys Project --type UserDefined \
  --region "$FIXED_REGION" --output json >"$ERR_TMP/cetags.json" 2>"$ERR_TMP/cetags.err" || fail_aws "cost allocation tag state unreadable" "$ERR_TMP/cetags.err"
python3 -c '
import json,sys
d = json.load(open(sys.argv[1]))
tags = d.get("CostAllocationTags")
assert isinstance(tags, list) and len(tags) == 1, "ce count"
t = tags[0]
assert isinstance(t, dict), "ce shape"
assert t.get("TagKey") == "Project" and t.get("Type") == "UserDefined" and t.get("Status") == "Active", "ce Project state"
' "$ERR_TMP/cetags.json" 2>/dev/null || refuse "cost allocation tag Project is not Active UserDefined"

# --- five unique stack ECR bindings ---
"$AWS_BIN" cloudformation describe-stack-resources --stack-name "$FIXED_STACK" \
  --region "$FIXED_REGION" --output json >"$ERR_TMP/resources.json" 2>"$ERR_TMP/resources.err" || fail_aws "stack resources unreadable" "$ERR_TMP/resources.err"
python3 -c '
import json,sys
path, stack_id = sys.argv[1], sys.argv[2]
d = json.load(open(path))
res = d.get("StackResources")
assert isinstance(res, list), "resources shape"
expected = {"ApiEcrRepo": "launchcrew-api", "WebEcrRepo": "launchcrew-web", "WebProxyEcrRepo": "launchcrew-web-proxy", "MigrationEcrRepo": "launchcrew-migration", "BootstrapEcrRepo": "launchcrew-bootstrap"}
ok = ("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE", "IMPORT_COMPLETE")
ecr = [r for r in res if isinstance(r, dict) and r.get("ResourceType") == "AWS::ECR::Repository"]
assert len(ecr) == 5, "ecr count"
seen = set()
for r in ecr:
    logical = r.get("LogicalResourceId")
    physical = r.get("PhysicalResourceId")
    assert logical in expected and expected[logical] == physical, "binding"
    assert logical not in seen, "duplicate"
    seen.add(logical)
    assert r.get("ResourceStatus") in ok, "resource status"
    assert r.get("StackId") == stack_id, "resource stack"
    assert r.get("StackName") == "launchcrew-demo", "resource stack name"
assert seen == set(expected), "bindings"
' "$ERR_TMP/resources.json" "$STACK_ID" 2>/dev/null || refuse "stack ECR bindings proof malformed"

# --- each repo: exact identity, IMMUTABLE with no exclusions, exact tags ---
# ListTagsForResource answers with uppercase Key and Value fields.
for repo in launchcrew-api launchcrew-web launchcrew-web-proxy launchcrew-migration launchcrew-bootstrap; do
  "$AWS_BIN" ecr describe-repositories --repository-names "$repo" \
    --region "$FIXED_REGION" --output json >"$ERR_TMP/repo.json" 2>"$ERR_TMP/repo.err" || fail_aws "repository state unreadable" "$ERR_TMP/repo.err"
  REPO_ARN="$(python3 -c '
import json,sys
path, repo, account, region = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
d = json.load(open(path))
repos = d.get("repositories")
assert isinstance(repos, list) and len(repos) == 1, "repo count"
r = repos[0]
assert isinstance(r, dict), "repo shape"
assert r.get("repositoryName") == repo, "repo name"
assert r.get("registryId") == account, "repo registry"
assert r.get("repositoryArn") == "arn:aws:ecr:%s:%s:repository/%s" % (region, account, repo), "repo arn"
assert r.get("repositoryUri") == "%s.dkr.ecr.%s.amazonaws.com/%s" % (account, region, repo), "repo uri"
assert r.get("imageTagMutability") == "IMMUTABLE", "repo mutability"
for k, v in r.items():
    assert "xclusion" not in k.lower() or v in (None, [], {}), "repo exclusion"
print(r.get("repositoryArn"))
' "$ERR_TMP/repo.json" "$repo" "$EXPECTED_ACCOUNT" "$FIXED_REGION" 2>/dev/null)" || refuse "repository proof malformed"
  "$AWS_BIN" ecr list-tags-for-resource --resource-arn "$REPO_ARN" \
    --region "$FIXED_REGION" --output json >"$ERR_TMP/repotags.json" 2>"$ERR_TMP/repotags.err" || fail_aws "repository tags unreadable" "$ERR_TMP/repotags.err"
  python3 -c '
import json,sys
d = json.load(open(sys.argv[1]))
tags = d.get("tags")
assert isinstance(tags, list), "tags shape"
seen = {}
for t in tags:
    assert isinstance(t, dict), "tag shape"
    k, v = t.get("Key"), t.get("Value")
    assert isinstance(k, str) and isinstance(v, str), "tag fields"
    assert k not in seen, "tag duplicate"
    seen[k] = v
assert seen.get("Project") == "LaunchCrew", "Project tag"
assert seen.get("Environment") == "demo", "Environment tag"
' "$ERR_TMP/repotags.json" 2>/dev/null || refuse "repository tags do not assert Project LaunchCrew and Environment demo"
done

# --- existing tag state, before any build or push ---
# An absent tag answers exact allowlisted ImageNotFoundException. Any
# other API failure refuses and is never treated as absence. Any
# existing digest for the
# requested SHA refuses the whole run before any build or push: with
# IMMUTABLE repos there is no safe in place overwrite and no replay,
# the operator reviews the existing tag out of band.
existing_absent() {
  _repo="$1"
  if "$AWS_BIN" ecr describe-images --repository-name "$_repo" \
      --image-ids "imageTag=${SOURCE_SHA}" --region "$FIXED_REGION" \
      --output json >"$ERR_TMP/existing.json" 2>"$ERR_TMP/existing.err"; then
    python3 -c '
import json,sys
d = json.load(open(sys.argv[1]))
details = d.get("imageDetails")
assert isinstance(details, list) and len(details) >= 1, "details"
found = [x.get("imageDigest") for x in details if isinstance(x, dict) and x.get("imageDigest")]
assert found, "digest"
' "$ERR_TMP/existing.json" 2>/dev/null || refuse "existing tag state malformed"
    echo "publish-ecr: refused: conflicting tag already exists for ${_repo}" >&2
    return 1
  fi
  if [ "$(aws_class "$ERR_TMP/existing.err")" = "ImageNotFoundException" ]; then
    return 0
  fi
  fail_aws "existing tag state unreadable" "$ERR_TMP/existing.err"
}
for repo in launchcrew-api launchcrew-web launchcrew-web-proxy launchcrew-migration launchcrew-bootstrap; do
  existing_absent "$repo" || exit 1
done

# --- proven Podman storage, same values as scripts/podman-local.sh ---
PODMAN_RUN_BASE="$PWD/.local/run"
mkdir -p "$PODMAN_RUN_BASE"
chmod 700 "$PODMAN_RUN_BASE"
export XDG_RUNTIME_DIR="$PODMAN_RUN_BASE"
export CONTAINERS_CONF="$PWD/containers/podman.conf"
PODMAN_RUNROOT="/tmp/launchcrew-run-$(id -u)"
if [[ -L "$PODMAN_RUNROOT" || ( -e "$PODMAN_RUNROOT" && ! -O "$PODMAN_RUNROOT" ) ]]; then
  echo "publish-ecr: refused: Podman runroot must be owned by the current user and not a symlink" >&2
  exit 1
fi
mkdir -p -m 700 "$PODMAN_RUNROOT"
chmod 700 "$PODMAN_RUNROOT"
PODMAN_STORE_ROOT="$PWD/.local/podman"
PODMAN_GLOBAL=(--root "$PODMAN_STORE_ROOT" --runroot "$PODMAN_RUNROOT" --storage-driver vfs --cgroup-manager cgroupfs)

# --- build the six proven images, same Containerfiles as podman-local.sh ---
# Local tags stay localhost scoped. Only the five app images are pushed
# later, never db.
"$PODMAN_BIN" "${PODMAN_GLOBAL[@]}" build --format oci -f containers/db.Containerfile -t localhost/launchcrew-db:demo . 2>"$ERR_TMP/build.err" || refuse "local build failed"
"$PODMAN_BIN" "${PODMAN_GLOBAL[@]}" build --format oci -f containers/api.Containerfile -t localhost/launchcrew-api:demo . 2>"$ERR_TMP/build.err" || refuse "local build failed"
"$PODMAN_BIN" "${PODMAN_GLOBAL[@]}" build --format oci -f containers/migrate.Containerfile -t localhost/launchcrew-migrate:demo . 2>"$ERR_TMP/build.err" || refuse "local build failed"
"$PODMAN_BIN" "${PODMAN_GLOBAL[@]}" build --format oci -f containers/web.Containerfile -t localhost/launchcrew-web:demo . 2>"$ERR_TMP/build.err" || refuse "local build failed"
"$PODMAN_BIN" "${PODMAN_GLOBAL[@]}" build --format oci -f containers/web-proxy.Containerfile -t localhost/launchcrew-web-proxy:demo . 2>"$ERR_TMP/build.err" || refuse "local build failed"
"$PODMAN_BIN" "${PODMAN_GLOBAL[@]}" build --format oci -f containers/bootstrap-db.Containerfile -t localhost/launchcrew-bootstrap:demo . 2>"$ERR_TMP/build.err" || refuse "local build failed"

# --- ECR login on stdin only, private auth file, always cleaned up ---
# pipefail is set, so an AWS credential failure stops even when the
# Podman login step alone would exit zero. The password never appears
# in argv, files, or output. The auth file holds registry credentials
# on local disk during the run and is removed on success and failure.
AUTH_TMP="$(mktemp -d)"
chmod 700 "$AUTH_TMP"
AUTH_FILE="$AUTH_TMP/auth.json"
touch "$AUTH_FILE"
chmod 600 "$AUTH_FILE"
cleanup_auth() { rm -rf "$AUTH_TMP"; }
trap 'cleanup_auth; cleanup_err' EXIT INT TERM
REGISTRY="${EXPECTED_ACCOUNT}.dkr.ecr.${FIXED_REGION}.amazonaws.com"
if ! "$AWS_BIN" ecr get-login-password --region "$FIXED_REGION" 2>"$ERR_TMP/login.err" | "$PODMAN_BIN" "${PODMAN_GLOBAL[@]}" login --authfile "$AUTH_FILE" --username AWS --password-stdin "$REGISTRY" >"$ERR_TMP/login.out" 2>"$ERR_TMP/login2.err"; then
  echo "publish-ecr: refused: registry login failed" >&2
  exit 1
fi

# --- tag and push the five app images only, never db ---
# The pushed digest comes only from the --digestfile the push writes.
# Push stdout can be empty and progress lines never carry the manifest
# digest, so stdout is never parsed. The digest file must hold exactly
# one sha256:64 lowercase hex value. Three explicit bounded transport
# retries via --retry 3 only, no script level blind resend on failure.
push_one() {
  _local_name="$1"; _repo="$2"
  _target="${REGISTRY}/${_repo}:${SOURCE_SHA}"
  "$PODMAN_BIN" "${PODMAN_GLOBAL[@]}" tag "localhost/${_local_name}:demo" "$_target" 2>"$ERR_TMP/tag.err" || {
    echo "publish-ecr: refused: local tag step failed" >&2
    return 1
  }
  _digest_file="$ERR_TMP/digest-${_repo}"
  if ! "$PODMAN_BIN" "${PODMAN_GLOBAL[@]}" push --authfile "$AUTH_FILE" --digestfile "$_digest_file" --retry 3 "$_target" "$_target" >"$ERR_TMP/push-${_repo}.out" 2>"$ERR_TMP/push-${_repo}.err"; then
    echo "publish-ecr: refused: image push failed" >&2
    return 1
  fi
  _pushed="$(tr -d '[:space:]' <"$_digest_file" 2>/dev/null)" || {
    echo "publish-ecr: refused: pushed digest unreadable" >&2
    return 1
  }
  valid_digest "$_pushed" || {
    echo "publish-ecr: refused: pushed digest unreadable" >&2
    return 1
  }
  printf '%s' "$_pushed"
}
PUSHED_API="$(push_one launchcrew-api launchcrew-api)" || exit 1
PUSHED_WEB="$(push_one launchcrew-web launchcrew-web)" || exit 1
PUSHED_PROXY="$(push_one launchcrew-web-proxy launchcrew-web-proxy)" || exit 1
PUSHED_MIGRATE="$(push_one launchcrew-migrate launchcrew-migration)" || exit 1
PUSHED_BOOTSTRAP="$(push_one launchcrew-bootstrap launchcrew-bootstrap)" || exit 1

# --- read back all five digests, every one must equal its pushed digest ---
readback_digest() {
  _repo="$1"; _expect="$2"
  "$AWS_BIN" ecr describe-images --repository-name "$_repo" \
    --image-ids "imageTag=${SOURCE_SHA}" --region "$FIXED_REGION" \
    --output json >"$ERR_TMP/readback.json" 2>"$ERR_TMP/readback.err" || {
    echo "publish-ecr: failed: readback unreadable, partial publication" >&2
    return 1
  }
  _digest="$(python3 -c '
import json,sys
d = json.load(open(sys.argv[1]))
details = d.get("imageDetails")
assert isinstance(details, list) and len(details) >= 1, "details"
found = [x.get("imageDigest") for x in details if isinstance(x, dict) and x.get("imageDigest")]
assert found, "digest"
print(found[0])
' "$ERR_TMP/readback.json" 2>/dev/null)" || {
    echo "publish-ecr: failed: readback malformed, partial publication" >&2
    return 1
  }
  if [ -z "$_digest" ]; then
    echo "publish-ecr: failed: readback digest empty, partial publication" >&2
    return 1
  fi
  if [ "$_digest" != "$_expect" ]; then
    echo "publish-ecr: failed: readback digest mismatch, partial publication" >&2
    return 1
  fi
  printf '%s' "$_digest"
}
READ_API="$(readback_digest launchcrew-api "$PUSHED_API")" || exit 1
READ_WEB="$(readback_digest launchcrew-web "$PUSHED_WEB")" || exit 1
READ_PROXY="$(readback_digest launchcrew-web-proxy "$PUSHED_PROXY")" || exit 1
READ_MIGRATE="$(readback_digest launchcrew-migration "$PUSHED_MIGRATE")" || exit 1
READ_BOOTSTRAP="$(readback_digest launchcrew-bootstrap "$PUSHED_BOOTSTRAP")" || exit 1

# --- manifest holds only source SHA, repo short name, and digest ---
# Written atomically next to the target path with safe modes, only
# after every guard and every readback passed.
MANIFEST_DIR="$(dirname "$MANIFEST")"
mkdir -p "$MANIFEST_DIR" 2>/dev/null || {
  echo "publish-ecr: refused: manifest directory unwritable" >&2
  exit 1
}
if [ ! -O "$MANIFEST_DIR" ]; then
  echo "publish-ecr: refused: manifest directory is not owned" >&2
  exit 1
fi
MANIFEST_NEW="${MANIFEST}.new.$$"
python3 -c '
import json, sys
path, sha, api, web, proxy, migrate, bootstrap = sys.argv[1:8]
repos = [("launchcrew-api", api), ("launchcrew-web", web), ("launchcrew-web-proxy", proxy),
         ("launchcrew-migration", migrate), ("launchcrew-bootstrap", bootstrap)]
assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), "sha"
for name, digest in repos:
    assert len(digest) == 71 and digest.startswith("sha256:"), "digest shape"
    assert all(c in "0123456789abcdef" for c in digest[7:]), "digest hex"
manifest = {
    "source_sha": sha,
    "images": [
        {"repository": name, "digest": digest} for name, digest in repos
    ],
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2)
    handle.write("\n")
' "$MANIFEST_NEW" "$SOURCE_SHA" "$READ_API" "$READ_WEB" "$READ_PROXY" "$READ_MIGRATE" "$READ_BOOTSTRAP" 2>/dev/null || {
  echo "publish-ecr: failed: manifest proof malformed, partial publication" >&2
  rm -f "$MANIFEST_NEW"
  exit 1
}
chmod 600 "$MANIFEST_NEW" 2>/dev/null || {
  echo "publish-ecr: failed: manifest proof malformed, partial publication" >&2
  rm -f "$MANIFEST_NEW"
  exit 1
}
mv "$MANIFEST_NEW" "$MANIFEST" 2>/dev/null || {
  echo "publish-ecr: failed: manifest proof malformed, partial publication" >&2
  rm -f "$MANIFEST_NEW"
  exit 1
}
echo "publish-ecr: confirmed publication of five images with matching readback digests."
echo "Remaining work: assemble full URI with digest in private operator parameters, then deploy review."

