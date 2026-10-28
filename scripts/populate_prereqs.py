#!/usr/bin/env python3
"""LaunchCrew prereq memory-only SDK provisioner, no secret logging.

Runs ONLY as a one-off task on the existing bootstrap image (built from
containers/bootstrap-db.Containerfile), sharing that image with the existing
bootstrap task. No new ECR repo and no new local image: Phase C adds the
task definitions with command overrides. This terminal does source only;
no AWS calls run here. The host installs the isolated deploy-only lock
after the terminal and runs all checks.

Modes, selected by argv flag only (no secret ever appears in argv):
  --populate         validate caller plus metadata, then write canonical
                     runtime and migration database-url values plus TLS
                     material through SDK PutSecretValue, all in RAM.
  --verify-material  read-only readiness proof with zero Put and zero
                     Export calls. Separate task role and task definition
                     are defined later in Phase C.

Environment, metadata only, no secret values in env names or argv:
  Required:
    LAUNCHCREW_EXPECTED_ACCOUNT    12 digit owner account, validated via STS.
    LAUNCHCREW_EXPECTED_REGION     owner region, validated in every ARN.
    LAUNCHCREW_EXPECTED_ROLE       expected task role name substring, must
                                   appear in the STS caller Arn.
    LAUNCHCREW_MASTER_SECRET_ARN   master metadata only, Describe only,
                                   never GetSecretValue.
    LAUNCHCREW_RUNTIME_SECRET_ARN  runtime secret ARN, Describe plus scoped
                                   Get and Put.
    LAUNCHCREW_MIGRATION_SECRET_ARN migration secret ARN, same scope.
    LAUNCHCREW_TLS_SECRET_ARN      TLS secret ARN, same scope, starts empty.
    LAUNCHCREW_CERT_ARN            exact ACM certificate ARN.
    LAUNCHCREW_DB_HOST             real owned RDS endpoint, strict remote
                                   host, never loopback or localhost.
    DATABASE_SSL_ROOTCERT          existing CA bundle file path.
    LAUNCHCREW_DB_TLS_MODE         must be exactly verify-full.
  Fixed by this source (no override, exact match required):
    Project LaunchCrew, Environment demo, hostname
    launchcrew.summitsingh.com, DB launchcrew port 5432,
    users launchcrew_runtime and launchcrew_migration.

Order of validation, before any secret value is read:
  1. Local env shape, ARN shape, distinct ARNs, remote host, CA file.
  2. STS GetCallerIdentity account plus expected role substring.
  3. Secrets Manager DescribeSecret metadata for all four secrets in
     populate (three non-master in verify), with returned ARN equal to
     the input ARN plus Project and Environment tags.
  4. ACM DescribeCertificate plus ListTagsForCertificate ownership:
     ARN match, DomainName exact, single SAN exact, Type AMAZON_ISSUED,
     Options Export ENABLED, Status ISSUED, owned tags, current time
     within NotBefore and NotAfter.
  5. Only then GetSecretValue on the exact three non-master ARNs.
  Any refusal above makes zero value calls (zero Get, Put, Export).

Canonical values, all in RAM, no PEM files, no timestamps:
  Runtime and migration JSON holds username plus the preserved generated
  password plus database-url built as
  postgresql://user:percent-encoded-password@host:5432/launchcrew
  ?sslmode=verify-full. The password is percent-encoded without
  modification and roundtrips exactly. JSON is canonical with sorted
  keys and no spaces. TLS JSON holds tls-cert-b64 (leaf plus chain PEM,
  base64) and tls-key-b64 (decrypted key in canonical PKCS8 unencrypted
  PEM, base64). Payloads carry no timestamp or random fields.

Idempotency and drift:
  Each Put uses a deterministic 64 hex ClientRequestToken derived as
  SHA256 of purpose plus the actual SecretARN plus the canonical payload
  digest. Same accepted payload is a no-op with no new Put. Endpoint,
  certificate, or secret material drift never creates automatic new
  versions or tokens; the job fails closed with rotation-required and a
  later explicit rotation gate handles it. Partial resume reuses
  successful secrets unchanged and retries only the missing ones.

Crash semantics, bounded, no blind retry:
  PutSecretValue and ExportCertificate run at most once per secret per
  invocation with SDK retries disabled and short timeouts. On a Put
  failure the job performs exactly one readback GetSecretValue: if the
  readback SecretString equals the attempted canonical payload the write
  counts as success, otherwise the job fails closed with no new version
  and no second Put. Ambiguous readback (error or different content)
  stops with no rotation. There is no automatic task resend.

TLS empty handling:
  TLS starts as empty owned metadata. Only the exact
  ResourceNotFoundException shape from GetSecretValue counts as empty.
  Any other error fails closed and is never treated as absence.
  Existing valid TLS material that matches the current issued leaf is
  reused with zero Export calls. Malformed or drifted TLS is never
  overwritten.

Crypto, deployment only:
  The passphrase is 32 ASCII chars from a cryptographic RNG over the
  printable set excluding number sign, dollar, and percent, length
  within 4 to 128. Export returns an encrypted PKCS8 key which is
  decrypted in RAM with the pinned third party cryptography backend
  because Python stdlib cannot decrypt PKCS8. The job verifies key
  match, exact SAN, time bounds, and chain shape. Synthetic materials
  in tests are generated in RAM and are never user keys.

ACM leaf equality without Export:
  The verifier and the populate reuse path compare the stored leaf to
  the exact public ACM GetCertificate leaf bytes to prove the secret
  holds the actually issued leaf, with no Export call. Least-scoped
  read permission for that call is acm:GetCertificate on the exact
  certificate ARN only. The readonly verifier never calls Put or
  Export.

IAM expectations for Phase C integration (exact, no wildcards):
  Init task role on the exact owned ARNs only:
    secretsmanager:DescribeSecret on master plus runtime plus migration
      plus TLS (four, metadata and ownership only);
    secretsmanager:GetSecretValue on runtime plus migration plus TLS
      only (three, never master);
    secretsmanager:PutSecretValue on runtime plus migration plus TLS
      only (three, exact writes);
    acm:DescribeCertificate plus acm:ListTagsForCertificate plus
      acm:GetCertificate plus acm:ExportCertificate on the exact
      certificate ARN only (Export at most once, only when TLS empty).
    No secret delete, no rotation actions, no master value access, no
    publisher or root or static key credentials.
  Readonly verify task role on the exact owned ARNs only:
    secretsmanager:DescribeSecret plus secretsmanager:GetSecretValue
      on runtime plus migration plus TLS only (three, no master);
    acm:DescribeCertificate plus acm:ListTagsForCertificate plus
      acm:GetCertificate on the exact certificate ARN only.
    No PutSecretValue, no ExportCertificate, no master access, no
    delete, rotation, or wildcard.
  Each execution role pulls the image and writes logs only, with no
  secret injection through task Secrets entries. Task role and
  execution role wording uses a space to keep the scanner unchanged.

Deploy-only dependencies, host installed after the terminal:
  boto3==1.43.119 plus cryptography==50.0.2 with transitive pins and
  hashes in containers/bootstrap-deploy-requirements.lock, installed in
  the bootstrap image with pip --require-hashes only. Core stays stdlib
  plus psycopg for the distinct backend. No install or network runs in
  authoring. Import of boto3 and cryptography is lazy inside the
  functions that need them so pure validation helpers stay stdlib only
  for offline unit tests.

Stdlib plus boto3 plus cryptography only. No backend import, no psycopg
here, no file writes, no raw exception text in output.
"""

