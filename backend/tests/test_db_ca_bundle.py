"""Official RDS CA bundle: vendored public roots in API and migration images.

Static wiring plus fail-closed store behavior. No live database, no AWS,
no private key material, no photo fixtures. The bundle path checked here
must match the Fargate task definitions, which set
DATABASE_SSL_ROOTCERT=/app/rds-ca-bundle.pem with
LAUNCHCREW_DB_TLS_MODE=verify-full.

The bundle is the official regional Amazon RDS us-east-1 trust bundle:
three SELF-ISSUED Amazon RDS roots, not the Debian Mozilla trust store and
not Amazon Trust Services web PKI roots. Provenance:
https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html
(table RDS CA identifiers and regional bundles), bundle URL
https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem.
"""
import base64
import hashlib
import re
from pathlib import Path

import pytest

from backend import store

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "backend" / "assets" / "rds-us-east-1-bundle.pem"
API_IMAGE = ROOT / "containers" / "api.Containerfile"
MIGRATE_IMAGE = ROOT / "containers" / "migrate.Containerfile"
FARGATE = ROOT / "deploy" / "aws" / "fargate.yaml"
DOC = ROOT / "docs" / "db-ca-bundle.md"
BUNDLE_PATH = "/app/rds-ca-bundle.pem"
PINNED_SHA256 = "b1711d12bae51838581281e23b6cb97b1074016873b4dafc80ed14002462dd77"
EXPECTED_ROOT_CNS = frozenset({
    "Amazon RDS us-east-1 Root CA RSA2048 G1",
    "Amazon RDS us-east-1 Root CA RSA4096 G1",
    "Amazon RDS us-east-1 Root CA ECC384 G1",
})

def _read(path):
    return path.read_text(encoding="utf-8")


def _pem_blocks():
    text = _read(ASSET)
    blocks = [block for block in text.split("-----END CERTIFICATE-----") if "BEGIN CERTIFICATE" in block]
    return [block + "-----END CERTIFICATE-----\n" for block in blocks]


def test_vendored_bundle_matches_pinned_hash():
    digest = hashlib.sha256(ASSET.read_bytes()).hexdigest()
    assert digest == PINNED_SHA256


def _read_tlv(buf, pos):
    # Minimal DER reader: enough to walk Certificate/tbsCertificate/Name.
    tag = buf[pos]
    pos += 1
    length = buf[pos]
    pos += 1
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(buf[pos:pos + count], "big")
        pos += count
    return tag, bytes(buf[pos:pos + length]), pos + length


def _cert_issuer_subject_equal(cert_der):
    # Certificate ::= SEQUENCE { tbsCertificate, signatureAlgorithm, signatureValue }.
    # tbsCertificate children: [0] version?, serial INTEGER, signature SEQUENCE,
    # issuer Name, validity SEQUENCE, subject Name, ...
    assert cert_der[0] == 0x30
    _, outer, _ = _read_tlv(cert_der, 0)
    _, tbs, _ = _read_tlv(outer, 0)
    children = []
    pos = 0
    while pos < len(tbs):
        tag, value, pos = _read_tlv(tbs, pos)
        children.append((tag, value))
    index = 0
    if children[0][0] == 0xA0:
        index = 1
    assert children[index][0] == 0x02  # serialNumber INTEGER
    assert children[index + 1][0] == 0x30  # signature SEQUENCE
    issuer = children[index + 2][1]
    subject = children[index + 4][1]
    return issuer == subject, issuer


def _name_common_names(name_der):
    # AttributeTypeAndValue with OID 2.5.4.3 (commonName); the value TLV follows.
    found = []
    for match in re.finditer(b"\x06\x03\x55\x04\x03", name_der):
        _, value, _ = _read_tlv(name_der, match.end())
        found.append(value.decode("utf-8"))
    return found


