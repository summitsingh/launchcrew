#!/bin/sh
# LaunchCrew manual ECR publisher, dry-run by default, isolated helper.
# Dry-run (no --confirm) makes zero AWS calls and zero Podman calls and
# prints the ordered publish plan only.
# Confirm path builds the six proven Podman images locally, pushes only
# the five app images (never db) to ECR with full SHA tags, reads back
# every image digest, and writes a manifest only when all five digests
# match. Any refusal or mismatch stops before the next paid or mutating
# step and writes no manifest. This script never deploys anything.
# Conventions: POSIX sh plus python3 for JSON parsing only. Error output
# is sanitized: raw AWS or Podman stderr, account IDs, ARNs, tokens, and
# registry URIs are never printed. The ECR password travels on stdin to
# Podman with a private mode 600 auth file in an owned mode 700 temp
# dir, removed on success and on failure. Single attempts only, no blind
# retry loop and no overwrite of an existing conflicting tag.
set -eu
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

usage() {
  echo "Usage: $0 [--confirm --source-sha SHA --expected-account ID --publisher-role-arn ARN] [--expected-region us-east-1] [--stack-name NAME] [--manifest PATH]"
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

# Scrubbed bounded error printer: redacts 12-digit account-like runs and
# ARN-like tokens, prints at most 10 lines, never the raw stream.
scrubbed() {
  head -n 10 "$1" 2>/dev/null | sed -e 's/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]/REDACTED/g' -e 's/arn:[^ ][^ ]*/REDACTED/g' || true
}

if [ "$CONFIRM" -ne 1 ]; then
  cat <<'PLAN'
publish-ecr DRY RUN: no AWS call and no Podman call were made.
Confirm path plan, in order:
  1. exact source SHA (40 hex) equals checked out HEAD, clean tracked tree, expected repo and main ref
  2. expected account shape, region us-east-1, publisher role ARN shape with matching account
  3. assumed role caller identity (root refused)
  4. owned stack tags Project LaunchCrew and Environment demo
  5. cost allocation tag Project Active UserDefined
  6. five stack ECR bindings and IMMUTABLE on every app repo
  7. existing tag state: conflict refuses before any push, equal digest replays safely
  8. build six proven Podman images, push five app images only with full SHA tags, stdin login only
  9. read back all five digests; manifest only when every digest matches
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
if [ -n "${GITHUB_REPOSITORY:-}" ] && [ "${GITHUB_REPOSITORY}" != "${EXPECTED_REPO}" ]; then
  refuse "repository guard mismatch"
fi
if [ -n "${GITHUB_REF:-}" ] && [ "${GITHUB_REF}" != "${EXPECTED_REF}" ]; then
  refuse "ref guard mismatch: main only"
fi
HEAD_SHA="$(git rev-parse HEAD 2>/dev/null)" || refuse "source tree unreadable"
if [ "$HEAD_SHA" != "$SOURCE_SHA" ]; then
  refuse "source SHA does not equal checked out HEAD"
fi
if [ -n "$(git status --porcelain 2>/dev/null | grep -v '^??' || true)" ]; then
  refuse "tracked source tree is not clean"
fi
case "$EXPECTED_ACCOUNT" in
  *[!0-9]*|'') refuse "expected account must be 12 digits" ;;
esac
if [ "${#EXPECTED_ACCOUNT}" -ne 12 ]; then
  refuse "expected account must be 12 digits"
fi
if [ "$EXPECTED_REGION" != "us-east-1" ]; then
  refuse "region must be us-east-1"
fi
case "$ROLE_ARN" in
  arn:aws:iam::????????????:role/?*) ;;
  *) refuse "publisher role ARN is malformed" ;;