import base64
import hashlib
import json
import os
import re
import secrets as pysecrets
import sys
import urllib.parse

EXPECTED_PROJECT = "LaunchCrew"
EXPECTED_ENV = "demo"
EXPECTED_DOMAIN = "launchcrew.summitsingh.com"
EXPECTED_DB_NAME = "launchcrew"
EXPECTED_DB_PORT = 5432
EXPECTED_RUNTIME_USER = "launchcrew_runtime"
EXPECTED_MIGRATION_USER = "launchcrew_migration"
SECRET_LIMIT_BYTES = 65536

IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
DBNAME = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
TOKEN_RE = re.compile(r"^[0-9a-f]{32,64}$")

_REJECTED_QUERY_KEYS = frozenset({'host', 'hostaddr', 'service',
                                  'servicefile', 'sslrootcert'})
_LOCAL_HOSTS = frozenset({'localhost', '0.0.0.0', '::1',
                          '169.254.169.254'})

_known_secrets: list = []


def _redact(text):
    out = str(text)
    for secret in _known_secrets:
        if secret:
            out = out.replace(secret, "***")
    return out


def _fail(phase, detail=""):
    suffix = " " + _redact(detail) if detail else ""
    print("populate-prereqs: FAIL: %s%s" % (phase, suffix), flush=True)
    return 1


def _ok(phase):
    print("populate-prereqs: %s ok" % phase, flush=True)


def _env(name, required=True):
    value = os.environ.get(name, "")
    if required and not value:
        raise ValueError("missing %s" % name)
    return value


def _check_account(value):
    cleaned = (value or "").strip()
    if not ACCOUNT_RE.match(cleaned):
        raise ValueError("invalid expected account")
    return cleaned


def _check_region(value):
    cleaned = (value or "").strip()
    if not re.match(r"^[a-z]{2}-[a-z-]+-[0-9]$", cleaned):
        raise ValueError("invalid expected region")
    return cleaned


def _parse_arn(label, arn, expected_service, expected_account,
               expected_region):
    text = (arn or "").strip()
    parts = text.split(":", 5)
    if len(parts) != 6 or parts[0] != "arn" or parts[1] != "aws":
        raise ValueError("invalid %s ARN shape" % label)
    _partition, _service, service, region, account, resource = (
        parts[0], parts[1], parts[2], parts[3], parts[4], parts[5])
    if service != expected_service:
        raise ValueError("invalid %s ARN service" % label)
    if region != expected_region:
        raise ValueError("invalid %s ARN region" % label)
    if account != expected_account:
        raise ValueError("invalid %s ARN account" % label)
    if not resource:
        raise ValueError("invalid %s ARN resource" % label)
    return {"service": service, "region": region, "account": account,
            "resource": resource}


def _check_distinct(label_arns):
    seen = {}
    for label, arn in label_arns:
        if arn in seen:
            raise ValueError("duplicate ARN for %s and %s"
                             % (seen[arn], label))
        seen[arn] = label


