"""Actual offline crypto tests in RAM with the pinned backend.

No test contacts AWS, the network, or the filesystem for key material.
All certificates and keys are synthetic, generated in RAM with the real
third party cryptography backend, and are never user keys. Decrypt uses
cryptography because Python stdlib cannot decrypt PKCS8; no mocked
crypto counts as proof. Failures must never print PEM, key, passphrase,
or payload bytes, and the provisioner path writes no PEM files.

These tests require the deploy-only lock
(containers/bootstrap-deploy-requirements.lock with cryptography==50.0.2).
The host installs that lock isolated after the terminal and reruns. When
the backend is missing the tests skip honestly with that requirement;
a skip there means missing deploy deps, not a pass.
"""
import base64
import contextlib
import datetime
import importlib.util
import io
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "populate_prereqs.py"
DOMAIN = "launchcrew.summitsingh.com"

try:
    import cryptography  # noqa: F401
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    from cryptography.x509.oid import NameOID
    HAS_CRYPTO = True
except Exception:
    HAS_CRYPTO = False


def load_script():
    spec = importlib.util.spec_from_file_location("populate_prereqs_crypto",
                                                  SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PP = load_script()
REQUIRES = "requires deploy-only cryptography==50.0.2, host installs " \
    "isolated lock after terminal"


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _ca_pair(now=None):
    now = now or _now()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,
                                         "synthetic-test-ca")])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True,
                                                 path_length=0),
                           critical=True)
            .sign(key, hashes.SHA256()))
    return key, cert


def _leaf_cert(ca_key, ca_cert, leaf_key, domain=DOMAIN,
               sans=None, days_before=1, days_after=335,
               now=None):
    now = now or _now()
    if sans is None:
        sans = [domain]
    builder = (x509.CertificateBuilder()
               .subject_name(x509.Name([x509.NameAttribute(
                   NameOID.COMMON_NAME, "synthetic-test-leaf")]))
               .issuer_name(ca_cert.subject)
               .public_key(leaf_key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(
                   now - datetime.timedelta(days=days_before))
               .not_valid_after(
                   now + datetime.timedelta(days=days_after)))
    if sans is not None:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(name) for name in sans]),
            critical=False)
    return builder.sign(ca_key, hashes.SHA256())


