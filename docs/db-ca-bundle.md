# Database CA bundle: provenance, checksum, rotation, and region scope

Status: implemented in the image builds, verified by static tests only.
No live database TLS run exists yet, because the local demo database uses
trust auth without TLS. See the verification section below.

## What and where

`backend/store.py` requires `DATABASE_SSL_ROOTCERT` to point at an existing
CA bundle file when `LAUNCHCREW_DB_TLS_MODE=verify-full`. The Fargate API
and migration task definitions in `deploy/aws/fargate.yaml` set that
variable to `/app/rds-ca-bundle.pem`.

Both `containers/api.Containerfile` and `containers/migrate.Containerfile`
copy the exact vendored bundle `backend/assets/rds-us-east-1-bundle.pem`
to that path at build time, verify its SHA256 against the pinned value in
the Containerfile `ARG RDS_CA_SHA256` line, and set mode `644`. The bundle
holds only public roots, so every container user must be able to read it.
Private TLS keys stay at mode `600` under `/tmp/tls` and are never baked
into any image.

No private key, certificate signing request, `.env` value, or credential
is baked into either image. The bundle alone cannot authenticate anything;
it only lets the client verify the server chain.

## Provenance

The vendored file is the official regional Amazon RDS us-east-1 trust
bundle, downloaded over verified TLS from the official regional bundle URL:

- https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem

It holds exactly three certificates, all self-issued Amazon RDS roots
(subject equals issuer in each certificate):

- Amazon RDS us-east-1 Root CA RSA2048 G1
- Amazon RDS us-east-1 Root CA RSA4096 G1
- Amazon RDS us-east-1 Root CA ECC384 G1

These are the regional RDS roots listed in the RDS CA identifier table at
https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html
(rechecked Oct 28, 2026). They are NOT the Debian `ca-certificates`
Mozilla trust store and NOT the Amazon Trust Services web PKI roots
(such as Amazon Root CA 1): those general web roots do not sign RDS
server certificates, so a system trust store must never be substituted
for this bundle. The Debian `ca-certificates` package is still installed
in both images so the OS trust store stays available for ordinary outbound
HTTPS; it is kept separate and is never copied to `/app/rds-ca-bundle.pem`.

## Checksum

Pinned SHA256 of `backend/assets/rds-us-east-1-bundle.pem`:

- b1711d12bae51838581281e23b6cb97b1074016873b4dafc80ed14002462dd77

The same digest is pinned in the `ARG RDS_CA_SHA256` line of both
Containerfiles, and each image build fails when
`sha256sum -c` against `/app/rds-ca-bundle.pem` does not match.
`backend/tests/test_db_ca_bundle.py` re-checks the vendored file hash,
the exact three self-issued root names by DER parse, and the
Containerfile copy plus pin lines, without any AWS call.

## Rotation

- Routine refresh: an explicitly reviewed fetch of the official regional
  bundle URL above over verified TLS, then `sha256sum` of the download,
  then review of the new digest before updating the vendored file and both
  `ARG RDS_CA_SHA256` pins. Never treat a root or bundle URL as an
  automatic mutable value: every refresh is a reviewed rebuild.
- RDS CA rotation: when the database CA rotates, fetch and verify as
  above, update the vendored file and pins, rebuild both images, redeploy
  the migration task first, then the API task. No application code or
  configuration change is needed, because the path and the verification
  mode are unchanged.
- Emergency swap: if a root must be removed before a rebuild is possible,
  provisioning must supply the replacement bundle by another reviewed
  path. Do not weaken `LAUNCHCREW_DB_TLS_MODE` to work around rotation;
  `backend/store.py` fails closed and must stay that way.

## Region scope

This bundle serves us-east-1 only, which is the current cost plan region.
It does not cover other regions: do not claim other regions work. A
different region needs its own official regional bundle URL with its own
separately verified hash and pin, or the official global bundle with its
own separately verified hash, chosen explicitly and documented here; the
pinned digest above must never be reused for a different file.

## Verification

Static tests in `backend/tests/test_db_ca_bundle.py` check the vendored
hash, the three self-issued root names, both Containerfiles (exact copy,
hash pin, mode, no system-store substitution, no key material), the
Fargate environment values, the fail-closed store behavior, and the
absence of baked-in key material. They do not prove a live TLS handshake.
A live run still must show, against the real database, that the API and
migration tasks connect with `verify-full` and refuse an invalid
certificate. The local trust-auth database cannot prove that, so that
check stays an open deployment gate.

## Boundaries kept by this change

- Photos stay out of every image: this change adds no `COPY` of photo
  material, and `.containerignore` and `.dockerignore` still exclude
  `demo_photos` and image suffixes, checked by
  `backend/tests/test_container_boundary.py`.
- No waiver: `backend/store.py` enforcement is unchanged and now also
  refuses effective-destination overrides (`host`, `hostaddr`,
  `service`, `servicefile`, multi-host, single or duplicate
  `sslrootcert` query parameters) plus ambient `PGHOST`, `PGHOSTADDR`,
  `PGSERVICE`, and `PGSERVICEFILE` routing variables. A missing bundle
  file still fails closed at startup.
- No AWS calls, no DNS, no secrets, no push are part of this change.