def _check_remote_host(value):
    cleaned = (value or "").strip().lower()
    if not cleaned or "," in cleaned or " " in cleaned:
        raise ValueError("invalid DB host")
    if cleaned in _LOCAL_HOSTS or cleaned.startswith("127."):
        raise ValueError("refused local DB host")
    if cleaned == "localhost.localdomain":
        raise ValueError("refused local DB host")
    if "." not in cleaned:
        raise ValueError("refused single-label DB host")
    if not HOST.match(cleaned):
        raise ValueError("invalid DB host")
    return cleaned


def _tls_guard():
    if os.environ.get("LAUNCHCREW_DB_TLS_MODE", "") != "verify-full":
        raise ValueError("LAUNCHCREW_DB_TLS_MODE must be verify-full")
    bundle = os.environ.get("DATABASE_SSL_ROOTCERT", "")
    if not bundle or not os.path.isfile(bundle):
        raise ValueError("DATABASE_SSL_ROOTCERT bundle missing")
    return bundle


def _load_config():
    account = _check_account(_env("LAUNCHCREW_EXPECTED_ACCOUNT"))
    region = _check_region(_env("LAUNCHCREW_EXPECTED_REGION"))
    role = _env("LAUNCHCREW_EXPECTED_ROLE").strip()
    if not role or len(role) > 256:
        raise ValueError("invalid expected role")
    master = _env("LAUNCHCREW_MASTER_SECRET_ARN").strip()
    runtime = _env("LAUNCHCREW_RUNTIME_SECRET_ARN").strip()
    migration = _env("LAUNCHCREW_MIGRATION_SECRET_ARN").strip()
    tls = _env("LAUNCHCREW_TLS_SECRET_ARN").strip()
    cert = _env("LAUNCHCREW_CERT_ARN").strip()
    for label, arn in (("master", master), ("runtime", runtime),
                       ("migration", migration), ("tls", tls)):
        _parse_arn(label, arn, "secretsmanager", account, region)
    _parse_arn("cert", cert, "acm", account, region)
    _check_distinct([("master", master), ("runtime", runtime),
                     ("migration", migration), ("tls", tls),
                     ("cert", cert)])
    host = _check_remote_host(_env("LAUNCHCREW_DB_HOST"))
    _tls_guard()
    return {"account": account, "region": region, "role": role,
            "master": master, "runtime": runtime,
            "migration": migration, "tls": tls, "cert": cert,
            "host": host, "dbname": EXPECTED_DB_NAME,
            "port": EXPECTED_DB_PORT,
            "runtime_user": EXPECTED_RUNTIME_USER,
            "migration_user": EXPECTED_MIGRATION_USER,
            "domain": EXPECTED_DOMAIN}


def _is_not_found_error(exc):
    try:
        resp = getattr(exc, "response", None)
        if isinstance(resp, dict):
            code = resp.get("Error", {}).get("Code", "")
            if code == "ResourceNotFoundException":
                return True
    except Exception:
        pass
    name = type(exc).__name__
    if name == "ResourceNotFoundException":
        return True
    return False


def _tags_to_dict(tags):
    out = {}
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, dict):
                key = item.get("Key", "")
                value = item.get("Value", "")
                if isinstance(key, str) and isinstance(value, str):
                    out[key] = value
    return out


def _check_owned_tags(label, tags):
    mapping = _tags_to_dict(tags)
    if mapping.get("Project", "") != EXPECTED_PROJECT:
        raise ValueError("invalid %s Project tag" % label)
    if mapping.get("Environment", "") != EXPECTED_ENV:
        raise ValueError("invalid %s Environment tag" % label)
    return mapping


def _make_clients(region):
    import boto3
    from botocore.config import Config
    cfg = Config(connect_timeout=5, read_timeout=10,
                 retries={'max_attempts': 1})
    sts = boto3.client("sts", region_name=region, config=cfg)
    sm = boto3.client("secretsmanager", region_name=region, config=cfg)
    acm = boto3.client("acm", region_name=region, config=cfg)
    return {"sts": sts, "sm": sm, "acm": acm}


def _validate_caller(sts_client, expected_account, expected_role):
    try:
        resp = sts_client.get_caller_identity()
    except Exception:
        raise ValueError("sts caller lookup failed")
    if not isinstance(resp, dict):
        raise ValueError("sts caller malformed")
    account = str(resp.get("Account", "")).strip()
    arn = str(resp.get("Arn", "")).strip()
    if account != expected_account:
        raise ValueError("sts account mismatch")
    if expected_account not in arn:
        raise ValueError("sts ARN account mismatch")
    if expected_role not in arn:
        raise ValueError("sts role mismatch")
    if not arn.startswith("arn:aws:"):
        raise ValueError("sts ARN malformed")
    return {"account": account, "arn": arn}


def _describe_secret_metadata(sm_client, arn, label):
    try:
        resp = sm_client.describe_secret(SecretId=arn)
    except Exception:
        raise ValueError("%s describe failed" % label)
    if not isinstance(resp, dict):
        raise ValueError("%s describe malformed" % label)
    returned = str(resp.get("ARN", "")).strip()
    if returned != arn:
        raise ValueError("%s describe ARN mismatch" % label)
    _check_owned_tags(label, resp.get("Tags", []))
    return resp