def test_vendored_bundle_holds_exactly_three_self_issued_rds_roots():
    blocks = _pem_blocks()
    assert len(blocks) == 3
    seen = set()
    for block in blocks:
        body = "".join(
            line.strip() for line in block.splitlines() if "CERTIFICATE" not in line)
        cert_der = base64.b64decode(body)
        self_issued, issuer = _cert_issuer_subject_equal(cert_der)
        assert self_issued
        common_names = _name_common_names(issuer)
        assert len(common_names) == 1
        assert common_names[0] in EXPECTED_ROOT_CNS
        seen.add(common_names[0])
    assert seen == EXPECTED_ROOT_CNS


def test_vendored_bundle_is_not_a_system_trust_store():
    # A Mozilla-sized store would dwarf three roots; the pinned bundle is small
    # and holds exactly three certificates (count pinned in the root test above).
    # Human-readable root names live inside the DER, checked by the DER test,
    # not as plaintext in the PEM body.
    assert ASSET.stat().st_size < 8192
    assert len(_pem_blocks()) == 3


def test_api_image_copies_exact_vendored_bundle_with_hash_pin():
    text = _read(API_IMAGE)
    assert "COPY backend/assets/rds-us-east-1-bundle.pem /app/rds-ca-bundle.pem" in text
    assert "ARG RDS_CA_SHA256=" + PINNED_SHA256 in text
    assert "sha256sum -c" in text
    assert "chmod 644" in text
    assert "USER 10001:10001" in text
    assert "api-entrypoint.sh" in text
    # The OS trust store is kept for ordinary outbound HTTPS only; it is
    # never substituted for the RDS bundle at the database path.
    assert "cp /etc/ssl/certs/ca-certificates.crt /app/rds-ca-bundle.pem" not in text
    assert "Amazon Trust Services roots that sign RDS" not in text


def test_migrate_image_copies_exact_vendored_bundle_with_hash_pin():
    text = _read(MIGRATE_IMAGE)
    assert "COPY backend/assets/rds-us-east-1-bundle.pem /app/rds-ca-bundle.pem" in text
    assert "ARG RDS_CA_SHA256=" + PINNED_SHA256 in text
    assert "sha256sum -c" in text
    assert "chmod 644" in text
    assert "USER 10001:10001" in text
    assert 'CMD ["/opt/venv/bin/alembic", "upgrade", "head"]' in text
    assert "uvicorn" not in text.lower()
    assert "cp /etc/ssl/certs/ca-certificates.crt /app/rds-ca-bundle.pem" not in text
    assert "Amazon Trust Services roots that sign RDS" not in text


def test_no_private_key_material_in_images():
    for path in (API_IMAGE, MIGRATE_IMAGE):
        text = _read(path)
        for token in (".key", "TLS_KEY", "PRIVATE KEY", "OPENSSH PRIVATE"):
            assert token not in text, (path.name, token)
        lowered = text.lower()
        assert "tls-key-b64" not in lowered, path.name
        assert "tls-cert-b64" not in lowered, path.name


def test_fargate_api_and_migration_point_at_bundled_ca():
    text = _read(FARGATE)
    assert text.count("DATABASE_SSL_ROOTCERT") >= 2
    assert text.count(BUNDLE_PATH) >= 2
    assert text.count("LAUNCHCREW_DB_TLS_MODE") >= 2
    assert "verify-full" in text


def test_docs_cover_provenance_checksum_rotation_and_region_scope():
    text = _read(DOC).lower()
    for term in ("provenance", "checksum", "rotation",
                 "truststore.pki.rds.amazonaws.com",
                 "us-east-1",
                 BUNDLE_PATH, "644"):
        assert term in text, term
    assert "amazon trust services roots that sign rds" not in text
    assert PINNED_SHA256 in _read(DOC)