def _pem_cert(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _pem_key_unencrypted(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode("ascii")


def _pem_key_encrypted(key, passphrase):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(
            passphrase.encode("ascii"))).decode("ascii")


@unittest.skipUnless(HAS_CRYPTO, REQUIRES)
class DecryptRoundtripTests(unittest.TestCase):
    def test_encrypted_pkcs8_decrypts_with_correct_passphrase(self):
        key = rsa.generate_private_key(public_exponent=65537,
                                       key_size=2048)
        phrase = "correct-phrase-9!&*()-_=+[]"
        encrypted = _pem_key_encrypted(key, phrase)
        self.assertIn("ENCRYPTED PRIVATE KEY", encrypted)
        loaded = serialization.load_pem_private_key(
            encrypted.encode("ascii"), password=phrase.encode("ascii"))
        self.assertEqual(
            loaded.private_numbers().public_numbers.n,
            key.private_numbers().public_numbers.n)

    def test_wrong_passphrase_fails_closed(self):
        key = rsa.generate_private_key(public_exponent=65537,
                                       key_size=2048)
        encrypted = _pem_key_encrypted(key, "right-phrase-1!ab")
        with self.assertRaises(ValueError):
            try:
                serialization.load_pem_private_key(
                    encrypted.encode("ascii"),
                    password=b"wrong-phrase-2!cd")
            except Exception:
                raise ValueError("decrypt failed")

    def test_export_ciphertext_varies_while_content_stays_fixed(self):
        key = rsa.generate_private_key(public_exponent=65537,
                                       key_size=2048)
        phrase = "stable-content-7!ab()[]{}"
        first = _pem_key_encrypted(key, phrase)
        second = _pem_key_encrypted(key, phrase)
        self.assertNotEqual(first, second)
        loaded_first = serialization.load_pem_private_key(
            first.encode("ascii"), password=phrase.encode("ascii"))
        loaded_second = serialization.load_pem_private_key(
            second.encode("ascii"), password=phrase.encode("ascii"))
        self.assertEqual(
            loaded_first.private_numbers().public_numbers.n,
            loaded_second.private_numbers().public_numbers.n)
        canonical_first = loaded_first.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        canonical_second = loaded_second.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        self.assertEqual(canonical_first, canonical_second)


@unittest.skipUnless(HAS_CRYPTO, REQUIRES)
class KeyMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        now = _now()
        cls.now = now
        ca_key, ca_cert = _ca_pair(now)
        cls.ca_key = ca_key
        cls.ca_cert = ca_cert
        leaf_key = rsa.generate_private_key(public_exponent=65537,
                                            key_size=2048)
        cls.leaf_key = leaf_key
        cls.leaf = _leaf_cert(ca_key, ca_cert, leaf_key, now=now)
        other = rsa.generate_private_key(public_exponent=65537,
                                         key_size=2048)
        cls.other_key = other

    def test_matching_key_passes(self):
        PP._validate_key_match(self.leaf, self.leaf_key)

    def test_mismatched_key_fails(self):
        with self.assertRaisesRegex(ValueError, "key mismatch"):
            PP._validate_key_match(self.leaf, self.other_key)

    def test_mismatched_type_fails(self):
        ec_key = ec.generate_private_key(ec.SECP256R1())
        with self.assertRaises(ValueError):
            PP._validate_key_match(self.leaf, ec_key)

    def test_ec_matching_key_passes(self):
        now = _now()
        ca_key, ca_cert = _ca_pair(now)
        leaf_key = ec.generate_private_key(ec.SECP256R1())
        leaf = _leaf_cert(ca_key, ca_cert, leaf_key, now=now)
        PP._validate_key_match(leaf, leaf_key)


@unittest.skipUnless(HAS_CRYPTO, REQUIRES)
class SanAndTimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        now = _now()
        cls.now = now
        ca_key, ca_cert = _ca_pair(now)
        cls.ca_key = ca_key
        cls.ca_cert = ca_cert

    def test_exact_single_san_passes(self):
        key = rsa.generate_private_key(public_exponent=65537,
                                       key_size=2048)
        leaf = _leaf_cert(self.ca_key, self.ca_cert, key,
                          now=self.now)
        PP._validate_cert_san_time(leaf, DOMAIN, self.now)

    def test_wrong_san_fails(self):
        key = rsa.generate_private_key(public_exponent=65537,
                                       key_size=2048)
        leaf = _leaf_cert(self.ca_key, self.ca_cert, key,
                          domain="other.example.test",
                          sans=["other.example.test"],
                          now=self.now)
        with self.assertRaisesRegex(ValueError, "SAN"):
            PP._validate_cert_san_time(leaf, DOMAIN, self.now)

    def test_extra_san_fails(self):
        key = rsa.generate_private_key(public_exponent=65537,
                                       key_size=2048)
        leaf = _leaf_cert(self.ca_key, self.ca_cert, key,
                          sans=[DOMAIN, "other.example.test"],
                          now=self.now)
        with self.assertRaisesRegex(ValueError, "SAN"):
            PP._validate_cert_san_time(leaf, DOMAIN, self.now)

    def test_missing_san_fails(self):
        now = self.now
        key = rsa.generate_private_key(public_exponent=65537,
                                       key_size=2048)
        leaf = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(
                    NameOID.COMMON_NAME, "synthetic-no-san")]))
                .issuer_name(self.ca_cert.subject)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=90))
                .sign(self.ca_key, hashes.SHA256()))
        with self.assertRaisesRegex(ValueError, "SAN"):
            PP._validate_cert_san_time(leaf, DOMAIN, now)

    def test_expired_cert_fails(self):
        key = rsa.generate_private_key(public_exponent=65537,
                                       key_size=2048)
        leaf = _leaf_cert(self.ca_key, self.ca_cert, key,
                          days_before=90, days_after=-1,
                          now=self.now)
        with self.assertRaisesRegex(ValueError, "validity"):
            PP._validate_cert_san_time(leaf, DOMAIN, self.now)

    def test_not_yet_valid_fails(self):
        key = rsa.generate_private_key(public_exponent=65537,
                                       key_size=2048)
        leaf = _leaf_cert(self.ca_key, self.ca_cert, key,
                          days_before=-1, days_after=90,
                          now=self.now)
        with self.assertRaisesRegex(ValueError, "validity"):
            PP._validate_cert_san_time(leaf, DOMAIN, self.now)


@unittest.skipUnless(HAS_CRYPTO, REQUIRES)
class ChainTests(unittest.TestCase):
    def test_valid_chain_passes(self):
        now = _now()
        ca_key, ca_cert = _ca_pair(now)
        leaf_key = rsa.generate_private_key(public_exponent=65537,
                                            key_size=2048)
        leaf = _leaf_cert(ca_key, ca_cert, leaf_key, now=now)
        PP._validate_chain_shape(leaf, [ca_cert], now)

    def test_issuer_mismatch_fails(self):
        now = _now()
        ca_key, ca_cert = _ca_pair(now)
        other_key, other_cert = _ca_pair(now)
        leaf_key = rsa.generate_private_key(public_exponent=65537,
                                            key_size=2048)
        leaf = _leaf_cert(ca_key, ca_cert, leaf_key, now=now)
        with self.assertRaisesRegex(ValueError, "issuer"):
            PP._validate_chain_shape(leaf, [other_cert], now)

    def test_expired_chain_cert_fails(self):
        now = _now()
        old = now - datetime.timedelta(days=400)
        ca_key, ca_cert = _ca_pair(old)
        leaf_key = rsa.generate_private_key(public_exponent=65537,
                                            key_size=2048)
        leaf = _leaf_cert(ca_key, ca_cert, leaf_key, now=now)
        with self.assertRaisesRegex(ValueError, "validity"):
            PP._validate_chain_shape(leaf, [ca_cert], now)