def _parse_time_value(value):
    import datetime
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(
            value, tz=datetime.timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty time")
        candidate = text.replace("Z", "+00:00")
        try:
            parsed = datetime.datetime.fromisoformat(candidate)
        except Exception:
            raise ValueError("unreadable time")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc)
    raise ValueError("unreadable time")


def _validate_acm_describe(acm_client, cert_arn, expected_domain, now=None):
    import datetime
    try:
        resp = acm_client.describe_certificate(CertificateArn=cert_arn)
    except Exception:
        raise ValueError("acm describe failed")
    if not isinstance(resp, dict):
        raise ValueError("acm describe malformed")
    cert = resp.get("Certificate", {})
    if not isinstance(cert, dict):
        raise ValueError("acm describe malformed")
    if str(cert.get("CertificateArn", "")).strip() != cert_arn:
        raise ValueError("acm ARN mismatch")
    if str(cert.get("DomainName", "")).strip() != expected_domain:
        raise ValueError("acm domain mismatch")
    sans = cert.get("SubjectAlternativeNames", [])
    if not isinstance(sans, list) or len(sans) != 1:
        raise ValueError("acm SAN must be exactly one name")
    if str(sans[0]).strip() != expected_domain:
        raise ValueError("acm SAN mismatch")
    if str(cert.get("Type", "")).strip() != "AMAZON_ISSUED":
        raise ValueError("acm type mismatch")
    if str(cert.get("Status", "")).strip() != "ISSUED":
        raise ValueError("acm status not issued")
    options = cert.get("Options", {})
    export = ""
    if isinstance(options, dict):
        export = str(options.get("Export", "")).strip()
        if not export:
            export = str(options.get("CertificateExport", "")).strip()
    if not export:
        export = str(cert.get("CertificateExport", "")).strip()
    if export != "ENABLED":
        raise ValueError("acm export not enabled")
    try:
        not_before = _parse_time_value(cert.get("NotBefore", ""))
        not_after = _parse_time_value(cert.get("NotAfter", ""))
    except ValueError:
        raise ValueError("acm time bounds missing")
    current = now
    if current is None:
        current = datetime.datetime.now(datetime.timezone.utc)
    if not (not_before <= current <= not_after):
        raise ValueError("acm cert outside validity time")
    return cert


def _validate_acm_tags(acm_client, cert_arn):
    try:
        resp = acm_client.list_tags_for_certificate(
            CertificateArn=cert_arn)
    except Exception:
        raise ValueError("acm tags lookup failed")
    if not isinstance(resp, dict):
        raise ValueError("acm tags malformed")
    _check_owned_tags("acm cert", resp.get("Tags", []))
    return resp


def _get_secret_string(sm_client, arn, label):
    try:
        resp = sm_client.get_secret_value(SecretId=arn)
    except Exception as exc:
        if _is_not_found_error(exc):
            return None, None
        raise ValueError("%s get failed" % label)
    if not isinstance(resp, dict):
        raise ValueError("%s get malformed" % label)
    returned = str(resp.get("ARN", "")).strip()
    if returned and returned != arn:
        raise ValueError("%s get ARN mismatch" % label)
    secret_string = resp.get("SecretString", "")
    if not isinstance(secret_string, str) or not secret_string:
        raise ValueError("%s get empty value" % label)
    if len(secret_string.encode("utf-8")) > SECRET_LIMIT_BYTES:
        raise ValueError("%s value over size bound" % label)
    return secret_string, str(resp.get("VersionId", "") or "")


def _canonical_secret_string(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    text = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False)
    if len(text.encode("utf-8")) > SECRET_LIMIT_BYTES:
        raise ValueError("canonical payload over size bound")
    return text


def _deterministic_token(purpose, secret_arn, canonical_payload):
    if not purpose or not secret_arn or not canonical_payload:
        raise ValueError("token inputs missing")
    payload_digest = hashlib.sha256(
        canonical_payload.encode("utf-8")).hexdigest()
    joined = "%s\n%s\n%s" % (purpose, secret_arn, payload_digest)
    token = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    if len(token) < 32 or len(token) > 64:
        raise ValueError("token length out of bounds")
    if not TOKEN_RE.match(token):
        raise ValueError("token charset invalid")
    return token


def _build_canonical_db_url(username, password, host, port, dbname):
    if not IDENT.match(username or ""):
        raise ValueError("invalid DB username")
    if not isinstance(password, str) or not password:
        raise ValueError("missing DB password")
    if len(password.encode("utf-8")) > 1024:
        raise ValueError("DB password over size bound")
    cleaned_host = _check_remote_host(host)
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError("invalid DB port")
    if not DBNAME.match(dbname or ""):
        raise ValueError("invalid DB name")
    user_enc = urllib.parse.quote(username, safe='')
    pass_enc = urllib.parse.quote(password, safe='')
    url = ("postgresql://%s:%s@%s:%d/%s?sslmode=verify-full"
           % (user_enc, pass_enc, cleaned_host, port, dbname))
    if len(url.encode("utf-8")) > 4096:
        raise ValueError("database-url over size bound")
    roundtrip = _parse_db_url_strict("database-url", url, username,
                                     cleaned_host, dbname)
    if roundtrip["password"] != password:
        raise ValueError("password roundtrip mismatch")
    return url