esac
ROLE_ACCOUNT="$(printf '%s' "$ROLE_ARN" | cut -d: -f5)"
ROLE_NAME="$(printf '%s' "$ROLE_ARN" | cut -d/ -f2-)"
if [ "$ROLE_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
  refuse "publisher role account does not match expected account"
fi
if [ -z "$ROLE_NAME" ]; then
  refuse "publisher role ARN is malformed"
fi

ERR_TMP="$(mktemp -d)"
chmod 700 "$ERR_TMP"
cleanup_err() { rm -rf "$ERR_TMP"; }
trap cleanup_err EXIT INT TERM

# --- caller identity, first AWS call ---
"$AWS_BIN" sts get-caller-identity --output json >"$ERR_TMP/caller.json" 2>"$ERR_TMP/caller.err" || {
  echo "publish-ecr: refused: caller identity unreadable" >&2
  scrubbed "$ERR_TMP/caller.err" >&2
  exit 1
}
IDENT="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("Account","")+" "+d.get("Arn",""))' "$ERR_TMP/caller.json")" || refuse "caller identity malformed"
CALLER_ACCOUNT="${IDENT%% *}"
CALLER_ARN="${IDENT#* }"
if [ "$CALLER_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
  refuse "caller account does not match expected account"
fi
case "$CALLER_ARN" in
  *":assumed-role/${ROLE_NAME}/"*) ;;
  *) refuse "caller is not the expected publisher assumed role" ;;