def test_photos_not_copied_into_tls_images():
    for path in (API_IMAGE, MIGRATE_IMAGE):
        text = _read(path)
        assert "demo_photos" not in text, path.name
        assert ".heic" not in text, path.name
    for name in (".containerignore", ".dockerignore"):
        assert "demo_photos" in _read(ROOT / name), name


def _env(monkeypatch, mode=None, rootcert=None):
    if mode is None:
        monkeypatch.delenv("LAUNCHCREW_DB_TLS_MODE", raising=False)
    else:
        monkeypatch.setenv("LAUNCHCREW_DB_TLS_MODE", mode)
    if rootcert is None:
        monkeypatch.delenv("DATABASE_SSL_ROOTCERT", raising=False)
    else:
        monkeypatch.setenv("DATABASE_SSL_ROOTCERT", rootcert)


def test_verify_full_requires_existing_bundle_file(monkeypatch):
    missing = str(ROOT / "does-not-exist-ca.pem")
    _env(monkeypatch, mode="verify-full", rootcert=missing)
    url = "postgresql://user@dbremote:5432/launchcrew?sslmode=verify-full"
    with pytest.raises(ValueError, match="CA bundle"):
        store._require_verified_db_tls(url)


def test_verify_full_rejects_missing_sslmode(monkeypatch, tmp_path):
    bundle = tmp_path / "rds-ca-bundle.pem"
    bundle.write_text("public-roots-only", encoding="utf-8")
    _env(monkeypatch, mode="verify-full", rootcert=str(bundle))
    url = "postgresql://user@dbremote:5432/launchcrew"
    with pytest.raises(ValueError, match="sslmode=verify-full"):
        store._require_verified_db_tls(url)


def test_verify_full_accepts_real_vendored_bundle(monkeypatch):
    _env(monkeypatch, mode="verify-full", rootcert=str(ASSET))
    url = "postgresql://user@dbremote:5432/launchcrew?sslmode=verify-full"
    store._require_verified_db_tls(url)


def test_local_mode_rejects_nonlocal_host(monkeypatch):
    _env(monkeypatch, mode="local")
    url = "postgresql://user@dbremote:5432/launchcrew"
    with pytest.raises(ValueError, match="local"):
        store._require_verified_db_tls(url)


def test_local_mode_allows_compose_host(monkeypatch):
    _env(monkeypatch, mode="local")
    url = "postgresql://postgres@db:5432/launchcrew"
    store._require_verified_db_tls(url)


def test_unknown_mode_rejected(monkeypatch):
    _env(monkeypatch, mode="waive")
    url = "postgresql://postgres@db:5432/launchcrew"
    with pytest.raises(ValueError, match="verify-full, local"):
        store._require_verified_db_tls(url)


def test_engine_wires_sslrootcert_connect_arg(monkeypatch, tmp_path):
    bundle = tmp_path / "rds-ca-bundle.pem"
    bundle.write_text("public-roots-only", encoding="utf-8")
    _env(monkeypatch, mode="verify-full", rootcert=str(bundle))
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user@dbremote:5432/launchcrew?sslmode=verify-full",
    )
    seen = {}

    def fake_create_engine(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return "engine-sentinel"

    monkeypatch.setattr(store, "create_engine", fake_create_engine)
    assert store.engine.__wrapped__() == "engine-sentinel"
    assert seen["kwargs"]["connect_args"] == {"sslrootcert": str(bundle)}


def test_engine_refuses_effective_destination_override(monkeypatch, tmp_path):
    bundle = tmp_path / "rds-ca-bundle.pem"
    bundle.write_text("public-roots-only", encoding="utf-8")
    _env(monkeypatch, mode="verify-full", rootcert=str(bundle))
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user@localhost:5432/launchcrew?sslmode=verify-full&host=dbremote",
    )

    def fake_create_engine(url, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("create_engine must not run when the guard refuses")

    monkeypatch.setattr(store, "create_engine", fake_create_engine)
    with pytest.raises(ValueError, match="host"):
        store.engine.__wrapped__()