def _parse_db_url_strict(label, url, expected_user, expected_host,
                         expected_db):
    try:
        parts = urllib.parse.urlparse(url)
    except Exception:
        raise ValueError("%s is not a parseable URL" % label)
    if parts.scheme != "postgresql":
        raise ValueError("%s must use the postgresql scheme" % label)
    host = (parts.hostname or "").strip().lower()
    if not host or "," in host:
        raise ValueError("%s must name a single database host" % label)
    if host != expected_host:
        raise ValueError("%s host does not match the owned target"
                         % label)
    try:
        port = parts.port or 5432
    except ValueError:
        raise ValueError("%s has an invalid port" % label)
    if port < 1 or port > 65535:
        raise ValueError("%s has an invalid port" % label)
    netloc = parts.netloc
    if "@" not in netloc:
        raise ValueError("%s has no username" % label)
    userinfo = netloc.rsplit("@", 1)[0]
    if ":" not in userinfo:
        raise ValueError("%s has no password" % label)
    raw_user, raw_password = userinfo.split(":", 1)
    username = urllib.parse.unquote(raw_user)
    password = urllib.parse.unquote(raw_password)
    if username != expected_user:
        raise ValueError("%s username does not match the owned role"
                         % label)
    if not password:
        raise ValueError("%s has no password" % label)
    dbname = (parts.path or "").lstrip("/")
    if not dbname or "/" in dbname:
        raise ValueError("%s must name a single database" % label)
    if dbname != expected_db:
        raise ValueError("%s database does not match the owned target"
                         % label)
    try:
        items = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    except Exception:
        raise ValueError("%s has an unreadable query" % label)
    modes = []
    for key, value in items:
        lowered = key.strip().lower()
        if lowered == "sslmode":
            modes.append(value.strip().lower())
        elif lowered in _REJECTED_QUERY_KEYS:
            raise ValueError("%s must not carry rerouting query keys"
                             % label)
    if len(modes) != 1 or modes[0] != "verify-full":
        raise ValueError("%s requires exactly sslmode=verify-full"
                         % label)
    return {"host": host, "port": port, "dbname": dbname,
            "user": username, "password": password}


def _put_with_readback(sm_client, arn, canonical_payload, token, label):
    try:
        resp = sm_client.put_secret_value(
            SecretId=arn, SecretString=canonical_payload,
            ClientRequestToken=token)
    except Exception:
        try:
            readback, _version = _get_secret_string(
                sm_client, arn, label)
        except Exception:
            raise ValueError("%s put ambiguous, readback failed" % label)
        if readback == canonical_payload:
            return "readback-equal"
        raise ValueError("%s put ambiguous, refusing new version"
                         % label)
    if not isinstance(resp, dict):
        raise ValueError("%s put malformed" % label)
    returned = str(resp.get("ARN", "")).strip()
    if returned and returned != arn:
        raise ValueError("%s put ARN mismatch" % label)
    version = str(resp.get("VersionId", "") or "").strip()
    if version and version != token:
        raise ValueError("%s put version mismatch" % label)
    return version or "put-ok"


def _generate_passphrase(length=32):
    if length < 4 or length > 128:
        raise ValueError("passphrase length out of bounds")
    alphabet = "".join(chr(code) for code in range(33, 127)
                       if chr(code) not in ("#", "$", "%"))
    return "".join(pysecrets.choice(alphabet) for _ in range(length))


def _split_pem_blocks(pem_text):
    blocks = []
    current = []
    in_block = False
    for line in pem_text.splitlines():
        stripped = line.strip()
        if stripped == "-----BEGIN CERTIFICATE-----":
            in_block = True
            current = [stripped]
        elif stripped == "-----END CERTIFICATE-----" and in_block:
            current.append(stripped)
            blocks.append("\n".join(current) + "\n")
            current = []
            in_block = False
        elif in_block:
            current.append(stripped)
    return blocks


def _load_certificates(pem_text):
    from cryptography import x509
    blocks = _split_pem_blocks(pem_text)
    if not blocks:
        raise ValueError("no certificate PEM block")
    certs = []
    for block in blocks:
        try:
            certs.append(x509.load_pem_x509_certificate(
                block.encode("ascii")))
        except Exception:
            raise ValueError("malformed certificate PEM")
    return certs


def _cert_not_before(cert):
    moment = getattr(cert, "not_valid_before_utc", None)
    if moment is not None:
        return moment
    import datetime
    naive = cert.not_valid_before
    if naive.tzinfo is None:
        return naive.replace(tzinfo=datetime.timezone.utc)
    return naive


def _cert_not_after(cert):
    moment = getattr(cert, "not_valid_after_utc", None)
    if moment is not None:
        return moment
    import datetime
    naive = cert.not_valid_after
    if naive.tzinfo is None:
        return naive.replace(tzinfo=datetime.timezone.utc)
    return naive


def _validate_cert_san_time(cert, expected_domain, now=None):
    import datetime
    from cryptography import x509
    try:
        ext = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName)
    except Exception:
        raise ValueError("cert SAN missing")
    names = ext.value.get_values_for_type(x509.DNSName)
    if len(names) != 1 or names[0] != expected_domain:
        raise ValueError("cert SAN mismatch")
    current = now
    if current is None:
        current = datetime.datetime.now(datetime.timezone.utc)
    if not (_cert_not_before(cert) <= current <= _cert_not_after(cert)):
        raise ValueError("cert outside validity time")