@unittest.skipUnless(HAS_CRYPTO, REQUIRES)
class CanonicalStabilityTests(unittest.TestCase):
    def test_tls_payload_bytes_are_stable(self):
        now = _now()
        ca_key, ca_cert = _ca_pair(now)
        leaf_key = rsa.generate_private_key(public_exponent=65537,
                                            key_size=2048)
        leaf = _leaf_cert(ca_key, ca_cert, leaf_key, now=now)
        leaf_pem = _pem_cert(leaf)
        chain_pem = _pem_cert(ca_cert)
        first = PP._canonical_tls_payload(leaf_pem, chain_pem,
                                          leaf_key)
        second = PP._canonical_tls_payload(leaf_pem, chain_pem,
                                           leaf_key)
        self.assertEqual(first, second)
        payload = json.loads(first)
        self.assertEqual(sorted(payload.keys()),
                         ["tls-cert-b64", "tls-key-b64"])
        self.assertNotIn(" ", first)

    def test_stored_tls_roundtrips(self):
        now = _now()
        ca_key, ca_cert = _ca_pair(now)
        leaf_key = rsa.generate_private_key(public_exponent=65537,
                                            key_size=2048)
        leaf = _leaf_cert(ca_key, ca_cert, leaf_key, now=now)
        canonical = PP._canonical_tls_payload(_pem_cert(leaf),
                                              _pem_cert(ca_cert),
                                              leaf_key)
        stored = PP._parse_stored_tls(json.loads(canonical))
        PP._validate_key_match(stored["leaf"], stored["key"])
        PP._validate_cert_san_time(stored["leaf"], DOMAIN, now)
        PP._validate_chain_shape(stored["leaf"], stored["chain"],
                                 now)

    def test_malformed_pem_fails_closed(self):
        with self.assertRaises(ValueError):
            PP._load_certificates("not a pem block")

    def test_malformed_base64_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "base64"):
            PP._parse_stored_tls({"tls-cert-b64": "!!!not-base64!!!",
                                  "tls-key-b64": "!!!not-base64!!!"})

    def test_malformed_key_fails_closed(self):
        now = _now()
        _ca_key, ca_cert = _ca_pair(now)
        leaf_key = rsa.generate_private_key(public_exponent=65537,
                                            key_size=2048)
        now2 = _now()
        ca_key2, ca_cert2 = _ca_pair(now2)
        leaf = _leaf_cert(ca_key2, ca_cert2, leaf_key, now=now2)
        cert_b64 = base64.b64encode(
            _pem_cert(leaf).encode("ascii")).decode("ascii")
        key_b64 = base64.b64encode(b"not a key").decode("ascii")
        with self.assertRaisesRegex(ValueError, "key malformed"):
            PP._parse_stored_tls({"tls-cert-b64": cert_b64,
                                  "tls-key-b64": key_b64})

    def test_passphrase_never_contains_excluded_chars(self):
        for _ in range(25):
            phrase = PP._generate_passphrase(32)
            self.assertEqual(len(phrase), 32)
            for char in phrase:
                self.assertNotIn(char, ("#", "$", "%"))
                self.assertGreaterEqual(ord(char), 33)
                self.assertLessEqual(ord(char), 126)


class ProvisionerFileHygieneTests(unittest.TestCase):
    def test_no_tmp_pem_path_in_provisioner(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("/tmp", text)
        self.assertNotIn("rds-ca-bundle.pem", text)
        lowered = text.lower()
        self.assertNotIn("open(", lowered.replace(
            "load_pem", "loadX").replace("public_bytes", "publicX"))

    def test_no_em_dash_in_provisioner(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn(chr(0x2014), text)

    def test_synthetic_marker_in_crypto_tests(self):
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("synthetic", text.lower())
        self.assertIn("never user keys", text)


@unittest.skipUnless(HAS_CRYPTO, REQUIRES)
class CryptoPrivacyTests(unittest.TestCase):
    def test_crypto_failure_output_holds_no_private_bytes(self):
        now = _now()
        ca_key, ca_cert = _ca_pair(now)
        leaf_key = rsa.generate_private_key(public_exponent=65537,
                                            key_size=2048)
        leaf = _leaf_cert(ca_key, ca_cert, leaf_key,
                          sans=["other.example.test"], now=now)
        PP._known_secrets.clear()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                PP._validate_cert_san_time(leaf, DOMAIN, now)
                code = 0
            except ValueError as exc:
                code = PP._fail("tls-san", str(exc))
        text = out.getvalue()
        self.assertEqual(code, 1)
        self.assertNotIn("BEGIN CERTIFICATE", text)
        self.assertNotIn(_pem_cert(leaf)[:40], text)
        PP._known_secrets.clear()


if __name__ == "__main__":
    unittest.main()