esac
case "$CALLER_ARN" in
  *:root|*:user/*) refuse "caller is not the expected publisher assumed role" ;;
esac

# --- owned stack tags ---
"$AWS_BIN" cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --region "$EXPECTED_REGION" --output json >"$ERR_TMP/stacks.json" 2>"$ERR_TMP/stacks.err" || {
  echo "publish-ecr: refused: owned stack unreadable" >&2
  scrubbed "$ERR_TMP/stacks.err" >&2
  exit 1
}
TAGS="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); s=(d.get("Stacks") or [{}])[0]; print(" ".join(t.get("Key","")+"="+t.get("Value","") for t in s.get("Tags",[])))' "$ERR_TMP/stacks.json")" || refuse "owned stack tags malformed"
case " $TAGS " in
  *" Project=LaunchCrew "*) ;;
  *) refuse "owned stack Project tag mismatch" ;;
esac
case " $TAGS " in
  *" Environment=demo "*) ;;
  *) refuse "owned stack Environment tag mismatch" ;;
esac

# --- cost allocation tag Project must already read Active UserDefined ---
"$AWS_BIN" ce list-cost-allocation-tags \
  --region "$EXPECTED_REGION" --output json >"$ERR_TMP/cetags.json" 2>"$ERR_TMP/cetags.err" || {
  echo "publish-ecr: refused: cost allocation tag state unreadable" >&2
  scrubbed "$ERR_TMP/cetags.err" >&2
  exit 1
}
CE_STATE="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); tags=d.get("CostAllocationTags",d.get("CostAllocationTagList",[])); m=[t for t in tags if t.get("TagKey")=="Project"]; print((m[0].get("Type","") if m else "")+" "+(m[0].get("Status","") if m else ""))' "$ERR_TMP/cetags.json")" || refuse "cost allocation tag state malformed"
if [ "$CE_STATE" != "UserDefined Active" ]; then
  refuse "cost allocation tag Project is not Active UserDefined"
fi

# --- five stack ECR bindings ---
"$AWS_BIN" cloudformation describe-stack-resources --stack-name "$STACK_NAME" \
  --region "$EXPECTED_REGION" --output json >"$ERR_TMP/resources.json" 2>"$ERR_TMP/resources.err" || {
  echo "publish-ecr: refused: stack resources unreadable" >&2
  scrubbed "$ERR_TMP/resources.err" >&2
  exit 1
}
BINDINGS="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(" ".join(r.get("LogicalResourceId","")+"="+r.get("PhysicalResourceId","") for r in d.get("StackResources",[])))' "$ERR_TMP/resources.json")" || refuse "stack resources malformed"
check_binding() {
  case " $BINDINGS " in
    *" $1=$2 "*) ;;
    *) refuse "stack ECR binding mismatch for $2" ;;
  esac
}
check_binding ApiEcrRepo launchcrew-api
check_binding WebEcrRepo launchcrew-web
check_binding WebProxyEcrRepo launchcrew-web-proxy
check_binding MigrationEcrRepo launchcrew-migration
check_binding BootstrapEcrRepo launchcrew-bootstrap

# --- IMMUTABLE on all five repos, before any build or push ---
for repo in launchcrew-api launchcrew-web launchcrew-web-proxy launchcrew-migration launchcrew-bootstrap; do
  "$AWS_BIN" ecr describe-repositories --repository-names "$repo" \
    --region "$EXPECTED_REGION" --output json >"$ERR_TMP/repo.json" 2>"$ERR_TMP/repo.err" || {
    echo "publish-ecr: refused: repository state unreadable" >&2
    scrubbed "$ERR_TMP/repo.err" >&2
    exit 1
  }
  MUT="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); r=(d.get("repositories") or [{}])[0]; print(r.get("imageTagMutability",""))' "$ERR_TMP/repo.json")" || refuse "repository state malformed"
  if [ "$MUT" != "IMMUTABLE" ]; then
    refuse "repository mutability is not IMMUTABLE"
  fi
done

# --- build the six proven images, same Containerfiles as scripts/podman-local.sh ---
# Local tags stay localhost scoped. Only the five app images are pushed later, never db.
"$PODMAN_BIN" build --format oci -f containers/db.Containerfile -t localhost/launchcrew-db:demo . || refuse "local build failed"
"$PODMAN_BIN" build --format oci -f containers/api.Containerfile -t localhost/launchcrew-api:demo . || refuse "local build failed"
"$PODMAN_BIN" build --format oci -f containers/migrate.Containerfile -t localhost/launchcrew-migrate:demo . || refuse "local build failed"
"$PODMAN_BIN" build --format oci -f containers/web.Containerfile -t localhost/launchcrew-web:demo . || refuse "local build failed"
"$PODMAN_BIN" build --format oci -f containers/web-proxy.Containerfile -t localhost/launchcrew-web-proxy:demo . || refuse "local build failed"
"$PODMAN_BIN" build --format oci -f containers/bootstrap-db.Containerfile -t localhost/launchcrew-bootstrap:demo . || refuse "local build failed"

# Local digests, needed for the conflict gate and the readback comparison.
local_digest() {
  "$PODMAN_BIN" image inspect --format '{{.Digest}}' "localhost/$1:demo" 2>"$ERR_TMP/inspect.err" || {
    echo "publish-ecr: refused: local image digest unreadable" >&2
    scrubbed "$ERR_TMP/inspect.err" >&2
    exit 1
  }
}
DIGEST_API="$(local_digest launchcrew-api)" || exit 1
DIGEST_WEB="$(local_digest launchcrew-web)" || exit 1
DIGEST_PROXY="$(local_digest launchcrew-web-proxy)" || exit 1
DIGEST_MIGRATE="$(local_digest launchcrew-migrate)" || exit 1
DIGEST_BOOTSTRAP="$(local_digest launchcrew-bootstrap)" || exit 1

# --- existing tag state, before any push ---
# An absent tag is ImageNotFoundException. Any other API failure refuses,
# it is never treated as absence. An existing tag with the same digest is
# a safe replay and skips that push. An existing tag with a different
# digest refuses the whole run before any push.
REPLAY_API=0; REPLAY_WEB=0; REPLAY_PROXY=0; REPLAY_MIGRATE=0; REPLAY_BOOTSTRAP=0
existing_digest() {
  _repo="$1"; _local="$2"
  if "$AWS_BIN" ecr describe-images --repository-name "$_repo" \
      --image-ids "imageTag=${SOURCE_SHA}" --region "$EXPECTED_REGION" \
      --output json >"$ERR_TMP/existing.json" 2>"$ERR_TMP/existing.err"; then
    _found="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); ds=(d.get("imageDetails") or [{}]); print(ds[0].get("imageDigest",""))' "$ERR_TMP/existing.json")" || refuse "existing tag state malformed"
    if [ -z "$_found" ]; then
      refuse "existing tag state malformed"
    fi
    if [ "$_found" = "$_local" ]; then
      echo 1
    else
      echo "publish-ecr: refused: conflicting tag already exists" >&2
      exit 1
    fi
  else
    if grep -q 'ImageNotFoundException' "$ERR_TMP/existing.err" 2>/dev/null; then
      echo 0
    else
      echo "publish-ecr: refused: existing tag state unreadable" >&2
      scrubbed "$ERR_TMP/existing.err" >&2
      exit 1
    fi
  fi
}
REPLAY_API="$(existing_digest launchcrew-api "$DIGEST_API")" || exit 1
REPLAY_WEB="$(existing_digest launchcrew-web "$DIGEST_WEB")" || exit 1
REPLAY_PROXY="$(existing_digest launchcrew-web-proxy "$DIGEST_PROXY")" || exit 1
REPLAY_MIGRATE="$(existing_digest launchcrew-migration "$DIGEST_MIGRATE")" || exit 1
REPLAY_BOOTSTRAP="$(existing_digest launchcrew-bootstrap "$DIGEST_BOOTSTRAP")" || exit 1

# --- ECR login on stdin only, private auth file, always cleaned up ---
AUTH_TMP="$(mktemp -d)"
chmod 700 "$AUTH_TMP"
AUTH_FILE="$AUTH_TMP/auth.json"
touch "$AUTH_FILE"
chmod 600 "$AUTH_FILE"
cleanup_auth() { rm -rf "$AUTH_TMP"; }
trap 'cleanup_auth; cleanup_err' EXIT INT TERM
REGISTRY="${EXPECTED_ACCOUNT}.dkr.ecr.${EXPECTED_REGION}.amazonaws.com"
if ! "$AWS_BIN" ecr get-login-password --region "$EXPECTED_REGION" 2>"$ERR_TMP/login.err" | "$PODMAN_BIN" --authfile "$AUTH_FILE" login --username AWS --password-stdin "$REGISTRY" >"$ERR_TMP/login.out" 2>"$ERR_TMP/login2.err"; then
  echo "publish-ecr: refused: registry login failed" >&2
  scrubbed "$ERR_TMP/login.err" >&2
  scrubbed "$ERR_TMP/login2.err" >&2
  exit 1
fi

# --- tag and push the five app images only, never db ---
push_one() {
  _local_name="$1"; _repo="$2"; _local_digest="$3"; _replay="$4"
  _target="${REGISTRY}/${_repo}:${SOURCE_SHA}"
  if [ "$_replay" = "1" ]; then
    printf '%s' "$_local_digest"
    return 0
  fi
  "$PODMAN_BIN" tag "localhost/${_local_name}:demo" "$_target" || {
    echo "publish-ecr: refused: local tag step failed" >&2
    return 1
  }
  "$PODMAN_BIN" --authfile "$AUTH_FILE" push "$_target" >"$ERR_TMP/push.out" 2>"$ERR_TMP/push.err" || {
    echo "publish-ecr: refused: image push failed" >&2
    scrubbed "$ERR_TMP/push.err" >&2
    return 1
  }
  _pushed="$(grep -Eo 'sha256:[0-9a-f]{64}' "$ERR_TMP/push.out" | head -n 1 || true)"
  if [ -z "${_pushed:-}" ]; then
    echo "publish-ecr: refused: pushed digest unreadable" >&2
    return 1
  fi
  if [ "$_pushed" != "$_local_digest" ]; then
    echo "publish-ecr: refused: pushed digest does not match local digest" >&2
    return 1
  fi
  printf '%s' "$_pushed"
}
PUSHED_API="$(push_one launchcrew-api launchcrew-api "$DIGEST_API" "$REPLAY_API")" || exit 1
PUSHED_WEB="$(push_one launchcrew-web launchcrew-web "$DIGEST_WEB" "$REPLAY_WEB")" || exit 1
PUSHED_PROXY="$(push_one launchcrew-web-proxy launchcrew-web-proxy "$DIGEST_PROXY" "$REPLAY_PROXY")" || exit 1
PUSHED_MIGRATE="$(push_one launchcrew-migrate launchcrew-migration "$DIGEST_MIGRATE" "$REPLAY_MIGRATE")" || exit 1
PUSHED_BOOTSTRAP="$(push_one launchcrew-bootstrap launchcrew-bootstrap "$DIGEST_BOOTSTRAP" "$REPLAY_BOOTSTRAP")" || exit 1

# --- read back all five digests, every one must match ---
readback_digest() {
  _repo="$1"
  "$AWS_BIN" ecr describe-images --repository-name "$_repo" \
    --image-ids "imageTag=${SOURCE_SHA}" --region "$EXPECTED_REGION" \
    --output json >"$ERR_TMP/readback.json" 2>"$ERR_TMP/readback.err" || {
    echo "publish-ecr: failed: readback unreadable, partial publication" >&2
    scrubbed "$ERR_TMP/readback.err" >&2
    exit 1
  }
  _digest="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); ds=(d.get("imageDetails") or [{}]); print(ds[0].get("imageDigest",""))' "$ERR_TMP/readback.json")" || {
    echo "publish-ecr: failed: readback malformed, partial publication" >&2
    exit 1
  }
  if [ -z "$_digest" ]; then
    echo "publish-ecr: failed: readback digest empty, partial publication" >&2
    exit 1
  fi
  printf '%s' "$_digest"
}
READ_API="$(readback_digest launchcrew-api)" || exit 1
READ_WEB="$(readback_digest launchcrew-web)" || exit 1
READ_PROXY="$(readback_digest launchcrew-web-proxy)" || exit 1
READ_MIGRATE="$(readback_digest launchcrew-migration)" || exit 1
READ_BOOTSTRAP="$(readback_digest launchcrew-bootstrap)" || exit 1
if [ "$READ_API" != "$PUSHED_API" ] || [ "$READ_WEB" != "$PUSHED_WEB" ] || \
   [ "$READ_PROXY" != "$PUSHED_PROXY" ] || [ "$READ_MIGRATE" != "$PUSHED_MIGRATE" ] || \
   [ "$READ_BOOTSTRAP" != "$PUSHED_BOOTSTRAP" ]; then
  echo "publish-ecr: failed: readback digest mismatch, partial publication" >&2
  exit 1
fi

# --- manifest holds only source SHA, repo short name, and digest ---
mkdir -p "$(dirname "$MANIFEST")"
python3 - "$MANIFEST" "$SOURCE_SHA" "$READ_API" "$READ_WEB" "$READ_PROXY" "$READ_MIGRATE" "$READ_BOOTSTRAP" <<'PYEOF'
import json, sys
path, sha, api, web, proxy, migrate, bootstrap = sys.argv[1:8]
manifest = {
    "source_sha": sha,
    "images": [
        {"repository": "launchcrew-api", "digest": api},
        {"repository": "launchcrew-web", "digest": web},
        {"repository": "launchcrew-web-proxy", "digest": proxy},
        {"repository": "launchcrew-migration", "digest": migrate},
        {"repository": "launchcrew-bootstrap", "digest": bootstrap},
    ],
}
for image in manifest["images"]:
    assert image["digest"].startswith("sha256:"), "digest shape"
assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), "sha shape"
with open(path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2)
    handle.write("\n")
PYEOF
echo "publish-ecr: confirmed publication of five images with matching readback digests."
echo "Remaining work: assemble full URI with digest in private operator parameters, then deploy review."