def _validate_key_match(cert, private_key):
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    public = cert.public_key()
    private_public = private_key.public_key()
    if isinstance(public, rsa.RSAPublicKey):
        if not isinstance(private_public, rsa.RSAPublicKey):
            raise ValueError("cert key type mismatch")
        if (public.public_numbers().n !=
                private_public.public_numbers().n):
            raise ValueError("cert key mismatch")
        if (public.public_numbers().e !=
                private_public.public_numbers().e):
            raise ValueError("cert key mismatch")
        return
    if isinstance(public, ec.EllipticCurvePublicKey):
        if not isinstance(private_public, ec.EllipticCurvePublicKey):
            raise ValueError("cert key type mismatch")
        left = public.public_numbers()
        right = private_public.public_numbers()
        if (left.x != right.x or left.y != right.y or
                left.curve.name != right.curve.name):
            raise ValueError("cert key mismatch")
        return
    try:
        from cryptography.hazmat.primitives.asymmetric import (
            ed25519, ed448)
    except Exception:
        raise ValueError("unsupported cert key type")
    if isinstance(public, (ed25519.Ed25519PublicKey,
                           ed448.Ed448PublicKey)):
        left = public.public_bytes_raw()
        right = private_public.public_bytes_raw()
        if left != right:
            raise ValueError("cert key mismatch")
        return
    raise ValueError("unsupported cert key type")


def _validate_chain_shape(leaf, chain_certs, now=None):
    import datetime
    current = now
    if current is None:
        current = datetime.datetime.now(datetime.timezone.utc)
    ordered = [leaf] + list(chain_certs or [])
    for cert in ordered:
        if not (_cert_not_before(cert) <= current <=
                _cert_not_after(cert)):
            raise ValueError("chain cert outside validity time")
    for index in range(len(ordered) - 1):
        child = ordered[index]
        parent = ordered[index + 1]
        if child.issuer != parent.subject:
            raise ValueError("chain issuer mismatch")


def _canonical_tls_payload(certificate_pem, chain_pem, private_key):
    from cryptography.hazmat.primitives import serialization
    leaf_certs = _load_certificates(certificate_pem)
    if len(leaf_certs) != 1:
        raise ValueError("export leaf must be one certificate")
    chain_certs = []
    if chain_pem and chain_pem.strip():
        chain_certs = _load_certificates(chain_pem)
    ordered_pems = []
    for cert in leaf_certs + chain_certs:
        ordered_pems.append(cert.public_bytes(
            serialization.Encoding.PEM).decode("ascii"))
    cert_bundle = "".join(ordered_pems)
    key_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode("ascii")
    cert_b64 = base64.b64encode(cert_bundle.encode("ascii")).decode("ascii")
    key_b64 = base64.b64encode(key_pem.encode("ascii")).decode("ascii")
    payload = {"tls-cert-b64": cert_b64, "tls-key-b64": key_b64}
    return _canonical_secret_string(payload)


def _parse_stored_tls(stored_dict):
    if not isinstance(stored_dict, dict):
        raise ValueError("tls JSON must be an object")
    cert_b64 = stored_dict.get("tls-cert-b64", "")
    key_b64 = stored_dict.get("tls-key-b64", "")
    if not isinstance(cert_b64, str) or not cert_b64:
        raise ValueError("tls cert missing")
    if not isinstance(key_b64, str) or not key_b64:
        raise ValueError("tls key missing")
    try:
        cert_pem = base64.b64decode(cert_b64.encode("ascii"),
                                    validate=True).decode("ascii")
        key_pem = base64.b64decode(key_b64.encode("ascii"),
                                   validate=True).decode("ascii")
    except Exception:
        raise ValueError("tls base64 malformed")
    certs = _load_certificates(cert_pem)
    if not certs:
        raise ValueError("tls cert malformed")
    from cryptography.hazmat.primitives import serialization
    try:
        private_key = serialization.load_pem_private_key(
            key_pem.encode("ascii"), password=None)
    except Exception:
        raise ValueError("tls key malformed")
    return {"certs": certs, "leaf": certs[0],
            "chain": certs[1:], "key": private_key,
            "cert_pem": cert_pem, "key_pem": key_pem}


def _get_public_leaf(acm_client, cert_arn):
    try:
        resp = acm_client.get_certificate(CertificateArn=cert_arn)
    except Exception:
        raise ValueError("acm get leaf failed")
    if not isinstance(resp, dict):
        raise ValueError("acm get leaf malformed")
    leaf_pem = resp.get("Certificate", "")
    if not isinstance(leaf_pem, str) or not leaf_pem.strip():
        raise ValueError("acm get leaf empty")
    certs = _load_certificates(leaf_pem)
    if len(certs) != 1:
        raise ValueError("acm get leaf must be one certificate")
    return {"pem": leaf_pem, "cert": certs[0]}


def _populate_db_secret(sm_client, arn, label, expected_user, config):
    current, _version = _get_secret_string(sm_client, arn, label)
    if current is None:
        raise ValueError("%s missing value, refusing" % label)
    try:
        data = json.loads(current)
    except Exception:
        raise ValueError("%s JSON malformed, refusing overwrite"
                         % label)
    if not isinstance(data, dict):
        raise ValueError("%s JSON malformed, refusing overwrite"
                         % label)
    username = data.get("username", "")
    password = data.get("password", "")
    if username != expected_user:
        raise ValueError("%s username drift, rotation required"
                         % label)
    if not isinstance(password, str) or not password:
        raise ValueError("%s password missing, refusing" % label)
    _known_secrets.append(password)
    canonical_url = _build_canonical_db_url(
        expected_user, password, config["host"], config["port"],
        config["dbname"])
    _known_secrets.append(canonical_url)
    existing_url = data.get("database-url", "")
    if isinstance(existing_url, str) and existing_url:
        try:
            parsed = _parse_db_url_strict(
                label, existing_url, expected_user, config["host"],
                config["dbname"])
        except ValueError:
            raise ValueError("%s database-url malformed, refusing"
                             % label)
        if parsed["password"] != password:
            raise ValueError("%s password drift, rotation required"
                             % label)
        if existing_url != canonical_url:
            raise ValueError("%s endpoint drift, rotation required"
                             % label)
        expected = {"database-url": canonical_url,
                    "password": password, "username": expected_user}
        if data != expected:
            raise ValueError("%s payload drift, rotation required"
                             % label)
        return "reused"
    if "database-url" in data:
        raise ValueError("%s database-url malformed, refusing" % label)
    payload = {"database-url": canonical_url, "password": password,
               "username": expected_user}
    canonical = _canonical_secret_string(payload)
    token = _deterministic_token("%s-db-url-v1" % label, arn, canonical)
    _put_with_readback(sm_client, arn, canonical, token, label)
    return "populated"


def _populate_tls_secret(sm_client, acm_client, config, cert_detail,
                         now=None):
    from cryptography.hazmat.primitives import serialization
    label = "tls"
    arn = config["tls"]
    current, _version = _get_secret_string(sm_client, arn, label)
    if current is not None:
        try:
            data = json.loads(current)
        except Exception:
            raise ValueError("tls JSON malformed, refusing overwrite")
        stored = _parse_stored_tls(data)
        _validate_cert_san_time(stored["leaf"], config["domain"], now)
        _validate_key_match(stored["leaf"], stored["key"])
        _validate_chain_shape(stored["leaf"], stored["chain"], now)
        public = _get_public_leaf(acm_client, config["cert"])
        _validate_cert_san_time(public["cert"], config["domain"], now)
        stored_der = stored["leaf"].public_bytes(
            serialization.Encoding.DER)
        public_der = public["cert"].public_bytes(
            serialization.Encoding.DER)
        if stored_der != public_der:
            raise ValueError("tls cert drift, rotation required")
        expected_serial = str(cert_detail.get("Serial", "") or "")
        if expected_serial:
            stored_serial = format(stored["leaf"].serial_number, "X")
            normalized_expected = expected_serial.replace(":", "").upper()
            normalized_stored = stored_serial.replace(":", "").upper()
            if normalized_expected != normalized_stored:
                raise ValueError("tls cert drift, rotation required")
        return "reused"
    passphrase = _generate_passphrase(32)
    try:
        resp = acm_client.export_certificate(
            CertificateArn=config["cert"],
            Passphrase=passphrase.encode("ascii"))
    except Exception:
        raise ValueError("acm export failed")
    if not isinstance(resp, dict):
        raise ValueError("acm export malformed")
    certificate_pem = resp.get("Certificate", "")
    chain_pem = resp.get("CertificateChain", "")
    key_pem = resp.get("PrivateKey", "")
    if (not isinstance(certificate_pem, str) or
            not certificate_pem.strip()):
        raise ValueError("acm export leaf empty")
    if not isinstance(chain_pem, str):
        raise ValueError("acm export chain malformed")
    if not isinstance(key_pem, str) or not key_pem.strip():
        raise ValueError("acm export key empty")
    from cryptography.hazmat.primitives import serialization
    try:
        private_key = serialization.load_pem_private_key(
            key_pem.encode("ascii"),
            password=passphrase.encode("ascii"))
    except Exception:
        raise ValueError("tls key decrypt failed")
    leaf_certs = _load_certificates(certificate_pem)
    if len(leaf_certs) != 1:
        raise ValueError("export leaf must be one certificate")
    leaf = leaf_certs[0]
    chain_certs = []
    if chain_pem.strip():
        chain_certs = _load_certificates(chain_pem)
    _validate_cert_san_time(leaf, config["domain"], now)
    _validate_key_match(leaf, private_key)
    _validate_chain_shape(leaf, chain_certs, now)
    canonical = _canonical_tls_payload(certificate_pem, chain_pem,
                                       private_key)
    token = _deterministic_token("tls-material-v1", arn, canonical)
    _put_with_readback(sm_client, arn, canonical, token, label)
    return "populated"


def _verify_db_secret(sm_client, arn, label, expected_user, config):
    current, _version = _get_secret_string(sm_client, arn, label)
    if current is None:
        raise ValueError("%s missing value" % label)
    try:
        data = json.loads(current)
    except Exception:
        raise ValueError("%s JSON malformed" % label)
    if not isinstance(data, dict):
        raise ValueError("%s JSON malformed" % label)
    if data.get("username", "") != expected_user:
        raise ValueError("%s username mismatch" % label)
    password = data.get("password", "")
    if not isinstance(password, str) or not password:
        raise ValueError("%s password missing" % label)
    _known_secrets.append(password)
    canonical_url = _build_canonical_db_url(
        expected_user, password, config["host"], config["port"],
        config["dbname"])
    _known_secrets.append(canonical_url)
    existing = data.get("database-url", "")
    if existing != canonical_url:
        raise ValueError("%s database-url mismatch" % label)
    expected = {"database-url": canonical_url, "password": password,
                "username": expected_user}
    if data != expected:
        raise ValueError("%s payload mismatch" % label)
    return True


def _verify_tls_secret(sm_client, acm_client, config, cert_detail,
                       now=None):
    current, _version = _get_secret_string(sm_client, config["tls"],
                                           "tls")
    if current is None:
        raise ValueError("tls missing value")
    try:
        data = json.loads(current)
    except Exception:
        raise ValueError("tls JSON malformed")
    stored = _parse_stored_tls(data)
    _validate_cert_san_time(stored["leaf"], config["domain"], now)
    _validate_key_match(stored["leaf"], stored["key"])
    _validate_chain_shape(stored["leaf"], stored["chain"], now)
    public = _get_public_leaf(acm_client, config["cert"])
    _validate_cert_san_time(public["cert"], config["domain"], now)
    from cryptography.hazmat.primitives import serialization
    stored_der = stored["leaf"].public_bytes(serialization.Encoding.DER)
    public_der = public["cert"].public_bytes(serialization.Encoding.DER)
    if stored_der != public_der:
        raise ValueError("tls leaf mismatch")
    expected_serial = str(cert_detail.get("Serial", "") or "")
    if expected_serial:
        stored_serial = format(stored["leaf"].serial_number, "X")
        if (expected_serial.replace(":", "").upper() !=
                stored_serial.replace(":", "").upper()):
            raise ValueError("tls serial mismatch")
    return True


def do_populate(clients=None, now=None):
    config = _load_config()
    if clients is None:
        clients = _make_clients(config["region"])
    sts_client = clients["sts"]
    sm_client = clients["sm"]
    acm_client = clients["acm"]
    _validate_caller(sts_client, config["account"], config["role"])
    _ok("caller")
    _describe_secret_metadata(sm_client, config["master"], "master")
    _describe_secret_metadata(sm_client, config["runtime"], "runtime")
    _describe_secret_metadata(sm_client, config["migration"],
                              "migration")
    _describe_secret_metadata(sm_client, config["tls"], "tls")
    _ok("secret-metadata")
    cert_detail = _validate_acm_describe(acm_client, config["cert"],
                                         config["domain"], now)
    _validate_acm_tags(acm_client, config["cert"])
    _ok("acm-metadata")
    runtime_result = _populate_db_secret(sm_client, config["runtime"],
                                         "runtime",
                                         config["runtime_user"], config)
    _ok("runtime-%s" % runtime_result)
    migration_result = _populate_db_secret(
        sm_client, config["migration"], "migration",
        config["migration_user"], config)
    _ok("migration-%s" % migration_result)
    tls_result = _populate_tls_secret(sm_client, acm_client, config,
                                      cert_detail, now)
    _ok("tls-%s" % tls_result)
    print("populate-prereqs: POPULATE COMPLETE runtime=%s migration=%s "
          "tls=%s" % (runtime_result, migration_result, tls_result),
          flush=True)
    return 0


def do_verify_material(clients=None, now=None):
    config = _load_config()
    if clients is None:
        clients = _make_clients(config["region"])
    sts_client = clients["sts"]
    sm_client = clients["sm"]
    acm_client = clients["acm"]
    _validate_caller(sts_client, config["account"], config["role"])
    _ok("caller")
    _describe_secret_metadata(sm_client, config["runtime"], "runtime")
    _describe_secret_metadata(sm_client, config["migration"],
                              "migration")
    _describe_secret_metadata(sm_client, config["tls"], "tls")
    _ok("secret-metadata")
    cert_detail = _validate_acm_describe(acm_client, config["cert"],
                                         config["domain"], now)
    _validate_acm_tags(acm_client, config["cert"])
    _ok("acm-metadata")
    _verify_db_secret(sm_client, config["runtime"], "runtime",
                      config["runtime_user"], config)
    _ok("runtime-ready")
    _verify_db_secret(sm_client, config["migration"], "migration",
                      config["migration_user"], config)
    _ok("migration-ready")
    _verify_tls_secret(sm_client, acm_client, config, cert_detail, now)
    _ok("tls-ready")
    print("populate-prereqs: VERIFY COMPLETE runtime ready, migration "
          "ready, tls ready", flush=True)
    return 0


def main(argv):
    if len(argv) != 2 or argv[1] not in ("--populate",
                                        "--verify-material"):
        print("usage: populate_prereqs.py "
              "[--populate|--verify-material]", flush=True)
        return 2
    try:
        if argv[1] == "--populate":
            return do_populate()
        return do_verify_material()
    except ValueError as exc:
        return _fail("config", str(exc))
    except Exception:
        return _fail("internal")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
